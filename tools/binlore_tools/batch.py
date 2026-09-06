from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .clean import clean_run_dir, find_cleanable_runs, execute_clean
from .extract import DEFAULT_MODEL, extract_lore_from_vod, get_api_key, load_env
from .paths import CATALOG_JSON, CONTENT_EPISODES, REPO_ROOT, RUNS_DIR, TOOLS_ROOT
from .vods import Vod, format_duration, vod_from_catalog_entry

_INTERRUPTED = False
_CURRENT_ACTIVE_RUN_DIR: Path | None = None


def _format_size(num_bytes: int | float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def get_free_disk_space_gb(path: Path) -> float:
    """Returns free disk space in Gigabytes."""
    try:
        target = path if path.exists() else path.parent
        stat = shutil.disk_usage(target)
        return stat.free / (1024 ** 3)
    except Exception:
        return 999.0


class BatchLogger:
    """Logs timestamped messages simultaneously to stdout and batch.log."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str, level: str = "INFO") -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{ts}] [{level}] {message}"
        print(formatted, flush=True)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

    def info(self, message: str) -> None:
        self.log(message, level="INFO")

    def warning(self, message: str) -> None:
        self.log(message, level="WARN")

    def error(self, message: str) -> None:
        self.log(message, level="ERROR")

    def success(self, message: str) -> None:
        self.log(message, level="SUCCESS")


def _setup_signal_handlers(logger: BatchLogger) -> None:
    def handler(signum: int, frame: Any) -> None:
        global _INTERRUPTED
        _INTERRUPTED = True
        logger.warning(
            f"Received signal {signum} (Ctrl+C / SIGTERM). Cleaning up active temporary files..."
        )
        if _CURRENT_ACTIVE_RUN_DIR and _CURRENT_ACTIVE_RUN_DIR.exists():
            freed = clean_run_dir(_CURRENT_ACTIVE_RUN_DIR, force=True)
            logger.info(
                f"Cleaned transient media in active run {_CURRENT_ACTIVE_RUN_DIR.name} ({_format_size(freed)} freed)."
            )
        sys.exit(130)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def find_unprocessed_episodes(
    catalog_path: Path = TOOLS_ROOT / "youtube_catalog.json",
    episodes_dir: Path = CONTENT_EPISODES,
    *,
    oldest_first: bool = False,
    skip_drafts: bool = True,
) -> list[dict[str, Any]]:
    """
    Returns a list of stream catalog entries that have not yet been fully processed.
    An episode is considered processed if:
      - A markdown file in content/episodes/ exists for that date or VOD ID
      - It is NOT marked as draft
      - It contains extracted content (i.e. '## Characters' has real entries, not '_TBD_')
    """
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog file not found: {catalog_path}")

    with open(catalog_path, encoding="utf-8") as f:
        streams: list[dict[str, Any]] = json.load(f)

    # Scan existing markdown files in content/episodes/
    processed_dates: set[str] = set()
    processed_vod_ids: set[str] = set()
    skipped_dates: set[str] = set()
    skipped_vod_ids: set[str] = set()

    for ep_file in episodes_dir.glob("*.md"):
        if ep_file.name == "index.md":
            continue
        try:
            txt = ep_file.read_text(encoding="utf-8")
        except Exception:
            continue

        is_draft = "draft: true" in txt.lower()
        has_content = False
        if "## Characters" in txt:
            char_section = txt.split("## Characters", 1)[1]
            if "## " in char_section:
                char_section = char_section.split("## ", 1)[0]
            if "- _TBD_" not in char_section and len(char_section.strip()) > 10:
                has_content = True

        # Extract vod_id and date from frontmatter
        file_vod_id = ""
        file_date = ep_file.stem.split("-vod-")[0]
        for line in txt.splitlines()[:25]:
            if line.startswith("vod_id:"):
                file_vod_id = line.split(":", 1)[1].strip(" \"'")
            elif line.startswith("date:"):
                extracted_d = line.split(":", 1)[1].strip(" \"'")
                if extracted_d:
                    file_date = extracted_d

        if is_draft and skip_drafts:
            if file_date:
                skipped_dates.add(file_date)
            if file_vod_id:
                skipped_vod_ids.add(file_vod_id)
            continue

        if has_content:
            if file_date:
                processed_dates.add(file_date)
            if file_vod_id:
                processed_vod_ids.add(file_vod_id)

    unprocessed: list[dict[str, Any]] = []
    for s in streams:
        s_date = str(s.get("date") or "")
        yt_id = str(s.get("yt_id") or s.get("id") or "")
        twitch_id = str(s.get("twitch_id") or "")

        # Check if already processed
        if s_date and s_date in processed_dates:
            continue
        if yt_id and yt_id in processed_vod_ids:
            continue
        if twitch_id and twitch_id in processed_vod_ids:
            continue

        # Check if explicit draft to skip
        if skip_drafts:
            if s_date and s_date in skipped_dates:
                continue
            if yt_id and yt_id in skipped_vod_ids:
                continue
            if twitch_id and twitch_id in skipped_vod_ids:
                continue

        unprocessed.append(s)

    if oldest_first:
        unprocessed.reverse()

    return unprocessed


def check_backlog_status(
    catalog_path: Path = TOOLS_ROOT / "youtube_catalog.json",
    episodes_dir: Path = CONTENT_EPISODES,
) -> dict[str, Any]:
    """Returns a dictionary summarizing catalog and processing backlog status."""
    if not catalog_path.exists():
        return {"error": f"Catalog missing: {catalog_path}"}

    with open(catalog_path, encoding="utf-8") as f:
        streams = json.load(f)

    unprocessed = find_unprocessed_episodes(catalog_path, episodes_dir)
    total_streams = len(streams)
    unprocessed_count = len(unprocessed)
    ingested_count = total_streams - unprocessed_count
    free_disk_gb = get_free_disk_space_gb(RUNS_DIR)

    return {
        "total_streams": total_streams,
        "ingested_count": ingested_count,
        "backlog_count": unprocessed_count,
        "percent_complete": f"{(ingested_count / total_streams * 100):.1f}%" if total_streams else "0%",
        "free_disk_gb": f"{free_disk_gb:.2f} GB",
        "next_unprocessed": unprocessed[0] if unprocessed else None,
    }


def process_single_episode(
    stream: dict[str, Any],
    logger: BatchLogger,
    *,
    whisper_model: str = "small",
    openrouter_model: str = DEFAULT_MODEL,
    timeout: float = 90.0,
    clean_audio: bool = True,
    skip_extract: bool = False,
    build_quartz: bool = True,
    git_commit: bool = True,
    min_disk_gb: float = 1.0,
) -> dict[str, Any]:
    """
    Executes the end-to-end pipeline for a single episode:
      1. Disk space check
      2. Ingest audio & transcribe (Twitch with automatic YouTube archive fallback)
      3. Immediately deletes audio files to conserve disk space
      4. Lore extraction via OpenRouter
      5. Updates wiki pages (episode, characters, segments, storylines)
      6. Regenerates catalog index
      7. Final disk hygiene check
      8. Compiles and validates static wiki via Quartz (`npx quartz build`)
      9. Creates local git commit for the episode
    """
    global _CURRENT_ACTIVE_RUN_DIR

    s_date = stream.get("date") or "unknown-date"
    s_title = stream.get("title") or "(untitled)"
    yt_id = stream.get("yt_id") or stream.get("id") or ""
    yt_url = stream.get("yt_url") or (f"https://www.youtube.com/watch?v={yt_id}" if yt_id else "")
    twitch_id = str(stream.get("twitch_id") or "") if stream.get("twitch_id") else None
    twitch_url = stream.get("twitch_url")

    # 1. Disk space check
    free_gb = get_free_disk_space_gb(RUNS_DIR)
    if free_gb < min_disk_gb:
        raise RuntimeError(
            f"Insufficient disk space: {free_gb:.2f} GB available (minimum required: {min_disk_gb:.2f} GB). Aborting."
        )

    # 2. Check if a completed transcript already exists in tools/runs/
    target_vod_id = twitch_id or yt_id
    candidate_dirs = [d for d in [RUNS_DIR / target_vod_id, RUNS_DIR / yt_id] if d.exists()]
    existing_run_dir: Path | None = None
    for c_dir in candidate_dirs:
        if (c_dir / "transcript.txt").exists() or (c_dir / "transcript.json").exists():
            existing_run_dir = c_dir
            target_vod_id = c_dir.name
            break

    run_dir: Path
    if existing_run_dir:
        run_dir = existing_run_dir
        _CURRENT_ACTIVE_RUN_DIR = run_dir
        logger.info(f"Reusing existing transcript in tools/runs/{target_vod_id}/")
        # Ensure any leftover media in this run is deleted
        if clean_audio:
            clean_run_dir(run_dir, force=True)
    else:
        # Ingest needed: Try Twitch first if available, with YouTube archive fallback
        from .ingest import ingest

        ingest_successful = False
        vod_obj: Vod | None = None

        if twitch_url:
            vod_obj = vod_from_catalog_entry(stream, prefer_source="twitch")
            _CURRENT_ACTIVE_RUN_DIR = RUNS_DIR / vod_obj.id
            logger.info(f"Attempting download from Twitch VOD {vod_obj.id} ({twitch_url})...")
            try:
                run_dir = ingest(
                    vod=vod_obj,
                    model=whisper_model,
                    clean_audio=clean_audio,
                )
                target_vod_id = vod_obj.id
                ingest_successful = True
            except Exception as e:
                logger.warning(
                    f"Twitch download failed for {vod_obj.id} ({e}); falling back to YouTube archive ({yt_url})..."
                )
                if _CURRENT_ACTIVE_RUN_DIR and _CURRENT_ACTIVE_RUN_DIR.exists():
                    clean_run_dir(_CURRENT_ACTIVE_RUN_DIR, force=True)

        if not ingest_successful:
            if not yt_url:
                raise RuntimeError(f"No source URL available for stream {s_date} ({s_title})")
            vod_obj = vod_from_catalog_entry(stream, prefer_source="youtube")
            _CURRENT_ACTIVE_RUN_DIR = RUNS_DIR / vod_obj.id
            logger.info(f"Downloading from YouTube Archive {vod_obj.id} ({yt_url})...")
            run_dir = ingest(
                vod=vod_obj,
                model=whisper_model,
                clean_audio=clean_audio,
            )
            target_vod_id = vod_obj.id

        # Enrich meta.json with catalog metadata
        meta_file = run_dir / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta.update({
                    "yt_id": yt_id,
                    "yt_url": yt_url,
                    "twitch_id": twitch_id,
                    "twitch_url": twitch_url,
                    "catalog_date": s_date,
                })
                meta_file.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass

    # 3. Aggressively clean media files
    if clean_audio:
        freed = clean_run_dir(run_dir, force=True)
        if freed > 0:
            logger.info(f"Disk cleanup: Reclaimed {_format_size(freed)} from {run_dir.name}/")

    # 4. Lore Extraction via OpenRouter
    if not skip_extract:
        extraction_path = run_dir / "extraction.json"
        if not extraction_path.exists():
            logger.info(f"Extracting lore via OpenRouter for {target_vod_id} (model={openrouter_model})...")
            extract_lore_from_vod(
                vod_id=target_vod_id,
                model=openrouter_model,
                timeout=timeout,
            )
            logger.info(f"Lore extraction saved to tools/runs/{target_vod_id}/extraction.json")
        else:
            logger.info(f"Existing extraction found in tools/runs/{target_vod_id}/extraction.json")

        # 5. Update Wiki Pages
        from .wiki_updater import update_wiki_from_extraction
        logger.info(f"Updating wiki pages from extraction for {target_vod_id}...")
        report = update_wiki_from_extraction(
            vod_id=target_vod_id,
            auto_create_characters=True,
        )
        logger.info(
            f"Wiki updated: {len(report.characters_updated)} characters updated, "
            f"{len(report.characters_created)} created, "
            f"{len(report.storylines_updated)} storylines updated, "
            f"{len(report.segments_updated)} segments updated."
        )

    # 6. Regenerate Episodes Catalog Index
    from .catalog import generate_episodes_index
    generate_episodes_index()

    # 7. Post-run hygiene check
    if clean_audio:
        clean_run_dir(run_dir, force=True)

    # 8. Compile and validate wiki with Quartz before committing
    quartz_ok = True
    if build_quartz:
        logger.info("Compiling and verifying Quartz wiki (npx quartz build)...")
        try:
            subprocess.run(
                ["npx", "quartz", "build"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("✓ Quartz wiki compiled and validated successfully.")
        except FileNotFoundError:
            logger.warning("npx/node not found in PATH; skipping Quartz compilation.")
        except subprocess.CalledProcessError as e:
            quartz_ok = False
            err_output = (e.stderr or e.stdout or str(e)).strip()
            logger.error(f"Quartz build failed (exit {e.returncode}): {err_output[:300]}")

    # 9. Create local Git Commit (runs after Quartz validation)
    if git_commit:
        if build_quartz and not quartz_ok:
            logger.warning(
                "Skipping git commit because Quartz build failed (preventing broken build from being committed)."
            )
        else:
            try:
                commit_msg = f"lore(episodes): process {s_date} - {s_title}"
                subprocess.run(["git", "add", "content/"], cwd=REPO_ROOT, check=True, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=REPO_ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info(f"Git commit created: {commit_msg}")
            except subprocess.CalledProcessError as e:
                err_text = (e.stderr or e.stdout or "").strip()
                if "nothing to commit" in err_text:
                    logger.info("Git: Nothing new to commit.")
                else:
                    logger.warning(f"Git commit skipped or failed: {err_text}")

    _CURRENT_ACTIVE_RUN_DIR = None
    free_after = get_free_disk_space_gb(RUNS_DIR)

    return {
        "status": "success",
        "vod_id": target_vod_id,
        "date": s_date,
        "title": s_title,
        "free_disk_gb": f"{free_after:.2f} GB",
    }


def run_batch_processing(
    *,
    limit: int | None = None,
    oldest_first: bool = False,
    whisper_model: str = "small",
    openrouter_model: str = DEFAULT_MODEL,
    delay: float = 5.0,
    timeout: float = 90.0,
    clean_audio: bool = True,
    clean_existing: bool = True,
    skip_extract: bool = False,
    skip_drafts: bool = True,
    build_quartz: bool = True,
    git_commit: bool = True,
    min_disk_gb: float = 1.0,
    log_file: Path = RUNS_DIR / "batch.log",
    dry_run: bool = False,
) -> int:
    """
    Main entry point for unattended batch processing of all unprocessed episodes.
    Designed for 24/7 autonomous server execution with guaranteed disk hygiene.
    """
    logger = BatchLogger(log_file)
    _setup_signal_handlers(logger)

    logger.info("=" * 65)
    logger.info("BINLORE UNATTENDED BATCH PROCESSOR STARTING")
    logger.info(f"Configuration: whisper_model={whisper_model}, openrouter_model={openrouter_model}")
    logger.info(f"Disk hygiene: clean_audio={clean_audio}, clean_existing={clean_existing}, min_disk_gb={min_disk_gb}")
    logger.info(f"Free disk space on host: {get_free_disk_space_gb(RUNS_DIR):.2f} GB")
    logger.info("=" * 65)

    # Pre-flight API key check if extraction is requested
    if not skip_extract and not dry_run:
        load_env()
        try:
            get_api_key()
        except SystemExit:
            logger.error(
                "OPENROUTER_API_KEY is not set! Set OPENROUTER_API_KEY in tools/.env or environment. "
                "Use --skip-extract to run transcription-only without an API key."
            )
            return 1

    # Pre-run sweep: clean any existing lingering media files
    if clean_existing and not dry_run:
        targets = find_cleanable_runs(force=False)
        if targets:
            logger.info(f"Sweeping {len(targets)} existing run directories for lingering media...")
            reclaimed = execute_clean(targets, dry_run=False)
            logger.info(f"Initial cleanup freed {_format_size(reclaimed)} of disk space.")

    # Discover unprocessed episodes
    unprocessed = find_unprocessed_episodes(
        oldest_first=oldest_first,
        skip_drafts=skip_drafts,
    )

    total_unprocessed = len(unprocessed)
    logger.info(f"Found {total_unprocessed} unprocessed episodes in the catalog.")

    if not unprocessed:
        logger.success("All episodes in the catalog are already processed! Nothing to do.")
        return 0

    if limit and limit > 0:
        unprocessed = unprocessed[:limit]
        logger.info(f"Processing capped by --limit to {len(unprocessed)} episodes.")

    if dry_run:
        logger.info("\n--- [DRY RUN: Unprocessed Episodes Queue] ---")
        for idx, ep in enumerate(unprocessed, 1):
            date_s = ep.get("date") or "?"
            title = ep.get("title") or "?"
            dur = ep.get("duration_str") or "?"
            yt = ep.get("yt_id") or "?"
            tw = ep.get("twitch_id") or "none"
            print(f"  {idx:3d}. [{date_s}] ({dur}) {title} [YT: {yt} | Twitch: {tw}]")
        logger.info("--- [END DRY RUN] ---")
        return 0

    processed_count = 0
    failed_episodes: list[tuple[dict[str, Any], str]] = []

    start_time = time.time()
    for idx, stream in enumerate(unprocessed, 1):
        if _INTERRUPTED:
            logger.warning("Interrupted flag set. Exiting loop.")
            break

        date_s = stream.get("date") or "?"
        title = stream.get("title") or "?"
        logger.info("-" * 65)
        logger.info(f"[{idx}/{len(unprocessed)}] Processing Episode: {date_s} — \"{title}\"")

        try:
            res = process_single_episode(
                stream,
                logger,
                whisper_model=whisper_model,
                openrouter_model=openrouter_model,
                timeout=timeout,
                clean_audio=clean_audio,
                skip_extract=skip_extract,
                build_quartz=build_quartz,
                git_commit=git_commit,
                min_disk_gb=min_disk_gb,
            )
            processed_count += 1
            logger.success(
                f"[{idx}/{len(unprocessed)}] ✓ Completed {date_s} (VOD: {res['vod_id']}). "
                f"Free disk: {res['free_disk_gb']}."
            )
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            logger.error(f"[{idx}/{len(unprocessed)}] ✗ Failed {date_s} — {title}: {err_msg}")
            # Ensure transient files cleaned up
            if _CURRENT_ACTIVE_RUN_DIR and _CURRENT_ACTIVE_RUN_DIR.exists():
                clean_run_dir(_CURRENT_ACTIVE_RUN_DIR, force=True)
            failed_episodes.append((stream, err_msg))

        # Inter-episode cooldown delay
        if idx < len(unprocessed) and delay > 0 and not _INTERRUPTED:
            logger.info(f"Sleeping {delay:.1f}s before next episode...")
            time.sleep(delay)

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"BATCH RUN FINISHED in {elapsed / 60:.1f} minutes")
    logger.info(f"  Successfully processed: {processed_count}")
    logger.info(f"  Failed: {len(failed_episodes)}")
    logger.info(f"  Free disk space remaining: {get_free_disk_space_gb(RUNS_DIR):.2f} GB")

    if failed_episodes:
        logger.warning(f"\nFailed episodes ({len(failed_episodes)}):")
        for stream, reason in failed_episodes:
            logger.warning(f"  - {stream.get('date')}: {stream.get('title')} -> {reason}")

    logger.info("=" * 65)
    return 0 if not failed_episodes else 1
