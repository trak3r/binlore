from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def format_ts(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


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

    # CPU int8 works everywhere; Apple Silicon still fine for Phase 1
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=5,
    )

    segments: list[dict[str, Any]] = []
    lines: list[str] = []
    for seg in segments_iter:
        item = {
            "id": seg.id,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        }
        segments.append(item)
        lines.append(f"[{format_ts(seg.start)} --> {format_ts(seg.end)}] {item['text']}")

    return {
        "engine": "faster-whisper",
        "model": model_size,
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
