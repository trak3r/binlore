#!/usr/bin/env python3
"""
tools/process_all.py — thin wrapper around ``binlore process-all``.

Prefer ``./binlore`` (full pipeline) from the repo root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

VENV_DIR = (TOOLS_DIR / ".venv").resolve()
VENV_BIN = TOOLS_DIR / ".venv" / ("Scripts" if os.name == "nt" else "bin")
VENV_PYTHON = VENV_BIN / ("python3.exe" if os.name == "nt" else "python3")

if VENV_BIN.is_dir():
    _bin_str = str(VENV_BIN)
    if _bin_str not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = f"{_bin_str}{os.pathsep}{os.environ.get('PATH', '')}"

if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_DIR:
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

from binlore_tools.cli import main as binlore_main


def main() -> None:
    # Mimic ``./binlore process-all …``
    binlore_main(["process-all", *sys.argv[1:]])


if __name__ == "__main__":
    main()
