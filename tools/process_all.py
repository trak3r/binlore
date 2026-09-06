#!/usr/bin/env python3
"""
tools/process_all.py — Unattended Batch Processor for Barely Informed News (BIN) Lore Wiki

Loops through all unprocessed episodes in the catalog, performs audio download,
transcription with faster-whisper, lore extraction via OpenRouter, wiki page generation,
and catalog index synchronization.

Features strict disk hygiene:
- Automatically and immediately deletes 100-300MB audio files upon transcription completion.
- Reclaims transient / incomplete download files on error or shutdown.
- Pre-flight disk space monitoring to prevent filling the host filesystem.
- Safe to run in background (nohup, tmux, systemd) with graceful SIGINT/SIGTERM handling.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add tools directory to sys.path
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# If running outside tools/.venv, auto-switch to venv python if present
VENV_DIR = (TOOLS_DIR / ".venv").resolve()
VENV_PYTHON = TOOLS_DIR / ".venv" / "bin" / "python3"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_DIR:
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

from binlore_tools.batch import check_backlog_status, run_batch_processing
from binlore_tools.extract import DEFAULT_MODEL
from binlore_tools.paths import RUNS_DIR


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="process_all.py",
        description="Autonomous unattended batch processing for BIN Lore Wiki",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of unprocessed episodes to process (default: all)",
    )
    p.add_argument(
        "--oldest-first",
        action="store_true",
        help="Process backlog from oldest to newest (default: newest first)",
    )
    p.add_argument(
        "--model",
        default="small",
        help="faster-whisper model size: tiny, base, small, medium, large-v3 (default: small)",
    )
    p.add_argument(
        "--openrouter-model",
        default=DEFAULT_MODEL,
        help=f"OpenRouter model slug for lore extraction (default: {DEFAULT_MODEL})",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Cool-down delay in seconds between processing episodes (default: 5.0)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="OpenRouter LLM extraction timeout in seconds (default: 90.0)",
    )
    p.add_argument(
        "--min-disk-gb",
        type=float,
        default=1.0,
        help="Minimum free disk space in GB required before ingesting (default: 1.0)",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="Print current backlog status (ingested vs remaining) and exit",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview unprocessed episodes queue without downloading or modifying files",
    )
    p.add_argument(
        "--no-clean-existing",
        action="store_true",
        help="Do not sweep existing runs for lingering media files before starting",
    )
    p.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep audio files after transcription (warning: consumes high disk space)",
    )
    p.add_argument(
        "--skip-extract",
        action="store_true",
        help="Ingest and transcribe only, skipping LLM extraction and wiki updates",
    )
    p.add_argument(
        "--no-skip-drafts",
        action="store_true",
        help="Do not skip episodes marked with draft: true in content/episodes/",
    )
    p.add_argument(
        "--build-quartz",
        action="store_true",
        help="Run `npx quartz build` after batch run completes",
    )
    p.add_argument(
        "--git-commit",
        action="store_true",
        help="Create a local git commit for each processed episode",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=RUNS_DIR / "batch.log",
        help="Log file destination (default: tools/runs/batch.log)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    if args.status:
        st = check_backlog_status()
        print("\n--- [BIN Lore Backlog Status] ---")
        print(f"Total catalog streams: {st['total_streams']}")
        print(f"Ingested & Extracted:  {st['ingested_count']}")
        print(f"Remaining in Backlog:  {st['backlog_count']} ({st['percent_complete']} complete)")
        print(f"Free Disk Space:       {st['free_disk_gb']}")
        if st.get("next_unprocessed"):
            nx = st["next_unprocessed"]
            print(f"Next in queue:         {nx.get('date')} — {nx.get('title')}")
        print("---------------------------------\n")
        return 0

    return run_batch_processing(
        limit=args.limit,
        oldest_first=args.oldest_first,
        whisper_model=args.model,
        openrouter_model=args.openrouter_model,
        delay=args.delay,
        timeout=args.timeout,
        clean_audio=not args.keep_audio,
        clean_existing=not args.no_clean_existing,
        skip_extract=args.skip_extract,
        skip_drafts=not args.no_skip_drafts,
        build_quartz=args.build_quartz,
        git_commit=args.git_commit,
        min_disk_gb=args.min_disk_gb,
        log_file=args.log_file,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
