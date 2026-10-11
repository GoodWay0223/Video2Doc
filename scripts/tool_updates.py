"""Detect, check and update the external tools Video2Doc depends on.

Policy
- Online checks read only public release metadata (PyPI, the official Windows
  FFmpeg builds on GitHub, Homebrew, nodejs.org, endoflife.date). No API keys,
  media, transcripts or local paths are sent.
- Only stable releases that are at least MIN_RELEASE_AGE_DAYS old are installed
  (a supply-chain cool-off: broken or malicious releases are usually pulled
  within days). The newest release is still shown.
- Updates replace the old version in place: pip runs with --no-cache-dir and
  FFmpeg files are overwritten, so no second copy is left on disk.
- Python and Node.js installed system-wide need administrator rights; for those
  Video2Doc only reports the exact upgrade command.
"""
import concurrent.futures
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .platform_utils import find_executable, load_state, load_user_config, save_state
except ImportError:  # Direct execution from scripts/
    from platform_utils import find_executable, load_state, load_user_config, save_state

MIN_RELEASE_AGE_DAYS = 7
AUTO_CHECK_INTERVAL_SECONDS = 24 * 3600
CHECK_CACHE_SECONDS = 3600
HTTP_TIMEOUT = 8
USER_AGENT = "Video2Doc-tool-check"
STABLE_RE = re.compile(r"\d+(?:\.\d+)*")

PIP_COMPONENTS = {
    "yt_dlp": {"label": "yt-dlp", "role": "视频/字幕下载（必需）", "dist": "yt-dlp",
               "spec": "yt-dlp[default]", "required": True},
    "playwright": {"label": "Playwright", "role": "抖音浏览器兜底（可选）", "dist": "playwright",
                   "spec": "playwright", "post": [["-m", "playwright", "install", "chromium"]]},
    "whisper": {"label": "openai-whisper", "role": "本地识别（可选）", "dist": "openai-whisper",
                "spec": "openai-whisper"},
    "funasr": {"label": "FunASR", "role": "本地识别（可选）", "dist": "funasr", "spec": "funasr"},
}
COMPONENT_IDS = ("yt_dlp", "ffmpeg", "playwright", "whisper", "funasr", "node", "python")


# ─── helpers ──────────────────────────────────────────────

def version_tuple(value):
    match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
    return tuple(int(part) for part in match.group(0).split(".")) if match else None


def _compare(left, right):
    a, b = version_tuple(left), version_tuple(right)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def _parse_time(value):
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _old_enough(published, now=None):
    if published is None:
        return False
    now = now or datetime.now(timezone.utc)
    return (now - published).total_seconds() >= MIN_RELEASE_AGE_DAYS * 86400


def _get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _run(command, timeout=900):
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _tail(result):
    text = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return text.splitlines()[-1][:300] if text else f"退出码 {result.returncode}"


