import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from webui import bilibili, douyin, pipeline
from webui.job_manager import Job


class PlatformParsingTests(unittest.TestCase):
    def test_bilibili_parses_bv_and_av_ids(self):
        self.assertEqual(
            {"bvid": "BV1rXga6pEEu"},
            bilibili.parse_video_id("https://www.bilibili.com/video/BV1rXga6pEEu/"),
        )
        self.assertEqual(
            {"aid": 123456},
            bilibili.parse_video_id("https://www.bilibili.com/video/av123456"),
        )

    def test_bilibili_412_is_classified_without_identical_retry(self):
        calls = []

        def fail(request, timeout=0):
            calls.append(request.full_url)
            raise urllib.error.HTTPError(request.full_url, 412, "", {}, io.BytesIO())

        with mock.patch.object(bilibili.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(bilibili.BilibiliError) as raised:
                bilibili._request_json("/test", {"bvid": "BV1rXga6pEEu"})
        self.assertEqual("BILI_HTTP_412", raised.exception.kind)
        self.assertEqual(1, len(calls))

    def test_stream_selection_prefers_bandwidth_and_h264_at_equal_size(self):
        audio = bilibili.select_audio_stream(
            {"audio": [{"id": 1, "bandwidth": 64}, {"id": 2, "bandwidth": 128}]}
        )
        self.assertEqual(2, audio["id"])
        video = bilibili.select_video_stream(
            {"video": [
                {"id": 1, "width": 1920, "height": 1080, "codecs": "hev1", "bandwidth": 9},
                {"id": 2, "width": 1920, "height": 1080, "codecs": "avc1", "bandwidth": 8},
            ]}
        )
        self.assertEqual(2, video["id"])

    def test_douyin_extracts_share_url_and_id(self):
        text = "复制打开抖音 https://v.douyin.com/abc123/ 直接观看"
        self.assertEqual("https://v.douyin.com/abc123/", douyin.extract_url(text))
        self.assertEqual("7654321", douyin.parse_aweme_id("https://www.douyin.com/video/7654321"))

    def test_douyin_refreshes_expired_signed_audio_once(self):
        info = {
            "audio": {"urls": ["https://cdn.example/audio"], "size": 10},
            "video": {},
            "title": "demo",
        }
        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch.object(douyin, "inspect_media", side_effect=[info, info]) as inspect, \
             mock.patch.object(
                 douyin,
                 "download_stream",
                 side_effect=[
                     douyin.DouyinError("expired", status=403),
                     Path(temp_dir) / "audio.m4a",
                 ],
             ):
            path, metadata = douyin.acquire_audio("https://www.douyin.com/video/1", Path(temp_dir))
        self.assertEqual(2, inspect.call_count)
        self.assertTrue(metadata["signed_url_refreshed"])
        self.assertEqual("audio.m4a", path.name)


class PipelineRoutingTests(unittest.TestCase):
    def make_job(self, temp_dir, url):
        return Job(url=url, job_dir=temp_dir, allow_enrichment=False)

    def test_default_cookie_mode_never_reads_live_chrome(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args, mode = pipeline._cookie_args("douyin")
        self.assertEqual([], args)
        self.assertEqual("none", mode)

    def test_legacy_gb18030_config_is_supported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / ".video2doc"
            config_dir.mkdir()
            (config_dir / "config.json").write_bytes(
                json.dumps({"label": "中文配置"}, ensure_ascii=False).encode("gb18030")
            )
            with mock.patch.object(Path, "home", return_value=Path(temp_dir)):
                self.assertEqual("中文配置", pipeline._read_config()["label"])

    def test_bilibili_transcription_uses_direct_audio_before_full_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = self.make_job(temp_dir, "https://www.bilibili.com/video/BV1rXga6pEEu/")
            audio = Path(temp_dir) / "raw" / "audio.m4a"
            audio.parent.mkdir()
            audio.write_bytes(b"media")
            transcript = {"text": "测试文稿", "segments": []}
            with mock.patch.object(pipeline, "_download_subtitles_only", return_value=False), \
                 mock.patch.object(pipeline, "acquire_transcription_audio", return_value=audio) as acquire, \
                 mock.patch.object(pipeline, "download_video", side_effect=AssertionError("full video")), \
                 mock.patch.object(pipeline, "transcribe", return_value=transcript), \
                 mock.patch.object(pipeline, "export_formats", return_value=[]):
                pipeline.run_transcribe_pipeline(job)
        acquire.assert_called_once_with(job)
        self.assertEqual("done", job.status)

    def test_bilibili_full_download_prefers_public_dash_without_cookie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = self.make_job(temp_dir, "https://www.bilibili.com/video/BV1rXga6pEEu/")
            merged = Path(temp_dir) / "raw" / "video.mp4"
            with mock.patch.object(pipeline, "_cookie_args", return_value=([], "none")), \
                 mock.patch.object(bilibili, "acquire_av", return_value=(Path("v"), Path("a"), {})), \
                 mock.patch.object(pipeline, "_merge_streams", return_value=merged), \
                 mock.patch.object(pipeline, "validate_media", return_value={"bytes": 1}), \
                 mock.patch.object(pipeline, "_run_ytdlp", side_effect=AssertionError("yt-dlp")):
                result = pipeline._download_bilibili_video(job, job.url, Path(temp_dir) / "raw")
        self.assertEqual(merged, result)
        self.assertEqual("bilibili.public_api_dash", job.download_strategy)

    def test_douyin_full_download_order_starts_with_mobile_ssr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = self.make_job(temp_dir, "https://www.douyin.com/video/1")
            video = Path(temp_dir) / "raw" / "video.mp4"
            with mock.patch.object(douyin, "acquire_muxed", return_value=(video, {})) as ssr, \
                 mock.patch.object(douyin, "acquire_av", side_effect=AssertionError("playwright")), \
                 mock.patch.object(pipeline, "validate_media", return_value={"bytes": 1}):
                result = pipeline._download_douyin_video(job, job.url, Path(temp_dir) / "raw")
        ssr.assert_called_once()
        self.assertEqual(video, result)
        self.assertEqual("douyin.mobile_ssr_mp4", job.download_strategy)

    def test_download_trace_strips_query_and_sensitive_details(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = self.make_job(temp_dir, "https://example.com/video?token=secret")
            pipeline._record_attempt(
                job,
                "test.route",
                "success",
                details={"url": "secret", "cookie": "secret", "bytes": 42},
            )
            trace = json.loads(
                (Path(temp_dir) / "raw" / "download.trace.json").read_text(encoding="utf-8")
            )
        self.assertEqual("https://example.com/video", trace["source"])
        self.assertEqual({"bytes": 42}, trace["attempts"][0]["details"])


if __name__ == "__main__":
    unittest.main()
