"""Pipeline: download, extract audio, transcribe, export."""
import base64
import json
import locale
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import bilibili, douyin
from .job_manager import Job, JobType, OUTPUT_DIR
from scripts.platform_utils import find_executable


MIN_MEDIA_BYTES = 1024


class PipelineError(RuntimeError):
    """Classified acquisition failure suitable for UI and trace output."""

    def __init__(self, message, *, code="PIPELINE_ERROR"):
        super().__init__(message)
        self.code = code


def _read_config():
    """Read modern UTF-8 config and legacy GB18030 Windows config safely."""

    try:
        path = Path.home() / ".video2doc" / "config.json"
    except (OSError, RuntimeError):
        return {}
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            payload = json.loads(raw.decode(encoding))
            return payload if isinstance(payload, dict) else {}
        except (UnicodeError, json.JSONDecodeError):
            continue
    return {}


def _get_api_key():
    """Read the SiliconFlow key only from explicit Video2Doc configuration."""
    key = os.environ.get("SILICONFLOW_API_KEY", "")
    if key: return key
    d = _read_config()
    if d.get("siliconflow_api_key"):
        return d["siliconflow_api_key"]
    return ""

def resolve_url(url):
    curl = find_executable(["curl", "curl.exe"])
    if not curl:
        return url
    try:
        r = subprocess.run(
            [curl, "-sI", "-o", os.devnull, "-w", "%{url_effective}", "-L", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10)
        return r.stdout.strip() or url
    except Exception:
        return url

def _download_xhs_initial_state(url, raw_dir, job):
    """小红书下载：解析页面 __INITIAL_STATE__ 提视频直链（移动端 UA，cookie 可选）。

    比纯 yt-dlp+cookie 稳：移动端 UA 更宽容，结构化数据优先，masterUrl 直链下载。
    参考 chubbyguan/chubbyskills。可选 XHS_COOKIE 环境变量提高成功率。
    返回视频路径或 None。
    """
    UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
    curl = find_executable(["curl", "curl.exe"]) or "curl"
    cookie = os.environ.get("XHS_COOKIE", "")
    try:
        # 1) 抓页面（移动端 UA + Referer，可选 cookie）
        hdr = ["-H", f"User-Agent: {UA}", "-H", "Referer: https://www.xiaohongshu.com/"]
        if cookie:
            hdr += ["-H", f"Cookie: {cookie}"]
        r = subprocess.run([curl, "-s", "-L"] + hdr + [url],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        html = r.stdout
        # 风控检测
        if "请通过小红书" in html or "verify" in html.lower()[:2000]:
            job.error = "小红书风控拦截（建议设 XHS_COOKIE 环境变量）"
            return None
        # 2) 括号配平提取 __INITIAL_STATE__（比 }</script> 正则稳）
        idx = html.find("__INITIAL_STATE__")
        if idx == -1:
            job.error = "小红书: __INITIAL_STATE__ 未找到"
            return None
        brace = html.find("{", idx)
        if brace == -1:
            return None
        depth, in_str, esc, end = 0, False, False, -1
        for i, ch in enumerate(html[brace:]):
            if esc: esc = False; continue
            if ch == "\\": esc = True; continue
            if ch == '"': in_str = not in_str; continue
            if in_str: continue
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0: end = brace + i + 1; break
        if end < 0:
            return None
        raw = re.sub(r"([:,\[]\s*)undefined\b", r"\1null", html[brace:end])
        state = json.loads(raw)
        # 3) 递归找 note（含 interactInfo + desc/title）
        note = [None]
        def walk(o):
            if note[0] is not None: return
            if isinstance(o, dict):
                if "interactInfo" in o and ("desc" in o or "title" in o):
                    note[0] = o; return
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        # 优先走已知路径
        try:
            nm = state["note"]["noteDetailMap"]
            for v in nm.values():
                if isinstance(v, dict) and v.get("note"): note[0] = v["note"]; break
        except Exception:
            pass
        if note[0] is None:
            walk(state)
        if note[0] is None:
            job.error = "小红书: 未定位到 note 对象"
            return None
        if not job.title:
            job.title = (note[0].get("title") or "").strip()
        # 4) 提视频直链 masterUrl（h264/h265/h266/av1）
        video = note[0].get("video") or {}
        stream = (video.get("media") or {}).get("stream") or {}
        vurl = None
        for codec in ("h264", "h265", "h266", "av1"):
            for item in (stream.get(codec) or []):
                if item.get("masterUrl"): vurl = item["masterUrl"]; break
            if vurl: break
        if not vurl:
            found = [None]
            def w2(o):
                if found[0] is not None: return
                if isinstance(o, dict):
                    if isinstance(o.get("masterUrl"), str): found[0] = o["masterUrl"]; return
                    for v in o.values(): w2(v)
                elif isinstance(o, list):
                    for v in o: w2(v)
            w2(video); vurl = found[0]
        if not vurl:
            job.error = "小红书: 未提取到视频直链（可能是图文笔记，非视频）"
            return None
        # 5) 下载视频
        out = raw_dir / "video.mp4"
        subprocess.run([curl, "-s", "-L", "-o", str(out)] + hdr + [vurl],
                       timeout=300, check=True)
        if out.exists() and out.stat().st_size > 100000:
            return str(out)
        job.error = "小红书: 下载文件过小或为空"
        return None
    except Exception as e:
        job.error = f"小红书下载失败: {e}"
        return None


def _safe_message(message):
    text = str(message or "").strip()
    text = re.sub(r"sk-[A-Za-z0-9]+", "sk-***", text)
    text = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?<redacted>", text)
    return text[:600]


def _write_download_trace(job):
    trace_dir = job.dir / "raw"
    trace_dir.mkdir(parents=True, exist_ok=True)
    source = ""
    try:
        match = re.search(r"https?://[^\s<>\"']+", str(job.url or ""))
        if match:
            parsed = urllib.parse.urlsplit(match.group(0))
            source = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, "", "")
            )
    except (TypeError, ValueError):
        source = ""
    payload = {
        "source": source,
        "download_strategy": getattr(job, "download_strategy", ""),
        "attempts": getattr(job, "attempts", []),
    }
    (trace_dir / "download.trace.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def _record_attempt(
    job,
    strategy,
    status,
    *,
    error_code="",
    message="",
    elapsed_ms=None,
    details=None,
):
    attempt = {
        "strategy": strategy,
        "status": status,
        "error_code": error_code,
        "message": _safe_message(message),
    }
    if elapsed_ms is not None:
        attempt["elapsed_ms"] = elapsed_ms
    if details:
        attempt["details"] = {
            key: value
            for key, value in details.items()
            if key not in {"url", "cookie", "cookies", "api_key"}
        }
    if not hasattr(job, "attempts"):
        job.attempts = []
    job.attempts.append(attempt)
    if status == "success":
        job.download_strategy = strategy
    _write_download_trace(job)


