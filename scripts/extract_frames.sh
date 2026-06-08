#!/bin/bash
# Extract representative keyframes from video chapters
# Usage: ./extract_frames.sh <VIDEO_FILE> <CHAPTERS_CSV> <OUTPUT_DIR>
# CHAPTERS_CSV format: ch_label,start_sec,end_sec
#   Example: ch01_intro,0,120
#            ch02_setup,120,340

set -euo pipefail

VIDEO="${1:?Usage: $0 <VIDEO_FILE> <CHAPTERS_CSV> <OUTPUT_DIR>}"
CHAPTERS_CSV="${2:?Usage: $0 <VIDEO_FILE> <CHAPTERS_CSV> <OUTPUT_DIR>}"
OUTPUT_DIR="${3:?Usage: $0 <VIDEO_FILE> <CHAPTERS_CSV> <OUTPUT_DIR>}"

mkdir -p "$OUTPUT_DIR"
TMPDIR="${OUTPUT_DIR}/.tmp_frames"
mkdir -p "$TMPDIR"

VIDEO_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
VIDEO_DUR=${VIDEO_DUR%.*}
echo "Video duration: ${VIDEO_DUR}s"

process_chapter() {
    local ch_label="$1"
    local start_sec="$2"
    local end_sec="$3"
    
    # Clamp end_sec to video duration
    if [[ "$end_sec" -gt "$VIDEO_DUR" ]]; then
        end_sec="$VIDEO_DUR"
    fi
    
    local chapter_len=$((end_sec - start_sec))
    echo "  Chapter: $ch_label  [${start_sec}s - ${end_sec}s]  (${chapter_len}s)"
    
    # For short chapters (< 30s), extract one frame at midpoint
    if [[ "$chapter_len" -le 30 ]]; then
        local mid=$((start_sec + chapter_len / 2))
        ffmpeg -ss "$mid" -i "$VIDEO" \
            -vframes 1 -q:v 1 \
            "$OUTPUT_DIR/${ch_label}_${mid}s.jpg" -y 2>/dev/null
        echo "    → Extracted 1 frame at ${mid}s"
        return
    fi
    
    # For longer chapters, use parallel shard extraction
    # Sample at 1 frame per 5 seconds (~12 frames/min, good coverage)
    local fps=$(python3 -c "print(max(0.2, min(2, 60/$chapter_len)))")
    
    ffmpeg -ss "$start_sec" -to "$end_sec" \
        -i "$VIDEO" \
        -vf "fps=$fps" \
        -q:v 3 \
        "$TMPDIR/${ch_label}_%04d.jpg" -y 2>/dev/null
    
    local frame_count=$(ls "$TMPDIR/${ch_label}_"*.jpg 2>/dev/null | wc -l | tr -d ' ')
    echo "    → Extracted $frame_count candidate frames"
    
    # Select the best frame: largest file size (generally = most detail/information)
    local best_frame=$(ls -S "$TMPDIR/${ch_label}_"*.jpg 2>/dev/null | head -1)
    if [[ -n "$best_frame" ]]; then
        # Extract timestamp from filename (approximate by frame number)
        local frame_num=$(echo "$best_frame" | grep -oP '\d{4}(?=\.jpg)')
        local est_time=$(python3 -c "print(int($start_sec + int('$frame_num') / $fps))")
        
        cp "$best_frame" "$OUTPUT_DIR/${ch_label}_${est_time}s.jpg"
        local fsize=$(ls -lh "$best_frame" | awk '{print $5}')
        echo "    → Selected best frame: frame #$frame_num (~${est_time}s), ${fsize}"
    fi
    
    # Clean up temp frames for this chapter
    rm -f "$TMPDIR/${ch_label}_"*.jpg
}

echo ""
echo "=== Extracting keyframes ==="

while IFS=',' read -r ch_label start_sec end_sec; do
    # Skip empty lines and header
    [[ -z "$ch_label" || "$ch_label" == "ch_label" ]] && continue
    process_chapter "$ch_label" "$start_sec" "$end_sec"
done < "$CHAPTERS_CSV"

# Cleanup
rm -rf "$TMPDIR"

echo ""
echo "=== Frame extraction complete ==="
echo "Frames saved to: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR"/*.jpg 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}'
