# Changelog

## [v0.4.1] — 2026-06-30

### Fixed
- **结果内容读取回退**：修复转录任务只选 MD 格式时，前端「文稿 Tab」读取 `/api/content/{id}/text` 返回"内容不存在"的问题
  - `text` 类型自动回退到 `transcript.md`
  - `md` 类型自动回退到 `transcript.txt`
  - `srt` 在无 .srt 文件时，从原始 `tele_result.json` 实时生成
- **启动自检**：`webui.py` 启动时自动运行跨平台环境检查（`--no-check` 可跳过）

### Verified
- 后端 14 个模块函数导入正常
- 三种 Job 类型（download / transcribe_online / transcribe_local）创建与状态流转正常
- 本地转录端到端实测通过（上传 → 提取音频 → TeleSpeechASR → 导出 MD/SRT）
- 三个 API 端点接受请求、历史记录正确归类

## [v0.4.0] — 2026-06-26

### Added
- **三大核心功能**：视频下载、在线视频转录、本地媒体转录
- **全新首页**：暗色工业风 + 毛玻璃 + 三列功能卡片 + Hero区
- **三个全屏模态弹窗**：各有独立的功能色（下载翠绿/转录天蓝/本地薰衣紫）
- **视频下载**：支持「下载后同时转录为文稿」可选勾选框
- **本地转录**：拖拽上传区 + 文件信息展示 + 200MB大小限制
- **双Tab结果展示**：文稿 + SRT字幕切换，支持复制/下载
- **步骤进度指示器**：横向步骤条 + 实时状态动画
- **首页历史记录**：底部最近处理列表

### Changed
- **代码架构重构**：`webui.py` 拆分为 `webui/` 包（server / job_manager / pipeline / templates）
- HTML 模板从 Python 字符串迁出为独立文件 `webui/static/index.html`
- Job 模型新增 `JobType`（download / transcribe_online / transcribe_local）
- API 端点新增：`/api/download-video`、`/api/transcribe-online`、`/api/transcribe-local`、`/api/content/`
- Python 3.13 兼容（移除 `cgi` 模块，改为手动 multipart 解析）

### Design
- 借鉴"非丨链接提取文案"项目前端设计，但全面升级：
  - 紫蓝亮渐变 → 暗色深蓝基调 (#08090B → #111627)
  - 毛玻璃骨架保留（`rgba(15,17,25,0.88)` + `backdrop-filter: blur(24px)`）
  - 三功能色克制区分（翠绿/天蓝/薰衣紫）
  - 拒绝过度动效：仅 fadeIn/slideUp/transition 基础动画
  - 响应式 768px 断点

## [v0.3.0] — 2026-06-26

### Added
- **`webui.py`**: 本地 Web 可视化界面 — 单文件 Python HTTP 服务+暗色主题前端
  - 中文界面，粘贴链接即可操作
  - 实时管道可视化（解析→下载→提取→转录→导出）
  - 支持选择模式/格式/领域、批量模式
  - 一键下载输出文件
  - Windows 兼容（自动检测 ffmpeg.exe、yt-dlp.exe、curl.exe）
- **Windows 完整支持**：README 新增 Windows 安装说明，Python 后端自动适配 Windows 路径

### Changed
- Web UI 界面完全中文化
- `find_executable()` 工具函数支持 Windows .exe 后缀自动检测
- README 重写为 Web UI 优先体验

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
