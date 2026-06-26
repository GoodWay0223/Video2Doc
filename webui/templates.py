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
    """Get path to transcription content file"""
    job_dir = Path(__file__).parent.parent / "output" / job_id
    mapping = {"text": "transcript.txt", "srt": "transcript.srt",
               "md": "transcript.md", "json": "transcript.json"}
    filename = mapping.get(content_type)
    if not filename: return None
    path = job_dir / filename
    return str(path) if path.exists() else None

def read_content(job_id, content_type):
    """Read transcription content for frontend display"""
    path = get_content_path(job_id, content_type)
    if not path: return None
    return Path(path).read_text(encoding="utf-8")
