<div align="center">

# ytdl

**Fast YouTube downloader. Terminal-native. No nonsense.**

Built with Python + [yt-dlp](https://github.com/yt-dlp/yt-dlp) · UI styled after [@clack/prompts](https://github.com/natemoo-re/clack)

</div>

---

## What it does

- Downloads YouTube videos to MP4 in the quality you choose
- Runs in interactive mode (guided prompts) or CLI mode (one-liner)
- Accepts YouTube URLs, youtu.be links, or bare 11-character Video IDs
- Merges video + audio via FFmpeg with `+faststart` for streaming compatibility
- Accelerates downloads via aria2c — 16 parallel connections by default
- Live progress bar: speed, ETA, file size — rendered inline, no flicker

---

## Requirements

| Tool | What for | Install |
|------|----------|---------|
| Python 3.10+ | Runtime | [python.org](https://www.python.org/) |
| FFmpeg | Merge video + audio | [ffmpeg.org](https://ffmpeg.org/) |
| aria2 | Parallel download acceleration | [github.com/aria2](https://github.com/aria2/aria2/releases) |

Add `ffmpeg.exe` and `aria2c.exe` to your system PATH, then verify:

```bash
ffmpeg -version
aria2c -v
```

Install Python packages:

```bash
pip install -r requirements.txt
```

---

## Usage

### Interactive mode

Run without arguments — prompts for URL, quality, and output folder, then loops until you type `exit`:

```bash
python main.py
```

You'll see a menu like this:

```
◆  Quality
│
│    1.  Best  (video + m4a, merged via FFmpeg)  ← slower download
│    2.  1080p (mp4, single file)
│    3.  720p  (mp4, single file)
│    4.  480p  (mp4, lighter)
│    5.  Audio only  (m4a / best audio)
│
└─▶
```

---

### CLI mode

```bash
# Bare Video ID — uses best quality by default
python main.py eoXKfaWrCE0

# Full URL
python main.py https://youtu.be/eoXKfaWrCE0

# --url / --link flag
python main.py --url eoXKfaWrCE0
python main.py --link https://youtube.com/watch?v=eoXKfaWrCE0

# Custom output folder
python main.py eoXKfaWrCE0 --out D:/Videos

# Choose quality
python main.py eoXKfaWrCE0 --quality 1080p
python main.py eoXKfaWrCE0 -q 720p
python main.py eoXKfaWrCE0 -q audio
```

---

### Quality presets

| Flag | What you get | Note |
|------|-------------|------|
| `best` | Highest available video + best m4a audio | Merged via FFmpeg — **slower download** |
| `1080p` | Up to 1080p MP4 | Pre-muxed when available, faster |
| `720p` | Up to 720p MP4 | Good balance of size and quality |
| `480p` | Up to 480p MP4 | Smaller file, faster download |
| `audio` | Best audio only (m4a) | No video track |

> **Why is "Best" slower?**
> YouTube serves its highest-quality video and audio as **separate streams** — there's no single file that contains both. ytdl downloads both streams in parallel, then FFmpeg stitches them together. This is the same method used by every serious downloader; the merge step just adds a few extra seconds at the end.
> If you want a single-pass download with no merge, pick `1080p` or lower — those use pre-muxed MP4 streams when available.

---

## Build EXE (Windows)

Use the included `ytdl.spec`:

```bash
pyinstaller ytdl.spec
```

Output: `dist\ytdl\ytdl.exe`

Make sure these files are present before building:

```
main.py
ytdl.spec
favicon.ico
```

> `--onedir` is used (not `--onefile`) — same result, no temp-extraction delay on launch.

---

## Notes

- Some age-restricted or region-locked videos require browser cookies. yt-dlp supports `--cookies-from-browser` if needed.
- MP4 Fast Start (`+faststart`) is always enabled — files are safe to stream from a server or media player before fully downloaded.
- The tool remembers your last output folder within a session (interactive mode only).

---

## License

Personal use only.