def _decode_process_output(raw):
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _cookie_args(platform):
    """Return only explicitly configured cookie sources.

    Reading a live Chrome profile is never implicit: Windows Chrome may lock
    the SQLite database, and a browser login is not automatically inherited by
    this process.
    """

    config = _read_config()
    prefix = platform.upper()
    cookie_file = (
        os.environ.get(f"VIDEO2DOC_{prefix}_COOKIES_FILE")
        or os.environ.get("VIDEO2DOC_COOKIES_FILE")
        or config.get(f"{platform}_cookies_file")
        or config.get("cookies_file")
    )
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if not path.is_file():
            raise PipelineError(
                f"配置的 cookies.txt 不存在：{path}",
                code="COOKIE_FILE_NOT_FOUND",
            )
        return ["--cookies", str(path)], "cookies_file"

    browser = (
        os.environ.get(f"VIDEO2DOC_{prefix}_COOKIES_BROWSER")
        or os.environ.get("VIDEO2DOC_COOKIES_BROWSER")
        or config.get(f"{platform}_cookies_browser")
        or config.get("cookies_browser")
    )
    if browser:
        return ["--cookies-from-browser", str(browser)], f"browser:{browser}"
    return [], "none"


def _classify_ytdlp_error(output):
    lowered = output.lower()
    if "could not copy chrome cookie database" in lowered or (
        "permissionerror" in lowered and "network\\cookies" in lowered
    ):
        return (
            "COOKIE_DB_LOCKED",
            "Chrome 正在占用 Cookie 数据库；请改用导出的 cookies.txt。",
        )
    if "http error 412" in lowered or "precondition failed" in lowered:
        return (
            "BILI_WBI_412",
            "yt-dlp 的 B站 WBI 请求返回 412；已停止同路径盲目重试。",
        )
    if "fresh cookies" in lowered:
        return (
            "COOKIE_STALE_OR_REQUIRED",
            "该提取器需要新鲜 Cookie；默认不会读取正在运行的 Chrome。",
        )
    if "private video" in lowered or "login required" in lowered:
        return "AUTH_REQUIRED", "视频需要登录或当前账号无权访问。"
    if "timed out" in lowered or "timeout" in lowered:
        return "NETWORK_TIMEOUT", "yt-dlp 请求超时。"
    if "unsupported url" in lowered:
        return "UNSUPPORTED_URL", "yt-dlp 暂不支持该链接类型。"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return "YTDLP_FAILED", _safe_message(lines[-1] if lines else "yt-dlp 下载失败。")


def _ffprobe(path):
    ffprobe = find_executable(["ffprobe", "ffprobe.exe"])
    if not ffprobe:
        raise PipelineError("未找到 ffprobe。", code="FFPROBE_MISSING")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise PipelineError("ffprobe 无法读取媒体文件。", code="MEDIA_INVALID")
    try:
        return json.loads(_decode_process_output(result.stdout))
    except json.JSONDecodeError as exc:
        raise PipelineError("ffprobe 返回无效 JSON。", code="MEDIA_INVALID") from exc


