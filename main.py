import argparse, yt_dlp, sys, re, shutil
from pathlib import Path

DEFAULT_OUTPUT = Path.cwd()

# ─── ANSI helpers ────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
RED    = "\033[31m"
WHITE  = "\033[97m"
GRAY   = "\033[90m"

def c(text, *codes): return "".join(codes) + str(text) + RESET

# ─── clack-style primitives ──────────────────────────────────────────────────

def intro(title: str):
    cols = shutil.get_terminal_size().columns
    print()
    print(c("┌", GRAY) + c("─" * (cols - 2), GRAY) + c("┐", GRAY))
    pad = (cols - 2 - len(title)) // 2
    print(c("│", GRAY) + " " * pad + c(title, BOLD, WHITE) + " " * (cols - 2 - pad - len(title)) + c("│", GRAY))
    print(c("└", GRAY) + c("─" * (cols - 2), GRAY) + c("┘", GRAY))
    print()

def outro(message: str):
    print()
    print(c("◆", GREEN) + "  " + c(message, BOLD, WHITE))
    print()

def log_step(symbol: str, color: str, label: str, value: str = ""):
    line = c(symbol, color, BOLD) + "  " + c(label, WHITE)
    if value:
        line += "  " + c(value, GRAY)
    print(line)

def log_info(label: str, value: str = ""):   log_step("◇", CYAN,   label, value)
def log_success(label: str, value: str = ""): log_step("◆", GREEN,  label, value)
def log_warn(label: str, value: str = ""):   log_step("▲", YELLOW, label, value)
def log_error(label: str, value: str = ""):  log_step("✗", RED,    label, value)

def prompt(question: str, placeholder: str = "") -> str:
    print(c("◆", CYAN, BOLD) + "  " + c(question, WHITE))
    if placeholder:
        print(c("│", GRAY) + "  " + c(f"  ({placeholder})", GRAY))
    print(c("└", GRAY) + c("─▶", GRAY) + "  ", end="", flush=True)
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt

def confirm(question: str) -> bool:
    print(c("◆", CYAN, BOLD) + "  " + c(question, WHITE) + "  " + c("[y/N]", GRAY))
    print(c("└", GRAY) + c("─▶", GRAY) + "  ", end="", flush=True)
    try:
        return input().strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt

# ─── quality presets ─────────────────────────────────────────────────────────

QUALITY_PRESETS = [
    # (key, tag, max_height, label_base, format_str)
    ("1", "best",  None, "Best Quality",  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"),
    ("2", "1080p", 1080, "1080p", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]"),
    ("3", "720p",   720, "720p",  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]"),
    ("4", "480p",   480, "480p",  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]"),
    ("5", "audio", None, "Audio only", "bestaudio[ext=m4a]/bestaudio"),
]

def _preset_by_tag(value: str) -> dict | None:
    value = value.strip().lower()
    for key, tag, max_h, label, fmt in QUALITY_PRESETS:
        if value == key or value == tag:
            return {"key": key, "tag": tag, "max_height": max_h, "label": label, "format": fmt}
    return None

def resolve_quality_from_arg(value: str) -> dict:
    p = _preset_by_tag(value)
    if p:
        return p
    tags = ", ".join(t for _, t, *_ in QUALITY_PRESETS)
    raise ValueError(f"Unknown quality '{value}'. Choose from: {tags}  (or 1–5)")

# ─── format detection ─────────────────────────────────────────────────────────

def _needs_merge(info: dict, max_height: int | None) -> bool:
    """
    Returns True if yt-dlp will need to merge separate video+audio streams.

    Strategy: find the best video stream that would actually be selected
    (highest height within cap), then check if that *specific* stream also
    carries audio. If it doesn't, a merge is required.

    YouTube pre-muxed streams exist only at low resolutions (≤360p), so
    if the best available video is 720p/1080p/etc and it's video-only,
    we must merge — even though a 360p pre-muxed stream also exists.
    """
    formats = info.get("formats", [])
    if not formats:
        return False
    video_streams = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and (max_height is None or (f.get("height") or 0) <= max_height)
    ]
    if not video_streams:
        return False
    best_video = max(
        video_streams,
        key=lambda f: ((f.get("height") or 0), (f.get("tbr") or f.get("vbr") or 0))
    )
    return best_video.get("acodec") in (None, "none")

