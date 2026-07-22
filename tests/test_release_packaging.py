import hashlib
import json
import shutil
import subprocess
import sys
import unittest
import uuid
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_release


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = ROOT / "tests" / ("release-test-" + uuid.uuid4().hex)
        self.temp_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_archive_is_safe_cross_platform_and_runnable(self):
        output = self.temp_dir / "dist"
        result = build_release.build_release(
            ROOT, output, "9.8.7-test", allow_dirty=True
        )
        self.assertEqual("Video2Doc-v9.8.7-test.zip", result.archive.name)
        self.assertTrue(result.checksum_file.is_file())
        self.assertEqual(
            result.checksum,
            hashlib.sha256(result.archive.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            f"{result.checksum}  {result.archive.name}\n",
            result.checksum_file.read_text(encoding="ascii"),
        )

        with zipfile.ZipFile(result.archive) as bundle:
            names = bundle.namelist()
            root_name = "Video2Doc-v9.8.7-test"
            required = {
                f"{root_name}/README.md",
                f"{root_name}/CHANGELOG.md",
                f"{root_name}/requirements.txt",
                f"{root_name}/start-video2doc.cmd",
                f"{root_name}/start-video2doc.command",
                f"{root_name}/webui.py",
                f"{root_name}/scripts/check_setup.py",
                f"{root_name}/webui/server.py",
                f"{root_name}/{build_release.MANIFEST_NAME}",
            }
            self.assertTrue(required.issubset(names))
            for name in names:
                with self.subTest(member=name):
                    self.assertNotIn("\\", name)
                    path = PurePosixPath(name)
                    self.assertFalse(path.is_absolute())
                    self.assertNotIn("..", path.parts)
                    self.assertEqual(root_name, path.parts[0])
                    self.assertNotIn(".git", path.parts)
                    self.assertNotIn("output", path.parts)
                    self.assertNotIn("__pycache__", path.parts)
                    self.assertFalse(name.endswith("/.env"))
                    self.assertFalse(name.endswith("cookies.txt"))
                    self.assertFalse(name.endswith(".key"))

            shell_members = [name for name in names if name.endswith(".sh")]
            self.assertTrue(shell_members)
            for shell_member in shell_members:
                with self.subTest(executable=shell_member):
                    shell_info = bundle.getinfo(shell_member)
                    self.assertEqual(
                        0o755, (shell_info.external_attr >> 16) & 0o777
                    )
            command_info = bundle.getinfo(f"{root_name}/start-video2doc.command")
            self.assertEqual(0o755, (command_info.external_attr >> 16) & 0o777)
            cmd_content = bundle.read(f"{root_name}/start-video2doc.cmd")
            self.assertIn(b"\r\n", cmd_content)
            self.assertNotIn(b"\n", cmd_content.replace(b"\r\n", b""))
            command_content = bundle.read(f"{root_name}/start-video2doc.command")
            self.assertNotIn(b"\r\n", command_content)
            manifest = json.loads(
                bundle.read(f"{root_name}/{build_release.MANIFEST_NAME}")
            )
            self.assertEqual("9.8.7-test", manifest["version"])
            self.assertEqual(result.file_count, len(manifest["files"]))

            extracted = self.temp_dir / "extracted"
            bundle.extractall(extracted)

        completed = subprocess.run(
            [sys.executable, "webui.py", "--help"],
            cwd=extracted / root_name,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("--check-only", completed.stdout)

    def test_build_is_reproducible(self):
        first = build_release.build_release(
            ROOT, self.temp_dir / "first", "1.2.3", allow_dirty=True
        )
        second = build_release.build_release(
            ROOT, self.temp_dir / "second", "1.2.3", allow_dirty=True
        )
        self.assertEqual(first.checksum, second.checksum)
        self.assertEqual(first.archive.read_bytes(), second.archive.read_bytes())

    def test_secret_guard_stops_release(self):
        source = self.temp_dir / "source"
        source.mkdir()
        for name in (
            "README.md", "CHANGELOG.md", "requirements.txt",
            "start-video2doc.cmd", "start-video2doc.command", "webui.py",
        ):
            (source / name).write_text("safe\n", encoding="utf-8")
        (source / "accidental-secret.txt").write_text(
            "SILICONFLOW_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(build_release.ReleaseError, "疑似"):
            build_release.build_release(source, self.temp_dir / "blocked", "1.0.0")
        self.assertFalse((self.temp_dir / "blocked" / "Video2Doc-v1.0.0.zip").exists())

    def test_formal_build_rejects_dirty_git_worktree(self):
        source = self.temp_dir / "dirty-source"
        source.mkdir()
        for name in (
            "README.md", "CHANGELOG.md", "requirements.txt",
            "start-video2doc.cmd", "start-video2doc.command", "webui.py",
        ):
            (source / name).write_text("safe\n", encoding="utf-8")
        initialized = subprocess.run(
            ["git", "init", "-q"], cwd=source, capture_output=True, text=True
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)

        with self.assertRaisesRegex(build_release.ReleaseError, "干净"):
            build_release.build_release(source, self.temp_dir / "formal", "1.0.0")
        draft = build_release.build_release(
            source, self.temp_dir / "draft", "1.0.0", allow_dirty=True
        )
        self.assertTrue(draft.archive.is_file())

    def test_version_validation_blocks_path_injection(self):
        for value in ("../1.0.0", "v1.0", "release/latest", "1.0.0 beta"):
            with self.subTest(value=value):
                with self.assertRaises(build_release.ReleaseError):
                    build_release.normalize_version(value)


if __name__ == "__main__":
    unittest.main()
