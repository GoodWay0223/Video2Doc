#!/usr/bin/env python3
"""
Video2Doc — Multi-Format Exporter
Converts TeleSpeechASR verbose_json output into:
  - SRT (subtitles with timestamps)
  - JSON (structured segments)
  - TXT (plain text, no timestamps)

Usage:
  cat tele_result.json | python3 export_formats.py --format srt > output.srt
  python3 export_formats.py --input tele_result.json --format all --output-dir ./output/
  python3 export_formats.py --input tele_result.json --format txt --correct --domain auto > corrected.txt
"""

import sys, json, argparse, os
from pathlib import Path

def format_time(seconds):
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def to_srt(segments):
    """Generate SRT subtitle format"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_time(seg.get("start", 0))
        end = format_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)

def to_txt(segments):
    """Generate plain text (all segments joined)"""
    return "\n".join(seg.get("text", "").strip() for seg in segments if seg.get("text", "").strip())

def to_json_structured(segments):
    """Generate structured JSON with metadata"""
    return json.dumps({
        "segments": [
            {
                "index": seg.get("id", i),
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip(),
                "duration": round(seg.get("end", 0) - seg.get("start", 0), 2)
            }
            for i, seg in enumerate(segments)
        ],
        "total_segments": len(segments),
        "total_duration": round(sum(
            seg.get("end", 0) - seg.get("start", 0) for seg in segments
        ), 2)
    }, ensure_ascii=False, indent=2)

def to_md(segments, title="", source=""):
    """Generate Markdown transcript"""
    lines = []
    if title:
        lines.append(f"# {title}\n")
    if source:
        lines.append(f"来源：{source}\n")
    for seg in segments:
        text = seg.get("text", "").strip()
        if text:
            lines.append(text + "\n")
    return "\n".join(lines)

def apply_corrections_to_segments(segments, corrections_script):
    """Run corrections script on all segment texts"""
    import subprocess
    import tempfile

    combined = "\n".join(seg.get("text", "") for seg in segments)
    script_path = str(Path(__file__).parent / "apply_corrections.py")

    result = subprocess.run(
        [sys.executable, script_path],
        input=combined, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Warning: corrections failed: {result.stderr}", file=sys.stderr)
        return segments

    corrected_lines = result.stdout.strip().split("\n")
    for i, seg in enumerate(segments):
        if i < len(corrected_lines):
            seg["text"] = corrected_lines[i]
        else:
            break
    return segments

def main():
    parser = argparse.ArgumentParser(description="Multi-format exporter for Video2Doc")
    parser.add_argument("--input", "-i", help="Input JSON file (stdin if omitted)")
    parser.add_argument("--format", "-f", default="srt",
                        choices=["srt", "txt", "json", "md", "all"],
                        help="Output format (default: srt)")
    parser.add_argument("--output-dir", "-o", help="Output directory (for --format all)")
    parser.add_argument("--title", help="Video title (for markdown)")
    parser.add_argument("--source", help="Video source URL")
    parser.add_argument("--correct", action="store_true", help="Apply corrections before export")
    parser.add_argument("--domain", help="Correction domain (auto, tech)")

    args = parser.parse_args()

    # Read input
    if args.input:
        with open(args.input) as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    segments = data.get("segments", [])
    full_text = data.get("text", "")

    # If no segments, create one from full text
    if not segments and full_text:
        segments = [{"id": 0, "start": 0, "end": 0, "text": full_text}]

    # Apply corrections if requested
    if args.correct:
        segments = apply_corrections_to_segments(segments, None)

    # Generate output
    outputs = {}
    formats_to_generate = ["srt", "txt", "json", "md"] if args.format == "all" else [args.format]

    for fmt in formats_to_generate:
        if fmt == "srt":
            outputs["transcript.srt"] = to_srt(segments)
        elif fmt == "txt":
            outputs["transcript.txt"] = to_txt(segments)
        elif fmt == "json":
            outputs["transcript.json"] = to_json_structured(segments)
        elif fmt == "md":
            outputs["transcript.md"] = to_md(segments, args.title or "", args.source or "")

    if args.format == "all" and args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        for name, content in outputs.items():
            path = os.path.join(args.output_dir, name)
            with open(path, 'w') as f:
                f.write(content)
            print(f"  ✅ {path}")
    else:
        for content in outputs.values():
            print(content)

if __name__ == "__main__":
    main()
