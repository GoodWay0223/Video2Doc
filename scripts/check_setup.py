#!/usr/bin/env python3
"""
Video2Doc Environment Checker (Cross-Platform)
Checks all required dependencies for both Mac and Windows.
Can be called directly or imported by webui.py on startup.
"""
import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .platform_utils import find_executable, load_user_config
except ImportError:  # Direct execution: python scripts/check_setup.py
    from platform_utils import find_executable, load_user_config

MIN_PYTHON = (3, 10)
REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / 'requirements.txt'
PYPI_YTDLP_URL = 'https://pypi.org/pypi/yt-dlp/json'
VERSION_PROBE_TIMEOUT = 5
UPDATE_CHECK_TIMEOUT = 4

def find_bin(name):
    """Find an executable, checking PATH and common locations."""
    return find_executable([name])


def module_available(name):
    """Check an optional Python dependency without importing heavy modules."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _read_ytdlp_minimum(path=REQUIREMENTS_PATH):
    """Read the local yt-dlp lower bound without importing packaging tools."""
    try:
        content = Path(path).read_text(encoding='utf-8')
    except OSError:
        return None
    match = re.search(
        r'^\s*yt-dlp(?:\[[^\]\r\n]+\])?\s*>=\s*([0-9]+(?:\.[0-9]+){1,3})',
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1) if match else None


def _numeric_version(value):
    """Extract a comparable numeric release tuple from tool version output."""
    if not value:
        return None
    match = re.search(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)', str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split('.'))


def _version_at_least(installed, minimum):
    installed_parts = _numeric_version(installed)
    minimum_parts = _numeric_version(minimum)
    if installed_parts is None or minimum_parts is None:
        return None
    width = max(len(installed_parts), len(minimum_parts))
    return (installed_parts + (0,) * (width - len(installed_parts))
            >= minimum_parts + (0,) * (width - len(minimum_parts)))


def _probe_tool_version(executable, tool_name):
    """Execute one local version command with no shell and a short timeout."""
    args_by_tool = {
        'ffmpeg': ['-version'],
        'ffprobe': ['-version'],
        'curl': ['--version'],
        'yt-dlp': ['--version'],
        'deno': ['--version'],
        'node': ['--version'],
        'bun': ['--version'],
        'qjs': ['--help'],
    }
    args = args_by_tool.get(tool_name, ['--version'])
    try:
        completed = subprocess.run(
            [executable] + args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=VERSION_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = '\n'.join(part for part in (completed.stdout, completed.stderr) if part)
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), '')
    patterns = {
        'ffmpeg': r'^ffmpeg version\s+([^\s]+)',
        'ffprobe': r'^ffprobe version\s+([^\s]+)',
        'curl': r'^curl\s+([^\s]+)',
        'yt-dlp': r'([0-9]+(?:\.[0-9]+){2,3}(?:[^\s]*)?)',
        'deno': r'^deno\s+([^\s]+)',
        'node': r'^v?([^\s]+)',
        'bun': r'^v?([^\s]+)',
        'qjs': r'^QuickJS version\s+([^\s]+)',
    }
    match = re.search(patterns.get(tool_name, r'([^\s]+)'), first_line, re.IGNORECASE)
    return match.group(1) if match else None


def _tool_result(executable, tool_name):
    if not executable:
        return {
            'ok': False, 'installed': False, 'msg': '未安装',
            'version': None, 'path': None,
        }
    version = _probe_tool_version(executable, tool_name)
    if version:
        return {
            'ok': True,
            'installed': True,
            'msg': f'{version} ({executable})',
            'version': version,
            'path': str(executable),
        }
    return {
        'ok': False,
        'installed': True,
        'msg': f'已找到但无法读取版本 ({executable})',
        'version': None,
        'path': str(executable),
    }


def _quote_command(value):
    value = str(value)
    if os.name == 'nt':
        return '"' + value.replace('"', '""') + '"'
    return shlex.quote(value)


def _uv_tool_installed(package_name):
    candidates = []
    configured = os.environ.get('UV_TOOL_DIR')
    if configured:
        candidates.append(Path(configured).expanduser() / package_name)
    app_data = os.environ.get('APPDATA')
    if app_data:
        candidates.append(Path(app_data) / 'uv' / 'tools' / package_name)
    xdg_data = os.environ.get('XDG_DATA_HOME')
    if xdg_data:
        candidates.append(Path(xdg_data) / 'uv' / 'tools' / package_name)
    candidates.append(Path.home() / '.local' / 'share' / 'uv' / 'tools' / package_name)
    return any(candidate.is_dir() for candidate in candidates)


def _ytdlp_upgrade_command(executable, minimum_version):
    requirement = f'yt-dlp>={minimum_version}' if minimum_version else 'yt-dlp'
    uv = find_bin('uv')
    if executable and uv and _uv_tool_installed('yt-dlp'):
        return f'{_quote_command(uv)} tool upgrade yt-dlp'
    if executable and module_available('yt_dlp'):
        return (f'{_quote_command(sys.executable)} -m pip install --upgrade '
                f'{_quote_command(requirement)}')
    if executable:
        return f'{_quote_command(executable)} -U'
    if uv:
        return f'{_quote_command(uv)} tool install {_quote_command(requirement)}'
    return (f'{_quote_command(sys.executable)} -m pip install --upgrade '
            f'{_quote_command(requirement)}')


def _fetch_latest_ytdlp_version():
    """Query public PyPI metadata only; never read or attach credentials."""
    request = urllib.request.Request(
        PYPI_YTDLP_URL,
        headers={'Accept': 'application/json', 'User-Agent': 'Video2Doc-update-check/0.6'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=UPDATE_CHECK_TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8'))
        version = payload.get('info', {}).get('version')
        if not isinstance(version, str) or _numeric_version(version) is None:
            raise ValueError('invalid PyPI version response')
        return version, None
    except (OSError, ValueError, TypeError, json.JSONDecodeError,
            urllib.error.URLError) as exc:
        # Do not surface URLs, proxy details, request headers, or local credentials.
        return None, f'更新检查失败（{type(exc).__name__}）'


def _load_config():
    return load_user_config()


def _get_siliconflow_key(config):
    """Read only explicit Video2Doc configuration, never unrelated memory files."""
    key = os.environ.get('SILICONFLOW_API_KEY', '')
    if key:
        return key
    key = config.get('siliconflow_api_key', '')
    if key:
        return key
    return ''


def _get_doubao_key(config):
    return (os.environ.get('DOUBAO_API_KEY', '')
            or config.get('doubao_api_key', ''))


def _playwright_browser_installed():
    """Detect the Chromium bundle used by Python Playwright."""
    candidates = []
    configured = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if configured and configured != '0':
        candidates.append(Path(configured).expanduser())
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    if local_app_data:
        candidates.append(Path(local_app_data) / 'ms-playwright')
    candidates.extend([
        Path.home() / 'Library' / 'Caches' / 'ms-playwright',
        Path.home() / '.cache' / 'ms-playwright',
    ])
    spec = importlib.util.find_spec('playwright') if module_available('playwright') else None
    if configured == '0' and spec and spec.origin:
        candidates.append(Path(spec.origin).parent / 'driver' / 'package' / '.local-browsers')
    return any(p.is_dir() and any(p.glob('chromium*')) for p in candidates)

def check_all(check_updates=False):
    """Run local checks; network access occurs only when check_updates is true."""
    python_ok = sys.version_info[:2] >= MIN_PYTHON
    python_version = (f'{sys.version_info.major}.{sys.version_info.minor}.'
                      f'{sys.version_info.micro}')
    results = {
        'python': {
            'ok': python_ok,
            'msg': (f'Python {python_version}'
                    + ('' if python_ok else ' (需要 3.10+)')),
            'version': python_version,
            'path': sys.executable,
        },
        'ffmpeg': {'ok': False, 'msg': ''},
        'ffprobe': {'ok': False, 'msg': ''},
        'curl': {'ok': False, 'msg': ''},
        'yt_dlp': {'ok': False, 'msg': ''},
        'javascript_runtime': {'ok': False, 'msg': ''},
        'playwright': {'ok': False, 'msg': ''},
        'doubao': {'ok': False, 'msg': ''},
        'siliconflow': {'ok': False, 'msg': ''},
        'funasr': {'ok': False, 'msg': ''},
        'whisper': {'ok': False, 'msg': ''},
        'transcription': {'ok': False, 'msg': ''},
        'api_key': {'ok': False, 'msg': ''},
        'os': {'ok': True, 'msg': 'Windows' if os.name == 'nt' else 'macOS' if sys.platform == 'darwin' else 'Linux'},
        'warnings': [],
    }

    # Local executable versions. A path alone is insufficient: a broken binary
    # should not be advertised as ready.
    ffmpeg = find_bin('ffmpeg')
    results['ffmpeg'] = _tool_result(ffmpeg, 'ffmpeg')
    if not ffmpeg:
        results['ffmpeg']['msg'] = '未安装 (brew install ffmpeg / winget install ffmpeg)'
    elif not results['ffmpeg']['ok']:
        results['warnings'].append('ffmpeg 已找到，但版本命令执行失败')

    ffprobe = find_bin('ffprobe')
    results['ffprobe'] = _tool_result(ffprobe, 'ffprobe')
    if not ffprobe:
        results['ffprobe']['msg'] = '随 ffmpeg 安装'
    elif not results['ffprobe']['ok']:
        results['warnings'].append('ffprobe 已找到，但版本命令执行失败')

    curl = find_bin('curl')
    results['curl'] = _tool_result(curl, 'curl')
    if not curl:
        results['curl']['msg'] = '未安装'
    elif not results['curl']['ok']:
        results['warnings'].append('curl 已找到，但版本命令执行失败')

    # yt-dlp readiness is evaluated offline against requirements.txt.
    minimum_ytdlp = _read_ytdlp_minimum()
    yt = find_bin('yt-dlp')
    yt_result = _tool_result(yt, 'yt-dlp')
    installed_ytdlp = yt_result.get('version')
    meets_minimum = _version_at_least(installed_ytdlp, minimum_ytdlp)
    yt_result.update({
        'installed': bool(yt),
        'minimum_version': minimum_ytdlp,
        'meets_minimum': meets_minimum,
        'version_status': 'unknown',
        'upgrade_command': _ytdlp_upgrade_command(yt, minimum_ytdlp),
        'latest_version': None,
        'update_available': None,
        'update_check_error': None,
    })
    if yt:
        if installed_ytdlp is None:
            yt_result['ok'] = False
            yt_result['version_status'] = 'unknown'
            results['warnings'].append('yt-dlp 已找到，但无法读取本地版本')
        elif minimum_ytdlp is None:
            yt_result['ok'] = False
            yt_result['version_status'] = 'unknown'
            results['warnings'].append('requirements.txt 未声明 yt-dlp 最低版本')
        elif meets_minimum is False:
            yt_result['ok'] = False
            yt_result['version_status'] = 'update_required'
            yt_result['msg'] = (f'{installed_ytdlp}，低于要求 {minimum_ytdlp} '
                                f'({yt})')
            results['warnings'].append(
                f'yt-dlp {installed_ytdlp} 低于最低要求 {minimum_ytdlp}')
        else:
            yt_result['version_status'] = 'meets_minimum'
    else:
        yt_result['ok'] = False
        yt_result['version_status'] = 'not_installed'
        yt_result['msg'] = '未安装 (pip install yt-dlp)'
        results['warnings'].append('yt-dlp 未安装，非抖音平台的视频下载将不可用')
    if check_updates:
        latest_version, update_error = _fetch_latest_ytdlp_version()
        yt_result['latest_version'] = latest_version
        yt_result['update_check_error'] = update_error
        if latest_version and installed_ytdlp:
            installed_parts = _numeric_version(installed_ytdlp)
            latest_parts = _numeric_version(latest_version)
            if installed_parts is not None and latest_parts is not None:
                width = max(len(installed_parts), len(latest_parts))
                installed_parts += (0,) * (width - len(installed_parts))
                latest_parts += (0,) * (width - len(latest_parts))
                if installed_parts < latest_parts:
                    yt_result['update_available'] = True
                    yt_result['version_status'] = 'update_available'
                elif installed_parts == latest_parts:
                    yt_result['update_available'] = False
                    yt_result['version_status'] = 'up_to_date'
                else:
                    yt_result['update_available'] = False
                    yt_result['version_status'] = 'newer_than_latest'
        if update_error:
            results['warnings'].append(update_error)
    results['yt_dlp'] = yt_result

    # Modern YouTube extraction may require yt-dlp-ejs plus a JS runtime.
    for runtime_name in ('deno', 'node', 'bun', 'qjs'):
        runtime_path = find_bin(runtime_name)
        if not runtime_path:
            continue
        runtime_result = _tool_result(runtime_path, runtime_name)
        runtime_result['name'] = runtime_name
        results['javascript_runtime'] = runtime_result
        if runtime_result['ok']:
            break
    if not results['javascript_runtime']['ok']:
        if results['javascript_runtime'].get('installed'):
            runtime_name = results['javascript_runtime'].get('name') or 'JavaScript runtime'
            results['javascript_runtime']['msg'] = f'已找到 {runtime_name}，但无法读取版本'
            results['warnings'].append(
                'JavaScript runtime 已找到但不可执行；YouTube 部分格式或签名解析可能不可用')
        else:
            results['javascript_runtime'].update({
                'msg': '未检测到 Deno / Node / Bun / QuickJS',
                'version': None,
                'path': None,
                'name': None,
                'installed': False,
            })
            results['warnings'].append(
                '未检测到 JavaScript runtime；YouTube 部分格式或签名解析可能不可用')

    # Python Playwright is what pipeline.py imports; npx/playwright-cli is not enough.
    playwright_package = module_available('playwright')
    playwright_browser = _playwright_browser_installed() if playwright_package else False
    if playwright_package and playwright_browser:
        results['playwright'] = {'ok': True, 'msg': 'Python 包 + Chromium 已安装'}
    elif playwright_package:
        results['playwright'] = {'ok': False, 'msg': 'Python 包已安装，但 Chromium 未安装'}
        results['warnings'].append('Playwright Chromium 未安装，抖音浏览器兜底不可用')
    else:
        results['playwright'] = {'ok': False, 'msg': '未安装 Python playwright 包'}
        results['warnings'].append('Python Playwright 未安装，抖音浏览器兜底不可用')

    # Transcription engines. Keys are detected locally but never validated over network.
    config = _load_config()
    siliconflow_key = _get_siliconflow_key(config)
    doubao_key = _get_doubao_key(config)
    if doubao_key:
        results['doubao'] = {'ok': True, 'msg': 'API Key 已配置（未联网验证）'}
    else:
        results['doubao'] = {'ok': False, 'msg': '未配置 DOUBAO_API_KEY'}

    if siliconflow_key and results['curl']['ok']:
        results['siliconflow'] = {'ok': True, 'msg': 'API Key + curl 已就绪（未联网验证）'}
    elif siliconflow_key:
        results['siliconflow'] = {'ok': False, 'msg': 'API Key 已配置，但 curl 缺失'}
    else:
        results['siliconflow'] = {'ok': False, 'msg': '未配置 SILICONFLOW_API_KEY'}
    # Keep the historical field for callers that inspect check_all() directly.
    results['api_key'] = {
        'ok': bool(siliconflow_key),
        'msg': ('已配置（未联网验证）' if siliconflow_key
                else '未配置 SILICONFLOW_API_KEY'),
    }

    funasr_package = module_available('funasr')
    torch_package = module_available('torch')
    if funasr_package and torch_package:
        results['funasr'] = {'ok': True, 'msg': 'funasr + torch 已安装（模型可能需首次下载）'}
    elif funasr_package:
        results['funasr'] = {'ok': False, 'msg': 'funasr 已安装，但 torch 缺失'}
    else:
        results['funasr'] = {'ok': False, 'msg': '未安装 funasr'}

    whisper_package = module_available('whisper')
    if whisper_package and results['ffmpeg']['ok']:
        results['whisper'] = {'ok': True, 'msg': 'openai-whisper + ffmpeg 已就绪（模型可能需首次下载）'}
    elif whisper_package:
        results['whisper'] = {'ok': False, 'msg': 'openai-whisper 已安装，但 ffmpeg 缺失'}
    else:
        results['whisper'] = {'ok': False, 'msg': '未安装 openai-whisper'}

    ready_engines = [name for name in ('doubao', 'siliconflow', 'funasr', 'whisper')
                     if results[name]['ok']]
    results['transcription'] = {
        'ok': bool(ready_engines),
        'msg': ('可用引擎: ' + ', '.join(ready_engines)
                if ready_engines else '无可用转录引擎'),
    }
    if not ready_engines:
        results['warnings'].append(
            '没有可用转录引擎：配置任一云端 Key，或安装 FunASR/Whisper')

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

    tool_checks = [
        ('ffmpeg', 'FFmpeg (音频处理)'),
        ('ffprobe', 'ffprobe (格式探测)'),
        ('curl', 'curl (API 请求)'),
        ('yt_dlp', 'yt-dlp (视频下载)'),
        ('javascript_runtime', 'JavaScript runtime (YouTube 增强)'),
        ('playwright', 'Python Playwright (抖音兜底)'),
    ]
    for key, label in tool_checks:
        r = results[key]
        icon = icons['ok'] if r['ok'] else icons['warn']
        print(f"  {icon} {label}: {r['msg']}")

    yt_result = results['yt_dlp']
    if yt_result.get('latest_version'):
        update_note = ('（有更新）' if yt_result.get('update_available')
                       else '（已是最新或更高版本）')
        print(f"     PyPI 最新稳定版: {yt_result['latest_version']} {update_note}")
    if not yt_result['ok'] or yt_result.get('update_available'):
        print(f"     安全升级命令: {yt_result['upgrade_command']}")

    print()
    print("  转录引擎（至少一个可用）：")
    engine_checks = [
        ('doubao', '豆包云端'),
        ('siliconflow', 'SiliconFlow 云端'),
        ('funasr', 'FunASR 本地'),
        ('whisper', 'Whisper 本地'),
    ]
    for key, label in engine_checks:
        r = results[key]
        icon = icons['ok'] if r['ok'] else icons['warn']
        print(f"  {icon} {label}: {r['msg']}")
    transcription = results['transcription']
    print(f"  {icons['ok'] if transcription['ok'] else icons['error']} "
          f"转录能力: {transcription['msg']}")

    if results['warnings']:
        print()
        for w in results['warnings']:
            print(f"  ⚠️  {w}")

    blockers = []
    if not results['python']['ok']:
        blockers.append('Python 3.10+')
    if not results['ffmpeg']['ok']:
        blockers.append('ffmpeg')
    if not results['ffprobe']['ok']:
        blockers.append('ffprobe')
    if not results['curl']['ok']:
        blockers.append('curl')
    if not results['yt_dlp']['ok']:
        minimum = results['yt_dlp'].get('minimum_version')
        blockers.append(f"yt-dlp>={minimum}" if minimum else 'yt-dlp')
    if not results['transcription']['ok']:
        blockers.append('至少一个转录引擎')
    all_ok = not blockers

    print()
    if all_ok:
        print("  ✅ 基础处理能力与至少一个转录引擎已就绪。")
    else:
        print(f"  ❌ 核心阻塞项: {', '.join(blockers)}")

    print()
    return all_ok

def main(argv=None):
    parser = argparse.ArgumentParser(description='Video2Doc 环境与组件版本检查')
    parser.add_argument(
        '--check-updates',
        action='store_true',
        help='联网查询 PyPI 上 yt-dlp 最新稳定版（默认完全离线）',
    )
    args = parser.parse_args(argv)
    results = check_all(check_updates=args.check_updates)
    ok = print_report(results)

    if not ok:
        print("  修复建议：")
        if not results['ffmpeg']['ok']:
            print("    安装 ffmpeg（Windows: winget install ffmpeg；Mac: brew install ffmpeg）")
        if not results['transcription']['ok']:
            print("    配置 DOUBAO_API_KEY / SILICONFLOW_API_KEY，")
            print("    或安装本地引擎：pip install funasr torch / openai-whisper")
        print()

    # Return exit code for scripting
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
