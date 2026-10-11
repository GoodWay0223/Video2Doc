# Changelog

## [Unreleased]

暂无。

## [v0.8.0] — 2026-10-11

### Added
- `video2doc.py` 命令行：与 Web UI 共用同一套 pipeline（链接/分享文本/本地文件、批量、`--download`、`--local-only`、`--json`）；`video2doc.sh` 改为其薄封装，CLI 不再是只能转写已有音频的半成品。
- 任务持久化：每个任务写入 `output/<任务 ID>/job.json`，重启服务后“最近处理”自动恢复；运行中被中断的任务明确标记为 `INTERRUPTED`。
- 有界任务队列：默认最多并行 2 个任务（`VIDEO2DOC_MAX_JOBS` 可调），避免多个下载/本地模型同时运行耗尽内存。
- YouTube/通用站点也走“字幕优先 → 仅音频”路径，不再为转文稿下载完整视频；小红书走统一的直链 → yt-dlp 兜底。
- Markdown 文稿包含标题、来源、时长、识别来源，并按停顿/句末自动分段；TXT 同样分段；JSON 增加元数据。
- `VIDEO2DOC_WHISPER_LANGUAGE`（如 `auto`/`en`）与 `VIDEO2DOC_ENRICH_MODEL` 配置项。

### Changed
- Web 服务改为多线程，上传/下载大文件期间状态轮询与页面访问不再被阻塞。
- 本地上传改为原始字节流式写盘，单文件上限由 200 MB 提升到 4 GB，内存占用恒定；前端显示上传进度。旧 multipart 接口保留（200 MB）。
- 所有音频在识别前统一转为 16 kHz 单声道 MP3（一次 ffmpeg），云端上传体积通常缩小 4–8 倍。
- 抖音转文稿改为“移动分享 MP4 → Playwright 签名音轨”，免浏览器路径优先，失败时通常不到 1 秒即切换。
- 豆包轮询时限随音频时长伸缩（至少 3 分钟），TeleSpeechASR 超时同理；长音频不再因固定 90/120 秒超时失败。
- FunASR/Whisper 模型在进程内缓存并串行推理，不再每个任务重新加载。
- 云端摘要在 4000 字预算内对长文稿取首/中/尾节选，摘要覆盖全篇而非只看开头。
- yt-dlp 下载启用 4 路分片并发，视频优先 MP4/M4A；`~/.video2doc/config.json` 读取逻辑统一，自检与 pipeline 对 UTF-8 BOM 配置的判断一致。
- yt-dlp 最低版本提升到 2026.8.19；GitHub Actions 升级到 v7，CI 矩阵改为 Python 3.10/3.12/3.14。

### Security
- 校验 Host 头以阻止 DNS rebinding；POST 请求校验 Origin/Sec-Fetch-Site，拒绝其他网站的跨站请求（CSRF）。
- 首页增加 `X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`。

### Fixed
- Windows 上 `raw/tele_result.json` 按系统 GBK 写入导致含 emoji/生僻字时报错、预览回退读取失败；现统一 UTF-8。
- 纯下载失败时具体原因被笼统的“下载失败”覆盖。
- YouTube 字幕请求 `--sub-langs all` 会拉取数百条机器翻译轨并触发 HTTP 429；B站弹幕可能被误当作字幕。
- 本地 WAV/FLAC 等音频被直接改名为 `audio.mp3` 交给引擎；本地视频提取失败时错误不明确。
- 引擎返回空文本时没有任何原因提示；YouTube 自动字幕的滚动重复行被重复写入文稿。
- 纯下载任务缺少视频标题；前端关闭弹窗后旧轮询仍可能覆盖新任务界面。

### Verification
- 96 项 Python 回归测试通过；Python 编译、JavaScript、Shell 语法检查通过。
- Windows 真实端到端：YouTube 字幕路径（4.7 s）、YouTube MP4 下载、B站公共音轨 + 豆包 + 云端摘要、抖音（分享页无数据 0.3 s 内切换 Playwright 音轨）+ 豆包、本地上传 TeleSpeechASR、multipart 旧接口、隐私模式 Whisper、CLI 本地文件与链接；无头浏览器验证流式上传、结果展示与历史恢复。

## [v0.7.0] — 2026-08-02

### Added
- B站公共 API 采集器：转文稿默认直接下载公开 DASH 音轨，纯下载使用独立音视频轨并经 ffmpeg 合并；yt-dlp 保留为字幕、登录画质和兼容兜底。
- 抖音分层采集器：移动分享 MP4、隔离 Playwright 会话捕获签名 DASH 音轨、显式 Cookie yt-dlp 与 MediaRecorder 组成不同原理的回退链。
- `download.trace.json` 记录每次策略、耗时、分类错误及媒体校验结果，同时移除查询参数、Cookie、API Key 和签名 URL。
- `scripts/acquire_media.py` 提供与 Web UI 完全相同的 B站/抖音媒体采集入口。
- Whisper 模型可通过 `VIDEO2DOC_WHISPER_MODEL` 或 `whisper_model` 显式选择；默认仍为 `turbo`。

