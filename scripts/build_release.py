#!/usr/bin/env python3
"""Build a safe, reproducible Video2Doc source release archive.

The resulting ZIP uses POSIX member paths and preserves executable bits for
shell scripts, so the same archive can be extracted on Windows and macOS.
Runtime output, caches, repository metadata, local configuration, credentials,
and media files are deliberately excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


PRODUCT_NAME = "Video2Doc"
DEFAULT_OUTPUT_DIRECTORY = "dist"
MANIFEST_NAME = "RELEASE-MANIFEST.json"
ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".github",
    ".idea",
    ".mypy_cache",
    ".nox",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "audio",
    "build",
    "dist",
    "images",
    "node_modules",
    "output",
    "raw",
    "tests",
    "venv",
    "verify",
}
EXCLUDED_FILE_NAMES = {
    ".coverage",
    ".DS_Store",
    ".env",
    "cookies.txt",
    "desktop.ini",
    "playwright_state.json",
    "Thumbs.db",
}
EXCLUDED_SUFFIXES = {
    ".coverage",
    ".key",
    ".log",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".wav",
    ".webm",
    ".zip",
}
TEMPORARY_DIRECTORY_PATTERNS = (
    re.compile(r"^pipeline-test-[0-9a-f]+$"),
    re.compile(r"^release-test-[0-9a-f]+$"),
)
VERSION_PATTERN = re.compile(
    r"^v?(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?"
    r"(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?)$"
)
CHANGELOG_VERSION_PATTERN = re.compile(r"^## \[v(?P<version>[^\]]+)\]", re.MULTILINE)

# These patterns are intentionally high-confidence. Placeholder values used by
# documentation (for example ``sk-xxxxx`` or ``your-key``) do not match.
SECRET_PATTERNS = (
    (
        "private key block",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "SiliconFlow-style API key",
        re.compile(rb"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
)
CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    rb"(?im)^[ \t]*(?:DOUBAO_API_KEY|SILICONFLOW_API_KEY|XHS_COOKIE)"
    rb"[ \t]*[:=][ \t]*(?P<value>[^\r\n#]*)$"
)


class ReleaseError(RuntimeError):
    """Raised when a release cannot be built safely."""


@dataclass(frozen=True)
class ReleaseFile:
    source: Path
    relative_path: PurePosixPath
    content: bytes
    sha256: str


@dataclass(frozen=True)
class ReleaseResult:
    archive: Path
    checksum_file: Path
    checksum: str
    version: str
    file_count: int


def normalize_version(value: str) -> str:
    """Return a validated semantic version without a leading ``v``."""
    match = VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise ReleaseError(
            "版本号必须类似 0.6.0、v0.6.0 或 0.6.0-rc.1，不能包含路径字符"
        )
    return match.group("version")


def version_from_changelog(source_root: Path) -> str:
    """Read the newest released version, deliberately skipping Unreleased."""
    changelog = source_root / "CHANGELOG.md"
    if not changelog.is_file():
        raise ReleaseError("找不到 CHANGELOG.md；请通过 --version 显式指定版本")
    match = CHANGELOG_VERSION_PATTERN.search(changelog.read_text(encoding="utf-8"))
    if not match:
        raise ReleaseError("CHANGELOG.md 中没有找到形如 ## [v0.6.0] 的正式版本")
    return normalize_version(match.group("version"))


def _is_excluded_directory(name: str) -> bool:
    if name in EXCLUDED_DIRECTORY_NAMES:
        return True
    return any(pattern.fullmatch(name) for pattern in TEMPORARY_DIRECTORY_PATTERNS)


def _is_excluded_file(relative_path: Path) -> bool:
    name = relative_path.name
    lower_name = name.lower()
    if name in EXCLUDED_FILE_NAMES:
        return True
    if lower_name.startswith(".env.") and lower_name != ".env.example":
        return True
    if lower_name.endswith(tuple(EXCLUDED_SUFFIXES)):
        return True
    return False


def _assert_no_secret(relative_path: PurePosixPath, content: bytes) -> None:
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(content):
            raise ReleaseError(
                f"检测到疑似{label}，已中止打包：{relative_path.as_posix()}"
            )
    for match in CREDENTIAL_ASSIGNMENT_PATTERN.finditer(content):
        value = match.group("value").strip(b" \t'\"")
        lower_value = value.lower()
        placeholder = (
            lower_value in {b"", b"your-key", b"replace-me"}
            or re.fullmatch(rb"sk-x+", lower_value) is not None
        )
        if len(value) >= 12 and not placeholder:
            raise ReleaseError(
                "检测到疑似configured API credential，已中止打包："
                f"{relative_path.as_posix()}"
            )


def _normalize_text_endings(relative_path: PurePosixPath, content: bytes) -> bytes:
    """Give launch scripts the line endings required by their target OS."""
    if relative_path.suffix not in {".cmd", ".command", ".sh"}:
        return content
    lf_content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if relative_path.suffix == ".cmd":
        return lf_content.replace(b"\n", b"\r\n")
    return lf_content


def assert_clean_worktree(source_root: Path, output_directory: Path) -> None:
    """Reject release builds from a dirty Git checkout.

    A previous archive in the selected output directory is ignored because it
    is itself generated release output. All other staged, modified, and
    untracked files block a formal build.
    """
    git_marker = source_root / ".git"
    if not git_marker.exists():
        return
    try:
        completed = subprocess.run(
            [
                "git", "-C", str(source_root), "status", "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError(f"无法验证 Git 工作树是否干净：{exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "git status 执行失败"
        raise ReleaseError(f"无法验证 Git 工作树是否干净：{detail}")

    ignored_prefix = None
    try:
        ignored_prefix = output_directory.resolve().relative_to(source_root).as_posix()
    except ValueError:
        pass

    changes = []
    for line in completed.stdout.splitlines():
        changed_path = line[3:] if len(line) > 3 else line
        if " -> " in changed_path:
            changed_path = changed_path.rsplit(" -> ", 1)[-1]
        if ignored_prefix and (
            changed_path == ignored_prefix
            or changed_path.startswith(ignored_prefix.rstrip("/") + "/")
        ):
            continue
        changes.append(line)
    if changes:
        preview = "; ".join(changes[:8])
        if len(changes) > 8:
            preview += f"；另有 {len(changes) - 8} 项"
        raise ReleaseError(
            "正式发布要求干净的 Git 工作树。请先提交变更，"
            f"或仅在草稿/测试场景使用 --allow-dirty。当前变更：{preview}"
        )


def collect_release_files(source_root: Path) -> list[ReleaseFile]:
    """Collect safe regular files below *source_root* in stable order."""
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ReleaseError(f"源码目录不存在：{source_root}")

    collected: list[ReleaseFile] = []
    for current, directories, filenames in os.walk(source_root, topdown=True):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories if not _is_excluded_directory(name)
        )
        for filename in sorted(filenames):
            source = current_path / filename
            relative = source.relative_to(source_root)
            if _is_excluded_file(relative):
                continue
            if source.is_symlink():
                raise ReleaseError(f"发布包不接受符号链接：{relative.as_posix()}")
            if not source.is_file():
                continue
            posix_relative = PurePosixPath(*relative.parts)
            if posix_relative.is_absolute() or ".." in posix_relative.parts:
                raise ReleaseError(f"不安全的发布路径：{posix_relative.as_posix()}")
            content = _normalize_text_endings(posix_relative, source.read_bytes())
            _assert_no_secret(posix_relative, content)
            collected.append(
                ReleaseFile(
                    source=source,
                    relative_path=posix_relative,
                    content=content,
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )

    if not collected:
        raise ReleaseError("没有找到可打包文件")
    required = {
        "README.md",
        "CHANGELOG.md",
        "requirements.txt",
        "start-video2doc.cmd",
        "start-video2doc.command",
        "webui.py",
    }
    present = {item.relative_path.as_posix() for item in collected}
    missing = sorted(required - present)
    if missing:
        raise ReleaseError("发布包缺少必要文件：" + ", ".join(missing))
    return collected


def _zip_info(member_name: str, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(member_name, date_time=ZIP_TIMESTAMP)
    info.create_system = 3  # Unix attributes are understood by macOS unzip.
    mode = 0o755 if executable else 0o644
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _manifest_bytes(version: str, archive_root: str,
                    files: Sequence[ReleaseFile]) -> bytes:
    manifest = {
        "format_version": 1,
        "product": PRODUCT_NAME,
        "version": version,
        "archive_root": archive_root,
        "files": [
            {
                "path": item.relative_path.as_posix(),
                "size": len(item.content),
                "sha256": item.sha256,
            }
            for item in files
        ],
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def build_release(source_root: Path, output_directory: Path,
                  version: str, *, allow_dirty: bool = False) -> ReleaseResult:
    """Build one versioned ZIP and matching ``.sha256`` sidecar."""
    source_root = source_root.resolve()
    output_directory = output_directory.resolve()
    normalized_version = normalize_version(version)
    archive_root = f"{PRODUCT_NAME}-v{normalized_version}"
    archive = output_directory / f"{archive_root}.zip"
    checksum_file = archive.with_suffix(archive.suffix + ".sha256")
    temporary_archive = archive.with_suffix(archive.suffix + ".tmp")

    if not allow_dirty:
        assert_clean_worktree(source_root, output_directory)
    files = collect_release_files(source_root)
    output_directory.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            temporary_archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as bundle:
            for item in files:
                member = f"{archive_root}/{item.relative_path.as_posix()}"
                executable = item.relative_path.suffix in {".command", ".sh"}
                bundle.writestr(_zip_info(member, executable), item.content)
            manifest_member = f"{archive_root}/{MANIFEST_NAME}"
            bundle.writestr(
                _zip_info(manifest_member),
                _manifest_bytes(normalized_version, archive_root, files),
            )
            bundle.comment = (
                f"{PRODUCT_NAME} v{normalized_version} cross-platform source release"
            ).encode("ascii")
        temporary_archive.replace(archive)
    except BaseException:
        temporary_archive.unlink(missing_ok=True)
        raise

    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="ascii", newline="\n")
    return ReleaseResult(
        archive=archive,
        checksum_file=checksum_file,
        checksum=checksum,
        version=normalized_version,
        file_count=len(files),
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="构建不含凭据、缓存和运行产物的 Video2Doc 跨平台 ZIP 发布包"
    )
    parser.add_argument(
        "--version",
        help="发布版本（如 0.6.0）；默认读取 CHANGELOG.md 最新正式版本",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"输出目录（默认：项目根目录/{DEFAULT_OUTPUT_DIRECTORY}）",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="允许从脏工作树构建草稿包（正式 GitHub Release 不应使用）",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    source_root = (args.source_root or Path(__file__).resolve().parents[1]).resolve()
    output_directory = args.output_dir or source_root / DEFAULT_OUTPUT_DIRECTORY
    try:
        version = normalize_version(args.version) if args.version else version_from_changelog(source_root)
        result = build_release(
            source_root, output_directory, version, allow_dirty=args.allow_dirty
        )
    except (OSError, ReleaseError, zipfile.BadZipFile) as exc:
        print(f"发布包构建失败：{exc}", file=sys.stderr)
        return 1

    print(f"发布包：{result.archive}")
    print(f"校验文件：{result.checksum_file}")
    print(f"SHA-256：{result.checksum}")
    print(f"已收录源码文件：{result.file_count} 个（另含 {MANIFEST_NAME}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
