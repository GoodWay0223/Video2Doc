"""Job management: models, state, thread-safe operations."""
import threading
import time
import uuid
from pathlib import Path
from enum import Enum

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

class JobType:
    DOWNLOAD = "download"
    TRANSCRIBE_ONLINE = "transcribe_online"
    TRANSCRIBE_LOCAL = "transcribe_local"

class Job:
    def __init__(self, job_id=None, url="", job_type=JobType.TRANSCRIBE_ONLINE,
                 mode="transcript", formats=None, domain=None):
        self.id = job_id or str(uuid.uuid4())[:8]
        self.url = url
        self.type = job_type
        self.mode = mode
        self.formats = formats or ["md"]
        self.domain = domain
        self.status = "queued"
        self.progress = 0
        self.title = ""
        self.duration = ""
        self.files = []
        self.error = None
        self.created_at = time.time()
        # Local transcription fields
        self.local_filename = ""
        self.local_filesize = 0
        # Download fields
        self.download_path = ""
        # Directory
        self.dir = OUTPUT_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "type": self.type,
            "mode": self.mode, "formats": self.formats, "domain": self.domain,
            "status": self.status, "progress": self.progress,
            "title": self.title, "duration": self.duration,
            "files": self.files, "error": self.error,
            "local_filename": self.local_filename,
            "local_filesize": self.local_filesize,
            "download_path": self.download_path,
            "created_at": self.created_at,
        }

# Thread-safe job storage
jobs = {}
jobs_lock = threading.Lock()

def add_job(job):
    with jobs_lock:
        jobs[job.id] = job

def get_job(job_id):
    with jobs_lock:
        return jobs.get(job_id)

def get_history(limit=20):
    with jobs_lock:
        sorted_ids = sorted(jobs.keys(), key=lambda jid: jobs[jid].created_at, reverse=True)
        return [jobs[jid].to_dict() for jid in sorted_ids[:limit]]
