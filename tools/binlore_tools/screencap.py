from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .paths import REPO_ROOT, RUNS_DIR, TOOLS_ROOT

SCREENCAPS_DIR = TOOLS_ROOT / "screencaps"


def get_stream_url(vod_url_or_id: str) -> str:
    """Fetch direct m3u8 stream URL using yt-dlp."""
    if vod_url_or_id.isdigit():
        target = f"https://www.twitch.tv/videos/{vod_url_or_id}"
    else:
        target = vod_url_or_id

    cmd = ["yt-dlp", "-g", target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        url = proc.stdout.strip().splitlines()[0]
        return url
    except Exception as e:
        raise RuntimeError(f"Failed to resolve stream URL with yt-dlp: {e}")


def extract_frame(
    stream_url: str,
    timestamp: str,
    output_path: Path,
    *,
    quality: int = 2,
) -> Path:
    """Extract a single frame from stream at timestamp using ffmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert MM:SS to HH:MM:SS if needed
    parts = timestamp.split(":")
    if len(parts) == 2:
        ts = f"00:{parts[0].zfill(2)}:{parts[1].zfill(2)}"
    elif len(parts) == 3:
        ts = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
    else:
        ts = timestamp

    cmd = [
        "ffmpeg",
        "-ss",
        ts,
        "-i",
        stream_url,
        "-frames:v",
        "1",
        "-q:v",
        str(quality),
        "-y",
        str(output_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg frame extraction failed at {timestamp}: {proc.stderr[-300:]}")

    return output_path


def upload_to_release(
    file_paths: list[Path],
    *,
    release_tag: str = "media-assets",
) -> None:
    """Upload screencap files to a GitHub release."""
    cmd = [
        "gh",
        "release",
        "upload",
        release_tag,
        *[str(p) for p in file_paths],
        "--clobber",
        "-R",
        "trak3r/binlore",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh release upload failed: {proc.stderr}")
    print(f"✓ Uploaded {len(file_paths)} assets to GitHub release '{release_tag}'")
