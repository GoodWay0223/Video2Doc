import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import publish_lark
from webui import pipeline, settings

from test_settings_and_tools import HomeSandbox


class ReplacementTests(unittest.TestCase):
    def test_rules_parse_all_arrow_styles_and_skip_noise(self):
        pairs = pipeline.parse_replacements("CDEC => CEDEC\n踩刹->踩镲\n金桔蚕→京极彩\n无效行\nA = A\n")
        self.assertEqual([("CDEC", "CEDEC"), ("踩刹", "踩镲"), ("金桔蚕", "京极彩")], pairs)

    def test_rules_fix_segments_and_full_text_before_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = pipeline.Job(job_dir=temp_dir, formats=["srt", "txt"], allow_enrichment=False,
                               replacements=[["CDEC", "CEDEC"]])
            transcript = {"text": "欢迎来到 CDEC。", "segments": [{"start": 0, "end": 1, "text": "欢迎来到 CDEC。"}]}
            with mock.patch.object(pipeline, "_read_config", return_value={"replacements": "踩刹 => 踩镲"}):
                pipeline._finish_transcript(job, transcript)
            srt = (Path(temp_dir) / "transcript.srt").read_text(encoding="utf-8")
            raw = json.loads((Path(temp_dir) / "raw" / "tele_result.json").read_text(encoding="utf-8"))
        self.assertIn("CEDEC", srt)
        self.assertNotIn("CDEC。", srt)
        self.assertEqual("欢迎来到 CEDEC。", raw["text"])

    def test_settings_normalize_replacement_rules(self):
        with HomeSandbox():
            data = settings.update_settings({"options": {"replacements": "CDEC=CEDEC\n\n踩刹 -> 踩镲"}})
        self.assertEqual("CDEC => CEDEC\n踩刹 => 踩镲", data["options"]["replacements"]["value"])


class FakeLark:
    def __init__(self, cwd):
        self.cwd, self.calls = cwd, []

    def run(self, args, stdin=None, retries=4):
        self.calls.append((args, stdin))
        if args[:2] == ["docs", "+fetch"] and "outline" in args:
            return {"data": {"document": {"content": '<h3 id="h1">逐字稿（图文版）</h3>'}}}
        if args[:2] == ["docs", "+fetch"]:
            return {"data": {"document": {"content":
                    '<fragment><h3 id="h1">x</h3><p id="p1">a</p><img id="i1" src="t"/><ul><li id="l1">b</li></ul></fragment>'}}}
        return {"ok": True}


class LarkPublisherTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual("TxVx123", publish_lark.doc_token("https://a.larksuite.com/docx/TxVx123?from=x"))
        self.assertEqual({"ok": True}, publish_lark.parse_cli_json("Uploading...\nDone\n{\"ok\": true}"))
        self.assertEqual(["a", "b", "c"], publish_lark.top_level_ids(
            '<p id="a">x<b>y</b></p><ul><li id="b">1</li></ul><img id="c" src="t"/>'))

    def test_publish_interleaves_images_and_text_then_moves_and_resumes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job = Path(temp_dir)
            (job / "slides").mkdir()
            (job / "slides" / "slide_000.jpg").write_bytes(b"jpg")
            (job / "slides" / "sections.json").write_text(json.dumps([
                {"file": "slide_000.jpg", "time": "00:00–00:10", "paragraphs": ["第一段<原文>"]}],
                ensure_ascii=False), encoding="utf-8")
            (job / "job.json").write_text(json.dumps({"url": "https://b.tv/x", "duration": "00:10"}), encoding="utf-8")
            (job / "transcript.srt").write_text("1", encoding="utf-8")
            lark = FakeLark(str(job))
            publish_lark.publish(lark, job, "DOC", heading="逐字稿（图文版）", after_block="anchor")
            commands = [call[0][1] for call in lark.calls]
            self.assertEqual(["+update", "+media-insert", "+update", "+media-insert", "+fetch", "+fetch", "+update"],
                             commands)
            self.assertIn("&lt;原文&gt;", lark.calls[2][1])
            self.assertIn("00:00–00:10", lark.calls[1][0])
            move = lark.calls[-1][0]
            self.assertEqual("h1,p1,i1,l1", move[move.index("--src-block-ids") + 1])
            again = FakeLark(str(job))
            publish_lark.publish(again, job, "DOC", heading="逐字稿（图文版）", after_block="anchor")
            self.assertEqual([], again.calls)


if __name__ == "__main__":
    unittest.main()
