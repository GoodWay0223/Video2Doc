import contextlib
import io
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import apply_corrections, check_setup, export_formats, platform_utils, verify_html
from webui import job_manager, pipeline


@contextmanager
def workspace_temp_dir():
    """Create a normal workspace directory without restrictive tempfile ACLs."""
    path = ROOT / "tests" / ("pipeline-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def make_job(directory, **overrides):
    values = {
        "engine": "auto",
        "local_only": False,
        "allow_enrichment": True,
        "error": None,
        "engine_used": "",
        "engine_note": "",
        "dir": Path(directory),
        "formats": ["md"],
        "status": "queued",
        "progress": 0,
        "files": [],
        "title": "",
        "duration": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class JobAndPipelineTests(unittest.TestCase):
    def test_api_key_lookup_does_not_scan_unrelated_memory_files(self):
        with workspace_temp_dir() as temp_dir:
            memory = Path(temp_dir) / ".workbuddy" / "MEMORY.md"
            memory.parent.mkdir()
            memory.write_text("SILICONFLOW_API_KEY: sk-should-not-be-read", encoding="utf-8")
            with mock.patch.object(pipeline.Path, "home", return_value=Path(temp_dir)), \
                 mock.patch.dict(os.environ, {"SILICONFLOW_API_KEY": ""}):
                self.assertEqual("", pipeline._get_api_key())

    def test_telespeech_key_is_not_exposed_in_process_arguments(self):
        completed = subprocess.CompletedProcess([], 0, stdout='{"text":"ok"}')
        job = make_job(".")
        with mock.patch.object(pipeline, "_get_api_key", return_value="secret-key"), \
             mock.patch.object(pipeline, "find_executable", return_value="curl"), \
             mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run:
            self.assertEqual("ok", pipeline._transcribe_tele("audio.mp3", job)["text"])
        args = run.call_args.args[0]
        self.assertNotIn("secret-key", " ".join(args))
        self.assertEqual("Authorization: Bearer secret-key\r\n",
                         run.call_args.kwargs["input"])

    def test_enrichment_uses_in_process_http_request(self):
        response = mock.MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"{\\"summary\\":\\"ok\\"}"}}]}')
        response.__enter__.return_value = response
        with mock.patch.object(pipeline, "_get_api_key", return_value="secret-key"), \
             mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = pipeline._enrich_transcript("这是足够长的一段测试文稿，用于验证请求。", make_job("."))
        self.assertEqual("ok", result["summary"])
        request = urlopen.call_args.args[0]
        self.assertEqual("Bearer secret-key", request.get_header("Authorization"))
        self.assertNotIn(b"secret-key", request.data)

    def test_job_flags_are_backward_compatible_and_serialized(self):
        with workspace_temp_dir() as temp_dir:
            with mock.patch.object(job_manager, "OUTPUT_DIR", Path(temp_dir)):
                job = job_manager.Job(job_id="flags")
                self.assertFalse(job.local_only)
                self.assertTrue(job.allow_enrichment)
                self.assertFalse(job.to_dict()["local_only"])
                self.assertTrue(job.to_dict()["allow_enrichment"])

    def test_local_only_auto_never_calls_cloud_engines(self):
        job = make_job(".", local_only=True)
        expected = {"text": "本地结果", "segments": []}
        with mock.patch.object(pipeline, "_transcribe_doubao",
                               side_effect=AssertionError("cloud engine called")) as doubao, \
             mock.patch.object(pipeline, "_transcribe_tele",
                               side_effect=AssertionError("cloud engine called")) as tele, \
             mock.patch.object(pipeline, "_transcribe_funasr", return_value=None) as funasr, \
             mock.patch.object(pipeline, "_transcribe_whisper", return_value=expected) as whisper:
            result = pipeline.transcribe("audio.mp3", job)
        self.assertEqual(expected, result)
        doubao.assert_not_called()
        tele.assert_not_called()
        funasr.assert_called_once()
        whisper.assert_called_once()
        self.assertEqual("whisper", job.engine_used)

    def test_local_only_rejects_explicit_cloud_engine(self):
        job = make_job(".", local_only=True, engine="doubao")
        with mock.patch.object(pipeline, "_transcribe_doubao") as doubao:
            self.assertIsNone(pipeline.transcribe("audio.mp3", job))
        doubao.assert_not_called()
        self.assertIn("local_only", job.error)

    def test_whisper_model_can_be_selected_explicitly(self):
        job = make_job(".")
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = {
            "text": "测试",
            "segments": [{"start": 0, "end": 1, "text": "测试"}],
        }
        fake_whisper = mock.Mock()
        fake_whisper.load_model.return_value = fake_model
        with mock.patch.dict(os.environ, {"VIDEO2DOC_WHISPER_MODEL": "tiny"}), \
             mock.patch.dict("sys.modules", {"whisper": fake_whisper}):
            result = pipeline._transcribe_whisper("audio.mp3", job)
        fake_whisper.load_model.assert_called_once_with("tiny")
        self.assertEqual("测试", result["text"])

    def test_local_only_and_disabled_flag_both_skip_cloud_enrichment(self):
        cases = [
            {"local_only": True, "allow_enrichment": True},
            {"local_only": False, "allow_enrichment": False},
        ]
        for flags in cases:
            with self.subTest(**flags), workspace_temp_dir() as temp_dir:
                job = make_job(temp_dir, **flags)
                raw_dir = Path(temp_dir) / "raw"
                raw_dir.mkdir()
                audio = raw_dir / "audio.mp3"
                audio.write_bytes(b"audio")
                transcript = {"text": "测试文稿", "segments": []}
                with mock.patch.object(pipeline, "transcribe", return_value=transcript), \
                     mock.patch.object(pipeline, "_enrich_transcript",
                                       side_effect=AssertionError("cloud enrichment called")) as enrich, \
                     mock.patch.object(pipeline, "export_formats", return_value=[]):
                    pipeline.run_local_pipeline(job, str(audio))
                enrich.assert_not_called()
                self.assertEqual("done", job.status)

    def test_allow_enrichment_default_preserves_existing_behavior(self):
        with workspace_temp_dir() as temp_dir:
            job = make_job(temp_dir)
            raw_dir = Path(temp_dir) / "raw"
            raw_dir.mkdir()
            audio = raw_dir / "audio.mp3"
            audio.write_bytes(b"audio")
            transcript = {"text": "测试文稿", "segments": []}
            with mock.patch.object(pipeline, "transcribe", return_value=transcript), \
                 mock.patch.object(pipeline, "_enrich_transcript", return_value=None) as enrich, \
                 mock.patch.object(pipeline, "export_formats", return_value=[]):
                pipeline.run_local_pipeline(job, str(audio))
            enrich.assert_called_once()
            self.assertEqual("done", job.status)

    def test_formats_without_enrichment_output_skip_cloud_call(self):
        for formats in (["txt"], ["srt"]):
            with self.subTest(formats=formats):
                job = make_job(".", formats=formats, allow_enrichment=True)
                self.assertFalse(pipeline._should_enrich(job))

    def test_default_ytdlp_does_not_read_live_browser_cookies(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args, mode = pipeline._cookie_args("bilibili")
        self.assertEqual([], args)
        self.assertEqual("none", mode)
        self.assertNotIn("--cookies-from-browser", args)

    def test_explicit_cookie_file_is_supported_without_flattening_browser_state(self):
        with workspace_temp_dir() as temp_dir:
            cookie_file = Path(temp_dir) / "my cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"VIDEO2DOC_BILIBILI_COOKIES_FILE": str(cookie_file)},
                clear=True,
            ):
                args, mode = pipeline._cookie_args("bilibili")
        self.assertEqual(["--cookies", str(cookie_file)], args)
        self.assertEqual("cookies_file", mode)

    def test_resolve_url_uses_platform_null_device(self):
        completed = subprocess.CompletedProcess([], 0, stdout="https://example.com/full")
        with mock.patch.object(pipeline, "find_executable", return_value="curl"), \
             mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run:
            resolved = pipeline.resolve_url("https://example.com/short")
        self.assertEqual("https://example.com/full", resolved)
        self.assertIn(os.devnull, run.call_args.args[0])
        self.assertEqual("utf-8", run.call_args.kwargs["encoding"])
        self.assertEqual("replace", run.call_args.kwargs["errors"])

    def test_failed_audio_extraction_does_not_accept_stale_output(self):
        with workspace_temp_dir() as temp_dir:
            output = Path(temp_dir) / "audio.mp3"
            output.write_bytes(b"stale" * 1000)
            completed = subprocess.CompletedProcess([], 1)
            with mock.patch.object(pipeline, "find_executable", return_value="ffmpeg"), \
                 mock.patch.object(pipeline.subprocess, "run", return_value=completed):
                self.assertFalse(pipeline.extract_audio("video.mp4", output))
            self.assertEqual(b"stale" * 1000, output.read_bytes())
            self.assertFalse((Path(temp_dir) / "audio.part.mp3").exists())

    def test_common_binary_dirs_cover_homebrew_and_windows_package_managers(self):
        mac_dirs = platform_utils.candidate_bin_dirs(
            os_name="posix", platform_name="darwin", environ={},
            home="/Users/test", python_executable="/usr/bin/python3")
        mac_paths = {path.as_posix() for path in mac_dirs}
        self.assertTrue(any(path.endswith("/opt/homebrew/bin") for path in mac_paths))
        self.assertTrue(any(path.endswith("/usr/local/bin") for path in mac_paths))

        win_dirs = platform_utils.candidate_bin_dirs(
            os_name="nt", platform_name="win32",
            environ={"LOCALAPPDATA": "C:/Local", "PROGRAMDATA": "C:/ProgramData"},
            home="C:/Users/test", python_executable="C:/Python/python.exe")
        win_paths = {str(path).replace("\\", "/").lower() for path in win_dirs}
        self.assertIn("c:/local/microsoft/winget/links", win_paths)
        self.assertIn("c:/users/test/scoop/shims", win_paths)
        self.assertIn("c:/programdata/chocolatey/bin", win_paths)

    def test_executable_discovery_checks_common_dirs(self):
        with workspace_temp_dir() as temp_dir:
            executable = Path(temp_dir) / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
            executable.write_bytes(b"test")
            if os.name != "nt":
                executable.chmod(0o755)
            with mock.patch.object(platform_utils, "candidate_bin_dirs",
                                   return_value=[Path(temp_dir)]), \
                 mock.patch.object(platform_utils.shutil, "which", return_value=None):
                result = platform_utils.find_executable(["yt-dlp"])
        self.assertEqual(str(executable), result)

    def test_verify_html_finds_windows_browser_install(self):
        expected = str(Path("C:/Local") / "Google" / "Chrome" /
                       "Application" / "chrome.exe")
        candidates = verify_html.chrome_candidates(
            os_name="nt", environ={"LOCALAPPDATA": "C:/Local"})
        self.assertIn(expected, candidates)


