"""Character appearance indexing and promotion (minor ≥3, recurring ≥6, core top-20)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .canon import is_excluded_external_subject, load_wiki_canon
from .paths import CONTENT_CHARACTERS, RUNS_DIR

APPEARANCE_INDEX_PATH = RUNS_DIR / "character-appearance-index.json"
MINOR_THRESHOLD = 3
RECURRING_THRESHOLD = 6
CORE_TALENT_LIMIT = 20

_EP_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_EXCLUDED_STATUS_TOKENS = (
    "guest",
    "call-in",
    "community",
    "public figure",
    "historical figure",
    "satirized",
    "retired",
    "deceased",
)


@dataclass
class AppearanceRecord:
    slug: str
    name: str
    episodes: set[str] = field(default_factory=set)
    display_names: set[str] = field(default_factory=set)

    @property
    def count(self) -> int:
        return len(self.episodes)


@dataclass
class PromoteReport:
    index_path: Path
    characters_indexed: int = 0
    minors_created: list[str] = field(default_factory=list)
    promoted_recurring: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _slugify(text: str) -> str:
    s = text.lower().replace("&", "and").replace("–", "-").replace("—", "-")
    s = "".join(c if c.isalnum() or c in " -" else "" for c in s)
    return "-".join(s.split())


def _episode_from_appearance_row(row: str) -> str | None:
    m = _EP_DATE_RE.search(row)
    return m.group(1) if m else None


def _collect_appearance_dates_from_page(path: Path) -> set[str]:
    """Distinct episode dates from ## Appearances (including collapsed archive)."""
    from .wiki_updater import _collect_appearance_rows, _extract_section, _split_frontmatter_and_body

    text = path.read_text(encoding="utf-8")
    _, body = _split_frontmatter_and_body(text)
    _before, section, _after = _extract_section(body, "## Appearances")
    if "## Appearances" not in body:
        return set()
    dates: set[str] = set()
    for row in _collect_appearance_rows(section):
        d = _episode_from_appearance_row(row)
        if d:
            dates.add(d)
    return dates


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _resolve_slug_and_name(raw_name: str, canon: dict) -> tuple[str, str]:
    """Map a detected name to wiki slug when possible."""
    from .wiki_updater import _match_character_file

    name = (raw_name or "").strip()
    if not name:
        return "", ""
    char_file, slug = _match_character_file(name, canon)
    if char_file and char_file.exists():
        fm = _parse_frontmatter(char_file)
        title = str(fm.get("title") or name).strip()
        return char_file.stem, title
    return _slugify(name), name


def build_appearance_index(*, write: bool = True) -> dict[str, AppearanceRecord]:
    """
    Aggregate distinct episode dates per character slug from:
    - extraction.json characters[] (speaking only)
    - existing character page Appearances tables
    - unknown-characters.jsonl (speaking only)
    """
    from .wiki_updater import UNKNOWN_CHARACTERS_LOG

    canon = load_wiki_canon()
    records: dict[str, AppearanceRecord] = {}

    def touch(slug: str, name: str, episode: str | None) -> None:
        if not slug or not episode:
            return
        if is_excluded_external_subject(name, ""):
            return
        rec = records.get(slug)
        if rec is None:
            rec = AppearanceRecord(slug=slug, name=name)
            records[slug] = rec
        elif name and len(name) > len(rec.name):
            rec.name = name
        rec.display_names.add(name)
        rec.episodes.add(episode)

    # 1) Extractions
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        ext_path = run_dir / "extraction.json"
        if not ext_path.exists():
            continue
        meta: dict[str, Any] = {}
        meta_path = run_dir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        episode = str(meta.get("date") or "").strip()
        if not _EP_DATE_RE.fullmatch(episode or ""):
            # Fall back to nothing — skip undated
            continue
        try:
            extraction = json.loads(ext_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for char_info in extraction.get("characters") or []:
            if not isinstance(char_info, dict):
                continue
            if not bool(char_info.get("speaking")):
                continue
            name = str(char_info.get("canonical_name") or char_info.get("name") or "").strip()
            if not name:
                continue
            notes = str(char_info.get("notes") or "")
            if is_excluded_external_subject(name, notes):
                continue
            slug, resolved_name = _resolve_slug_and_name(name, canon)
            touch(slug, resolved_name or name, episode)

    # 2) Appearances tables on existing pages
    for path in CONTENT_CHARACTERS.glob("*.md"):
        if path.name == "index.md":
            continue
        slug = path.stem
        fm = _parse_frontmatter(path)
        name = str(fm.get("title") or slug).strip()
        for ep in _collect_appearance_dates_from_page(path):
            touch(slug, name, ep)

    # 3) Unknown queue (speaking)
    if UNKNOWN_CHARACTERS_LOG.exists():
        for line in UNKNOWN_CHARACTERS_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not bool(row.get("speaking")):
                continue
            name = str(row.get("name") or "").strip()
            episode = str(row.get("episode") or "").strip()
            notes = str(row.get("notes") or "")
            if not name or not _EP_DATE_RE.fullmatch(episode or ""):
                continue
            if is_excluded_external_subject(name, notes):
                continue
            slug = str(row.get("slug") or "").strip() or _slugify(name)
            # Re-resolve through canon in case a page was created later
            resolved_slug, resolved_name = _resolve_slug_and_name(name, canon)
            if resolved_slug:
                slug = resolved_slug
            touch(slug, resolved_name or name, episode)

    if write:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "thresholds": {
                "minor": MINOR_THRESHOLD,
                "recurring": RECURRING_THRESHOLD,
                "core_talent": CORE_TALENT_LIMIT,
            },
            "characters": {
                slug: {
                    "name": rec.name,
                    "count": rec.count,
                    "episodes": sorted(rec.episodes),
                    "display_names": sorted(rec.display_names),
                }
                for slug, rec in sorted(records.items(), key=lambda kv: (-kv[1].count, kv[0]))
            },
        }
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        APPEARANCE_INDEX_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return records


