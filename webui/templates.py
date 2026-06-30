"""HTML template loading and rendering."""
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "static"

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
    job_dir = Path(__file__).parent.parent / "output" / job_id
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
        path = job_dir / filename
        if path.exists():
            return str(path)
    return None

def read_content(job_id, content_type):
    """Read transcription content for frontend display.
    For 'srt', if no .srt file exists, regenerate from raw tele_result.json.
    """
    path = get_content_path(job_id, content_type)
    if path:
        return Path(path).read_text(encoding="utf-8")

    # SRT fallback: regenerate from raw transcription result
    if content_type == "srt":
        raw = Path(__file__).parent.parent / "output" / job_id / "raw" / "tele_result.json"
        if raw.exists():
            try:
                import json as _json
                from .pipeline import to_srt
                data = _json.loads(raw.read_text(encoding="utf-8"))
                return to_srt(data.get("segments", []))
            except Exception:
                return None
    return None
