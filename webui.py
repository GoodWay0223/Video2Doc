#!/usr/bin/env python3
"""
Video2Doc Web UI v0.4.0 — 本地可视化前端
Run: python3 webui.py
Open: http://localhost:8765

Three core functions:
  1. Video download — paste link, get video file
  2. Online transcription — paste link, AI transcribes to text
  3. Local media transcription — upload file, AI transcribes to text
"""
import http.server, sys
from webui.server import Handler

PORT = 8765

def main():
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║   🎬 Video2Doc 工坊 v0.4.0               ║
║                                          ║
║   打开: http://localhost:{PORT}              ║
║   按 Ctrl+C 停止                           ║
╚══════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()

if __name__ == "__main__":
    main()
