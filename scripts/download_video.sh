#!/bin/bash
# Download video with full metadata using yt-dlp
# Usage: ./download_video.sh <VIDEO_URL> <OUTPUT_DIR> [COOKIE_SOURCE]
# Cookie source: chrome (default), firefox, edge, or path to cookies.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/python_cmd.sh"
PYTHON_BIN="$(video2doc_find_python)"

VIDEO_URL="${1:?Usage: $0 <VIDEO_URL> <OUTPUT_DIR> [COOKIE_SOURCE]}"
OUTPUT_DIR="${2:?Usage: $0 <VIDEO_URL> <OUTPUT_DIR> [COOKIE_SOURCE]}"
COOKIE_SOURCE="${3:-chrome}"

mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR"

echo "=== Downloading: $VIDEO_URL ==="
echo "Output dir: $OUTPUT_DIR"
echo "Cookie source: $COOKIE_SOURCE"

# Determine cookies arg
if [[ "$COOKIE_SOURCE" == *.txt ]]; then
    COOKIES_ARGS=(--cookies "$COOKIE_SOURCE")
else
    COOKIES_ARGS=(--cookies-from-browser "$COOKIE_SOURCE")
fi

if command -v yt-dlp >/dev/null 2>&1; then
    YTDLP=(yt-dlp)
elif "$PYTHON_BIN" -c "import yt_dlp" >/dev/null 2>&1; then
    YTDLP=("$PYTHON_BIN" -m yt_dlp)
else
    echo "ERROR: yt-dlp not found. Install with: $PYTHON_BIN -m pip install yt-dlp" >&2
    exit 1
fi

"${YTDLP[@]}" \
    "${COOKIES_ARGS[@]}" \
    --write-info-json \
    --write-thumbnail \
    --write-subs \
    --sub-langs all \
    --embed-metadata \
    --output "%(title).200s-%(id)s.%(ext)s" \
    "$VIDEO_URL"

# Find the info.json and summarize
INFO_JSON=$(ls *.info.json 2>/dev/null | head -1)
if [[ -n "$INFO_JSON" ]]; then
    echo ""
    echo "=== Metadata Summary ==="
    "$PYTHON_BIN" -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    d = json.load(f)
duration = d.get("duration", 0) or 0
print("Title:     {}".format(d.get("title", "N/A")))
print("Uploader:  {}".format(d.get("uploader", "N/A")))
print("Duration:  {:.0f}s ({:.1f}min)".format(duration, duration / 60))
print("Tags:      {}".format(d.get("tags", [])))
print("Chapters:  {} found".format(len(d.get("chapters", []))))
print("Parts:     {}".format(d.get("n_entries", 1)))
' "$INFO_JSON" 2>/dev/null || echo "(Could not parse metadata)"
else
    echo "WARNING: No .info.json found!"
fi

echo ""
echo "=== Download complete ==="
