import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_setup, platform_utils
from webui import job_manager, pipeline
from webui.job_manager import Job


def make_job(temp_dir, **kwargs):
    kwargs.setdefault("allow_enrichment", False)
    return Job(job_dir=temp_dir, **kwargs)


class ConfigTests(unittest.TestCase):
    def test_bom_config_is_visible_to_pipeline_and_self_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / ".video2doc" / "config.json"
            config.parent.mkdir()
            config.write_bytes(b"\xef\xbb\xbf" + json.dumps({"doubao_api_key": "k"}).encode())
            with mock.patch.object(Path, "home", return_value=Path(temp_dir)), \
                    mock.patch.dict(os.environ, {"DOUBAO_API_KEY": ""}):
                self.assertEqual("k", pipeline._get_doubao_key())
                self.assertEqual("k", check_setup._get_doubao_key(check_setup._load_config()))
                self.assertEqual({"doubao_api_key": "k"}, platform_utils.load_user_config())


class PipelineOutcomeTests(unittest.TestCase):
    def test_raw_transcript_is_utf8_even_with_emoji(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, job_type="transcribe_local", formats=["txt"])
            audio = Path(temp_dir) / "raw" / "audio.mp3"
            audio.parent.mkdir(exist_ok=True)
            audio.write_bytes(b"audio")
            transcript = {"text": "测试🎬文稿", "segments": [{"start": 0, "end": 1, "text": "测试🎬文稿"}]}
            with mock.patch.object(pipeline, "transcribe", return_value=transcript):
                pipeline.run_local_pipeline(job, str(audio))
            self.assertEqual("done", job.status, job.error)
            raw = (Path(temp_dir) / "raw" / "tele_result.json").read_bytes().decode("utf-8")
            self.assertIn("🎬", raw)

    def test_download_pipeline_keeps_the_specific_failure_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, url="https://www.youtube.com/watch?v=x", job_type="download")
            error = pipeline.PipelineError("视频需要登录或当前账号无权访问。", code="AUTH_REQUIRED")
            with mock.patch.object(pipeline, "_run_ytdlp", side_effect=error):
                pipeline.run_download_pipeline(job)
            self.assertEqual("error", job.status)
            self.assertEqual("AUTH_REQUIRED", job.error_code)
            self.assertIn("需要登录", job.error)

    def test_local_video_without_extractable_audio_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, job_type="transcribe_local")
            video = Path(temp_dir) / "raw" / "uploaded-media.mp4"
            video.parent.mkdir(exist_ok=True)
            video.write_bytes(b"not a video")
            with mock.patch.object(pipeline, "extract_audio", return_value=False), \
                    mock.patch.object(pipeline, "transcribe", side_effect=AssertionError("asr")):
                pipeline.run_local_pipeline(job, str(video))
            self.assertEqual("AUDIO_EXTRACTION_FAILED", job.error_code)


class AcquisitionOrderTests(unittest.TestCase):
    def test_douyin_transcription_tries_browserless_share_mp4_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, url="https://www.douyin.com/video/1")
            video = Path(temp_dir) / "raw" / "video.mp4"
            with mock.patch.object(pipeline.douyin, "acquire_muxed",
                                   return_value=(video, {"title": "抖音标题", "duration": 12})) as ssr, \
                    mock.patch.object(pipeline.douyin, "acquire_audio",
                                      side_effect=AssertionError("playwright")), \
                    mock.patch.object(pipeline, "validate_media", return_value={"bytes": 1}):
                result = pipeline.acquire_transcription_audio(job)
            ssr.assert_called_once()
            self.assertEqual(video, result)
            self.assertEqual("douyin.mobile_ssr_mp4", job.download_strategy)
            self.assertEqual("抖音标题", job.title)

    def test_douyin_falls_back_to_playwright_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, url="https://www.douyin.com/video/1")
            audio = Path(temp_dir) / "raw" / "audio.m4a"
            with mock.patch.object(pipeline.douyin, "acquire_muxed",
                                   side_effect=pipeline.douyin.DouyinError("changed", kind="DOUYIN_SSR_CHANGED")), \
                    mock.patch.object(pipeline.douyin, "acquire_audio", return_value=(audio, {})), \
                    mock.patch.object(pipeline, "validate_media", return_value={"bytes": 1}):
                result = pipeline.acquire_transcription_audio(job)
            self.assertEqual(audio, result)
            self.assertEqual(["failed", "success"], [a["status"] for a in job.attempts])

    def test_youtube_transcription_uses_subtitles_then_audio_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, url="https://www.youtube.com/watch?v=x")
            audio = Path(temp_dir) / "raw" / "audio-source.webm"
            transcript = {"text": "hello world", "segments": []}
            with mock.patch.object(pipeline, "_download_subtitles_only", return_value=False) as subs, \
                    mock.patch.object(pipeline, "_run_ytdlp", return_value=audio) as ytdlp, \
                    mock.patch.object(pipeline, "prepare_asr_audio", return_value=audio), \
                    mock.patch.object(pipeline, "transcribe", return_value=transcript), \
                    mock.patch.object(pipeline, "export_formats", return_value=[]):
                pipeline.run_transcribe_pipeline(job)
            self.assertEqual("done", job.status, job.error)
            subs.assert_called_once_with(job, job.url, "youtube")
            self.assertEqual("bestaudio/best", ytdlp.call_args.kwargs["format_selector"])
            self.assertFalse(ytdlp.call_args.kwargs["require_video"])

    def test_subtitle_request_never_asks_for_every_language(self):
        self.assertNotIn("all", pipeline.SUBTITLE_LANGS.split(","))
        self.assertIn("-danmaku", pipeline.SUBTITLE_LANGS)
        self.assertIn("-live_chat", pipeline.SUBTITLE_LANGS)


