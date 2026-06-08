#!/bin/bash
# Extract best audio, convert to MP3, and validate duration
# Usage: ./extract_audio.sh <VIDEO_FILE> <INFO_JSON> <OUTPUT_MP3>

set -euo pipefail

VIDEO_FILE="${1:?Usage: $0 <VIDEO_FILE> <INFO_JSON> <OUTPUT_MP3>}"
INFO_JSON="${2:?Usage: $0 <VIDEO_FILE> <INFO_JSON> <OUTPUT_MP3>}"
OUTPUT_MP3="${3:?Usage: $0 <VIDEO_FILE> <INFO_JSON> <OUTPUT_MP3>}"

echo "=== Extracting audio from: $VIDEO_FILE ==="

# Step 1: Extract and convert to MP3
ffmpeg -i "$VIDEO_FILE" \
    -vn \
    -acodec libmp3lame \
    -q:a 2 \
    -y \
    "$OUTPUT_MP3" 2>&1 | tail -5

# Step 2: Get audio duration from ffprobe
AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUTPUT_MP3")
echo "Audio duration (ffprobe): ${AUDIO_DUR}s"

# Step 3: Get metadata duration from info.json
if [[ -f "$INFO_JSON" ]]; then
    META_DUR=$(python3 -c "import json; print(json.load(open('$INFO_JSON')).get('duration', 0))" 2>/dev/null || echo "0")
    echo "Metadata duration: ${META_DUR}s"

    # Step 4: Compare
    python3 -c "
a = float($AUDIO_DUR)
m = float($META_DUR)
if m == 0:
    print('WARNING: Metadata duration is 0, cannot validate')
    exit(0)
diff = abs(a - m) / m * 100
print(f'Discrepancy: {diff:.1f}%')
if diff > 5:
    print('ERROR: Duration discrepancy exceeds 5% threshold!')
    print(f'  Audio: {a:.1f}s, Metadata: {m:.1f}s, Diff: {diff:.1f}%')
    exit(1)
else:
    print('OK: Duration within acceptable range')
"
    VALID=$?
else
    echo "WARNING: No info.json found, skipping duration validation"
    VALID=0
fi

echo ""
echo "=== Audio extraction complete ==="
echo "Output: $OUTPUT_MP3"
echo "Duration: ${AUDIO_DUR}s"
echo "Validated: $([ $VALID -eq 0 ] && echo 'YES' || echo 'NO - needs re-download')"

exit $VALID