def load_appearance_counts() -> dict[str, int]:
    """Load counts from cached index, rebuilding if missing."""
    if APPEARANCE_INDEX_PATH.exists():
        try:
            data = json.loads(APPEARANCE_INDEX_PATH.read_text(encoding="utf-8"))
            chars = data.get("characters") or {}
            return {slug: int(info.get("count") or 0) for slug, info in chars.items()}
        except Exception:
            pass
    records = build_appearance_index(write=True)
    return {slug: rec.count for slug, rec in records.items()}


def appearance_count_for(slug: str, *, counts: dict[str, int] | None = None) -> int:
    table = counts if counts is not None else load_appearance_counts()
    return int(table.get(slug, 0))


def _status_excluded_from_promotion(status: str) -> bool:
    s = (status or "").lower()
    return any(tok in s for tok in _EXCLUDED_STATUS_TOKENS)


def _status_promotable_to_recurring(status: str) -> bool:
    """Only normalize empty / active / minor statuses to recurring."""
    s = (status or "").strip().lower()
    if _is_recurring_status(s):
        return False
    if _status_excluded_from_promotion(s):
        return False
    if not s or s == "active" or "minor" in s:
        return True
    return False


def _is_recurring_status(status: str) -> bool:
    return "recurring" in (status or "").lower()


def _set_frontmatter_status(path: Path, status: str, *, dry_run: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return False
    if str(fm.get("status") or "") == status:
        return False
    fm["status"] = status
    new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    new_text = f"---\n{new_fm}\n---{parts[2]}"
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def _ensure_minor_tag(path: Path, *, dry_run: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        return
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return
    tags = list(fm.get("tags") or [])
    if "minor" in [str(t).lower() for t in tags]:
        return
    tags.append("minor")
    fm["tags"] = tags
    new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    if not dry_run:
        path.write_text(f"---\n{new_fm}\n---{parts[2]}", encoding="utf-8")


def promote_characters(*, dry_run: bool = False, rebuild_index: bool = True) -> PromoteReport:
    """
    - ≥3 distinct episodes → create minor contributor page if missing
    - ≥6 distinct episodes → set status: recurring (unless excluded guest/public)
    """
    from .wiki_updater import create_character_page

    records = build_appearance_index(write=rebuild_index)

    report = PromoteReport(index_path=APPEARANCE_INDEX_PATH, characters_indexed=len(records))
    canon = load_wiki_canon()

    for slug, rec in sorted(records.items(), key=lambda kv: (-kv[1].count, kv[0])):
        if rec.count < MINOR_THRESHOLD:
            continue
        if is_excluded_external_subject(rec.name, ""):
            report.skipped.append(slug)
            continue

        path = CONTENT_CHARACTERS / f"{slug}.md"
        if not path.exists():
            if rec.count >= MINOR_THRESHOLD:
                # Seed page from earliest episode in the index
                ep_slug = sorted(rec.episodes)[0]
                notes = (
                    f"Auto-created minor character after appearing in {rec.count} "
                    f"extracted episodes (threshold {MINOR_THRESHOLD})."
                )
                created = create_character_page(
                    rec.name,
                    slug,
                    ep_slug,
                    notes,
                    [],
                    dry_run=dry_run,
                    status="minor contributor",
                    tags=["character", "minor"],
                )
                if created is not None:
                    report.minors_created.append(slug)
                else:
                    report.skipped.append(slug)
            continue

        fm = _parse_frontmatter(path)
        status = str(fm.get("status") or "")
        if _status_excluded_from_promotion(status):
            report.skipped.append(slug)
            continue

        if rec.count >= RECURRING_THRESHOLD and _status_promotable_to_recurring(status):
            if _set_frontmatter_status(path, "recurring", dry_run=dry_run):
                report.promoted_recurring.append(slug)
        elif (
            MINOR_THRESHOLD <= rec.count < RECURRING_THRESHOLD
            and not status
        ):
            if _set_frontmatter_status(path, "minor contributor", dry_run=dry_run):
                if not dry_run:
                    _ensure_minor_tag(path, dry_run=dry_run)

    return report


def select_core_talent(
    characters: list | None = None,
    *,
    limit: int = CORE_TALENT_LIMIT,
    counts: dict[str, int] | None = None,
) -> list:
    """
    Top `limit` characters by appearance count among recurring-eligible talent:
    status contains "recurring", or appearance count ≥ RECURRING_THRESHOLD
    (and passes exclusion filters). Minors/guests never qualify.
    """
    from .canon import CanonEntity, is_core_network_character

    if characters is None:
        characters = load_wiki_canon().get("characters", [])
    count_table = counts if counts is not None else load_appearance_counts()

    eligible: list[tuple[int, CanonEntity]] = []
    for char in characters:
        if not isinstance(char, CanonEntity):
            continue
        if not is_core_network_character(char):
            continue
        slug = char.file_path.stem if char.file_path else _slugify(char.name)
        count = appearance_count_for(slug, counts=count_table)
        recurring = _is_recurring_status(char.status or "")
        if not recurring and count < RECURRING_THRESHOLD:
            continue
        eligible.append((count, char))

    eligible.sort(key=lambda pair: (-pair[0], pair[1].name.lower()))
    return [char for _, char in eligible[:limit]]