def validate_media(path, *, require_audio, require_video=False, expected_duration=0):
    path = Path(path)
    if not path.is_file() or path.stat().st_size < MIN_MEDIA_BYTES:
        raise PipelineError("媒体文件为空或过小。", code="MEDIA_INCOMPLETE")
    probe = _ffprobe(path)
    streams = probe.get("streams") or []
    stream_types = {stream.get("codec_type") for stream in streams}
    if require_audio and "audio" not in stream_types:
        raise PipelineError("媒体文件没有音轨。", code="MEDIA_NO_AUDIO")
    if require_video and "video" not in stream_types:
        raise PipelineError("媒体文件没有视频轨。", code="MEDIA_NO_VIDEO")
    try:
        duration = float((probe.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise PipelineError("媒体时长无效。", code="MEDIA_INVALID_DURATION")
    if expected_duration:
        difference = abs(duration - float(expected_duration))
        if difference > 5 and difference / float(expected_duration) > 0.05:
            raise PipelineError(
                f"媒体时长异常：预期约 {expected_duration:.1f}s，实际 {duration:.1f}s。",
                code="MEDIA_DURATION_MISMATCH",
            )
    return {
        "bytes": path.stat().st_size,
        "duration": duration,
        "stream_types": sorted(item for item in stream_types if item),
    }


def _merge_streams(video_path, audio_path, output_path):
    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe"])
    if not ffmpeg:
        raise PipelineError("未找到 ffmpeg。", code="FFMPEG_MISSING")
    output_path = Path(output_path)
    partial = output_path.with_name(output_path.stem + ".part" + output_path.suffix)
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(partial),
        ],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0 or not partial.exists() or partial.stat().st_size < MIN_MEDIA_BYTES:
        if partial.exists():
            partial.unlink()
        raise PipelineError("ffmpeg 合并音视频失败。", code="FFMPEG_MERGE_FAILED")
    partial.replace(output_path)
    return output_path


def _set_media_metadata(job, metadata):
    if metadata.get("title"):
        job.title = str(metadata["title"])
    try:
        duration = float(metadata.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration:
        job.duration = f"{int(duration) // 60:02d}:{int(duration) % 60:02d}"


def _run_ytdlp(
    job,
    url,
    output_dir,
    *,
    platform,
    format_selector=None,
    require_video=True,
):
    yt = find_executable(["yt-dlp", "yt-dlp.exe"])
    if not yt:
        raise PipelineError("未找到 yt-dlp，请执行 pip install yt-dlp。", code="YTDLP_MISSING")
    cookie_args, cookie_mode = _cookie_args(platform)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"yt-{uuid.uuid4().hex[:8]}"
    output_template = str(output_dir / f"{stem}.%(ext)s")
    command = [
        yt,
        "--ignore-config",
        "--no-playlist",
        "--no-progress",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--socket-timeout",
        "20",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "all",
        "--sub-format",
        "srt/vtt/best",
        "-o",
        output_template,
    ]
    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe"])
    if ffmpeg:
        command.extend(["--ffmpeg-location", str(Path(ffmpeg).parent)])
    if format_selector:
        command.extend(["-f", format_selector])
    command.extend(cookie_args)
    command.append(url)
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        _record_attempt(
            job,
            f"{platform}.yt_dlp",
            "failed",
            error_code="NETWORK_TIMEOUT",
            message="yt-dlp 超过30分钟仍未完成。",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            details={"cookie_mode": cookie_mode},
        )
        raise PipelineError("yt-dlp 下载超时。", code="NETWORK_TIMEOUT") from exc
    elapsed = int((time.monotonic() - started) * 1000)
    output = _decode_process_output(result.stdout) + "\n" + _decode_process_output(result.stderr)
    if result.returncode != 0:
        code, message = _classify_ytdlp_error(output)
        _record_attempt(
            job,
            f"{platform}.yt_dlp",
            "failed",
            error_code=code,
            message=message,
            elapsed_ms=elapsed,
            details={"cookie_mode": cookie_mode, "returncode": result.returncode},
        )
        raise PipelineError(message, code=code)
    media_suffixes = {
        ".aac", ".flac", ".flv", ".m4a", ".mkv", ".mov", ".mp3",
        ".mp4", ".ogg", ".opus", ".ts", ".wav", ".webm",
    }
    candidates = [
        path
        for path in output_dir.glob(f"{stem}.*")
        if path.suffix.lower() in media_suffixes
        and path.is_file()
        and path.stat().st_size >= MIN_MEDIA_BYTES
    ]
    if not candidates:
        raise PipelineError("yt-dlp 没有生成有效媒体文件。", code="MEDIA_INCOMPLETE")
    candidate = max(candidates, key=lambda path: path.stat().st_size)
    validation = validate_media(
        candidate,
        require_audio=True,
        require_video=require_video,
    )
    prefix = "video" if require_video else "audio-source"
    final_path = output_dir / f"{prefix}{candidate.suffix.lower()}"
    candidate.replace(final_path)
    _record_attempt(
        job,
        f"{platform}.yt_dlp",
        "success",
        elapsed_ms=elapsed,
        details={"cookie_mode": cookie_mode, **validation},
    )
    return final_path


def _extract_first_url(value):
    match = re.search(r"https?://[^\s<>\"']+", str(value or ""))
    if not match:
        raise PipelineError("输入中没有找到 http(s) 视频链接。", code="INPUT_NO_URL")
    return match.group(0).rstrip("，。；;！!）)]}")


def _resolve_platform_url(value):
    url = _extract_first_url(value)
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host != "b23.tv":
        return url
    request = urllib.request.Request(url, headers={"User-Agent": bilibili.USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read(1)
            return response.geturl()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PipelineError("B站短链解析失败。", code="SHORTLINK_RESOLVE_FAILED") from exc


def _download_subtitles_only(job, url):
    """Fetch platform subtitles without downloading the full video."""

    yt = find_executable(["yt-dlp", "yt-dlp.exe"])
    if not yt:
        return False
    raw_dir = job.dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        cookie_args, cookie_mode = _cookie_args("bilibili")
    except PipelineError as exc:
        _record_attempt(
            job,
            "bilibili.subtitle_config",
            "failed",
            error_code=exc.code,
            message=exc,
        )
        cookie_args, cookie_mode = [], "none"
    command = [
        yt,
        "--ignore-config",
        "--no-playlist",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "all",
        "--sub-format",
        "srt/best",
        "--convert-subs",
        "srt",
        "-o",
        str(raw_dir / "subtitle.%(ext)s"),
        *cookie_args,
        url,
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _record_attempt(
            job,
            "bilibili.platform_subtitles",
            "failed",
            error_code="SUBTITLE_FETCH_FAILED",
            message=exc,
        )
        return False
    elapsed = int((time.monotonic() - started) * 1000)
    files = [path for path in raw_dir.glob("*.srt") if path.stat().st_size >= 50]
    if result.returncode == 0 and files:
        _record_attempt(
            job,
            "bilibili.platform_subtitles",
            "success",
            elapsed_ms=elapsed,
            details={"cookie_mode": cookie_mode, "subtitle_count": len(files)},
        )
        return True
    output = _decode_process_output(result.stdout) + "\n" + _decode_process_output(result.stderr)
    code, message = _classify_ytdlp_error(output)
    _record_attempt(
        job,
        "bilibili.platform_subtitles",
        "failed",
        error_code=code,
        message=message,
        elapsed_ms=elapsed,
        details={"cookie_mode": cookie_mode},
    )
    return False


def _download_bilibili_video(job, source, raw_dir):
    tried_ytdlp = False
    try:
        cookie_args, _ = _cookie_args("bilibili")
    except PipelineError as exc:
        _record_attempt(job, "bilibili.auth_config", "failed", error_code=exc.code, message=exc)
        cookie_args = []
    if cookie_args:
        tried_ytdlp = True
        try:
            return _run_ytdlp(job, source, raw_dir, platform="bilibili")
        except PipelineError:
            pass
    started = time.monotonic()
    try:
        video_track, audio_track, metadata = bilibili.acquire_av(source, raw_dir)
        output_path = _merge_streams(video_track, audio_track, raw_dir / "video.mp4")
        validation = validate_media(
            output_path,
            require_audio=True,
            require_video=True,
            expected_duration=float(metadata.get("duration") or 0),
        )
        _set_media_metadata(job, metadata)
        _record_attempt(
            job,
            "bilibili.public_api_dash",
            "success",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            details=validation,
        )
        return output_path
    except (bilibili.BilibiliError, PipelineError) as exc:
        code = getattr(exc, "kind", getattr(exc, "code", "BILI_API_ERROR"))
        _record_attempt(
            job,
            "bilibili.public_api_dash",
            "failed",
            error_code=code,
            message=exc,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        if not tried_ytdlp:
            return _run_ytdlp(job, source, raw_dir, platform="bilibili")
        raise PipelineError("登录画质与公共 DASH 路径均失败。", code=code)


def _download_douyin_video(job, source, raw_dir):
    errors = []
    started = time.monotonic()
    try:
        output_path, metadata = douyin.acquire_muxed(source, raw_dir)
        validation = validate_media(
            output_path,
            require_audio=True,
            require_video=True,
            expected_duration=float(metadata.get("duration") or 0),
        )
        _set_media_metadata(job, metadata)
        _record_attempt(
            job,
            "douyin.mobile_ssr_mp4",
            "success",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            details={**validation, "cookie_mode": metadata.get("cookie_mode")},
        )
        return output_path
    except (douyin.DouyinError, PipelineError) as exc:
        error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "DOUYIN_ERROR")))
        errors.append(error)
        _record_attempt(
            job,
            "douyin.mobile_ssr_mp4",
            "failed",
            error_code=error.code,
            message=error,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    started = time.monotonic()
    try:
        video_track, audio_track, metadata = douyin.acquire_av(source, raw_dir)
        output_path = _merge_streams(video_track, audio_track, raw_dir / "video.mp4")
        validation = validate_media(
            output_path,
            require_audio=True,
            require_video=True,
            expected_duration=float(metadata.get("duration") or 0),
        )
        _set_media_metadata(job, metadata)
        _record_attempt(
            job,
            "douyin.playwright_dash",
            "success",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            details={**validation, "cookie_mode": metadata.get("cookie_mode")},
        )
        return output_path
    except (douyin.DouyinError, PipelineError) as exc:
        error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "DOUYIN_ERROR")))
        errors.append(error)
        _record_attempt(
            job,
            "douyin.playwright_dash",
            "failed",
            error_code=error.code,
            message=error,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    try:
        cookie_args, _ = _cookie_args("douyin")
    except PipelineError as exc:
        errors.append(exc)
        _record_attempt(job, "douyin.auth_config", "failed", error_code=exc.code, message=exc)
        cookie_args = []
    if cookie_args:
        try:
            return _run_ytdlp(job, source, raw_dir, platform="douyin")
        except PipelineError as exc:
            errors.append(exc)
    started = time.monotonic()
    try:
        recorded = douyin.record_with_media_recorder(source, raw_dir / "video.webm")
        validation = validate_media(recorded, require_audio=True, require_video=True)
        _record_attempt(
            job,
            "douyin.media_recorder",
            "success",
            elapsed_ms=int((time.monotonic() - started) * 1000),
            details=validation,
        )
        return recorded
    except (douyin.DouyinError, PipelineError) as exc:
        error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "DOUYIN_ERROR")))
        errors.append(error)
        _record_attempt(
            job,
            "douyin.media_recorder",
            "failed",
            error_code=error.code,
            message=error,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    final = errors[-1] if errors else PipelineError("没有可用的抖音下载策略。")
    raise PipelineError(f"抖音全部下载路径均失败。最后错误：{final}", code=final.code)


def download_video(job):
    """Platform-aware full-video download preserving v0.7 transcription features."""

    try:
        source = _resolve_platform_url(job.url)
        job.url = source
        job.status = "downloading"
        job.progress = max(int(getattr(job, "progress", 0) or 0), 20)
        raw_dir = job.dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        if bilibili.is_bilibili_url(source):
            result = _download_bilibili_video(job, source, raw_dir)
        elif douyin.is_douyin_url(source):
            result = _download_douyin_video(job, source, raw_dir)
        elif "xiaohongshu.com" in source or "xhslink.com" in source:
            result = _download_xhs_initial_state(source, raw_dir, job)
            if result:
                try:
                    validation = validate_media(result, require_audio=True, require_video=True)
                    _record_attempt(job, "xiaohongshu.initial_state", "success", details=validation)
                except PipelineError:
                    result = None
            if not result:
                result = _run_ytdlp(job, source, raw_dir, platform="xiaohongshu")
        else:
            result = _run_ytdlp(job, source, raw_dir, platform="generic")
        job.error = None
        job.error_code = ""
        return str(result)
    except PipelineError as exc:
        job.error = _safe_message(exc)
        job.error_code = exc.code
        return None
    except Exception as exc:
        job.error = _safe_message(exc)
        job.error_code = "UNEXPECTED_ERROR"
        return None


def acquire_transcription_audio(job):
    """Acquire the smallest valid audio asset for Bilibili and Douyin ASR."""

    source = _resolve_platform_url(job.url)
    job.url = source
    raw_dir = job.dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    if bilibili.is_bilibili_url(source):
        started = time.monotonic()
        try:
            audio_path, metadata = bilibili.acquire_audio(source, raw_dir)
            validation = validate_media(
                audio_path,
                require_audio=True,
                expected_duration=float(metadata.get("duration") or 0),
            )
            _set_media_metadata(job, metadata)
            _record_attempt(
                job,
                "bilibili.public_api_audio",
                "success",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                details=validation,
            )
            return Path(audio_path)
        except (bilibili.BilibiliError, PipelineError) as exc:
            error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "BILI_API_ERROR")))
            errors.append(error)
            _record_attempt(
                job,
                "bilibili.public_api_audio",
                "failed",
                error_code=error.code,
                message=error,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        try:
            return _run_ytdlp(
                job,
                source,
                raw_dir,
                platform="bilibili",
                format_selector="bestaudio/best",
                require_video=False,
            )
        except PipelineError as exc:
            errors.append(exc)
    elif douyin.is_douyin_url(source):
        started = time.monotonic()
        try:
            audio_path, metadata = douyin.acquire_audio(source, raw_dir)
            validation = validate_media(
                audio_path,
                require_audio=True,
                expected_duration=float(metadata.get("duration") or 0),
            )
            _set_media_metadata(job, metadata)
            _record_attempt(
                job,
                "douyin.playwright_audio",
                "success",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                details={**validation, "cookie_mode": metadata.get("cookie_mode")},
            )
            return Path(audio_path)
        except (douyin.DouyinError, PipelineError) as exc:
            error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "DOUYIN_ERROR")))
            errors.append(error)
            _record_attempt(
                job,
                "douyin.playwright_audio",
                "failed",
                error_code=error.code,
                message=error,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        started = time.monotonic()
        try:
            video_path, metadata = douyin.acquire_muxed(source, raw_dir)
            validation = validate_media(
                video_path,
                require_audio=True,
                require_video=True,
                expected_duration=float(metadata.get("duration") or 0),
            )
            audio_path = raw_dir / "audio.mp3"
            if not extract_audio(video_path, audio_path):
                raise PipelineError("音频提取失败。", code="AUDIO_EXTRACTION_FAILED")
            validate_media(audio_path, require_audio=True)
            _set_media_metadata(job, metadata)
            _record_attempt(
                job,
                "douyin.mobile_ssr_mp4",
                "success",
                elapsed_ms=int((time.monotonic() - started) * 1000),
                details={**validation, "cookie_mode": metadata.get("cookie_mode")},
            )
            return audio_path
        except (douyin.DouyinError, PipelineError) as exc:
            error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "DOUYIN_ERROR")))
            errors.append(error)
            _record_attempt(
                job,
                "douyin.mobile_ssr_mp4",
                "failed",
                error_code=error.code,
                message=error,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        try:
            cookie_args, _ = _cookie_args("douyin")
        except PipelineError as exc:
            errors.append(exc)
            _record_attempt(job, "douyin.auth_config", "failed", error_code=exc.code, message=exc)
            cookie_args = []
        if cookie_args:
            try:
                return _run_ytdlp(
                    job,
                    source,
                    raw_dir,
                    platform="douyin",
                    format_selector="bestaudio/best",
                    require_video=False,
                )
            except PipelineError as exc:
                errors.append(exc)
        started = time.monotonic()
        try:
            recorded = douyin.record_with_media_recorder(source, raw_dir / "video.webm")
            validate_media(recorded, require_audio=True, require_video=True)
            audio_path = raw_dir / "audio.mp3"
            if not extract_audio(recorded, audio_path):
                raise PipelineError("音频提取失败。", code="AUDIO_EXTRACTION_FAILED")
            _record_attempt(
                job,
                "douyin.media_recorder",
                "success",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            return audio_path
        except (douyin.DouyinError, PipelineError) as exc:
            error = PipelineError(str(exc), code=getattr(exc, "kind", getattr(exc, "code", "DOUYIN_ERROR")))
            errors.append(error)
            _record_attempt(
                job,
                "douyin.media_recorder",
                "failed",
                error_code=error.code,
                message=error,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
    else:
        return None
    final = errors[-1] if errors else PipelineError("没有可用的下载策略。", code="NO_DOWNLOAD_STRATEGY")
    job.error_code = final.code
    raise PipelineError(f"所有下载路径均失败。最后错误：{final}", code=final.code)

def download_video_only(job):
    """Pure download — 复用 download_video 的平台策略与媒体校验，
    视频移到 job.dir/ 根目录，供 server /api/download/{id}/{file} 直供下载。"""
    video = download_video(job)  # 下载到 job.dir/raw/video.mp4（含所有平台优化 + 字幕）
    if not video:
        if not job.error: job.error = "下载失败"
        return None
    # 移到 job.dir/ 根目录，供 server /api/download/{id}/{file} 服务
    src = Path(video)
    dst = job.dir / src.name
    if src.resolve() != dst.resolve():
        shutil.move(str(src), str(dst))
    job.download_path = str(dst)
    job.files = [{"name": "Video", "file": dst.name, "size": dst.stat().st_size}]
    return str(dst)

def extract_audio(video_path, output_path):
    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe",
                              str(Path.home() / ".workbuddy/binaries/ffmpeg/ffmpeg")])
    if not ffmpeg:
        return False
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(output_path.stem + ".part" + output_path.suffix)
    try:
        if partial.exists():
            partial.unlink()
        result = subprocess.run(
            [ffmpeg, "-i", str(video_path), "-vn", "-acodec", "libmp3lame",
             "-q:a", "2", "-y", str(partial)],
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0 or not partial.exists() or partial.stat().st_size < MIN_MEDIA_BYTES:
            if partial.exists():
                partial.unlink()
            return False
        partial.replace(output_path)
        return True
    except (OSError, subprocess.SubprocessError):
        if partial.exists():
            partial.unlink()
        return False

def _get_doubao_key():
    """读取豆包语音 API Key：环境变量 → Video2Doc 专用配置。"""
    key = os.environ.get("DOUBAO_API_KEY", "")
    if key: return key
    d = _read_config()
    if d.get("doubao_api_key"):
        return d["doubao_api_key"]
    return ""


def _transcribe_doubao(audio_path, job):
    """云端转录：豆包录音文件识别大模型 2.0（异步 submit+query，base64 内联音频）。

    云端首选引擎。中文准确度高（实测优于 TeleSpeechASR）、自带标点+ITN+词级时间戳。
    需 DOUBAO_API_KEY。音频自动用 ffmpeg 重采样到 16kHz 单声道。

    实现要点（对齐官方文档 docs/6561/1354868）：
    - 异步：submit 提交(X-Api-Sequence:-1) → 用同一 X-Api-Request-Id 轮询 query。
    - 状态码在响应头 X-Api-Status-Code（非 body）：20000000 成功 / 20000001 处理中 /
      20000002 排队 / 20000003 静音 / 4xxxxx·5xxxxx 错误。
    - 音频官方文档仅列 audio.url；audio.data(base64 内联) 实测可用但非文档字段。
    - 用 urllib 而非 curl：规避 ARG_MAX 限制、可直接读响应头。
    返回归一化 {text, segments} 或 None（无 Key/失败时落到下一级）。
    """
    key = _get_doubao_key()
    if not key:
        return None  # 无 Key → 落到下一级
    import urllib.request, urllib.error
    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe",
                              str(Path.home() / ".workbuddy/binaries/ffmpeg/ffmpeg")])
    submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
    logid = ""
    try:
        # 1) 重采样到 16kHz 单声道 mp3（豆包要求 16k）
        tmp_16k = None
        if ffmpeg:
            tmp_16k = Path(job.dir) / "raw" / "audio_16k.mp3"
            tmp_16k.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([ffmpeg, "-y", "-i", str(audio_path), "-ar", "16000",
                            "-ac", "1", str(tmp_16k)],
                           capture_output=True, timeout=180)
        src = tmp_16k if (tmp_16k and tmp_16k.exists()) else Path(audio_path)
        # 2) base64 内联（实测可用；官方文档仅列 audio.url，待充分验证）
        b64 = base64.b64encode(src.read_bytes()).decode()
        rid = str(uuid.uuid4())
        body = json.dumps({
            "user": {"uid": "video2doc"},
            "audio": {"data": b64, "format": "mp3", "codec": "raw",
                      "rate": 16000, "bits": 16, "channel": 1},
            "request": {"model_name": "bigmodel", "enable_itn": True,
                        "enable_punc": True, "enable_ddc": False,
                        "enable_speaker_info": False, "enable_channel_split": False,
                        "show_utterances": True, "vad_segment": False,
                        "sensitive_words_filter": ""}
        }).encode("utf-8")
        base_hdr = {"Content-Type": "application/json",
                    "x-api-key": key,
                    "X-Api-Resource-Id": "volc.seedasr.auc",
                    "X-Api-Request-Id": rid}
        # 3) submit（X-Api-Sequence:-1 仅 submit 需要）
        submit_req = urllib.request.Request(
            submit_url, data=body,
            headers=dict(base_hdr, **{"X-Api-Sequence": "-1"}), method="POST")
        try:
            with urllib.request.urlopen(submit_req, timeout=60) as resp:
                s_status = resp.headers.get("X-Api-Status-Code", "")
                s_msg = resp.headers.get("X-Api-Message", "")
                logid = resp.headers.get("X-Tt-Logid", "")
            if s_status and s_status != "20000000":
                job.error = f"豆包 submit 失败: status={s_status} msg={s_msg} logid={logid}"
                return None
        except urllib.error.HTTPError as e:
            job.error = f"豆包 submit HTTP 错误: {e.code} {e.reason}"
            return None
        # 4) 轮询 query（按响应头状态码判定，最多 ~90s）
        data = None
        for _ in range(30):
            qreq = urllib.request.Request(query_url, data=b"{}",
                                          headers=base_hdr, method="POST")
            try:
                with urllib.request.urlopen(qreq, timeout=30) as resp:
                    q_status = resp.headers.get("X-Api-Status-Code", "")
                    q_msg = resp.headers.get("X-Api-Message", "")
                    logid = resp.headers.get("X-Tt-Logid", "") or logid
                    raw = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                job.error = f"豆包 query HTTP 错误: {e.code} {e.reason}"
                return None
            try:
                d = json.loads(raw) if raw else {}
            except Exception:
                d = {}
            res = d.get("result")
            if q_status == "20000000":
                if res and (res.get("text") or res.get("utterances")):
                    data = d
                    break
                # 成功但无内容（可能静音）
                job.error = f"豆包: 成功但无识别内容(可能静音) logid={logid}"
                return None
            elif q_status in ("20000001", "20000002"):
                time.sleep(3)  # 处理中/排队中 → 继续轮询
                continue
            elif q_status == "20000003":
                job.error = f"豆包: 未检测到人声(静音音频) logid={logid}"
                return None
            elif q_status and (q_status.startswith("4") or q_status.startswith("5")):
                job.error = f"豆包 query 错误: status={q_status} msg={q_msg} logid={logid}"
                return None
            else:
                time.sleep(3)  # 无状态头 → 兜底继续轮询
        if not data:
            if not job.error:
                job.error = f"豆包转录超时或无结果 logid={logid}"
            return None
        # 5) 归一化为 {text, segments}（ms → s）
        result = data.get("result", {})
        text = result.get("text", "")
        segs = []
        for u in result.get("utterances", []):
            segs.append({
                "id": len(segs),
                "start": u.get("start_time", 0) / 1000.0,
                "end": u.get("end_time", 0) / 1000.0,
                "text": u.get("text", "").strip()
            })
        if not segs and text:
            dur = data.get("audio_info", {}).get("duration", 0)
            segs.append({"id": 0, "start": 0,
                         "end": dur / 1000.0 if dur else 0, "text": text})
        return {"text": text, "segments": segs}
    except Exception as e:
        job.error = f"豆包转录失败: {e} logid={logid}"
        return None


