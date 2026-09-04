from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .paths import CHANNEL_VIDEOS_URL


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
    cmd = ["yt-dlp", *args]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise SystemExit(
            "yt-dlp not found. Install with: brew install yt-dlp"
        ) from e
    except subprocess.CalledProcessError as e:
        raise SystemExit(e.stderr.strip() or e.stdout.strip() or str(e)) from e
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
            raise SystemExit(f"No VODs found for {CHANNEL_VIDEOS_URL}")
        # Flat playlist often lacks dates — refresh full metadata
        return resolve_vod(vods[0].url, latest=False)

    assert url_or_latest is not None
    out = _run_yt_dlp(["--dump-json", "--no-download", "--no-playlist", url_or_latest])
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


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
