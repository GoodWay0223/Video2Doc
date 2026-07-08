# Changelog

## [v0.4.3] — 2026-07-08

### Added
- **豆包录音文件识别大模型 2.0（云端首选）**：接入火山引擎豆包 ASR，实测中文准确率 78%，
  显著优于 TeleSpeechASR（22%）。异步 submit+query、base64 内联音频、自带标点+ITN+词级时间戳。
  严格按官方文档处理响应头 `X-Api-Status-Code`（20000000 成功 / 20000001·2 处理中排队 /
  20000003 静音 / 4xxxxx·5xxxxx 错误），捕获 `X-Tt-Logid` 便于排错。
  用 `urllib` 而非 curl（规避 ARG_MAX 限制、可直接读响应头）。
- **引擎选择机制（默认自动 + 手动可选）**：`transcribe()` 按 `job.engine` 选引擎。
  - `auto`（默认）：豆包 → TeleSpeechASR → FunASR → Whisper 自动降级，首选额度耗尽/不稳定时
    静默切下一级，结果区显示「🤖 已自动切换到 tele（doubao 不可用）」。
  - 手动指定 `doubao`/`tele`/`funasr`/`whisper`：仅用该引擎，失败提示「可切换其他引擎重试」。
- **本地 FunASR (Paraformer) 引擎**：作为本地首选（优先于 Whisper），中文更快更准、自带 VAD+标点+ITN，
  自动检测 cuda/cpu。Whisper 降为末位兜底。
- **前端引擎选择器**：在线/本地转录弹窗各加「引擎」下拉 + 结果区引擎徽章。
- **B站 AI 字幕自动下载说明**：文档补明 `--write-subs` 会拉 `ai-zh` 等多语种字幕，可作 ASR 兜底。
- **豆包 X-Api-Key 获取路径文档**：新版控制台 → API 密钥管理（console.volcengine.com/speech/new/setting/apikeys）。

### Changed
- 转录链路改为 5 级：豆包(bigmodel 2.0) → TeleSpeechASR → SenseVoiceSmall → 本地 FunASR → 本地 Whisper。
- `Job` 新增 `engine`/`engine_used`/`engine_note` 字段；三处转录接口接受 `engine` 参数。
- import 守卫从 `except ImportError` 改为 `except Exception`（torch 在 macOS 未签名抛 OSError，原写法会崩）。

### Verified
- 3 个 py 文件语法 OK + webui 包导入 OK
- 引擎选择逻辑测试全正确（auto 全失败 / 强制引擎失败 / 未知引擎 / auto 降级 + engine_note）
- 豆包独立测试矩阵 4/4 通过（new 鉴权 × url/base64）；B站 6:43 音频 ~35s 完成、75 段、末段 402s
- 豆包 vs TeleSpeechASR 准确率对比：9 关键术语 7/9 vs 2/9

## [v0.4.2] — 2026-07-02

### Fixed
- **步骤进度指示器状态映射错位**：修复本地转录弹窗的步骤条高亮错误
  - 后端本地流水线的状态为 `extracting → transcribing → exporting`（无单独上传态），旧逻辑用全局序号映射导致「提取音频」阶段错误地高亮第 3 步「AI识别」，且「上传文件」永不显示完成
  - 改为按弹窗分别定义 `statusStep` 映射，本地弹窗「上传文件」在任务开始即标记完成，「提取音频 / AI识别 / 完成」依次正确点亮
  - 修正本地转录初始调用，任务开始即显示「上传文件」完成 + 「提取音频」进行中

### Changed
- **下载流水线新增 `downloading` 状态**：纯下载任务进度条在解析后、下载中、完成三个阶段更平滑
- 版本号统一更新为 v0.4.2（前端页脚、CLI 横幅、文档）

### Verified
- 前端脚本 `node --check` 语法通过
- 后端 4 个模块导入正常，HTTP 服务路由冒烟测试通过（GET /、/api/history、各 API 错误分支）
- 本地转录端到端实测通过（MP3 → 提取音频 → TeleSpeechASR → 导出 MD 1111B / SRT 1246B）

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
