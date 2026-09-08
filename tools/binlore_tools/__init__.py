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

# Load .env files early if present (sets HF_TOKEN, OPENROUTER_API_KEY, etc.)
_tools_root = Path(__file__).resolve().parents[1]
_repo_root = _tools_root.parent
for _env_path in [_tools_root / ".env", _repo_root / ".env"]:
    if _env_path.is_file():
        try:
            for _line in _env_path.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip("'\"")
                if _k not in os.environ:
                    os.environ[_k] = _v
        except Exception:
            pass

__version__ = "0.1.0"
