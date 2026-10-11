---
name: Video2Doc
description: "Video2Doc converts videos (Douyin, Xiaohongshu, Bilibili, YouTube) into structured documentation. Bilibili and Douyin use platform-aware subtitle/audio-first acquisition with classified fallbacks; transcription supports Doubao, TeleSpeechASR, local FunASR, and local Whisper, plus structured exports and optional deep analysis."
agent_created: true
---

# Video2Doc — 视频转文档

Convert any video (Douyin/Xiaohongshu/Bilibili/YouTube) into structured documentation.

---

## 🔒 Security & Privacy

**This Skill does NOT ship with any cookies, API keys, or credentials.**

- **Cookies**: Public Bilibili and Douyin paths normally need no Cookie. Logged-in
  quality or restricted content must use an explicitly configured `cookies.txt`,
  browser source, or Douyin Playwright `storage_state`; live Chrome is never read
  implicitly. `.gitignore` blocks these files and runtime media from commits.
- **API Keys**: Keys are read only from the matching environment variable or
  `~/.video2doc/config.json`. No key is hardcoded or discovered from unrelated files.
- **All runtime files** (`*.mp4`, `*.mp3`, `raw/`, `output/`, etc.) are gitignored.

When you share this Skill repo, recipients get only the workflow logic. They
must supply any optional login state and API keys themselves.

---

## First-Run Guide

**When this skill is loaded for the first time (or the user hasn't indicated a
preference), ALWAYS present this guide before doing anything else:**

```
## 🎬 Video2Doc — 你的视频转文档助手

我可以帮你把抖音/小红书/B站/YouTube 视频转成结构化文档，两种模式可选：

| 模式 | 输出 | 适合 |
|------|------|------|
| 📝 **纯文稿**（默认） | 校正后的转录文本 + 逐段对照表 + 要点提炼 | 快速看内容，不需要图表 |
| 🎨 **深度分析** | 离线 HTML（分章 + SVG 图解 + 关键帧截图），支持一键导出 MD/DOCX/长截图 | 教程、评测、演示类，想留存查阅 |

在开始之前，需要先配置语音转录引擎。两种选择：
- ☁️ **云端（推荐）**：硅基流动免费 API，速度快、精度高、不占本机算力
- 💻 **本地**：优先 FunASR（Paraformer，中文更快更准、自带标点，~300MB）；Whisper 作为末位兜底（多语言，~1.5GB）

你已经有硅基流动 API Key 了吗？还是需要我引导注册？
```

**After presenting the guide, proceed to the transcription setup flow below.**

### Transcription Setup Flow

**Step 1: Check if an API key exists.** Check the `DOUBAO_API_KEY` and
`SILICONFLOW_API_KEY` environment variables, then `~/.video2doc/config.json`.
Never search memory files or unrelated project files for credentials.

**Step 2: If no key found, ask the user:**

```
语音转录需要硅基流动 API（免费，每月 10 小时）。你有 API Key 吗？

- 选项 A：我已有 Key → 直接提供给我
- 选项 B：帮我注册 → 打开 https://cloud.siliconflow.cn/i/pWcvZzOr 注册后在"API 密钥"页面创建一个 Key 给我
- 选项 C：用本地 FunASR（推荐离线）→ Paraformer 中文模型，GPU 上 6 分钟音频约 20s，自带标点
- 选项 D：用本地 Whisper → 多语言兜底，CPU 推理较慢，~1.5GB 模型
```

**Step 3: Store the key only with explicit user authorization.** The easiest
path for the user is the Web UI: `python webui.py` → **⚙️ 设置 → 🔑 API Key**
(get-key links, verify, save, clear; stored only in `~/.video2doc/config.json`,
never echoed back). Otherwise use the operating-system environment or write
`~/.video2doc/config.json` (UTF-8):
```
{"doubao_api_key": "...", "siliconflow_api_key": "...",
 "enrich_model": "deepseek-ai/DeepSeek-V3", "auto_update_tools": true}
```

**Step 4: Confirm ready.** Once key is stored or user chooses local, confirm and
proceed to accept video links.

**Default behavior**: If the user just says "分析这个视频" without specifying,
default to **纯文稿** mode. Only switch to deep analysis if they explicitly
ask for "深度分析" or "完整分析" or "生成 HTML".

Supported output modes:

1. **Clean Transcript** (`transcript.md`) — **DEFAULT**. Whisper transcription
   with manual correction of recognition errors, formatted as readable prose
   with a segment-by-segment correction table.
2. **Full HTML Document** (`index.html`) — self-contained offline page with
   chapter-by-chapter analysis, dynamic SVG diagrams, keyframe screenshots,
   and built-in export buttons (MD, DOCX, long screenshot).

---

## Workflow Overview

**Two branches** depending on output mode. Check which mode the user requested
before starting (default = transcript-only).

```
TRANSCRIPT ONLY (default):
  Phase 1 → Phase 2 → Phase 3 → Phase 4 → Output transcript.md → DONE

DEEP ANALYSIS (user asked for "深度分析"/"完整分析"/"HTML"):
  Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → Phase 8
```

**Phase summary**:
| Phase | Required for | Description |
|-------|-------------|-------------|
| 1. Acquire | Both | Platform subtitle/audio-first routes; full video only when needed |
| 2. Validate | Both | ffprobe audio/video/duration/integrity checks |
| 3. Transcribe | Both | Doubao bigmodel → TeleSpeechASR → local FunASR → local Whisper（可手动指定 engine） |
| 4. Structure | Both | Chapter breakdown, extract key points |
| 5. SVG | Deep only | Content-driven diagrams per chapter |
| 6. Keyframes | Deep only | UI/demo videos only; skip for talking-head |
| 7. HTML | Deep only | Single-page with export toolbar |
| 8. Verify | Deep only | Chrome headless screenshot + visual check |

**Failsafe**: In `engine=auto`, platform subtitles are tried before ASR. If all
four transcription engines fail, report the last classified error and keep the
download trace; embedded subtitles may still be extracted from a local video:
```bash
ffmpeg -i video.mp4 -map 0:s:0 output.srt
```

