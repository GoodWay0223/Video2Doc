# Prerequisites and Environment Check

Run this check before starting any video analysis.

## Required Tools

| Tool | Min Version | Check Command | Install |
|------|-------------|---------------|---------|
| yt-dlp | any recent | `yt-dlp --version` | `brew install yt-dlp` or `pip install yt-dlp` |
| ffmpeg | 4.0+ | `ffmpeg -version` | `brew install ffmpeg` |
| ffprobe | (bundled with ffmpeg) | `ffprobe -version` | (comes with ffmpeg) |
| whisper | any recent | `python -c "import whisper"` | `pip install openai-whisper` |
| Python Playwright | any recent | `python -c "import playwright"` | `pip install playwright` |

## Quick Check

```bash
echo "=== Checking tools ==="
echo -n "yt-dlp:  "; which yt-dlp && yt-dlp --version || echo "NOT FOUND"
echo -n "ffmpeg:  "; which ffmpeg && ffmpeg -version | head -1 || echo "NOT FOUND"
echo -n "ffprobe: "; which ffprobe && ffprobe -version | head -1 || echo "NOT FOUND"
echo -n "whisper: "; which whisper && whisper --help | head -1 || echo "NOT FOUND"
echo -n "Chrome:  "; ls /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome 2>/dev/null && echo "FOUND" || echo "NOT FOUND"
```

## Optional Login State

Public Bilibili and Douyin routes normally work without cookies. For logged-in
quality or restricted content:

1. Log into the platform in Chrome
2. Export a Netscape-format `cookies.txt`, then configure
   `VIDEO2DOC_BILIBILI_COOKIES_FILE` or `VIDEO2DOC_DOUYIN_COOKIES_FILE`
3. For Douyin Playwright, optionally configure
   `VIDEO2DOC_DOUYIN_STORAGE_STATE` with an explicitly exported state file

Video2Doc never reads the live Chrome cookie database implicitly.

## Storage Requirements

- A 10-minute 1080p video: ~200 MB downloaded, + ~15 MB audio, + ~50 MB frames
- Plan for ~500 MB free space per video analysis
- The final HTML is typically 1-5 MB (mostly inline SVGs)
