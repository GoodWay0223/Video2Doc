"""Douyin acquisition through a fresh, isolated Playwright browser session.

Public Douyin pages currently expose signed DASH media URLs through the
``aweme/detail`` response.  Capturing that response is faster and more reliable
than recording in real time, while a MediaRecorder fallback remains available
for pages that render a playable video without exposing a parseable response.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.platform_utils import load_user_config


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)
_AWEME_RE = re.compile(r"/video/(\d+)")
_ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.*?\});?\s*</script>",
    re.DOTALL,
)


class DouyinError(RuntimeError):
    """A classified Douyin acquisition failure."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "DOUYIN_ERROR",
        status: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.status = status


def is_douyin_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return (
        host == "v.douyin.com"
        or host == "douyin.com"
        or host.endswith(".douyin.com")
        or host == "iesdouyin.com"
        or host.endswith(".iesdouyin.com")
    )


def parse_aweme_id(url: str) -> str | None:
    match = _AWEME_RE.search(urllib.parse.urlparse(url).path)
    return match.group(1) if match else None


def extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s<>\"']+", text)
    if not match:
        raise DouyinError("分享文本中没有找到链接。", kind="INPUT_NO_URL")
    return match.group(0).rstrip("，。；;！!）)]}")


def resolve_aweme_id(source: str, *, timeout: float = 20) -> tuple[str, str]:
    """Resolve a short link with GET and return ``(aweme_id, final_url)``."""

    url = extract_url(source)
    direct_id = parse_aweme_id(url)
    if direct_id:
        return direct_id, url

    request = urllib.request.Request(
        url,
        headers={"User-Agent": MOBILE_USER_AGENT, "Referer": "https://www.douyin.com/"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            # Reading a small amount completes challenge/redirect responses on
            # servers that do not finalize the URL until the body starts.
            response.read(1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DouyinError(
            f"抖音短链解析失败：{exc}",
            kind="SHORTLINK_RESOLVE_FAILED",
        ) from exc

    aweme_id = parse_aweme_id(final_url)
    if not aweme_id:
        raise DouyinError(
            "短链已跳转，但没有解析出抖音作品 ID。",
            kind="SHORTLINK_RESOLVE_FAILED",
        )
    return aweme_id, final_url


def inspect_mobile_share(source: str, *, timeout: float = 20) -> dict:
    """Parse Douyin's mobile SSR share page without browser cookies."""

    aweme_id, _ = resolve_aweme_id(source, timeout=timeout)
    share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    request = urllib.request.Request(
        share_url,
        headers={"User-Agent": MOBILE_USER_AGENT, "Referer": "https://www.iesdouyin.com/"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DouyinError(
            f"抖音移动分享页请求失败：{exc}",
            kind="DOUYIN_SSR_NETWORK_ERROR",
        ) from exc

    match = _ROUTER_DATA_RE.search(html)
    if not match:
        raise DouyinError(
            "抖音移动分享页结构已变化，未找到 _ROUTER_DATA。",
            kind="DOUYIN_SSR_CHANGED",
        )
    try:
        router_data = json.loads(match.group(1))
        page_data = (router_data.get("loaderData") or {}).get("video_(id)/page") or {}
        items = ((page_data.get("videoInfoRes") or {}).get("item_list") or [])
        item = items[0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise DouyinError(
            "抖音移动分享页没有有效视频数据。",
            kind="DOUYIN_SSR_CHANGED",
        ) from exc

    video = item.get("video") or {}
    play_urls = _address_urls(video.get("play_addr"))
    if not play_urls:
        raise DouyinError(
            "抖音移动分享页没有播放地址。",
            kind="DOUYIN_SSR_NO_MEDIA",
        )

    # The share page exposes a playwm endpoint.  The corresponding play
    # endpoint is the normal media resource; request 1080p where available.
    normalized_urls = []
    for media_url in play_urls:
        parsed = urllib.parse.urlsplit(media_url.replace("/playwm/", "/play/"))
        query = urllib.parse.parse_qs(parsed.query)
        query["ratio"] = ["1080p"]
        normalized_urls.append(
            urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    urllib.parse.urlencode(query, doseq=True),
                    parsed.fragment,
                )
            )
        )

    author = item.get("author") or {}
    duration_ms = int(video.get("duration") or 0)
    return {
        "aweme_id": str(item.get("aweme_id") or aweme_id),
        "title": item.get("desc") or "",
        "uploader": author.get("nickname") or "",
        "uploader_id": author.get("uid") or "",
        "duration": duration_ms / 1000 if duration_ms else 0,
        "source": f"https://www.douyin.com/video/{aweme_id}",
        "resolved_url": share_url,
        "muxed": {
            "urls": normalized_urls,
            "size": 0,
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
        },
        "cookie_mode": "anonymous_mobile_ssr",
    }


def storage_state_path() -> Path | None:
    """Return an explicitly configured Playwright state file, if any."""

    value = os.environ.get("VIDEO2DOC_DOUYIN_STORAGE_STATE") or load_user_config().get(
        "douyin_storage_state"
    )
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_file():
        raise DouyinError(
            f"配置的抖音 storage_state 不存在：{path}",
            kind="DOUYIN_STORAGE_STATE_NOT_FOUND",
        )
    return path


def _address_urls(address: object) -> list[str]:
    if not isinstance(address, dict):
        return []
    if any(key in address for key in ("main_url", "backup_url", "fallback_url")):
        preferred = [
            address.get("main_url"),
            address.get("backup_url"),
            address.get("fallback_url"),
        ]
        return [item for item in preferred if isinstance(item, str) and item.startswith("http")]
    value = address.get("url_list")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.startswith("http")]
    if isinstance(value, dict):
        preferred = [
            value.get("main_url"),
            value.get("backup_url"),
            value.get("fallback_url"),
        ]
        return [item for item in preferred if isinstance(item, str) and item.startswith("http")]
    return []


def _select_audio(video: dict, observed: dict[str, list[str]]) -> dict:
    candidates = []
    for item in video.get("bit_rate_audio") or []:
        meta = item.get("audio_meta") or {}
        urls = _address_urls(meta.get("url_list"))
        if urls:
            candidates.append(
                {
                    "urls": urls,
                    "bandwidth": int(meta.get("bitrate") or 0),
                    "size": int(meta.get("size") or 0),
                    "codec": meta.get("codec_type") or "",
                }
            )
    if candidates:
        return max(candidates, key=lambda item: (item["bandwidth"], item["size"]))
    if observed["audio"]:
        return {"urls": observed["audio"], "bandwidth": 0, "size": 0, "codec": ""}
    raise DouyinError("抖音页面没有暴露可下载音轨。", kind="DOUYIN_NO_AUDIO")


def _select_video(video: dict, observed: dict[str, list[str]]) -> dict:
    candidates = []
    for item in video.get("bit_rate") or []:
        address = item.get("play_addr") or {}
        urls = _address_urls(address)
        if not urls:
            continue
        is_h265 = bool(item.get("is_h265")) or "h265" in str(item.get("gear_name") or "").lower()
        candidates.append(
            {
                "urls": urls,
                "bandwidth": int(item.get("bit_rate") or 0),
                "size": int(address.get("data_size") or 0),
                "width": int(address.get("width") or video.get("width") or 0),
                "height": int(address.get("height") or video.get("height") or 0),
                "is_h265": is_h265,
            }
        )
    if candidates:
        # Prefer H.264 at the best available resolution for widest ffmpeg/player
        # compatibility.  Use H.265 only when no H.264 variant exists.
        h264 = [item for item in candidates if not item["is_h265"]]
        pool = h264 or candidates
        return max(
            pool,
            key=lambda item: (item["height"], item["width"], item["bandwidth"]),
        )

    fallback = video.get("play_addr") or {}
    urls = _address_urls(fallback)
    if urls:
        return {
            "urls": urls,
            "bandwidth": 0,
            "size": int(fallback.get("data_size") or 0),
            "width": int(fallback.get("width") or video.get("width") or 0),
            "height": int(fallback.get("height") or video.get("height") or 0),
            "is_h265": bool(video.get("is_h265")),
        }
    if observed["video"]:
        return {
            "urls": observed["video"],
            "bandwidth": 0,
            "size": 0,
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "is_h265": False,
        }
    raise DouyinError("抖音页面没有暴露可下载视频轨。", kind="DOUYIN_NO_VIDEO")


def inspect_media(url: str, *, timeout_ms: int = 30_000) -> dict:
    """Open one fresh browser session and capture metadata plus signed streams."""

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DouyinError(
            "缺少 Python Playwright。请执行 pip install playwright && playwright install chromium。",
            kind="DOUYIN_PLAYWRIGHT_MISSING",
        ) from exc

    detail_responses = []
    observed: dict[str, list[str]] = {"audio": [], "video": []}
    state_path = storage_state_path()

    try:
        with sync_playwright() as playwright:
            launch_error = None
            browser = None
            for launch_kwargs in (
                {"channel": "chrome", "headless": True},
                {"headless": True},
            ):
                try:
                    browser = playwright.chromium.launch(**launch_kwargs)
                    break
                except PlaywrightError as exc:
                    launch_error = exc
            if browser is None:
                raise DouyinError(
                    f"无法启动 Chrome/Chromium：{launch_error}",
                    kind="DOUYIN_BROWSER_START_FAILED",
                )

            context_kwargs = {
                "user_agent": USER_AGENT,
                "viewport": {"width": 1280, "height": 720},
                "locale": "zh-CN",
                "accept_downloads": True,
            }
            if state_path:
                context_kwargs["storage_state"] = str(state_path)
            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            def capture_response(response) -> None:
                response_url = response.url
                if "/aweme/v1/web/aweme/detail/" in response_url:
                    detail_responses.append(response)
                if "douyinvod.com" not in response_url:
                    return
                if "/media-audio-" in response_url:
                    observed["audio"].append(response_url)
                elif "/media-video-" in response_url:
                    observed["video"].append(response_url)

            page.on("response", capture_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            for _ in range(max(1, timeout_ms // 500)):
                if detail_responses:
                    break
                page.wait_for_timeout(500)

            title = page.title()
            final_url = page.url
            if "验证码" in title or any(mark in final_url for mark in ("/verify", "/captcha")):
                raise DouyinError(
                    "抖音返回验证码页；本次浏览器会话已关闭，请稍后再试或配置独立 storage_state。",
                    kind="DOUYIN_CAPTCHA",
                )

            detail = {}
            for response in reversed(detail_responses):
                try:
                    payload = response.json()
                    if payload.get("aweme_detail"):
                        detail = payload["aweme_detail"]
                        break
                except Exception:
                    continue

            if not detail and not (observed["audio"] or observed["video"]):
                raise DouyinError(
                    "页面已打开，但未捕获到视频详情或媒体流。",
                    kind="DOUYIN_MEDIA_NOT_FOUND",
                )

            video = detail.get("video") or {}
            audio_stream = _select_audio(video, observed)
            video_stream = _select_video(video, observed)
            browser.close()

    except DouyinError:
        raise
    except PlaywrightError as exc:
        raise DouyinError(
            f"抖音页面自动化失败：{exc}",
            kind="DOUYIN_BROWSER_ERROR",
        ) from exc

    aweme_id = str(detail.get("aweme_id") or parse_aweme_id(final_url) or "")
    author = detail.get("author") or {}
    duration_ms = int(video.get("duration") or 0)
    return {
        "aweme_id": aweme_id,
        "title": detail.get("desc") or title or "",
        "uploader": author.get("nickname") or "",
        "uploader_id": author.get("uid") or "",
        "duration": duration_ms / 1000 if duration_ms else 0,
        "source": f"https://www.douyin.com/video/{aweme_id}" if aweme_id else final_url,
        "resolved_url": final_url,
        "audio": audio_stream,
        "video": video_stream,
        "cookie_mode": "storage_state" if state_path else "anonymous_fresh_session",
    }


def download_stream(
    candidates: list[str],
    target: Path,
    *,
    expected_size: int = 0,
    referer: str = "https://www.douyin.com/",
    timeout: float = 180,
) -> Path:
    """Download a signed CDN URL without exporting browser-session cookies.

    A configured storage state is used only inside the isolated browser page.
    Douyin cookies must never be flattened and forwarded to unrelated CDN
    hosts; the captured signed URL plus its Referer is the download authority.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    last_error: Exception | None = None
    last_http_status: int | None = None

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Accept": "*/*",
    }

    for url in list(dict.fromkeys(candidates)):
        try:
            request = urllib.request.Request(url, headers=headers)
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
                raise DouyinError(
                    f"媒体下载不完整：期望 {required} 字节，实际 {size} 字节。",
                    kind="MEDIA_INCOMPLETE",
                )
            partial.replace(target)
            return target
        except Exception as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError):
                last_http_status = exc.code
                exc.close()
            if partial.exists():
                partial.unlink()

    if isinstance(last_error, DouyinError):
        raise last_error
    if last_http_status is not None:
        raise DouyinError(
            f"抖音 CDN 返回 HTTP {last_http_status}。",
            kind="DOUYIN_CDN_HTTP_ERROR",
            status=last_http_status,
        ) from last_error
    raise DouyinError(
        f"抖音 CDN 下载失败：{last_error}",
        kind="DOUYIN_CDN_ERROR",
    ) from last_error


def _public_metadata(info: dict) -> dict:
    public = {
        key: value
        for key, value in info.items()
        if not key.startswith("_") and key not in {"audio", "video", "muxed"}
    }
    if info.get("audio"):
        public.update(
            {
                "audio_bandwidth": info["audio"].get("bandwidth"),
                "audio_size": info["audio"].get("size"),
            }
        )
    if info.get("video"):
        public.update(
            {
                "video_bandwidth": info["video"].get("bandwidth"),
                "video_size": info["video"].get("size"),
                "video_width": info["video"].get("width"),
                "video_height": info["video"].get("height"),
                "video_h265": info["video"].get("is_h265"),
            }
        )
    if info.get("muxed"):
        public.update(
            {
                "video_size": info["muxed"].get("size"),
                "video_width": info["muxed"].get("width"),
                "video_height": info["muxed"].get("height"),
                "muxed_source": True,
            }
        )
    return public


def _write_metadata(raw_dir: Path, info: dict) -> None:
    (raw_dir / "video.info.json").write_text(
        json.dumps(_public_metadata(info), ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )


def acquire_audio(url: str, raw_dir: Path) -> tuple[Path, dict]:
    for attempt in range(2):
        info = inspect_media(url)
        try:
            target = download_stream(
                info["audio"]["urls"],
                raw_dir / "audio.m4a",
                expected_size=info["audio"].get("size") or 0,
            )
        except DouyinError as exc:
            if attempt == 0 and exc.status in {403, 410}:
                continue
            raise
        info["signed_url_refreshed"] = bool(attempt)
        _write_metadata(raw_dir, info)
        return target, _public_metadata(info)
    raise DouyinError("抖音签名音轨刷新失败。", kind="DOUYIN_SIGNED_URL_EXPIRED")


def acquire_av(url: str, raw_dir: Path) -> tuple[Path, Path, dict]:
    for attempt in range(2):
        info = inspect_media(url)
        try:
            video_path = download_stream(
                info["video"]["urls"],
                raw_dir / "video.m4s",
                expected_size=info["video"].get("size") or 0,
            )
            audio_path = download_stream(
                info["audio"]["urls"],
                raw_dir / "audio.m4a",
                expected_size=info["audio"].get("size") or 0,
            )
        except DouyinError as exc:
            if attempt == 0 and exc.status in {403, 410}:
                continue
            raise
        info["signed_url_refreshed"] = bool(attempt)
        _write_metadata(raw_dir, info)
        return video_path, audio_path, _public_metadata(info)
    raise DouyinError("抖音签名音视频刷新失败。", kind="DOUYIN_SIGNED_URL_EXPIRED")


def acquire_muxed(source: str, raw_dir: Path) -> tuple[Path, dict]:
    """Download the public mobile-share MP4 without browser cookies."""

    info = inspect_mobile_share(source)
    target = download_stream(
        info["muxed"]["urls"],
        raw_dir / "video.mp4",
        expected_size=info["muxed"].get("size") or 0,
        referer="https://www.iesdouyin.com/",
    )
    _write_metadata(raw_dir, info)
    return target, _public_metadata(info)


def record_with_media_recorder(url: str, target: Path, *, timeout_ms: int = 1_800_000) -> Path:
    """Real-time fallback for a playable page with no usable signed URL."""

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DouyinError("缺少 Python Playwright。", kind="DOUYIN_PLAYWRIGHT_MISSING") from exc

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    if partial.exists():
        partial.unlink()
    state_path = storage_state_path()
    try:
        with sync_playwright() as playwright:
            browser = None
            launch_error = None
            for launch_kwargs in (
                {"channel": "chrome", "headless": True},
                {"headless": True},
            ):
                try:
                    browser = playwright.chromium.launch(**launch_kwargs)
                    break
                except PlaywrightError as exc:
                    launch_error = exc
            if browser is None:
                raise DouyinError(
                    f"无法启动 Chrome/Chromium：{launch_error}",
                    kind="DOUYIN_BROWSER_START_FAILED",
                )

            try:
                context_kwargs = {
                    "user_agent": USER_AGENT,
                    "viewport": {"width": 1280, "height": 720},
                    "locale": "zh-CN",
                    "accept_downloads": True,
                }
                if state_path:
                    context_kwargs["storage_state"] = str(state_path)
                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                video = page.locator("video").first
                video.wait_for(state="attached", timeout=30_000)

                script = """
                async () => {
                  const videos = [...document.querySelectorAll('video')];
                  const video = videos.find(v => Number.isFinite(v.duration) && v.duration > 0) || videos[0];
                  if (!video || typeof video.captureStream !== 'function') throw new Error('NO_CAPTURABLE_VIDEO');
                  video.loop = false;
                  video.muted = false;
                  video.currentTime = 0;
                  await video.play();
                  const stream = video.captureStream();
                  const mime = ['video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm']
                    .find(x => MediaRecorder.isTypeSupported(x));
                  const chunks = [];
                  const recorder = new MediaRecorder(stream, mime ? {mimeType:mime} : undefined);
                  recorder.ondataavailable = event => { if (event.data && event.data.size) chunks.push(event.data); };
                  const stopped = new Promise((resolve, reject) => {
                    recorder.onstop = resolve;
                    recorder.onerror = event => reject(event.error || new Error('RECORDER_ERROR'));
                  });
                  recorder.start(1000);
                  await new Promise((resolve, reject) => {
                    const durationMs = Number.isFinite(video.duration) && video.duration > 0
                      ? (video.duration + 30) * 1000
                      : 10 * 60 * 1000;
                    const timer = setTimeout(
                      () => reject(new Error('VIDEO_PLAYBACK_TIMEOUT')),
                      durationMs,
                    );
                    video.addEventListener('ended', () => {
                      clearTimeout(timer);
                      resolve();
                    }, {once:true});
                    video.addEventListener('error', () => {
                      clearTimeout(timer);
                      reject(new Error('VIDEO_PLAYBACK_ERROR'));
                    }, {once:true});
                  });
                  recorder.stop();
                  await stopped;
                  const blob = new Blob(chunks, {type: recorder.mimeType || 'video/webm'});
                  if (!blob.size) throw new Error('EMPTY_RECORDING');
                  const link = document.createElement('a');
                  link.href = URL.createObjectURL(blob);
                  link.download = 'video.webm';
                  document.body.appendChild(link);
                  link.click();
                  return blob.size;
                }
                """
                with page.expect_download(timeout=timeout_ms) as download_info:
                    page.evaluate(script)
                download_info.value.save_as(str(partial))
            finally:
                browser.close()
    except DouyinError:
        if partial.exists():
            partial.unlink()
        raise
    except PlaywrightError as exc:
        if partial.exists():
            partial.unlink()
        raise DouyinError(
            f"抖音实时录制失败：{exc}",
            kind="DOUYIN_MEDIA_RECORDER_FAILED",
        ) from exc

    if not partial.exists() or partial.stat().st_size <= 0:
        if partial.exists():
            partial.unlink()
        raise DouyinError("MediaRecorder 生成了空文件。", kind="MEDIA_INCOMPLETE")
    partial.replace(target)
    return target
