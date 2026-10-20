"""Munch & Crum debate catalog: seed, load, validate."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .paths import REPO_ROOT

DATA_PATH = REPO_ROOT / "data" / "debates.json"
STATIC_PATH = REPO_ROOT / "quartz" / "static" / "debates.json"
MUNCH_CRUM_PATH = REPO_ROOT / "content" / "segments" / "munch-and-crum.md"
EPISODES_DIR = REPO_ROOT / "content" / "episodes"

PERSONA_ALIASES = {
    "munch": "munch",
    "ralph munchcut": "munch",
    "al manchester": "al-manchester",
    "crum": "crum",
    "leonard crum": "crum",
    "leonard confucius crumb": "crum",
    "scrum": "scrum",
    "eugene scrum": "scrum",
    "plumb": "plumb",
    "belulia": "belulia",
    "kendall": "kendelle",
    "kendelle": "kendelle",
    "case": "case-blackwell",
    "case blackwell": "case-blackwell",
    "fiona nova": "fiona",
    "fiona": "fiona",
}

KNOWN_WINNERS = {
    "munch",
    "crum",
    "draw",
    "default",
    "scrum",
    "plumb",
    "al-manchester",
    "kendelle",
    "case-blackwell",
    "fiona",
}

REQUIRED_FIELDS = ("id", "date", "episode", "topic", "participants", "winner", "summary")


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "debate"


def normalize_winner(raw: str | None) -> str | None:
    if not raw:
        return None
    t = raw.lower().strip()
    if "expand from transcript" in t or not t:
        return None
    if "draw" in t or "tie" in t or "50/50" in t or "50-50" in t:
        return "draw"
    if re.search(r"\bdefault\b", t) and not re.search(r"\bmunch\b|\bcrum\b", t):
        return "default"
    munch = bool(re.search(r"\bmunch\b|\bmanchester\b", t))
    crum = bool(re.search(r"\bcrum\b", t))
    scrum = bool(re.search(r"\bscrum\b", t))
    if scrum and not munch:
        return "scrum"
    if munch and not crum:
        return "munch"
    if crum and not munch:
        return "crum"
    if "plumb" in t:
        return "plumb"
    if munch and crum:
        return "munch" if t.find("munch") <= t.find("crum") else "crum"
    for key, slug in PERSONA_ALIASES.items():
        if key in t:
            return slug
    return None


def norm_ts(ts: str | None) -> str | None:
    if not ts:
        return None
    ts = ts.strip().replace("—", "").replace("–", "").strip()
    if not ts or not re.match(r"^\d", ts):
        return None
    parts = ts.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return f"{nums[0]}:{nums[1]:02d}"
    if len(nums) == 3:
        return f"{nums[0]}:{nums[1]:02d}:{nums[2]:02d}"
    return ts


def merge_pos(a: dict | None, b: dict | None) -> dict:
    out = dict(a or {})
    out.update(b or {})
    return out


def parse_year_md(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"\n### ", text)
    out: list[dict[str, Any]] = []
    for part in parts[1:]:
        lines = part.splitlines()
        title = lines[0].strip()
        body = "\n".join(lines[1:])
        ep_m = re.search(
            r"\*\*Episode:\*\*\s*\[\[(?:\.\./)*episodes/([^\]|]+)\|([^\]]+)\]\]\s*(?:\[([^\]]+)\])?",
            body,
        )
        if not ep_m:
            continue
        episode = ep_m.group(1).split("/")[-1]
        date = ep_m.group(2) if re.match(r"\d{4}-\d{2}-\d{2}", ep_m.group(2)) else episode[:10]
        timestamp = norm_ts(ep_m.group(3))
        topic_m = re.search(r"\*\*Topic:\*\*\s*(.+)", body)
        topic = topic_m.group(1).strip() if topic_m else title
        parts_list = re.findall(
            r"\[\[(?:\.\./)*characters/([^\]|]+)\|([^\]]+)\]\]",
            body.split("####")[0],
        )
        participants = [slug for slug, _ in parts_list] or ["munch", "crum"]
        positions: dict[str, str] = {}
        for sec in re.finditer(r"####\s+([^\n]+)\n+(.*?)(?=\n#### |\Z)", body, re.S):
            name = sec.group(1).strip()
            if name.lower() == "result":
                continue
            pos_m = re.search(r"\*\*Position:\*\*\s*(.+)", sec.group(2))
            if not pos_m:
                continue
            pos = pos_m.group(1).strip()
            if "expand from transcript" in pos.lower():
                continue
            key = PERSONA_ALIASES.get(name.lower(), slugify(name))
            positions[key] = pos
        winner_m = re.search(r"\*\*Winner:\*\*\s*(.+)", body)
        summary_m = re.search(r"\*\*Summary:\*\*\s*(.+)", body)
        winner = normalize_winner(winner_m.group(1) if winner_m else None)
        summary = summary_m.group(1).strip() if summary_m else None
        if not winner and summary:
            winner = normalize_winner(summary)
        if not re.match(r"\d{4}-\d{2}-\d{2}", str(date)):
            continue
        out.append(
            {
                "id": f"{date[:10]}-{slugify(topic)}",
                "date": date[:10],
                "episode": episode,
                "timestamp": timestamp,
                "topic": topic,
                "participants": participants,
                "positions": positions,
                "winner": winner,
                "summary": summary,
                "_src": "year",
            }
        )
    return out


def parse_occurrences(path: Path = MUNCH_CRUM_PATH) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Known occurrences\n+(.*?)(?:\n## |\Z)", text, re.S)
    if not m:
        return []
    rows: list[dict[str, Any]] = []
    skip_kw = ["award show", "cold open", "pre-debate", "pre-show", "wind-down", "discord outage"]
    row_re = re.compile(
        r"^\|\s*\[\[(?:\.\./)*episodes/([^\]|]+)(?:\|[^\]]+)?\]\]\s*\|\s*([^|]+)\|\s*(.+?)\s*\|$"
    )
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        rm = row_re.match(line)
        if not rm:
            continue
        episode = rm.group(1)
        if not re.match(r"\d{4}-\d{2}-\d{2}", episode):
            continue
        date = episode[:10]
        timestamp = norm_ts(rm.group(2).strip())
        notes = rm.group(3).strip()
        low = notes.lower()
        if any(k in low for k in skip_kw) and not re.match(r"(?i).{0,40}(debate|vs\.?)", notes):
            continue
        topic = notes.split(":")[0].strip()
        topic = re.sub(r"^(?:Munch\s*&\s*Crum:\s*|Debate:\s*)", "", topic, flags=re.I)
        rows.append(
            {
                "id": f"{date}-{slugify(topic)}",
                "date": date,
                "episode": episode,
                "timestamp": timestamp,
                "topic": topic,
                "participants": ["munch", "crum"],
                "positions": {},
                "winner": normalize_winner(notes),
                "summary": notes,
                "_src": "occ",
            }
        )
    return rows


def primary_key(e: dict[str, Any]) -> tuple:
    ts = e.get("timestamp")
    if ts:
        return ("ts", e["date"], ts)
    return ("topic", e["date"], slugify(e["topic"])[:50])


def build_debates(year_dir: Path | None = None) -> list[dict[str, Any]]:
    """Merge year-page WIP (optional) with munch-and-crum known occurrences."""
    year_entries: list[dict[str, Any]] = []
    if year_dir and year_dir.is_dir():
        for y in ("2023", "2024", "2025", "2026"):
            p = year_dir / f"{y}.md"
            if p.exists():
                year_entries.extend(parse_year_md(p))
    occ = parse_occurrences()

    merged: dict[tuple, dict[str, Any]] = {}
    for e in occ:
        merged[primary_key(e)] = e
    for e in year_entries:
        k = primary_key(e)
        if k in merged:
            base = merged[k]
            base["positions"] = merge_pos(base.get("positions"), e.get("positions"))
            if e.get("winner"):
                base["winner"] = e["winner"]
            if e.get("summary"):
                base["summary"] = e["summary"]
            if e.get("participants"):
                base["participants"] = e["participants"]
            if e.get("topic"):
                base["topic"] = e["topic"]
                base["id"] = e["id"]
            base["_src"] = "year"
            merged[k] = base
        else:
            merged[k] = e

    debates = sorted(merged.values(), key=lambda e: (e["date"], e.get("timestamp") or "", e["topic"]))

    by_date: dict[str, list] = defaultdict(list)
    for e in debates:
        by_date[e["date"]].append(e)
    for group in by_date.values():
        if len(group) > 1:
            for i, e in enumerate(group, 1):
                e["night_index"] = i

    seen_ids: dict[str, int] = {}
    clean: list[dict[str, Any]] = []
    for e in debates:
        e = {k: v for k, v in e.items() if not str(k).startswith("_")}
        base_id = e["id"]
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            e["id"] = f"{base_id}-{seen_ids[base_id]}"
        else:
            seen_ids[base_id] = 1
        e.setdefault("positions", {})
        clean.append(e)
    return clean


def write_debates(debates: list[dict[str, Any]], *, sync_static: bool = True) -> Path:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(debates, indent=2, ensure_ascii=False) + "\n"
    DATA_PATH.write_text(payload, encoding="utf-8")
    if sync_static:
        STATIC_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATIC_PATH.write_text(payload, encoding="utf-8")
    return DATA_PATH


def load_debates(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_debates(debates: list[dict[str, Any]] | None = None) -> list[str]:
    """Return list of validation error strings (empty = ok)."""
    if debates is None:
        if not DATA_PATH.exists():
            return [f"missing {DATA_PATH}"]
        debates = load_debates()

    errors: list[str] = []
    ids: set[str] = set()
    episode_files = {p.stem for p in EPISODES_DIR.glob("*.md")} if EPISODES_DIR.exists() else set()

    for i, e in enumerate(debates):
        prefix = f"[{i}] {e.get('id', '?')}"
        for field in REQUIRED_FIELDS:
            if field not in e:
                errors.append(f"{prefix}: missing field {field}")
        did = e.get("id")
        if did in ids:
            errors.append(f"{prefix}: duplicate id")
        ids.add(did)
        date = e.get("date") or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            errors.append(f"{prefix}: bad date {date!r}")
        ep = e.get("episode") or ""
        # episode stubs may use vod-suffixed filenames; accept date prefix match
        if episode_files and ep not in episode_files and not any(
            f.startswith(ep) or ep.startswith(f[:10]) for f in episode_files
        ):
            # soft: only warn if no episode starts with date
            if date and not any(f.startswith(date) for f in episode_files):
                errors.append(f"{prefix}: unknown episode {ep!r}")
        winner = e.get("winner")
        if winner is not None and winner not in KNOWN_WINNERS:
            errors.append(f"{prefix}: unusual winner {winner!r}")
        parts = e.get("participants")
        if not isinstance(parts, list) or not parts:
            errors.append(f"{prefix}: participants must be non-empty list")
        if not e.get("topic"):
            errors.append(f"{prefix}: empty topic")

    return errors


def cumulative_scoreboard(debates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cumulative Munch/Crum wins over chronological debates."""
    munch = crum = 0
    series = []
    for e in sorted(debates, key=lambda x: (x["date"], x.get("timestamp") or "", x["id"])):
        w = e.get("winner")
        if w == "munch" or w == "al-manchester":
            munch += 1
        elif w == "crum":
            crum += 1
        series.append(
            {
                "id": e["id"],
                "date": e["date"],
                "timestamp": e.get("timestamp"),
                "winner": w,
                "munch": munch,
                "crum": crum,
            }
        )
    return series
