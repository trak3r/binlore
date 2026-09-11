from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import CHANNEL_VIDEOS_URL, TOOLS_ROOT

YOUTUBE_COOKIES_HINT = (
    "YouTube blocked this IP as a bot. Export cookies from a logged-in browser "
    "and put them at tools/cookies.txt, or set YTDLP_COOKIES / "
    "YTDLP_COOKIES_FROM_BROWSER in tools/.env. "
    "See https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies"
)

_AUTH_LOGGED = False


def _cookies_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = TOOLS_ROOT / path
    return path.resolve()


def youtube_bot_check(text: str) -> bool:
    return "not a bot" in text.lower()


def yt_dlp_extra_args() -> list[str]:
    """Cookie / extractor args so YouTube accepts datacenter IPs.

    Precedence:
      1. YTDLP_COOKIES_FROM_BROWSER (e.g. chrome, firefox, safari, chrome:Profile 1)
      2. YTDLP_COOKIES path, or tools/cookies.txt if that file exists
      3. YTDLP_EXTRACTOR_ARGS if set (appended either way)
    """
    global _AUTH_LOGGED
    args: list[str] = []

    browser = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "").strip()
    cookies_raw = os.environ.get("YTDLP_COOKIES", "").strip()
    default_cookies = TOOLS_ROOT / "cookies.txt"
    cookies_file = _cookies_path(cookies_raw) if cookies_raw else (
        default_cookies if default_cookies.is_file() else None
    )

    if browser:
        args.extend(["--cookies-from-browser", browser])
        source = f"browser {browser}"
    elif cookies_file is not None:
        if not cookies_file.is_file():
            raise RuntimeError(
                f"YTDLP_COOKIES is set but file not found: {cookies_file}\n"
                "Export YouTube cookies to that path, or unset YTDLP_COOKIES."
            )
        args.extend(["--cookies", str(cookies_file)])
        source = f"cookies file {cookies_file}"
    else:
        source = ""

    extractor_args = os.environ.get("YTDLP_EXTRACTOR_ARGS", "").strip()
    if extractor_args:
        args.extend(["--extractor-args", extractor_args])

    if args and not _AUTH_LOGGED:
        _AUTH_LOGGED = True
        parts = [p for p in (source, "extractor-args" if extractor_args else "") if p]
        print(f"yt-dlp: using {' + '.join(parts)}", flush=True)

    return args


def get_yt_dlp_cmd() -> list[str]:
    """Find the best command to invoke yt-dlp.

    Checks in order:
    1. PATH via shutil.which('yt-dlp')
    2. Active virtual environment bin directory
    3. tools/.venv bin directory
    4. Python module invocation via sys.executable -m yt_dlp

    Cookie/auth flags from the environment are appended so every caller
    (ingest, catalog resolve, screencap) gets the same YouTube session.
    """
    # 1. System or active PATH
    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        return [ytdlp, *yt_dlp_extra_args()]

    # 2. Virtual environment bin (active or current python interpreter)
    bin_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    venv_dir = "Scripts" if os.name == "nt" else "bin"
    venv_bin = Path(sys.prefix) / venv_dir / bin_name
    if venv_bin.is_file() and os.access(venv_bin, os.X_OK):
        return [str(venv_bin), *yt_dlp_extra_args()]

    # 3. tools/.venv bin directory
    tools_venv_bin = TOOLS_ROOT / ".venv" / venv_dir / bin_name
    if tools_venv_bin.is_file() and os.access(tools_venv_bin, os.X_OK):
        return [str(tools_venv_bin), *yt_dlp_extra_args()]

    # 4. As an importable python module
    try:
        import yt_dlp  # noqa: F401

        return [sys.executable, "-m", "yt_dlp", *yt_dlp_extra_args()]
    except ImportError:
        pass

    raise RuntimeError(
        "yt-dlp not found.\n"
        "Please install it in your Python environment:\n"
        "  pip install yt-dlp\n"
        "Or install via your system package manager:\n"
        "  sudo apt update && sudo apt install -y yt-dlp   # Linux (Ubuntu/Debian)\n"
        "  brew install yt-dlp                            # macOS"
    )


@dataclass
class Vod:
    id: str
    title: str
    url: str
    duration: float | None
    timestamp: int | None  # unix seconds

    @property
    def aired_at(self) -> datetime | None:
        if self.timestamp is None:
            return None
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    @property
    def date_str(self) -> str | None:
        if self.aired_at is None:
            return None
        return self.aired_at.date().isoformat()


