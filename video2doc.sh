#!/usr/bin/env bash
# ============================================================
# Video2Doc — CLI Entry Point
# Convert video links into structured documentation.
#
# Usage:
#   # Single video (pure transcript)
#   ./video2doc.sh "https://v.douyin.com/xxxx"
#
#   # Single video (deep analysis HTML)
#   ./video2doc.sh --mode deep "https://v.douyin.com/xxxx"
#
#   # Batch mode (one link per line)
#   ./video2doc.sh --batch links.txt
#
#   # With custom output dir
#   ./video2doc.sh --output ~/my-transcripts "https://v.douyin.com/xxxx"
#
#   # Export specific formats
#   ./video2doc.sh --format srt,txt "https://v.douyin.com/xxxx"
#
# Flags:
#   --mode transcript|deep     Output mode (default: transcript)
#   --batch FILE               Process multiple links from file
#   --output DIR               Output directory (default: auto-generated)
#   --format FORMATS           Export formats: srt,txt,json,md (default: md)
#   --cookie FILE              Cookies file for Douyin/XHS
#   --domain auto|tech|general Apply domain corrections
#   --verbose                  Show detailed logs
#   --dry-run                  Show what would be done
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# SCRIPT_DIR = Video2Doc/ (since video2doc.sh is at repo root)

# Load config (API key etc.)
source "$SCRIPT_DIR/scripts/load_config.sh" 2>/dev/null || true

# ─── Defaults ───────────────────────────────────────────
MODE="transcript"
BATCH_FILE=""
OUTPUT_DIR=""
FORMATS="md"
COOKIE_FILE=""
DOMAIN=""
VERBOSE=false
DRY_RUN=false
LINKS=()

# ─── Parse Args ─────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --batch) BATCH_FILE="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    --format) FORMATS="$2"; shift 2 ;;
    --cookie) COOKIE_FILE="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --verbose) VERBOSE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h)
      head -30 "$0" | grep "^#" | sed 's/^# \?//'
      exit 0
      ;;
    *) LINKS+=("$1"); shift ;;
  esac
done

# ─── Resolve batch file ─────────────────────────────────
if [ -n "$BATCH_FILE" ]; then
  if [ ! -f "$BATCH_FILE" ]; then
    echo "❌ Batch file not found: $BATCH_FILE"
    exit 1
  fi
  while IFS= read -r line; do
    line=$(echo "$line" | sed 's/#.*//' | xargs)
    [ -n "$line" ] && LINKS+=("$line")
  done < "$BATCH_FILE"
fi

# ─── Validate ───────────────────────────────────────────
if [ ${#LINKS[@]} -eq 0 ]; then
  echo "❌ No video links provided."
  echo "Usage: $0 [--batch links.txt] <video_url> [video_url...]"
  exit 1
fi

echo "🎬 Video2Doc — Processing ${#LINKS[@]} video(s)"
echo "   Mode: $MODE | Formats: $FORMATS | Domain: ${DOMAIN:-none}"
if [ "$DRY_RUN" = true ]; then
  echo "   ⚠️  DRY RUN — no actual processing"
fi
echo ""

# ─── Process each link ──────────────────────────────────
SUCCESS=0
FAILED=0

for i in "${!LINKS[@]}"; do
  LINK="${LINKS[$i]}"
  IDX=$((i + 1))
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  [$IDX/${#LINKS[@]}] $LINK"
  echo ""

  # Resolve short link → full URL
  FULL_URL=$(curl -sI -o /dev/null -w "%{url_effective}" -L "$LINK" 2>/dev/null || echo "$LINK")
  VIDEO_ID=$(echo "$FULL_URL" | grep -oE 'video/([0-9]+)' | cut -d/ -f2 || echo "unknown")
  TIMESTAMP=$(date +%Y%m%d-%H%M%S)
  PROJ_DIR="${OUTPUT_DIR:-./output}/${VIDEO_ID:-v$TIMESTAMP}"
  mkdir -p "$PROJ_DIR/raw"

  if [ "$DRY_RUN" = true ]; then
    echo "  [DRY RUN] Would process: $FULL_URL → $PROJ_DIR"
    continue
  fi

  # Phase 1: Download (placeholder — actual download needs platform logic)
  # For Douyin, this would use Playwright MediaRecorder
  # For Bilibili/YouTube, use yt-dlp
  echo "  📥 Downloading... (platform detection TBD)"
  echo "  ⚠️  Download step requires manual workflow for now."
  echo "  ⚠️  See SKILL.md for platform-specific download instructions."
  echo ""

  # Phase 2: Extract audio (if video exists)
  VIDEO_FILE="$PROJ_DIR/raw/video.mp4"
  if [ -f "$VIDEO_FILE" ]; then
    echo "  🎵 Extracting audio..."
    if command -v ffmpeg &>/dev/null; then
      ffmpeg -i "$VIDEO_FILE" -vn -acodec libmp3lame -q:a 2 "$PROJ_DIR/raw/audio.mp3" -y 2>/dev/null
    elif [ -f "$HOME/.workbuddy/binaries/ffmpeg/ffmpeg" ]; then
      "$HOME/.workbuddy/binaries/ffmpeg/ffmpeg" -i "$VIDEO_FILE" -vn -acodec libmp3lame -q:a 2 "$PROJ_DIR/raw/audio.mp3" -y 2>/dev/null
    fi
    echo "  ✅ Audio extracted: $PROJ_DIR/raw/audio.mp3"
  fi

  # Phase 3: Transcribe (if audio + API key available)
  AUDIO_FILE="$PROJ_DIR/raw/audio.mp3"
  if [ -f "$AUDIO_FILE" ] && [ -n "${SILICONFLOW_API_KEY:-}" ]; then
    echo "  🎙️  Transcribing with TeleSpeechASR..."
    RESULT=$(curl -s --max-time 120 --retry 3 --retry-delay 2 \
      https://api.siliconflow.cn/v1/audio/transcriptions \
      -H "Authorization: Bearer $SILICONFLOW_API_KEY" \
      -F "file=@$AUDIO_FILE" \
      -F "model=TeleAI/TeleSpeechASR" \
      -F "response_format=verbose_json" 2>&1)
    echo "$RESULT" > "$PROJ_DIR/raw/tele_result.json"
    echo "  ✅ Transcription saved: $PROJ_DIR/raw/tele_result.json"

    # Phase 4: Apply corrections + Export
    echo "  📝 Exporting ($FORMATS)..."
    CORRECT_FLAG=""
    [ -n "$DOMAIN" ] && CORRECT_FLAG="--correct --domain $DOMAIN"

    IFS=',' read -ra FMT_ARR <<< "$FORMATS"
    for fmt in "${FMT_ARR[@]}"; do
      python3 "$SCRIPT_DIR/export_formats.py" \
        --input "$PROJ_DIR/raw/tele_result.json" \
        --format "$fmt" \
        --output-dir "$PROJ_DIR" \
        $CORRECT_FLAG 2>/dev/null || true
    done
    echo "  ✅ Exports: $(ls "$PROJ_DIR"/transcript.* 2>/dev/null | tr '\n' ' ')"
    ((SUCCESS++))
  elif [ -f "$AUDIO_FILE" ]; then
    echo "  ⚠️  No API key configured. Skipping transcription."
    echo "  Run: source scripts/load_config.sh"
  fi

  echo ""
done

# ─── Summary ──────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════"
echo "  ✅ $SUCCESS succeeded  ❌ $FAILED failed"
echo "  Output: ${OUTPUT_DIR:-./output}/"