class SubtitleTests(unittest.TestCase):
    def test_chinese_subtitles_rank_before_original_auto_captions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw = Path(temp_dir) / "raw"
            raw.mkdir()
            body = "1\n00:00:00,000 --> 00:00:01,000\n{}\n\n2\n00:00:01,000 --> 00:00:02,000\n{}\n"
            (raw / "subtitle.en-orig.srt").write_text(body.format("hello there", "general kenobi"), encoding="utf-8")
            (raw / "subtitle.zh-Hans.srt").write_text(body.format("你好，", "世界。"), encoding="utf-8")
            job = make_job(temp_dir)
            transcript = pipeline._try_subtitle_transcript(job)
        self.assertEqual("subtitle.zh-Hans.srt", transcript["_subtitle_source"])
        self.assertEqual("你好，世界。", transcript["text"])

    def test_rolling_auto_caption_lines_are_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            srt = Path(temp_dir) / "subtitle.en.srt"
            srt.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n<c>first line</c>\n\n"
                "2\n00:00:02,000 --> 00:00:04,000\nfirst line\nsecond line\n\n"
                "3\n00:00:04,000 --> 00:00:06,000\nsecond line\nthird line\n",
                encoding="utf-8")
            transcript = pipeline._parse_srt_to_transcript(srt)
        self.assertEqual("first line second line third line", transcript["text"])
        self.assertEqual(3, len(transcript["segments"]))

    def test_srt_timestamps_round_trip(self):
        self.assertEqual("01:02:03,450", pipeline._fmt_time(3723.45))
        self.assertEqual("00:00:01,000", pipeline._fmt_time(0.9996))