class CorrectionAndExportTests(unittest.TestCase):
    def test_context_rules_do_not_replace_outside_context(self):
        exact, context, fuzzy = apply_corrections.load_rules()
        source = "领克零七GT，普通零七GT，劝你一句顶盒千万不要。200百公里"
        corrected = apply_corrections.apply_corrections(source, exact, context, fuzzy)
        self.assertIn("领克07GT", corrected)
        self.assertIn("普通零七GT", corrected)
        self.assertIn("劝你一句领克千万不要", corrected)
        self.assertIn("200公里", corrected)
        self.assertNotIn("$1公里", corrected)

    def test_domain_context_after_rule_is_respected(self):
        exact, context, fuzzy = apply_corrections.load_rules("auto")
        source = "淋巴车友，淋巴结，碳纤维大耦"
        corrected = apply_corrections.apply_corrections(source, exact, context, fuzzy)
        self.assertEqual("08车友，淋巴结，碳纤维大尾翼", corrected)

    def test_exporter_applies_domain_without_breaking_segment_newlines(self):
        segments = [{"text": "淋巴车友\n第二行"}, {"text": "淋巴结"}]
        result = export_formats.apply_corrections_to_segments(segments, domain="auto")
        self.assertEqual("08车友\n第二行", result[0]["text"])
        self.assertEqual("淋巴结", result[1]["text"])

    def test_selected_format_is_written_when_output_dir_is_given(self):
        with workspace_temp_dir() as temp_dir:
            input_path = Path(temp_dir) / "input.json"
            output_dir = Path(temp_dir) / "out"
            input_path.write_text(
                '{"segments":[{"start":0,"end":1,"text":"hello"}]}',
                encoding="utf-8")
            argv = ["export_formats.py", "--input", str(input_path),
                    "--format", "md", "--output-dir", str(output_dir)]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                export_formats.main()
            self.assertEqual("hello\n", (output_dir / "transcript.md").read_text(encoding="utf-8"))


