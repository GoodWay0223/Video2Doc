#!/usr/bin/env bash
# ============================================================
# Video2Doc — Config Loader (Cross-Agent)
# Source this file to get $SILICONFLOW_API_KEY from any Agent.
#
# Priority (highest first):
#   1. SILICONFLOW_API_KEY environment variable
#   2. ~/.video2doc/config.json
#   3. ~/.workbuddy/MEMORY.md (WorkBuddy legacy)
#
# Usage:
#   source scripts/load_config.sh
#   echo "Key: ${SILICONFLOW_API_KEY:0:20}..."
# ============================================================

# If already set via environment, use it directly
if [ -n "${SILICONFLOW_API_KEY:-}" ]; then
  export SILICONFLOW_API_KEY
  return 0 2>/dev/null || exit 0
fi

# Try cross-Agent config file
if [ -f "$HOME/.video2doc/config.json" ]; then
  KEY=$(python3 -c "
import json, sys
try:
  with open('$HOME/.video2doc/config.json') as f:
    d = json.load(f)
  k = d.get('siliconflow_api_key', '')
  if k and k != 'sk-xxxxxxxxxxxx':
    print(k)
    sys.exit(0)
except: pass
sys.exit(1)
" 2>/dev/null)
  if [ -n "$KEY" ]; then
    export SILICONFLOW_API_KEY="$KEY"
    return 0 2>/dev/null || exit 0
  fi
fi

# Fall back to WorkBuddy MEMORY.md (legacy)
if [ -f "$HOME/.workbuddy/MEMORY.md" ]; then
  KEY=$(grep "SILICONFLOW_API_KEY:" "$HOME/.workbuddy/MEMORY.md" 2>/dev/null | head -1 | awk '{print $NF}')
  if [ -n "$KEY" ] && [ "$KEY" != "sk-xxxxxxxxxxxx" ]; then
    export SILICONFLOW_API_KEY="$KEY"
    return 0 2>/dev/null || exit 0
  fi
fi

# Not found
echo "❌ SILICONFLOW_API_KEY not configured. Choose one:" >&2
echo "   export SILICONFLOW_API_KEY=sk-xxxx" >&2
echo "   mkdir -p ~/.video2doc && echo '{\"siliconflow_api_key\":\"sk-xxxx\"}' > ~/.video2doc/config.json" >&2
echo "   Or register: https://cloud.siliconflow.cn/i/pWcvZzOr" >&2
return 1 2>/dev/null || exit 1
