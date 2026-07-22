#!/usr/bin/env bash
# Keep the shell entry point for macOS/Git Bash, but use the same checker as
# `python webui.py --check-only` so supported-platform results cannot drift.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/python_cmd.sh"
PYTHON_BIN="$(video2doc_find_python)"
exec "$PYTHON_BIN" "$SCRIPT_DIR/check_setup.py" "$@"
