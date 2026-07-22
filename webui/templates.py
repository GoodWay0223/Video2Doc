"""HTML template loading and rendering."""
import re
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_WINDOWS_RESERVED_FILENAME_CHARS = set('<>:"/\\|?*')


def is_safe_job_id(job_id):
    """Return whether a job id is a single, non-traversing path component."""
    return isinstance(job_id, str) and bool(JOB_ID_RE.fullmatch(job_id))


def is_safe_filename(filename):
    """Return whether a requested result filename is safe on all platforms."""
    if not isinstance(filename, str) or not filename or len(filename) > 255:
        return False
    if filename in {".", ".."}:
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in filename):
        return False
    return not any(ch in _WINDOWS_RESERVED_FILENAME_CHARS for ch in filename)


def _is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_job_dir(job_id):
    """Resolve a job directory while guaranteeing it remains under output/."""
    if not is_safe_job_id(job_id):
        return None
    root = OUTPUT_DIR.resolve()
    job_dir = (root / job_id).resolve()
    return job_dir if _is_within(job_dir, root) and job_dir != root else None


def resolve_job_file(job_id, filename):
    """Resolve one direct child of a job directory without following escapes."""
    if not is_safe_filename(filename):
        return None
    job_dir = resolve_job_dir(job_id)
    if job_dir is None:
        return None
    path = (job_dir / filename).resolve()
    return path if _is_within(path, job_dir) and path != job_dir else None

def load_html():
    """Load index.html from static directory, with fallback"""
    html_path = TEMPLATE_DIR / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return _fallback_html()

def _fallback_html():
    """Minimal fallback if index.html is missing"""
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>Video2Doc</title></head><body><h1>Video2Doc</h1>
<p>Web UI 文件丢失。请确保 webui/static/index.html 存在。</p></body></html>"""

def get_content_path(job_id, content_type):
    """Get path to transcription content file, with fallbacks.
    text → transcript.txt → transcript.md (whichever exists)
    srt  → transcript.srt
    md   → transcript.md → transcript.txt
    json → transcript.json
    """
    job_dir = resolve_job_dir(job_id)
    if job_dir is None:
        return None
    # Ordered fallback candidates per content type
    fallbacks = {
        "text": ["transcript.txt", "transcript.md"],
        "md":   ["transcript.md", "transcript.txt"],
        "srt":  ["transcript.srt"],
        "json": ["transcript.json"],
    }
    candidates = fallbacks.get(content_type)
    if not candidates:
        return None
    for filename in candidates:
        path = resolve_job_file(job_id, filename)
        if path is not None and path.is_file():
            return str(path)
    return None

def read_content(job_id, content_type):
    """Read transcription content for frontend display.
    For 'srt', if no .srt file exists, regenerate from raw tele_result.json.
    """
    path = get_content_path(job_id, content_type)
    if path:
        return Path(path).read_text(encoding="utf-8")

    # Preview fallback: derive text/SRT from the raw normalized transcript even
    # when the user exported only JSON or SRT.
    if content_type in {"text", "srt"}:
        job_dir = resolve_job_dir(job_id)
        if job_dir is None:
            return None
        raw = (job_dir / "raw" / "tele_result.json").resolve()
        if _is_within(raw, job_dir) and raw.is_file():
            try:
                import json as _json
                data = _json.loads(raw.read_text(encoding="utf-8"))
                if content_type == "text":
                    text = str(data.get("text", "")).strip()
                    if not text:
                        text = " ".join(
                            str(segment.get("text", "")).strip()
                            for segment in data.get("segments", [])
                            if str(segment.get("text", "")).strip()
                        )
                    return text or None
                from .pipeline import to_srt
                return to_srt(data.get("segments", []))
            except Exception:
                return None
    return None
