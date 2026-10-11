import io
import json
import runpy
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from webui import server, templates

TEST_TEMP_ROOT = Path(__file__).resolve().parent


@contextmanager
def workspace_temp_dir():
    # tempfile.TemporaryDirectory(mode=0o700) can create unusable ACLs on some Windows runtimes.
    path = TEST_TEMP_ROOT / ("security-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def make_handler(path="/", body=b"", headers=None):
    handler = server.Handler.__new__(server.Handler)
    handler.path = path
    handler.headers = headers or {}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.response_statuses = []
    handler.response_headers = []
    handler.send_response = handler.response_statuses.append
    handler.send_header = lambda name, value: handler.response_headers.append((name, value))
    handler.end_headers = lambda: None
    return handler


class PlatformUrlValidationTests(unittest.TestCase):
    def test_accepts_supported_hosts_and_subdomains(self):
        accepted = (
            "https://v.douyin.com/abc/",
            "https://www.bilibili.com/video/BV123",
            "https://b23.tv/abc",
            "https://www.youtube.com/watch?v=abc",
            "https://youtu.be/abc",
            "https://www.xiaohongshu.com/explore/abc",
            "https://xhslink.com/abc",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(server.validate_platform_url(value), value)

    def test_extracts_url_from_platform_share_text(self):
        value = "复制打开抖音，看看视频 https://v.douyin.com/abc/ 口令"
        self.assertEqual(server.validate_platform_url(value), "https://v.douyin.com/abc/")

    def test_rejects_unsafe_or_lookalike_urls(self):
        rejected = (
            "file:///etc/passwd",
            "http://127.0.0.1/admin",
            "https://youtube.com.evil.example/watch?v=x",
            "https://evil-youtube.com/watch?v=x",
            "https://youtube.com@127.0.0.1/watch?v=x",
            "https://youtube.com:8443/watch?v=x",
            "https://youtube.com\\@127.0.0.1/watch?v=x",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(server.RequestValidationError):
                    server.validate_platform_url(value)


class PathSafetyTests(unittest.TestCase):
    def test_job_and_filename_components_are_validated(self):
        self.assertTrue(templates.is_safe_job_id("a1b2c3d4"))
        self.assertFalse(templates.is_safe_job_id("../output"))
        self.assertFalse(templates.is_safe_job_id("..\\output"))
        self.assertTrue(templates.is_safe_filename("transcript.md"))
        self.assertFalse(templates.is_safe_filename("../README.md"))
        self.assertFalse(templates.is_safe_filename("..\\README.md"))
        self.assertFalse(templates.is_safe_filename("C:\\Windows\\win.ini"))

    def test_resolved_result_file_stays_inside_job_directory(self):
        with workspace_temp_dir() as output:
            job_dir = output / "job_123"
            job_dir.mkdir()
            result = job_dir / "transcript.md"
            result.write_text("safe", encoding="utf-8")
            with mock.patch.object(templates, "OUTPUT_DIR", output):
                self.assertEqual(templates.resolve_job_file("job_123", "transcript.md"),
                                 result.resolve())
                self.assertIsNone(templates.resolve_job_file("job_123", "../secret.txt"))
                self.assertIsNone(templates.resolve_job_file("../job_123", "transcript.md"))

    def test_text_preview_falls_back_to_raw_transcript(self):
        with workspace_temp_dir() as output:
            raw_dir = output / "job_123" / "raw"
            raw_dir.mkdir(parents=True)
            (raw_dir / "tele_result.json").write_text(
                '{"text":"统一预览文本","segments":[]}', encoding="utf-8")
            with mock.patch.object(templates, "OUTPUT_DIR", output):
                self.assertEqual("统一预览文本", templates.read_content("job_123", "text"))

    def test_download_route_rejects_traversal(self):
        handler = make_handler("/api/download/../README.md")
        handler.do_GET()
        self.assertEqual(handler.response_statuses, [400])


class RequestBoundaryTests(unittest.TestCase):
    def test_public_capabilities_expose_readiness_without_secrets(self):
        checks = {
            "ffmpeg": {"ok": True}, "ffprobe": {"ok": True},
            "curl": {"ok": True}, "yt_dlp": {"ok": True},
            "doubao": {"ok": True}, "siliconflow": {"ok": False},
            "funasr": {"ok": False}, "whisper": {"ok": False},
        }
        with mock.patch("scripts.check_setup.check_all", return_value=checks) as check, \
             mock.patch.object(server.pipeline, "_get_api_key", return_value="sk-secret"):
            capabilities = server.get_public_capabilities()
        check.assert_called_once_with(check_updates=False)
        self.assertTrue(capabilities["download_tools_ready"])
        self.assertTrue(capabilities["transcription_configured"])
        self.assertEqual({"doubao": True, "tele": False,
                          "funasr": False, "whisper": False},
                         capabilities["engines"])
        self.assertTrue(capabilities["enrichment_configured"])
        payload = json.dumps(capabilities, ensure_ascii=False)
        self.assertNotIn("api_key", payload.lower())
        self.assertNotIn("secret", payload.lower())

    def test_public_capabilities_whitelist_component_versions_and_update_state(self):
        checks = {
            "python": {"ok": True, "version": "3.11.15"},
            "ffmpeg": {"ok": True, "version": "7.1", "msg": "C:\\private\\ffmpeg.exe"},
            "ffprobe": {"ok": True, "version": "7.1"},
            "curl": {"ok": True, "version": "8.14.1"},
            "yt_dlp": {
                "ok": True, "installed": True, "version": "2026.7.4",
                "minimum_version": "2026.7.4", "latest_version": "2026.8.1",
                "version_status": "update_available", "meets_minimum": True,
                "update_available": True, "msg": "C:\\private\\yt-dlp.exe",
                "upgrade_command": "secret-command", "update_check_error": "private-error",
            },
            "javascript_runtime": {"ok": True, "installed": True,
                                   "name": "node", "version": "22.0.0"},
        }
        with mock.patch("scripts.check_setup.check_all", return_value=checks) as check:
            capabilities = server.get_public_capabilities(check_updates=True)

        check.assert_called_once_with(check_updates=True)
        yt_dlp = capabilities["components"]["yt_dlp"]
        self.assertEqual("2026.7.4", yt_dlp["version"])
        self.assertEqual("2026.8.1", yt_dlp["latest_version"])
        self.assertTrue(yt_dlp["update_available"])
        self.assertTrue(yt_dlp["update_check_failed"])
        payload = json.dumps(capabilities, ensure_ascii=False)
        self.assertNotIn("private", payload)
        self.assertNotIn("upgrade_command", payload)
        self.assertNotIn("secret-command", payload)

    def test_oversized_body_is_rejected_before_read(self):
        handler = make_handler(headers={"Content-Length": str(server.MAX_JSON_BODY_BYTES + 1)})

        class MustNotRead:
            def read(self, _size):
                raise AssertionError("oversized request body was read")

        handler.rfile = MustNotRead()
        with self.assertRaises(server.RequestValidationError) as caught:
            handler._read_body(server.MAX_JSON_BODY_BYTES)
        self.assertEqual(caught.exception.status, 413)

    def test_invalid_json_and_non_object_json_return_400(self):
        for body in (b"{bad", b"[]"):
            with self.subTest(body=body):
                handler = make_handler(
                    "/api/transcribe-online",
                    body,
                    {"Content-Length": str(len(body)), "Content-Type": "application/json"},
                )
                handler.do_POST()
                self.assertEqual(handler.response_statuses, [400])

    def test_invalid_field_type_returns_400_without_starting_job(self):
        body = json.dumps({
            "url": "https://www.youtube.com/watch?v=abc",
            "formats": ["md"],
        }).encode("utf-8")
        handler = make_handler(
            "/api/transcribe-online",
            body,
            {"Content-Length": str(len(body)), "Content-Type": "application/json"},
        )
        with mock.patch.object(server.job_manager, "submit") as submit:
            handler.do_POST()
        self.assertEqual(handler.response_statuses, [400])
        submit.assert_not_called()

    def test_json_response_does_not_enable_wildcard_cors(self):
        handler = make_handler()
        handler._send_json({"ok": True})
        header_names = {name.lower() for name, _ in handler.response_headers}
        self.assertNotIn("access-control-allow-origin", header_names)

    def test_boolean_parser_is_strict(self):
        self.assertTrue(server.parse_bool(True, "flag"))
        self.assertTrue(server.parse_bool("true", "flag"))
        self.assertFalse(server.parse_bool("0", "flag"))
        with self.assertRaises(server.RequestValidationError):
            server.parse_bool("yes", "flag")

    def test_online_job_receives_enrichment_choice(self):
        body = json.dumps({
            "url": "https://www.youtube.com/watch?v=abc",
            "allow_enrichment": False,
        }).encode("utf-8")
        handler = make_handler(
            "/api/transcribe-online",
            body,
            {"Content-Length": str(len(body)), "Content-Type": "application/json"},
        )
        fake_job = mock.Mock(id="job123")
        with mock.patch.object(server.job_manager, "Job", return_value=fake_job) as job_class, \
                mock.patch.object(server.job_manager, "add_job"), \
                mock.patch.object(server.job_manager, "submit") as submit:
            handler.do_POST()
        self.assertEqual(handler.response_statuses, [200])
        self.assertFalse(job_class.call_args.kwargs["allow_enrichment"])
        submit.assert_called_once_with(fake_job, server.pipeline.run_transcribe_pipeline)


class UploadSafetyTests(unittest.TestCase):
    def test_storage_name_is_server_generated(self):
        self.assertEqual(server.clean_original_filename("..\\..\\camera.MP4"), "camera.MP4")
        self.assertEqual(server.upload_storage_name("..\\..\\camera.MP4"), "uploaded-media.mp4")
        self.assertNotIn(".exe", server.ALLOWED_UPLOAD_SUFFIXES)

    def test_multipart_filename_cannot_escape_job_directory(self):
        boundary = "----video2doc-test"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="..\\..\\owned.mp4"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode("ascii") + b"video-bytes" + (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="formats"\r\n\r\n'
            f"md\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="engine"\r\n\r\n'
            f"auto\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="local_only"\r\n\r\n'
            f"true\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="allow_enrichment"\r\n\r\n'
            f"true\r\n--{boundary}--\r\n"
        ).encode("ascii")

        with workspace_temp_dir() as tmp:
            job_dir = tmp / "job123"
            captured = {}

            class FakeJob:
                def __init__(self, **kwargs):
                    captured.update(kwargs)
                    self.id = "job123"
                    self.dir = job_dir
                    self.dir.mkdir(parents=True)
                    self.local_filename = ""
                    self.local_filesize = 0

            handler = make_handler(
                "/api/transcribe-local",
                body,
                {
                    "Content-Length": str(len(body)),
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
            with mock.patch.object(server.job_manager, "Job", FakeJob), \
                    mock.patch.object(server.job_manager, "add_job"), \
                    mock.patch.object(server.job_manager, "submit") as submit:
                handler.do_POST()

            self.assertEqual(handler.response_statuses, [200])
            self.assertEqual((job_dir / "raw" / "uploaded-media.mp4").read_bytes(), b"video-bytes")
            self.assertFalse((tmp / "owned.mp4").exists())
            self.assertTrue(captured["local_only"])
            self.assertFalse(captured["allow_enrichment"])
            submit.assert_called_once()

    def test_raw_upload_streams_to_disk_with_query_options(self):
        payload = b"x" * (server.STREAM_CHUNK_SIZE + 17)
        with workspace_temp_dir() as tmp:
            job_dir = tmp / "jobraw"
            captured = {}

            class FakeJob:
                def __init__(self, **kwargs):
                    captured.update(kwargs)
                    self.id = "jobraw"
                    self.dir = job_dir
                    self.dir.mkdir(parents=True)
                    self.local_filename = ""
                    self.local_filesize = 0

            handler = make_handler(
                "/api/transcribe-local?filename=%E4%BC%9A%E8%AE%AE.M4A&formats=srt"
                "&engine=whisper&local_only=true&allow_enrichment=true",
                payload,
                {"Content-Length": str(len(payload)),
                 "Content-Type": "application/octet-stream"},
            )
            with mock.patch.object(server.job_manager, "Job", FakeJob), \
                    mock.patch.object(server.job_manager, "add_job"), \
                    mock.patch.object(server.job_manager, "submit") as submit:
                handler.do_POST()

            self.assertEqual(handler.response_statuses, [200])
            stored = job_dir / "raw" / "uploaded-media.m4a"
            self.assertEqual(payload, stored.read_bytes())
            self.assertFalse((job_dir / "raw" / "uploaded-media.m4a.part").exists())
            self.assertEqual(["srt"], captured["formats"])
            self.assertEqual("whisper", captured["engine"])
            self.assertTrue(captured["local_only"])
            self.assertFalse(captured["allow_enrichment"])
            submit.assert_called_once()

    def test_truncated_raw_upload_leaves_no_job_directory(self):
        with workspace_temp_dir() as tmp:
            job_dir = tmp / "jobcut"

            class FakeJob:
                def __init__(self, **kwargs):
                    self.id = "jobcut"
                    self.dir = job_dir
                    self.dir.mkdir(parents=True)

            handler = make_handler(
                "/api/transcribe-local?filename=a.mp3",
                b"short",
                {"Content-Length": "1000", "Content-Type": "application/octet-stream"},
            )
            with mock.patch.object(server.job_manager, "Job", FakeJob), \
                    mock.patch.object(server.job_manager, "submit") as submit:
                handler.do_POST()
            self.assertEqual(handler.response_statuses, [400])
            self.assertFalse(job_dir.exists())
            submit.assert_not_called()


class HostAndOriginTests(unittest.TestCase):
    def test_dns_rebinding_host_is_rejected(self):
        handler = make_handler("/api/history", headers={"Host": "evil.example:8765"})
        handler.do_GET()
        self.assertEqual([403], handler.response_statuses)

    def test_loopback_hosts_are_accepted(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
            with self.subTest(host=host), \
                    mock.patch.object(server.job_manager, "get_history", return_value=[]):
                handler = make_handler("/api/history", headers={"Host": host})
                handler.do_GET()
                self.assertEqual([200], handler.response_statuses)

    def test_cross_site_post_is_rejected_before_reading_body(self):
        for headers in (
            {"Host": "127.0.0.1:8765", "Origin": "https://evil.example"},
            {"Host": "127.0.0.1:8765", "Origin": "null"},
            {"Host": "127.0.0.1:8765", "Sec-Fetch-Site": "cross-site"},
        ):
            with self.subTest(headers=headers):
                handler = make_handler("/api/transcribe-online", headers=dict(headers))
                handler.rfile = mock.Mock(read=mock.Mock(side_effect=AssertionError("read")))
                handler.do_POST()
                self.assertEqual([403], handler.response_statuses)

    def test_lan_mode_accepts_any_host(self):
        self.assertIsNone(server.allowed_hosts_for("0.0.0.0"))
        self.assertIn("192.168.1.5", server.allowed_hosts_for("192.168.1.5"))


class StartupDefaultsTests(unittest.TestCase):
    def test_default_host_is_loopback(self):
        root = Path(__file__).resolve().parents[1]
        namespace = runpy.run_path(str(root / "webui.py"), run_name="video2doc_webui_test")
        self.assertEqual(namespace["HOST"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
