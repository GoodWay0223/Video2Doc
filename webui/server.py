"""HTTP Server: request handler, routing, and request-boundary validation."""
import http.server
import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, job_manager, pipeline, templates


OUTPUT_DIR = Path(__file__).parent.parent / "output"
MAX_JSON_BODY_BYTES = 64 * 1024
# Raw (application/octet-stream) uploads are streamed straight to disk, so the
# limit is about disk use, not memory. Legacy multipart uploads are parsed in
# memory and keep the smaller historical limit.
MAX_UPLOAD_FILE_BYTES = 4 * 1024 * 1024 * 1024
MAX_MULTIPART_FILE_BYTES = 200 * 1024 * 1024
# Multipart headers and boundaries add a small amount beyond the file itself.
MAX_UPLOAD_BODY_BYTES = MAX_MULTIPART_FILE_BYTES + 1024 * 1024
STREAM_CHUNK_SIZE = 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

ALLOWED_PLATFORM_DOMAINS = (
    "douyin.com",
    "iesdouyin.com",
    "bilibili.com",
    "b23.tv",
    "youtube.com",
    "youtu.be",
    "xiaohongshu.com",
    "xhslink.com",
)
ALLOWED_FORMATS = {"md", "txt", "json", "srt", "all"}
ALLOWED_ENGINES = {"auto", "doubao", "tele", "funasr", "whisper"}
ALLOWED_UPLOAD_SUFFIXES = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv",
}

PUBLIC_PLATFORMS = (
    {"id": "douyin", "label": "抖音", "experimental": False},
    {"id": "bilibili", "label": "B站", "experimental": False},
    {"id": "youtube", "label": "YouTube", "experimental": False},
    {"id": "xiaohongshu", "label": "小红书", "experimental": True},
)

PUBLIC_COMPONENT_FIELDS = (
    "name", "version", "minimum_version", "latest_version", "version_status",
)
PUBLIC_VERSION_STATUSES = {
    "meets_minimum", "update_required", "unknown", "not_installed",
    "up_to_date", "update_available", "newer_than_latest",
}


def _public_component(checks, name):
    """Copy only version metadata that is safe to expose to the local Web UI."""
    raw = checks.get(name, {})
    if not isinstance(raw, dict):
        raw = {}
    component = {
        "installed": bool(raw.get("installed", raw.get("ok", False))),
    }
    for field in PUBLIC_COMPONENT_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value or len(value) > 80:
            continue
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            continue
        if field == "version_status" and value not in PUBLIC_VERSION_STATUSES:
            continue
        component[field] = value
    for field in ("meets_minimum", "update_available"):
        value = raw.get(field)
        if isinstance(value, bool):
            component[field] = value
    if raw.get("update_check_error"):
        component["update_check_failed"] = True
    return component


def get_public_capabilities(*, check_updates=False):
    """Return runtime readiness without exposing paths, messages, or credentials."""
    try:
        from scripts import check_setup
        checks = check_setup.check_all(check_updates=check_updates)
    except Exception:
        checks = {}

    def ready(name):
        value = checks.get(name, {})
        return bool(value.get("ok")) if isinstance(value, dict) else False

    engines = {
        "doubao": ready("doubao"),
        "tele": ready("siliconflow"),
        "funasr": ready("funasr"),
        "whisper": ready("whisper"),
    }
    return {
        "version": __version__,
        "max_upload_bytes": MAX_UPLOAD_FILE_BYTES,
        "download_tools_ready": (
            ready("ffmpeg") and ready("ffprobe")
            and ready("curl") and ready("yt_dlp")
        ),
        "transcription_configured": any(engines.values()),
        # Enrichment uses in-process HTTPS and only needs the explicit SiliconFlow key;
        # TeleSpeech additionally needs curl, so the two readiness flags can differ.
        "enrichment_configured": bool(pipeline._get_api_key()),
        "engines": engines,
        "subtitle_first": True,
        "formats": ["md", "txt", "json", "srt"],
        "platforms": list(PUBLIC_PLATFORMS),
        "components": {
            name: _public_component(checks, name)
            for name in ("python", "ffmpeg", "ffprobe", "curl", "yt_dlp",
                         "javascript_runtime")
        },
    }


