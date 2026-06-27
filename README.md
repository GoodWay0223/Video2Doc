# Video2Doc

> 视频转文档工具 — AI Agent Skill + CLI + Web 可视化界面。  
> Mac / Windows / Linux 全平台支持。

---

## 快速开始（30 秒）

```bash
git clone https://github.com/GoodWay0223/Video2Doc.git
cd Video2Doc
python3 scripts/check_setup.py          # 🆕 跨平台自检（Python 实现）
python3 webui.py                         # 启动 Web 界面
```

浏览器打开 `http://localhost:8765`，粘贴链接即可转录。

> Tip: `python3 webui.py --check-only` 仅做环境检查不启动服务。  
> Tip: `python3 webui.py --no-check` 跳过自检直接启动。

---

## 系统兼容性

| 功能 | Mac | Windows | Linux |
|------|-----|---------|-------|
| Web UI (`webui.py`) | ✅ Python3 即可 | ✅ Python3 即可 | ✅ Python3 即可 |
| 环境自检 (`scripts/check_setup.py`) | ✅ 跨平台 Python | ✅ 跨平台 Python | ✅ 跨平台 Python |
| CLI (`video2doc.sh`) | ✅ | ⚠️ 需 Git Bash | ✅ |
| Agent Skill | ✅ WorkBuddy 等 | ✅ WorkBuddy 等 | ✅ WorkBuddy 等 |

**核心原则**：整个项目的 **唯一入口** 是 `python3 webui.py`，Mac 和 Windows 运行方式完全相同。所有 .sh 脚本都是辅助工具，Web UI 和 Python 脚本不依赖它们。

---

## 📋 安装教程

### 第一步：安装 Python 3.9+

| 系统 | 方式 |
|------|------|
| **Mac** | 系统自带 `python3`，或 `brew install python3` |
| **Windows** | [python.org](https://python.org) 下载安装，勾选 "Add Python to PATH" |
| **Linux** | `sudo apt install python3` |

### 第二步：安装 ffmpeg（音频处理必需）

| 系统 | 命令 |
|------|------|
| **Mac** | `brew install ffmpeg` |
| **Windows** | `winget install ffmpeg` 或下载 [ffmpeg.org](https://ffmpeg.org) |
| **Linux** | `sudo apt install ffmpeg` |

### 第三步（可选）：安装 yt-dlp（非抖音平台下载）

```bash
pip install yt-dlp
```

### 第四步：配置 API Key（转录功能必需）

```bash
# 方式 1: 环境变量（推荐）
# Mac/Linux:
export SILICONFLOW_API_KEY=sk-xxxxx
# Windows CMD:
set SILICONFLOW_API_KEY=sk-xxxxx

# 方式 2: 配置文件
mkdir -p ~/.video2doc
echo '{"siliconflow_api_key":"sk-xxxxx"}' > ~/.video2doc/config.json
```

> 🔑 注册链接：https://cloud.siliconflow.cn/i/pWcvZzOr（免费 10 小时/月）

### 第五步：运行环境检查

```bash
python3 scripts/check_setup.py
# 或
python3 webui.py --check-only
```

输出示例：
```
  系统: macOS
  Python: Python 3.13.12

  ✅ FFmpeg (音频处理): /usr/local/bin/ffmpeg
  ✅ curl (API 请求): curl
  ✅ yt-dlp (视频下载): yt-dlp
  ✅ API Key: sk-zrcjwfs...sgwhd

  ✅ 所有核心依赖就绪，可以正常使用。
```

如果某项显示 ❌，按提示安装对应工具后再运行一次检查。

---

## 三种使用方式

### 1. Web 可视化界面（推荐）

```bash
python3 webui.py
# 浏览器打开 http://localhost:8765
```

三个功能：
- 📥 **视频下载** — 输入链接下载原视频
- 🎙️ **在线转录** — 输入链接 AI 转录为文稿
- 📤 **本地转录** — 上传本地文件 AI 转录

### 2. CLI 命令行

```bash
./video2doc.sh "https://v.douyin.com/xxxx"       # 单视频
./video2doc.sh --batch links.txt --format all     # 批量处理
```

### 3. Agent Skill

直接对 AI Agent 说：

| Agent | 安装提示词 |
|-------|-----------|
| **WorkBuddy** | `帮我安装 Video2Doc skill，仓库是 https://github.com/GoodWay0223/Video2Doc` |
| **其他 Agent** | `从 https://github.com/GoodWay0223/Video2Doc 安装 Video2Doc` |

---

## 🪟 Windows 特别说明

在 Windows 上，唯一需要额外安装的是 **Git for Windows**（如果要用 CLI 脚本）或仅装 **Python 3.9+**（如果只用 Web UI）。

推荐方案：
1. 安装 [Python](https://python.org)（勾选 "Add Python to PATH"）
2. 安装 [ffmpeg](https://ffmpeg.org)（下载后解压，将 `bin/` 加入 PATH）
3. 打开 CMD 或 PowerShell，运行：
   ```
   cd Video2Doc
   python scripts/check_setup.py
   python webui.py
   ```

无需安装 Git Bash、WSL 或任何 Linux 模拟层。Web UI 完全是跨平台的。

---

## 功能列表

- **三大核心功能**：视频下载 / 在线转录 / 本地转录
- **多平台支持**：抖音 / B站 / YouTube
- **三级智能转录**：TeleSpeechASR → SenseVoiceSmall → 本地 Whisper
- **多格式输出**：SRT 字幕 / JSON / TXT / Markdown
- **内容深度分析**：自动分章 + SVG 图解 + 关键帧截图
- **智能校正规则库**：自动修复常见 ASR 错误
- **跨 Agent 配置**：环境变量 / 配置文件 / WorkBuddy 三来源

---

## 目录结构

```
Video2Doc/
├── webui.py                    # Web UI 入口（Mac/Win/Linux 通用）
├── video2doc.sh                # CLI 入口
├── SKILL.md                    # Agent Skill 工作流
├── README.md                   # 本文件
├── CHANGELOG.md
├── scripts/
│   ├── check_setup.py          # 🆕 跨平台环境自检（Python）
│   ├── check_setup.sh          # 环境自检（Shell 版）
│   ├── load_config.sh          # 配置加载
│   ├── export_formats.py       # 多格式导出
│   ├── apply_corrections.py    # 校正规则应用
│   └── ...
├── webui/                      # Web UI 后端包
│   ├── server.py
│   ├── pipeline.py
│   ├── job_manager.py
│   ├── templates.py
│   └── static/
│       └── index.html          # 前端页面
├── references/
│   ├── corrections.json        # 校正规则库
│   └── ...
└── output/                     # 输出目录（运行时生成）
```

## License

MIT
