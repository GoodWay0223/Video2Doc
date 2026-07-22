#!/usr/bin/env bash
# Resolve a working Python 3 command on macOS and Windows Git Bash/WSL.

video2doc_find_python() {
  local candidate=""
  local candidates=()

  if [ -n "${VIDEO2DOC_PYTHON:-}" ]; then
    candidates+=("$VIDEO2DOC_PYTHON")
  fi
  candidates+=(python3 python)

  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1 \
       && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' \
          >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "ERROR: Python 3.10+ not found (tried VIDEO2DOC_PYTHON, python3, python)." >&2
  return 1
}
