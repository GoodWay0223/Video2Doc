import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import video2doc
from webui import bilibili, illustrate, pipeline, server

from test_server_security import make_handler


class HotwordTests(unittest.TestCase):
    def test_parse_hotwords_splits_dedupes_and_limits(self):
        words = pipeline.parse_hotwords("京极彩, CEDEC，狸克、京极彩\n" + "长" * 31 + ";SE")
        self.assertEqual(["京极彩", "CEDEC", "狸克", "SE"], words)
        self.assertEqual(pipeline.MAX_HOTWORDS,
                         len(pipeline.parse_hotwords([f"w{i}" for i in range(500)])))

    def test_job_and_global_hotwords_are_merged_into_doubao_context(self):
        job = SimpleNamespace(hotwords=["京极彩"], title="讲座一｜CEDEC 2020")
        with mock.patch.object(pipeline, "_read_config", return_value={"hotwords": "狸克，京极彩"}):
            context = json.loads(pipeline._doubao_context(job))
        self.assertEqual([{"word": "京极彩"}, {"word": "狸克"}], context["hotwords"])
        self.assertIn("讲座一｜CEDEC 2020", context["context_data"][0]["text"])
        with mock.patch.object(pipeline, "_read_config", return_value={}):
            self.assertEqual("", pipeline._doubao_context(SimpleNamespace(hotwords=[], title="")))

    def test_doubao_submit_carries_corpus_context(self):
        captured = []

        def fake_urlopen(request, timeout=0):
            captured.append(request)
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.headers = {"X-Api-Status-Code": "20000000"}
            response.read.return_value = json.dumps(
                {"result": {"text": "好", "utterances": [{"start_time": 0, "end_time": 500, "text": "好"}]}}
            ).encode()
            return response

        with tempfile.TemporaryDirectory() as temp_dir:
            audio = Path(temp_dir) / "audio_16k.mp3"
            audio.write_bytes(b"mp3")
            job = SimpleNamespace(error=None, hotwords=["京极彩"], title="标题")
            with mock.patch.object(pipeline, "_get_doubao_key", return_value="key"), \
                    mock.patch.object(pipeline, "_read_config", return_value={}), \
                    mock.patch.object(pipeline, "_asr_timeout", return_value=10), \
                    mock.patch.object(pipeline.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = pipeline._transcribe_doubao(audio, job)
        self.assertEqual("好", result["text"])
        body = json.loads(captured[0].data.decode("utf-8"))
        self.assertIn("京极彩", json.loads(body["request"]["corpus"]["context"])["hotwords"][0]["word"])

    def test_online_request_passes_hotwords_and_illustrated(self):
        body = json.dumps({"url": "https://www.bilibili.com/video/BV1VuyMBsEVH/",
                           "hotwords": "京极彩, CEDEC", "illustrated": True}).encode("utf-8")
        handler = make_handler("/api/transcribe-online", body,
                               {"Content-Length": str(len(body)), "Content-Type": "application/json"})
        fake_job = mock.Mock(id="job1")
        with mock.patch.object(server.job_manager, "Job", return_value=fake_job) as job_class, \
                mock.patch.object(server.job_manager, "add_job"), \
                mock.patch.object(server.job_manager, "submit"):
            handler.do_POST()
        self.assertEqual([200], handler.response_statuses)
        self.assertEqual(["京极彩", "CEDEC"], job_class.call_args.kwargs["hotwords"])
        self.assertTrue(job_class.call_args.kwargs["illustrated"])


class IllustratedTests(unittest.TestCase):
    def test_segments_follow_the_slide_on_screen_and_end_cards_are_dropped(self):
        slides = [{"file": "a.jpg", "start": 0, "end": 10}, {"file": "b.jpg", "start": 10, "end": 30},
                  {"file": "ad.jpg", "start": 30, "end": 40}]
        segments = [{"start": 1, "text": "第一句。"}, {"start": 9.8, "text": "换页前一刻。"},
                    {"start": 12, "text": "第二页。"}]
        sections = illustrate.align(slides, segments, pipeline._join_text, compact=False)
        self.assertEqual(["a.jpg", "b.jpg"], [section["file"] for section in sections])
        self.assertEqual(["第一句。"], sections[0]["paragraphs"])
        self.assertEqual(["换页前一刻。第二页。"], sections[1]["paragraphs"])
        self.assertEqual("00:10–00:30", sections[1]["time"])

    def test_compact_mode_folds_low_value_frames_without_losing_text(self):
        long = "这一页讲了很多内容。" * 10
        slides = [{"file": "title.jpg", "start": 0, "end": 5}, {"file": "a.jpg", "start": 5, "end": 20},
                  {"file": "b.jpg", "start": 20, "end": 25}, {"file": "c.jpg", "start": 25, "end": 60}]
        segments = [{"start": 1, "text": "开场。"}, {"start": 6, "text": long},
                    {"start": 21, "text": "过渡。"}, {"start": 26, "text": long}]
        sections = illustrate.align(slides, segments, pipeline._join_text)
        self.assertEqual(["a.jpg", "c.jpg"], [section["file"] for section in sections])
        self.assertTrue(sections[0]["paragraphs"][0].startswith("开场。"))
        self.assertTrue("".join(sections[0]["paragraphs"]).endswith("过渡。"))
        self.assertEqual("00:05–00:25", sections[0]["time"])
        text = "".join("".join(s["paragraphs"]) for s in sections)
        self.assertEqual(len("开场。" + long + "过渡。" + long), len(text))

    def test_html_is_self_contained_and_markdown_links_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "a.jpg").write_bytes(b"\xff\xd8jpeg")
            sections = [{"file": "a.jpg", "time": "00:00–00:10", "paragraphs": ["<原文>"]}]
            page = illustrate.render_html("标题", ["时长：00:10"], sections, temp_dir)
        self.assertIn("data:image/jpeg;base64,", page)
        self.assertIn("&lt;原文&gt;", page)
        markdown = illustrate.render_markdown("标题", [], sections)
        self.assertIn("![00:00–00:10](slides/a.jpg)", markdown)

    def test_fast_cut_footage_is_thinned_to_the_slide_limit(self):
        stderr = "".join(f"pts_time:{t} " for t in range(0, 2000, 3))
        completed = mock.Mock(stderr=stderr)
        with mock.patch.object(illustrate.subprocess, "run", return_value=completed), \
                mock.patch.object(illustrate, "find_executable", return_value="ffmpeg"):
            starts = illustrate.detect_scenes("v.mp4", 2000, max_slides=50)
        self.assertLessEqual(len(starts), 50)
        self.assertEqual(0.0, starts[0])

    def test_illustration_failure_keeps_the_transcript(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = pipeline.Job(job_dir=temp_dir, formats=["txt"], allow_enrichment=False, illustrated=True)
            transcript = {"text": "文稿。", "segments": [{"start": 0, "end": 1, "text": "文稿。"}]}
            with mock.patch.object(illustrate, "build", side_effect=RuntimeError("ffmpeg crashed")), \
                    mock.patch.object(pipeline, "_probe_duration", return_value=1.0):
                pipeline._finish_transcript(job, transcript, video=Path(temp_dir) / "v.mp4")
        self.assertEqual("done", job.status)
        self.assertEqual(["transcript.txt"], [item["file"] for item in job.files])
        self.assertIn("图文稿生成失败", job.engine_note)


class PlatformAndCliTests(unittest.TestCase):
    def test_bilibili_requests_try_look_for_720p_without_login(self):
        payload = {"data": {"dash": {"video": [], "audio": []}}}
        with mock.patch.object(bilibili, "_request_json", return_value=payload) as request:
            bilibili.fetch_dash({"cid": 1, "bvid": "BV1", "source": "https://b"})
        self.assertEqual(1, request.call_args.args[1]["try_look"])

    def test_cli_json_output_is_not_mixed_with_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "a.mp3"
            media.write_bytes(b"x")
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = video2doc.main([str(media), "--download", "--json", "--output", temp_dir])
        self.assertEqual(1, code)
        self.assertEqual([None], json.loads(stdout.getvalue()))
        self.assertIn("--download 只适用于视频链接", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
