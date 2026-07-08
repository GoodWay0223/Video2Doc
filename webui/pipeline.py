"""Pipeline: download, extract audio, transcribe, export."""
import json, os, re, subprocess, shutil, base64, uuid, time
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
    """Download video for online transcription.

    优先用 yt-dlp（支持抖音/B站/YouTube 等绝大多数平台）；
    抖音因反爬常导致 yt-dlp 拿不到视频时，再回退到 Playwright 浏览器兜底。
    """
    full_url = resolve_url(job.url)
    job.url = full_url
    raw_dir = job.dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    is_douyin = "douyin.com" in full_url

    # 1) 优先尝试 yt-dlp（抖音本身也在其支持列表里）
    yt = find_executable(["yt-dlp", "yt-dlp.exe",
                          str(Path.home() / ".workbuddy/binaries/python/envs/default/bin/yt-dlp")])
    if yt:
        subprocess.run([yt, "-o", str(raw_dir / "video.%(ext)s"), full_url],
                      capture_output=True, timeout=300)
        for ext in ["mp4", "webm", "mkv", "flv"]:
            f = raw_dir / f"video.{ext}"
            if f.exists(): return str(f)

    # 2) yt-dlp 没拿到视频：抖音走 Playwright 浏览器兜底
    if is_douyin:
        f = _download_douyin_playwright(full_url, raw_dir, job)
        if f and Path(f).exists(): return str(f)

    # 3) 都失败，给出可执行的提示
    if not yt:
        job.error = "未找到 yt-dlp，请执行 pip install yt-dlp"
    elif is_douyin:
        job.error = ("抖音下载失败：yt-dlp 未能获取视频。可安装 Playwright 浏览器兜底："
                     "pip install playwright && playwright install chromium")
    else:
        job.error = "视频下载失败：yt-dlp 未能获取该链接的视频"
    return None


