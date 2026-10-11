"""Bilibili public-video acquisition helpers.

The narrow, transcript-oriented path intentionally uses Bilibili's ordinary
web APIs instead of yt-dlp's WBI playurl endpoint.  It is designed for public
BV/av videos and falls back to yt-dlp in ``pipeline.py`` for unsupported or
restricted content.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API_ROOT = "https://api.bilibili.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
_BVID_RE = re.compile(r"(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])")
_AID_RE = re.compile(r"(?:^|/)(?:av)?(\d+)(?:[/?#]|$)", re.IGNORECASE)


class BilibiliError(RuntimeError):
    """A classified Bilibili acquisition failure."""

    def __init__(self, message: str, *, kind: str = "BILI_API_ERROR", status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def is_bilibili_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "b23.tv" or host.endswith(".bilibili.com") or host == "bilibili.com"


def parse_video_id(url: str) -> dict[str, str | int]:
    """Return a query dictionary containing either ``bvid`` or ``aid``."""

    match = _BVID_RE.search(url)
    if match:
        return {"bvid": match.group(1)}

    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    match = re.search(r"/video/av(\d+)$", path, re.IGNORECASE)
    if match:
        return {"aid": int(match.group(1))}

    raise BilibiliError(
        "暂不支持该 B 站链接类型；标准 BV/av 视频将自动走直连音轨。",
        kind="BILI_UNSUPPORTED_URL",
    )


def _headers(referer: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": referer or "https://www.bilibili.com/",
    }


def _request_json(
    endpoint: str,
    params: dict[str, object],
    *,
    referer: str | None = None,
    timeout: float = 20,
    transient_retries: int = 2,
) -> dict:
    """Fetch JSON, retrying only transient network/429/5xx failures.

    HTTP 412 is deliberately not retried with identical parameters because it
    normally represents a risk-control decision rather than a transient socket
    failure.
    """

    url = f"{API_ROOT}{endpoint}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None

    for attempt in range(transient_retries + 1):
        request = urllib.request.Request(url, headers=_headers(referer))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            code = payload.get("code", 0)
            if code != 0:
                raise BilibiliError(
                    f"B站接口返回 code={code}: {payload.get('message') or '未知错误'}",
                    kind="BILI_API_CODE",
                )
            return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            status = exc.code
            exc.close()
            if status == 412:
                raise BilibiliError(
                    "B站接口返回 HTTP 412，已停止同路径盲目重试。",
                    kind="BILI_HTTP_412",
                    status=412,
                ) from exc
            if status in {429} or status >= 500:
                if attempt < transient_retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
            raise BilibiliError(
                f"B站接口 HTTP {status}",
                kind="BILI_HTTP_ERROR",
                status=status,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < transient_retries:
                time.sleep(0.5 * (2**attempt))
                continue
            raise BilibiliError(
                "连接 B 站接口超时或网络不可达。",
                kind="BILI_NETWORK_ERROR",
            ) from exc
        except json.JSONDecodeError as exc:
            raise BilibiliError(
                "B站接口没有返回有效 JSON。",
                kind="BILI_INVALID_JSON",
            ) from exc

    raise BilibiliError(str(last_error or "B站接口请求失败"))


def fetch_metadata(url: str) -> dict:
    video_id = parse_video_id(url)
    payload = _request_json("/x/web-interface/view", video_id, referer=url)
    data = payload.get("data") or {}
    pages = data.get("pages") or []
    if not pages:
        raise BilibiliError("B站视频没有可用分P信息。", kind="BILI_NO_PAGES")

    requested_page = 1
    try:
        requested_page = max(1, int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("p", ["1"])[0]))
    except (TypeError, ValueError):
        requested_page = 1
    page = pages[min(requested_page - 1, len(pages) - 1)]

    return {
        "bvid": data.get("bvid"),
        "aid": data.get("aid"),
        "cid": page.get("cid"),
        "page": page.get("page", requested_page),
        "part": page.get("part") or "",
        "title": data.get("title") or "",
        "uploader": (data.get("owner") or {}).get("name") or "",
        "uploader_id": (data.get("owner") or {}).get("mid"),
        "duration": page.get("duration") or data.get("duration") or 0,
        "source": f"https://www.bilibili.com/video/{data.get('bvid')}/"
        if data.get("bvid")
        else url,
    }


def fetch_dash(metadata: dict, *, quality: int = 64) -> dict:
    params = {
        "cid": metadata["cid"],
        "qn": quality,
        "fnval": 16,
        "fourk": 0,
        # Without this flag anonymous requests are capped at 480p; with it the
        # public player serves 720p/1080p previews, still without any cookie.
        "try_look": 1,
    }
    if metadata.get("bvid"):
        params["bvid"] = metadata["bvid"]
    else:
        params["avid"] = metadata["aid"]

    payload = _request_json(
        "/x/player/playurl",
        params,
        referer=metadata.get("source"),
    )
    dash = (payload.get("data") or {}).get("dash")
    if not dash:
        raise BilibiliError(
            "该视频没有公开 DASH 流，交由 yt-dlp 兼容路径处理。",
            kind="BILI_NO_DASH",
        )
    return dash


def stream_urls(stream: dict) -> list[str]:
    urls: list[str] = []
    for key in ("baseUrl", "base_url"):
        value = stream.get(key)
        if value:
            urls.append(value)
    for key in ("backupUrl", "backup_url"):
        value = stream.get(key) or []
        if isinstance(value, str):
            value = [value]
        urls.extend(item for item in value if item)
    return list(dict.fromkeys(urls))


def select_audio_stream(dash: dict) -> dict:
    streams = dash.get("audio") or []
    if not streams:
        raise BilibiliError("DASH 中没有音轨。", kind="BILI_NO_AUDIO")
    return max(streams, key=lambda item: int(item.get("bandwidth") or 0))


def select_video_stream(dash: dict) -> dict:
    streams = dash.get("video") or []
    if not streams:
        raise BilibiliError("DASH 中没有视频轨。", kind="BILI_NO_VIDEO")

    def score(item: dict) -> tuple[int, int, int, int]:
        codec = str(item.get("codecs") or "").lower()
        avc_compatible = 1 if codec.startswith(("avc", "h264")) else 0
        return (
            int(item.get("height") or 0),
            int(item.get("width") or 0),
            avc_compatible,
            int(item.get("bandwidth") or 0),
        )

    return max(streams, key=score)


def download_stream(
    candidates: list[str],
    target: Path,
    *,
    referer: str,
    expected_size: int | None = None,
    timeout: float = 120,
) -> Path:
    """Download to a temporary file and atomically replace the final target."""

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    last_error: Exception | None = None

    for url in candidates:
        try:
            request = urllib.request.Request(url, headers=_headers(referer))
            with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
                content_length = response.headers.get("Content-Length")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)

            size = partial.stat().st_size
            required = expected_size or (int(content_length) if content_length else 0)
            if size <= 0 or (required and size != required):
                raise BilibiliError(
                    f"媒体下载不完整：期望 {required} 字节，实际 {size} 字节。",
                    kind="MEDIA_INCOMPLETE",
                )
            partial.replace(target)
            return target
        except Exception as exc:  # Try backup CDN URLs before failing.
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if partial.exists():
                partial.unlink()

    if isinstance(last_error, BilibiliError):
        raise last_error
    raise BilibiliError(
        f"B站 CDN 下载失败：{last_error}",
        kind="BILI_CDN_ERROR",
    ) from last_error


def _write_metadata(raw_dir: Path, metadata: dict, audio: dict, video: dict | None = None) -> None:
    info = dict(metadata)
    info.update(
        {
            "audio_id": audio.get("id"),
            "audio_bandwidth": audio.get("bandwidth"),
        }
    )
    if video:
        info.update(
            {
                "video_id": video.get("id"),
                "video_bandwidth": video.get("bandwidth"),
                "video_width": video.get("width"),
                "video_height": video.get("height"),
                "video_codecs": video.get("codecs"),
            }
        )
    (raw_dir / "video.info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def acquire_audio(url: str, raw_dir: Path) -> tuple[Path, dict]:
    metadata = fetch_metadata(url)
    dash = fetch_dash(metadata)
    audio = select_audio_stream(dash)
    target = download_stream(
        stream_urls(audio),
        raw_dir / "audio.m4a",
        referer=metadata["source"],
    )
    _write_metadata(raw_dir, metadata, audio)
    return target, metadata


def acquire_av(url: str, raw_dir: Path) -> tuple[Path, Path, dict]:
    metadata = fetch_metadata(url)
    dash = fetch_dash(metadata, quality=80)
    audio = select_audio_stream(dash)
    video = select_video_stream(dash)
    video_path = download_stream(
        stream_urls(video),
        raw_dir / "video.m4s",
        referer=metadata["source"],
    )
    audio_path = download_stream(
        stream_urls(audio),
        raw_dir / "audio.m4a",
        referer=metadata["source"],
    )
    _write_metadata(raw_dir, metadata, audio, video)
    return video_path, audio_path, metadata
