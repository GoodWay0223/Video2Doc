# Video2Doc

> AI Agent Skill + CLI 工具——将视频（抖音/小红书/B站/YouTube）转化为结构化文档。

## 这是什么

Video2Doc 既是一个 **AI Agent Skill**，也是一个独立的 **CLI 工具**。既可以加载到 Agent 中自动执行，也可以直接在终端运行。

**两种输出模式**：

| 模式 | 输出 | 说明 |
|------|------|------|
| 📝 **纯文稿**（默认） | `transcript.md` | 校正文本 + 逐段对照表 + 要点提炼 |
| 🎨 **深度分析** | `index.html` | 离线 HTML，分章 + SVG 图解 + 一键导出 MD/DOCX/长截图 |

## 快速开始

### Mac / Linux

```bash
git clone https://github.com/GoodWay0223/Video2Doc.git
cd Video2Doc
bash scripts/check_setup.sh                    # 环境检查

export SILICONFLOW_API_KEY=sk-xxxxx             # 配置 API Key
python3 webui.py                                # 🆕 启动可视化界面
```

打开 `http://localhost:8765`，粘贴链接即可转录。

CLI 模式也支持：

```bash
./video2doc.sh "https://v.douyin.com/xxxx"      # 命令行转录
./video2doc.sh --batch links.txt --format all   # 批量处理
```

### 🪟 Windows

安装 [Git for Windows](https://git-scm.com/download/win) 和 [Python 3.9+](https://python.org)：

```bash
# Git Bash 终端中
git clone https://github.com/GoodWay0223/Video2Doc.git
cd Video2Doc
bash scripts/check_setup.sh

set SILICONFLOW_API_KEY=sk-xxxxx                 # CMD 中设置环境变量
# 或 Git Bash: export SILICONFLOW_API_KEY=sk-xxxxx

python webui.py                                  # 启动可视化界面
```

> Windows 下需要额外安装 ffmpeg：`winget install ffmpeg` 或 `choco install ffmpeg`

## 兼容的 Agent

| Agent | 状态 |
|-------|------|
| WorkBuddy | ✅ 主要开发与测试平台 |
| OpenCLaw | ✅ 兼容 |
| Claude Code / Cline | ✅ 兼容 |
| Codex CLI | ✅ 兼容 |

## 功能

- **多平台支持**：抖音、小红书、B站、YouTube
- **三级智能转录**：TeleSpeechASR（首选）→ SenseVoiceSmall → 本地 Whisper
- **多格式输出**：SRT 字幕 / JSON 结构化 / TXT 纯文本 / Markdown
- **内容分析**：按视频自然结构分章，提炼问题/陷阱/步骤/结论
- **SVG 图解**：按内容类型动态生成（流程/关系/时间线/对比/决策树/因果链）
- **关键帧抽取**：界面类视频每章抽一帧作为视觉实证
- **离线 HTML**：单页自包含，内联 CSS/SVG，截图相对路径
- **一键导出**：深度分析 HTML 内置导出按钮（Markdown / DOCX / 长截图）
- **纯文稿模式**：校正后的自然段落 + 逐段对照表 + 信息提炼
- **批量处理**：`--batch links.txt` 一次处理多个链接
- **智能校正**：内置规则库自动修正常见 ASR 错误
- **跨 Agent 配置**：API Key 支持环境变量 / `~/.video2doc/config.json` / WorkBuddy 兼容
- **🆕 Web 可视化界面**：`python3 webui.py` 启动本地服务，浏览器操作，不需要命令行知识

## 通过 Agent 安装

直接对 AI Agent 说一句话即可安装：

| Agent | 安装提示词 |
|-------|-----------|
| **WorkBuddy** | `帮我安装 Video2Doc skill，仓库是 https://github.com/GoodWay0223/Video2Doc` |
| **其他 Agent** | `从 https://github.com/GoodWay0223/Video2Doc 安装 Video2Doc` |

## 配置 API Key

三种方式，任选其一（优先级从左到右）：

```bash
# 方式 1: 环境变量（推荐，跨 Agent 通用）
export SILICONFLOW_API_KEY=sk-xxxxx

# 方式 2: 配置文件（机器级）
mkdir -p ~/.video2doc
echo '{"siliconflow_api_key":"sk-xxxxx"}' > ~/.video2doc/config.json

# 方式 3: WorkBuddy 自动存储（向后兼容）
# Agent 会自动写入 ~/.workbuddy/MEMORY.md
```

> 注册链接：https://cloud.siliconflow.cn/i/pWcvZzOr（免费 10 小时/月）

## 目录结构

```
Video2Doc/
├── video2doc.sh              # CLI 入口（单视频/批量）
├── webui.py                   # 🆕 Web 可视化界面入口
├── SKILL.md                  # Agent Skill 完整工作流
├── README.md                 # 本文件
├── CHANGELOG.md              # 版本记录
├── scripts/                  # 可执行脚本
│   ├── check_setup.sh        # 🆕 环境自检
│   ├── load_config.sh        # 🆕 跨 Agent 配置加载
│   ├── export_formats.py     # 🆕 多格式导出 (SRT/JSON/TXT/MD)
│   ├── apply_corrections.py  # 🆕 转录校正规则应用
│   ├── download_video.sh     # yt-dlp 下载
│   ├── extract_audio.sh      # 音频提取 + 校验
│   ├── transcribe.sh         # Whisper 转录
│   ├── extract_frames.sh     # 关键帧抽帧
│   └── verify_html.py        # HTML 验证
├── references/               # 参考文档
│   ├── corrections.json      # 🆕 转录校正规则库
│   ├── svg_guidelines.md     # SVG 图解指南
│   └── prerequisites.md      # 环境依赖详解
└── assets/
    └── template.html         # HTML 模板
```

## License

MIT
