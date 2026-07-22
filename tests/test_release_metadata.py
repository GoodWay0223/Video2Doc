import re
import unittest
from pathlib import Path

from webui import __version__


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_version_is_semantic_and_released_in_changelog(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        released = re.findall(r"^## \[v([^\]]+)\]", changelog, re.MULTILINE)
        self.assertTrue(released)
        self.assertEqual(__version__, released[0])

    def test_frontend_and_readme_match_package_version(self):
        frontend = (ROOT / "webui" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"Video2Doc v{__version__}", frontend)
        self.assertIn(f"Video2Doc-v{__version__}.zip", readme)

    def test_python_entrypoint_uses_package_version(self):
        entrypoint = (ROOT / "webui.py").read_text(encoding="utf-8")
        self.assertIn("from webui import __version__", entrypoint)
        self.assertNotRegex(entrypoint, r"Video2Doc 工坊 v\d+\.\d+\.\d+")

    def test_ytdlp_stable_release_tracking_is_scheduled(self):
        root = Path(__file__).resolve().parents[1]
        dependabot = (root / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        requirements = (root / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn('package-ecosystem: "pip"', dependabot)
        self.assertIn('dependency-name: "yt-dlp"', dependabot)
        self.assertIn('versioning-strategy: "increase"', dependabot)
        self.assertRegex(workflow, r"(?m)^\s+schedule:\s*$")
        self.assertRegex(requirements, r"(?m)^yt-dlp>=\d+\.\d+\.\d+\s*$")


if __name__ == "__main__":
    unittest.main()
