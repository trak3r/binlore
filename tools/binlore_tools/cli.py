from __future__ import annotations

import argparse
import sys

from . import __version__
from .ingest import ingest
from .vods import format_duration, list_vods


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="binlore",
        description="Binlore VOD ingest and transcript tools",
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

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
