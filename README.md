# Video2Doc

[![Latest Release](https://img.shields.io/github/v/release/GoodWay0223/Video2Doc?label=release)](https://github.com/GoodWay0223/Video2Doc/releases/latest)
[![Cross-platform CI](https://github.com/GoodWay0223/Video2Doc/actions/workflows/ci.yml/badge.svg)](https://github.com/GoodWay0223/Video2Doc/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB)](https://www.python.org/downloads/)

> 视频下载与转文稿工具 — 本地 Web 界面 + 命令行 + AI Agent Skill，三者共用同一套处理流程。
> 正式支持 Windows 与 macOS 的核心 Python/Web 流程；Linux 保持兼容但不在当前 CI 矩阵内。

---

## 下载最新版本

前往 [GitHub Releases](https://github.com/GoodWay0223/Video2Doc/releases/latest)，优先下载：

- `Video2Doc-v0.9.0.zip` — Windows/macOS 共用的跨平台源码包
- `Video2Doc-v0.9.0.zip.sha256` — ZIP 的 SHA-256 校验值

该 ZIP 不是 `.exe` 或 `.app` 安装包，仍需本机安装 Python 3.10+ 和 ffmpeg。GitHub 自动生成的 “Source code” 归档没有经过项目发布构建器的清理、清单与跨平台启动器检查，因此不作为首选下载。

---

## 快速开始

### Windows 10/11

在 PowerShell 中进入解压后的目录：

```powershell
python --version
python -m pip install -r requirements.txt
python scripts\check_setup.py
.\start-video2doc.cmd
```

如果 `python` 不可用，请从 [python.org](https://www.python.org/downloads/windows/) 安装并勾选 “Add Python to PATH”。启动后打开 `http://localhost:8765`。

### macOS

先确认 `python3 --version` 为 3.10 或更高；未安装时使用 `brew install python` 或 [python.org](https://www.python.org/downloads/macos/)：

```bash
python3 -m pip install -r requirements.txt
python3 scripts/check_setup.py
./start-video2doc.command
```

如果解压工具没有保留执行权限，先运行 `chmod +x start-video2doc.command scripts/*.sh video2doc.sh video2doc.py`。启动后打开 `http://localhost:8765`。

### 从源码运行

```bash
git clone https://github.com/GoodWay0223/Video2Doc.git
cd Video2Doc
python -m pip install -r requirements.txt   # macOS 可使用 python3
python webui.py                              # macOS 可使用 python3
```

> `python webui.py --check-only` 仅做环境检查；`python webui.py --no-check` 跳过启动自检。macOS 将 `python` 换成 `python3`。
> 安全默认值：服务只监听 `127.0.0.1`，不会自动暴露到局域网。

---

## 系统兼容性

| 范围 | Windows | macOS | Linux |
|------|---------|-------|-------|
| Web UI / Python pipeline | ✅ 正式支持 | ✅ 正式支持 | 🟡 兼容保留 |
| 一键启动 | `start-video2doc.cmd` | `start-video2doc.command` | 使用 `python3 webui.py` |
| 环境自检 | `python scripts\check_setup.py` | `python3 scripts/check_setup.py` | `python3 scripts/check_setup.py` |
| GitHub Actions | Python 3.10/3.12/3.14 核心回归 + 打包 smoke | Python 3.10/3.12/3.14 核心回归 + 打包 smoke | 当前未纳入矩阵 |
| 命令行 | `python video2doc.py` | `python3 video2doc.py` 或 `./video2doc.sh` | 同 macOS |

CI 验证的是核心代码、启动器和发布包结构，不代表抖音/B站/YouTube/小红书下载及云端 API 已在两个系统上完成真实媒体端到端验证。正式使用仍建议先运行环境自检和一个非敏感短视频任务。

---

## 📋 安装教程

### 第一步：安装 Python 3.10+

| 系统 | 方式 |
|------|------|
| **macOS** | 先运行 `python3 --version`；未安装或低于 3.10 时执行 `brew install python`，或使用 python.org 安装包 |
| **Windows** | [python.org](https://python.org) 下载安装，勾选 "Add Python to PATH" |
| **Linux** | `sudo apt install python3` |

### 第二步：安装 ffmpeg（音频处理必需）

| 系统 | 命令 |
|------|------|
| **macOS** | `brew install ffmpeg` |
| **Windows** | `winget install ffmpeg` 或下载 [ffmpeg.org](https://ffmpeg.org) |
| **Linux** | `sudo apt install ffmpeg` |

### 第三步：安装 yt-dlp（字幕、登录画质与通用平台兜底）

```bash
# Windows
python -m pip install -r requirements.txt

# macOS / Linux
python3 -m pip install -r requirements.txt
```

### 工具自动保持最新

Video2Doc 默认**每天检查一次**依赖工具，并把可自动更新的工具升级到**最新稳定版**（Web UI 右上角 **⚙️ 设置 → 🔄 工具与更新** 可查看、手动更新或关闭自动更新）：

| 工具 | 检查来源 | 自动更新方式 |
|------|----------|--------------|
| yt-dlp（含 yt-dlp-ejs） | PyPI | `pip install --upgrade --no-cache-dir` 原地替换 |
| Playwright + Chromium | PyPI | pip 升级后重新安装 Chromium，Playwright 自动删除不再使用的旧浏览器 |
| openai-whisper / FunASR | PyPI | 仅在已安装时升级 |
| FFmpeg | Windows：gyan.dev 官方构建（GitHub，带 SHA-256）；macOS：Homebrew | Windows 独立目录：下载校验后覆盖原目录；winget / Homebrew 安装：调用对应包管理器 |
| Node.js、Python | nodejs.org、endoflife.date | 需要管理员权限，只显示升级命令 |

- 只安装**发布满 7 天**的稳定版（预发布、已撤回版本一律跳过），避开刚发布就被撤回的问题版本；界面同时显示真正的最新版。
- 升级是原地替换：pip 不写缓存，FFmpeg 直接覆盖原目录，不会在电脑上留下第二份。
- 有任务正在运行时不更新；离线时不报错，下次再试。版本查询只访问公开的发布信息，不发送 Key、媒体、文稿或本机路径。
- 命令行：`python scripts/tool_updates.py` 查看状态，加 `--update` 立即更新。

仓库侧由 Dependabot 每周检查 yt-dlp 稳定版并提升 `requirements.txt` 的已测试最低基线；计划任务同时在 Windows/macOS、Python 3.10/3.12/3.14 上重新安装当时的最新稳定版并运行完整 CI。更新只会形成待审查的 PR，不会绕过测试直接发布。

> YouTube 页面变化较快。完整支持通常还需要 yt-dlp 推荐的 JavaScript runtime（优先 Deno，也可使用受支持的 Node.js/Bun/QuickJS）及相关 EJS 组件；地区、账号和页面变化仍可能影响结果。

如果已经安装 [uv](https://docs.astral.sh/uv/)，也可以使用 `uv tool install yt-dlp`；uv 不是运行 Video2Doc 的必需依赖。

抖音的快速签名音轨和最终 MediaRecorder 回退需要 Python Playwright；不使用抖音时可不安装：

```powershell
python -m pip install playwright
python -m playwright install chromium
```

### 第四步：配置云端 API Key（至少一种）

最简单的方式：启动后点页面右上角 **⚙️ 设置 → 🔑 API Key**。每个服务商都有 **“获取 Key ↗”** 直达链接、输入框、**验证**（只把 Key 发给该服务商做一次无害查询）、**保存**和**清除**按钮。

| 服务商 | 用途 | 获取地址 | 环境变量 |
|--------|------|----------|----------|
| 豆包语音（火山引擎） | 语音识别首选：豆包录音文件识别 2.0 | [控制台 API Key](https://console.volcengine.com/speech/new/setting/apikeys) | `DOUBAO_API_KEY` |
| 硅基流动 SiliconFlow | 语音识别备选：TeleSpeechASR；AI 摘要/要点/标签 | [API 密钥](https://cloud.siliconflow.cn/account/ak) | `SILICONFLOW_API_KEY` |

- Key 只保存在本机 `~/.video2doc/config.json`（UTF-8，尽量限制为仅当前用户可读），页面上只显示掩码，接口永远不回传明文。
- 同名环境变量优先于设置页保存的值，方便脚本化部署。
- 修改设置只允许在运行 Video2Doc 的这台电脑上进行；即使用 `--host 0.0.0.0` 共享到局域网，其他设备也不能读写 Key。
- **⚙️ 设置 → 🧠 模型**：AI 摘要模型会列出你的硅基流动账号实际可用的对话模型（默认 `deepseek-ai/DeepSeek-V3`，也可填自定义 ID）；本地 Whisper 的模型与语言也在这里选。
- **⚙️ 设置 → 🍪 登录态**：可选的 cookies.txt、抖音 storage_state 和小红书 Cookie。

FunASR / Whisper 只是可选的本地后备，不是必装项。不要把真实 Key 写进仓库或聊天记录。

### 第五步：运行环境检查

```powershell
# Windows
python scripts\check_setup.py
python webui.py --check-only
```

```bash
# macOS / Linux
python3 scripts/check_setup.py
python3 webui.py --check-only
```

输出示例：
```
  系统: macOS
  Python: Python 3.13.12

  ✅ FFmpeg (音频处理): /usr/local/bin/ffmpeg
  ✅ curl (API 请求): curl
  ✅ yt-dlp (视频下载): yt-dlp
  ✅ 豆包云端: API Key 已配置（未联网验证）

  ✅ 所有核心依赖就绪，可以正常使用。
```

如果某项显示 ❌，按提示安装对应工具后再运行一次检查。

---

## 三种使用方式

### 1. Web 可视化界面（推荐）

```powershell
python webui.py
# 浏览器打开 http://localhost:8765
```

三个处理入口：
- 📥 **视频下载** — 下载支持平台当前可获取的视频文件
- 🎙️ **链接转文稿** — 平台字幕优先；无字幕时使用已配置的识别引擎
- 📤 **本地文件转文稿** — 上传本地文件（单文件最大 4 GB，流式写盘不占内存）；可显式开启“仅本机处理”

任务状态与结果写入 `output/<任务 ID>/job.json`，重启服务后“最近处理”会自动恢复；同时最多并行 2 个任务（`VIDEO2DOC_MAX_JOBS` 可调），其余排队。

### 各平台默认路径

| 平台 | 链接转文稿 | 纯视频下载 |
|------|------------|------------|
| B站 | 平台字幕 → 公共 DASH 音轨 → yt-dlp 音频兜底 | 显式 Cookie yt-dlp（登录画质）→ 公共 DASH 音视频 → yt-dlp 兜底 |
| 抖音 | 移动分享 MP4（免浏览器，失败通常 <1 秒）→ 隔离 Playwright 签名音轨 → 显式 Cookie yt-dlp → MediaRecorder | 移动分享 MP4 → 隔离 Playwright DASH → 显式 Cookie yt-dlp → MediaRecorder |
| YouTube | 平台字幕（中文 > 原声自动字幕）→ yt-dlp 仅音频 | yt-dlp（优先 MP4/M4A，4 路分片并发） |
| 小红书 | 页面直链视频 → yt-dlp 兜底 | 同左 |

所有音频在识别前统一转为 16 kHz 单声道 MP3：云端上传体积通常缩小 4–8 倍，本地模型也无需重复解码。字幕只请求中文、原声与少量常用语言，不再请求 YouTube 上百条机器翻译轨（会触发 HTTP 429）。

每条成功路径都会经 ffprobe 校验音轨、视频轨、时长与文件完整性，并在任务的 `raw/download.trace.json` 中留下已脱敏的尝试记录。HTTP 412、403/410、页面加载超时会切换到不同原理的后备路径，不会把完全相同的失败请求无限重试。

浏览器里已经登录 B站/抖音，不代表独立运行的 Video2Doc 自动拥有该登录态。默认不会读取正在运行的 Chrome Cookie 数据库；只有登录画质或受限内容确实需要时，才应显式配置导出的 cookies.txt 或抖音 Playwright storage state。公开内容通常不需要 Cookie。

Windows 的“Beta 版：使用 Unicode UTF-8”开关不是运行本项目的前置条件。v0.7.0 起明确按 UTF-8 读写，并兼容旧 GB18030 配置；建议程序自身处理编码，不依赖全局系统区域设置来修复第三方项目。

用于采集诊断、但不执行转录的统一命令：

```powershell
python scripts\acquire_media.py "视频链接或分享文本" --output-dir output\smoke --purpose audio
```

### 2. 命令行

`video2doc.py` 直接调用与 Web UI 完全相同的 pipeline（字幕优先、平台直取音频、引擎降级、隐私模式、多格式导出），结果写入 `output/<任务 ID>/`，重启 Web UI 后也会出现在“最近处理”里。

```bash
python video2doc.py "https://www.bilibili.com/video/BV..."          # 链接转文稿（macOS 用 python3）
python video2doc.py "复制打开抖音 https://v.douyin.com/xxxx/ ..."      # 直接粘贴分享文本
python video2doc.py meeting.m4a --format all --local-only            # 本地文件 + 仅本机识别
python video2doc.py --download "https://youtu.be/..."                # 只下载视频
python video2doc.py --batch links.txt --format md,srt --json         # 批量，每行一个链接或文件
```

macOS/Linux 也可以用等价的 `./video2doc.sh ...`。完整参数见 `python video2doc.py --help`。

### 3. Agent Skill

直接对 AI Agent 说：

| Agent | 安装提示词 |
|-------|-----------|
| **WorkBuddy** | `帮我安装 Video2Doc skill，仓库是 https://github.com/GoodWay0223/Video2Doc` |
| **其他 Agent** | `从 https://github.com/GoodWay0223/Video2Doc 安装 Video2Doc` |

---

## 隐私模式（仅本机处理）

隐私模式只用于 Web UI 的 **“本地文件转文稿”** 入口。它是服务端实际执行的数据边界，不只是一个前端提示：开启后，云端语音识别和云端内容增强都会被禁止。

| 项目 | 标准模式 | 隐私模式 |
|------|---------|---------|
| 语音识别 | 可使用豆包、TeleSpeechASR、FunASR 或 Whisper | 只允许 FunASR / Whisper；`自动` 按 FunASR → Whisper 尝试 |
| 云端内容增强 | 用户可选；开启时最多发送 4000 字正文到 SiliconFlow（长文稿取首/中/尾节选） | 服务端强制关闭 |
| 本地引擎失败 | 可继续尝试其他已配置引擎 | 直接失败，不回退云端 |
| 文件与结果 | 保存在本机 `output/<任务 ID>/` | 同样保存在本机 `output/<任务 ID>/`，目前不会自动清理 |

> **不要混淆：**单独选择 FunASR / Whisper，或只关闭“云端内容增强”，都不等于开启隐私模式。只有勾选 **“🔒 隐私模式：仅本机识别”** 后，服务端才会强制禁止云端 ASR 和 SiliconFlow 增强。

### 如何开启

FunASR / Whisper 是可选依赖。以云端 API 为主时不需要安装；只有需要仅本机识别时，才按需安装其中至少一种：

```powershell
# 任选一种本地引擎
python -m pip install funasr torch
# 或
python -m pip install openai-whisper
```

1. 运行 `python scripts\check_setup.py`，确认 FunASR 或 Whisper 显示已就绪。
2. 重启 `python webui.py`，浏览器打开 `http://localhost:8765`。
3. 点击 **“本地文件转文稿”**，勾选 **“🔒 隐私模式：仅本机识别”**。
4. 选择文件并开始转录。推荐保留“自动”，它会按 FunASR → Whisper 尝试。

如果开关是灰色，表示当前没有检测到可用的 FunASR / Whisper；Video2Doc 不会偷偷回退到云端。安装后需要重启 Web 服务，前端才会重新读取能力状态。

### 数据边界

- 开启后，Video2Doc 不会把上传的音视频或生成的文稿发送给豆包、TeleSpeechASR 或 SiliconFlow。
- 首次使用 FunASR / Whisper 时，模型库可能联网下载权重；缓存完成后，媒体识别在本机执行。因此不能把首次使用描述为“完全无网络”。
- 浏览器会把文件上传到默认监听 `127.0.0.1` 的本机 Video2Doc 服务；不要在没有认证和 HTTPS 的情况下使用 `--host 0.0.0.0` 处理敏感文件。
- 源文件、中间音频、转录结果和导出文件会保留在 `output/<任务 ID>/`。当前没有自动清理策略，使用后请确认任务 ID，再手动删除对应目录。
- “链接转文稿”必须联网获取平台媒体，目前没有隐私模式入口；即使选择本地识别，也不能称为全程离线。

---

## 平台说明

### Windows

Windows 推荐安装 Python 3.10+、ffmpeg 和 yt-dlp。命令行直接用 `python video2doc.py`，不需要 Git Bash。

推荐方案：
1. 安装 [Python](https://python.org)（勾选 "Add Python to PATH"）
2. 安装 [ffmpeg](https://ffmpeg.org)（下载后解压，将 `bin/` 加入 PATH）
3. 安装依赖：`python -m pip install -r requirements.txt`
4. 重新打开 PowerShell，运行：
   ```
   cd Video2Doc
   python scripts/check_setup.py
   .\start-video2doc.cmd
   ```

无需安装 Git Bash、WSL 或任何 Linux 模拟层。服务默认仅监听 `127.0.0.1`；不要在没有认证的情况下使用 `--host 0.0.0.0`。

### macOS

Homebrew 推荐安装方式：

```bash
brew install python ffmpeg
python3 -m pip install -r requirements.txt
python3 scripts/check_setup.py
./start-video2doc.command
```

启动器和自检会额外检查 Apple Silicon Homebrew 的 `/opt/homebrew/bin`、Intel Homebrew 的 `/usr/local/bin` 以及 MacPorts 的 `/opt/local/bin`，因此从 Finder 启动时也能发现这些工具。

---

## 升级与发布包校验

### 从 v0.7.x 或更早版本升级

1. 下载新的 `Video2Doc-v0.9.0.zip`，解压到新目录；不要直接覆盖正在运行的旧目录。
2. API Key 继续使用系统环境变量或 `~/.video2doc/config.json`，发布包不包含任何凭据。
3. 如需保留旧任务，请单独备份旧目录中的 `output/`；新发布包不会包含运行产物。
4. 重新运行 `python -m pip install -r requirements.txt` 和环境自检，再启动 v0.9.0。
5. v0.6.0 起默认只监听 `127.0.0.1`。如过去依赖局域网访问，需要显式传入 `--host 0.0.0.0`；该模式当前没有认证或 HTTPS，不适合敏感文件。

### 验证 SHA-256

Windows PowerShell：

```powershell
Get-FileHash .\Video2Doc-v0.9.0.zip -Algorithm SHA256
Get-Content .\Video2Doc-v0.9.0.zip.sha256
```

macOS：

```bash
shasum -a 256 Video2Doc-v0.9.0.zip
cat Video2Doc-v0.9.0.zip.sha256
```

两边的哈希值必须完全一致。ZIP 内还包含 `RELEASE-MANIFEST.json`，列出每个源码文件的大小与 SHA-256。

### 当前验证边界

- 本地 Windows 已运行完整 Python 回归、Shell/Python/JavaScript 语法检查和真实浏览器桌面/移动端检查。
- GitHub Actions 在 `windows-latest`、`macos-latest` 上执行 Python 3.10/3.12/3.14 核心回归、启动器和打包 smoke。
- CI 不调用真实平台媒体或收费 API；平台页面变化、账号权限、地区限制、Key 有效性和额度仍需用户自行验证。
- YouTube 下载还会受到 yt-dlp/EJS/JavaScript runtime 版本及站点变化影响；自检通过不等于任意视频均可下载。

---

## 功能列表

- **三个处理入口**：视频下载 / 链接转文稿 / 本地文件转文稿
- **多平台链接**：抖音 / B站 / YouTube / 小红书（实验）
- **转录策略**：平台字幕优先；无字幕时按可用引擎尝试豆包、TeleSpeechASR、FunASR、Whisper
- **四种文稿格式**：Markdown（标题、来源/时长/识别来源、按停顿自动分段）/ TXT / JSON（含元数据）/ SRT
- **隐私控制**：云端增强可关闭；本地媒体支持仅本地处理模式
- **Agent 深度分析蓝图**：分章 + SVG 图解 + 关键帧截图（尚未接入 Web 主流程）
- **智能校正规则库**：`scripts/apply_corrections.py` / `scripts/export_formats.py --correct` 可用，默认流程不自动改写文稿
- **显式凭据配置**：仅从环境变量或 `~/.video2doc/config.json` 读取

---

## 目录结构

```
Video2Doc/
├── start-video2doc.cmd         # Windows 启动器
├── start-video2doc.command     # macOS 启动器
├── webui.py                    # 跨平台 Web UI 入口
├── video2doc.py                # 命令行（与 Web UI 共用 pipeline）
├── video2doc.sh                # 命令行的 Bash 薄封装
├── SKILL.md                    # Agent Skill 工作流
├── requirements.txt            # 核心 Python 依赖
├── scripts/
│   ├── check_setup.py          # 跨平台环境自检
│   ├── check_setup.sh          # 环境自检（Shell 版）
│   ├── build_release.py        # 安全、可复现的发布包构建器
│   ├── acquire_media.py        # 与 Web UI 共用的两平台采集诊断入口
│   ├── load_config.sh          # 配置加载
│   ├── export_formats.py       # 多格式导出
│   ├── apply_corrections.py    # 校正规则应用
│   └── ...
├── webui/                      # Web UI 后端包
│   ├── server.py
│   ├── pipeline.py
│   ├── bilibili.py             # B站公共 DASH 采集
│   ├── douyin.py               # 抖音 SSR/签名媒体采集
│   ├── job_manager.py
│   ├── templates.py
│   └── static/
│       └── index.html          # 前端页面
├── references/
│   ├── corrections.json        # 校正规则库
│   └── ...
├── tests/                       # 安全、正确性、兼容与打包回归
├── .github/workflows/ci.yml    # Windows/macOS CI
└── output/                     # 输出目录（运行时生成）
```

## License

当前仓库尚未包含正式 `LICENSE` 文件。除非版权所有者另行授权，否则默认不授予复制、修改或再发布权利；请勿自行假定为 MIT 或其他开源许可证。
