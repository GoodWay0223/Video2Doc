#!/usr/bin/env python3
"""Verify HTML output with Chrome headless and crop into slices.

Usage: python3 verify_html.py <HTML_FILE> <OUTPUT_DIR>
"""

import subprocess
import sys
import os
from pathlib import Path

try:
    from .platform_utils import find_executable
except ImportError:  # Direct execution: python scripts/verify_html.py
    from platform_utils import find_executable


def chrome_candidates(*, os_name=None, environ=None):
    """Return standard browser install locations for the requested platform."""
    os_name = os.name if os_name is None else os_name
    environ = os.environ if environ is None else environ
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    if os_name == "nt":
        for base_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = environ.get(base_name)
            if not base:
                continue
            candidates.extend([
                str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            ])
    return candidates


def find_chrome():
    """Find Chrome/Chromium on Windows, macOS, or Linux."""
    candidates = chrome_candidates()
    for c in candidates:
        if os.path.exists(c):
            return c
    return find_executable([
        "chrome", "chrome.exe", "msedge", "msedge.exe",
        "google-chrome", "chromium", "chromium-browser",
    ])


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <HTML_FILE> <OUTPUT_DIR>")
        sys.exit(1)

    html_file = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    if not html_file.is_file():
        print(f"ERROR: HTML file not found: {html_file}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    chrome = find_chrome()
    if not chrome:
        print("ERROR: Chrome/Chromium not found!")
        sys.exit(1)

    print(f"Using Chrome: {chrome}")
    print(f"HTML file: {html_file}")
    print(f"Output dir: {output_dir}")

    # Step 1: Full-page screenshot
    full_page_png = output_dir / "full_page.png"
    print("\n=== Step 1: Taking full-page screenshot ===")

    result = subprocess.run(
        [
            chrome,
            "--headless",
            "--disable-gpu",
            f"--screenshot={full_page_png}",
            "--window-size=1280,900",
            "--virtual-time-budget=15000",
            "--hide-scrollbars",
            html_file.as_uri(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    if result.returncode != 0:
        print(f"ERROR: Chrome exited with code {result.returncode}")
        print(result.stderr[-500:] if result.stderr else "(no stderr)")
        sys.exit(1)

    if not full_page_png.is_file():
        print("ERROR: Screenshot was not created!")
        sys.exit(1)

    # Get image dimensions
    ffprobe = find_executable(["ffprobe", "ffprobe.exe"])
    if not ffprobe:
        print("ERROR: ffprobe not found!")
        sys.exit(1)
    probe = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            full_page_png,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode != 0:
        print(f"ERROR: ffprobe failed: {probe.stderr.strip()}")
        sys.exit(1)
    try:
        width, height = probe.stdout.strip().split(",")
    except ValueError:
        print("ERROR: ffprobe returned invalid image dimensions")
        sys.exit(1)
    width, height = int(width), int(height)
    print(f"Screenshot dimensions: {width}x{height}px")
    print(f"File size: {full_page_png.stat().st_size / 1024:.0f} KB")

    # Step 2: Crop with overlap
    print("\n=== Step 2: Cropping with 100px overlap ===")
    slice_height = 900  # Match window height for readable slices
    overlap = 100
    effective_height = slice_height - overlap

    num_slices = max(1, (height + effective_height - 1) // effective_height)
    print(f"Generating {num_slices} slices...")

    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe"])
    if not ffmpeg:
        print("ERROR: ffmpeg not found!")
        sys.exit(1)

    for i in range(num_slices):
        y_offset = max(0, i * effective_height)
        actual_height = min(slice_height, height - y_offset)
        slice_path = output_dir / f"slice_{i+1:02d}.png"

        subprocess.run(
            [
                ffmpeg,
                "-i", full_page_png,
                "-vf", f"crop={width}:{actual_height}:0:{y_offset}",
                "-y",
                slice_path,
            ],
            capture_output=True,
            check=True,
        )

        fsize = slice_path.stat().st_size / 1024
        print(f"  slice_{i+1:02d}.png: y={y_offset}, {width}x{actual_height}px, {fsize:.0f} KB")

    print("\n=== Verification complete ===")
    print(f"Full page: {full_page_png}")
    print(f"Slices ({num_slices}): {output_dir}/")


if __name__ == "__main__":
    main()
