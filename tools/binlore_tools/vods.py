from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import CHANNEL_VIDEOS_URL, TOOLS_ROOT


# YouTube does not publish a fixed bot-check TTL. Community + yt-dlp docs:
# - Session rate-limit ("try again later"): up to ~1 hour
# - Temporary IP bot-check: often clears in ~1–12 hours if you stop hammering
# - Heavy / datacenter blocks: days, or until IP changes
DEFAULT_BOT_COOLDOWN_INITIAL_S = 3600  # 1 hour before first probe
DEFAULT_BOT_COOLDOWN_PROBE_S = 1800  # 30 minutes between probes


def _env_seconds(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(60, int(float(raw)))
    except ValueError:
        return default


def youtube_bot_cooldown_hint() -> str:
    """Explain the cooldown (no published fixed timeout)."""
    initial = _env_seconds("YTDLP_BOT_COOLDOWN_INITIAL", DEFAULT_BOT_COOLDOWN_INITIAL_S)
    probe = _env_seconds("YTDLP_BOT_COOLDOWN_PROBE", DEFAULT_BOT_COOLDOWN_PROBE_S)
    return f"""YouTube bot-check on this host (temporary IP / session throttle).

There is NO published fixed timeout. Observed behavior:
  • Official yt-dlp session rate-limit message: "up to an hour"
  • Temporary bot-checks often clear in ~1–12 hours if you STOP retrying
  • Hammering during a block can extend it; datacenter IPs get hit hardest

This batch will sleep and probe until YouTube accepts requests again
(initial wait {initial}s / {initial / 3600:.1f}h, then every {probe}s / {probe / 60:.0f}m).
Override with YTDLP_BOT_COOLDOWN_INITIAL / YTDLP_BOT_COOLDOWN_PROBE in tools/.env.
"""


class YoutubeBotCheckError(RuntimeError):
    """YouTube rejected the client as a bot; wait/cooldown before retrying."""


_YTDLP_OPTS_LOGGED = False


def youtube_bot_check(text: str) -> bool:
    return "not a bot" in text.lower()


def interruptible_sleep(seconds: float, *, is_interrupted) -> bool:
    """Sleep up to `seconds`. Returns False if interrupted."""
    deadline = time.time() + max(0.0, seconds)
    while time.time() < deadline:
        if is_interrupted():
            return False
        time.sleep(min(5.0, max(0.0, deadline - time.time())))
    return not is_interrupted()


def probe_youtube_clear(url: str) -> bool:
    """True if a lightweight metadata fetch is not bot-blocked."""
    cmd = [
        *get_yt_dlp_cmd(),
        "--dump-json",
        "--no-download",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return True
    err = (proc.stderr or proc.stdout or "")
    # Any non-bot failure means the IP throttle cleared; let the real download decide.
    return not youtube_bot_check(err)


def wait_for_youtube_clear(
    url: str,
    *,
    log,
    is_interrupted,
) -> bool:
    """Sleep/probe until YouTube stops bot-checking `url`. Returns False if interrupted."""
    initial = _env_seconds("YTDLP_BOT_COOLDOWN_INITIAL", DEFAULT_BOT_COOLDOWN_INITIAL_S)
    probe = _env_seconds("YTDLP_BOT_COOLDOWN_PROBE", DEFAULT_BOT_COOLDOWN_PROBE_S)
    log(youtube_bot_cooldown_hint())
    started = time.time()
    wait_s = float(initial)
    attempt = 0
    while True:
        if is_interrupted():
            return False
        attempt += 1
        resume_at = datetime.now(tz=timezone.utc) + timedelta(seconds=wait_s)
        log(
            f"YouTube cooldown: sleeping {wait_s / 60:.0f}m "
            f"(probe #{attempt}; resume ~{resume_at.strftime('%Y-%m-%d %H:%M:%S UTC')}). "
            "Ctrl+C to abort."
        )
        if not interruptible_sleep(wait_s, is_interrupted=is_interrupted):
            return False
        log(f"YouTube cooldown: probing access for {url}…")
        try:
            if probe_youtube_clear(url):
                elapsed = time.time() - started
                log(
                    f"YouTube cooldown cleared after {elapsed / 60:.1f} minutes. "
                    "Retrying download."
                )
                return True
        except Exception as e:
            log(f"YouTube probe error ({e}); will keep waiting.")
        wait_s = float(probe)


def yt_dlp_extra_args() -> list[str]:
    """Pacing / extractor args for YouTube (reduces bot-check trips)."""
    global _YTDLP_OPTS_LOGGED
    args: list[str] = []

    extractor_args = os.environ.get("YTDLP_EXTRACTOR_ARGS", "").strip()
    if extractor_args:
        args.extend(["--extractor-args", extractor_args])

    # Pace metadata requests; bursts trip YouTube bot-checks faster than byte downloads.
    sleep_req = os.environ.get("YTDLP_SLEEP_REQUESTS", "1").strip()
    if sleep_req and sleep_req not in {"0", "false", "off"}:
        args.extend(["--sleep-requests", sleep_req])

    if args and not _YTDLP_OPTS_LOGGED:
        _YTDLP_OPTS_LOGGED = True
        parts: list[str] = []
        if extractor_args:
            parts.append("extractor-args")
        if sleep_req and sleep_req not in {"0", "false", "off"}:
            parts.append(f"sleep-requests={sleep_req}")
        if parts:
            print(f"yt-dlp: using {' + '.join(parts)}", flush=True)

    return args


def get_yt_dlp_cmd() -> list[str]:
    """Find the best command to invoke yt-dlp.

    Checks in order:
    1. PATH via shutil.which('yt-dlp')
    2. Active virtual environment bin directory
    3. tools/.venv bin directory
    4. Python module invocation via sys.executable -m yt_dlp
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
            raise YoutubeBotCheckError(
                "YouTube bot-check (temporary). Batch will sleep and probe until clear."
            ) from e
        raise RuntimeError(err) from e
    return proc.stdout


def run_yt_dlp(cmd: list[str]) -> None:
    """Run yt-dlp, streaming stderr live. Raise YoutubeBotCheckError on bot-check."""
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    err_lines: list[str] = []
    if proc.stderr is not None:
        for line in proc.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            err_lines.append(line)
    rc = proc.wait()
    if rc == 0:
        return
    err = "".join(err_lines)
    if youtube_bot_check(err):
        raise YoutubeBotCheckError(
            "YouTube bot-check (temporary). Batch will sleep and probe until clear."
        )
    raise subprocess.CalledProcessError(rc, cmd, stderr=err)


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
