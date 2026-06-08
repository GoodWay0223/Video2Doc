#!/bin/bash
# Transcribe audio with Whisper and validate output
# Usage: ./transcribe.sh <AUDIO_MP3> <OUTPUT_DIR> <LANGUAGE>
# Language: zh (Chinese → turbo), en (English → small.en), auto (→ turbo)

set -euo pipefail

AUDIO="${1:?Usage: $0 <AUDIO_MP3> <OUTPUT_DIR> <LANGUAGE>}"
OUTPUT_DIR="${2:?Usage: $0 <AUDIO_MP3> <OUTPUT_DIR> <LANGUAGE>}"
LANG="${3:-zh}"

mkdir -p "$OUTPUT_DIR"

# Select model based on language
case "$LANG" in
    zh|chinese|cn)
        MODEL="turbo"
        WHISPER_LANG="zh"
        echo "Language: Chinese → model: turbo"
        ;;
    en|english)
        MODEL="small.en"
        WHISPER_LANG="en"
        echo "Language: English → model: small.en"
        ;;
    *)
        MODEL="turbo"
        WHISPER_LANG="$LANG"
        echo "Language: $LANG → model: turbo (default)"
        ;;
esac

AUDIO_NAME=$(basename "$AUDIO" .mp3)
SRT_OUTPUT="$OUTPUT_DIR/${AUDIO_NAME}.srt"

echo "=== Transcribing: $AUDIO ==="
echo "Model: $MODEL, Language: $WHISPER_LANG"

whisper "$AUDIO" \
    --model "$MODEL" \
    --language "$WHISPER_LANG" \
    --output_format srt \
    --output_dir "$OUTPUT_DIR" \
    --word_timestamps True \
    --condition_on_previous_text False

# Validate: check last segment end time vs audio duration
if [[ -f "$SRT_OUTPUT" ]]; then
    AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO")
    
    LAST_END=$(python3 -c "
import re
with open('$SRT_OUTPUT') as f:
    text = f.read()
segments = re.findall(r'(\d{2}):(\d{2}):(\d{2})[,\.]\d{3}\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,\.]\d{3}', text)
if segments:
    h, m, s = map(int, segments[-1][3:6])
    print(h * 3600 + m * 60 + s)
else:
    print(0)
")
    
    python3 -c "
a = float($AUDIO_DUR)
l = float($LAST_END)
gap = a - l
print(f'Audio duration: {a:.1f}s')
print(f'Last segment ends at: {l:.1f}s')
print(f'Gap: {gap:.1f}s')
if gap > 5:
    print('WARNING: Gap exceeds 5s — transcription may be truncated!')
elif gap < -2:
    print('WARNING: Last segment exceeds audio duration — possible artifact!')
else:
    print('OK: Last segment end time is close to audio duration')
"
    
    SEG_COUNT=$(grep -c '-->' "$SRT_OUTPUT" || echo 0)
    echo "Total segments: $SEG_COUNT"
else
    echo "ERROR: SRT output not found!"
    exit 1
fi

echo ""
echo "=== Transcription complete ==="
echo "Output: $SRT_OUTPUT"