Proceed phase by phase. If any phase fails, diagnose and retry before moving on.

### 🚀 Parallel Processing Strategy (Batch Mode)

When processing **multiple videos**, run phases in parallel for maximum speed:

```
VIDEO 1: Phase 1 (download) → Phase 2 (audio) → Phase 3 (transcribe) → Phase 4 (output)
VIDEO 2: Phase 1 (download) → Phase 2 (audio) → Phase 3 (transcribe) → Phase 4 (output)
          └── start while video1 is transcribing ──┘
```

**Key rule**: Download + audio extraction of video N can start while video N-1
is being transcribed by TeleSpeechASR (cloud API, non-blocking). This
parallelizes the slowest phase (download is real-time for MediaRecorder).

**DO NOT parallelize within a single video** — transcription depends on audio,
which depends on download. But different videos are independent.

### ⏱️ Time Estimates

Public DASH/SSR downloads are normally faster than real time; cloud and local ASR
times vary by provider, CPU/GPU, and model. Only the final MediaRecorder fallback
is expected to take approximately the video duration. Do not promise fixed timing.

---

## Phase 1: Acquire the Smallest Required Media

Run `python video2doc.py "<URL_OR_SHARE_TEXT>"` (or call
`run_transcribe_pipeline()`) for normal work. It first asks for platform
subtitles (Bilibili/YouTube), then acquires the smallest validated audio asset
(Bilibili DASH audio, Douyin share MP4/signed audio, YouTube audio-only). It
does not download a full video merely to transcribe speech. Use
`--download` / `download_video()` only when the user asked for the video file.

For acquisition-only diagnostics, use the same implementation as the Web UI:

```bash
python scripts/acquire_media.py "<URL_OR_SHARE_TEXT>" --output-dir output/smoke --purpose audio
```

### Key requirements

- **No implicit browser state**: do not read live Chrome by default. Public
  Bilibili/Douyin routes are anonymous; configure Cookie input only when needed.
- **Media validation**: every success must pass ffprobe for required streams,
  positive duration, minimum size, and duration tolerance when metadata exists.
- **Classified fallback**: 412 is not retried identically; signed 403/410 is
  refreshed once; then switch to a route with a different failure mode.
- **Traceability**: `raw/download.trace.json` records strategy and timing without
  URL queries, cookies, API keys, or signed CDN URLs.

After download, read the `.info.json` file and extract:
- `title` — video title
- `uploader` / `uploader_id` — creator
- `description` — full description
- `tags` — tag list
- `duration` — total duration in seconds
- `thumbnail` — cover image path
- `chapters` — if present, use as initial chapter hints
- `multi_part` info — number of parts, individual part titles

---

## Phase 2: Audio Extraction and Validation

Extract audio directly as MP3 in one step (skip WAV intermediate). Validate
duration against ffprobe (no metadata JSON needed for most platforms).

Bilibili/Douyin audio-first routes already return a validated audio asset and
skip this extraction step. Run it only when Phase 1 produced a full video.

### Step 1: Extract Audio (One-Step)

```bash
ffmpeg -i "<VIDEO_FILE>" \
  -vn \
  -acodec libmp3lame \
  -q:a 2 \
  -y \
  "<OUTPUT>.mp3"
```

- `-vn` — discard video stream
- `-q:a 2` — VBR quality 2 (≈190 kbps, excellent for transcription)
- One step from video → MP3. No need to extract WAV first.
- For mono-only optimization (slightly smaller file): add `-ac 1`

### Step 2: Validate Duration

```bash
AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "<OUTPUT>.mp3")
VIDEO_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "<VIDEO_FILE>")

python3 -c "
a = float($AUDIO_DUR)
v = float($VIDEO_DUR)
diff = abs(a - v) / v
print(f'Audio: {a:.1f}s, Video: {v:.1f}s, Diff: {diff*100:.1f}%')
if diff > 0.05:
    print('WARNING: Duration discrepancy exceeds 5%')
"
```

