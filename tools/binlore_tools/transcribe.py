from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Rough peak RSS for CPU int8 + beam_size=1 on a multi-hour VOD (conservative).
# "Killed" with no traceback = Linux OOM killer when MemAvailable is below this.
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
                    # kB
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
    # Unknown / custom HF id — assume "small"-class
    return 2200


def pick_whisper_model(requested: str, *, avail_mb: float | None) -> str:
    """Downgrade model when free RAM is too low for the requested size."""
    if avail_mb is None:
        return requested
    need = _min_ram_for(requested)
    if avail_mb >= need:
        return requested

    # Prefer smaller models in the same .en / multilingual family when possible
    want_en = requested.endswith(".en")
    candidates = [m for m in _MODEL_FALLBACK_ORDER if _min_ram_for(m) <= avail_mb]
    if not candidates:
        return "tiny"
    best = candidates[-1]  # largest that fits
    if want_en and f"{best}.en" in _MODEL_MIN_AVAIL_MB and _min_ram_for(f"{best}.en") <= avail_mb:
        return f"{best}.en"
    return best


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
            f"(Linux would otherwise SIGKILL with just 'Killed'). "
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

    # CPU int8 + beam_size=1 + single worker: lowest reliable footprint for VPS hosts.
    # beam_size=5 (old default) often OOM-kills multi-hour VODs on ≤4 GB machines.
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
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=vad,
        beam_size=max(1, beam_size),
    )

    segments: list[dict[str, Any]] = []
    lines: list[str] = []
    total_dur = getattr(info, "duration", 0) or 0
    last_log = 0.0
    for seg in segments_iter:
        item = {
            "id": seg.id,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        }
        segments.append(item)
        lines.append(f"[{format_ts(seg.start)} --> {format_ts(seg.end)}] {item['text']}")
        if seg.start - last_log >= 300:  # log every 5 minutes of stream time
            progress_str = f" / {format_ts(total_dur)}" if total_dur else ""
            print(f"  transcribed up to {format_ts(seg.start)}{progress_str}...", flush=True)
            last_log = seg.start

    return {
        "engine": "faster-whisper",
        "model": chosen,
        "model_requested": model_size,
        "language": info.language,
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
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
    # plain text without timestamps for easy re-LLM
    (run_dir / "transcript.plain.txt").write_text(
        transcript.get("text") or "",
        encoding="utf-8",
    )
