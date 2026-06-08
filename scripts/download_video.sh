#!/bin/bash
# Download video with full metadata using yt-dlp
# Usage: ./download_video.sh <VIDEO_URL> <OUTPUT_DIR> [COOKIE_SOURCE]
# Cookie source: chrome (default), firefox, edge, or path to cookies.txt

set -euo pipefail

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
    COOKIES_ARG="--cookies $COOKIE_SOURCE"
else
    COOKIES_ARG="--cookies-from-browser $COOKIE_SOURCE"
fi

yt-dlp \
    $COOKIES_ARG \
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
    python3 -c "
import json, sys
with open('$INFO_JSON') as f:
    d = json.load(f)
print(f'Title:     {d.get(\"title\", \"N/A\")}')
print(f'Uploader:  {d.get(\"uploader\", \"N/A\")}')
print(f'Duration:  {d.get(\"duration\", 0):.0f}s ({d.get(\"duration\", 0)/60:.1f}min)')
print(f'Tags:      {d.get(\"tags\", [])}')
print(f'Chapters:  {len(d.get(\"chapters\", []))} found')
print(f'Parts:     {d.get(\"n_entries\", 1)}')
" 2>/dev/null || echo "(Could not parse metadata)"
else
    echo "WARNING: No .info.json found!"
fi

echo ""
echo "=== Download complete ==="