### Security
- 默认不再读取正在运行的 Chrome Cookie 数据库；登录能力必须显式配置 `cookies.txt`、浏览器源或抖音 Playwright `storage_state`。
- 抖音浏览器状态只在隔离浏览器上下文使用，不会把 Cookie 扁平化后转发给第三方 CDN；CDN 仅使用捕获的签名 URL 与 Referer。

### Changed
- 在线转文稿改为“字幕优先 → 平台音频直取 → ASR”，B站和抖音不再为了识别语音先下载完整视频。
- B站字幕 HTTP 412 不再原样盲重试；立即切换公共音轨。抖音签名 URL 的 403/410 只刷新一次页面签名，再进入不同原理的后备路径。
- 保留 v0.6.0 的豆包、TeleSpeechASR、FunASR、Whisper、多格式导出、隐私模式和 Web 安全能力；平台元数据标题与时长不再被转录首句覆盖。
- Windows 配置统一按 UTF-8 BOM/UTF-8 读取，并兼容旧 GB18030 配置，无需依赖系统“UTF-8 Beta”区域设置。

### Fixed
- 转录全部失败时保留最后一个引擎的可执行错误信息，避免只显示笼统的“所有引擎失败”。
- 发布构建器在 Git worktree 中正确排除文件形式的 `.git` 元数据。
- yt-dlp 固定使用 `--ignore-config` 和唯一输出名，避免用户全局配置、缩略图或上一次残留文件被误判为成功媒体。

### Verification
- 71/71 Python 回归测试通过，并通过 Python、JavaScript、Shell 语法检查与 `git diff --check`。
- Windows 真实 B站全流程：字幕请求 412 后切 `bilibili.public_api_audio`，完成 Whisper 转录及 MD/TXT/JSON/SRT 导出。
- Windows 真实抖音全流程：签名音轨页面超时后切 `douyin.mobile_ssr_mp4`，完成 Whisper 转录及 MD/TXT/JSON/SRT 导出。
- 两个真实样本均经 ffprobe 校验音轨、时长和文件完整性；平台页面与风控会变化，不构成永久成功率承诺。

## [v0.6.0] — 2026-07-22

### Security
- Web 服务默认仅监听 `127.0.0.1`，移除通配 CORS。
- 修复下载路径穿越和上传文件名越界写入；上传文件使用服务端生成的落盘名。
- JSON / 上传请求增加读取前大小限制，文件下载改为流式返回。
- 前端移除不可信 `innerHTML` 与 inline 事件处理，结果和历史记录改为安全 DOM 渲染。
- 输入 URL 限制为支持平台的 HTTP/HTTPS 域名，并拒绝凭据、异常端口和伪装域名。

### Added
- 云端摘要增强开关，以及本地媒体的“仅本地处理”隐私模式。
- 隐私模式保留本地 `auto` 降级链，按 FunASR → Whisper 兜底，不再被前端强制锁定到 FunASR。
- `local_only` / `allow_enrichment` Job 字段及服务端强制执行。
- 首页运行时能力状态：只公开下载/引擎就绪布尔值，不返回凭据或本机路径。
- Windows/macOS 一键启动器、跨平台可执行文件发现和 UTF-8 控制台/子进程处理。
- Windows/macOS GitHub Actions 矩阵，执行 Python 3.10/3.11 核心回归、启动器与发布包冒烟检查。
- 可复现的跨平台发布构建器：生成版本化 ZIP、SHA-256 和包内 `RELEASE-MANIFEST.json`，自动排除密钥、缓存、媒体与运行产物。
- 组件版本健康检查：默认离线读取 Python、FFmpeg、ffprobe、curl、yt-dlp 与 JavaScript runtime；yt-dlp 低于内置最低版本时不再标为就绪。
- 用户显式触发的 PyPI 最新稳定版只读检查，以及适配 uv tool、pip 或独立版的手动升级建议；启动和首页不会自动联网或执行升级。
- Dependabot 每周提高 yt-dlp 已测试最低基线；计划 CI 每周在 Windows/macOS、Python 3.10/3.11 上重新验证当时的最新稳定版。
- 依赖清单、密钥变量示例、跨平台换行规则和 57 项安全/正确性/发布回归测试。
- API Key 仅从显式 Video2Doc 配置读取，且不再出现在 curl 进程参数中；摘要正文改为进程内 HTTPS 请求。
- 首页和本地文件弹窗增加隐私模式入口提示、启用条件、数据边界及可展开的安装步骤；README 增加完整使用说明。

