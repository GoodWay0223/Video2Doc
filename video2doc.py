#!/usr/bin/env python3
"""Video2Doc command line — the same pipeline as the Web UI, without a browser.

Examples:
  python video2doc.py "https://www.bilibili.com/video/BV..."      # link → transcript
  python video2doc.py "复制打开抖音 https://v.douyin.com/xxx/"      # share text works too
  python video2doc.py meeting.m4a --format all --local-only       # local file, on-device ASR
  python video2doc.py --download "https://youtu.be/..."           # download the video only
  python video2doc.py --batch links.txt --format md,srt            # one link/file per line
  python video2doc.py "<讲座链接>" --illustrated --hotwords "京极彩,CEDEC"   # slides + matching text
"""
import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webui import __version__, pipeline  # noqa: E402
from webui.job_manager import OUTPUT_DIR, Job, JobType  # noqa: E402

FORMATS = {"md", "txt", "json", "srt", "all"}
ENGINES = ("auto", "doubao", "tele", "funasr", "whisper")
STATUS_LABELS = {
    "resolving": "解析链接", "downloading": "获取媒体", "extracting": "提取音频",
    "transcribing": "识别文字", "exporting": "生成文件",
}


def configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (LookupError, OSError):
                pass


def parse_formats(value):
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not formats or any(item not in FORMATS for item in formats):
        raise argparse.ArgumentTypeError(f"格式无效：{value}（可选 md,txt,json,srt,all）")
    return formats


def read_batch(path):
    lines = (line.strip() for line in Path(path).read_text(encoding="utf-8-sig").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def build_job(item, args):
    output_root = Path(args.output).expanduser().resolve() if args.output else OUTPUT_DIR
    job_id = uuid.uuid4().hex[:12]
    common = {
        "job_id": job_id, "job_dir": output_root / job_id, "formats": args.format,
        "engine": args.engine, "local_only": args.local_only,
        "allow_enrichment": not (args.no_enrich or args.local_only),
        "hotwords": pipeline.parse_hotwords(args.hotwords or ""),
        "illustrated": args.illustrated,
        "replacements": pipeline.parse_replacements(args.replace or []),
    }
    local = Path(item).expanduser()
    if local.is_file():
        if args.download:
            raise ValueError("--download 只适用于视频链接")
        job = Job(job_type=JobType.TRANSCRIBE_LOCAL, **common)
        job.local_filename = local.name
        job.local_filesize = local.stat().st_size
        return job, pipeline.run_local_pipeline, (str(local.resolve()),)
    if args.local_only:
        raise ValueError("--local-only 仅适用于本地文件；链接必须联网获取媒体")
    url = pipeline._extract_first_url(item)
    if args.download:
        return Job(url=url, job_type=JobType.DOWNLOAD, **common), pipeline.run_download_pipeline, ()
    return Job(url=url, job_type=JobType.TRANSCRIBE_ONLINE, **common), pipeline.run_transcribe_pipeline, ()


def log(message=""):
    # Progress goes to stderr so that `--json` keeps stdout machine-readable.
    print(message, file=sys.stderr, flush=True)


def run_one(item, args, index, total):
    log(f"\n[{index}/{total}] {item}")
    try:
        job, target, extra = build_job(item, args)
    except (ValueError, pipeline.PipelineError) as exc:
        log(f"  ❌ {exc}")
        return None
    worker = threading.Thread(target=target, args=(job, *extra), daemon=True)
    worker.start()
    last = None
    while worker.is_alive():
        if job.status != last and job.status in STATUS_LABELS:
            last = job.status
            log(f"  … {STATUS_LABELS[last]}")
        time.sleep(0.3)
    worker.join()
    job.finished_at = time.time()
    job.save()
    if job.status == "done":
        engine = pipeline.ENGINE_LABELS.get(job.engine_used, job.engine_used)
        log(f"  ✅ {job.title or '完成'}" + (f"（{engine}）" if engine else ""))
        if job.engine_note:
            log(f"     注：{job.engine_note}")
        for entry in job.files:
            log(f"     {job.dir / entry['file']}")
    else:
        log(f"  ❌ [{job.error_code or 'ERROR'}] {job.error or '失败'}")
    return job


def main(argv=None):
    configure_console_encoding()
    parser = argparse.ArgumentParser(
        prog="video2doc",
        description="把视频链接或本地音视频转为文稿（与 Web UI 共用同一套流程）。",
        epilog=__doc__.split("Examples:", 1)[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="*", help="视频链接、平台分享文本或本地音视频文件")
    parser.add_argument("--batch", help="批量文件：每行一个链接或本地文件路径（# 开头为注释）")
    parser.add_argument("--download", action="store_true", help="只下载视频，不转文稿")
    parser.add_argument("--format", type=parse_formats, default=["md"],
                        help="导出格式，逗号分隔：md,txt,json,srt 或 all（默认 md）")
    parser.add_argument("--engine", choices=ENGINES, default="auto", help="识别引擎（默认 auto）")
    parser.add_argument("--local-only", action="store_true",
                        help="隐私模式：仅本地文件，仅 FunASR/Whisper，禁止任何云端调用")
    parser.add_argument("--no-enrich", action="store_true", help="不调用云端 AI 摘要/要点/标签")
    parser.add_argument("--hotwords", help="热词：人名/术语，逗号分隔，提高识别准确率（豆包 / Whisper）")
    parser.add_argument("--replace", action="append", metavar="错词=>正确词",
                        help="识别后替换（可重复），例如 --replace \"金桔蚕=>京极彩\"")
    parser.add_argument("--illustrated", action="store_true",
                        help="生成图文稿：截取每张幻灯片/画面并配上对应原文（HTML + Markdown 图片包）")
    parser.add_argument("--output", help=f"输出根目录（默认 {OUTPUT_DIR}）")
    parser.add_argument("--json", action="store_true", help="结束时向 stdout 输出任务结果 JSON")
    parser.add_argument("--version", action="version", version=f"Video2Doc {__version__}")
    args = parser.parse_args(argv)

    items = list(args.inputs)
    if args.batch:
        items.extend(read_batch(args.batch))
    if not items:
        parser.error("请提供至少一个链接/文件，或使用 --batch")

    jobs = [run_one(item, args, index, len(items)) for index, item in enumerate(items, 1)]
    succeeded = sum(1 for job in jobs if job and job.status == "done")
    log(f"\n完成：✅ {succeeded}  ❌ {len(items) - succeeded}")
    if args.json:
        print(json.dumps([job.to_dict() if job else None for job in jobs], ensure_ascii=False, indent=2))
    return 0 if succeeded == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
