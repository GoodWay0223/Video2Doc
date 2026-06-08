# Video2Doc

将视频（抖音/B站/YouTube）转化为结构化深度文档——支持纯文稿和完整 HTML 两种输出模式。

## 功能

- **多平台支持**：抖音、B站、YouTube
- **智能转录**：TeleSpeechASR（首选）→ SenseVoiceSmall → Groq Whisper → 本地 Whisper 四级降级
- **内容分析**：按视频自然结构分章，提炼问题/陷阱/步骤/结论
- **SVG 图解**：按内容类型动态生成（流程/关系/时间线/对比/决策树/因果链）
- **关键帧抽取**：界面类视频每章抽一帧作为视觉实证
- **离线 HTML**：单页自包含，内联 CSS/SVG，截图相对路径
- **纯文稿模式**：校正后的自然段落 + 逐段对照表 + 信息提炼

## 使用方法

在 WorkBuddy 中加载此 Skill 后：

```
# 深度分析（完整 HTML + SVG 图解 + 截图）
深度分析这个视频 https://v.douyin.com/xxxxx/

# 仅转录
把这个视频转成文稿 https://www.bilibili.com/video/xxxxx/
```

## 转录模型优先级

| 优先级 | 模型 | 特点 |
|--------|------|------|
| 1st | TeleSpeechASR | 中文精度最高，无 emoji 噪声 |
| 2nd | SenseVoiceSmall | 含 emoji，需后处理清洗 |
| 3rd | Groq Whisper | 支持时间戳，非中文场景 |
| 4th | 本地 Whisper | 离线兜底，带时间戳 |

## 依赖

- `yt-dlp` — 视频下载
- `ffmpeg` + `ffprobe` — 音视频处理
- 硅基流动 API Key — 云端转录（推荐）
- `whisper` — 本地转录（可选）
- Chrome/Chromium — 验证截图（可选）

## 安装

将本目录放入 `~/.workbuddy/skills/` 即可被 WorkBuddy 自动发现。

## 结构

```
Video2Doc/
├── SKILL.md                  # 主工作流（8 阶段完整指南）
├── README.md                 # 本文件
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
    └── template.html         # HTML 模板
```

## License

MIT