class SetupCheckTests(unittest.TestCase):
    def test_setup_key_lookup_does_not_scan_unrelated_memory_files(self):
        with workspace_temp_dir() as temp_dir:
            memory = Path(temp_dir) / ".workbuddy" / "MEMORY.md"
            memory.parent.mkdir()
            memory.write_text("SILICONFLOW_API_KEY: sk-should-not-be-read", encoding="utf-8")
            with mock.patch.object(check_setup.Path, "home", return_value=Path(temp_dir)), \
                 mock.patch.dict(os.environ, {"SILICONFLOW_API_KEY": ""}):
                self.assertEqual("", check_setup._get_siliconflow_key({}))

    def test_one_local_engine_makes_transcription_ready(self):
        def find_bin(name):
            return name if name in {"ffmpeg", "ffprobe", "curl"} else None

        def module_available(name):
            return name == "whisper"

        with mock.patch.object(check_setup, "find_bin", side_effect=find_bin), \
             mock.patch.object(check_setup, "module_available", side_effect=module_available), \
             mock.patch.object(check_setup, "_probe_tool_version", return_value="1.0.0"), \
             mock.patch.object(check_setup, "_load_config", return_value={}), \
             mock.patch.object(check_setup, "_get_siliconflow_key", return_value=""), \
             mock.patch.object(check_setup, "_get_doubao_key", return_value=""):
            results = check_setup.check_all()
        self.assertTrue(results["whisper"]["ok"])
        self.assertTrue(results["transcription"]["ok"])
        self.assertFalse(results["playwright"]["ok"])

    def test_ytdlp_requirement_parser_supports_extras(self):
        with workspace_temp_dir() as temp_dir:
            requirements = Path(temp_dir) / "requirements.txt"
            requirements.write_text(
                "yt-dlp[default]>=2026.7.4; python_version >= '3.10'\n",
                encoding="utf-8",
            )
            self.assertEqual(
                "2026.7.4", check_setup._read_ytdlp_minimum(requirements))

    def test_version_comparison_handles_calendar_version_padding(self):
        self.assertTrue(check_setup._version_at_least("2026.07.04", "2026.7.4"))
        self.assertTrue(check_setup._version_at_least("2026.7.4.1", "2026.7.4"))
        self.assertFalse(check_setup._version_at_least("2026.6.30", "2026.7.4"))
        self.assertIsNone(check_setup._version_at_least("unknown", "2026.7.4"))

    def _versioned_check(self, yt_version="2026.7.4", *, check_updates=False,
                         latest=(None, None)):
        paths = {
            "ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "curl": "curl",
            "yt-dlp": "yt-dlp", "node": "node",
        }
        versions = {
            "ffmpeg": "7.1.1", "ffprobe": "7.1.1", "curl": "8.14.1",
            "yt-dlp": yt_version, "node": "22.16.0",
        }

        def probe(_path, name):
            return versions[name]

        with mock.patch.object(check_setup, "find_bin",
                               side_effect=lambda name: paths.get(name)), \
             mock.patch.object(check_setup, "_probe_tool_version", side_effect=probe), \
             mock.patch.object(check_setup, "module_available", return_value=False), \
             mock.patch.object(check_setup, "_load_config", return_value={}), \
             mock.patch.object(check_setup, "_get_siliconflow_key", return_value=""), \
             mock.patch.object(check_setup, "_get_doubao_key", return_value=""), \
             mock.patch.object(check_setup, "_fetch_latest_ytdlp_version",
                               return_value=latest) as fetch:
            results = check_setup.check_all(check_updates=check_updates)
        return results, fetch

    def test_default_version_check_is_offline_and_has_safe_fields(self):
        results, fetch = self._versioned_check()
        fetch.assert_not_called()
        yt = results["yt_dlp"]
        self.assertTrue(yt["installed"])
        self.assertEqual("2026.7.4", yt["version"])
        self.assertEqual("2026.7.4", yt["minimum_version"])
        self.assertTrue(yt["meets_minimum"])
        self.assertEqual("meets_minimum", yt["version_status"])
        self.assertIsNone(yt["latest_version"])
        self.assertIsNone(yt["update_available"])
        self.assertNotIn("sk-", yt["upgrade_command"])
        self.assertEqual("22.16.0", results["javascript_runtime"]["version"])
        self.assertTrue(results["javascript_runtime"]["installed"])

    def test_outdated_ytdlp_is_installed_but_requires_update(self):
        results, _fetch = self._versioned_check("2026.6.30")
        yt = results["yt_dlp"]
        self.assertTrue(yt["installed"])
        self.assertFalse(yt["ok"])
        self.assertFalse(yt["meets_minimum"])
        self.assertEqual("update_required", yt["version_status"])
        self.assertTrue(any("低于最低要求" in item for item in results["warnings"]))

    def test_explicit_update_check_reports_latest_status(self):
        results, fetch = self._versioned_check(
            "2026.7.4", check_updates=True, latest=("2026.8.1", None))
        fetch.assert_called_once_with()
        yt = results["yt_dlp"]
        self.assertEqual("2026.8.1", yt["latest_version"])
        self.assertTrue(yt["update_available"])
        self.assertEqual("update_available", yt["version_status"])

    def test_update_check_failure_is_warning_only(self):
        results, _fetch = self._versioned_check(
            check_updates=True, latest=(None, "更新检查失败（URLError）"))
        yt = results["yt_dlp"]
        self.assertTrue(yt["ok"])
        self.assertEqual("meets_minimum", yt["version_status"])
        self.assertEqual("更新检查失败（URLError）", yt["update_check_error"])
        self.assertIn("更新检查失败（URLError）", results["warnings"])


if __name__ == "__main__":
    unittest.main()