class RequestValidationError(Exception):
    """An expected client error that should be returned as JSON."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def validate_platform_url(value):
    """Extract and validate an advertised platform URL without accepting lookalikes."""
    if not isinstance(value, str):
        raise RequestValidationError("链接必须是字符串")
    raw_value = value.strip()
    if not raw_value:
        raise RequestValidationError("未提供链接")

    # Platform share actions often copy a sentence rather than a bare URL.
    match = re.search(r"https?://[^\s<>\"']+", raw_value, re.IGNORECASE)
    if not match:
        raise RequestValidationError("未找到有效链接")
    value = match.group(0).rstrip(".,;!?，。；！？）》】}]")
    if "\\" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise RequestValidationError("链接格式无效")

    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        raise RequestValidationError("链接格式无效") from None

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise RequestValidationError("仅支持 http/https 链接")
    if parsed.username is not None or parsed.password is not None:
        raise RequestValidationError("链接不得包含用户凭据")

    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or not any(host == domain or host.endswith("." + domain)
                           for domain in ALLOWED_PLATFORM_DOMAINS):
        raise RequestValidationError("不支持该链接域名")

    expected_port = 80 if scheme == "http" else 443
    if port is not None and port != expected_port:
        raise RequestValidationError("链接端口不受支持")
    return value


def parse_formats(value):
    if not isinstance(value, str):
        raise RequestValidationError("formats 必须是字符串")
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not formats or any(item not in ALLOWED_FORMATS for item in formats):
        raise RequestValidationError("formats 参数无效")
    return formats


def validate_engine(value):
    if not isinstance(value, str):
        raise RequestValidationError("engine 必须是字符串")
    engine = value.strip().lower()
    if engine not in ALLOWED_ENGINES:
        raise RequestValidationError("engine 参数无效")
    return engine


def parse_bool(value, field, default=False):
    """Parse a strict boolean from JSON booleans or multipart text fields."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    raise RequestValidationError(f"{field} 必须是布尔值")


def optional_string(data, field, default=None, max_length=128):
    if field not in data:
        return default
    value = data[field]
    if value is None and default is None:
        return None
    if not isinstance(value, str):
        raise RequestValidationError(f"{field} 必须是字符串")
    if len(value) > max_length:
        raise RequestValidationError(f"{field} 过长")
    return value


def clean_original_filename(filename):
    """Create display-only metadata from an untrusted multipart filename."""
    if not isinstance(filename, str):
        return "uploaded-media"
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    leaf = "".join("_" if ord(ch) < 32 or ord(ch) == 127 else ch for ch in leaf)
    if not leaf or leaf in {".", ".."}:
        return "uploaded-media"
    return leaf[:180]


def upload_storage_name(original_filename):
    """Generate the on-disk name; only a conservative extension is retained."""
    display_name = clean_original_filename(original_filename)
    match = re.search(r"(\.[A-Za-z0-9]{1,10})$", display_name)
    suffix = match.group(1).lower() if match else ""
    return "uploaded-media" + suffix


