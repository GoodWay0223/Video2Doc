# Changelog

## [v0.2.0] — 2026-06-26

### Added
- **`check_setup.sh`**: 一键环境自检脚本，彩色输出检测所有依赖
- **`load_config.sh`**: 跨 Agent 配置加载，优先级 env var > ~/.video2doc/config.json > WorkBuddy legacy
- **`corrections.json`**: 转录校正规则库（通用规则 + 汽车/科技领域规则）
- **`apply_corrections.py`**: 自动应用校正规则（精确匹配 + 上下文匹配 + 模糊正则）
- **`export_formats.py`**: 多格式导出（SRT 字幕 / JSON 结构化 / TXT 纯文本 / MD）
- **`video2doc.sh`**: CLI 入口脚本，支持单视频、批量模式、自定义格式、领域校正

### Changed
- API Key 读取不再绑定 WorkBuddy，新增环境变量和 config.json 两种跨 Agent 方案
- README 重写：新增快速开始、配置指南、CLI 用法
- SKILL.md 新增 CLI & Scripts 章节

## [v0.1.1] — 2026-06-08

### Fixed
- **Douyin anti-bot detection**: Rewrote download strategy with 3-tier approach
  (MediaRecorder → page.route → yt-dlp), captcha detection, and session isolation rules
- **Cookie handling**: Added `sameSite: 'Lax'` requirement, cookie freshness guidance,
  and `playwright_state.json` generation snippet
- **Audio extraction**: Simplified to one-step video→MP3 (skip WAV intermediate)

### Added
- **Parallel batch processing**: Download video N while transcribing video N-1
- **Time estimates table**: Expected durations for different video lengths
- **Error recovery table**: Specific actions for captcha, NO_VIDEO, 0-byte, expired cookies
- **Captcha detection rule**: Check page title for "验证码" and abort immediately

### Optimized
- Replaced `sleep(5)` with `waitForSelector('video')` for faster page readiness
- Duration validation now uses ffprobe on video file directly (vs. depending on yt-dlp .info.json)
- Douyin gold rules: 1 browser session per video, load cookies before navigate, close after download

## [v0.1.0] — 2026-06-08

### Added
- Initial release
- 3-tier transcription: TeleSpeechASR → SenseVoiceSmall → Local Whisper
- Multi-platform video download: Douyin, Xiaohongshu, Bilibili, YouTube
- Full HTML output mode with SVG diagrams and keyframe screenshots
- **Export toolbar**: one-click export to MD, DOCX, and long-screenshot (PNG) from HTML pages
- **First-run guide**: Agent automatically presents a mode selection menu on first use
- **Default mode**: Pure transcript (文稿) — faster, no SVG/Screenshots
- Clean transcript mode with segment comparison table
- Audio extraction with ffprobe duration validation (±5%)
- Chapter-based content analysis (problem/trap/steps/conclusion)
- Post-processing: SenseVoiceSmall emoji stripping
- Playwright-based Douyin video capture (MediaRecorder fallback)
- GitHub release packaging: `Video2Doc-v{version}.zip`
- Multi-agent compatibility: WorkBuddy, OpenCLaw, Claude Code, Codex, Cline
