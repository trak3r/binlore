"""Local (no-LLM) ranking of Munch/Crum and arc-keyword episodes."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .paths import CATALOG_JSON, RUNS_DIR, TOOLS_ROOT

MIN_DURATION_SECONDS = 20 * 60

CHAR_PATTERNS: list[tuple[str, str, int]] = [
    (r"\bmunch(?:cut)?\b", "munch", 2),
    (r"\bmonch\b", "munch", 2),
    (r"\bcrum(?:b|ble|fuscious)?\b", "crum", 2),
    (r"\bleonard\b", "crum", 1),
]

ARC_PATTERNS: list[tuple[str, str, int]] = [
    (r"dick\s*punch", "dick_punch", 8),
    (r"groin\s*punch", "dick_punch", 6),
    (r"gorilla", "dick_punch", 4),
    (r"rock[- ]?afire", "dick_punch", 6),
    (r"beyblade", "beyblade", 8),
    (r"skeleton", "skeleton", 5),
    (r"gambling|wager|\bbet\b", "gambling", 1),
]

DEFAULT_RANKED_PATH = RUNS_DIR / "munch-crum-ranked.json"
DEFAULT_PILOT_PATH = RUNS_DIR / "munch-crum-pilot.json"

# Dick-punch timeline bookmarks (climaxes / setup nights) preferred for pilots.
PILOT_BOOKMARK_DATES = (
    "2026-09-07",
    "2026-09-04",
    "2026-09-02",
    "2026-09-01",
    "2026-08-26",
    "2026-08-14",
    "2026-08-08",
    "2026-07-17",
    "2026-07-16",
    "2026-07-11",
    "2026-06-29",
    "2026-06-27",
)


def _catalog_by_id() -> dict[str, dict[str, Any]]:
    if not CATALOG_JSON.exists():
        return {}
    streams = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for s in streams:
        for key in ("id", "yt_id", "twitch_id"):
            val = s.get(key)
            if val:
                out[str(val)] = s
    return out


def _run_transcript_text(run_dir: Path) -> tuple[str, float]:
    """Return (lowercase text, duration_seconds)."""
    text = ""
    dur = 0.0
    plain = run_dir / "transcript.plain.txt"
    tt = run_dir / "transcript.txt"
    tj = run_dir / "transcript.json"
    if plain.exists() and plain.stat().st_size > 50:
        text = plain.read_text(encoding="utf-8", errors="ignore").lower()
    elif tt.exists() and tt.stat().st_size > 50:
        raw = tt.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"\[\d+:\d+(?::\d+)?\]", " ", raw).lower()
    if tj.exists():
        try:
            data = json.loads(tj.read_text(encoding="utf-8"))
            dur = float(data.get("duration") or 0)
            if not text:
                text = (data.get("text") or "").lower()
        except Exception:
            pass
    return text, dur


def rank_munch_crum_episodes(
    *,
    min_duration_seconds: float = MIN_DURATION_SECONDS,
) -> list[dict[str, Any]]:
    catalog = _catalog_by_id()
    results: list[dict[str, Any]] = []

    if not RUNS_DIR.exists():
        return results

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        text, dur = _run_transcript_text(run_dir)
        if not text.strip():
            continue

        meta: dict[str, Any] = {}
        meta_path = run_dir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            if not dur:
                dur = float(meta.get("duration_seconds") or 0)

        stream = catalog.get(run_dir.name) or catalog.get(str(meta.get("yt_id") or "")) or catalog.get(
            str(meta.get("vod_id") or "")
        )
        if stream and not dur:
            dur = float(stream.get("duration_seconds") or 0)

        if dur and dur < min_duration_seconds:
            continue

        char_hits: dict[str, int] = defaultdict(int)
        score = 0
        for pat, key, weight in CHAR_PATTERNS:
            n = len(re.findall(pat, text, re.I))
            if n:
                char_hits[key] += n
                score += n * weight

        arc_hits: dict[str, int] = defaultdict(int)
        for pat, key, weight in ARC_PATTERNS:
            n = len(re.findall(pat, text, re.I))
            if n:
                arc_hits[key] += n
                score += n * weight

        if char_hits.get("munch", 0) + char_hits.get("crum", 0) < 3 and sum(arc_hits.values()) < 2:
            continue

        date = str(meta.get("date") or (stream or {}).get("date") or "")
        title = str(meta.get("title") or (stream or {}).get("title") or run_dir.name)
        results.append(
            {
                "vod_id": run_dir.name,
                "date": date,
                "title": title,
                "duration_seconds": dur,
                "duration_min": round(dur / 60, 1) if dur else None,
                "score": score,
                "munch": char_hits.get("munch", 0),
                "crum": char_hits.get("crum", 0),
                "arcs": dict(arc_hits),
                "has_extraction": (run_dir / "extraction.json").exists(),
            }
        )

    results.sort(key=lambda r: (-r["score"], r["date"] or ""))
    return results


def build_pilot_set(
    ranked: list[dict[str, Any]],
    *,
    size: int = 12,
    bookmark_dates: tuple[str, ...] = PILOT_BOOKMARK_DATES,
) -> list[dict[str, Any]]:
    by_date = {r["date"]: r for r in ranked if r.get("date")}
    pilot: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in sorted(bookmark_dates, reverse=True):
        row = by_date.get(d)
        if row and row["vod_id"] not in seen:
            pilot.append(row)
            seen.add(row["vod_id"])
    for row in ranked:
        if len(pilot) >= size:
            break
        if row["vod_id"] not in seen:
            pilot.append(row)
            seen.add(row["vod_id"])
    pilot = pilot[:size]
    pilot.sort(key=lambda r: r.get("date") or "")
    return pilot


def write_rankings(
    *,
    ranked_path: Path = DEFAULT_RANKED_PATH,
    pilot_path: Path = DEFAULT_PILOT_PATH,
    pilot_size: int = 12,
    min_duration_seconds: float = MIN_DURATION_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = rank_munch_crum_episodes(min_duration_seconds=min_duration_seconds)
    pilot = build_pilot_set(ranked, size=pilot_size)
    ranked_path.parent.mkdir(parents=True, exist_ok=True)
    ranked_path.write_text(json.dumps(ranked, indent=2) + "\n", encoding="utf-8")
    pilot_path.write_text(json.dumps(pilot, indent=2) + "\n", encoding="utf-8")
    return ranked, pilot