def _split_host(value):
    """Return the lowercase hostname from a Host/Origin authority."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed_hosts_for(bind_host):
    """Hosts accepted in the Host header; None means any (explicit LAN mode)."""
    bind_host = (bind_host or "").strip().lower().strip("[]")
    if bind_host in {"", "0.0.0.0", "::"}:
        return None
    return LOOPBACK_HOSTS | {bind_host}


class Handler(http.server.BaseHTTPRequestHandler):
    # Configured by webui.py. Rejecting unknown Host headers blocks DNS
    # rebinding: a malicious page cannot read this loopback API via its own name.
    allowed_hosts = frozenset(LOOPBACK_HOSTS)

    def log_message(self, format, *args):
        pass

    def _request_allowed(self, *, state_changing=False):
        host_header = self.headers.get("Host")
        allowed = self.allowed_hosts
        if host_header and allowed is not None and _split_host(host_header) not in allowed:
            self._send_json({"error": "不允许的 Host"}, 403)
            return False
        if state_changing:
            # Browsers always attach Origin / Sec-Fetch-Site to cross-site POSTs,
            # so this rejects CSRF from other websites without breaking the UI.
            origin = self.headers.get("Origin")
            if origin and origin != "null":
                origin_authority = urlparse(origin).netloc.lower()
                if not host_header or origin_authority != host_header.strip().lower():
                    self._send_json({"error": "拒绝跨站请求"}, 403)
                    return False
            elif origin == "null" or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self._send_json({"error": "拒绝跨站请求"}, 403)
                return False
        return True

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, filename=None):
        path = Path(path)
        download_name = filename or path.name
        if not templates.is_safe_filename(download_name):
            self._send_json({"error": "无效文件名"}, 400)
            return
        try:
            file_size = path.stat().st_size
            source = path.open("rb")
        except (FileNotFoundError, IsADirectoryError, OSError):
            self._send_json({"error": "文件不存在"}, 404)
            return

        with source:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            try:
                shutil.copyfileobj(source, self.wfile, STREAM_CHUNK_SIZE)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The browser cancelled the download.

    def _content_length(self, max_bytes):
        transfer_encoding = self.headers.get("Transfer-Encoding", "").strip().lower()
        if transfer_encoding and transfer_encoding != "identity":
            raise RequestValidationError("不支持 Transfer-Encoding 请求体")

        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestValidationError("缺少 Content-Length", 411)
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise RequestValidationError("Content-Length 无效") from None
        if length < 0:
            raise RequestValidationError("Content-Length 无效")
        if length > max_bytes:
            raise RequestValidationError("请求体过大", 413)
        return length

    def _read_body(self, max_bytes):
        length = self._content_length(max_bytes)
        body = self.rfile.read(length)
        if len(body) != length:
            raise RequestValidationError("请求体不完整")
        return body

    def _read_json(self):
        body = self._read_body(MAX_JSON_BODY_BYTES)
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RequestValidationError("JSON 格式无效") from None
        if not isinstance(data, dict):
            raise RequestValidationError("JSON 请求体必须是对象")
        return data

    # ─── GET ───────────────────────────────
    def do_GET(self):
        if not self._request_allowed():
            return
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            html = templates.load_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path.startswith("/api/status/"):
            jid = unquote(path[len("/api/status/"):])
            if not templates.is_safe_job_id(jid):
                self._send_json({"error": "无效任务 ID"}, 400)
                return
            job = job_manager.get_job(jid)
            if not job:
                self._send_json({"error": "任务未找到"}, 404)
                return
            self._send_json(job.to_dict())
            return

        if path.startswith("/api/content/"):
            parts = path.split("/")
            if len(parts) != 5:
                self._send_json({"error": "无效路径"}, 400)
                return
            jid, content_type = unquote(parts[3]), unquote(parts[4])
            if not templates.is_safe_job_id(jid):
                self._send_json({"error": "无效任务 ID"}, 400)
                return
            if content_type not in {"text", "md", "srt", "json"}:
                self._send_json({"error": "无效内容类型"}, 400)
                return
            content = templates.read_content(jid, content_type)
            if content is not None:
                self._send_json({"content": content, "type": content_type})
            else:
                self._send_json({"error": "内容不存在"}, 404)
            return

        if path.startswith("/api/download/"):
            parts = path.split("/")
            if len(parts) != 5:
                self._send_json({"error": "无效路径"}, 400)
                return
            jid, filename = unquote(parts[3]), unquote(parts[4])
            file_path = templates.resolve_job_file(jid, filename)
            if file_path is None:
                self._send_json({"error": "无效文件路径"}, 400)
                return
            self._send_file(file_path, filename)
            return

        if path == "/api/history":
            self._send_json(job_manager.get_history())
            return

        if path == "/api/capabilities":
            self._send_json(get_public_capabilities())
            return

        if path == "/api/component-updates":
            self._send_json(get_public_capabilities(check_updates=True))
            return

        self._send_json({"error": "未找到"}, 404)

    # ─── POST ──────────────────────────────
    def do_POST(self):
        if not self._request_allowed(state_changing=True):
            return
        try:
            self._handle_post()
        except RequestValidationError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except Exception:
            # Do not expose local paths, command details, or credentials in HTTP errors.
            self._send_json({"error": "服务器内部错误"}, 500)

    def _handle_post(self):
        path = urlparse(self.path).path

        if path in ("/api/process", "/api/transcribe-online"):
            data = self._read_json()
            url = validate_platform_url(data.get("url"))
            formats = parse_formats(data.get("formats", "md"))
            engine = validate_engine(data.get("engine", "auto"))
            mode = optional_string(data, "mode", "transcript", 32)
            domain = optional_string(data, "domain", None, 64)
            local_only = parse_bool(data.get("local_only"), "local_only", False)
            allow_enrichment = parse_bool(
                data.get("allow_enrichment"), "allow_enrichment", True)
            if local_only:
                allow_enrichment = False

            job = job_manager.Job(
                url=url,
                job_type=job_manager.JobType.TRANSCRIBE_ONLINE,
                mode=mode,
                formats=formats,
                domain=domain,
                engine=engine,
                local_only=local_only,
                allow_enrichment=allow_enrichment,
            )
            job_manager.add_job(job)
            job_manager.submit(job, pipeline.run_transcribe_pipeline)
            self._send_json({"job_id": job.id, "status": "queued"})
            return

        if path == "/api/download-video":
            data = self._read_json()
            url = validate_platform_url(data.get("url"))
            engine = validate_engine(data.get("engine", "auto"))
            transcribe = parse_bool(data.get("transcribe"), "transcribe", False)
            allow_enrichment = parse_bool(
                data.get("allow_enrichment"), "allow_enrichment", True)

            job = job_manager.Job(
                url=url,
                job_type=job_manager.JobType.DOWNLOAD,
                engine=engine,
                allow_enrichment=allow_enrichment,
            )
            job_manager.add_job(job)
            if transcribe:
                job.type = job_manager.JobType.TRANSCRIBE_ONLINE
                target = pipeline.run_transcribe_pipeline
            else:
                target = pipeline.run_download_pipeline
            job_manager.submit(job, target)
            self._send_json({"job_id": job.id, "status": "queued"})
            return

        if path == "/api/transcribe-local":
            self._handle_local_upload()
            return

        self._send_json({"error": "未找到"}, 404)

    def _handle_local_upload(self):
        content_type = self.headers.get("Content-Type", "").lower()
        if content_type.startswith("application/octet-stream"):
            self._handle_raw_upload()
        elif "multipart/form-data" in content_type:
            self._handle_multipart_upload()
        else:
            raise RequestValidationError("需要 application/octet-stream 或 multipart/form-data")

    def _create_local_job(self, original_filename, formats_value, engine_value,
                          local_only_value, allow_enrichment_value):
        formats = parse_formats(formats_value)
        engine = validate_engine(engine_value)
        local_only = parse_bool(local_only_value, "local_only", False)
        allow_enrichment = parse_bool(
            allow_enrichment_value, "allow_enrichment", True)
        if local_only:
            allow_enrichment = False
        display_filename = clean_original_filename(original_filename)
        if Path(display_filename).suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
            raise RequestValidationError("不支持该媒体文件格式")
        storage_filename = upload_storage_name(original_filename)

        job = job_manager.Job(
            job_type=job_manager.JobType.TRANSCRIBE_LOCAL,
            formats=formats,
            engine=engine,
            local_only=local_only,
            allow_enrichment=allow_enrichment,
        )
        job.local_filename = display_filename

        job_root = job.dir.resolve()
        raw_dir = (job_root / "raw").resolve()
        try:
            raw_dir.relative_to(job_root)
        except ValueError:
            raise RequestValidationError("任务目录无效", 500) from None
        raw_dir.mkdir(parents=True, exist_ok=True)
        file_path = (raw_dir / storage_filename).resolve()
        try:
            file_path.relative_to(raw_dir)
        except ValueError:
            raise RequestValidationError("上传文件路径无效", 500) from None
        return job, file_path

    def _start_local_job(self, job, file_path, size):
        job.local_filesize = size
        job_manager.add_job(job)
        job_manager.submit(job, pipeline.run_local_pipeline, str(file_path))
        self._send_json({"job_id": job.id, "status": "queued"})

    def _handle_raw_upload(self):
        """Stream the request body to disk: memory use stays constant for any size."""
        query = parse_qs(urlparse(self.path).query)

        def field(name, default):
            values = query.get(name)
            return values[-1] if values else default

        length = self._content_length(MAX_UPLOAD_FILE_BYTES)
        if length == 0:
            raise RequestValidationError("未收到文件")
        job, file_path = self._create_local_job(
            field("filename", ""), field("formats", "md"), field("engine", "auto"),
            field("local_only", "false"), field("allow_enrichment", "true"))
        partial = file_path.with_name(file_path.name + ".part")
        remaining = length
        try:
            with partial.open("wb") as output:
                while remaining:
                    chunk = self.rfile.read(min(STREAM_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise RequestValidationError("请求体不完整")
                    output.write(chunk)
                    remaining -= len(chunk)
            partial.replace(file_path)
        except BaseException:
            # Only the directory created for this request is removed.
            shutil.rmtree(job.dir, ignore_errors=True)
            raise
        self._start_local_job(job, file_path, length)

    def _handle_multipart_upload(self):
        content_type = self.headers.get("Content-Type", "")
        boundary = None
        for item in content_type.split(";"):
            item = item.strip()
            if item.lower().startswith("boundary="):
                boundary = item.split("=", 1)[1].strip().strip('"')
                break
        if not boundary or len(boundary) > 200 or "\r" in boundary or "\n" in boundary:
            raise RequestValidationError("缺少或无效 boundary")
        try:
            boundary_bytes = boundary.encode("ascii")
        except UnicodeEncodeError:
            raise RequestValidationError("boundary 必须为 ASCII") from None

        body = self._read_body(MAX_UPLOAD_BODY_BYTES)
        parts = body.split(b"--" + boundary_bytes)
        file_data = None
        original_filename = None
        fields = {"formats": "md", "engine": "auto",
                  "local_only": "false", "allow_enrichment": "true"}

        for part in parts:
            separator = b"\r\n\r\n" if b"\r\n\r\n" in part else b"\n\n"
            if separator not in part:
                continue
            header_section, content = part.split(separator, 1)
            if content.endswith(b"\r\n"):
                content = content[:-2]
            elif content.endswith(b"\n"):
                content = content[:-1]
            header_string = header_section.decode("iso-8859-1", errors="replace")

            filename_match = re.search(r'filename="([^"]*)"', header_string, re.IGNORECASE)
            if filename_match:
                original_filename = filename_match.group(1)
                file_data = content
                continue
            name_match = re.search(r'name="([^"]*)"', header_string, re.IGNORECASE)
            if name_match and name_match.group(1) in fields:
                fields[name_match.group(1)] = content.decode("utf-8", errors="replace").strip()

        if file_data is None or original_filename is None or not file_data:
            raise RequestValidationError("未收到文件")
        if len(file_data) > MAX_MULTIPART_FILE_BYTES:
            raise RequestValidationError("multipart 上传超过 200MB 限制", 413)

        job, file_path = self._create_local_job(
            original_filename, fields["formats"], fields["engine"],
            fields["local_only"], fields["allow_enrichment"])
        file_path.write_bytes(file_data)
        self._start_local_job(job, file_path, len(file_data))

    def do_OPTIONS(self):
        # Same-origin API: retain a standards-compliant response without enabling CORS.
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()
