---
name: Video2Doc
description: "Video2Doc converts videos (Douyin, Xiaohongshu, Bilibili, YouTube) into structured documentation — a clean transcript by default, with optional deep analysis mode. Handles downloading (yt-dlp + Playwright MediaRecorder with anti-bot strategy), one-step audio extraction, 3-tier transcription (TeleSpeechASR cloud API → SenseVoiceSmall → local Whisper), content chaptering, SVG generation, and parallel batch processing for multiple videos."
agent_created: true
---

# Video2Doc — 视频转文档

Convert any video (Douyin/Xiaohongshu/Bilibili/YouTube) into structured documentation.

---

## 🔒 Security & Privacy

**This Skill does NOT ship with any cookies, API keys, or credentials.**

- **Cookies**: Douyin/XHS require cookies for download. Each user must provide
  their own `cookies.txt` exported from their browser. The `.gitignore` blocks
  `cookies.txt`, `playwright_state.json`, and all runtime media files from
  ever being committed.
- **API Keys**: SiliconFlow key is stored in `~/.workbuddy/MEMORY.md` (local, per-user,
  never committed). The SKILL.md only references the key via lookup — no key is
  hardcoded.
- **All runtime files** (`*.mp4`, `*.mp3`, `raw/`, `output/`, etc.) are gitignored.

When you share this Skill repo, recipients get only the workflow logic. They
must supply their own cookies and API keys.

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
- 💻 **本地**：使用 Whisper 在本机运行，完全离线，但需下载 1.5GB 模型

你已经有硅基流动 API Key 了吗？还是需要我引导注册？
```

**After presenting the guide, proceed to the transcription setup flow below.**

### Transcription Setup Flow

**Step 1: Check if API key exists.** Look in `~/.workbuddy/MEMORY.md` for
`SILICONFLOW_API_KEY`. If found, skip to "ready" state.

**Step 2: If no key found, ask the user:**

```
语音转录需要硅基流动 API（免费，每月 10 小时）。你有 API Key 吗？

- 选项 A：我已有 Key → 直接提供给我
- 选项 B：帮我注册 → 打开 https://cloud.siliconflow.cn/i/pWcvZzOr 注册后在"API 密钥"页面创建一个 Key 给我
- 选项 C：用本地 Whisper → 大模型下载 + CPU 推理（较慢但完全离线）
```

**Step 3: Store the key.** When the user provides a key, store it:
```
→ Edit ~/.workbuddy/MEMORY.md, append:
  ## SiliconFlow API Key
  SILICONFLOW_API_KEY: sk-xxxxxxxxxxxx
  (Auto-configured by Video2Doc skill)
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
| 1. Download | Both | yt-dlp + cookies + metadata |
| 2. Audio | Both | Extract MP3 + ffprobe validate (±5%) |
| 3. Transcribe | Both | TeleSpeechASR → SenseVoiceSmall → local Whisper |
| 4. Structure | Both | Chapter breakdown, extract key points |
| 5. SVG | Deep only | Content-driven diagrams per chapter |
| 6. Keyframes | Deep only | UI/demo videos only; skip for talking-head |
| 7. HTML | Deep only | Single-page with export toolbar |
| 8. Verify | Deep only | Chrome headless screenshot + visual check |

**Failsafe**: If Phase 3 (transcription) fails at all 3 tiers with no API key
and no local Whisper, fall back to embedded subtitles from `--write-subs`
(Phase 1). Extract SRT directly from the video file:
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

### ⏱️ Time Estimates (per video, single-threaded)

| Video Length | Download (MediaRecorder) | Audio Extract | Transcribe (TeleSpeechASR) | Total |
|-------------|--------------------------|---------------|---------------------------|-------|
| 1 min | ~60s | ~3s | ~5s | **~70s** |
| 3 min | ~180s | ~5s | ~8s | **~195s** |
| 10 min | ~600s | ~10s | ~15s | **~625s** |

With parallel batch processing (N videos): ~60s + N × 8s (transcription overlaps download).

---

## Phase 1: Download Video with Full Metadata

Use `yt-dlp` with cookies for platforms that require authentication (Bilibili
logged-in quality, etc.).

### Command Template

```bash
yt-dlp \
  --cookies-from-browser chrome \
  --add-header "Referer:https://www.xiaohongshu.com/" \  # required for Xiaohongshu
  --write-info-json \
  --write-thumbnail \
  --write-subs \
  --sub-langs all \
  --embed-metadata \
  --output "%(title).200s-%(id)s.%(ext)s" \
  "<VIDEO_URL>"
```

### Key requirements

- **Cookies**: Use `--cookies-from-browser chrome` (or `firefox`/`edge`). If
  that fails, fall back to `--cookies /path/to/cookies.txt`.
- **Metadata**: The `--write-info-json` flag produces a `.info.json` file
  containing title, uploader, description, tags, duration, chapters, and
  multi-part (分P) info. Parse this file to extract all metadata.
- **Platform-specific**: For Bilibili, add `--parse-metadata "description:%(description)s"`.
  For Douyin and Xiaohongshu, cookies are mandatory.
- **Output naming**: Keep the video ID in the filename for traceability.

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

Fast, no local compute, no model download. Two tiers:

| Priority | Provider | Register | Free Tier | Model | Notes |
|----------|----------|----------|-----------|-------|-------|
| **1st** | 硅基流动 | https://siliconflow.cn | 10h/month | TeleSpeechASR | Chinese-optimized, no emoji, best accuracy |
| **2nd** | 硅基流动 | https://siliconflow.cn | 10h/month | SenseVoiceSmall | Has emoji noise, post-process required |

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

**SenseVoiceSmall emoji issue**: The `FunAudioLLM/SenseVoiceSmall` model
outputs emoji for audio events and emotions (🎼=BGM, 😡=angry, 😊=happy).
SiliconFlow's API does not expose a `use_emoji` parameter to disable this.
**Always post-process** SenseVoiceSmall output with `emoji.replace_emoji()`:

```python
from emoji import replace_emoji
cleaned = replace_emoji(raw_text, replace="")
```

**Recommendation**: Prefer `TeleAI/TeleSpeechASR` for Chinese — it has better
accuracy AND doesn't output emoji. Only use SenseVoiceSmall for comparison.

**API key storage**: Stored in `~/.workbuddy/MEMORY.md` as `SILICONFLOW_API_KEY`.
If not found, go back to First-Run Guide → Transcription Setup Flow.

**Provider selection logic (ordered by priority)**:
1. **TeleSpeechASR** — use for all Chinese content. Best accuracy, no emoji noise.
2. **SenseVoiceSmall** — fallback if TeleSpeechASR fails or for A/B comparison.
   Always post-process with `emoji.replace_emoji()` to strip emoji.
3. **Local Whisper** — last resort when no API key is configured, or user
   explicitly prefers offline transcription (privacy, no network).

### Mode B: Local Whisper (Fallback)

Only use this if no cloud API key is available, or the user explicitly prefers
local transcription (privacy, no network, etc.).

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

### Post-Transcription Validation (Both Modes)

Parse the SRT or JSON output and check:
1. Extract the `end` timestamp of the last segment.
2. Compare with the actual audio duration from ffprobe.
3. If the gap > 5 seconds, flag as potential truncation.

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

- Requires cookies for 1080p+ quality. Use `--cookies-from-browser chrome`.
- Multi-part videos (分P): `yt-dlp` downloads all parts by default. Use
  `--playlist-items 1` to download a specific part.
- Subtitles (弹幕): use `--write-subs --sub-langs all` to capture CC
  subtitles; Danmaku (弹幕) is not supported by yt-dlp directly.

### Douyin (抖音) — CRITICAL: Anti-Bot Strategy

Douyin aggressively detects headless browsers. The following strategy is
**battle-tested** across multiple downloads.

#### ⚠️ Gold Rules for Douyin Download

1. **NEVER reuse a browser session** after it's been flagged (captcha page).
   Always `playwright-cli close` and `open` fresh for each video.
2. **Load cookies FIRST, then navigate.** Do NOT navigate before cookies are set.
   Navigating without cookies triggers bot detection that persists for the session.
3. **ONE video per browser session.** After download, immediately close the browser.
4. **Detect captcha early.** If page title contains "验证码", abort immediately and
   retry with a fresh session after 30s delay.

#### Download Strategy (ordered by reliability)

**Tier 1: MediaRecorder (most reliable, ~video_duration seconds)**

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

**Tier 2: page.route interception (faster, but browser fingerprint must match)**

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

**Tier 3: yt-dlp (rarely works for Douyin)**
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

- Cookies are mandatory. Use `--cookies-from-browser chrome` or a cookies.txt.
- **Referer header is critical**: always add `--add-header "Referer:https://www.xiaohongshu.com/"`.
- **M3U8 streams**: Many Xiaohongshu videos use HLS/M3U8 segmented streaming.
  yt-dlp handles this natively but may need `--concurrent-fragments 5` for speed.
- **Watermark**: Default download includes watermark. To get watermark-free,
  look for the `source` or `origin` video stream in the page HTML.
- **Playwright fallback**: If yt-dlp fails (common due to API changes):
  1. Open the video page in Playwright with cookies injected
  2. Wait for video element to load
  3. Extract `document.querySelector('video').src`
  4. Download with curl + cookies + Referer header
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
| `emoji` (Python) | SenseVoiceSmall text cleanup | If using SenseVoiceSmall |
| 硅基流动 API Key | Cloud transcription (recommended) | Cloud mode |
| `openai-whisper` | Local transcription fallback | Only if no API key |
| Playwright CLI | Douyin/XHS video URL extraction | Douyin/XHS scenarios |
| Chrome/Chromium | Headless verification | Optional (deep analysis mode) |

Check tool availability:

```bash
which yt-dlp ffmpeg ffprobe
pip show emoji openai-whisper 2>/dev/null
```

For cloud API, check keys are set as environment variables or in project config.

---

## Versioning & Release

This skill follows [Semantic Versioning](https://semver.org/). Releases are
packaged as `Video2Doc-v{MAJOR}.{MINOR}.{PATCH}.zip` and published to GitHub.

**Release workflow** (run after any SKILL.md or script change):
```bash
cd ~/.workbuddy/skills/Video2Doc
VERSION=v0.1.0  # bump as needed
git add -A && git commit -m "feat: description" && git push
git tag -a $VERSION -m "Video2Doc $VERSION" && git push origin $VERSION
# Then create GitHub Release with zip asset
```

After releasing, the agent should confirm:
- [ ] Tag pushed to GitHub
- [ ] Release created with `Video2Doc-{VERSION}.zip` asset
- [ ] CHANGELOG.md updated
