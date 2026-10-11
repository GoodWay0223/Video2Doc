#!/usr/bin/env python3
"""Acquire platform media through the same routes used by the Web UI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webui import pipeline
from webui.job_manager import Job


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载 B站/抖音/YouTube/小红书媒体，并输出可机器读取的策略追踪"
    )
    parser.add_argument("source", help="视频 URL，或包含 URL 的平台分享文本")
    parser.add_argument("--output-dir", required=True, help="任务输出目录")
    parser.add_argument("--purpose", choices=("audio", "video"), default="audio")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    job = Job(url=args.source, job_dir=output_dir)

    try:
        if args.purpose == "audio":
            acquired = pipeline.acquire_transcription_audio(job)
            if acquired is None:
                raise pipeline.PipelineError(
                    "音频直取目前仅支持 B站和抖音。",
                    code="AUDIO_ROUTE_UNSUPPORTED",
                )
        else:
            acquired = pipeline.download_video(job)
            if acquired is None:
                raise pipeline.PipelineError(
                    job.error or "视频下载失败。",
                    code=job.error_code or "DOWNLOAD_FAILED",
                )
        payload = {
            "ok": True,
            "path": str(Path(acquired)),
            "strategy": job.download_strategy,
            "title": job.title,
            "duration": job.duration,
            "attempts": job.attempts,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except pipeline.PipelineError as exc:
        payload = {
            "ok": False,
            "error_code": exc.code,
            "error": str(exc),
            "attempts": job.attempts,
        }
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
