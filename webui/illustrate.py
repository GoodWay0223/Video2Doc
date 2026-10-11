"""Illustrated transcripts: one frame per slide/scene, each followed by its narration.

Lecture and tutorial videos are much easier to study when every slide sits
next to exactly what was said while it was on screen. Scene changes are
detected with ffmpeg; narration segments are assigned to the frame that was
visible when they started.
"""
import base64
import html
import json
import re
import subprocess
import zipfile
from pathlib import Path

from scripts.platform_utils import find_executable

SCENE_THRESHOLD = 0.3
MIN_SCENE_SECONDS = 8.0
MAX_SLIDES = 150
_SENTENCES = re.compile(r"[^。！？!?…]+[。！？!?…”」』）)]*")


def _fmt(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60:02d}:{rest % 60:02d}"


def detect_scenes(video, duration, *, threshold=SCENE_THRESHOLD, min_gap=MIN_SCENE_SECONDS,
                  max_slides=MAX_SLIDES):
    """Return slide start times (seconds). The first slide always starts at 0."""
    ffmpeg = find_executable(["ffmpeg"])
    if not ffmpeg:
        return [0.0]
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(video), "-an", "-vf",
         f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    cuts = [float(value) for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)]
    gap = min_gap
    while True:
        starts = [0.0]
        for cut in cuts:
            if cut - starts[-1] >= gap and duration - cut >= 2:
                starts.append(cut)
        if len(starts) <= max_slides:
            return starts
        gap *= 1.5  # Fast-cut footage (vlogs): keep the document readable.


def extract_frames(video, starts, duration, out_dir):
    ffmpeg = find_executable(["ffmpeg"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else duration
        # A little after the cut avoids cross-fades and half-built slides.
        shot = max(0.0, min(start + min(3.0, (end - start) / 2), end - 0.2))
        target = out_dir / f"slide_{index:03d}.jpg"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{shot:.2f}",
                        "-i", str(video), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2",
                        "-q:v", "4", str(target)], capture_output=True, timeout=120)
        if target.is_file() and target.stat().st_size > 0:
            slides.append({"file": target.name, "start": start, "end": end})
    return slides


def _paragraphs(text, limit=230):
    paragraphs, current = [], ""
    for sentence in _SENTENCES.findall(text) or [text]:
        if current and len(current) + len(sentence) > limit:
            paragraphs.append(current.strip())
            current = ""
        current += sentence
    if current.strip():
        paragraphs.append(current.strip())
    return paragraphs


def align(slides, segments, join_text):
    """Attach each narration segment to the slide on screen when it started."""
    sections = []
    for slide in slides:
        text = ""
        for segment in segments:
            start = float(segment.get("start") or 0)
            if slide["start"] - 0.6 <= start < slide["end"] - 0.6:
                text = join_text(text, str(segment.get("text") or "").strip())
        sections.append({**slide, "time": f"{_fmt(slide['start'])}–{_fmt(slide['end'])}",
                         "paragraphs": _paragraphs(text) if text else []})
    # Closing frames without narration are usually end cards or adverts.
    while len(sections) > 1 and not sections[-1]["paragraphs"]:
        sections.pop()
    return sections


def render_markdown(title, facts, sections, image_prefix="slides/"):
    lines = [f"# {title}", ""]
    if facts:
        lines += ["> " + " · ".join(facts), ""]
    for section in sections:
        lines += [f"![{section['time']}]({image_prefix}{section['file']})", "",
                  f"*{section['time']}*", ""]
        lines += [paragraph + "\n" for paragraph in section["paragraphs"]]
    return "\n".join(lines)


def render_html(title, facts, sections, slides_dir):
    """Self-contained page: images are embedded, so the single file works offline."""
    parts = [f"<h1>{html.escape(title)}</h1>"]
    if facts:
        parts.append(f"<p class='facts'>{html.escape(' · '.join(facts))}</p>")
    for section in sections:
        data = base64.b64encode((Path(slides_dir) / section["file"]).read_bytes()).decode("ascii")
        parts.append(f"<figure><img loading='lazy' src='data:image/jpeg;base64,{data}' "
                     f"alt='{html.escape(section['time'])}'><figcaption>{html.escape(section['time'])}"
                     "</figcaption></figure>")
        parts += [f"<p>{html.escape(paragraph)}</p>" for paragraph in section["paragraphs"]]
    style = ("body{max-width:860px;margin:2rem auto;padding:0 1rem;font:16px/1.85 -apple-system,"
             "'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2937}h1{line-height:1.3}"
             ".facts{color:#6b7280;font-size:.9rem}figure{margin:2rem 0 .6rem}img{width:100%;"
             "border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.12)}figcaption{color:#9ca3af;"
             "font-size:.8rem;text-align:center;margin-top:.3rem}")
    return ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
            f"<style>{style}</style></head><body>{''.join(parts)}</body></html>")


def build(video, segments, job_dir, *, title, facts, join_text, duration):
    """Write 图文稿 files into job_dir; returns the export entries for the UI."""
    job_dir = Path(job_dir)
    slides_dir = job_dir / "slides"
    starts = detect_scenes(video, duration)
    slides = extract_frames(video, starts, duration, slides_dir)
    if not slides:
        return []
    sections = align(slides, segments, join_text)
    (slides_dir / "sections.json").write_text(json.dumps(sections, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    page = job_dir / "illustrated.html"
    page.write_text(render_html(title, facts, sections, slides_dir), encoding="utf-8")
    bundle = job_dir / "illustrated.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("图文稿.md", render_markdown(title, facts, sections))
        for section in sections:
            archive.write(slides_dir / section["file"], f"slides/{section['file']}")
    return [
        {"name": f"图文稿 HTML（{len(sections)} 张图）", "file": page.name, "size": page.stat().st_size},
        {"name": "图文稿 Markdown + 图片", "file": bundle.name, "size": bundle.stat().st_size},
    ]
