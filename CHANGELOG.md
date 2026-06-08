# Changelog

## [v0.1.0] — 2026-06-08

### Added
- Initial release
- 4-tier transcription: TeleSpeechASR → SenseVoiceSmall → Groq → Local Whisper
- Multi-platform video download: Douyin, Bilibili, YouTube
- Full HTML output mode with SVG diagrams and keyframe screenshots
- Clean transcript mode with segment comparison table
- Audio extraction with ffprobe duration validation (±5%)
- Chapter-based content analysis (problem/trap/steps/conclusion)
- Post-processing: SenseVoiceSmall emoji stripping
- Playwright-based Douyin video capture (MediaRecorder fallback)
- GitHub release packaging: `Video2Doc-v{version}.zip`
- Multi-agent compatibility: WorkBuddy, OpenCLaw, Claude Code, Codex, Cline
