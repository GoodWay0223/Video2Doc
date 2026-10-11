"""Job management: models, persistence, bounded background execution."""
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
JOB_FILE_NAME = "job.json"
FINISHED_STATUSES = {"done", "error"}


def _max_workers():
    try:
        return max(1, min(8, int(os.environ.get("VIDEO2DOC_MAX_JOBS", "2"))))
    except ValueError:
        return 2


class JobType:
    DOWNLOAD = "download"
    TRANSCRIBE_ONLINE = "transcribe_online"
    TRANSCRIBE_LOCAL = "transcribe_local"

class Job:
    def __init__(self, job_id=None, url="", job_type=JobType.TRANSCRIBE_ONLINE,
                 mode="transcript", formats=None, domain=None, engine="auto",
                 local_only=False, allow_enrichment=True, job_dir=None):
        self.id = job_id or uuid.uuid4().hex[:12]
        self.url = url
        self.type = job_type
        self.mode = mode
        self.formats = formats or ["md"]
        self.domain = domain
        self.engine = engine or "auto"  # auto|doubao|tele|funasr|whisper
        self.local_only = bool(local_only)
        self.allow_enrichment = bool(allow_enrichment)
        self.engine_used = ""            # 实际成功的引擎
        self.engine_note = ""            # 引擎切换提示（如"已自动切换到 tele"）
        self.status = "queued"
        self.progress = 0
        self.title = ""
        self.duration = ""
        self.files = []
        self.error = None
        self.error_code = ""
        self.download_strategy = ""
        self.attempts = []
        self.created_at = time.time()
        self.finished_at = None
        # Local transcription fields
        self.local_filename = ""
        self.local_filesize = 0
        # Download fields
        self.download_path = ""
        # Directory
        self.dir = Path(job_dir) if job_dir is not None else OUTPUT_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "type": self.type,
            "mode": self.mode, "formats": self.formats, "domain": self.domain,
            "engine": self.engine, "local_only": self.local_only,
            "allow_enrichment": self.allow_enrichment,
            "engine_used": self.engine_used, "engine_note": self.engine_note,
            "status": self.status, "progress": self.progress,
            "title": self.title, "duration": self.duration,
            "files": self.files, "error": self.error,
            "error_code": self.error_code,
            "download_strategy": self.download_strategy,
            "attempts": self.attempts,
            "local_filename": self.local_filename,
            "local_filesize": self.local_filesize,
            "download_path": self.download_path,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def save(self):
        """Atomically persist the public job state next to its results."""
        try:
            payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
            target = self.dir / JOB_FILE_NAME
            partial = target.with_name(target.name + ".part")
            partial.write_text(payload, encoding="utf-8", newline="\n")
            partial.replace(target)
        except (OSError, TypeError, ValueError):
            pass

    @classmethod
    def from_file(cls, path):
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("id") != path.parent.name:
            raise ValueError("job.json does not match its directory")
        job = cls(job_id=data["id"], job_dir=path.parent)
        for key, value in data.items():
            if key != "id" and hasattr(job, key):
                setattr(job, key, value)
        return job


# Thread-safe job storage
jobs = {}
jobs_lock = threading.Lock()

def add_job(job):
    with jobs_lock:
        jobs[job.id] = job
    if hasattr(job, "save"):
        job.save()

def get_job(job_id):
    with jobs_lock:
        return jobs.get(job_id)

def get_history(limit=20):
    with jobs_lock:
        sorted_ids = sorted(jobs.keys(), key=lambda jid: jobs[jid].created_at, reverse=True)
        return [jobs[jid].to_dict() for jid in sorted_ids[:limit]]


def load_history(output_dir=None):
    """Restore finished jobs from output/*/job.json after a restart.

    Jobs that were still running when the process stopped cannot resume, so
    they are marked as interrupted instead of polling forever.
    """
    root = Path(output_dir or OUTPUT_DIR)
    restored = 0
    for path in root.glob(f"*/{JOB_FILE_NAME}"):
        try:
            job = Job.from_file(path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if job.status not in FINISHED_STATUSES:
            job.status = "error"
            job.error = "服务重启，任务已中断；请重新提交。"
            job.error_code = "INTERRUPTED"
            job.save()
        with jobs_lock:
            jobs.setdefault(job.id, job)
        restored += 1
    return restored


# Bounded background execution: long downloads and local ASR models must not
# run unbounded in parallel. Daemon workers keep Ctrl+C responsive.
_queue = queue.Queue()
_workers = []
_workers_lock = threading.Lock()


def _run(job, target, args):
    try:
        target(job, *args)
    except Exception as exc:  # Pipelines classify their own errors; this is a last resort.
        job.status = "error"
        job.error = str(exc)[:600] or "未知错误"
        job.error_code = job.error_code or "UNEXPECTED_ERROR"
    finally:
        if job.status not in FINISHED_STATUSES:
            job.status = "error"
            job.error = job.error or "任务意外结束"
        job.finished_at = time.time()
        job.save()


def _worker():
    while True:
        job, target, args = _queue.get()
        try:
            _run(job, target, args)
        finally:
            _queue.task_done()


def submit(job, target, *args):
    """Queue a pipeline function; at most VIDEO2DOC_MAX_JOBS run concurrently."""
    with _workers_lock:
        while len(_workers) < _max_workers():
            worker = threading.Thread(target=_worker, name=f"video2doc-job-{len(_workers)}",
                                      daemon=True)
            worker.start()
            _workers.append(worker)
    _queue.put((job, target, args))
