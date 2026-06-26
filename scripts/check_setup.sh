#!/usr/bin/env bash
# ============================================================
# Video2Doc — Environment Setup Check
# Checks all dependencies and tells you what's missing.
# Run: bash check_setup.sh
# ============================================================
set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PASS=0
WARN=0
FAIL=0
MISSING=()

ok()   { echo -e "  ${GREEN}✅${NC} $1"; ((PASS++)); }
warn() { echo -e "  ${YELLOW}⚠️${NC}  $1"; ((WARN++)); }
fail() { echo -e "  ${RED}❌${NC} $1"; ((FAIL++)); MISSING+=("$1"); }

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║   Video2Doc — Environment Checker    ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${NC}"
echo ""

# ─── Core Tools ───────────────────────────────────────────
echo -e "${BOLD}📦 Core Tools${NC}"

if command -v yt-dlp &>/dev/null; then
  ok "yt-dlp — $(yt-dlp --version 2>&1 | head -1)"
elif [ -f "$HOME/.workbuddy/binaries/python/envs/default/bin/yt-dlp" ]; then
  ok "yt-dlp — found in WorkBuddy managed path"
else
  fail "yt-dlp — NOT FOUND (pip install yt-dlp)"
fi

if command -v ffmpeg &>/dev/null; then
  ok "ffmpeg — $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
elif [ -f "$HOME/.workbuddy/binaries/ffmpeg/ffmpeg" ]; then
  ok "ffmpeg — found in WorkBuddy managed path"
else
  fail "ffmpeg — NOT FOUND (brew install ffmpeg / apt install ffmpeg)"
fi

if command -v ffprobe &>/dev/null; then
  ok "ffprobe"
elif [ -f "$HOME/.workbuddy/binaries/ffmpeg/ffprobe" ]; then
  ok "ffprobe — found in WorkBuddy managed path"
else
  fail "ffprobe — NOT FOUND (comes with ffmpeg)"
fi

if command -v curl &>/dev/null; then
  ok "curl — $(curl --version 2>&1 | head -1 | awk '{print $2}')"
else
  fail "curl — NOT FOUND"
fi

if command -v python3 &>/dev/null; then
  ok "python3 — $(python3 --version 2>&1)"
else
  fail "python3 — NOT FOUND"
fi

echo ""
echo -e "${BOLD}📦 Platform-Specific Tools${NC}"

# playwright-cli
if command -v playwright-cli &>/dev/null; then
  ok "playwright-cli — $(playwright-cli --version 2>&1 || echo 'installed')"
elif command -v npx &>/dev/null; then
  warn "playwright-cli — NOT installed globally, but npx available (npx @playwright/cli@latest)"
else
  fail "playwright-cli/npx — NOT FOUND (npm i -g @playwright/cli@latest)"
fi

echo ""
echo -e "${BOLD}📦 Transcription Engines${NC}"

# Whisper (optional)
if python3 -c "import whisper" 2>/dev/null; then
  ok "openai-whisper — installed (local fallback)"
else
  warn "openai-whisper — NOT installed (optional, only for offline fallback)"
fi

# emoji (for SenseVoiceSmall)
if python3 -c "import emoji" 2>/dev/null; then
  ok "emoji — installed (SenseVoiceSmall cleanup)"
else
  warn "emoji — NOT installed (pip install emoji, needed for SenseVoiceSmall)"
fi

echo ""
echo -e "${BOLD}🔑 API Configuration${NC}"

FOUND_KEY=false

# 1. Environment variable (cross-Agent, preferred)
if [ -n "${SILICONFLOW_API_KEY:-}" ]; then
  ok "SILICONFLOW_API_KEY — set via environment variable"
  FOUND_KEY=true
fi

# 2. Cross-Agent config file
if [ -f "$HOME/.video2doc/config.json" ]; then
  if python3 -c "
import json, sys
try:
  with open('$HOME/.video2doc/config.json') as f:
    d = json.load(f)
  if d.get('siliconflow_api_key') and d['siliconflow_api_key'] != 'sk-xxxxxxxxxxxx':
    sys.exit(0)
  else:
    sys.exit(1)
except: sys.exit(1)
" 2>/dev/null; then
  if [ "$FOUND_KEY" = false ]; then
    ok "siliconflow_api_key — found in ~/.video2doc/config.json"
    FOUND_KEY=true
  else
    ok "siliconflow_api_key — also in ~/.video2doc/config.json"
  fi
else
  warn "~/.video2doc/config.json exists but contains no valid key"
fi
fi

# 3. WorkBuddy MEMORY.md (legacy, backward-compatible)
if [ -f "$HOME/.workbuddy/MEMORY.md" ]; then
  WB_KEY=$(grep "SILICONFLOW_API_KEY:" "$HOME/.workbuddy/MEMORY.md" 2>/dev/null | head -1 | awk '{print $NF}')
  if [ -n "$WB_KEY" ] && [ "$WB_KEY" != "sk-xxxxxxxxxxxx" ]; then
    if [ "$FOUND_KEY" = false ]; then
      ok "SILICONFLOW_API_KEY — found in ~/.workbuddy/MEMORY.md"
      FOUND_KEY=true
    else
      ok "SILICONFLOW_API_KEY — also in ~/.workbuddy/MEMORY.md"
    fi
  fi
fi

if [ "$FOUND_KEY" = false ]; then
  warn "NO SiliconFlow API Key configured"
  echo ""
  echo -e "  ${CYAN}To fix, choose ONE of:${NC}"
  echo -e "  ${CYAN}  • export SILICONFLOW_API_KEY=sk-xxxxx${NC}"
  echo -e "  ${CYAN}  • mkdir -p ~/.video2doc && echo '{\"siliconflow_api_key\":\"sk-xxxxx\"}' > ~/.video2doc/config.json${NC}"
  echo -e "  ${CYAN}  • 注册: https://cloud.siliconflow.cn/i/pWcvZzOr${NC}"
fi

# ─── Summary ──────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║   Summary                            ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${NC}"
echo -e "  ${GREEN}Passed:${NC} $PASS  ${YELLOW}Warnings:${NC} $WARN  ${RED}Failed:${NC} $FAIL"

if [ $FAIL -eq 0 ] && [ $WARN -eq 0 ]; then
  echo ""
  echo -e "  ${GREEN}${BOLD}🎉 All checks passed! Ready to process videos.${NC}"
  exit 0
elif [ $FAIL -eq 0 ]; then
  echo ""
  echo -e "  ${YELLOW}${BOLD}⚠️  All core tools available. Some optional items missing.${NC}"
  exit 0
else
  echo ""
  echo -e "  ${RED}${BOLD}❌ ${#MISSING[@]} required tool(s) missing:${NC}"
  for m in "${MISSING[@]}"; do
    echo -e "    • $m"
  done
  echo ""
  echo -e "  ${CYAN}Install missing tools, then re-run this script.${NC}"
  exit 1
fi
