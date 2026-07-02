"""Pipeline: download, extract audio, transcribe, export."""
import json, os, re, subprocess, shutil
from pathlib import Path

from .job_manager import Job, JobType, OUTPUT_DIR

IS_WINDOWS = os.name == 'nt'

def find_executable(names):
    """Find the first available executable.
    Handles: bare names (ffmpeg), .exe variants (ffmpeg.exe),
    and absolute paths (/usr/local/bin/ffmpeg).
    """
    for name in names:
        # Check absolute/relative path directly
        if '/' in name or '\\' in name:
            if Path(name).exists() and Path(name).is_file():
                return name
            continue
        # Check PATH via which
        if shutil.which(name):
            return name
        if IS_WINDOWS:
            exe = name + '.exe'
            if shutil.which(exe):
                return exe
            for base in [os.environ.get('LOCALAPPDATA', ''), os.environ.get('PROGRAMFILES', ''), 'C:\\Program Files']:
                c = Path(base) / exe
                if c.exists(): return str(c)
    return None

def _get_api_key():
    key = os.environ.get("SILICONFLOW_API_KEY", "")
    if key: return key
    cfg = Path.home() / ".video2doc" / "config.json"
    if cfg.exists():
        try:
            d = json.loads(cfg.read_text())
            if d.get("siliconflow_api_key"): return d["siliconflow_api_key"]
        except: pass
    wb = Path.home() / ".workbuddy" / "MEMORY.md"
    if wb.exists():
        m = re.search(r'SILICONFLOW_API_KEY:\s*(sk-[a-zA-Z0-9]+)', wb.read_text())
        if m: return m.group(1)
    return ""

def resolve_url(url):
    try:
        r = subprocess.run(
            ["curl", "-sI", "-o", "/dev/null", "-w", "%{url_effective}", "-L", url],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or url
    except:
        return url

def download_video(job):
    """Download video for online transcription"""
    full_url = resolve_url(job.url)
    job.url = full_url
    raw_dir = job.dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    is_douyin = "douyin.com" in full_url
    if is_douyin:
        for ext in ["mp4", "webm"]:
            f = raw_dir / f"video.{ext}"
            if f.exists(): return str(f)
        job.error = "抖音下载需 Playwright 支持，或手动将视频放入 raw/video.mp4"
        return None
    else:
        yt = find_executable(["yt-dlp", "yt-dlp.exe",
                              str(Path.home() / ".workbuddy/binaries/python/envs/default/bin/yt-dlp")])
        if not yt:
            job.error = "未找到 yt-dlp，请执行 pip install yt-dlp"
            return None
        subprocess.run([yt, "-o", str(raw_dir / "video.%(ext)s"), full_url],
                      capture_output=True, timeout=300)
        for ext in ["mp4", "webm", "mkv", "flv"]:
            f = raw_dir / f"video.{ext}"
            if f.exists(): return str(f)
    return None

def download_video_only(job):
    """Pure download — save to output/downloads/"""
    full_url = resolve_url(job.url)
    job.url = full_url
    dl_dir = OUTPUT_DIR / "downloads" / job.id
    dl_dir.mkdir(parents=True, exist_ok=True)

    yt = find_executable(["yt-dlp", "yt-dlp.exe",
                          str(Path.home() / ".workbuddy/binaries/python/envs/default/bin/yt-dlp")])
    if not yt:
        job.error = "未找到 yt-dlp"
        return None
    out_tpl = str(dl_dir / "video.%(ext)s")
    subprocess.run([yt, "-o", out_tpl, full_url], capture_output=True, timeout=300)
    for ext in ["mp4", "webm", "mkv", "flv"]:
        f = dl_dir / f"video.{ext}"
        if f.exists():
            job.download_path = str(f)
            job.files = [{"name": "Video", "file": f"video.{ext}", "size": f.stat().st_size}]
            return str(f)
    return None

def extract_audio(video_path, output_path):
    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe",
                              str(Path.home() / ".workbuddy/binaries/ffmpeg/ffmpeg")])
    if not ffmpeg: return False
    try:
        subprocess.run([ffmpeg, "-i", str(video_path), "-vn", "-acodec", "libmp3lame",
                       "-q:a", "2", "-y", str(output_path)], capture_output=True, timeout=120)
        return Path(output_path).exists()
    except: return False

