#!/usr/bin/env bash
# ============================================================
# Video2Doc — CLI Entry Point (Bash wrapper)
#
# Thin wrapper around video2doc.py so the CLI and the Web UI share exactly
# the same download / subtitle / ASR / export pipeline.
#
# Usage:
#   ./video2doc.sh "https://www.bilibili.com/video/BV..."
#   ./video2doc.sh --format all meeting.m4a
#   ./video2doc.sh --download "https://youtu.be/..."
#   ./video2doc.sh --batch links.txt --format md,srt
#
# Run ./video2doc.sh --help for every option. On Windows without Bash,
# use: python video2doc.py ...
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Windows Git Bash commonly exposes a non-working Microsoft Store `python3`
# alias. Resolve and execute-test the interpreter before doing any work.
source "$SCRIPT_DIR/scripts/python_cmd.sh"
PYTHON_BIN="$(video2doc_find_python)" || exit 1

exec "$PYTHON_BIN" "$SCRIPT_DIR/video2doc.py" "$@"
