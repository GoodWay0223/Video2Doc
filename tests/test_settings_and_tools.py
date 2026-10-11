import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts import platform_utils, tool_updates
from webui import server, settings

from test_server_security import make_handler


class HomeSandbox:
    """Point Path.home() at a throwaway directory and clear related env vars."""

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.patches = [
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(os.environ, {name: "" for name in (
                "DOUBAO_API_KEY", "SILICONFLOW_API_KEY", "XHS_COOKIE",
                "VIDEO2DOC_ENRICH_MODEL", "VIDEO2DOC_WHISPER_MODEL",
                "VIDEO2DOC_WHISPER_LANGUAGE", "VIDEO2DOC_COOKIES_FILE",
                "VIDEO2DOC_DOUYIN_STORAGE_STATE")}),
        ]
        for patch in self.patches:
            patch.start()
        return self.home

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()


def post(path, payload, client=("127.0.0.1", 5000)):
    body = json.dumps(payload).encode("utf-8")
    handler = make_handler(path, body, {"Content-Length": str(len(body)),
                                        "Content-Type": "application/json",
                                        "Host": "127.0.0.1:8765",
                                        "Origin": "http://127.0.0.1:8765"})
    handler.client_address = client
    handler.do_POST()
    return handler


def response_json(handler):
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


class SettingsTests(unittest.TestCase):
    def test_saved_key_is_used_by_pipeline_but_never_returned(self):
        secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        with HomeSandbox() as home:
            data = settings.update_settings({"secrets": {"siliconflow_api_key": secret}})
            from webui import pipeline
            self.assertEqual(secret, pipeline._get_api_key())
            provider = next(p for p in data["providers"] if p["id"] == "siliconflow")
            self.assertTrue(provider["configured"])
            self.assertEqual("config", provider["source"])
            self.assertNotIn(secret, json.dumps(settings.public_settings(), ensure_ascii=False))
            self.assertEqual(secret, json.loads((home / ".video2doc" / "config.json")
                                                .read_text(encoding="utf-8"))["siliconflow_api_key"])

    def test_environment_variable_keeps_priority_and_clear_removes_key(self):
        with HomeSandbox():
            settings.update_settings({"secrets": {"doubao_api_key": "from-config-1234567890"}})
            with mock.patch.dict(os.environ, {"DOUBAO_API_KEY": "from-env-0987654321"}):
                self.assertEqual("env", settings.secret_status("doubao_api_key")["source"])
                self.assertEqual("from-env-0987654321", settings.effective_secret("doubao_api_key"))
            settings.update_settings({"secrets": {"doubao_api_key": None}})
            self.assertFalse(settings.secret_status("doubao_api_key")["configured"])

    def test_other_config_entries_are_preserved(self):
        with HomeSandbox() as home:
            config = home / ".video2doc" / "config.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"bilibili_cookies_file": "x"}), encoding="utf-8")
            settings.update_settings({"options": {"whisper_language": "auto"}})
            saved = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual({"bilibili_cookies_file": "x", "whisper_language": "auto"}, saved)

    def test_invalid_values_are_rejected(self):
        with HomeSandbox():
            for payload in (
                {"secrets": {"unknown_key": "x"}},
                {"secrets": {"doubao_api_key": "bad\nkey"}},
                {"options": {"whisper_model": "giant"}},
                {"options": {"enrich_model": "../../etc"}},
                {"options": {"cookies_file": "Z:/definitely/missing.txt"}},
                {"options": {"auto_update_tools": "yes"}},
                {},
            ):
                with self.subTest(payload=payload), self.assertRaises(settings.SettingsError):
                    settings.update_settings(payload)

    def test_key_verification_interprets_provider_responses(self):
        cases = [
            ("siliconflow", (200, {}, b"{}"), True),
            ("siliconflow", (401, {}, b"{}"), False),
            ("doubao", (200, {"X-Api-Status-Code": "45000092"}, b"{}"), True),
            ("doubao", (401, {"X-Api-Status-Code": "45000010"}, b"{}"), False),
        ]
        for provider, response, expected in cases:
            with self.subTest(provider=provider, status=response[0]), \
                    mock.patch.object(settings, "_request", return_value=response) as request:
                result = settings.verify_key(provider, "candidate-key-123456")
            self.assertEqual(expected, result["ok"])
            sent = json.dumps(request.call_args.kwargs.get("headers"))
            self.assertIn("candidate-key-123456", sent)

    def test_model_list_falls_back_to_presets_without_key(self):
        with HomeSandbox():
            self.assertEqual("presets", settings.enrich_models()["source"])


class SettingsRouteTests(unittest.TestCase):
    def test_settings_writes_are_limited_to_this_computer(self):
        with HomeSandbox():
            handler = post("/api/settings", {"options": {"whisper_language": "en"}},
                           client=("192.168.1.20", 5000))
            self.assertEqual([403], handler.response_statuses)
            handler = post("/api/settings", {"options": {"whisper_language": "en"}})
            self.assertEqual([200], handler.response_statuses)
            self.assertEqual("en", response_json(handler)["options"]["whisper_language"]["value"])

    def test_invalid_settings_return_400(self):
        with HomeSandbox():
            handler = post("/api/settings", {"options": {"whisper_model": "giant"}})
        self.assertEqual([400], handler.response_statuses)

    def test_tool_update_route_validates_component(self):
        handler = post("/api/tools/update", {"id": "rm -rf"})
        self.assertEqual([400], handler.response_statuses)
        with mock.patch.object(tool_updates, "start_update", return_value=True) as start:
            handler = post("/api/tools/update", {"id": "yt_dlp"})
        self.assertEqual([200], handler.response_statuses)
        start.assert_called_once_with("yt_dlp")