def transcribe(audio_path, job):
    api_key = _get_api_key()
    if not api_key:
        job.error = "未找到 API Key。请设置 SILICONFLOW_API_KEY 环境变量"
        return None
    curl = find_executable(["curl", "curl.exe"]) or "curl"
    try:
        r = subprocess.run(
            [curl, "-s", "--max-time", "120", "--retry", "3", "--retry-delay", "2",
             "https://api.siliconflow.cn/v1/audio/transcriptions",
             "-H", f"Authorization: Bearer {api_key}",
             "-F", f"file=@{audio_path}",
             "-F", "model=TeleAI/TeleSpeechASR",
             "-F", "response_format=verbose_json"],
            capture_output=True, text=True, timeout=130)
        return json.loads(r.stdout)
    except Exception as e:
        job.error = f"转录 API 错误: {e}"
        return None

def _fmt_time(seconds):
    h, m = divmod(int(seconds), 3600)
    m, s = divmod(m, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def to_srt(segments):
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _fmt_time(seg.get("start", 0))
        end = _fmt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if text: lines.extend([str(i), f"{start} --> {end}", text, ""])
    return "\n".join(lines)

def export_formats(job, transcript):
    exported = []
    segments = transcript.get("segments", [])
    full_text = transcript.get("text", "")

    for fmt in job.formats:
        fmt = fmt.strip()
        if fmt == "all":
            fmt_list = ["md", "txt", "json", "srt"]
        else:
            fmt_list = [fmt]
        for f in fmt_list:
            if f == "md":
                p = job.dir / "transcript.md"
                p.write_text(full_text, encoding="utf-8")
                exported.append({"name":"Markdown","file":"transcript.md","size":p.stat().st_size})
            elif f == "txt":
                p = job.dir / "transcript.txt"
                p.write_text(full_text, encoding="utf-8")
                exported.append({"name":"TXT","file":"transcript.txt","size":p.stat().st_size})
            elif f == "json":
                p = job.dir / "transcript.json"
                p.write_text(json.dumps({"segments":segments,"total":len(segments)},ensure_ascii=False,indent=2),encoding="utf-8")
                exported.append({"name":"JSON","file":"transcript.json","size":p.stat().st_size})
            elif f == "srt":
                p = job.dir / "transcript.srt"
                p.write_text(to_srt(segments), encoding="utf-8")
                exported.append({"name":"SRT","file":"transcript.srt","size":p.stat().st_size})
    return exported

def run_transcribe_pipeline(job):
    """Full pipeline: download → audio → transcribe → export (for online transcription)"""
    try:
        job.status = "resolving"; job.progress = 10
        video = download_video(job)
        if not video: return

        job.status = "extracting"; job.progress = 30
        audio = job.dir / "raw" / "audio.mp3"
        audio.parent.mkdir(exist_ok=True)
        if not extract_audio(video, audio):
            job.status = "error"; job.error = "音频提取失败"; return

        job.status = "transcribing"; job.progress = 60
        transcript = transcribe(audio, job)
        if not transcript: return

        (job.dir / "raw" / "tele_result.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
        job.title = (transcript.get("text","")[:80] + "...") if len(transcript.get("text",""))>80 else transcript.get("text","")
        segs = transcript.get("segments",[])
        if segs:
            t = segs[-1].get("end",0)
            job.duration = f"{int(t)//60:02d}:{int(t)%60:02d}"

        job.status = "exporting"; job.progress = 85
        job.files = export_formats(job, transcript)
        job.status = "done"; job.progress = 100
    except Exception as e:
        job.status = "error"; job.error = str(e)

def run_local_pipeline(job, file_path):
    """Pipeline for local file transcription"""
    try:
        fp = Path(file_path)
        job.status = "extracting"; job.progress = 20

        is_video = fp.suffix.lower() in {".mp4",".mov",".mkv",".webm",".avi",".flv"}
        audio_path = job.dir / "raw" / "audio.mp3"
        audio_path.parent.mkdir(exist_ok=True)

        if is_video:
            if not extract_audio(str(fp), audio_path):
                job.status = "error"; job.error = "音频提取失败"; return
        else:
            shutil.copy2(str(fp), audio_path)

        job.status = "transcribing"; job.progress = 50
        transcript = transcribe(audio_path, job)
        if not transcript: return

        (job.dir / "raw" / "tele_result.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
        job.title = fp.name
        segs = transcript.get("segments",[])
        if segs:
            t = segs[-1].get("end",0)
            job.duration = f"{int(t)//60:02d}:{int(t)%60:02d}"

        job.status = "exporting"; job.progress = 85
        job.files = export_formats(job, transcript)
        job.status = "done"; job.progress = 100
    except Exception as e:
        job.status = "error"; job.error = str(e)

def run_download_pipeline(job):
    """Pure download pipeline"""
    try:
        job.status = "resolving"; job.progress = 20
        job.status = "downloading"; job.progress = 50
        video = download_video_only(job)
        if not video:
            job.status = "error"; job.error = "下载失败"
            return
        job.status = "done"; job.progress = 100
    except Exception as e:
        job.status = "error"; job.error = str(e)