def _transcribe_tele(audio_path, job):
    """云端转录：硅基流动 TeleSpeechASR（同步 API）。需 SILICONFLOW_API_KEY。"""
    api_key = _get_api_key()
    if not api_key:
        return None  # 无 Key → 落到下一级
    curl = find_executable(["curl", "curl.exe"]) or "curl"
    try:
        r = subprocess.run(
            [curl, "-s", "--max-time", "120", "--retry", "3", "--retry-delay", "2",
             "https://api.siliconflow.cn/v1/audio/transcriptions",
             "-H", "@-",
             "-F", f"file=@{audio_path}",
             "-F", "model=TeleAI/TeleSpeechASR",
             "-F", "response_format=verbose_json"],
            input=f"Authorization: Bearer {api_key}\r\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=130)
        data = json.loads(r.stdout)
        if data and data.get("text"):
            return data
        job.error = "TeleSpeechASR 返回空结果"
    except Exception as e:
        job.error = f"TeleSpeechASR 失败: {e}"
    return None


# 引擎注册表（在 transcribe() 内构建，避免定义顺序问题）：
#   doubao(云端首选,中文最准) → tele(云端兜底) → funasr(本地首选) → whisper(本地末位)


def transcribe(audio_path, job):
    """Transcribe audio. 引擎由 job.engine 决定（默认 auto）。

    - auto: 豆包 → TeleSpeechASR → FunASR → Whisper 自动降级（首选额度耗尽/不稳定时
      静默切到下一级，并在 engine_note 里提示用户）。
    - local_only: auto 仅尝试 FunASR → Whisper；显式选择云引擎会直接拒绝。
    - doubao/tele/funasr/whisper: 仅用指定引擎；失败时 error 提示可切换其他引擎。
    返回 {text, segments} 或 None。成功时 job.engine_used 记录所用引擎。
    """
    engines = [("doubao", _transcribe_doubao), ("tele", _transcribe_tele),
               ("funasr", _transcribe_funasr), ("whisper", _transcribe_whisper)]
    local_engines = [("funasr", _transcribe_funasr), ("whisper", _transcribe_whisper)]
    engine_map = dict(engines)
    engine = (getattr(job, "engine", None) or "auto").lower()
    local_only = bool(getattr(job, "local_only", False))
    if local_only and engine in ("doubao", "tele"):
        job.error = (f"local_only 模式不允许云端引擎「{engine}」；"
                     "请选择 funasr、whisper 或 auto")
        return None
    if engine == "auto":
        order = local_engines if local_only else engines
    else:
        fn = engine_map.get(engine)
        if not fn:
            job.error = f"未知引擎: {engine}（可选 doubao/tele/funasr/whisper/auto）"
            return None
        order = [(engine, fn)]

    failed = []
    failure_notes = []
    for name, fn in order:
        previous_error = job.error
        r = fn(audio_path, job)
        if r and r.get("text"):
            job.error = None
            job.engine_used = name
            job.engine_note = (f"已自动切换到「{name}」（{'→'.join(failed)} 不可用）"
                               if (engine == "auto" and failed) else "")
            return r
        failed.append(name)
        if job.error and job.error != previous_error:
            failure_notes.append(f"{name}: {_safe_message(job.error)}")

    # 全部失败
    if engine == "auto":
        scope = "本地引擎" if local_only else "所有引擎"
        detail = f" 最后错误：{failure_notes[-1]}" if failure_notes else ""
        job.error = (f"{scope}均失败（{'→'.join(failed)}）。{detail}"
                     " 可在「引擎」下拉切换后重试。")
    else:
        base = job.error or f"{engine} 转录失败"
        job.error = f"{base}（可切换其他引擎重试：引擎下拉选择）"
    return None


def _transcribe_funasr(audio_path, job):
    """本地转录：FunASR Paraformer（离线、无需 API Key）。

    中文场景比 Whisper 更快更准，自带 VAD + 标点 + ITN。
    需: pip install funasr（首次运行下载约 300MB 模型到 ~/.cache/modelscope/）。
    """
    try:
        from funasr import AutoModel
    except Exception:
        return None  # 未安装 / torch 损坏 → 落到下一级
    try:
        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
        except Exception:
            pass
        model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device=device,
        )
        res = model.generate(input=str(audio_path), batch_size_s=300)
        if not res:
            return None
        segments = []
        parts = []
        for item in res:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            ts = item.get("timestamp") or []
            start = end = 0.0
            if isinstance(ts, list) and len(ts) > 0:
                first = ts[0]
                last = ts[-1]
                if isinstance(first, (list, tuple)) and len(first) >= 1:
                    start = float(first[0]) / 1000.0
                if isinstance(last, (list, tuple)) and len(last) >= 2:
                    end = float(last[1]) / 1000.0
            segments.append({"id": len(segments), "start": start, "end": end, "text": text})
            parts.append(text)
        if not segments:
            return None
        # 时间戳缺失时，用 ffprobe 取音频总时长兜底给末段
        if all(s["end"] == 0 for s in segments):
            try:
                fp = find_executable(["ffprobe", "ffprobe.exe",
                                      str(Path.home() / ".workbuddy/binaries/ffmpeg/ffprobe")])
                if fp:
                    r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                                        "-of", "csv=p=0", str(audio_path)],
                                       capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=30)
                    dur = float(r.stdout.strip()) if r.stdout.strip() else 0
                    if dur:
                        segments[-1]["end"] = dur
            except Exception:
                pass
        return {"text": "".join(parts), "segments": segments}
    except Exception as e:
        job.error = f"FunASR 本地转录失败: {e}"
        return None