class DocumentTests(unittest.TestCase):
    def test_paragraphs_break_on_pauses_and_join_cjk_without_spaces(self):
        transcript = {"segments": [
            {"start": 0, "end": 1, "text": "第一句。"},
            {"start": 1, "end": 2, "text": "第二句。"},
            {"start": 6, "end": 7, "text": "停顿之后。"},
        ]}
        self.assertEqual(["第一句。第二句。", "停顿之后。"],
                         pipeline.transcript_paragraphs(transcript))

    def test_markdown_document_has_title_metadata_and_paragraphs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, url="https://www.bilibili.com/video/BV1", formats=["all"])
            job.title, job.duration, job.engine_used = "示例\n标题", "01:05", "doubao"
            transcript = {"text": "甲。乙。", "segments": [
                {"start": 0, "end": 1, "text": "甲。"}, {"start": 5, "end": 6, "text": "乙。"}]}
            files = pipeline.export_formats(job, transcript, {"summary": "摘要"})
            markdown = (Path(temp_dir) / "transcript.md").read_text(encoding="utf-8")
            data = json.loads((Path(temp_dir) / "transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(["transcript.md", "transcript.txt", "transcript.json", "transcript.srt"],
                         [item["file"] for item in files])
        self.assertTrue(markdown.startswith("# 示例 标题\n"))
        self.assertIn("时长：01:05", markdown)
        self.assertIn("> 摘要", markdown)
        self.assertIn("甲。\n\n乙。", markdown)
        self.assertEqual(2, data["total"])
        self.assertEqual("示例 标题", data["title"])

    def test_enrichment_excerpt_covers_whole_transcript_within_budget(self):
        text = "头" * 5000 + "中" * 5000 + "尾" * 5000
        excerpt = pipeline._enrichment_excerpt(text)
        self.assertLessEqual(len(excerpt.replace("\n……\n", "")), pipeline.ENRICH_CHAR_BUDGET)
        for marker in "头中尾":
            self.assertIn(marker, excerpt)
        self.assertEqual("短文本", pipeline._enrichment_excerpt("短文本"))

    def test_duration_format_supports_hours(self):
        self.assertEqual("01:05", pipeline._format_duration(65))
        self.assertEqual("1:01:05", pipeline._format_duration(3665))
        self.assertEqual("", pipeline._format_duration(None))


class EngineFailureMessageTests(unittest.TestCase):
    def test_engine_returning_no_text_is_explained(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = make_job(temp_dir, engine="whisper")
            with mock.patch.object(pipeline, "_transcribe_whisper", return_value={"text": "", "segments": []}):
                self.assertIsNone(pipeline.transcribe("missing.mp3", job))
        self.assertIn("未识别到任何文字", job.error)


class DoubaoPollingTests(unittest.TestCase):
    def test_polls_until_success_beyond_the_old_fixed_limit(self):
        statuses = ["20000001"] * 40 + ["20000000"]

        def response(status, body=b"{}"):
            resp = mock.MagicMock()
            resp.headers = {"X-Api-Status-Code": status}
            resp.read.return_value = body
            resp.__enter__.return_value = resp
            return resp

        done_body = json.dumps({"result": {"text": "好", "utterances": [
            {"start_time": 0, "end_time": 1000, "text": "好"}]}}).encode()
        responses = [response("20000000")] + [
            response(status, done_body if status == "20000000" else b"{}") for status in statuses]
        with tempfile.TemporaryDirectory() as temp_dir:
            audio = Path(temp_dir) / "audio_16k.mp3"
            audio.write_bytes(b"mp3")
            job = make_job(temp_dir)
            with mock.patch.object(pipeline, "_get_doubao_key", return_value="key"), \
                    mock.patch.object(pipeline, "_asr_timeout", return_value=600), \
                    mock.patch.object(pipeline.time, "sleep"), \
                    mock.patch.object(pipeline.urllib.request, "urlopen", side_effect=responses):
                result = pipeline._transcribe_doubao(audio, job)
        self.assertEqual("好", result["text"])
        self.assertEqual(1.0, result["segments"][0]["end"])


class JobPersistenceTests(unittest.TestCase):
    def test_history_survives_restart_and_running_jobs_are_marked_interrupted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            done = Job(job_id="donejob", job_dir=root / "donejob")
            done.status, done.title = "done", "完成的任务"
            done.save()
            running = Job(job_id="runjob", job_dir=root / "runjob")
            running.status = "transcribing"
            running.save()
            with mock.patch.dict(job_manager.jobs, {}, clear=True):
                self.assertEqual(2, job_manager.load_history(root))
                self.assertEqual("完成的任务", job_manager.get_job("donejob").title)
                interrupted = job_manager.get_job("runjob")
                self.assertEqual("error", interrupted.status)
                self.assertEqual("INTERRUPTED", interrupted.error_code)
            saved = json.loads((root / "runjob" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual("error", saved["status"])

    def test_mismatched_job_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "abc"
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({"id": "../evil"}), encoding="utf-8")
            with mock.patch.dict(job_manager.jobs, {}, clear=True):
                self.assertEqual(0, job_manager.load_history(temp_dir))

    def test_submit_runs_in_background_and_persists_final_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ok = Job(job_id="okjob", job_dir=Path(temp_dir) / "okjob")
            bad = Job(job_id="badjob", job_dir=Path(temp_dir) / "badjob")

            def succeed(job):
                job.status = "done"

            def crash(job):
                raise RuntimeError("boom")

            job_manager.submit(ok, succeed)
            job_manager.submit(bad, crash)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (ok.finished_at and bad.finished_at):
                time.sleep(0.02)
            self.assertEqual("done", ok.status)
            self.assertEqual("error", bad.status)
            self.assertIn("boom", bad.error)
            saved = json.loads((Path(temp_dir) / "badjob" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual("error", saved["status"])


if __name__ == "__main__":
    unittest.main()