def _tool_version(executable, args=("--version",)):
    try:
        result = _run([executable, *args], timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    line = next((l.strip() for l in (result.stdout or result.stderr or "").splitlines() if l.strip()), "")
    return line or None


def _dist_version(dist):
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


# ─── release metadata ────────────────────────────────────

def pypi_release(dist, now=None):
    """Return the newest stable version and the newest one past the cool-off."""
    data = _get_json(f"https://pypi.org/pypi/{dist}/json")
    candidates = []
    for version, files in (data.get("releases") or {}).items():
        files = [item for item in files or [] if not item.get("yanked")]
        if not STABLE_RE.fullmatch(version) or not files:
            continue
        times = [t for t in (_parse_time(item.get("upload_time_iso_8601")) for item in files) if t]
        candidates.append((version_tuple(version), version, min(times) if times else None))
    candidates.sort(reverse=True)
    if not candidates:
        return {"latest": None, "target": None}
    target = next((item[1] for item in candidates if _old_enough(item[2], now)), None)
    return {"latest": candidates[0][1], "target": target}


def ffmpeg_release(flavor="full"):
    """Latest official Windows build from gyan.dev (published on GitHub with a SHA-256 digest)."""
    data = _get_json("https://api.github.com/repos/GyanD/codexffmpeg/releases/latest")
    tag = str(data.get("tag_name") or "")
    name = f"ffmpeg-{tag}-{flavor}_build.zip"
    asset = next((item for item in data.get("assets") or [] if item.get("name") == name), None)
    published = _parse_time(data.get("published_at"))
    digest = str((asset or {}).get("digest") or "")
    return {
        "latest": tag or None,
        "target": tag if (asset and _old_enough(published) and digest.startswith("sha256:")) else None,
        "url": (asset or {}).get("browser_download_url"),
        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
    }


def brew_release(formula):
    data = _get_json(f"https://formulae.brew.sh/api/formula/{formula}.json")
    stable = (data.get("versions") or {}).get("stable")
    return {"latest": stable, "target": stable}


def node_lts_release(now=None):
    data = _get_json("https://nodejs.org/dist/index.json")
    lts = [item for item in data if item.get("lts")]
    if not lts:
        return {"latest": None, "target": None}
    target = next((item["version"] for item in lts
                   if _old_enough(_parse_time(item.get("date")), now)), None)
    return {"latest": lts[0]["version"].lstrip("v"), "target": (target or "").lstrip("v") or None}


def python_release(current):
    cycle = ".".join(str(part) for part in (version_tuple(current) or ())[:2])
    for item in _get_json("https://endoflife.date/api/python.json"):
        if str(item.get("cycle")) == cycle:
            latest = item.get("latest")
            published = _parse_time(item.get("latestReleaseDate"))
            return {"latest": latest, "target": latest if _old_enough(published) else None}
    return {"latest": None, "target": None}


# ─── local detection ─────────────────────────────────────

_FFMPEG_ROOT_ENTRIES = {"bin", "doc", "presets", "include", "lib", "license", "license.txt",
                        "readme.txt"}


def _ffmpeg_layout(executable):
    """Classify how FFmpeg is installed and whether Video2Doc may update it."""
    path = Path(executable).resolve()
    text = str(path).lower()
    if os.name == "nt":
        if "\\winget\\packages\\" in text:
            return "winget", None
        root = path.parent.parent
        if path.parent.name.lower() != "bin" or not (path.parent / "ffprobe.exe").is_file():
            return "manual", None
        if "program files" in text or not os.access(root, os.W_OK):
            return "manual", None
        # Only a dedicated FFmpeg directory may be overwritten in place.
        if all(entry.name.lower() in _FFMPEG_ROOT_ENTRIES for entry in root.iterdir()):
            return "standalone", root
        return "manual", None
    if "/cellar/" in text or text.startswith(("/opt/homebrew/", "/usr/local/")):
        if find_executable(["brew"]):
            return "brew", None
    return "manual", None


def _ffmpeg_installed():
    executable = find_executable(["ffmpeg"])
    if not executable:
        return None
    line = _tool_version(executable, ("-version",)) or ""
    match = re.search(r"ffmpeg version\s+(\S+)", line)
    raw = match.group(1) if match else ""
    manager, root = _ffmpeg_layout(executable)
    return {
        "path": executable, "raw": raw, "root": root, "manager": manager,
        "dev_build": raw.startswith("N-") or "git" in raw.lower(),
        "version": raw.split("-", 1)[0] if raw and not raw.startswith("N-") else raw,
        "flavor": "essentials" if "essentials" in raw else "full",
    }


def _ffmpeg_hint(manager):
    if os.name == "nt":
        return "winget upgrade --id Gyan.FFmpeg" if manager == "winget" else \
            "下载 https://www.gyan.dev/ffmpeg/builds/ 的 release 版并替换现有目录"
    return "brew upgrade ffmpeg && brew cleanup ffmpeg" if sys.platform == "darwin" else \
        "使用系统包管理器升级 ffmpeg"


# ─── checks ──────────────────────────────────────────────

def _status(version, release, *, dev_build=False):
    """A release still inside the cool-off window does not count as an update yet."""
    if not version:
        return "not_installed"
    target, latest = release.get("target"), release.get("latest")
    if dev_build:
        return "update_available" if target else "unknown"
    if target and (_compare(version, target) or 0) < 0:
        return "update_available"
    comparison = _compare(version, latest) if latest else None
    if comparison is None:
        return "unknown"
    return "newer" if comparison > 0 else "up_to_date"


def _safe(fetch, *args):
    try:
        return fetch(*args), None
    except Exception as exc:  # Network/JSON errors must not break the UI.
        return {"latest": None, "target": None}, type(exc).__name__


def check(online=True):
    """Return one status row per component (safe to show in the local UI)."""
    rows = {}
    ffmpeg = _ffmpeg_installed()
    node_path = find_executable(["node"])
    node_version = (_tool_version(node_path) or "").lstrip("v") if node_path else None
    python_version = ".".join(str(part) for part in sys.version_info[:3])

    fetchers = {}
    if online:
        for cid, spec in PIP_COMPONENTS.items():
            if _dist_version(spec["dist"]) or spec.get("required"):
                fetchers[cid] = (pypi_release, spec["dist"])
        if ffmpeg:
            if os.name == "nt" and ffmpeg["manager"] in {"standalone", "winget", "manual"}:
                fetchers["ffmpeg"] = (ffmpeg_release, ffmpeg["flavor"])
            elif sys.platform == "darwin":
                fetchers["ffmpeg"] = (brew_release, "ffmpeg")
        if node_version:
            fetchers["node"] = (node_lts_release,)
        fetchers["python"] = (python_release, python_version)
    releases = {}
    if fetchers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
            futures = {cid: pool.submit(_safe, *call) for cid, call in fetchers.items()}
            releases = {cid: future.result() for cid, future in futures.items()}

    def release(cid):
        return releases.get(cid, ({"latest": None, "target": None}, None))

    for cid, spec in PIP_COMPONENTS.items():
        version = _dist_version(spec["dist"])
        data, error = release(cid)
        manager = "pip" if version else ("pip" if spec.get("required") else "none")
        if cid == "yt_dlp" and not version:
            executable = find_executable(["yt-dlp"])
            if executable:
                version, manager = _tool_version(executable), "yt-dlp -U"
        rows[cid] = {
            "label": spec["label"], "role": spec["role"], "version": version,
            "latest": data.get("latest"), "target": data.get("target"),
            "status": _status(version, data), "manager": manager,
            "updatable": manager in {"pip", "yt-dlp -U"} and (bool(version) or spec.get("required", False)),
            "hint": f"{Path(sys.executable).name} -m pip install -U \"{spec['spec']}\"",
            "check_error": error,
        }

    data, error = release("ffmpeg")
    manager = ffmpeg["manager"] if ffmpeg else "none"
    rows["ffmpeg"] = {
        "label": "FFmpeg", "role": "音视频处理（必需）",
        "version": ffmpeg["version"] if ffmpeg else None,
        "latest": data.get("latest"), "target": data.get("target"),
        "status": _status(ffmpeg and ffmpeg["version"], data,
                          dev_build=bool(ffmpeg and ffmpeg["dev_build"])),
        "manager": manager,
        "updatable": manager in {"standalone", "winget", "brew"},
        "hint": _ffmpeg_hint(manager), "check_error": error,
    }

    data, error = release("node")
    brew_node = bool(node_path and sys.platform == "darwin" and find_executable(["brew"])
                     and ("/cellar/" in str(Path(node_path).resolve()).lower()))
    rows["node"] = {
        "label": "Node.js", "role": "YouTube 签名解析运行时（推荐）", "version": node_version,
        "latest": data.get("latest"), "target": data.get("target"),
        "status": _status(node_version, data), "manager": "brew" if brew_node else "system",
        "updatable": brew_node,
        "hint": "brew upgrade node" if sys.platform == "darwin" else
                "winget install --id OpenJS.NodeJS.LTS（需要管理员确认）",
        "check_error": error,
    }

    data, error = release("python")
    rows["python"] = {
        "label": "Python", "role": "运行环境（必需）", "version": python_version,
        "latest": data.get("latest"), "target": data.get("target"),
        "status": _status(python_version, data), "manager": "system", "updatable": False,
        "hint": (f"winget upgrade --id Python.Python.{sys.version_info.major}.{sys.version_info.minor}"
                 "（需要管理员确认）") if os.name == "nt" else
                f"brew upgrade python@{sys.version_info.major}.{sys.version_info.minor}",
        "check_error": error,
    }
    return [{"id": cid, **rows[cid]} for cid in COMPONENT_IDS]


# ─── updates ─────────────────────────────────────────────

def _update_pip(cid, target):
    spec = PIP_COMPONENTS[cid]
    requirement = f"{spec['spec']}=={target}" if target else spec["spec"]
    result = _run([sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir",
                   "--disable-pip-version-check", requirement])
    if result.returncode != 0:
        return False, f"pip 升级失败：{_tail(result)}"
    for args in spec.get("post", []):
        post = _run([sys.executable, *args])
        if post.returncode != 0:
            return False, f"附加步骤失败：{_tail(post)}"
    return True, f"已更新到 {_dist_version(spec['dist']) or target}"


def _mirror_ffmpeg(source_root, target_root):
    """Overwrite target_root with source_root; stale files are removed only in known subdirs."""
    source_root, target_root = Path(source_root), Path(target_root)
    new_files = {path.relative_to(source_root) for path in source_root.rglob("*") if path.is_file()}
    for relative in sorted(new_files):
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)
    for path in sorted(target_root.rglob("*"), reverse=True):
        relative = path.relative_to(target_root)
        if relative.parts and relative.parts[0].lower() not in {"bin", "doc", "presets"}:
            continue
        if path.is_file() and relative not in new_files:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _update_ffmpeg_standalone(root, flavor):
    release = ffmpeg_release(flavor)
    if not (release.get("target") and release.get("url") and release.get("sha256")):
        return False, "暂无满足冷却期且带校验值的 FFmpeg 稳定版"
    with tempfile.TemporaryDirectory(prefix="video2doc-ffmpeg-", dir=root.parent) as staging:
        archive = Path(staging) / "ffmpeg.zip"
        request = urllib.request.Request(release["url"], headers={"User-Agent": USER_AGENT})
        digest = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest().lower() != release["sha256"].lower():
            return False, "下载文件 SHA-256 校验失败，已放弃更新"
        extracted = Path(staging) / "extracted"
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if member.startswith(("/", "\\")) or ".." in Path(member).parts:
                    return False, "压缩包包含不安全路径，已放弃更新"
            bundle.extractall(extracted)
        top = next((path for path in extracted.iterdir() if (path / "bin" / "ffmpeg.exe").is_file()), None)
        if top is None:
            return False, "压缩包结构异常，已放弃更新"
        try:
            _mirror_ffmpeg(top, root)
        except PermissionError:
            return False, "ffmpeg 正被其他程序使用，部分文件未替换；关闭相关程序后重试"
    return True, f"已更新到 {release['target']}（{root}）"