def _run_yt_dlp(args: list[str]) -> str:
    cmd = [*get_yt_dlp_cmd(), *args]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "yt-dlp not found.\n"
            "Please install it: pip install yt-dlp (or brew install yt-dlp / sudo apt install yt-dlp)"
        ) from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        if youtube_bot_check(err):
            err = f"{err}\n{YOUTUBE_COOKIES_HINT}"
        raise RuntimeError(err) from e
    return proc.stdout


def list_vods(limit: int = 20) -> list[Vod]:
    """List recent channel VODs (newest first)."""
    # flat-playlist + dump-json: one JSON object per line
    out = _run_yt_dlp(
        [
            "--flat-playlist",
            "--dump-json",
            "--playlist-end",
            str(limit),
            CHANNEL_VIDEOS_URL,
        ]
    )
    vods: list[Vod] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        data: dict[str, Any] = json.loads(line)
        vid = str(data.get("id") or "")
        if not vid:
            continue
        # Normalize Twitch ids (sometimes prefixed with "v")
        if vid.startswith("v") and vid[1:].isdigit():
            vid = vid[1:]
        url = data.get("url") or data.get("webpage_url")
        if not url or not str(url).startswith("http"):
            url = f"https://www.twitch.tv/videos/{vid}"
        elif "/videos/v" in str(url):
            url = str(url).replace("/videos/v", "/videos/")

        ts = data.get("timestamp") or data.get("release_timestamp")
        upload = data.get("upload_date")  # YYYYMMDD
        if ts is None and upload and len(str(upload)) == 8:
            try:
                dt = datetime.strptime(str(upload), "%Y%m%d").replace(tzinfo=timezone.utc)
                ts = int(dt.timestamp())
            except ValueError:
                pass

        vods.append(
            Vod(
                id=vid,
                title=str(data.get("title") or "(untitled)"),
                url=str(url),
                duration=data.get("duration"),
                timestamp=ts,
            )
        )
    return vods


def resolve_vod(url_or_latest: str | None, *, latest: bool) -> Vod:
    if latest or url_or_latest in (None, "", "--latest"):
        vods = list_vods(limit=1)
        if not vods:
            raise RuntimeError(f"No VODs found for {CHANNEL_VIDEOS_URL}")
        # Flat playlist often lacks dates — refresh full metadata
        return resolve_vod(vods[0].url, latest=False)

    assert url_or_latest is not None
    target_url = url_or_latest
    if target_url.isdigit() or (target_url.startswith("v") and target_url[1:].isdigit()):
        target_url = f"https://www.twitch.tv/videos/{target_url.lstrip('v')}"
    elif not target_url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={target_url}"

    out = _run_yt_dlp(["--dump-json", "--no-download", "--no-playlist", target_url])
    data = json.loads(out.splitlines()[0])
    vid = str(data["id"])
    if vid.startswith("v") and vid[1:].isdigit():
        vid = vid[1:]
    ts = data.get("timestamp") or data.get("release_timestamp")
    upload = data.get("upload_date")
    if ts is None and upload and len(str(upload)) == 8:
        try:
            dt = datetime.strptime(str(upload), "%Y%m%d").replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
        except ValueError:
            pass
    return Vod(
        id=vid,
        title=str(data.get("title") or "(untitled)"),
        url=str(data.get("webpage_url") or url_or_latest),
        duration=data.get("duration"),
        timestamp=ts,
    )


def vod_from_catalog_entry(entry: dict[str, Any], *, prefer_source: str = "twitch") -> Vod:
    """Build a Vod dataclass directly from a youtube_catalog.json entry."""
    twitch_id = entry.get("twitch_id")
    twitch_url = entry.get("twitch_url")
    yt_id = entry.get("yt_id") or entry.get("id")
    yt_url = entry.get("yt_url") or (f"https://www.youtube.com/watch?v={yt_id}" if yt_id else "")

    if prefer_source == "twitch" and twitch_url:
        vid = str(twitch_id)
        url = str(twitch_url)
    else:
        vid = str(yt_id or twitch_id or "")
        url = str(yt_url or twitch_url or "")

    ts = None
    date_str = entry.get("date")
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
        except Exception:
            pass

    return Vod(
        id=vid,
        title=str(entry.get("title") or "(untitled)"),
        url=url,
        duration=entry.get("duration_seconds"),
        timestamp=ts,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
