#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

source "$SCRIPT_DIR/scripts/python_cmd.sh"
PYTHON_BIN="$(video2doc_find_python)" || {
  echo "请先运行 brew install python，或从 https://www.python.org/downloads/macos/ 安装。" >&2
  exit 1
}

exec "$PYTHON_BIN" webui.py "$@"
