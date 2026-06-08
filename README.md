# Video2Doc

> 一个 AI Agent Skill——让任意 AI 助手将视频（抖音/小红书/B站/YouTube）转化为结构化文档。

## 这是什么

Video2Doc 是一个 **AI Agent Skill**，定义了从视频到文档的完整工作流。加载后 Agent 自动完成：视频下载 → 音频提取 → 转录 → 内容分章 → SVG 图解 → 关键帧截图 → 打包输出。

**两种输出模式**：

| 模式 | 输出 | 说明 |
|------|------|------|
| 📝 **纯文稿**（默认） | `transcript.md` | 校正文本 + 逐段对照表 + 要点提炼 |
| 🎨 **深度分析** | `index.html` | 离线 HTML，分章 + SVG 图解 + 截图 + 一键导出 MD/DOCX/长截图 |

> 未来计划：提供基于本地 HTML 的可直接运行的独立脚本版本，无需 Agent 也可一键使用。

## 兼容的 Agent

| Agent | 状态 |
|-------|------|
| WorkBuddy | ✅ 主要开发与测试平台 |
| OpenCLaw | ✅ 兼容 |
| Hermes | ✅ 兼容 |
| Cline / Claude Code | ✅ 兼容 |
| Codex CLI | ✅ 兼容 |

## 功能

- **多平台支持**：抖音、小红书、B站、YouTube
- **三级智能转录**：TeleSpeechASR（首选）→ SenseVoiceSmall → 本地 Whisper
- **内容分析**：按视频自然结构分章，提炼问题/陷阱/步骤/结论
- **SVG 图解**：按内容类型动态生成（流程/关系/时间线/对比/决策树/因果链）
- **关键帧抽取**：界面类视频每章抽一帧作为视觉实证
- **离线 HTML**：单页自包含，内联 CSS/SVG，截图相对路径
- **一键导出**：深度分析 HTML 内置导出按钮（Markdown / DOCX / 长截图）
- **纯文稿模式**：校正后的自然段落 + 逐段对照表 + 信息提炼

## 首次使用引导

加载 Skill 后，Agent 会自动展示引导菜单：

> 🎬 我可以帮你把视频转成文档：
> - 📝 **纯文稿**（默认）— 快速转录 + 信息提炼
> - 🎨 **深度分析** — 分章 + SVG 图解 + 截图 + 一键导出
>
> 直接给我视频链接就行 👇

## 使用方法

加载此 Skill 后，直接向 Agent 发送视频链接：

```
# 默认就是纯文稿模式
分析这个视频 https://v.douyin.com/xxxxx/

# 需要深度分析时明确指定
深度分析这个视频 https://v.douyin.com/xxxxx/
```

## 转录模型优先级

| 优先级 | 模型 | 特点 |
|--------|------|------|
| 1st | TeleSpeechASR | 中文精度最高，无 emoji 噪声 |
| 2nd | SenseVoiceSmall | 含 emoji，需后处理清洗 |
| 3rd | 本地 Whisper | 离线兜底，带时间戳 |

## 依赖

| 工具 | 用途 | 必需？ |
|------|------|--------|
| `yt-dlp` | 视频下载 | ✅ |
| `ffmpeg` + `ffprobe` | 音视频处理 | ✅ |
| 硅基流动 API Key | 云端转录（推荐） | 云端模式必需 |
| `openai-whisper` | 本地转录兜底 | 无 API Key 时必需 |
| Chrome/Chromium | 验证截图 | 可选 |
| Playwright CLI | 抖音视频获取 | 抖音场景必需 |

## 安装

直接对 AI Agent 说一句话即可安装，无需手动敲命令：

| Agent | 安装提示词 |
|-------|-----------|
| **WorkBuddy** | `帮我安装 Video2Doc skill，仓库是 https://github.com/GoodWay0223/Video2Doc` |
| **OpenCLaw** | `install skill from https://github.com/GoodWay0223/Video2Doc` |
| **Claude Code** | `请从 https://github.com/GoodWay0223/Video2Doc 安装 Video2Doc skill 到我的 skills 目录` |
| **Codex CLI** | `install the Video2Doc skill from https://github.com/GoodWay0223/Video2Doc` |
| **Cline** | `帮我安装 Video2Doc skill，GitHub 地址 https://github.com/GoodWay0223/Video2Doc` |

> 如果 Agent 不支持自然语言安装，手动执行：
> ```bash
> git clone https://github.com/GoodWay0223/Video2Doc.git ~/.workbuddy/skills/Video2Doc
> ```

## 目录结构

```
Video2Doc/
├── SKILL.md                  # 主工作流（8 阶段完整指南 + 首次使用引导）
├── README.md                 # 本文件
├── CHANGELOG.md              # 版本记录
├── scripts/                  # 可执行辅助脚本
│   ├── download_video.sh     # yt-dlp 下载 + 元数据
│   ├── extract_audio.sh      # 音频提取 + ffprobe 校验
│   ├── transcribe.sh         # Whisper 转写 + 验证
│   ├── extract_frames.sh     # 并行分片抽帧
│   └── verify_html.py        # Chrome headless 验证
├── references/               # 参考文档
│   ├── svg_guidelines.md     # SVG 图解生成指南
│   └── prerequisites.md      # 环境依赖检查
└── assets/
    └── template.html         # HTML 模板（含导出工具栏）
```

## License

MIT