def update(cid, *, target=None):
    """Update one component in place. Returns (ok, message)."""
    if cid in PIP_COMPONENTS:
        executable = find_executable(["yt-dlp"]) if cid == "yt_dlp" else None
        if cid == "yt_dlp" and not _dist_version("yt-dlp") and executable:
            result = _run([executable, "-U"])
            return result.returncode == 0, _tail(result)
        return _update_pip(cid, target)
    if cid == "ffmpeg":
        info = _ffmpeg_installed()
        if not info:
            return False, "未检测到 ffmpeg"
        if info["manager"] == "standalone":
            return _update_ffmpeg_standalone(info["root"], info["flavor"])
        if info["manager"] == "winget":
            winget = find_executable(["winget", str(Path(os.environ.get("LOCALAPPDATA", ""))
                                                     / "Microsoft" / "WindowsApps" / "winget.exe")])
            if not winget:
                return False, "未找到 winget"
            result = _run([winget, "upgrade", "--id", "Gyan.FFmpeg", "--silent",
                           "--accept-source-agreements", "--accept-package-agreements"])
            return result.returncode == 0, _tail(result)
        if info["manager"] == "brew":
            brew = find_executable(["brew"])
            result = _run([brew, "upgrade", "ffmpeg"])
            if result.returncode == 0:
                _run([brew, "cleanup", "ffmpeg"])
            return result.returncode == 0, _tail(result)
        return False, "该 ffmpeg 安装位置不支持自动更新：" + _ffmpeg_hint(info["manager"])
    if cid == "node":
        brew = find_executable(["brew"])
        if sys.platform == "darwin" and brew:
            result = _run([brew, "upgrade", "node"])
            if result.returncode == 0:
                _run([brew, "cleanup", "node"])
            return result.returncode == 0, _tail(result)
    return False, "该组件需要管理员权限，请按提示命令手动升级"


