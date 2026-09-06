from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .episode import write_episode_stub
from .paths import RUNS_DIR
from .transcribe import transcribe_audio, write_transcript
from .vods import Vod, format_duration, resolve_vod


def _ensure_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg") from e


def download_audio(vod: Vod, dest_dir: Path) -> Path:
    _ensure_ffmpeg()
    dest_dir.mkdir(parents=True, exist_ok=True)
    # yt-dlp chooses extension; we request m4a
    outtmpl = str(dest_dir / "audio.%(ext)s")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format",
        "m4a",
        "--audio-quality",
        "0",
        "-o",
        outtmpl,
        "--no-playlist",
        vod.url,
    ]
    print(f"Downloading audio for {vod.id}…", flush=True)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp download failed for {vod.url} (exit {e.returncode})") from e

    matches = list(dest_dir.glob("audio.*"))
    # ignore json sidecars if any
    audio = [p for p in matches if p.suffix.lower() in {".m4a", ".mp3", ".opus", ".webm", ".wav", ".mp4"}]
    if not audio:
        raise RuntimeError(f"No audio file found in {dest_dir}")
    return audio[0]


def write_meta(run_dir: Path, vod: Vod, extra: dict[str, Any] | None = None) -> Path:
    meta: dict[str, Any] = {
        "vod_id": vod.id,
        "title": vod.title,
        "url": vod.url,
        "duration_seconds": vod.duration,
        "duration": format_duration(vod.duration),
        "timestamp": vod.timestamp,
        "aired_at": vod.aired_at.isoformat() if vod.aired_at else None,
        "date": vod.date_str,
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
        "channel": "caseblackwell",
    }
    if extra:
        meta.update(extra)
    path = run_dir / "meta.json"
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


def ingest(
    *,
    url: str | None = None,
    vod: Vod | None = None,
    latest: bool = False,
    model: str = "small",
    skip_download: bool = False,
    skip_transcribe: bool = False,
    force_episode: bool = False,
    clean_audio: bool = False,
) -> Path:
    if vod is None:
        vod = resolve_vod(url, latest=latest)
    run_dir = RUNS_DIR / vod.id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"VOD {vod.id}: {vod.title}", flush=True)
    print(f"  {vod.url}", flush=True)
    print(f"  duration={format_duration(vod.duration)} date={vod.date_str}", flush=True)
    print(f"  run dir: {run_dir}", flush=True)

    audio_path = run_dir / "audio.m4a"
    existing_audio = list(run_dir.glob("audio.*"))
    existing_audio = [
        p
        for p in existing_audio
        if p.suffix.lower() in {".m4a", ".mp3", ".opus", ".webm", ".wav", ".mp4"}
    ]

    try:
        if skip_download and existing_audio:
            audio_path = existing_audio[0]
            print(f"Using existing audio: {audio_path.name}", flush=True)
        elif skip_download:
            raise RuntimeError("--skip-download set but no audio.* in run dir")
        else:
            audio_path = download_audio(vod, run_dir)

        write_meta(
            run_dir,
            vod,
            extra={"audio_file": audio_path.name, "whisper_model": model},
        )

        if not skip_transcribe:
            print(
                f"Transcribing with faster-whisper model={model} (this can take a while)…",
                flush=True,
            )
            transcript = transcribe_audio(audio_path, model_size=model)
            write_transcript(run_dir, transcript)
            print(
                f"Wrote {run_dir / 'transcript.json'} ({len(transcript['segments'])} segments)",
                flush=True,
            )
            if clean_audio:
                from .clean import clean_run_dir
                freed = clean_run_dir(run_dir)
                print(
                    f"Deleted audio files to save disk space ({freed / (1024 * 1024):.1f} MB freed).",
                    flush=True,
                )
        else:
            print("Skipping transcription", flush=True)

    except Exception:
        if clean_audio:
            from .clean import clean_run_dir
            clean_run_dir(run_dir)
        raise

    episode_path = write_episode_stub(vod, run_id=vod.id, force=force_episode)
    print(f"Episode stub: {episode_path.relative_to(run_dir.parents[2])}", flush=True)
    return run_dir
