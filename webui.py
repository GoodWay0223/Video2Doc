#!/usr/bin/env python3
"""
Video2Doc Web UI — Local Visual Frontend
Run: python3 webui.py
Open: http://localhost:8765

A single-file web application with embedded backend API.
No external dependencies beyond Python stdlib.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from io import BytesIO

# ─── Configuration ─────────────────────────────────────
PORT = 8765
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── Platform Utils ─────────────────────────────────────
IS_WINDOWS = os.name == 'nt'

def find_executable(names):
    """Find the first available executable, Windows-aware"""
    import shutil as _shutil
    for name in names:
        # Try direct command
        if _shutil.which(name):
            return name
        # Try with .exe suffix (Windows)
        if IS_WINDOWS:
            exe_name = name + '.exe'
            if _shutil.which(exe_name):
                return exe_name
            # Check common install paths on Windows
            for base in [os.environ.get('LOCALAPPDATA', ''), os.environ.get('PROGRAMFILES', ''), 'C:\\']:
                candidate = Path(base) / exe_name
                if candidate.exists():
                    return str(candidate)
    return None

# ─── Job Manager ───────────────────────────────────────
jobs = {}
jobs_lock = threading.Lock()

class Job:
    def __init__(self, job_id, url, mode="transcript", formats="md", domain=None):
        self.id = job_id
        self.url = url
        self.mode = mode
        self.formats = formats.split(",") if isinstance(formats, str) else formats
        self.domain = domain
        self.status = "queued"  # queued → downloading → extracting → transcribing → correcting → done
        self.stage = 0
        self.progress = 0
        self.title = ""
        self.duration = ""
        self.files = []
        self.error = None
        self.created_at = time.time()
        self.dir = OUTPUT_DIR / job_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "mode": self.mode,
            "formats": self.formats,
            "domain": self.domain,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "title": self.title,
            "duration": self.duration,
            "files": self.files,
            "error": self.error,
            "created_at": self.created_at,
        }

def resolve_short_link(url):
    """Resolve douyin short links to full URLs"""
    try:
        result = subprocess.run(
            ["curl", "-sI", "-o", "/dev/null", "-w", "%{url_effective}", "-L", url],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or url
    except:
        return url

def process_job(job):
    """Run the full pipeline in a background thread"""
    try:
        # Stage 1: Resolve URL
        job.status = "resolving"
        job.progress = 10
        full_url = resolve_short_link(job.url)
        job.url = full_url

        # Extract video ID
        match = re.search(r'video/(\d+)', full_url)
        video_id = match.group(1) if match else job.id[:8]

        # Stage 2: Download
        job.status = "downloading"
        job.progress = 20

        is_douyin = "douyin.com" in full_url
        if is_douyin:
            # For demo/standalone: check if we have Playwright available
            video_file = download_douyin(job)
        else:
            video_file = download_generic(job, full_url)

        if not video_file:
            job.status = "error"
            job.error = "下载失败 — cookies 可能已过期或平台暂不支持。"
            return

        # Stage 3: Extract Audio
        job.status = "extracting"
        job.progress = 40
        audio_file = job.dir / "raw" / "audio.mp3"
        audio_file.parent.mkdir(exist_ok=True)
        if not extract_audio(video_file, audio_file):
            job.status = "error"
            job.error = "音频提取失败，请检查 ffmpeg 是否已安装。"
            return

        # Stage 4: Transcribe
        job.status = "transcribing"
        job.progress = 60
        transcript = transcribe(audio_file, job)
        if not transcript:
            job.status = "error"
            job.error = "Transcription failed — check API key configuration."
            return

        # Save transcript
        tele_json = job.dir / "raw" / "tele_result.json"
        tele_json.parent.mkdir(parents=True, exist_ok=True)
        tele_json.write_text(json.dumps(transcript, ensure_ascii=False, indent=2))

        # Extract title from transcription
        job.title = transcript.get("text", "")[:80] + "..." if len(transcript.get("text", "")) > 80 else transcript.get("text", "")
        segments = transcript.get("segments", [])
        if segments:
            total = segments[-1].get("end", 0)
            m, s = divmod(int(total), 60)
            job.duration = f"{m:02d}:{s:02d}"

        # Stage 5: Apply corrections + Export
        job.status = "exporting"
        job.progress = 85

        exported = export_formats(job, tele_json)
        job.files = exported

        job.status = "done"
        job.progress = 100

    except Exception as e:
        job.status = "error"
        job.error = str(e)

def download_douyin(job):
    """Download douyin video via Playwright (if available) or provide manual path"""
    # For standalone CLI usage, download needs Playwright
    # We take a pragmatic approach: check if a pre-downloaded file exists
    video_candidates = [
        job.dir / "raw" / "video.mp4",
        job.dir / "raw" / "video.webm",
    ]
    for candidate in video_candidates:
        if candidate.exists():
            return str(candidate)

    # Try Playwright CLI if available
    try:
        playwright_check = subprocess.run(
            ["npx", "@playwright/cli@latest", "--version"],
            capture_output=True, text=True, timeout=15
        )
        if playwright_check.returncode != 0:
            job.error = "Playwright not available. For Douyin, provide cookies.txt and video file manually to raw/video.mp4"
            return None
    except:
        job.error = "Playwright not available."
        return None

    job.error = "Automatic douyin download requires cookies and Playwright. Place video at raw/video.mp4"
    return None

def download_generic(job, url):
    """Download via yt-dlp (Windows-compatible)"""
    yt_dlp_candidates = ["yt-dlp", "yt-dlp.exe",
                         str(Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "bin" / "yt-dlp"),
                         str(Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "Scripts" / "yt-dlp.exe")]
    yt_dlp = find_executable(yt_dlp_candidates)
    if not yt_dlp:
        job.error = "未找到 yt-dlp。请执行: pip install yt-dlp"
        return None

    output = str(job.dir / "raw" / "video.%(ext)s")
    try:
        subprocess.run([yt_dlp, "-o", output, url],
                      cwd=str(job.dir), timeout=300, capture_output=True)
    except:
        pass

    for ext in ["mp4", "webm", "mkv", "flv"]:
        candidate = job.dir / "raw" / f"video.{ext}"
        if candidate.exists():
            return str(candidate)
    return None

def extract_audio(video_file, output_file):
    """Extract audio as MP3 (Windows-compatible)"""
    ffmpeg_candidates = ["ffmpeg", "ffmpeg.exe",
                         str(Path.home() / ".workbuddy" / "binaries" / "ffmpeg" / "ffmpeg"),
                         str(Path.home() / ".workbuddy" / "binaries" / "ffmpeg" / "ffmpeg.exe")]
    ffmpeg = find_executable(ffmpeg_candidates)
    if not ffmpeg:
        return False
    try:
        subprocess.run([ffmpeg, "-i", str(video_file), "-vn", "-acodec", "libmp3lame",
                       "-q:a", "2", "-y", str(output_file)],
                      capture_output=True, timeout=120)
        return output_file.exists()
    except:
        return False

def transcribe(audio_file, job):
    """Transcribe via TeleSpeechASR (Windows-compatible)"""
    api_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        config_path = Path.home() / ".video2doc" / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                api_key = config.get("siliconflow_api_key", "")
            except:
                pass
    if not api_key:
        wb_path = Path.home() / ".workbuddy" / "MEMORY.md"
        if wb_path.exists():
            content = wb_path.read_text()
            match = re.search(r'SILICONFLOW_API_KEY:\s*(sk-[a-zA-Z0-9]+)', content)
            if match:
                api_key = match.group(1)

    if not api_key:
        job.error = "未找到 API Key。请设置 SILICONFLOW_API_KEY 环境变量，或配置 ~/.video2doc/config.json"
        return None

    curl_cmd = find_executable(["curl", "curl.exe"]) or "curl"

    try:
        result = subprocess.run(
            [curl_cmd, "-s", "--max-time", "120", "--retry", "3", "--retry-delay", "2",
             "https://api.siliconflow.cn/v1/audio/transcriptions",
             "-H", f"Authorization: Bearer {api_key}",
             "-F", f"file=@{audio_file}",
             "-F", "model=TeleAI/TeleSpeechASR",
             "-F", "response_format=verbose_json"],
            capture_output=True, text=True, timeout=130
        )
        return json.loads(result.stdout)
    except Exception as e:
        job.error = f"Transcription API error: {e}"
        return None

def export_formats(job, transcript):
    """Export to selected formats"""
    exported = []
    segments = transcript.get("segments", [])
    full_text = transcript.get("text", "")

    if "md" in job.formats or "all" in job.formats:
        path = job.dir / "transcript.md"
        path.write_text(full_text, encoding="utf-8")
        exported.append({"name": "Markdown", "file": "transcript.md", "size": path.stat().st_size})

    if "txt" in job.formats or "all" in job.formats:
        path = job.dir / "transcript.txt"
        path.write_text(full_text, encoding="utf-8")
        exported.append({"name": "Plain Text", "file": "transcript.txt", "size": path.stat().st_size})

    if "json" in job.formats or "all" in job.formats:
        path = job.dir / "transcript.json"
        data = {"segments": segments, "total_segments": len(segments)}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        exported.append({"name": "JSON", "file": "transcript.json", "size": path.stat().st_size})

    if "srt" in job.formats or "all" in job.formats:
        path = job.dir / "transcript.srt"
        srt_content = to_srt(segments)
        path.write_text(srt_content, encoding="utf-8")
        exported.append({"name": "SRT Subtitles", "file": "transcript.srt", "size": path.stat().st_size})

    return exported

def to_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_time(seg.get("start", 0))
        end = _fmt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if text:
            lines.extend([str(i), f"{start} --> {end}", text, ""])
    return "\n".join(lines)

def _fmt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

# ─── HTTP Server ────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video2Doc — 视频转录工坊</title>
<style>
  :root {
    --bg: #0F0F11;
    --surface: #1A1A1E;
    --panel: #242429;
    --border: #2E2E36;
    --text: #E4E4E7;
    --muted: #71717A;
    --accent: #2563EB;
    --accent-glow: rgba(37,99,235,0.15);
    --green: #22C55E;
    --amber: #F59E0B;
    --red: #EF4444;
    --radius: 10px;
    --font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-mono: 'SF Mono', 'JetBrains Mono', 'Fira Code', monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font-ui); background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
  
  /* Sidebar */
  aside { width: 260px; background: var(--surface); border-right: 1px solid var(--border); padding: 24px 20px; display: flex; flex-direction: column; gap: 28px; flex-shrink: 0; }
  aside .logo { display: flex; align-items: center; gap: 10px; }
  aside .logo .icon { width: 32px; height: 32px; background: var(--accent); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 16px; }
  aside .logo .title { font-size: 16px; font-weight: 700; letter-spacing: -0.3px; }
  aside .logo .ver { font-size: 11px; color: var(--muted); margin-left: auto; }
  
  aside .pipeline { display: flex; flex-direction: column; gap: 2px; }
  aside .pipeline .label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 8px; }
  aside .pipeline .step { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 6px; font-size: 13px; color: var(--muted); transition: all 0.2s; }
  aside .pipeline .step.active { background: var(--accent-glow); color: var(--accent); }
  aside .pipeline .step.done { color: var(--green); }
  aside .pipeline .step.error { color: var(--red); }
  aside .pipeline .step .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--border); flex-shrink: 0; }
  aside .pipeline .step.active .dot { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  aside .pipeline .step.done .dot { background: var(--green); }
  aside .pipeline .step.error .dot { background: var(--red); }
  
  aside .history h3 { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 10px; }
  aside .history .item { padding: 6px 8px; border-radius: 6px; font-size: 12px; color: var(--muted); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: all 0.15s; }
  aside .history .item:hover { background: var(--panel); color: var(--text); }
  
  /* Main */
  main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; gap: 32px; }
  main .container { width: 100%; max-width: 620px; }
  
  /* Header */
  .hero { text-align: center; margin-bottom: 8px; }
  .hero h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 6px; }
  .hero p { color: var(--muted); font-size: 14px; }
  
  /* Input */
  .input-group { display: flex; gap: 8px; }
  .input-group input { flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; font-size: 15px; color: var(--text); font-family: var(--font-mono); outline: none; transition: border-color 0.2s; }
  .input-group input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
  .input-group input::placeholder { color: var(--muted); }
  
  .btn { padding: 12px 24px; border: none; border-radius: var(--radius); font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; font-family: var(--font-ui); }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { filter: brightness(1.1); }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-secondary { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
  .btn-secondary:hover { border-color: var(--accent); }
  .btn-sm { padding: 6px 14px; font-size: 12px; border-radius: 6px; }
  
  /* Settings */
  .settings { display: flex; gap: 12px; flex-wrap: wrap; }
  .settings select { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 13px; color: var(--text); outline: none; cursor: pointer; font-family: var(--font-ui); }
  .settings select:focus { border-color: var(--accent); }
  
  /* Progress */
  .progress-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; display: none; }
  .progress-panel.visible { display: block; }
  .progress-bar-outer { height: 4px; background: var(--border); border-radius: 2px; margin: 12px 0; overflow: hidden; }
  .progress-bar-inner { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.5s ease; width: 0%; }
  .progress-info { display: flex; justify-content: space-between; font-size: 13px; }
  .progress-info .status { color: var(--accent); display: flex; align-items: center; gap: 6px; }
  .progress-info .pct { color: var(--muted); font-family: var(--font-mono); }
  .spinner { width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }
  
  /* Results */
  .results { display: none; }
  .results.visible { display: block; }
  .results .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
  .results .card h3 { font-size: 14px; margin-bottom: 12px; }
  .results .files { display: flex; gap: 8px; flex-wrap: wrap; }
  .results .files a { text-decoration: none; }
  .file-chip { display: flex; align-items: center; gap: 6px; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 8px 14px; font-size: 13px; color: var(--text); transition: all 0.15s; cursor: pointer; }
  .file-chip:hover { border-color: var(--accent); background: var(--accent-glow); }
  .file-chip .ext { font-size: 10px; color: var(--accent); font-weight: 700; text-transform: uppercase; }
  .file-chip .size { font-size: 11px; color: var(--muted); font-family: var(--font-mono); }
  
  /* Error */
  .error-msg { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); border-radius: var(--radius); padding: 14px 18px; color: var(--red); font-size: 13px; display: none; }
  .error-msg.visible { display: block; }
  
  /* Batch */
  .batch-toggle { text-align: center; }
  .batch-toggle button { background: none; border: none; color: var(--muted); font-size: 12px; cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: all 0.15s; font-family: var(--font-ui); }
  .batch-toggle button:hover { color: var(--text); background: var(--panel); }
  .batch-area { display: none; }
  .batch-area.visible { display: block; }
  .batch-area textarea { width: 100%; height: 120px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; font-size: 13px; color: var(--text); font-family: var(--font-mono); resize: vertical; outline: none; }
  .batch-area textarea:focus { border-color: var(--accent); }
  .batch-area .hint { font-size: 11px; color: var(--muted); margin-top: 6px; }
  
  /* Responsive */
  @media (max-width: 720px) {
    body { flex-direction: column; }
    aside { width: 100%; flex-direction: row; padding: 12px 16px; gap: 16px; overflow-x: auto; border-right: none; border-bottom: 1px solid var(--border); }
    aside .pipeline, aside .history { display: none; }
    main { padding: 24px 16px; }
    .settings { flex-direction: column; }
  }
</style>
</head>
<body>

<aside>
  <div class="logo">
    <div class="icon">🎬</div>
    <span class="title">Video2Doc</span>
    <span class="ver">v0.3</span>
  </div>
  <div class="pipeline" id="pipeline">
    <div class="label">处理流水线</div>
    <div class="step" data-stage="resolving"><span class="dot"></span> 解析链接</div>
    <div class="step" data-stage="downloading"><span class="dot"></span> 下载视频</div>
    <div class="step" data-stage="extracting"><span class="dot"></span> 提取音频</div>
    <div class="step" data-stage="transcribing"><span class="dot"></span> 语音转录</div>
    <div class="step" data-stage="exporting"><span class="dot"></span> 导出文件</div>
  </div>
  <div class="history" id="sidebar-history">
    <h3>历史记录</h3>
  </div>
</aside>

<main>
  <div class="container">
    <div class="hero">
      <h1>视频 → 文档</h1>
      <p>粘贴抖音/B站/YouTube 链接，自动转录为结构化文稿。</p>
    </div>

    <!-- Input -->
    <div class="input-group" style="margin-bottom:12px">
      <input type="text" id="url-input" placeholder="https://v.douyin.com/xxxx 或 https://youtube.com/watch?v=xxxx"
             autocomplete="off" autofocus>
      <button class="btn btn-primary" id="btn-process" onclick="startProcess()">开始转录</button>
    </div>

    <!-- Settings -->
    <div class="settings">
      <select id="mode-select">
        <option value="transcript">📝 纯文稿 (MD)</option>
        <option value="deep">🎨 深度分析 (HTML)</option>
      </select>
      <select id="format-select">
        <option value="md">格式：MD</option>
        <option value="srt">格式：SRT 字幕</option>
        <option value="txt">格式：TXT</option>
        <option value="json">格式：JSON</option>
        <option value="all">格式：全部</option>
      </select>
      <select id="domain-select">
        <option value="">领域：自动检测</option>
        <option value="auto">领域：汽车 🚗</option>
        <option value="tech">领域：科技 💻</option>
      </select>
    </div>

    <!-- Batch toggle -->
    <div class="batch-toggle" style="margin-top:8px">
      <button onclick="toggleBatch()">+ 批量模式</button>
    </div>
    <div class="batch-area" id="batch-area">
      <textarea id="batch-input" placeholder="粘贴多个链接，一行一个：
https://v.douyin.com/xxxx
https://www.youtube.com/watch?v=xxxx
# 以 # 开头的行为注释，自动跳过"></textarea>
      <div class="hint">一行一个链接，# 开头的行为注释会被跳过</div>
    </div>

    <!-- Progress -->
    <div class="progress-panel" id="progress-panel">
      <div class="progress-info">
        <span class="status"><span class="spinner" id="spinner"></span> <span id="status-text">Processing...</span></span>
        <span class="pct" id="pct-text">0%</span>
      </div>
      <div class="progress-bar-outer"><div class="progress-bar-inner" id="progress-bar"></div></div>
    </div>

    <!-- Error -->
    <div class="error-msg" id="error-msg"></div>

    <!-- Results -->
    <div class="results" id="results">
      <div class="card">
        <h3 id="result-title">输出文件</h3>
        <div class="files" id="result-files"></div>
      </div>
    </div>
  </div>
</main>

<script>
let currentJobId = null;
let pollTimer = null;

async function startProcess() {
  const url = document.getElementById('url-input').value.trim();
  const batchInput = document.getElementById('batch-input').value.trim();
  const batchArea = document.getElementById('batch-area');

  let links = [];
  if (batchArea.classList.contains('visible') && batchInput) {
    links = batchInput.split('\\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  } else if (url) {
    links = [url];
  }

  if (links.length === 0) {
    alert('请输入视频链接。');
    return;
  }

  const mode = document.getElementById('mode-select').value;
  const formats = document.getElementById('format-select').value;
  const domain = document.getElementById('domain-select').value;

  document.getElementById('btn-process').disabled = true;
  document.getElementById('error-msg').classList.remove('visible');
  document.getElementById('results').classList.remove('visible');
  document.getElementById('progress-panel').classList.add('visible');
  document.getElementById('status-text').textContent = '正在启动...';
  document.getElementById('pct-text').textContent = '0%';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('spinner').style.display = 'inline-block';

  resetPipeline();

  try {
    const response = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: links[0], mode, formats, domain, batch: links.length > 1 ? links : null })
    });
    const data = await response.json();

    if (data.error) {
      showError(data.error);
      return;
    }

    currentJobId = data.job_id;
    pollStatus();
  } catch (e) {
    showError('连接失败，是否已启动 webui.py？');
  }
}

async function pollStatus() {
  if (!currentJobId) return;

  try {
    const response = await fetch('/api/status/' + currentJobId);
    const job = await response.json();

    updatePipeline(job.status);
    const statusMap = {'resolving':'解析链接中','downloading':'下载视频中','extracting':'提取音频中','transcribing':'语音转录中','exporting':'导出文件中','done':'处理完成','error':'处理失败','queued':'排队中'};
    document.getElementById('status-text').textContent = statusMap[job.status] || job.status;
    document.getElementById('pct-text').textContent = job.progress + '%';
    document.getElementById('progress-bar').style.width = job.progress + '%';

    if (job.status === 'done') {
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('btn-process').disabled = false;
      showResults(job);
      loadHistory();
      return;
    }

    if (job.status === 'error') {
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('btn-process').disabled = false;
      showError(job.error || 'Unknown error');
      return;
    }

    pollTimer = setTimeout(pollStatus, 1000);
  } catch (e) {
    pollTimer = setTimeout(pollStatus, 2000);
  }
}

function showError(msg) {
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  el.classList.add('visible');
  document.getElementById('progress-panel').classList.remove('visible');
  document.getElementById('btn-process').disabled = false;
}

function showResults(job) {
  document.getElementById('results').classList.add('visible');
  document.getElementById('progress-panel').classList.remove('visible');
  const title = job.title || job.url;
  document.getElementById('result-title').textContent = title;
  const container = document.getElementById('result-files');
  container.innerHTML = job.files.map(f => `
    <a href="/api/download/${job.id}/${f.file}" download>
      <div class="file-chip">
        <span class="ext">${f.file.split('.').pop()}</span>
        <span>${f.name}</span>
        <span class="size">${formatSize(f.size)}</span>
      </div>
    </a>
  `).join('');
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function resetPipeline() {
  document.querySelectorAll('#pipeline .step').forEach(s => {
    s.classList.remove('active', 'done', 'error');
  });
}

function updatePipeline(status) {
  const stages = ['resolving', 'downloading', 'extracting', 'transcribing', 'exporting'];
  let foundCurrent = false;
  stages.forEach(stage => {
    const el = document.querySelector(`#pipeline .step[data-stage="${stage}"]`);
    if (!el) return;
    el.classList.remove('active', 'done', 'error');
    if (stage === status || (status === 'done' && !foundCurrent)) {
      el.classList.add(status === 'done' ? 'done' : status === 'error' ? 'error' : 'active');
      foundCurrent = true;
    } else if (!foundCurrent) {
      el.classList.add('done');
    }
  });
  if (status === 'done') {
    document.querySelectorAll('#pipeline .step').forEach(s => s.classList.add('done'));
  }
}

function toggleBatch() {
  const area = document.getElementById('batch-area');
  area.classList.toggle('visible');
  document.getElementById('url-input').style.display = area.classList.contains('visible') ? 'none' : '';
}

async function loadHistory() {
  try {
    const resp = await fetch('/api/history');
    const data = await resp.json();
    const container = document.getElementById('sidebar-history');
    container.innerHTML = '<h3>History</h3>' + data.map(j => {
      const title = (j.title || j.url || '').substring(0, 30);
      const st = j.status === 'done' ? '✅' : j.status === 'error' ? '❌' : '⏳';
      return `<div class="item" onclick="loadJob('${j.id}')">${st} ${title}</div>`;
    }).join('');
  } catch(e) {}
}

async function loadJob(id) {
  try {
    const resp = await fetch('/api/status/' + id);
    const job = await resp.json();
    if (job.status === 'done') {
      showResults(job);
    }
  } catch(e) {}
}

// Load history on page load
loadHistory();

// Enter key to submit
document.getElementById('url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') startProcess();
});
</script>
</body>
</html>"""

class APIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Quiet

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, filename):
        if not os.path.exists(path):
            self._send_json({"error": "File not found"}, 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(os.path.getsize(path)))
        self.end_headers()
        with open(path, 'rb') as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed = urlparse(self.path)

        # Static HTML
        if parsed.path == '/' or parsed.path == '/index.html':
            body = HTML_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # API: status
        if parsed.path.startswith('/api/status/'):
            job_id = parsed.path.split('/')[-1]
            job = jobs.get(job_id)
            if not job:
                self._send_json({"error": "Job not found"}, 404)
                return
            self._send_json(job.to_dict())
            return

        # API: download
        if parsed.path.startswith('/api/download/'):
            parts = parsed.path.split('/')
            if len(parts) >= 5:
                job_id = parts[3]
                filename = parts[4]
                path = OUTPUT_DIR / job_id / filename
                self._send_file(str(path), filename)
                return
            self._send_json({"error": "Invalid path"}, 400)
            return

        # API: history
        if parsed.path == '/api/history':
            history = []
            for jid in sorted(jobs.keys(), reverse=True)[:20]:
                job = jobs[jid]
                history.append(job.to_dict())
            self._send_json(history)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)

        # API: process
        if parsed.path == '/api/process':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
            except:
                self._send_json({"error": "Invalid JSON"}, 400)
                return

            url = data.get('url', '').strip()
            if not url:
                self._send_json({"error": "No URL provided"}, 400)
                return

            mode = data.get('mode', 'transcript')
            formats = data.get('formats', 'md')
            domain = data.get('domain')
            batch = data.get('batch')

            job_id = str(uuid.uuid4())[:8]
            job = Job(job_id, url, mode, formats, domain)
            jobs[job_id] = job

            # Process in background
            t = threading.Thread(target=process_job, args=(job,), daemon=True)
            t.start()

            self._send_json({"job_id": job_id, "status": "queued"})
            return

        self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def main():
    server = http.server.HTTPServer(('0.0.0.0', PORT), APIHandler)
    print(f"""
╔══════════════════════════════════════════╗
║   🎬 Video2Doc 工坊 v0.3.0               ║
║                                          ║
║   打开: http://localhost:{PORT}              ║
║   按 Ctrl+C 停止                           ║
╚══════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
