"""Binlore VOD ingest and transcript tools."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure virtualenv bin directory is in PATH for child subprocesses (yt-dlp, ffmpeg, etc.)
_venv_bin = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
if _venv_bin.is_dir():
    _path = os.environ.get("PATH", "")
    _bin_str = str(_venv_bin)
    if _bin_str not in _path.split(os.pathsep):
        os.environ["PATH"] = f"{_bin_str}{os.pathsep}{_path}"

__version__ = "0.1.0"
