import re
import unittest
from pathlib import Path

from webui import server


HTML_PATH = Path(__file__).resolve().parents[1] / "webui" / "static" / "index.html"
README_PATH = Path(__file__).resolve().parents[1] / "README.md"


class FrontendTruthfulnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_homepage_uses_supported_claims_and_hides_unfinished_controls(self):
        for unsupported in (
            "95%+", "AI 准确率", "高清无水印", "一键下载",
            "永久免费", "MIT License", "4级", 'id="tr-domain"',
            'id="dl-transcribe"',
        ):
            with self.subTest(unsupported=unsupported):
                self.assertNotIn(unsupported, self.html)

        for supported in (
            "3", "处理方式", "字幕优先", "文稿格式",
            "MD / TXT / JSON / SRT", "小红书（实验）",
            'id="runtime-status"', "/api/capabilities",
        ):
            with self.subTest(supported=supported):
                self.assertIn(supported, self.html)

    def test_format_selectors_match_backend_contract(self):
        for select_id in ("tr-format", "lo-format"):
            with self.subTest(select_id=select_id):
                match = re.search(
                    rf'<select id="{select_id}">(.*?)</select>', self.html, re.DOTALL)
                self.assertIsNotNone(match)
                values = set(re.findall(r'<option value="([^"]+)"', match.group(1)))
                self.assertEqual(server.ALLOWED_FORMATS, values)

    def test_privacy_mode_is_discoverable_and_documented(self):
        for visible_contract in (
            'id="lo-local-only"', 'id="lo-privacy-guide"',
            "隐私模式：仅本机识别", "选择本地引擎本身不等于开启隐私模式",
            "当前不可开启：未检测到 FunASR 或 Whisper",
        ):
            with self.subTest(visible_contract=visible_contract):
                self.assertIn(visible_contract, self.html)

        for documented_contract in (
            "## 隐私模式（仅本机处理）", "只有勾选",
            "不会偷偷回退到云端", "首次使用 FunASR / Whisper",
            "output/<任务 ID>/", "链接转文稿",
        ):
            with self.subTest(documented_contract=documented_contract):
                self.assertIn(documented_contract, self.readme)

    def test_component_update_check_is_explicit_and_never_auto_upgrades(self):
        for visible_contract in (
            'id="runtime-update-btn"', "/api/component-updates",
            "联网检查最新版", "本机版本为离线读取", "不会自动升级",
            "低于最低要求", "请手动更新",
        ):
            with self.subTest(visible_contract=visible_contract):
                self.assertIn(visible_contract, self.html)

        self.assertNotIn("yt-dlp -U", self.html)
        self.assertNotIn("pip install --upgrade", self.html)


if __name__ == "__main__":
    unittest.main()
