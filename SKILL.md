---
name: Video2Doc
description: "Video2Doc converts videos (Douyin, Bilibili, YouTube) into structured documentation — either a self-contained offline HTML page with chapter analysis, dynamic SVG diagrams, and keyframe screenshots; or a clean transcript with corrected text. Handles downloading, audio extraction with ffprobe validation, 4-tier transcription (TeleSpeechASR → SenseVoiceSmall → Groq → local Whisper), content chaptering, SVG generation, keyframe extraction, and headless verification. Use when the user asks to analyze a video, generate video notes, convert video to document, or provides a video URL for transcription."
agent_created: true
---

# Video2Doc — 视频转文档

Convert any video (Douyin/Bilibili/YouTube/etc.) into structured documentation.
Supports two output modes — the user can ask for either or both:

1. **Full HTML Document** (`index.html`) — self-contained offline page with
   chapter-by-chapter analysis, dynamic SVG diagrams, and keyframe screenshots.
2. **Clean Transcript** (`transcript.md`) — Whisper transcription with manual
   correction of recognition errors, formatted as readable prose with a
   segment-by-segment correction table.

---

## Workflow Overview

```
Download → Audio Extract+Validate → Transcribe → Structure → SVG+Keyframes → HTML Compose → Verify
```

Proceed phase by phase. If any phase fails, diagnose and retry before moving on.

---

## Phase 1: Download Video with Full Metadata

Use `yt-dlp` with cookies for platforms that require authentication (Bilibili
logged-in quality, etc.).

### Command Template

```bash
yt-dlp \
  --cookies-from-browser chrome \
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
  For Douyin, the cookie file is often mandatory.
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

## Phase 2: Audio Extraction, Conversion, and Validation

Extract the best audio stream, convert to MP3, and validate duration against
the metadata.

### Step 1: Extract and Convert

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
- Use `-ac 1` for mono if transcript quality is more important than fidelity

### Step 2: Validate Duration

```bash
AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "<OUTPUT>.mp3")
```

```bash
META_DUR=$(python3 -c "import json; d=json.load(open('<INFO_JSON>')); print(d['duration'])")
```

```bash
python3 -c "
a = float($AUDIO_DUR)
m = float($META_DUR)
diff = abs(a - m) / m
print(f'Audio: {a:.1f}s, Metadata: {m:.1f}s, Diff: {diff*100:.1f}%')
if diff > 0.05:
    print('WARNING: Duration discrepancy exceeds 5%')
"
```

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

Fast, no local compute, no model download. Three tiers:

| Priority | Provider | Register | Free Tier | Model | Notes |
|----------|----------|----------|-----------|-------|-------|
| **1st** | 硅基流动 | https://siliconflow.cn | 10h/month | TeleSpeechASR | Chinese-optimized, no emoji, best accuracy |
| **2nd** | 硅基流动 | https://siliconflow.cn | 10h/month | SenseVoiceSmall | Has emoji noise, post-process required |
| **3rd** | Groq | https://console.groq.com | 8h/day, 2000 req/day | whisper-large-v3-turbo | Rich timestamps, non-Chinese |

Both use the same OpenAI-compatible API. Request format:

```bash
curl https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@audio.mp3" \
  -F "model=whisper-large-v3-turbo" \
  -F "response_format=verbose_json" \
  -F "language=zh"
```

For 硅基流动, swap the endpoint:

```bash
curl https://api.siliconflow.cn/v1/audio/transcriptions \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@audio.mp3" \
  -F "model=TeleAI/TeleSpeechASR" \
  -F "response_format=verbose_json"
```

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

**API key storage**: Check `~/.workbuddy/MEMORY.md` or ask the user for their
key. Store it as `GROQ_API_KEY` or `SILICONFLOW_API_KEY` env var / config.

**Provider selection logic (ordered by priority)**:
1. **TeleSpeechASR** — use for all Chinese content. Best accuracy, no emoji noise.
2. **SenseVoiceSmall** — fallback if TeleSpeechASR fails or for A/B comparison.
   Always post-process with `emoji.replace_emoji()` to strip emoji.
3. **Groq Whisper** — use for non-Chinese content or when rich timestamps needed.
4. **Local Whisper** — last resort when no API key is configured, or user
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
  </style>
</head>
<body>
  <header>  <!-- Video metadata: title, uploader, duration, tags --> </header>
  <nav>     <!-- Chapter TOC with jump links -->                    </nav>
  <main>
    <section class="chapter" id="ch1"> ... </section>
    <section class="chapter" id="ch2"> ... </section>
    <!-- ... -->
  </main>
  <footer>  <!-- Generation timestamp, tool versions -->            </footer>
  <script>
    /* Minimal JS for timestamp seek, if embedding video/audio */
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

---

## Phase 8: Verification

After generating the HTML and all supporting files, verify the output.

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

### Douyin (抖音)

- Cookies are mandatory for most videos.
- **yt-dlp frequently fails** for Douyin due to API anti-bot protection ("Fresh
  cookies needed" or "Failed to parse JSON"). The recommended fallback:
  1. Use Playwright (`playwright-cli`) to open the video page with cookies
     injected via `cookie-set`.
  2. Wait for the video player to load (~5-8 seconds).
  3. Extract the video URL via `eval "document.querySelector('video').src"`.
  4. Download the video with `curl` using the same cookies file.
  This approach bypasses yt-dlp's broken API calls entirely.
- Short video format (< 5 min) — skip parallel shard extraction, just
  extract one frame directly.
- `ffmpeg` must be in `PATH` for Whisper to work. If using a custom
  ffmpeg binary, add its directory to `PATH` before running Whisper.

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
| Groq / 硅基流动 API Key | Cloud transcription (recommended) | Either one |
| `whisper` (local) | Fallback transcription | Only if no API key |
| Chrome/Chromium | Headless verification | Optional |

Check tool availability:

```bash
which yt-dlp ffmpeg ffprobe
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