def _actual_height(info: dict, max_height: int | None) -> int | None:
    """Return the real resolution that will be downloaded."""
    formats = info.get("formats", [])
    candidates = [
        f for f in formats
        if (max_height is None or (f.get("height") or 0) <= max_height)
        and (f.get("vcodec") not in (None, "none"))
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    return best.get("height")

# ─── probe ───────────────────────────────────────────────────────────────────

def probe_video(url: str) -> dict:
    """Fetch video metadata without downloading."""
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        return ydl.extract_info(url, download=False)

# ─── quality menu (built from live probe data) ────────────────────────────────

def build_menu_rows(info: dict) -> list[dict]:
    """
    Build quality menu entries annotated with real merge/no-merge info
    from the probe result for this specific video.
    """
    rows = []
    for key, tag, max_h, label_base, fmt in QUALITY_PRESETS:
        if tag == "audio":
            rows.append({
                "key": key, "tag": tag, "label": label_base,
                "format": fmt, "max_height": None,
                "merge": False, "note": "m4a, no video",
                "actual_height": None,
            })
            continue
        merge = _needs_merge(info, max_h)
        actual_h = _actual_height(info, max_h)
        if actual_h:
            res_str = f"{actual_h}p"
        elif max_h:
            res_str = f"up to {max_h}p"
        else:
            res_str = "best available"
        if merge:
            note = "video + audio → FFmpeg merge  " + c("← slower", YELLOW)
        else:
            note = "single file, fast"
        rows.append({
            "key": key, "tag": tag, "label": label_base,
            "format": fmt, "max_height": max_h,
            "merge": merge, "note": note,
            "actual_height": actual_h,
            "res_str": res_str,
        })
    return rows

def select_quality_interactive(info: dict) -> dict:
    """Render quality menu with live format info and return chosen preset."""
    rows = build_menu_rows(info)
    print()
    print(c("◆", CYAN, BOLD) + "  " + c("Quality", WHITE))
    print(c("│", GRAY))
    for row in rows:
        if row["tag"] == "audio":
            line = f"  {row['key']}.  {row['label']}  " + c(f"({row['note']})", GRAY)
        else:
            line = (
                f"  {row['key']}.  {row['label']}"
                + c(f"  [{row.get('res_str', '')}]", GRAY)
                + "  "
                + row["note"]   # already contains ANSI colour for merge note
            )
        print(c("│", GRAY) + "  " + line)
    print(c("│", GRAY))
    print(c("└", GRAY) + c("─▶", GRAY) + "  ", end="", flush=True)
    key_map = {r["key"]: r for r in rows}
    while True:
        try:
            choice = input().strip()
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
        if choice == "":
            choice = "1"  # default to best quality
        if choice in key_map:
            row = key_map[choice]
            if row.get("merge"):
                print()
                log_warn(
                    "This quality requires a separate audio stream.",
                    "FFmpeg will merge them after download — takes a moment.",
                )
            return row
        print(c("│", GRAY) + "  " + c("  Please enter 1–5.", GRAY))
        print(c("└", GRAY) + c("─▶", GRAY) + "  ", end="", flush=True)

# ─── utils ───────────────────────────────────────────────────────────────────

def normalize_youtube_input(value: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return value
    if re.fullmatch(r"[\w-]{11}", value):
        return f"https://www.youtube.com/watch?v={value}"
    raise ValueError("Invalid YouTube URL or Video ID")

def format_bytes(value: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"

def format_eta(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s"

# ─── yt-dlp config ───────────────────────────────────────────────────────────

def create_ydl_opts(output_dir: str, hook, fmt: str) -> dict:
    return {
        "format": fmt,
        "outtmpl": str(Path(output_dir) / "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "prefer_ffmpeg": True,
        "postprocessor_args": ["-movflags", "+faststart"],
        "concurrent_fragment_downloads": 16,
        "external_downloader": "aria2c",
        "external_downloader_args": ["-x", "16", "-s", "16", "-k", "1M"],
        "retries": 10,
        "fragment_retries": 10,
        "http_chunk_size": 10485760,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
    }

# ─── progress renderer ───────────────────────────────────────────────────────

_last_lines = 0

def _clear_progress(n: int):
    for _ in range(n):
        print("\033[1A\033[2K", end="", flush=True)

def make_progress_hook(title_holder: list):
    cols = shutil.get_terminal_size().columns
    bar_width = min(40, cols - 30)

    def hook(d):
        global _last_lines
        if d["status"] == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed      = d.get("speed") or 0
            eta        = d.get("eta") or 0
            percent    = (downloaded / total) if total else 0
            filled   = int(bar_width * percent)
            bar      = c("█" * filled, GREEN) + c("░" * (bar_width - filled), GRAY)
            pct_str  = f"{percent * 100:5.1f}%"
            size_str = format_bytes(downloaded) + (f" / {format_bytes(total)}" if total else "")
            spd_str  = f"{format_bytes(speed)}/s" if speed else "---"
            eta_str  = format_eta(eta) if eta else "--"
            _clear_progress(_last_lines)
            lines = [
                c("│", GRAY) + "  " + c(title_holder[0] or "Downloading…", DIM),
                c("│", GRAY),
                c("│", GRAY) + "  " + bar + "  " + c(pct_str, BOLD, WHITE),
                c("│", GRAY) + "  " + c(f"↓ {spd_str}", CYAN) + "   " + c(f"ETA {eta_str}", GRAY) + "   " + c(size_str, GRAY),
                c("│", GRAY),
            ]
            print("\n".join(lines), flush=True)
            _last_lines = len(lines)
        elif d["status"] == "finished":
            _clear_progress(_last_lines)
            _last_lines = 0
            log_info("Merging video + audio…")
    return hook

# ─── download runner ─────────────────────────────────────────────────────────

def run_download(url: str, output_dir: str, fmt: str, info: dict | None = None):
    """Download video. Pass pre-fetched `info` to skip a second probe."""
    title_holder = [None]
    try:
        if info is None:
            info = probe_video(url)
        title_holder[0] = info.get("title", "")
        duration  = info.get("duration", 0)
        uploader  = info.get("uploader", "")
        log_info("Title",    c(title_holder[0], CYAN))
        log_info("Channel",  c(uploader, GRAY))
        if duration:
            m, s = divmod(duration, 60)
            log_info("Duration", c(f"{m}:{s:02d}", GRAY))
        log_info("Output",   c(output_dir, GRAY))
        print(c("│", GRAY))
        log_step("▶", CYAN, "Downloading…")
        print(c("│", GRAY))
    except Exception:
        log_info("Starting download…")
    hook = make_progress_hook(title_holder)
    with yt_dlp.YoutubeDL(create_ydl_opts(output_dir, hook, fmt)) as ydl:
        ydl.download([url])

# ─── interactive mode ─────────────────────────────────────────────────────────

def interactive_mode():
    intro("YouTube Downloader")
    last_output = str(DEFAULT_OUTPUT)
    while True:
        while True:
            raw = prompt("YouTube URL or Video ID", "https://youtu.be/…   or   'exit' to quit")
            if raw.lower() == "exit":
                outro("Bye!")
                return
            if not raw:
                log_warn("Input is required.")
                continue
            try:
                url = normalize_youtube_input(raw)
                break
            except ValueError as e:
                log_error(str(e))
        log_info("Fetching video info…")
        try:
            info = probe_video(url)
        except Exception as e:
            log_error("Could not fetch video info", str(e))
            continue
        print("\033[1A\033[2K", end="", flush=True)
        preset = select_quality_interactive(info)
        raw_out = prompt("Output folder", f"leave blank for  {last_output}")
        output_dir = raw_out if raw_out else last_output
        if not Path(output_dir).exists():
            if confirm("Folder doesn't exist. Create it?"):
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                log_success("Folder created.")
            else:
                log_warn("Using current directory instead.")
                output_dir = str(DEFAULT_OUTPUT)
        last_output = output_dir
        print()
        try:
            run_download(url, output_dir, preset["format"], info=info)
            log_success("Saved to", c(output_dir, GRAY))
        except Exception as e:
            log_error("Download failed", str(e))
        print()
        print(c("─" * shutil.get_terminal_size().columns, GRAY))
        print()

# ─── CLI mode ─────────────────────────────────────────────────────────────────

def cli_mode(raw_input: str, output_dir: str, preset: dict):
    url = normalize_youtube_input(raw_input)
    log_info("Fetching video info…")
    try:
        info = probe_video(url)
    except Exception as e:
        log_error("Could not fetch video info", str(e))
        sys.exit(1)
    print("\033[1A\033[2K", end="", flush=True)
    merge = _needs_merge(info, preset.get("max_height"))
    tag   = preset["tag"]
    if tag != "audio":
        actual_h = _actual_height(info, preset.get("max_height"))
        res_note = f"{actual_h}p" if actual_h else tag
        log_info("Quality", c(res_note, CYAN) + ("  " + c("(merge required)", YELLOW) if merge else ""))
        if merge:
            log_warn(
                "This quality uses separate video + audio streams.",
                "FFmpeg will merge them — download takes a moment longer.",
            )
    else:
        log_info("Quality", c("audio only", CYAN))
    run_download(url, output_dir, preset["format"], info=info)
    log_success("Download complete!", c(output_dir, GRAY))

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    print("\033]0;YouTube Downloader\007", end="", flush=True)
    parser = argparse.ArgumentParser(prog="ytdl", description="YouTube Downloader")
    parser.add_argument("input", nargs="?", help="YouTube URL or Video ID")
    parser.add_argument("--url", "--link", dest="url", help="YouTube URL or Video ID")
    parser.add_argument("--out", "-o", default=str(DEFAULT_OUTPUT), help="Output folder")
    parser.add_argument(
        "--quality", "-q",
        default="best",
        metavar="QUALITY",
        help="Quality preset: best, 1080p, 720p, 480p, audio  (default: best)",
    )
    args = parser.parse_args()
    raw_input = args.url or args.input
    try:
        if raw_input:
            intro("YouTube Downloader")
            try:
                preset = resolve_quality_from_arg(args.quality)
            except ValueError as e:
                log_error(str(e))
                sys.exit(1)
            cli_mode(raw_input, args.out, preset)
            outro(f"Saved to  {args.out}")
        else:
            interactive_mode()
    except KeyboardInterrupt:
        print()
        log_warn("Cancelled.")
        print()

if __name__ == "__main__":
    main()