# ─── background state for the Web UI ─────────────────────

_lock = threading.Lock()
_state = {"running": None, "results": [], "checked_at": 0.0, "rows": []}


def auto_update_enabled():
    value = load_user_config().get("auto_update_tools", True)
    return value is not False and str(value).lower() not in {"false", "0", "off"}


def snapshot(refresh=False):
    """Cached online check (at most hourly unless refresh=True)."""
    with _lock:
        fresh = _state["rows"] and time.time() - _state["checked_at"] < CHECK_CACHE_SECONDS
    if refresh or not fresh:
        rows = check(online=True)
        with _lock:
            _state.update(rows=rows, checked_at=time.time())
    with _lock:
        state = load_state()
        return {
            "components": _state["rows"], "checked_at": _state["checked_at"],
            "running": _state["running"], "results": list(_state["results"][-10:]),
            "auto_update": auto_update_enabled(),
            "last_auto_update": state.get("tools_last_auto_check"),
            "min_release_age_days": MIN_RELEASE_AGE_DAYS,
        }


def _record(cid, ok, message):
    with _lock:
        _state["results"].append({"id": cid, "ok": ok, "message": message, "at": time.time()})
        _state["results"] = _state["results"][-20:]


def _run_updates(cids, targets):
    try:
        for cid in cids:
            with _lock:
                _state["running"] = cid
            try:
                ok, message = update(cid, target=targets.get(cid))
            except Exception as exc:
                ok, message = False, f"{type(exc).__name__}: {exc}"[:300]
            _record(cid, ok, message)
    finally:
        rows = check(online=True)
        with _lock:
            _state.update(running=None, rows=rows, checked_at=time.time())


