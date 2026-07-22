"""Pipeline: download, extract audio, transcribe, export."""
import json, os, re, subprocess, base64, uuid, time
from pathlib import Path

from .job_manager import Job, JobType, OUTPUT_DIR
from scripts.platform_utils import find_executable

def _get_api_key():
    """Read the SiliconFlow key only from explicit Video2Doc configuration."""
    key = os.environ.get("SILICONFLOW_API_KEY", "")
    if key: return key
    cfg = Path.home() / ".video2doc" / "config.json"
    if cfg.exists():
        try:
            d = json.loads(cfg.read_text(encoding="utf-8"))
            if d.get("siliconflow_api_key"): return d["siliconflow_api_key"]
        except: pass
    return ""

def resolve_url(url):
    curl = find_executable(["curl", "curl.exe"])
    if not curl:
        return url
    try:
        r = subprocess.run(
            [curl, "-sI", "-o", os.devnull, "-w", "%{url_effective}", "-L", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10)
        return r.stdout.strip() or url
    except Exception:
        return url

def download_video(job):
    """Download video for online transcription.

    抖音：优先用 iesdouyin 分享接口（无需 cookie/登录，最稳），失败再退 yt-dlp/Playwright。
    其他平台（B站/YouTube 等）：直接走 yt-dlp。
    """
    full_url = resolve_url(job.url)
    job.url = full_url
    job.status = "downloading"
    job.progress = max(int(getattr(job, "progress", 0) or 0), 20)
    raw_dir = job.dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    is_douyin = "douyin.com" in full_url or "iesdouyin" in full_url
    is_xhs = "xiaohongshu.com" in full_url or "xhslink.com" in full_url

    # 1) 抖音：优先 iesdouyin 分享接口（无 cookie，实测最稳）
    if is_douyin:
        f = _download_douyin_iesdouyin(full_url, raw_dir, job)
        if f and Path(f).exists(): return str(f)

    # 1b) 小红书：优先 __INITIAL_STATE__ 解析（移动端 UA，cookie 可选）
    if is_xhs:
        f = _download_xhs_initial_state(full_url, raw_dir, job)
        if f and Path(f).exists(): return str(f)

    # 2) yt-dlp（通用，抖音 iesdouyin 失败时也再试一次带 cookie 的 yt-dlp）
    yt = find_executable(["yt-dlp", "yt-dlp.exe",
                          str(Path.home() / ".workbuddy/binaries/python/envs/default/bin/yt-dlp")])
    if yt:
        sub_opts = ["--write-subs", "--sub-langs", "all", "--write-auto-subs",
                    "--sub-format", "srt/vtt/best"]
        # 指定 ffmpeg 位置，让 yt-dlp 自动合并视频轨+音频轨成 video.mp4（否则留 video.fXXXX.mp4 不匹配）
        ff_bin = find_executable(["ffmpeg", "ffmpeg.exe",
                                  str(Path.home() / ".workbuddy/binaries/ffmpeg/ffmpeg")])
        ff_loc = ["--ffmpeg-location", str(Path(ff_bin).parent)] if ff_bin else []
        cookie_ok = False
        try:
            cookie_result = subprocess.run(
                [yt, "--cookies-from-browser", "chrome"] + sub_opts + ff_loc +
                ["-o", str(raw_dir / "video.%(ext)s"), full_url],
                capture_output=True, timeout=300)
            cookie_ok = cookie_result.returncode == 0
        except Exception:
            cookie_ok = False
        if not cookie_ok:
            try:
                subprocess.run([yt] + sub_opts + ff_loc +
                               ["-o", str(raw_dir / "video.%(ext)s"), full_url],
                              capture_output=True, timeout=300)
            except Exception:
                pass
        for ext in ["mp4", "webm", "mkv", "flv"]:
            f = raw_dir / f"video.{ext}"
            if f.exists(): return str(f)
        # 兜底：若仍未合并，找 video.f*.mp4 单视频轨并尝试合并
        v_tracks = sorted(raw_dir.glob("video.f*.mp4"))
        a_tracks = sorted(raw_dir.glob("video.f*.m4a")) + sorted(raw_dir.glob("video.f*.mp3"))
        if v_tracks and ff_bin:
            merged = raw_dir / "video.mp4"
            cmd = [ff_bin, "-y", "-i", str(v_tracks[0])]
            if a_tracks:
                cmd += ["-i", str(a_tracks[0]), "-c", "copy", "-map", "0:v", "-map", "1:a"]
            else:
                cmd += ["-c", "copy"]
            cmd += [str(merged)]
            subprocess.run(cmd, capture_output=True, timeout=120)
            if merged.exists() and merged.stat().st_size > 100000:
                return str(merged)

    # 3) 抖音 Playwright 浏览器兜底（最后手段）
    if is_douyin:
        f = _download_douyin_playwright(full_url, raw_dir, job)
        if f and Path(f).exists(): return str(f)

    # 4) 都失败，给出可执行的提示
    if is_douyin:
        job.error = ("抖音下载失败：iesdouyin/yt-dlp/Playwright 均未拿到视频。"
                     "可手动保存视频后走「本地媒体转录」。")
    elif is_xhs:
        job.error = ("小红书下载失败：__INITIAL_STATE__/yt-dlp 均未拿到视频。"
                     "可设 XHS_COOKIE 环境变量，或手动保存视频后走「本地媒体转录」。")
    elif not yt:
        job.error = "未找到 yt-dlp，请执行 pip install yt-dlp"
    else:
        job.error = "视频下载失败：yt-dlp 未能获取该链接的视频"
    return None


def _download_douyin_iesdouyin(url, raw_dir, job):
    """抖音下载：iesdouyin 分享接口（无需 cookie/登录/yt-dlp）。

    用 iesdouyin.com/share/video/<id> + 移动端 UA 提取 window._ROUTER_DATA，
    拿 CDN 直链（playwm→play 去水印）下载。参考 chubbyguan/chubbyskills。
    返回视频路径或 None。
    """
    MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 "
                 "Version/17.0 Mobile/15E148 Safari/604.1")
    curl = find_executable(["curl", "curl.exe"]) or "curl"
    try:
        # 1) 提取 video id（已是完整链接直接取；短链则跟重定向）
        m = re.search(r'/video/(\d+)', url)
        if not m:
            r = subprocess.run([curl, "-sI", "-L", "-H", f"User-Agent: {MOBILE_UA}", url],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=15)
            for line in r.stdout.split('\n'):
                if 'location:' in line.lower():
                    url = line.split(':', 1)[1].strip()
            m = re.search(r'/video/(\d+)', url)
        if not m:
            job.error = "iesdouyin: 无法提取视频ID"
            return None
        vid = m.group(1)
        # 2) 抓 iesdouyin 分享页
        share = f"https://www.iesdouyin.com/share/video/{vid}"
        r = subprocess.run([curl, "-s", "-L", "-H", f"User-Agent: {MOBILE_UA}", share],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        html = r.stdout
        # 3) 提取 window._ROUTER_DATA
        match = re.search(r'window\._ROUTER_DATA\s*=\s*(.*?)</script>', html, re.DOTALL)
        if not match:
            job.error = "iesdouyin: _ROUTER_DATA 未找到（接口可能已变）"
            return None
        data = json.loads(match.group(1).strip())
        item = data["loaderData"]["video_(id)/page"]["videoInfoRes"]["item_list"][0]
        if not job.title:
            job.title = item.get("desc", "")  # 顺便拿视频标题
        vurl = item["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
        # 4) 下载视频（移动端 UA + Referer）
        out = raw_dir / "video.mp4"
        subprocess.run([curl, "-s", "-L", "-o", str(out),
                        "-H", f"User-Agent: {MOBILE_UA}",
                        "-H", "Referer: https://www.douyin.com/", vurl],
                       timeout=300, check=True)
        if out.exists() and out.stat().st_size > 100000:
            return str(out)
        job.error = "iesdouyin: 下载文件过小或为空"
        return None
    except Exception as e:
        job.error = f"iesdouyin 下载失败: {e}"
        return None


def _download_xhs_initial_state(url, raw_dir, job):
    """小红书下载：解析页面 __INITIAL_STATE__ 提视频直链（移动端 UA，cookie 可选）。

    比纯 yt-dlp+cookie 稳：移动端 UA 更宽容，结构化数据优先，masterUrl 直链下载。
    参考 chubbyguan/chubbyskills。可选 XHS_COOKIE 环境变量提高成功率。
    返回视频路径或 None。
    """
    UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
    curl = find_executable(["curl", "curl.exe"]) or "curl"
    cookie = os.environ.get("XHS_COOKIE", "")
    try:
        # 1) 抓页面（移动端 UA + Referer，可选 cookie）
        hdr = ["-H", f"User-Agent: {UA}", "-H", "Referer: https://www.xiaohongshu.com/"]
        if cookie:
            hdr += ["-H", f"Cookie: {cookie}"]
        r = subprocess.run([curl, "-s", "-L"] + hdr + [url],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        html = r.stdout
        # 风控检测
        if "请通过小红书" in html or "verify" in html.lower()[:2000]:
            job.error = "小红书风控拦截（建议设 XHS_COOKIE 环境变量）"
            return None
        # 2) 括号配平提取 __INITIAL_STATE__（比 }</script> 正则稳）
        idx = html.find("__INITIAL_STATE__")
        if idx == -1:
            job.error = "小红书: __INITIAL_STATE__ 未找到"
            return None
        brace = html.find("{", idx)
        if brace == -1:
            return None
        depth, in_str, esc, end = 0, False, False, -1
        for i, ch in enumerate(html[brace:]):
            if esc: esc = False; continue
            if ch == "\\": esc = True; continue
            if ch == '"': in_str = not in_str; continue
            if in_str: continue
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0: end = brace + i + 1; break
        if end < 0:
            return None
        raw = re.sub(r"([:,\[]\s*)undefined\b", r"\1null", html[brace:end])
        state = json.loads(raw)
        # 3) 递归找 note（含 interactInfo + desc/title）
        note = [None]
        def walk(o):
            if note[0] is not None: return
            if isinstance(o, dict):
                if "interactInfo" in o and ("desc" in o or "title" in o):
                    note[0] = o; return
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        # 优先走已知路径
        try:
            nm = state["note"]["noteDetailMap"]
            for v in nm.values():
                if isinstance(v, dict) and v.get("note"): note[0] = v["note"]; break
        except Exception:
            pass
        if note[0] is None:
            walk(state)
        if note[0] is None:
            job.error = "小红书: 未定位到 note 对象"
            return None
        if not job.title:
            job.title = (note[0].get("title") or "").strip()
        # 4) 提视频直链 masterUrl（h264/h265/h266/av1）
        video = note[0].get("video") or {}
        stream = (video.get("media") or {}).get("stream") or {}
        vurl = None
        for codec in ("h264", "h265", "h266", "av1"):
            for item in (stream.get(codec) or []):
                if item.get("masterUrl"): vurl = item["masterUrl"]; break
            if vurl: break
        if not vurl:
            found = [None]
            def w2(o):
                if found[0] is not None: return
                if isinstance(o, dict):
                    if isinstance(o.get("masterUrl"), str): found[0] = o["masterUrl"]; return
                    for v in o.values(): w2(v)
                elif isinstance(o, list):
                    for v in o: w2(v)
            w2(video); vurl = found[0]
        if not vurl:
            job.error = "小红书: 未提取到视频直链（可能是图文笔记，非视频）"
            return None
        # 5) 下载视频
        out = raw_dir / "video.mp4"
        subprocess.run([curl, "-s", "-L", "-o", str(out)] + hdr + [vurl],
                       timeout=300, check=True)
        if out.exists() and out.stat().st_size > 100000:
            return str(out)
        job.error = "小红书: 下载文件过小或为空"
        return None
    except Exception as e:
        job.error = f"小红书下载失败: {e}"
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
    """Pure download — 复用 download_video 的优化逻辑(iesdouyin/小红书/ffmpeg-location)，
    视频移到 job.dir/ 根目录，供 server /api/download/{id}/{file} 直供下载。"""
    video = download_video(job)  # 下载到 job.dir/raw/video.mp4（含所有平台优化 + 字幕）
    if not video:
        if not job.error: job.error = "下载失败"
        return None
    # 移到 job.dir/ 根目录，供 server /api/download/{id}/{file} 服务
    src = Path(video)
    dst = job.dir / src.name
    if src.resolve() != dst.resolve():
        shutil.move(str(src), str(dst))
    job.download_path = str(dst)
    job.files = [{"name": "Video", "file": dst.name, "size": dst.stat().st_size}]
    return str(dst)

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
    """读取豆包语音 API Key：环境变量 → Video2Doc 专用配置。"""
    key = os.environ.get("DOUBAO_API_KEY", "")
    if key: return key
    cfg = Path.home() / ".video2doc" / "config.json"
    if cfg.exists():
        try:
            d = json.loads(cfg.read_text(encoding="utf-8"))
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
             "-H", "@-",
             "-F", f"file=@{audio_path}",
             "-F", "model=TeleAI/TeleSpeechASR",
             "-F", "response_format=verbose_json"],
            input=f"Authorization: Bearer {api_key}\r\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=130)
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
    - local_only: auto 仅尝试 FunASR → Whisper；显式选择云引擎会直接拒绝。
    - doubao/tele/funasr/whisper: 仅用指定引擎；失败时 error 提示可切换其他引擎。
    返回 {text, segments} 或 None。成功时 job.engine_used 记录所用引擎。
    """
    engines = [("doubao", _transcribe_doubao), ("tele", _transcribe_tele),
               ("funasr", _transcribe_funasr), ("whisper", _transcribe_whisper)]
    local_engines = [("funasr", _transcribe_funasr), ("whisper", _transcribe_whisper)]
    engine_map = dict(engines)
    engine = (getattr(job, "engine", None) or "auto").lower()
    local_only = bool(getattr(job, "local_only", False))
    if local_only and engine in ("doubao", "tele"):
        job.error = (f"local_only 模式不允许云端引擎「{engine}」；"
                     "请选择 funasr、whisper 或 auto")
        return None
    if engine == "auto":
        order = local_engines if local_only else engines
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
        scope = "本地引擎" if local_only else "所有引擎"
        job.error = f"{scope}均失败（{'→'.join(failed)}）。可在「引擎」下拉切换后重试。"
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
                                       capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=30)
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

def _enrich_transcript(text, job):
    """content-enrich：用 LLM(SiliconFlow chat) 给文稿补 摘要+要点+标签。best-effort，失败返回 None。"""
    key = _get_api_key()  # SiliconFlow key 同时支持 chat
    if not key or not text or len(text) < 20:
        return None
    snippet = text[:4000]
    prompt = ("请阅读下面视频文稿，输出 JSON：{\"summary\":\"一句话摘要\","
              "\"keypoints\":[\"要点1\",\"要点2\",...],\"tags\":[\"标签1\",...]}。"
              "要点3-5条，标签3-5个。只输出 JSON。\n\n文稿：\n" + snippet)
    body = json.dumps({
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3, "max_tokens": 700,
    }).encode("utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.siliconflow.cn/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=70) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return None
    except Exception:
        return None  # 增强失败不阻断主流程


def _should_enrich(job):
    """Return whether cloud transcript enrichment is allowed for this job."""
    formats = {str(item).strip().lower() for item in getattr(job, "formats", [])}
    supports_enrichment = bool(formats & {"md", "json", "all"})
    return (bool(getattr(job, "allow_enrichment", True))
            and not bool(getattr(job, "local_only", False))
            and supports_enrichment)


def _enrichment_block(enrichment):
    """把 enrich 结果渲染成 Markdown 摘要块。"""
    if not enrichment:
        return ""
    lines = ["## 📝 摘要", ""]
    if enrichment.get("summary"):
        lines += ["> " + enrichment["summary"], ""]
    kp = enrichment.get("keypoints") or []
    if kp:
        lines += ["**要点：**", ""]
        lines += [f"- {k}" for k in kp]
        lines.append("")
    tags = enrichment.get("tags") or []
    if tags:
        lines += ["**标签：** " + " ".join(f"`{t}`" for t in tags), ""]
    lines += ["---", ""]
    return "\n".join(lines)


def export_formats(job, transcript, enrichment=None):
    exported = []
    segments = transcript.get("segments", [])
    full_text = transcript.get("text", "")
    head = _enrichment_block(enrichment)

    for fmt in job.formats:
        fmt = fmt.strip()
        if fmt == "all":
            fmt_list = ["md", "txt", "json", "srt"]
        else:
            fmt_list = [fmt]
        for f in fmt_list:
            if f == "md":
                p = job.dir / "transcript.md"
                p.write_text(head + full_text if head else full_text, encoding="utf-8")
                exported.append({"name":"Markdown","file":"transcript.md","size":p.stat().st_size})
            elif f == "txt":
                p = job.dir / "transcript.txt"
                p.write_text(full_text, encoding="utf-8")
                exported.append({"name":"TXT","file":"transcript.txt","size":p.stat().st_size})
            elif f == "json":
                p = job.dir / "transcript.json"
                p.write_text(json.dumps({"segments":segments,"total":len(segments),"enrichment":enrichment},ensure_ascii=False,indent=2),encoding="utf-8")
                exported.append({"name":"JSON","file":"transcript.json","size":p.stat().st_size})
            elif f == "srt":
                p = job.dir / "transcript.srt"
                p.write_text(to_srt(segments), encoding="utf-8")
                exported.append({"name":"SRT","file":"transcript.srt","size":p.stat().st_size})
    return exported

def _parse_srt_to_transcript(srt_path):
    """解析 SRT 字幕 → {text, segments}（与 ASR 输出同构）。失败返回 None。"""
    try:
        content = Path(srt_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    segments = []
    parts = []
    for blk in re.split(r'\n\s*\n', content.strip()):
        lines = [l for l in blk.strip().split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        tline = None
        tidx = 0
        for i, l in enumerate(lines):
            if '-->' in l:
                tline = l
                tidx = i
                break
        if not tline:
            continue
        m = re.match(r'\s*(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', tline)
        if m:
            g = m.groups()
            start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
            end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000
        else:
            m2 = re.match(r'\s*(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+)[,.](\d+)', tline)
            if not m2:
                continue
            g = m2.groups()
            start = int(g[0]) * 60 + int(g[1]) + int(g[2]) / 1000
            end = int(g[3]) * 60 + int(g[4]) + int(g[5]) / 1000
        text = ' '.join(lines[tidx + 1:]).strip()
        if not text:
            continue
        segments.append({"id": len(segments), "start": start, "end": end, "text": text})
        parts.append(text)
    if not segments:
        return None
    return {"text": " ".join(parts), "segments": segments}


def _try_subtitle_transcript(job):
    """字幕优先：扫描 raw/ 下平台字幕（B站 ai-zh.srt 优先，其次任意 .srt），
    有则解析为 {text, segments} 返回，无则 None。仅 engine=auto 时调用。"""
    raw = job.dir / "raw"
    if not raw.exists():
        return None
    cands = []
    for p in raw.glob("*.srt"):
        name = p.name.lower()
        if "ai-zh" in name or "ai_cn" in name or name.endswith(".zh.srt"):
            cands.insert(0, p)
        elif "zh" in name:
            cands.append(p)
    if not cands:
        cands = list(raw.glob("*.srt"))
    for p in cands:
        try:
            if p.stat().st_size < 50:
                continue
        except Exception:
            continue
        t = _parse_srt_to_transcript(p)
        if t and t.get("text"):
            t["_subtitle_source"] = p.name
            return t
    return None


def run_transcribe_pipeline(job):
    """Full pipeline: download → (字幕优先 | audio→ASR) → export (for online transcription)"""
    try:
        job.status = "resolving"; job.progress = 10
        video = download_video(job)
        if not video:
            job.status = "error"
            if not job.error: job.error = "视频下载失败"
            return

        transcript = None
        # 字幕优先：engine=auto 时，有平台字幕(B站 ai-zh 等)就直接用、跳过 ASR（秒级、免额度）
        if (getattr(job, "engine", "auto") or "auto") == "auto":
            transcript = _try_subtitle_transcript(job)
            if transcript:
                job.engine_used = "subtitle"
                job.engine_note = "使用平台字幕（免 ASR）"
                job.error = None

        if not transcript:
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
        enrichment = (_enrich_transcript(transcript.get("text", ""), job)
                      if _should_enrich(job) else None)
        job.files = export_formats(job, transcript, enrichment)
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
            # 音频文件：若已是目标路径(如上传文件就叫 audio.mp3)则直接用，否则复制
            if fp.resolve() != audio_path.resolve():
                shutil.copy2(str(fp), audio_path)

        job.status = "transcribing"; job.progress = 50
        transcript = transcribe(audio_path, job)
        if not transcript:
            job.status = "error"
            if not job.error: job.error = "转录失败"
            return

        (job.dir / "raw" / "tele_result.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2))
        job.title = getattr(job, "local_filename", "") or fp.name
        segs = transcript.get("segments",[])
        if segs:
            t = segs[-1].get("end",0)
            job.duration = f"{int(t)//60:02d}:{int(t)%60:02d}"

        job.status = "exporting"; job.progress = 85
        enrichment = (_enrich_transcript(transcript.get("text", ""), job)
                      if _should_enrich(job) else None)
        job.files = export_formats(job, transcript, enrichment)
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