def _download_douyin_playwright(url, raw_dir, job):
    """用 Playwright 打开抖音页面、拦截媒体流并下载（yt-dlp 失败时的兜底）。

    需要：pip install playwright && playwright install chromium（约 150MB）。
    抖音页面会同时吐出多路 mp4（加载动画 / 贴纸特效 / 真正的主视频），且主视频的
    直链要等触发播放后才会加载。这里：静音自动播放 → 循环多次重试直到抓到抖音
    VOD CDN(douyinvod) 上的主视频直链 → 按体积选最大（最高清）那路；抓到 m3u8/mpd
    则交给 ffmpeg 拉流。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        collected = []  # (content_length, url, content_type)
        def _on_response(resp):
            u = resp.url
            ct = resp.headers.get("content-type", "")
            cl = resp.headers.get("content-length", "")
            if (".mp4" in u or ".m4s" in u or ".mpd" in u or ".m3u8" in u
                    or ct.startswith("video/") or "application/vnd.apple.mpegurl" in ct):
                try:
                    cln = int(cl) if cl else 0
                except ValueError:
                    cln = 0
                collected.append((cln, u, ct))
        def _pick():
            # 抖音主视频直链常无 .mp4 后缀，靠 content-type 判定视频响应
            cands = [(cl, u) for cl, u, ct in collected if ct.startswith("video/")]
            # 排除加载动画(douyinstatic)与贴纸特效(byteeffecttos)等干扰来源
            cands = [(cl, u) for cl, u in cands
                     if "douyinstatic.com" not in u and "byteeffecttos.com" not in u]
            vod = [(cl, u) for cl, u in cands if "douyinvod" in u]
            pool = vod or cands
            return max(pool, key=lambda x: x[0])[1] if pool else None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True,
                                       args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0 Safari/537.36"))
            page = ctx.new_page()
            page.on("response", _on_response)
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass
            page.wait_for_timeout(2000)
            # 静音触发播放（诊断验证此方式可加载主视频直链），多次轮询直到抓到
            best = None
            for _ in range(3):
                try:
                    page.evaluate("const v=document.querySelector('video'); if(v){v.muted=true; void v.play();}")
                except Exception:
                    pass
                page.wait_for_timeout(7000)
                best = _pick()
                if best and "douyinvod" in best:
                    break
            # 兜底：直接读 video 元素的真实播放地址（若不是 blob 直链）
            if not best or "douyinvod" not in best:
                try:
                    src = page.evaluate(
                        "const v=document.querySelector('video'); "
                        "return v ? (v.currentSrc || v.src || '') : '';")
                    if isinstance(src, str) and src.startswith("http") and ".mp4" in src:
                        best = src
                except Exception:
                    pass
            if not best:
                m3u8 = [u for cl, u, ct in collected if ".m3u8" in u or ".mpd" in u]
                best = m3u8[0] if m3u8 else _pick()
            if not best:
                browser.close()
                return None
            out = raw_dir / "video.mp4"
            if ".m3u8" in best or ".mpd" in best:
                ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe",
                                          str(Path.home() / ".workbuddy/binaries/ffmpeg/ffmpeg")])
                if not ffmpeg:
                    browser.close(); return None
                ck = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies())
                hdr = "Referer https://www.douyin.com/\r\n" + (f"Cookie {ck}\r\n" if ck else "")
                subprocess.run([ffmpeg, "-headers", hdr, "-i", best, "-c", "copy",
                                "-y", str(out)], capture_output=True, timeout=300)
            else:
                r = ctx.request.get(best, timeout=120000)
                out.write_bytes(r.body())
            browser.close()
        return str(out) if out.exists() and out.stat().st_size > 0 else None
    except Exception as e:
        job.error = f"Playwright 下载抖音失败: {e}"
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

def _get_doubao_key():
    """读取豆包语音 API Key：env DOUBAO_API_KEY → ~/.video2doc/config.json → MEMORY.md。"""
    key = os.environ.get("DOUBAO_API_KEY", "")
    if key: return key
    cfg = Path.home() / ".video2doc" / "config.json"
    if cfg.exists():
        try:
            d = json.loads(cfg.read_text())
            if d.get("doubao_api_key"): return d["doubao_api_key"]
        except: pass
    return ""


def _transcribe_doubao(audio_path, job):
    """云端转录：豆包录音文件识别大模型 2.0（异步 submit+query，base64 内联音频）。

    云端首选引擎。中文准确度高（实测优于 TeleSpeechASR）、自带标点+ITN+词级时间戳。
    需 DOUBAO_API_KEY。音频自动用 ffmpeg 重采样到 16kHz 单声道。

    实现要点（对齐官方文档 docs/6561/1354868）：
    - 异步：submit 提交(X-Api-Sequence:-1) → 用同一 X-Api-Request-Id 轮询 query。
    - 状态码在响应头 X-Api-Status-Code（非 body）：20000000 成功 / 20000001 处理中 /
      20000002 排队 / 20000003 静音 / 4xxxxx·5xxxxx 错误。
    - 音频官方文档仅列 audio.url；audio.data(base64 内联) 实测可用但非文档字段。
    - 用 urllib 而非 curl：规避 ARG_MAX 限制、可直接读响应头。
    返回归一化 {text, segments} 或 None（无 Key/失败时落到下一级）。
    """
    key = _get_doubao_key()
    if not key:
        return None  # 无 Key → 落到下一级
    import urllib.request, urllib.error
    ffmpeg = find_executable(["ffmpeg", "ffmpeg.exe",
                              str(Path.home() / ".workbuddy/binaries/ffmpeg/ffmpeg")])
    submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
    logid = ""
    try:
        # 1) 重采样到 16kHz 单声道 mp3（豆包要求 16k）
        tmp_16k = None
        if ffmpeg:
            tmp_16k = Path(job.dir) / "raw" / "audio_16k.mp3"
            tmp_16k.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([ffmpeg, "-y", "-i", str(audio_path), "-ar", "16000",
                            "-ac", "1", str(tmp_16k)],
                           capture_output=True, timeout=180)
        src = tmp_16k if (tmp_16k and tmp_16k.exists()) else Path(audio_path)
        # 2) base64 内联（实测可用；官方文档仅列 audio.url，待充分验证）
        b64 = base64.b64encode(src.read_bytes()).decode()
        rid = str(uuid.uuid4())
        body = json.dumps({
            "user": {"uid": "video2doc"},
            "audio": {"data": b64, "format": "mp3", "codec": "raw",
                      "rate": 16000, "bits": 16, "channel": 1},
            "request": {"model_name": "bigmodel", "enable_itn": True,
                        "enable_punc": True, "enable_ddc": False,
                        "enable_speaker_info": False, "enable_channel_split": False,
                        "show_utterances": True, "vad_segment": False,
                        "sensitive_words_filter": ""}
        }).encode("utf-8")
        base_hdr = {"Content-Type": "application/json",
                    "x-api-key": key,
                    "X-Api-Resource-Id": "volc.seedasr.auc",
                    "X-Api-Request-Id": rid}
        # 3) submit（X-Api-Sequence:-1 仅 submit 需要）
        submit_req = urllib.request.Request(
            submit_url, data=body,
            headers=dict(base_hdr, **{"X-Api-Sequence": "-1"}), method="POST")
        try:
            with urllib.request.urlopen(submit_req, timeout=60) as resp:
                s_status = resp.headers.get("X-Api-Status-Code", "")
                s_msg = resp.headers.get("X-Api-Message", "")
                logid = resp.headers.get("X-Tt-Logid", "")
            if s_status and s_status != "20000000":
                job.error = f"豆包 submit 失败: status={s_status} msg={s_msg} logid={logid}"
                return None
        except urllib.error.HTTPError as e:
            job.error = f"豆包 submit HTTP 错误: {e.code} {e.reason}"
            return None
        # 4) 轮询 query（按响应头状态码判定，最多 ~90s）
        data = None
        for _ in range(30):
            qreq = urllib.request.Request(query_url, data=b"{}",
                                          headers=base_hdr, method="POST")
            try:
                with urllib.request.urlopen(qreq, timeout=30) as resp:
                    q_status = resp.headers.get("X-Api-Status-Code", "")
                    q_msg = resp.headers.get("X-Api-Message", "")
                    logid = resp.headers.get("X-Tt-Logid", "") or logid
                    raw = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                job.error = f"豆包 query HTTP 错误: {e.code} {e.reason}"
                return None
            try:
                d = json.loads(raw) if raw else {}
            except Exception:
                d = {}
            res = d.get("result")
            if q_status == "20000000":
                if res and (res.get("text") or res.get("utterances")):
                    data = d
                    break
                # 成功但无内容（可能静音）
                job.error = f"豆包: 成功但无识别内容(可能静音) logid={logid}"
                return None
            elif q_status in ("20000001", "20000002"):
                time.sleep(3)  # 处理中/排队中 → 继续轮询
                continue
            elif q_status == "20000003":
                job.error = f"豆包: 未检测到人声(静音音频) logid={logid}"
                return None
            elif q_status and (q_status.startswith("4") or q_status.startswith("5")):
                job.error = f"豆包 query 错误: status={q_status} msg={q_msg} logid={logid}"
                return None
            else:
                time.sleep(3)  # 无状态头 → 兜底继续轮询
        if not data:
            if not job.error:
                job.error = f"豆包转录超时或无结果 logid={logid}"
            return None
        # 5) 归一化为 {text, segments}（ms → s）
        result = data.get("result", {})
        text = result.get("text", "")
        segs = []
        for u in result.get("utterances", []):
            segs.append({
                "id": len(segs),
                "start": u.get("start_time", 0) / 1000.0,
                "end": u.get("end_time", 0) / 1000.0,
                "text": u.get("text", "").strip()
            })
        if not segs and text:
            dur = data.get("audio_info", {}).get("duration", 0)
            segs.append({"id": 0, "start": 0,
                         "end": dur / 1000.0 if dur else 0, "text": text})
        return {"text": text, "segments": segs}
    except Exception as e:
        job.error = f"豆包转录失败: {e} logid={logid}"
        return None


def _transcribe_tele(audio_path, job):
    """云端转录：硅基流动 TeleSpeechASR（同步 API）。需 SILICONFLOW_API_KEY。"""
    api_key = _get_api_key()
    if not api_key:
        return None  # 无 Key → 落到下一级
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
        data = json.loads(r.stdout)
        if data and data.get("text"):
            return data
        job.error = "TeleSpeechASR 返回空结果"
    except Exception as e:
        job.error = f"TeleSpeechASR 失败: {e}"
    return None


# 引擎注册表（在 transcribe() 内构建，避免定义顺序问题）：
#   doubao(云端首选,中文最准) → tele(云端兜底) → funasr(本地首选) → whisper(本地末位)


def transcribe(audio_path, job):
    """Transcribe audio. 引擎由 job.engine 决定（默认 auto）。

    - auto: 豆包 → TeleSpeechASR → FunASR → Whisper 自动降级（首选额度耗尽/不稳定时
      静默切到下一级，并在 engine_note 里提示用户）。
    - doubao/tele/funasr/whisper: 仅用指定引擎；失败时 error 提示可切换其他引擎。
    返回 {text, segments} 或 None。成功时 job.engine_used 记录所用引擎。
    """
    engines = [("doubao", _transcribe_doubao), ("tele", _transcribe_tele),
               ("funasr", _transcribe_funasr), ("whisper", _transcribe_whisper)]
    engine_map = dict(engines)
    engine = (getattr(job, "engine", None) or "auto").lower()
    if engine == "auto":
        order = engines
    else:
        fn = engine_map.get(engine)
        if not fn:
            job.error = f"未知引擎: {engine}（可选 doubao/tele/funasr/whisper/auto）"
            return None
        order = [(engine, fn)]

    failed = []
    for name, fn in order:
        r = fn(audio_path, job)
        if r and r.get("text"):
            job.error = None
            job.engine_used = name
            job.engine_note = (f"已自动切换到「{name}」（{'→'.join(failed)} 不可用）"
                               if (engine == "auto" and failed) else "")
            return r
        failed.append(name)

    # 全部失败
    if engine == "auto":
        job.error = f"所有引擎均失败（{'→'.join(failed)}）。可在「引擎」下拉切换后重试。"
    else:
        base = job.error or f"{engine} 转录失败"
        job.error = f"{base}（可切换其他引擎重试：引擎下拉选择）"
    return None


def _transcribe_funasr(audio_path, job):
    """本地转录：FunASR Paraformer（离线、无需 API Key）。

    中文场景比 Whisper 更快更准，自带 VAD + 标点 + ITN。
    需: pip install funasr（首次运行下载约 300MB 模型到 ~/.cache/modelscope/）。
    """
    try:
        from funasr import AutoModel
    except Exception:
        return None  # 未安装 / torch 损坏 → 落到下一级
    try:
        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
        except Exception:
            pass
        model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device=device,
        )
        res = model.generate(input=str(audio_path), batch_size_s=300)
        if not res:
            return None
        segments = []
        parts = []
        for item in res:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            ts = item.get("timestamp") or []
            start = end = 0.0
            if isinstance(ts, list) and len(ts) > 0:
                first = ts[0]
                last = ts[-1]
                if isinstance(first, (list, tuple)) and len(first) >= 1:
                    start = float(first[0]) / 1000.0
                if isinstance(last, (list, tuple)) and len(last) >= 2:
                    end = float(last[1]) / 1000.0
            segments.append({"id": len(segments), "start": start, "end": end, "text": text})
            parts.append(text)
        if not segments:
            return None
        # 时间戳缺失时，用 ffprobe 取音频总时长兜底给末段
        if all(s["end"] == 0 for s in segments):
            try:
                fp = find_executable(["ffprobe", "ffprobe.exe",
                                      str(Path.home() / ".workbuddy/binaries/ffmpeg/ffprobe")])
                if fp:
                    r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                                        "-of", "csv=p=0", str(audio_path)],
                                       capture_output=True, text=True, timeout=30)
                    dur = float(r.stdout.strip()) if r.stdout.strip() else 0
                    if dur:
                        segments[-1]["end"] = dur
            except Exception:
                pass
        return {"text": "".join(parts), "segments": segments}
    except Exception as e:
        job.error = f"FunASR 本地转录失败: {e}"
        return None


def _transcribe_whisper(audio_path, job):
    """末位兜底：本地 Whisper（离线、多语言）。

    仅当无云端 Key 且 FunASR 未安装/失败时使用。中文用 turbo 模型。
    需: pip install openai-whisper（首次下载约 1.5GB 模型）。
    """
    try:
        import whisper
    except Exception:
        return None
    try:
        model = whisper.load_model("turbo")
        result = model.transcribe(str(audio_path), language="zh")
        segs = result.get("segments", [])
        segments = [{"id": i, "start": s.get("start", 0), "end": s.get("end", 0),
                     "text": (s.get("text") or "").strip()} for i, s in enumerate(segs)]
        return {"text": result.get("text", ""), "segments": segments}
    except Exception as e:
        job.error = f"Whisper 本地转录失败: {e}"
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
        if not video:
            job.status = "error"
            if not job.error: job.error = "视频下载失败"
            return

        job.status = "extracting"; job.progress = 30
        audio = job.dir / "raw" / "audio.mp3"
        audio.parent.mkdir(exist_ok=True)
        if not extract_audio(video, audio):
            job.status = "error"; job.error = "音频提取失败"; return

        job.status = "transcribing"; job.progress = 60
        transcript = transcribe(audio, job)
        if not transcript:
            job.status = "error"
            if not job.error: job.error = "转录失败"
            return

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