Note: Use ffprobe on the video file directly instead of parsing .info.json
(yt-dlp doesn't produce .info.json for MediaRecorder downloads). This is both
faster and more reliable.

### Step 3: Decision

- If discrepancy ≤ 5%: proceed to transcription.
- If discrepancy > 5%: re-download with `--format bestaudio` and re-extract,
  or flag as anomaly in the final document with a warning note.
- If re-download still fails: mark the video as having audio issues and
  document the discrepancy in the HTML.

---

## Phase 3: Transcription

Two modes are available. Ask the user which they prefer, or default to
cloud API if a key is configured.

### Mode A: Cloud API (Recommended)

Fast, no local compute, no model download. Two providers (豆包首选，TeleSpeechASR 兜底)：

| Priority | Provider | Register / 获取 Key | Model | Notes |
|----------|----------|----------|-------|-------|
| **1st** | 豆包(火山引擎) | https://console.volcengine.com/speech/new/setting/apikeys | bigmodel 2.0 | 中文最准(实测 78% vs TeleSpeechASR 22%)、自带标点+ITN+词级时间戳；异步 submit+query（**首选**） |
| **2nd** | 硅基流动 | https://siliconflow.cn | TeleSpeechASR | 已验证稳定、sync API、no emoji（兜底） |

#### 2nd: 硅基流动 TeleSpeechASR（云端兜底，已验证）

Both use the same OpenAI-compatible API. Request format:

```bash
curl -s --max-time 60 --retry 3 --retry-delay 2 \
  https://api.siliconflow.cn/v1/audio/transcriptions \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@audio.mp3" \
  -F "model=TeleAI/TeleSpeechASR" \
  -F "response_format=verbose_json"
```

**Retry & error handling**:
- Connection timeout: 60s (`--max-time 60`)
- Auto-retry on failure: 3 times (`--retry 3 --retry-delay 2`)
- On HTTP 429 (rate limit): wait 30s then retry once
- On HTTP 401/403 (auth failure): report to user, fall to next tier
- On timeout: report and fall to next tier

#### 1st: 豆包录音文件识别大模型 2.0（首选云端）

**云端首选引擎**（一次项目样本的 9 个关键术语命中 7/9，TeleSpeechASR 为 2/9；该结果不是通用准确率或 WER 基准）。官方文档：
https://www.volcengine.com/docs/6561/1354868

**获取 X-Api-Key**：新版控制台 → API 密钥管理
https://console.volcengine.com/speech/new/setting/apikeys （创建/复制 X-Api-Key）。
存入 `~/.video2doc/config.json` 的 `doubao_api_key`，或设 `DOUBAO_API_KEY` 环境变量。

异步 API：`submit` 提交(X-Api-Sequence:-1) → 用同一 `X-Api-Request-Id` 轮询
`query` 取结果。`X-Api-Resource-Id` 用 `volc.seedasr.auc`（2.0）；1.0 用 `volc.bigasr.auc`。

**关键实现要点（对齐官方文档）**：
- **状态码在响应头 `X-Api-Status-Code`，不在 body**：`20000000` 成功 /
  `20000001` 处理中 / `20000002` 排队 / `20000003` 静音 / `4xxxxx`·`5xxxxx` 错误。
  轮询时按此判定：处理中/排队继续等，错误立即退出。`X-Tt-Logid` 记录用于排错。
- **音频字段**：官方文档**仅列 `audio.url`**（公网 URL）。`audio.data`(base64 内联)
  **实测可用但非文档字段**，本地音频靠它免公网托管；超大文件(<512M 上限)建议走 URL。
- 音频需 16kHz；`_transcribe_doubao` 用 ffmpeg 自动重采样到 16k 单声道 mp3。

```bash
# submit（body 大时用 -d @file 避免 ARG_MAX；pipeline 内部用 urllib 无此问题）
curl -L -X POST 'https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit' \
  -H 'Content-Type: application/json' \
  -H "x-api-key: $DOUBAO_API_KEY" \
  -H 'X-Api-Resource-Id: volc.seedasr.auc' \
  -H "X-Api-Request-Id: $REQ_ID" -H 'X-Api-Sequence: -1' \
  -d @body.json   # {"user":..,"audio":{"data":"<base64>","format":"mp3","rate":16000,...},"request":{"model_name":"bigmodel","enable_itn":true,"enable_punc":true,"show_utterances":true,...}}

# query（同一 REQ_ID 轮询，看响应头 X-Api-Status-Code=20000000 即成功）
curl -L -X POST 'https://openspeech.bytedance.com/api/v3/auc/bigmodel/query' \
  -H 'Content-Type: application/json' -H "x-api-key: $DOUBAO_API_KEY" \
  -H 'X-Api-Resource-Id: volc.seedasr.auc' -H "X-Api-Request-Id: $REQ_ID" -d '{}'
```

`webui/pipeline.py` 的 `_transcribe_doubao()` 已封装（用 urllib 而非 curl）：
统一 16k 单声道 MP3→base64→submit→按响应头状态码轮询(时限随音频时长伸缩，至少 3 分钟)→归一化 `{text, segments}`(ms→s)。
实测 6:43 音频 ~35s 完成，中文同音字识别优于 TeleSpeechASR。

The `verbose_json` response includes segment-level timestamps (`segments[].start`,
`segments[].end`, `segments[].text`). Convert this to SRT format for downstream
processing:

```python
for i, seg in enumerate(result["segments"], 1):
    start = seg["start"]
    end = seg["end"]
    text = seg["text"].strip()
    # Format as SRT entry
```

**API key storage** (2 explicit sources checked in priority order):

1. **Environment variable** `SILICONFLOW_API_KEY` (recommended, works in any Agent)
   ```bash
   export SILICONFLOW_API_KEY=sk-xxxxx
   ```
2. **Cross-Agent config** `~/.video2doc/config.json` (machine-wide, Agent-agnostic)
   ```json
   {"siliconflow_api_key": "sk-xxxxx"}
   ```
Scripts source `scripts/load_config.sh` to load the key from any of these sources.
If not found, go back to First-Run Guide → Transcription Setup Flow.

**Provider selection logic (ordered by priority)**:
1. **Doubao bigmodel 2.0** (cloud) — preferred cloud engine. Best Chinese accuracy
   (实测 78% vs TeleSpeechASR 22%), built-in punctuation + ITN + word timestamps.
   Async submit+query, base64 inline audio. Needs `DOUBAO_API_KEY`.
2. **TeleSpeechASR** (cloud) — fallback. Proven stable, sync API, no emoji noise.
   Needs `SILICONFLOW_API_KEY`.
3. **Local FunASR / Paraformer** — preferred offline engine. Faster + more accurate
   for Chinese than Whisper, with built-in VAD + punctuation + ITN. Use when no
   API key, no network, or quota exhausted. Implemented in `webui/pipeline.py`
   (`_transcribe_funasr`), auto-selects `cuda`/`cpu`.
4. **Local Whisper** — last resort. Only when FunASR is unavailable or content is
   non-Chinese (Whisper has broader language coverage). Implemented in
   `_transcribe_whisper`.

#### 引擎选择机制（默认自动 + 手动可选）

webui `transcribe(audio_path, job)` 按 `job.engine` 决定引擎（默认 `auto`）：

- **`auto`（默认）**：按上述 1→2→4→5 顺序自动降级。**首选额度耗尽/不稳定时静默
  切到下一级**，并在 `job.engine_note` 提示用户（如「已自动切换到 tele（doubao 不可用）」），
  前端结果区显示所用引擎徽章。无 Key 的云端引擎会被即时跳过。
- **手动指定**：`engine` 取 `doubao` / `tele` / `funasr` / `whisper` 时，仅用该引擎；
  失败时 `job.error` 提示「可切换其他引擎重试」。

**前端（index.html）**：在线转录 / 本地转录弹窗各有一个「引擎」下拉
（默认自动降级 / 豆包2.0首选 / TeleSpeechASR / 本地FunASR / 本地Whisper），
用户可手动指定；不选则走自动降级链路。

**额度耗尽 / 不稳定时的处理**：
- auto 模式：自动切下一级，结果区显示「🤖 tele · 已自动切换到 tele（doubao 不可用）」。
- 手动模式：失败提示「可切换其他引擎重试：引擎下拉选择」，用户改下拉重试即可。
- 豆包额度相关错误码（`45000131` 超提交上限 / `45000132` 超大小 / `55000031` 服务器繁忙 /
  401·403 鉴权失败）由 `_transcribe_doubao` 捕获并写入 `job.error`，便于识别。

### Mode B: Local FunASR (Preferred Offline)

Use this when the cloud API is unavailable (no key, no network, quota exhausted)
or the user explicitly prefers offline transcription. **FunASR (Paraformer) is
the preferred local engine** — faster and more accurate for Chinese than Whisper,
with built-in VAD + punctuation + ITN.

#### Prerequisites

```bash
pip install funasr   # also pulls torch (CUDA optional)
# First run downloads ~300MB of models to ~/.cache/modelscope/ (one-time)
# GPU: install CUDA-enabled torch for ~10x speedup
```

#### Hardware & Speed (RTF = process_time / audio_time)

| Hardware | RTF | 6-min audio |
|----------|-----|-------------|
| RTX 4060/5060 (8GB VRAM) | ~0.05 | ~20s |
| CPU only | ~0.3-1.0 | 1-3 min |

Paraformer is non-autoregressive — much faster than Whisper's autoregressive decoding.

#### Command

```python
from funasr import AutoModel

model = AutoModel(
    model="paraformer-zh",      # Chinese ASR
    vad_model="fsmn-vad",       # silence segmentation
    punc_model="ct-punc",       # auto punctuation
    device="cuda",              # or "cpu"
)
res = model.generate(input="audio.mp3", batch_size_s=300)
# res: list of {text, timestamp} per VAD segment
```

The pipeline (`webui/pipeline.py`, `_transcribe_funasr`) normalizes FunASR output
into the same `{text, segments}` shape as the cloud API, so downstream phases
(SRT export, chaptering) work unchanged. Device auto-selects `cuda` if available,
else `cpu`.

#### When to use FunASR vs Whisper

- **FunASR** — Chinese content, want speed + punctuation, GPU or decent CPU.
- **Whisper** — multilingual (non-Chinese) content, or FunASR fails to install.

### Mode C: Local Whisper (Last Resort)

Only use this if no cloud API key is available AND FunASR is not installed/fails,
or the user explicitly prefers Whisper (e.g. non-Chinese content).

#### Model Selection

- **Chinese content**: Use `turbo` model with `--language zh`.
- **English content**: Use `small.en` model for faster processing.
- **Mixed language**: Default to `turbo` with auto-detection.

#### Command

```bash
export PATH="/path/to/ffmpeg:$PATH"  # ffmpeg must be in PATH for Whisper
whisper "<AUDIO.mp3>" \
  --model turbo \
  --language zh \
  --output_format srt \
  --output_dir "<OUTPUT_DIR>" \
  --word_timestamps True
```

Note: `ffmpeg` must be in `PATH` when running Whisper. If using a custom
ffmpeg binary, export its directory before running.

### Post-Transcription Validation (All Modes)

Parse the SRT or JSON output and check:
1. Extract the `end` timestamp of the last segment.
2. Compare with the actual audio duration from ffprobe.
3. If the gap > 5 seconds, flag as potential truncation.

### Content-Enrich（文稿增强，自动）

转录后 `run_transcribe_pipeline` / `run_local_pipeline` 自动调用 `_enrich_transcript()`：
用 SiliconFlow chat API（`deepseek-ai/DeepSeek-V3`，复用 SILICONFLOW_API_KEY）给文稿补
**一句话摘要 + 3-5 条要点 + 3-5 个标签**，经 `_enrichment_block()` 渲染成 `## 📝 摘要` 块
写入 `transcript.md` 顶部（原文完整保留），JSON 也带 `enrichment` 字段。
**best-effort**：无 Key / 失败 / 文稿过短时静默跳过，不阻断主流程。参考 chubbyguan/chubbyskills 的 content-enrich。

---

## Phase 4: Content Structuring — Chapter Breakdown

Analyze the transcript and break the video into chapters based on its
**natural content structure**. Do NOT force a fixed template.

### Chapter Identification Principles

1. **Topic shifts** — new subject, new phase, new scene
2. **Speaker changes** — different person speaking
3. **Action phases** — setup → execution → result
4. **Natural breaks** — pauses, transitions, "接下来"/"next" cues

### Per-Chapter Content Extraction

For each chapter, extract:

| Element | Description |
|---------|-------------|
| **问题 (Problem)** | What question or challenge is being addressed? |
| **陷阱 (Traps/Pitfalls)** | Common mistakes or gotchas mentioned |
| **步骤 (Steps)** | Actionable steps or procedures |
| **结论 (Conclusion)** | Key takeaway or result |
| **关键引用 (Key Quotes)** | Verbatim important sentences with timestamps |
| **视觉锚点 (Visual Anchors)** | Description of what's shown on screen at key moments |

### Timestamp Format

Use `HH:MM:SS` format with a jump-back link:

```html
<a href="#" onclick="seekTo(125);return false">02:05</a>
```

Where `seekTo(n)` seeks the embedded audio or video element to second `n`.

### Writing Style

- **Vernacular short sentences** (白话短句) — natural spoken Chinese, not
  academic prose.
- Active voice, direct language.
- Each chapter should feel like a friend explaining the key points.

---

## Phase 5: SVG Diagram Generation

Generate dynamic, content-driven SVG diagrams for EACH chapter. Every diagram
must be derived from the chapter's real content, not decorative or templated.

### Diagram Type Selection

| Content Type | SVG Type | Visual Elements |
|-------------|----------|-----------------|
| Process / workflow | Flowchart / step path | Boxes, arrows, numbered steps |
| Concepts / architecture | Relationship / layer diagram | Hierarchical boxes, connecting lines |
| Temporal changes | Timeline | Horizontal axis, markers, labels |
| Comparison | Matrix / side-by-side | Two-column layout, checkmarks/X marks |
| Risks / pitfalls | Checklist / decision tree | Branching paths, warning icons |
| Data / metrics | Simplified chart | Bars, lines, labeled axes |
| Cause-effect | Causal chain | Linked nodes, directional arrows |

### SVG Quality Rules

1. **Content-derived**: Every keyword, label, and arrow must come from the
   chapter transcript. No generic "Step 1, Step 2, Step 3".
2. **Labeled**: Add clear text labels for all nodes, arrows, and sections.
3. **Self-contained**: Inline the SVG directly in the HTML. No external files.
4. **Readable**: Use adequate font sizes, high contrast colors, and clear
   spacing. The SVG should be legible when viewed inline at ~680px width.
5. **Annotated**: Add a `<figcaption>` below each SVG with the label `「图解」`
   to distinguish it from screenshots.

### Example Pattern

```html
<figure class="diagram">
  <svg viewBox="0 0 680 320" xmlns="http://www.w3.org/2000/svg">
    <!-- Content-driven shapes, labels, arrows -->
  </svg>
  <figcaption>「图解」第三章：用户认证流程</figcaption>
</figure>
```

---

## Phase 6: Keyframe Extraction (UI/Operation Videos Only)

For videos that show user interfaces (canvas, console, editor, document),
extract a representative frame from each chapter. Skip this phase for
pure talking-head or lecture-style videos.

**Skip criteria** (skip Phase 6 if ANY of these are true):
- Video is a 口播 / 单人对着镜头说话（no UI shown）
- Screen content never changes significantly
- The transcript contains no visual descriptions（"大家看这里","打开这个"）
- Video is < 60 seconds (too short for meaningful frame extraction)

### Step 1: Identify Key Timestamps

For each chapter, scan the transcript for visual activity:
- UI changes (new panel, dialog, result)
- Code execution output
- Visual demonstrations
- Before/after comparisons

Pick the single most informative, clearest frame in that chapter.

### Step 2: Parallel Shard Extraction (Long Videos)

For videos > 10 minutes, split into shards for parallel extraction:

```bash
# Extract candidate frames at 2fps across the chapter's time range
ffmpeg -ss <CHAPTER_START> -to <CHAPTER_END> \
  -i "<VIDEO>" \
  -vf "fps=2" \
  -q:v 3 \
  "/tmp/frames/ch3_%04d.jpg"
```

Review the candidates and select the best one. Note its exact timestamp.

### Step 3: Precise Frame Export

Once the exact timestamp is determined:

```bash
ffmpeg -ss <EXACT_SECONDS> -i "<VIDEO>" \
  -vframes 1 \
  -q:v 1 \
  "<OUTPUT_DIR>/ch<NN>_<label>_<seconds>s.jpg"
```

- `-q:v 1` — highest quality JPEG
- Filename pattern: `ch03_login_flow_214s.jpg` (chapter number, short label,
  timestamp in seconds)
- Place screenshots in an `images/` subdirectory relative to the HTML file.

### Output Layout Convention

Each chapter renders as:

```
<!-- Chapter Section -->
<section class="chapter" id="ch3">
  <!-- 1. Text analysis -->
  <div class="content">...</div>

  <!-- 2. SVG diagram -->
  <figure class="diagram"> <svg>...</svg> </figure>

  <!-- 3. Screenshot (UI videos only) -->
  <figure class="screenshot">
    <img src="images/ch03_login_214s.jpg" alt="...">
    <figcaption>「视频时间戳 03:34」登录界面关键帧</figcaption>
  </figure>
</section>
```

Screenshots use relative paths for offline portability. Annotate each
screenshot with `「视频时间戳 HH:MM:SS」` to distinguish from SVG diagrams.

---

## Phase 7: HTML Document Composition

Generate a single, self-contained HTML file.

### Structure

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>【视频深度分析】{标题} — {UP主}</title>
  <style>
    /* All CSS inline — see styling guidelines below */
    /* Must include @media print rules for export */
  </style>
</head>
<body>
  <div id="export-toolbar">  <!-- Sticky export buttons: MD / DOCX / 长截图 --> </div>
  <header>  <!-- Video metadata: title, uploader, duration, tags --> </header>
  <nav>     <!-- Chapter TOC with jump links -->                    </nav>
  <main>
    <section class="chapter" id="ch1"> ... </section>
    <section class="chapter" id="ch2"> ... </section>
    <!-- ... -->
  </main>
  <footer>  <!-- Generation timestamp, tool versions -->            </footer>
  <script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
  <script>
    /* Export functions: exportMD(), exportDOCX(), exportScreenshot() */
  </script>
</body>
</html>
```

### Styling Guidelines

- **Clean and functional** — no excessive decorations, no Aurora/gradient
  themes. The user prefers restrained, minimalist design.
- **High readability**: 16px base font, 1.7 line-height, adequate paragraph
  spacing, max-width ~800px for main content.
- **Color scheme**: Light background (#fafafa or white), dark text (#1a1a1a),
  accent color for links and chapter markers (#2563eb or similar).
- **Responsive**: The page should work on both desktop and mobile.
- **Print-friendly**: Include `@media print` styles.
- **SVG styling**: Use consistent stroke/fill colors that match the page
  palette. All SVGs should have a subtle border and background.

### Chapter TOC

Generate a sticky or collapsible table of contents with anchor links to each
chapter section.

### Export Toolbar

Every deep-analysis HTML page MUST include a sticky export toolbar at the
top-right corner with the following buttons:

| Button | Action | Implementation |
|--------|--------|----------------|
| 📄 **导出 MD** | Download content as Markdown | `Blob` + `<a download>` with all chapter text and image paths |
| 📝 **导出 DOCX** | Download as Word document | Generate a simple HTML→DOCX (Word can open `.doc` with HTML content) |
| 📸 **长截图** | Capture full-page PNG | Use `html2canvas` or browser's built-in `window.print()` with `@media print` CSS, or trigger a `Ctrl+P` dialog |

**Implementation pattern** for the toolbar:

```html
<div id="export-toolbar" style="position:fixed;top:16px;right:16px;z-index:9999;
  background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;
  box-shadow:0 4px 12px rgba(0,0,0,0.08);display:flex;gap:8px;">
  <button onclick="exportMD()" title="导出 Markdown">📄 MD</button>
  <button onclick="exportDOCX()" title="导出 Word 文档">📝 DOCX</button>
  <button onclick="exportScreenshot()" title="导出长截图" style="background:#2563eb;color:#fff;">📸 长截图</button>
</div>
```

**Export MD**: Collect all `<section class="chapter">` content, convert to
Markdown format preserving headings, timestamps, figure captions.

**Export DOCX**: Wrap the content in a minimal HTML document that Microsoft
Word can open natively (Word opens `.doc` files with HTML content). Use
`application/msword` MIME type for download.

**Long screenshot**: Use `html2canvas` CDN to capture the full page. If
html2canvas is unavailable, fall back to `window.print()` with dedicated
`@media print` styles that produce a clean PDF/A4 output.

**@media print rules** required in the CSS:
```css
@media print {
  #export-toolbar { display: none !important; }
  nav { display: none !important; }
  .chapter { break-inside: avoid; }
  body { font-size: 12pt; color: #000; }
  a { color: #000; text-decoration: none; }
}
```

---

## Phase 8: Verification (Deep Analysis Only)

After generating the HTML and all supporting files, verify the output.

**If Chrome is available**, follow the steps below. **If Chrome is not
available**, skip to the manual checklist at the end of this section.

### Step 1: Chrome Headless Full-Page Screenshot

```bash
# Using Chrome/Chromium headless
<CHROME_PATH> --headless --disable-gpu \
  --screenshot="<OUTPUT>.png" \
  --window-size=1280,900 \
  --virtual-time-budget=10000 \
  "file://<ABSOLUTE_PATH_TO_HTML>"
```

The `--virtual-time-budget` allows the page to fully render (including fonts,
images, and layout) before capture.

### Step 2: Visual Inspection

Read the PNG screenshot and check:
1. **Rendering**: All text visible, no garbled characters, proper font fallback.
2. **Overlap**: No overlapping elements, proper spacing between chapters.
3. **Blanks**: No large empty areas or missing content sections.
4. **SVGs**: Every SVG diagram renders correctly — no broken shapes, all text
   labels visible, proper sizing.
5. **Screenshots**: Every keyframe image loads and displays, no broken `img` tags.
6. **Layout**: Chapters follow the 正文 → 图解 → 截图 order correctly.

### Step 3: Cropping with Overlap

For long pages, crop into manageable slices while preserving readability:

```bash
ffmpeg -i "<FULL_PAGE.png>" \
  -vf "crop=1280:${SLICE_HEIGHT}:0:${Y_OFFSET}" \
  "<SLICE_OUTPUT>.png"
```

- Each slice should overlap the previous by ~100px to avoid cutting through
  titles or section headers.
- Calculate crop windows such that:
  - `slice_n_y = max(0, n * effective_height - n * 100)`
  - Where `effective_height = slice_height - 100` (the 100px overlap).

### Step 4: Fix Issues

If any rendering or layout issues are found, fix the HTML/CSS and re-verify
until the output is clean.

### No-Chrome Fallback Checklist

If Chrome is unavailable, manually open `index.html` in any browser and check:
- [ ] Page loads without errors (F12 Console — no red errors)
- [ ] All chapter headings visible
- [ ] Export buttons work (MD / DOCX / 长截图)
- [ ] SVG diagrams render (not broken shapes)
- [ ] Screenshot images load (no broken image icons)
- [ ] Responsive: resize browser window to mobile width — layout still readable

---

## File Organization

For each video analysis, create a project directory:

```
{project_dir}/
├── index.html              # The final self-contained HTML document
├── images/                 # Extracted keyframe screenshots
│   ├── ch01_intro_45s.jpg
│   ├── ch02_setup_120s.jpg
│   └── ...
├── raw/                    # Raw downloaded assets (not for distribution)
│   ├── *.info.json
│   ├── *.mp4
│   ├── *.mp3
│   ├── *.srt
│   └── *.jpg (thumbnail)
└── verify/                 # Verification outputs
    ├── full_page.png
    ├── slice_01.png
    └── ...
```

---

## Transcript-Only Output Mode

When the user specifically asks for just a transcript/文稿 (without SVG diagrams
or keyframes), generate `transcript.md` with these sections:

1. **YAML frontmatter** — title, source, uploader, duration, generation info.
2. **Full corrected transcript** — a single flowing prose section with all
   Whisper recognition errors manually corrected. Read naturally as a paragraph.
3. **Segment comparison table** — a markdown table showing each SRT segment's
   original Whisper output side-by-side with the corrected version. This gives
   the user full transparency on what Whisper got wrong.
4. **Key points summary** — a bullet-point summary of the video's main
   arguments, data points, and conclusions.

Correction rules for Chinese transcription:
- "满车" → "版车", "文庚" → "领克", "五线自出" → "无限次"
- "潜意" → "配置", "不索节" → "不妥协", "员员" → "一员"
- Model numbers: "077T" → "07GT"
- Use context to distinguish homophones (e.g., "链接" vs "评论")

---

## Platform-Specific Notes

### Bilibili (B站)

- **转文稿**：`engine=auto` 先尝试平台 SRT；无字幕时走公共 DASH 音轨，
  仅当公共 API 不适用时才用 yt-dlp `bestaudio`。
- **纯视频**：显式 Cookie yt-dlp（登录画质）→ 匿名公共 DASH 音视频合并 →
  yt-dlp 匿名兜底。公开内容通常不需要 Cookie。
- HTTP 412 是当前请求被风控拒绝时的常见表现；记录分类错误后切换公共 API，
  不原样盲重试。浏览器已登录不等于 Python 进程自动获得 Cookie。

### Douyin (抖音)

转文稿默认走：移动 SSR MP4（免浏览器）→ 隔离 Playwright 签名音轨 → 显式
Cookie yt-dlp → MediaRecorder。纯视频默认走：移动 SSR MP4 → 隔离
Playwright DASH → 显式 Cookie yt-dlp → MediaRecorder。浏览器登录态不会被隐式读取。

#### 移动 SSR 分享接口（纯视频与转录的首选路径）

`webui/douyin.py` 的 `acquire_muxed()` 已实现：
1. 提取 video id（短链跟重定向，`/video/(\d+)`）
2. 抓 `https://www.iesdouyin.com/share/video/<id>`（**移动端 iPhone UA**）
3. 正则提取 `window._ROUTER_DATA` → `loaderData["video_(id)/page"]["videoInfoRes"]["item_list"][0]`
4. 取 `video.play_addr.url_list[0]`，`playwm`→`play` 去水印
5. curl 下载（移动端 UA + `Referer: https://www.douyin.com/`），顺带拿视频标题

```bash
curl -s -L -H "User-Agent: <iPhone UA>" "https://www.iesdouyin.com/share/video/<vid>" \
  | grep -oP 'window\._ROUTER_DATA\s*=\s*\K.*?(?=</script>)'  # 提取 JSON
# 拿到 play_addr 后：
curl -s -L -o video.mp4 -H "User-Agent: <iPhone UA>" -H "Referer: https://www.douyin.com/" "<play_url>"
```

实测：两个抖音视频（2:13 / 10:41）均一次成功，下载的视频**带音轨**，配合豆包转录 11.7s / 55.6s 出文稿。

#### v0.5 历史手动兜底说明（当前 pipeline 不执行以下命令）

抖音反爬强，下列方法需要 cookie 或浏览器自动化，作为 iesdouyin 失败后的退路：

#### ⚠️ Gold Rules for Douyin Download (兜底层)

1. **NEVER reuse a browser session** after it's been flagged (captcha page).
   Always `playwright-cli close` and `open` fresh for each video.
2. **Load cookies FIRST, then navigate.** Do NOT navigate before cookies are set.
   Navigating without cookies triggers bot detection that persists for the session.
3. **ONE video per browser session.** After download, immediately close the browser.
4. **Detect captcha early.** If page title contains "验证码", abort immediately and
   retry with a fresh session after 30s delay.

#### 历史手动 Download Strategy（仅供排障背景，不代表当前顺序）

**Tier 2: MediaRecorder (most reliable, ~video_duration seconds)**

This approach bypasses ALL bot detection because it records the video as it plays:
```bash
# Step 1: Set up cookies via state-load (load BEFORE navigating)
playwright-cli open --browser=chrome
playwright-cli state-load playwright_state.json

# Step 2: Navigate to video page
playwright-cli goto "https://www.douyin.com/video/VIDEO_ID"

# Step 3: Check for captcha — if page title is "验证码中间页", ABORT + retry
# Step 4: Use eval to start MediaRecorder
playwright-cli eval "
(async () => {
  const video = document.querySelector('video');
  if (!video) return 'NO_VIDEO';
  video.muted = false;
  video.play();
  const stream = video.captureStream();
  const chunks = [];
  const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
  recorder.ondataavailable = e => chunks.push(e.data);
  recorder.onstop = () => {
    const blob = new Blob(chunks, { type: 'video/webm' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'video.webm';
    a.click();
  };
  recorder.start();
  await new Promise(r => video.onended = r);
  recorder.stop();
  await new Promise(r => setTimeout(r, 500));
  return 'DONE';
})()
"

# Step 5: Copy downloaded file
cp .playwright-cli/video.webm vN/raw/video.mp4
```

**Tier 3: page.route interception (faster, but browser fingerprint must match)**

If MediaRecorder is too slow (video > 3min), try intercepting the video URL
from network requests:
```bash
playwright-cli eval "
  window.__videoUrl = null;
  // Scan existing script tags for video URLs
  document.querySelectorAll('script').forEach(s => {
    if (s.textContent) {
      const m = s.textContent.match(/https?:\\/\\/[^\\\"\\\\s]+\\\\.(mp4|m3u8)[^\\\"\\\\s]*/);
      if (m) window.__videoUrl = m[0];
    }
  });
  window.__videoUrl || document.querySelector('video')?.src || 'NOT_FOUND'
"
# Then download with curl (cookies MUST match)
```

**Tier 4: yt-dlp (rarely works for Douyin)**
Only try if both Tier 1 and Tier 2 fail. Known failure: "Fresh cookies needed",
"Failed to parse JSON".

#### Speed Tips for Douyin

- **MediaRecorder** = real-time (video duration = download time). For a 60s video,
  this is 60s. Accept this — it's the price of reliability.
- **Batch multiple videos**: download video2 while transcribing video1 (parallel).
- **Skip unnecessary wait**: replace `sleep(5)` with `page.waitForSelector('video')`.
- **Short videos (< 2min)**: MediaRecorder is fast enough, no need for Tier 2.

#### Cookie Management

- Export fresh cookies.txt before each session. Douyin cookies expire quickly (1-2 hours).
- Convert cookies.txt to Playwright state JSON with this Python snippet:
  ```python
  import json
  cookies = []
  with open('cookies.txt') as f:
      for line in f:
          if line.startswith('#') or not line.strip(): continue
          parts = line.strip().split('\t')
          if len(parts) >= 7:
              cookies.append({'name': parts[5], 'value': parts[6],
                  'domain': parts[0], 'path': parts[2],
                  'secure': parts[3]=='TRUE', 'httpOnly': False, 'sameSite': 'Lax'})
  json.dump({'cookies': cookies}, open('playwright_state.json', 'w'))
  ```
- **Important**: Cookies MUST have `sameSite: 'Lax'` — without it, Playwright
  may not send cookies correctly, triggering captcha.

#### Error Recovery

| Error | Action |
|-------|--------|
| Page title = "验证码中间页" | Close browser, wait 30s, new session, retry (max 3x) |
| `NO_VIDEO` from eval | Check if page loaded correctly; try longer wait |
| MediaRecorder produces 0-byte file | Video element may be DRM-protected — skip this video |
| yt-dlp "Fresh cookies needed" | Cookies expired — need re-export from browser |

### Xiaohongshu (小红书)

- **首选：`__INITIAL_STATE__` 解析（移动端 UA，cookie 可选）**——`webui/pipeline.py` 的
  `_download_xhs_initial_state()` 已实现：移动端 iPhone UA + Referer，括号配平提取
  `window.__INITIAL_STATE__`，递归定位 note，从 `video.media.stream.{h264,h265,h266,av1}[].masterUrl`
  提直链下载。可选 `XHS_COOKIE` 环境变量提高成功率（风控严时需要）。参考 chubbyguan/chubbyskills。
- **兜底：yt-dlp + cookie**——`__INITIAL_STATE__` 失败才走；优先使用显式配置的 cookies.txt，
  不要默认读取正在运行的 Chrome。
- **Referer header is critical**: always add `--add-header "Referer:https://www.xiaohongshu.com/"`.
- **M3U8 streams**: Some Xiaohongshu videos use HLS/M3U8；yt-dlp 原生支持，可加 `--concurrent-fragments 5`。
- **风控检测**：响应含「请通过小红书」或 `verify` 即被拦，提示设 `XHS_COOKIE`。
- Short video format (< 5 min) — skip parallel shard extraction.

### YouTube

- `yt-dlp` works without cookies for public videos.
- Chapters: YouTube chapters are extracted automatically by yt-dlp into
  `.info.json`. Prefer these as initial chapter boundaries.

---

## Prerequisites

| Tool | Purpose | Required |
|------|---------|----------|
| `yt-dlp` | Video download | Always |
| `ffmpeg` + `ffprobe` | Audio/video processing | Always |
| 豆包(火山) API Key | Cloud transcription (preferred, bigmodel 2.0) | Cloud mode |
| 硅基流动 API Key | Cloud transcription (fallback) | Cloud mode |
| `funasr` | Local transcription (preferred offline, Chinese) | Offline mode |
| `openai-whisper` | Local transcription (last resort, multilingual) | Offline fallback |
| Python Playwright | Douyin signed media capture and MediaRecorder fallback | Douyin scenarios |
| Chrome/Chromium | Headless verification | Optional (deep analysis mode) |

One-command check:
```bash
bash scripts/check_setup.sh
```

For cloud API, source `scripts/load_config.sh` (environment variable → `~/.video2doc/config.json`).

---

## CLI & Scripts

### Entry Point: `video2doc.py`

The CLI runs exactly the same pipeline as the Web UI (subtitle-first, direct
platform audio, engine fallback, privacy mode, multi-format export). Prefer it
over hand-written download/ASR commands; `./video2doc.sh` is an equivalent
Bash wrapper.

```bash
# Link or pasted share text → transcript (output/<job id>/transcript.md)
python video2doc.py "https://v.douyin.com/xxxx"

# Batch mode (one link or local file per line in links.txt)
python video2doc.py --batch links.txt --format srt,md

# Local file, on-device ASR only (FunASR/Whisper; no cloud calls)
python video2doc.py meeting.m4a --local-only --format all

# Download the video only; machine-readable result on stdout
python video2doc.py --download "https://youtu.be/xxxx" --json

# Lecture / tutorial → illustrated transcript (one frame per slide + its exact
# narration, HTML + Markdown/images zip). Pass names and terms as hotwords.
python video2doc.py "<URL>" --illustrated --format all --hotwords "人名,术语"
```

Recurring recognition errors can be fixed at export time with
`--replace "错词=>正确词"` (repeatable) or the global rules in Settings.
To publish an illustrated transcript to a Lark/Feishu doc (requires a logged-in
`lark-cli`): `python scripts/publish_lark.py --job output/<id> --new "标题"` or
`--doc <url> [--after-block <block_id>]`; reruns resume from the checkpoint.

Progress is printed to stderr; with `--json`, stdout contains only the result
JSON. For learning material, prefer `--illustrated`; then proofread proper
nouns against an authoritative source (official pages / articles) before
publishing.

### Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/check_setup.sh` | Environment health check (bash, macOS/Linux/Git Bash) |
| `scripts/check_setup.py` | Cross-platform environment check (Python, Windows/macOS/Linux) |
| `scripts/platform_utils.py` | Cross-platform executable discovery |
| `scripts/python_cmd.sh` | Resolve a real Python 3.10+ command for shell entry points |
| `scripts/build_release.py` | Reproducible ZIP + SHA-256 + manifest release builder |
| `scripts/load_config.sh` | Cross-Agent API key loader (source to get `$SILICONFLOW_API_KEY`) |
| `scripts/export_formats.py` | Convert TeleSpeechASR output → SRT/TXT/JSON/MD |
| `scripts/apply_corrections.py` | Apply `references/corrections.json` rules to fix ASR errors |
| `scripts/download_video.sh` | yt-dlp download + metadata |
| `scripts/extract_audio.sh` | Audio extraction + ffprobe validation |
| `scripts/transcribe.sh` | Whisper transcription + validation |
| `scripts/extract_frames.sh` | Parallel keyframe extraction |
| `scripts/verify_html.py` | Chrome headless HTML verification |

---

## Versioning & Release

This skill follows [Semantic Versioning](https://semver.org/). Releases are
packaged as `Video2Doc-v{MAJOR}.{MINOR}.{PATCH}.zip` and published to GitHub.

**Release workflow** (replace `X.Y.Z` with the version declared in CHANGELOG):
```bash
python -m unittest discover -s tests -p "test_*.py"
# Commit through the normal review flow, push, and wait for Windows/macOS CI.
python scripts/build_release.py --version X.Y.Z --output-dir dist
git tag -a vX.Y.Z -m "Video2Doc vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z dist/Video2Doc-vX.Y.Z.zip \
  dist/Video2Doc-vX.Y.Z.zip.sha256 --verify-tag
```

After releasing, the agent should confirm:
- [ ] Windows/macOS CI passed for the release commit
- [ ] Tag pushed to GitHub
- [ ] Release created with both ZIP and `.zip.sha256` assets
- [ ] ZIP manifest/version/executable modes verified
- [ ] CHANGELOG.md updated