### Fixed
- yt-dlp Chrome Cookie 调用失败后会正确重试无 Cookie 下载。
- Windows URL 解析改用 `os.devnull`。
- 上下文校正规则、正则捕获组、领域参数和单格式文件导出。
- 自检现在识别真实 Python Playwright、云端 Key、本地引擎和用户级 yt-dlp。
- CLI exporter 路径及成功/失败计数。
- 首页删除无依据的准确率、高清无水印、永久免费等承诺；明确三个处理入口、字幕优先策略、四种文稿格式和小红书实验状态。
- 隐藏尚未接入 Web pipeline 的领域选择及未正确返回视频的“下载后转录”组合控件。
- 运行时状态区分“已配置/已安装”与“实际验证可用”；TXT/SRT 自动禁止无产物的云端摘要调用。
- JSON/SRT 单格式导出时，结果页仍可从标准化转录结果生成统一文本预览。
- macOS Finder/Homebrew/MacPorts 与 Windows WinGet/Scoop/Chocolatey/uv/虚拟环境下的 ffmpeg、ffprobe、curl、yt-dlp 和浏览器发现。
- Shell 脚本统一选择真实可用的 Python 3.10+，与当前 yt-dlp 的最低版本一致；避免 Windows Store 的无效 `python3` 别名，并移除 macOS BSD grep 不支持的 `-P` 用法。
- `verify_html.py` 支持 Windows Chrome/Edge 路径、跨平台 `file://` URI 和 UTF-8 输出。

### Changed
- Web UI 推荐入口统一为原生 Python：Windows 使用 `start-video2doc.cmd`，macOS 使用 `start-video2doc.command`；实验性 Bash CLI 继续保留。
- `scripts/check_setup.sh` 委托跨平台 Python 自检，避免 Shell 与 Web UI 的能力判断漂移。
- 默认监听地址固定为 `127.0.0.1`；局域网监听必须显式指定 `--host 0.0.0.0`，且当前仍不提供认证或 HTTPS。

### Verification
- 本地 Windows：57/57 Python 单元测试、Python 编译、JavaScript 语法、Shell 语法和浏览器桌面/移动端检查通过。
- GitHub Actions：`windows-latest` 与 `macos-latest` 运行 Python 3.10/3.11 核心回归、启动器及发布包 smoke；不等同于真实平台媒体/API 端到端验证。

## [v0.5.0] — 2026-07-09（大版本：下载链路全面优化 + 字幕优先 + 文稿增强）

### Added
- **抖音免 cookie 下载**：接入 iesdouyin 分享接口（移动端 UA + 提取 `window._ROUTER_DATA` +
  `playwm→play` 去水印），**无需 cookie/登录/yt-dlp**，实测两个抖音视频一次成功带音轨。参考 chubbyguan/chubbyskills。
- **小红书免 cookie 下载**：接入 `__INITIAL_STATE__` 解析（括号配平提 JSON + 递归找 note +
  `video.media.stream.masterUrl` 直链），移动端 UA，XHS_COOKIE 可选。yt-dlp 降为兜底。
- **字幕优先（B站/YouTube）**：`run_transcribe_pipeline` 在 engine=auto 时优先用平台 `ai-zh.srt`
  直接当文稿、**跳过 ASR**（秒级、免额度）；新增 `_parse_srt_to_transcript` + `_try_subtitle_transcript`。
  手动指定 engine 则强制 ASR。
- **content-enrich 文稿增强**：转录后自动用 SiliconFlow chat（DeepSeek-V3）补**一句话摘要 + 3-5 要点 +
  3-5 标签**，写入 `transcript.md` 顶部 `## 📝 摘要` 块（原文完整保留），JSON 带 enrichment 字段。best-effort。

### Fixed
- **B站 webui 下载 bug**：yt-dlp 未合并视频轨（留 `video.fXXXX.mp4` 不匹配）→ 加 `--ffmpeg-location` 自动合并 + 兜底合并逻辑。
- **纯下载路径双重坏**：`download_video_only` 没用新优化方法 + 存到错误目录导致下载链接 404 → 复用 `download_video` 全优化 + 移到 job.dir 根目录供服务。
- **本地转录失败无错误处理**：`run_local_pipeline` 失败时未设 error 状态导致前端无限轮询 → 补 status=error + 消息。
- **本地转录同文件复制报错**：上传音频若名 audio.mp3 → `shutil.copy2` 同文件崩 → 同路径跳过复制。

### Changed
- 抖音下载链路：iesdouyin（首选，无 cookie）→ yt-dlp+cookie（兜底）→ Playwright（末位）。
- download_video 的 yt-dlp 加 `--write-subs --sub-langs all` 抓平台字幕（供字幕优先）。
- 三大核心平台（抖音/B站/小红书）下载成功率全面提升。

### Verified
- 抖音 iesdouyin：2 视频（10:41/2:13）一次成功带音轨 → 豆包转录 55.6s/11.7s
- B站字幕优先：11.2s 出稿（下载+字幕，零 ASR 额度）
- content-enrich：CDC/MRC 摘要+5要点+5标签准确
- 通篇 QA：纯下载/本地转录/在线转录/内容API 端到端实测通过；前端 JS + 全部 py 语法 OK

## [v0.4.3] — 2026-07-08

### Added
- **豆包录音文件识别大模型 2.0（云端首选）**：接入火山引擎豆包 ASR；一次项目样本的
  9 个关键术语命中 7/9（TeleSpeechASR 为 2/9），该结果不代表通用准确率或 WER 基准。
  异步 submit+query、base64 内联音频、自带标点+ITN+词级时间戳。
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
- 豆包 vs TeleSpeechASR 单次样本关键术语命中：7/9 vs 2/9（非通用准确率基准）

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
