"""Small, dependency-free helpers shared by Windows and macOS entry points."""

import json
import os
import shutil
import sys
from pathlib import Path


def user_config_path():
    return Path.home() / ".video2doc" / "config.json"


def load_user_config():
    """Read ~/.video2doc/config.json as UTF-8 (with/without BOM) or legacy GB18030.

    This is the single source of truth for every entry point (Web UI, CLI,
    self-check) so that a key visible to one component is visible to all.
    """
    try:
        raw = user_config_path().read_bytes()
    except (OSError, RuntimeError):
        return {}
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            payload = json.loads(raw.decode(encoding))
            return payload if isinstance(payload, dict) else {}
        except (UnicodeError, json.JSONDecodeError):
            continue
    return {}


def _write_private_json(path, payload):
    """Atomically write JSON readable only by the current user where supported."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
    try:
        os.chmod(partial, 0o600)
    except OSError:
        pass
    partial.replace(path)


def save_user_config(updates):
    """Merge updates into config.json; None or "" removes a key. Unknown keys are kept."""
    config = load_user_config()
    for key, value in updates.items():
        if value is None or value == "":
            config.pop(key, None)
        else:
            config[key] = value
    _write_private_json(user_config_path(), config)
    return config


def state_path():
    return Path.home() / ".video2doc" / "state.json"


def load_state():
    try:
        payload = json.loads(state_path().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, RuntimeError, ValueError):
        return {}


def save_state(updates):
    state = load_state()
    state.update(updates)
    try:
        _write_private_json(state_path(), state)
    except OSError:
        pass
    return state


def candidate_bin_dirs(*, os_name=None, platform_name=None, environ=None,
                       home=None, python_executable=None):
    """Return common executable directories that may be absent from app PATH."""
    os_name = os.name if os_name is None else os_name
    platform_name = sys.platform if platform_name is None else platform_name
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    python_executable = sys.executable if python_executable is None else python_executable
    python_dir = Path(python_executable).resolve().parent
    dirs = [
        python_dir,
        python_dir / "Scripts",
        home / ".local" / "bin",
    ]

    if os_name == "nt":
        local_app_data = environ.get("LOCALAPPDATA")
        program_data = environ.get("PROGRAMDATA")
        chocolatey = environ.get("ChocolateyInstall")
        if local_app_data:
            dirs.append(Path(local_app_data) / "Microsoft" / "WinGet" / "Links")
        dirs.append(home / "scoop" / "shims")
        if chocolatey:
            dirs.append(Path(chocolatey) / "bin")
        elif program_data:
            dirs.append(Path(program_data) / "chocolatey" / "bin")
    elif platform_name == "darwin":
        # Finder-launched apps often do not inherit the interactive shell PATH.
        dirs.extend([
            Path("/opt/homebrew/bin"),       # Apple Silicon Homebrew
            Path("/usr/local/bin"),          # Intel Homebrew
            Path("/opt/local/bin"),          # MacPorts
        ])

    managed = home / ".workbuddy" / "binaries"
    dirs.extend([
        managed / "ffmpeg",
        managed / "python" / "envs" / "default" / "bin",
        managed / "python" / "envs" / "default" / "Scripts",
    ])

    # Keep order stable while avoiding redundant filesystem checks.
    unique = []
    seen = set()
    for directory in dirs:
        key = os.path.normcase(os.path.abspath(os.fspath(directory)))
        if key not in seen:
            seen.add(key)
            unique.append(directory)
    return unique


def _variants(name):
    variants = [name]
    if os.name == "nt" and not name.lower().endswith((".exe", ".com", ".cmd", ".bat")):
        variants.extend([name + ".exe", name + ".com"])
    return variants


def _launchable(path):
    return path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))


def find_executable(names):
    """Resolve the first launchable executable from names or explicit paths."""
    for raw_name in names:
        name = os.fspath(raw_name)
        expanded = os.path.expandvars(os.path.expanduser(name))
        has_directory = Path(expanded).parent != Path(".")

        if has_directory:
            for variant in _variants(expanded):
                candidate = Path(variant)
                if _launchable(candidate):
                    return str(candidate)
            continue

        for variant in _variants(expanded):
            resolved = shutil.which(variant)
            if resolved:
                return resolved

        for directory in candidate_bin_dirs():
            for variant in _variants(expanded):
                candidate = directory / variant
                if _launchable(candidate):
                    return str(candidate)
    return None
