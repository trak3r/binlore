from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .paths import RUNS_DIR

MEDIA_EXTENSIONS = {
    ".m4a",
    ".mp3",
    ".opus",
    ".webm",
    ".wav",
    ".mp4",
    ".mkv",
    ".part",
    ".ytdl",
}


@dataclass
class CleanTarget:
    vod_id: str
    run_dir: Path
    media_files: list[Path]
    has_transcript: bool
    total_bytes: int


def _format_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0  # type: ignore[assignment]
    return f"{num_bytes:.1f} PB"


def find_cleanable_runs(
    target_vod_id: str | None = None,
    *,
    keep_latest: int = 0,
    force: bool = False,
) -> list[CleanTarget]:
    if not RUNS_DIR.exists():
        return []

    # Gather run directories
    run_dirs: list[Path] = [d for d in RUNS_DIR.iterdir() if d.is_dir()]
    # Sort newest first by directory modification time
    run_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)

    if target_vod_id:
        target_norm = target_vod_id.strip()
        if "twitch.tv/videos/" in target_norm:
            target_norm = target_norm.split("twitch.tv/videos/")[-1].split("?")[0].strip("/")
        if target_norm.startswith("v") and target_norm[1:].isdigit():
            target_norm = target_norm[1:]
        run_dirs = [d for d in run_dirs if d.name == target_norm]

    targets: list[CleanTarget] = []
    runs_to_process = run_dirs[keep_latest:] if keep_latest > 0 else run_dirs

    for r_dir in runs_to_process:
        media_files: list[Path] = []
        total_bytes = 0
        for f in r_dir.iterdir():
            if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS:
                media_files.append(f)
                total_bytes += f.stat().st_size

        has_transcript = (r_dir / "transcript.json").exists() or (r_dir / "transcript.txt").exists()

        if media_files:
            # If transcript is missing, only clean if force is True
            if not has_transcript and not force:
                continue
            targets.append(
                CleanTarget(
                    vod_id=r_dir.name,
                    run_dir=r_dir,
                    media_files=sorted(media_files),
                    has_transcript=has_transcript,
                    total_bytes=total_bytes,
                )
            )

    return targets


def execute_clean(
    targets: Sequence[CleanTarget],
    *,
    dry_run: bool = False,
) -> int:
    """Deletes media files and returns total bytes reclaimed."""
    if not targets:
        print("No media files found to clean.")
        return 0

    total_reclaimed = sum(t.total_bytes for t in targets)
    prefix = "[DRY RUN] Would delete" if dry_run else "Deleted"

    print(f"\n--- Clean Summary ({'DRY RUN' if dry_run else 'EXECUTING'}) ---")
    for t in targets:
        print(f"Run VOD {t.vod_id} ({_format_size(t.total_bytes)}):")
        for f in t.media_files:
            f_size = _format_size(f.stat().st_size)
            print(f"  - {prefix}: {f.name} ({f_size})")
            if not dry_run:
                try:
                    f.unlink()
                except OSError as e:
                    print(f"    Failed to delete {f.name}: {e}")

    action_word = "would be" if dry_run else "was"
    print(f"\nTotal media space that {action_word} freed: {_format_size(total_reclaimed)}")
    print("Transcripts, metadata, and wiki pages remain untouched.\n")
    return total_reclaimed


def clean_run_dir(run_dir: Path, force: bool = True) -> int:
    """Deletes all media and transient files in a single run directory. Returns bytes freed."""
    if not run_dir.exists():
        return 0
    freed = 0
    has_transcript = (run_dir / "transcript.json").exists() or (run_dir / "transcript.txt").exists()
    if not has_transcript and not force:
        return 0

    for f in list(run_dir.iterdir()):
        if not f.is_file():
            continue
        name_lower = f.name.lower()
        if (
            f.suffix.lower() in MEDIA_EXTENSIONS
            or name_lower.endswith(".part")
            or name_lower.endswith(".ytdl")
            or name_lower.endswith(".tmp")
        ):
            try:
                size = f.stat().st_size
                f.unlink()
                freed += size
            except OSError:
                pass
    return freed
