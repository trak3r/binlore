from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# Rough peak RSS for CPU int8 + beam_size=1 on a *single chunk* (conservative).
# "Killed" with no traceback = Linux OOM killer (common on multi-hour VODs that
# decode the entire PCM into one float32 array before Whisper runs).
_MODEL_MIN_AVAIL_MB: dict[str, int] = {
    "tiny": 700,
    "tiny.en": 700,
    "base": 1200,
    "base.en": 1200,
    "small": 2200,
    "small.en": 2200,
    "medium": 4500,
    "medium.en": 4500,
    "large-v2": 9000,
    "large-v3": 9000,
    "large": 9000,
}

_MODEL_FALLBACK_ORDER = ("tiny", "base", "small", "medium", "large-v3")

# Multi-hour BIN streams are usually ~2–3h; only rare outliers (Deb-8, long
# Lethal Company) need chunking. Ceiling of 4h keeps normal shows single-pass.
DEFAULT_CHUNK_SECONDS = 14400  # 4 hours


def format_ts(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def available_ram_mb() -> float | None:
    """Linux MemAvailable in MiB, or None if unknown."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    try:
        import psutil  # type: ignore

        return psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        return None


def _min_ram_for(model_size: str) -> int:
    if model_size in _MODEL_MIN_AVAIL_MB:
        return _MODEL_MIN_AVAIL_MB[model_size]
    return 2200


def pick_whisper_model(requested: str, *, avail_mb: float | None) -> str:
    """Downgrade model when free RAM is too low for the requested size."""
    if avail_mb is None:
        return requested
    need = _min_ram_for(requested)
    if avail_mb >= need:
        return requested

    want_en = requested.endswith(".en")
    candidates = [m for m in _MODEL_FALLBACK_ORDER if _min_ram_for(m) <= avail_mb]
    if not candidates:
        return "tiny"
    best = candidates[-1]
    if want_en and f"{best}.en" in _MODEL_MIN_AVAIL_MB and _min_ram_for(f"{best}.en") <= avail_mb:
        return f"{best}.en"
    return best


def audio_duration_seconds(audio_path: Path) -> float | None:
    """Best-effort duration via ffprobe."""
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(proc.stdout.strip())
    except Exception:
        return None


def _chunk_seconds() -> int:
    raw = os.environ.get("WHISPER_CHUNK_SECONDS", str(DEFAULT_CHUNK_SECONDS)).strip()
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_CHUNK_SECONDS


def _extract_chunk(src: Path, dest: Path, *, start: float, duration: float) -> None:
    """Write a 16 kHz mono wav slice (keeps Whisper decode memory bounded)."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(src),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(dest),
    ]
    subprocess.run(cmd, check=True)


def _transcribe_path(
    model: Any,
    audio_path: Path,
    *,
    language: str | None,
    beam_size: int,
    vad: bool,
    time_offset: float = 0.0,
    id_offset: int = 0,
    total_duration: float | None = None,
) -> tuple[list[dict[str, Any]], list[str], Any]:
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=vad,
        beam_size=max(1, beam_size),
    )
    segments: list[dict[str, Any]] = []
    lines: list[str] = []
    last_log = time_offset - 300.0  # force first milestone after 5m of *stream* time
    progress_total = total_duration if total_duration is not None else (
        (getattr(info, "duration", 0) or 0) + time_offset
    )
    for seg in segments_iter:
        start = round(seg.start + time_offset, 3)
        end = round(seg.end + time_offset, 3)
        text = seg.text.strip()
        item = {
            "id": id_offset + len(segments),
            "start": start,
            "end": end,
            "text": text,
        }
        segments.append(item)
        lines.append(f"[{format_ts(start)} --> {format_ts(end)}] {text}")
        if start - last_log >= 300:
            progress_str = f" / {format_ts(progress_total)}" if progress_total else ""
            print(f"  transcribed up to {format_ts(start)}{progress_str}...", flush=True)
            last_log = start
    return segments, lines, info