def start_update(cid):
    """Start a background update; returns False if another update is running."""
    with _lock:
        if _state["running"]:
            return False
        rows = {row["id"]: row for row in _state["rows"]}
        _state["running"] = cid
    target = (rows.get(cid) or {}).get("target")
    threading.Thread(target=_run_updates, args=([cid], {cid: target}), daemon=True).start()
    return True


def maybe_auto_update(is_busy=lambda: False, *, force=False):
    """Daily: update every outdated component Video2Doc is allowed to update."""
    if not auto_update_enabled():
        return []
    last = load_state().get("tools_last_auto_check") or 0
    if not force and time.time() - float(last) < AUTO_CHECK_INTERVAL_SECONDS:
        return []
    rows = check(online=True)
    with _lock:
        _state.update(rows=rows, checked_at=time.time())
    outdated = [row for row in rows if row["updatable"] and row["status"] == "update_available"
                and row.get("target") and row["version"]]
    checked = [row for row in rows if row["updatable"]]
    # Busy or offline: keep the timestamp so the next startup/hourly tick retries.
    if is_busy() or (checked and all(row.get("check_error") for row in checked)):
        return []
    save_state({"tools_last_auto_check": time.time()})
    if not outdated:
        return []
    with _lock:
        if _state["running"]:
            return []
        _state["running"] = outdated[0]["id"]
    _run_updates([row["id"] for row in outdated], {row["id"]: row["target"] for row in outdated})
    return [row["id"] for row in outdated]


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="检查/更新 Video2Doc 依赖的工具")
    parser.add_argument("--update", action="store_true", help="更新所有可自动更新且有新稳定版的工具")
    args = parser.parse_args(argv)
    rows = check(online=True)
    for row in rows:
        mark = {"up_to_date": "✅", "update_available": "⬆️", "not_installed": "—"}.get(row["status"], "•")
        print(f"{mark} {row['label']:<15} 当前 {row['version'] or '未安装':<16} "
              f"最新 {row['latest'] or '?':<12} {'可自动更新' if row['updatable'] else row['hint']}")
    if args.update:
        for row in rows:
            if row["updatable"] and row["status"] == "update_available" and row.get("target"):
                ok, message = update(row["id"], target=row["target"])
                print(f"{'✅' if ok else '❌'} {row['label']}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
