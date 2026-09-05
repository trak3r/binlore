from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .clean import execute_clean, find_cleanable_runs
from .extract import DEFAULT_MODEL, extract_lore_from_vod
from .ingest import ingest
from .paths import RUNS_DIR
from .vods import format_duration, list_vods


def _resolve_target_vod_id(target: str | None, *, latest: bool = False) -> str:
    if latest or not target:
        # Find most recently modified run directory with a transcript.txt
        runs = [d for d in RUNS_DIR.iterdir() if d.is_dir() and (d / "transcript.txt").exists()]
        if not runs:
            raise SystemExit("No completed runs found in tools/runs/. Ingest a VOD first with `binlore ingest`.")
        runs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        return runs[0].name

    target = target.strip()
    # Handle full URL e.g. https://www.twitch.tv/videos/2863722826
    if "twitch.tv/videos/" in target:
        part = target.split("twitch.tv/videos/")[-1].split("?")[0].strip("/")
        if part.startswith("v"):
            part = part[1:]
        return part

    if target.startswith("v") and target[1:].isdigit():
        return target[1:]

    return target


def cmd_vods(args: argparse.Namespace) -> int:
    vods = list_vods(limit=args.limit)
    if not vods:
        print("No VODs found.", file=sys.stderr)
        return 1
    for v in vods:
        date = v.date_str or "?"
        print(f"{v.id}\t{date}\t{format_duration(v.duration)}\t{v.title}\t{v.url}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    if not args.latest and not args.url:
        print("Provide a VOD URL or --latest", file=sys.stderr)
        return 2
    ingest(
        url=args.url,
        latest=args.latest,
        model=args.model,
        skip_download=args.skip_download,
        skip_transcribe=args.skip_transcribe,
        force_episode=args.force_episode,
    )
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    vod_id = _resolve_target_vod_id(args.target, latest=args.latest)

    result = extract_lore_from_vod(
        vod_id=vod_id,
        model=args.model,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )

    if args.dry_run:
        return 0

    print("\n--- [Extraction Summary] ---")
    if "episode_summary" in result:
        print(f"Summary: {result['episode_summary']}\n")

    segments = result.get("segments", [])
    print(f"Segments identified ({len(segments)}):")
    for s in segments:
        print(f"  [{s.get('start')} - {s.get('end')}] {s.get('title')}: {s.get('notes', '')}")

    characters = result.get("characters", [])
    print(f"\nCharacters detected ({len(characters)}):")
    for c in characters:
        name = c.get("canonical_name") or c.get("name")
        spk = "speaking" if c.get("speaking") else "mentioned"
        print(f"  - {name} ({spk}) — {c.get('notes', '')}")

    storylines = result.get("storylines", [])
    if storylines:
        print(f"\nStoryline developments ({len(storylines)}):")
        for st in storylines:
            ts = f"[{st['timestamp']}] " if st.get("timestamp") else ""
            print(f"  - {ts}{st.get('storyline')}: {st.get('beat')}")

    lore = result.get("lore_notes", [])
    if lore:
        print(f"\nLore notes recorded ({len(lore)}):")
        for l in lore:
            ts = f"[{l['timestamp']}] " if l.get("timestamp") else ""
            print(f"  - {ts}{l.get('entity')}: {l.get('fact')}")

    print("----------------------------\n")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    targets = find_cleanable_runs(
        target_vod_id=args.target,
        keep_latest=args.keep,
        force=args.force,
    )
    if not targets:
        print("No media files found to clean.")
        return 0

    execute_clean(targets, dry_run=args.dry_run)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="binlore",
        description="Binlore VOD ingest, transcript, and lore extraction tools",
    )
    p.add_argument("--version", action="version", version=f"binlore {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    vods = sub.add_parser("vods", help="List recent caseblackwell VODs")
    vods.add_argument("--limit", type=int, default=15, help="Max VODs to list (default 15)")
    vods.set_defaults(func=cmd_vods)

    ing = sub.add_parser("ingest", help="Download audio, transcribe, write episode stub")
    ing.add_argument("url", nargs="?", help="Twitch VOD URL")
    ing.add_argument(
        "--latest",
        action="store_true",
        help="Ingest the newest channel VOD",
    )
    ing.add_argument(
        "--model",
        default="small",
        help="faster-whisper model size (default: small)",
    )
    ing.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse audio.* already in tools/runs/<id>/",
    )
    ing.add_argument(
        "--skip-transcribe",
        action="store_true",
        help="Only download/meta/episode stub (no Whisper)",
    )
    ing.add_argument(
        "--force-episode",
        action="store_true",
        help="Overwrite existing episode stub for this date",
    )
    ing.set_defaults(func=cmd_ingest)

    ext = sub.add_parser("extract", help="Extract segments, characters, and lore using OpenRouter")
    ext.add_argument("target", nargs="?", help="VOD ID or Twitch URL (defaults to latest ingested run)")
    ext.add_argument(
        "--latest",
        action="store_true",
        help="Extract lore from the most recently ingested VOD",
    )
    ext.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenRouter model ID (default: {DEFAULT_MODEL})",
    )
    ext.add_argument(
        "--timeout",
        type=float,
        default=75.0,
        help="Timeout in seconds per model before falling back (default: 75)",
    )
    ext.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview prompt and token estimate without calling OpenRouter",
    )
    ext.set_defaults(func=cmd_extract)

    clean = sub.add_parser("clean", help="Delete downloaded media files (audio/video) to reclaim disk space")
    clean.add_argument("target", nargs="?", help="VOD ID or Twitch URL (defaults to all completed runs)")
    clean.add_argument(
        "--keep",
        type=int,
        default=0,
        help="Number of latest runs to keep media files for (default: 0 = delete all)",
    )
    clean.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview media files and space to be freed without deleting",
    )
    clean.add_argument(
        "--force",
        action="store_true",
        help="Clean media even if transcription is missing or incomplete",
    )
    clean.set_defaults(func=cmd_clean)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
