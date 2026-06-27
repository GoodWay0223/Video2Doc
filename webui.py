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
import http.server, sys, argparse
from webui.server import Handler

PORT = 8765

def main():
    parser = argparse.ArgumentParser(description='Video2Doc Web UI')
    parser.add_argument('--no-check', action='store_true', help='跳过启动环境检查')
    parser.add_argument('--check-only', action='store_true', help='仅运行环境检查，不启动服务')
    parser.add_argument('--port', type=int, default=PORT, help=f'指定端口 (默认: {PORT})')
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
    server = http.server.HTTPServer(('0.0.0.0', port), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║   🎬 Video2Doc 工坊 v0.4.0               ║
║                                          ║
║   打开: http://localhost:{port}              ║
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