def transcribe_audio(
    audio_path: Path,
    *,
    model_size: str = "small",
    language: str | None = "en",
) -> dict[str, Any]:
    """Run faster-whisper and return a serializable transcript dict."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SystemExit(
            "faster-whisper not installed. From tools/: pip install -e ."
        ) from e

    avail = available_ram_mb()
    chosen = pick_whisper_model(model_size, avail_mb=avail)
    if avail is not None:
        print(
            f"  RAM available: {avail:.0f} MiB "
            f"(need ~{_min_ram_for(model_size)} MiB for model={model_size})",
            flush=True,
        )
    if chosen != model_size:
        print(
            f"  Downgrading Whisper model {model_size} → {chosen} to avoid OOM "
            f"(Linux would otherwise SIGKILL the process with just 'Killed'). "
            f"Set --model {chosen} explicitly, free RAM, or raise "
            f"WHISPER_FORCE_MODEL=1 to keep {model_size}.",
            flush=True,
        )
        if os.environ.get("WHISPER_FORCE_MODEL", "").strip() in {"1", "true", "yes"}:
            chosen = model_size
            print(f"  WHISPER_FORCE_MODEL set; keeping model={chosen}", flush=True)

    beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
    cpu_threads = int(os.environ.get("WHISPER_CPU_THREADS", "0"))
    if cpu_threads <= 0:
        cpu_threads = min(4, max(1, (os.cpu_count() or 2)))
    vad = os.environ.get("WHISPER_VAD", "1").strip().lower() not in {"0", "false", "off", "no"}
    chunk_s = _chunk_seconds()

    print(
        f"  Loading WhisperModel({chosen!r}, device=cpu, compute_type=int8, "
        f"cpu_threads={cpu_threads}, beam_size={beam_size}, vad={vad})…",
        flush=True,
    )
    model = WhisperModel(
        chosen,
        device="cpu",
        compute_type="int8",
        cpu_threads=cpu_threads,
        num_workers=1,
    )

    duration = audio_duration_seconds(audio_path)
    use_chunks = bool(chunk_s and duration and duration > chunk_s)

    segments: list[dict[str, Any]] = []
    lines: list[str] = []
    info: Any = None

    if not use_chunks:
        if duration:
            print(f"  Audio duration {format_ts(duration)} — single-pass transcription", flush=True)
        segments, lines, info = _transcribe_path(
            model,
            audio_path,
            language=language,
            beam_size=beam_size,
            vad=vad,
            total_duration=duration,
        )
    else:
        assert duration is not None
        n_chunks = int((duration + chunk_s - 1) // chunk_s)
        chunk_label = (
            f"{chunk_s // 3600}h" if chunk_s >= 3600 else f"{chunk_s // 60}m"
        )
        print(
            f"  Audio duration {format_ts(duration)} — chunking into ~{chunk_label} slices "
            f"({n_chunks} chunks) so the full {format_ts(duration)} PCM is never in RAM at once "
            f"(this is what OOM-killed 8h streams). Set WHISPER_CHUNK_SECONDS=0 to disable.",
            flush=True,
        )
        with tempfile.TemporaryDirectory(prefix="binlore-whisper-") as td:
            tdir = Path(td)
            start = 0.0
            chunk_i = 0
            while start < duration:
                chunk_i += 1
                slice_dur = min(float(chunk_s), duration - start)
                chunk_path = tdir / f"chunk_{chunk_i:03d}.wav"
                print(
                    f"  chunk {chunk_i}/{n_chunks}: "
                    f"{format_ts(start)} → {format_ts(start + slice_dur)}…",
                    flush=True,
                )
                _extract_chunk(audio_path, chunk_path, start=start, duration=slice_dur)
                part_segs, part_lines, part_info = _transcribe_path(
                    model,
                    chunk_path,
                    language=language,
                    beam_size=beam_size,
                    vad=vad,
                    time_offset=start,
                    id_offset=len(segments),
                    total_duration=duration,
                )
                if info is None:
                    info = part_info
                segments.extend(part_segs)
                lines.extend(part_lines)
                try:
                    chunk_path.unlink(missing_ok=True)
                except OSError:
                    pass
                start += slice_dur

    language_out = getattr(info, "language", language) if info is not None else language
    lang_prob = getattr(info, "language_probability", None) if info is not None else None

    return {
        "engine": "faster-whisper",
        "model": chosen,
        "model_requested": model_size,
        "language": language_out,
        "language_probability": lang_prob,
        "duration": duration if duration is not None else getattr(info, "duration", None),
        "chunk_seconds": chunk_s if use_chunks else None,
        "segments": segments,
        "text": "\n".join(s["text"] for s in segments),
        "text_timestamped": "\n".join(lines),
    }


def write_transcript(run_dir: Path, transcript: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "transcript.json").write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "transcript.txt").write_text(
        transcript.get("text_timestamped") or transcript.get("text") or "",
        encoding="utf-8",
    )
    (run_dir / "transcript.plain.txt").write_text(
        transcript.get("text") or "",
        encoding="utf-8",
    )
