#!/usr/bin/env python3
"""
Video2Doc Web UI — 本地可视化前端
Run: python3 webui.py
Open: http://localhost:8765

Three core functions:
  1. Video download — paste link, get video file
  2. Online transcription — paste link, AI transcribes to text
  3. Local media transcription — upload file, AI transcribes to text
"""
import argparse
import http.server
import sys
from webui import __version__
from webui.server import Handler

PORT = 8765
HOST = "127.0.0.1"


def configure_console_encoding():
    """Keep Chinese/emoji status output safe in redirected Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (LookupError, OSError):
                pass

def main():
    configure_console_encoding()
    parser = argparse.ArgumentParser(description='Video2Doc Web UI')
    parser.add_argument('--no-check', action='store_true', help='跳过启动环境检查')
    parser.add_argument('--check-only', action='store_true', help='仅运行环境检查，不启动服务')
    parser.add_argument('--port', type=int, default=PORT, help=f'指定端口 (默认: {PORT})')
    parser.add_argument('--host', default=HOST,
                        help=f'监听地址 (默认: {HOST}；局域网共享时可显式指定 0.0.0.0)')
    args = parser.parse_args()

    # Startup environment check
    if not args.no_check:
        try:
            from scripts.check_setup import check_all, print_report
            results = check_all()
            all_ok = print_report(results)
            if not all_ok:
                print("  提示：使用 --no-check 可跳过此检查")
                print("  部分功能可能不可用\n")
        except ImportError:
            print("  ⚠️ 环境检查脚本未找到，跳过自检\n")

    if args.check_only:
        return

    port = args.port
    host = args.host
    server = http.server.HTTPServer((host, port), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║   🎬 Video2Doc 工坊 v{__version__:<20}║
║                                          ║
║   打开: http://{host}:{port}                  ║
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