class ToolUpdateTests(unittest.TestCase):
    def test_status_respects_cool_off_and_versions(self):
        self.assertEqual("update_available",
                         tool_updates._status("2026.7.4", {"latest": "2026.9.1", "target": "2026.8.19"}))
        self.assertEqual("up_to_date",
                         tool_updates._status("2026.08.19", {"latest": "2026.9.1", "target": "2026.8.19"}))
        self.assertEqual("newer", tool_updates._status("9.1", {"latest": "9.0.2", "target": "9.0.2"}))
        self.assertEqual("not_installed", tool_updates._status(None, {"latest": "1"}))
        self.assertEqual("update_available",
                         tool_updates._status("N-125136", {"latest": "9.0.2", "target": "9.0.2"}, dev_build=True))

    def test_pypi_target_skips_fresh_prerelease_and_yanked_versions(self):
        now = datetime(2026, 10, 11, tzinfo=timezone.utc)

        def release(days, yanked=False):
            when = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
            return [{"upload_time_iso_8601": when, "yanked": yanked}]

        payload = {"releases": {
            "2026.10.9": release(2),          # too fresh
            "2026.10.1": release(10, True),   # yanked
            "2026.11.0rc1": release(20),      # prerelease
            "2026.9.20": release(21),
            "2026.8.19": release(53),
        }}
        with mock.patch.object(tool_updates, "_get_json", return_value=payload):
            result = tool_updates.pypi_release("yt-dlp", now=now)
        self.assertEqual({"latest": "2026.10.9", "target": "2026.9.20"}, result)

    @unittest.skipUnless(os.name == "nt", "in-place FFmpeg updates are Windows-only")
    def test_ffmpeg_is_only_updated_inside_a_dedicated_directory(self):
        root = Path(__file__).resolve().parent / ("ffmpeg-test-" + uuid.uuid4().hex)
        try:
            (root / "bin").mkdir(parents=True)
            for name in ("ffmpeg.exe", "ffprobe.exe"):
                (root / "bin" / name).write_bytes(b"x")
            self.assertEqual(("standalone", root.resolve()),
                             tool_updates._ffmpeg_layout(root / "bin" / "ffmpeg.exe"))
            (root / "unrelated-project").mkdir()
            self.assertEqual("manual", tool_updates._ffmpeg_layout(root / "bin" / "ffmpeg.exe")[0])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_mirror_replaces_binaries_and_keeps_foreign_files(self):
        base = Path(__file__).resolve().parent / ("mirror-test-" + uuid.uuid4().hex)
        try:
            old, new = base / "old", base / "new"
            (old / "bin").mkdir(parents=True)
            (old / "bin" / "ffmpeg.exe").write_bytes(b"old")
            (old / "bin" / "stale.dll").write_bytes(b"old")
            (old / "notes.txt").write_text("keep", encoding="utf-8")
            (new / "bin").mkdir(parents=True)
            (new / "bin" / "ffmpeg.exe").write_bytes(b"new")
            tool_updates._mirror_ffmpeg(new, old)
            self.assertEqual(b"new", (old / "bin" / "ffmpeg.exe").read_bytes())
            self.assertFalse((old / "bin" / "stale.dll").exists())
            self.assertTrue((old / "notes.txt").exists())
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_pip_update_pins_target_and_avoids_cache(self):
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(tool_updates, "_run", return_value=completed) as run, \
                mock.patch.object(tool_updates, "_dist_version", return_value="2026.9.20"):
            ok, message = tool_updates.update("yt_dlp", target="2026.9.20")
        self.assertTrue(ok)
        command = run.call_args_list[0].args[0]
        self.assertIn("--no-cache-dir", command)
        self.assertIn("yt-dlp[default]==2026.9.20", command)

    def test_auto_update_respects_setting_busy_jobs_and_daily_interval(self):
        row = {"id": "yt_dlp", "updatable": True, "status": "update_available",
               "target": "2026.9.20", "version": "2026.8.19", "latest": "2026.9.20",
               "check_error": None}
        with HomeSandbox():
            platform_utils.save_user_config({"auto_update_tools": False})
            with mock.patch.object(tool_updates, "check") as check:
                self.assertEqual([], tool_updates.maybe_auto_update())
            check.assert_not_called()

            platform_utils.save_user_config({"auto_update_tools": True})
            with mock.patch.object(tool_updates, "check", return_value=[row]), \
                    mock.patch.object(tool_updates, "update") as update:
                self.assertEqual([], tool_updates.maybe_auto_update(lambda: True))
                update.assert_not_called()
                self.assertIsNone(platform_utils.load_state().get("tools_last_auto_check"))

            with mock.patch.object(tool_updates, "check", return_value=[row]), \
                    mock.patch.object(tool_updates, "update", return_value=(True, "ok")) as update:
                self.assertEqual(["yt_dlp"], tool_updates.maybe_auto_update(lambda: False))
                update.assert_called_once_with("yt_dlp", target="2026.9.20")
                self.assertEqual([], tool_updates.maybe_auto_update(lambda: False))
                update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
