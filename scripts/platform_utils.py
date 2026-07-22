"""Small, dependency-free helpers shared by Windows and macOS entry points."""

import os
import shutil
import sys
from pathlib import Path


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
