# Prerequisites and Environment Check

Run this check before starting any video analysis.

## Required Tools

| Tool | Min Version | Check Command | Install |
|------|-------------|---------------|---------|
| yt-dlp | any recent | `yt-dlp --version` | `brew install yt-dlp` or `pip install yt-dlp` |
| ffmpeg | 4.0+ | `ffmpeg -version` | `brew install ffmpeg` |
| ffprobe | (bundled with ffmpeg) | `ffprobe -version` | (comes with ffmpeg) |
| whisper | any recent | `whisper --help` | `pip install openai-whisper` |
| Chrome | any recent | `ls /Applications/Google\ Chrome.app` | Download from google.com |

## Quick Check

```bash
echo "=== Checking tools ==="
echo -n "yt-dlp:  "; which yt-dlp && yt-dlp --version || echo "NOT FOUND"
echo -n "ffmpeg:  "; which ffmpeg && ffmpeg -version | head -1 || echo "NOT FOUND"
echo -n "ffprobe: "; which ffprobe && ffprobe -version | head -1 || echo "NOT FOUND"
echo -n "whisper: "; which whisper && whisper --help | head -1 || echo "NOT FOUND"
echo -n "Chrome:  "; ls /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome 2>/dev/null && echo "FOUND" || echo "NOT FOUND"
```

## Cookie Setup

For Bilibili and Douyin, cookies are often required for full quality:

1. Log into the platform in Chrome
2. Use `--cookies-from-browser chrome` with yt-dlp
3. If that fails, export cookies manually:
   - Install a browser extension like "Get cookies.txt"
   - Export to `cookies.txt`
   - Use `--cookies cookies.txt`

## Storage Requirements

- A 10-minute 1080p video: ~200 MB downloaded, + ~15 MB audio, + ~50 MB frames
- Plan for ~500 MB free space per video analysis
- The final HTML is typically 1-5 MB (mostly inline SVGs)