def _transcribe_whisper(audio_path, job):
    """末位兜底：本地 Whisper（离线、多语言）。

    仅当无云端 Key 且 FunASR 未安装/失败时使用。中文用 turbo 模型。
    需: pip install openai-whisper（首次下载约 1.5GB 模型）。
    """
    try:
        import whisper
    except Exception:
        return None
    try:
        configured = (
            os.environ.get("VIDEO2DOC_WHISPER_MODEL")
            or _read_config().get("whisper_model")
            or "turbo"
        )
        allowed_models = {
            "tiny", "tiny.en", "base", "base.en", "small", "small.en",
            "medium", "medium.en", "large", "large-v1", "large-v2",
            "large-v3", "large-v3-turbo", "turbo",
        }
        model_name = configured if configured in allowed_models else "turbo"
        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), language="zh")
        segs = result.get("segments", [])
        segments = [{"id": i, "start": s.get("start", 0), "end": s.get("end", 0),
                     "text": (s.get("text") or "").strip()} for i, s in enumerate(segs)]
        return {"text": result.get("text", ""), "segments": segments}
    except Exception as e:
        job.error = f"Whisper 本地转录失败: {e}"
        return None

def _fmt_time(seconds):
    h, m = divmod(int(seconds), 3600)
    m, s = divmod(m, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def to_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_time(seg.get("start", 0))
        end = _fmt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if text: lines.extend([str(i), f"{start} --> {end}", text, ""])
    return "\n".join(lines)

def _enrich_transcript(text, job):
    """content-enrich：用 LLM(SiliconFlow chat) 给文稿补 摘要+要点+标签。best-effort，失败返回 None。"""
    key = _get_api_key()  # SiliconFlow key 同时支持 chat
    if not key or not text or len(text) < 20:
        return None
    snippet = text[:4000]
    prompt = ("请阅读下面视频文稿，输出 JSON：{\"summary\":\"一句话摘要\","
              "\"keypoints\":[\"要点1\",\"要点2\",...],\"tags\":[\"标签1\",...]}。"
              "要点3-5条，标签3-5个。只输出 JSON。\n\n文稿：\n" + snippet)
    body = json.dumps({
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3, "max_tokens": 700,
    }).encode("utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.siliconflow.cn/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=70) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return None
    except Exception:
        return None  # 增强失败不阻断主流程


def _should_enrich(job):
    """Return whether cloud transcript enrichment is allowed for this job."""
    formats = {str(item).strip().lower() for item in getattr(job, "formats", [])}
    supports_enrichment = bool(formats & {"md", "json", "all"})
    return (bool(getattr(job, "allow_enrichment", True))
            and not bool(getattr(job, "local_only", False))
            and supports_enrichment)


def _enrichment_block(enrichment):
    """把 enrich 结果渲染成 Markdown 摘要块。"""
    if not enrichment:
        return ""
    lines = ["## 📝 摘要", ""]
    if enrichment.get("summary"):
        lines += ["> " + enrichment["summary"], ""]
    kp = enrichment.get("keypoints") or []
    if kp:
        lines += ["**要点：**", ""]
        lines += [f"- {k}" for k in kp]
        lines.append("")
    tags = enrichment.get("tags") or []
    if tags:
        lines += ["**标签：** " + " ".join(f"`{t}`" for t in tags), ""]
    lines += ["---", ""]
    return "\n".join(lines)


def export_formats(job, transcript, enrichment=None):
    exported = []
    segments = transcript.get("segments", [])
    full_text = transcript.get("text", "")
    head = _enrichment_block(enrichment)

    for fmt in job.formats:
        fmt = fmt.strip()
        if fmt == "all":
            fmt_list = ["md", "txt", "json", "srt"]
        else:
            fmt_list = [fmt]
        for f in fmt_list:
            if f == "md":
                p = job.dir / "transcript.md"
                p.write_text(head + full_text if head else full_text, encoding="utf-8")
                exported.append({"name":"Markdown","file":"transcript.md","size":p.stat().st_size})
            elif f == "txt":
                p = job.dir / "transcript.txt"
                p.write_text(full_text, encoding="utf-8")
                exported.append({"name":"TXT","file":"transcript.txt","size":p.stat().st_size})
            elif f == "json":
                p = job.dir / "transcript.json"
                p.write_text(json.dumps({"segments":segments,"total":len(segments),"enrichment":enrichment},ensure_ascii=False,indent=2),encoding="utf-8")
                exported.append({"name":"JSON","file":"transcript.json","size":p.stat().st_size})
            elif f == "srt":
                p = job.dir / "transcript.srt"
                p.write_text(to_srt(segments), encoding="utf-8")
                exported.append({"name":"SRT","file":"transcript.srt","size":p.stat().st_size})
    return exported

def _parse_srt_to_transcript(srt_path):
    """解析 SRT 字幕 → {text, segments}（与 ASR 输出同构）。失败返回 None。"""
    try:
        content = Path(srt_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    segments = []
    parts = []
    for blk in re.split(r'\n\s*\n', content.strip()):
        lines = [l for l in blk.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        tline = None
        tidx = 0
        for i, l in enumerate(lines):
            if '-->' in l:
                tline = l
                tidx = i
                break
        if not tline:
            continue
        m = re.match(r'\s*(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', tline)
        if m:
            g = m.groups()
            start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
            end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
        else:
            m2 = re.match(r'\s*(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+)[,.](\d+)', tline)
            if not m2:
                continue
            g = m2.groups()
            start = int(g[0]) * 60 + int(g[1]) + int(g[2]) / 1000
            end = int(g[3]) * 60 + int(g[4]) + int(g[5]) / 1000
        text = ' '.join(lines[tidx + 1:]).strip()
        if not text:
            continue
        segments.append({"id": len(segments), "start": start, "end": end, "text": text})
        parts.append(text)
    if not segments:
        return None
    return {"text": " ".join(parts), "segments": segments}


def _try_subtitle_transcript(job):
    """字幕优先：扫描 raw/ 下平台字幕（B站 ai-zh.srt 优先，其次任意 .srt），
    有则解析为 {text, segments} 返回，无则 None。仅 engine=auto 时调用。"""
    raw = job.dir / "raw"
    if not raw.exists():
        return None
    cands = []
    for p in raw.glob("*.srt"):
        name = p.name.lower()
        if "ai-zh" in name or "ai_cn" in name or name.endswith(".zh.srt"):
            cands.insert(0, p)
        elif "zh" in name:
            cands.append(p)
    if not cands:
        cands = list(raw.glob("*.srt"))
    for p in cands:
        try:
            if p.stat().st_size < 50:
                continue
        except Exception:
            continue
        t = _parse_srt_to_transcript(p)
        if t and t.get("text"):
            t["_subtitle_source"] = p.name
            return t
    return None


def run_transcribe_pipeline(job):
    """Online pipeline: subtitles first, otherwise audio-first acquisition → ASR → export."""
    try:
        job.status = "resolving"
        job.progress = 10
        source = _resolve_platform_url(job.url)
        job.url = source
        transcript = None
        audio = None
        video = None
        engine = (getattr(job, "engine", "auto") or "auto").lower()
        platform_audio_first = (
            bilibili.is_bilibili_url(source) or douyin.is_douyin_url(source)
        )

        # B站 auto 模式先单独抓字幕；有字幕时不下载媒体，也不消耗 ASR。
        if engine == "auto" and bilibili.is_bilibili_url(source):
            job.status = "downloading"
            job.progress = 20
            _download_subtitles_only(job, source)
            transcript = _try_subtitle_transcript(job)
            if transcript:
                job.engine_used = "subtitle"
                job.engine_note = "使用平台字幕（免 ASR）"
                job.error = None

        if not transcript:
            if platform_audio_first:
                job.status = "downloading"
                job.progress = 30
                audio = acquire_transcription_audio(job)
            else:
                video = download_video(job)
                if not video:
                    raise PipelineError(
                        job.error or "视频下载失败",
                        code=job.error_code or "DOWNLOAD_FAILED",
                    )
                # 保留 v0.6 对 YouTube/通用站点的字幕优先能力。
                if engine == "auto":
                    transcript = _try_subtitle_transcript(job)
                    if transcript:
                        job.engine_used = "subtitle"
                        job.engine_note = "使用平台字幕（免 ASR）"
                        job.error = None
                if not transcript:
                    job.status = "extracting"
                    job.progress = 40
                    audio = job.dir / "raw" / "audio.mp3"
                    audio.parent.mkdir(parents=True, exist_ok=True)
                    if not extract_audio(video, audio):
                        raise PipelineError("音频提取失败", code="AUDIO_EXTRACTION_FAILED")

        if not transcript:
            job.status = "transcribing"; job.progress = 60
            transcript = transcribe(audio, job)
            if not transcript:
                raise PipelineError(job.error or "转录失败", code="TRANSCRIPTION_FAILED")

        (job.dir / "raw" / "tele_result.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
        if not job.title:
            job.title = ((transcript.get("text", "")[:80] + "...")
                         if len(transcript.get("text", "")) > 80
                         else transcript.get("text", ""))
        segs = transcript.get("segments",[])
        if segs and not job.duration:
            t = segs[-1].get("end",0)
            job.duration = f"{int(t)//60:02d}:{int(t)%60:02d}"

        job.status = "exporting"; job.progress = 85
        enrichment = (_enrich_transcript(transcript.get("text", ""), job)
                      if _should_enrich(job) else None)
        job.files = export_formats(job, transcript, enrichment)
        job.status = "done"; job.progress = 100
        job.error = None
        job.error_code = ""
    except PipelineError as e:
        job.status = "error"
        job.error = _safe_message(e)
        job.error_code = e.code
    except Exception as e:
        job.status = "error"
        job.error = _safe_message(e)
        job.error_code = "UNEXPECTED_ERROR"

def run_local_pipeline(job, file_path):
    """Pipeline for local file transcription"""
    try:
        fp = Path(file_path)
        job.status = "extracting"; job.progress = 20

        is_video = fp.suffix.lower() in {".mp4",".mov",".mkv",".webm",".avi",".flv"}
        audio_path = job.dir / "raw" / "audio.mp3"
        audio_path.parent.mkdir(exist_ok=True)

        if is_video:
            if not extract_audio(str(fp), audio_path):
                job.status = "error"; job.error = "音频提取失败"; return
        else:
            # 音频文件：若已是目标路径(如上传文件就叫 audio.mp3)则直接用，否则复制
            if fp.resolve() != audio_path.resolve():
                shutil.copy2(str(fp), audio_path)

        job.status = "transcribing"; job.progress = 50
        transcript = transcribe(audio_path, job)
        if not transcript:
            job.status = "error"
            if not job.error: job.error = "转录失败"
            return

        (job.dir / "raw" / "tele_result.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
        job.title = getattr(job, "local_filename", "") or fp.name
        segs = transcript.get("segments",[])
        if segs:
            t = segs[-1].get("end",0)
            job.duration = f"{int(t)//60:02d}:{int(t)%60:02d}"

        job.status = "exporting"; job.progress = 85
        enrichment = (_enrich_transcript(transcript.get("text", ""), job)
                      if _should_enrich(job) else None)
        job.files = export_formats(job, transcript, enrichment)
        job.status = "done"; job.progress = 100
    except Exception as e:
        job.status = "error"; job.error = str(e)

def run_download_pipeline(job):
    """Pure download pipeline"""
    try:
        job.status = "resolving"; job.progress = 20
        job.status = "downloading"; job.progress = 50
        video = download_video_only(job)
        if not video:
            job.status = "error"; job.error = "下载失败"
            return
        job.status = "done"; job.progress = 100
    except Exception as e:
        job.status = "error"; job.error = str(e)
