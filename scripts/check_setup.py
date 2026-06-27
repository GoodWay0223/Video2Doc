#!/usr/bin/env python3
"""
Video2Doc Environment Checker (Cross-Platform)
Checks all required dependencies for both Mac and Windows.
Can be called directly or imported by webui.py on startup.
"""
import os, sys, shutil, json, re
from pathlib import Path

def find_bin(name):
    """Find an executable, checking PATH and common locations."""
    # Direct PATH check
    if shutil.which(name):
        return name
    # Windows .exe variant
    if os.name == 'nt' and shutil.which(name + '.exe'):
        return name + '.exe'
    # WorkBuddy managed paths
    managed = Path.home() / '.workbuddy' / 'binaries'
    ffmpeg_dir = managed / 'ffmpeg'
    py_dir = managed / 'python' / 'envs' / 'default'
    candidates = [
        ffmpeg_dir / name,
        ffmpeg_dir / (name + '.exe'),
        py_dir / 'bin' / name,
        py_dir / 'bin' / (name + '.exe'),
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return str(c)
    return None

def check_all():
    """Run all checks and return results dict."""
    results = {
        'python': {'ok': True, 'msg': f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'},
        'ffmpeg': {'ok': False, 'msg': ''},
        'ffprobe': {'ok': False, 'msg': ''},
        'curl': {'ok': False, 'msg': ''},
        'yt_dlp': {'ok': False, 'msg': ''},
        'api_key': {'ok': False, 'msg': ''},
        'os': {'ok': True, 'msg': 'Windows' if os.name == 'nt' else 'macOS' if sys.platform == 'darwin' else 'Linux'},
        'warnings': [],
    }

    # FFmpeg
    ffmpeg = find_bin('ffmpeg')
    if ffmpeg:
        results['ffmpeg'] = {'ok': True, 'msg': ffmpeg}
    else:
        results['ffmpeg'] = {'ok': False, 'msg': '未安装 (brew install ffmpeg / winget install ffmpeg)'}

    ffprobe = find_bin('ffprobe')
    if ffprobe:
        results['ffprobe'] = {'ok': True, 'msg': ffprobe}
    else:
        results['ffprobe'] = {'ok': False, 'msg': '随 ffmpeg 安装'}

    # curl
    curl = find_bin('curl')
    if curl:
        results['curl'] = {'ok': True, 'msg': curl}
    else:
        results['curl'] = {'ok': False, 'msg': '未安装'}

    # yt-dlp
    yt = find_bin('yt-dlp')
    if yt:
        results['yt_dlp'] = {'ok': True, 'msg': yt}
    else:
        results['yt_dlp'] = {'ok': False, 'msg': '未安装 (pip install yt-dlp)'}
        results['warnings'].append('yt-dlp 未安装，非抖音平台的视频下载将不可用')

    # Optional: playwright / npx
    npx = shutil.which('npx')
    pw = shutil.which('playwright-cli')
    if npx or pw:
        results['playwright'] = {'ok': True, 'msg': 'npx 可用 (抖音下载)'}
    else:
        results['playwright'] = {'ok': False, 'msg': '未安装 (抖音下载需要 npx @playwright/cli)'}
        results['warnings'].append('npx 未安装，抖音平台下载不可用')

    # API Key (same logic as pipeline.py)
    key = os.environ.get('SILICONFLOW_API_KEY', '')
    if not key:
        cfg = Path.home() / '.video2doc' / 'config.json'
        if cfg.exists():
            try:
                d = json.loads(cfg.read_text())
                key = d.get('siliconflow_api_key', '')
            except: pass
    if not key:
        wb = Path.home() / '.workbuddy' / 'MEMORY.md'
        if wb.exists():
            m = re.search(r'SILICONFLOW_API_KEY:\s*(sk-[a-zA-Z0-9]+)', wb.read_text())
            if m: key = m.group(1)

    if key:
        results['api_key'] = {'ok': True, 'msg': key[:10] + '...' + key[-5:]}
    else:
        results['api_key'] = {'ok': False, 'msg': '未配置 — 设置 SILICONFLOW_API_KEY 环境变量'}
        results['warnings'].append('API Key 未配置，转录功能不可用')

    return results

def print_report(results):
    """Print a formatted report to console."""
    icons = {'ok': '✅', 'error': '❌', 'warn': '⚠️'}
    print("""
╔══════════════════════════════════════════╗
║   Video2Doc — 环境检查                   ║
╚══════════════════════════════════════════╝
    """)
    print(f"  系统: {results['os']['msg']}")
    print(f"  Python: {results['python']['msg']}")
    print()

    checks = [
        ('ffmpeg', 'FFmpeg (音频处理)'),
        ('ffprobe', 'ffprobe (格式探测)'),
        ('curl', 'curl (API 请求)'),
        ('yt_dlp', 'yt-dlp (视频下载)'),
        ('api_key', 'API Key (A转写)'),
    ]
    if 'playwright' in results:
        checks.append(('playwright', 'Playwright (抖音下载)'))

    all_ok = True
    for key, label in checks:
        r = results[key]
        icon = icons['ok'] if r['ok'] else '⚠️' if key == 'playwright' else icons['error']
        if not r['ok'] and key != 'playwright':
            all_ok = False
        print(f"  {icon} {label}: {r['msg']}")

    if results['warnings']:
        print()
        for w in results['warnings']:
            print(f"  ⚠️  {w}")

    print()
    if all_ok:
        print("  ✅ 所有核心依赖就绪，可以正常使用。")
    else:
        missing = sum(1 for k, _ in checks if not results[k].get('ok') and k != 'playwright')
        print(f"  ❌ {missing} 个核心依赖缺失，请安装后再运行。")

    print()
    return all_ok

def main():
    results = check_all()
    ok = print_report(results)

    if not ok:
        print("  安装指南：")
        print("    Mac:   brew install ffmpeg curl")
        print("           pip install yt-dlp")
        print("    Windows: winget install ffmpeg")
        print("           pip install yt-dlp")
        print()
        print("  API Key 注册：https://cloud.siliconflow.cn/i/pWcvZzOr")
        print()

    # Return exit code for scripting
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
