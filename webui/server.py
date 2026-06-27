"""HTTP Server: request handler and routing."""
import http.server
import json
import os
import threading
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import job_manager, pipeline, templates

OUTPUT_DIR = Path(__file__).parent.parent / "output"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path_str, filename=None):
        if not os.path.exists(path_str):
            self._send_json({"error": "文件不存在"}, 404); return
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Disposition', f'attachment; filename="{filename or os.path.basename(path_str)}"')
        self.send_header('Content-Length', str(os.path.getsize(path_str)))
        self.end_headers()
        with open(path_str, 'rb') as f:
            self.wfile.write(f.read())

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length)

    # ─── GET ────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Static HTML
        if path == '/' or path == '/index.html':
            html = templates.load_html().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        # Job status
        if path.startswith('/api/status/'):
            jid = path.split('/')[-1]
            job = job_manager.get_job(jid)
            if not job: self._send_json({"error":"任务未找到"},404); return
            self._send_json(job.to_dict())
            return

        # Job content (for result tabs)
        if path.startswith('/api/content/'):
            parts = path.split('/')
            if len(parts) >= 5:
                jid, ctype = parts[3], parts[4]
                content = templates.read_content(jid, ctype)
                if content: self._send_json({"content":content,"type":ctype})
                else: self._send_json({"error":"内容不存在"},404)
            else: self._send_json({"error":"Invalid path"},400)
            return

        # File download
        if path.startswith('/api/download/'):
            parts = path.split('/')
            if len(parts) >= 5:
                fp = str(OUTPUT_DIR / parts[3] / parts[4])
                self._send_file(fp, parts[4])
            else: self._send_json({"error":"无效路径"},400)
            return

        # History
        if path == '/api/history':
            self._send_json(job_manager.get_history())
            return

        self._send_json({"error":"未找到"}, 404)

    # ─── POST ───────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Online transcribe
        if path in ('/api/process', '/api/transcribe-online'):
            data = json.loads(self._read_body())
            url = data.get('url','').strip()
            if not url: self._send_json({"error":"未提供链接"},400); return

            job = job_manager.Job(url=url, job_type=job_manager.JobType.TRANSCRIBE_ONLINE,
                                  mode=data.get('mode','transcript'),
                                  formats=data.get('formats','md').split(','),
                                  domain=data.get('domain'))
            job_manager.add_job(job)
            threading.Thread(target=pipeline.run_transcribe_pipeline, args=(job,), daemon=True).start()
            self._send_json({"job_id":job.id,"status":"queued"})
            return

        # Download only
        if path == '/api/download-video':
            data = json.loads(self._read_body())
            url = data.get('url','').strip()
            if not url: self._send_json({"error":"未提供链接"},400); return

            job = job_manager.Job(url=url, job_type=job_manager.JobType.DOWNLOAD)
            job_manager.add_job(job)

            also_transcribe = data.get('transcribe', False)
            if also_transcribe:
                # When "also transcribe" is checked, run the full transcribe pipeline
                # (which includes download) instead of separate download + transcribe
                job.type = job_manager.JobType.TRANSCRIBE_ONLINE
                threading.Thread(target=pipeline.run_transcribe_pipeline, args=(job,), daemon=True).start()
            else:
                threading.Thread(target=pipeline.run_download_pipeline, args=(job,), daemon=True).start()
            self._send_json({"job_id":job.id,"status":"queued"})
            return

        # Local transcribe
        if path == '/api/transcribe-local':
            ctype = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in ctype:
                self._send_json({"error": "需要 multipart/form-data"}, 400); return

            # Parse multipart manually (cgi removed in Python 3.13)
            body = self._read_body()
            boundary = None
            for part in ctype.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part.split('=', 1)[1].strip('"')
            if not boundary:
                self._send_json({"error": "缺少 boundary"}, 400); return

            # Split by boundary
            b = boundary.encode()
            parts = body.split(b'--' + b)
            file_data = None
            filename = None
            formats_val = 'md'

            for part in parts:
                if b'\r\n\r\n' not in part and b'\n\n' not in part:
                    continue
                sep = b'\r\n\r\n' if b'\r\n\r\n' in part else b'\n\n'
                header_section, content = part.split(sep, 1)
                content = content.rstrip(b'\r\n--')  # Remove trailing boundary
                header_str = header_section.decode('utf-8', errors='ignore')

                # Extract filename
                fn_match = re.search(r'filename="([^"]+)"', header_str)
                if fn_match:
                    filename = fn_match.group(1)
                    file_data = content
                elif b'name="formats"' in header_section:
                    formats_val = content.decode('utf-8', errors='ignore').strip()

            if not file_data or not filename:
                self._send_json({"error": "未收到文件"}, 400); return

            if len(file_data) > 200 * 1024 * 1024:
                self._send_json({"error": "文件超过 200MB 限制"}, 413); return

            job = job_manager.Job(job_type=job_manager.JobType.TRANSCRIBE_LOCAL,
                                  formats=formats_val.split(','))
            job.local_filename = filename
            job.local_filesize = len(file_data)
            job_manager.add_job(job)

            # Save uploaded file
            raw_dir = job.dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            file_path = raw_dir / filename
            file_path.write_bytes(file_data)

            threading.Thread(target=pipeline.run_local_pipeline, args=(job, str(file_path)), daemon=True).start()
            self._send_json({"job_id":job.id,"status":"queued"})
            return

        self._send_json({"error":"未找到"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
