from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .exclusions import excluded_ids, is_excluded, is_excluded_entry
from .paths import CATALOG_JSON, CONTENT_DIR, CONTENT_EPISODES, RUNS_DIR

LINK_RE = re.compile(r"episodes/(\d{4}-\d{2}-\d{2}(?:-[A-Za-z0-9_-]+)?)")
VOD_ID_RE = re.compile(r'^vod_id:\s*"?([^"\n]+)"?\s*$', re.M)
FIRST_SEEN_RE = re.compile(r"^first_seen:\s*(\S+)\s*$", re.M)


@dataclass
class ExpungePlan:
    runs: dict[str, str] = field(default_factory=dict)  # run id -> date
    pages_deleted: list[Path] = field(default_factory=list)
    pages_regenerated: list[tuple[str, str]] = field(default_factory=list)  # (date, survivor run id)
    renames: dict[str, str] = field(default_factory=dict)  # old slug -> new slug
    full_dates: set[str] = field(default_factory=set)
    shared_dates: set[str] = field(default_factory=set)
    lines_removed: list[tuple[Path, str]] = field(default_factory=list)
    lines_replaced: list[tuple[Path, str, str]] = field(default_factory=list)
    first_seen_changes: list[tuple[Path, str, str]] = field(default_factory=list)
    needs_review: list[tuple[Path, str]] = field(default_factory=list)
    orphaned: list[Path] = field(default_factory=list)
    catalog_rows_dropped: int = 0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_ids_for_entry(entry: dict[str, Any]) -> list[str]:
    return [str(entry[k]) for k in ("yt_id", "twitch_id") if entry.get(k) and (RUNS_DIR / str(entry[k])).is_dir()]


def _episode_pages() -> dict[Path, str]:
    pages: dict[Path, str] = {}
    for p in CONTENT_EPISODES.glob("*.md"):
        if p.name == "index.md":
            continue
        m = VOD_ID_RE.search(p.read_text(encoding="utf-8")[:2000])
        pages[p] = m.group(1).strip() if m else ""
    return pages


def _fingerprints(extraction: dict[str, Any]) -> set[str]:
    from .wiki_updater import _short_appearance_notes

    fps: set[str] = set()

    def add(text: Any, n: int) -> None:
        s = " ".join(str(text or "").replace("|", "/").split())
        if len(s) >= 20:
            fps.add(s[:n])

    for s in extraction.get("segments") or []:
        if isinstance(s, dict):
            add(s.get("title"), 60)
            add(s.get("notes"), 40)
    for n in extraction.get("lore_notes") or []:
        add(n.get("fact") or n.get("note") or n.get("text") if isinstance(n, dict) else n, 35)
    for st in extraction.get("storylines") or []:
        if isinstance(st, dict):
            add(st.get("beat"), 40)
    for c in extraction.get("characters") or []:
        if isinstance(c, dict):
            add(_short_appearance_notes(str(c.get("notes") or "")), 40)
    return fps


def _character_notes(extraction: dict[str, Any], canon: dict) -> dict[str, str]:
    from .promote import _resolve_slug_and_name

    out: dict[str, str] = {}
    for c in extraction.get("characters") or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("canonical_name") or c.get("name") or "").strip()
        if name:
            slug, _ = _resolve_slug_and_name(name, canon)
            out.setdefault(slug, str(c.get("notes") or ""))
    return out


def _is_row_or_bullet(line: str) -> bool:
    """Table rows and generated Notable-moments bullets; hand-written prose bullets go to review."""
    s = line.lstrip()
    return s.startswith("|") or s.startswith("- **[") or s.startswith("- First seen in [[episodes/")


def _matches(line: str, fps: set[str]) -> bool:
    flat = " ".join(line.split())
    return any(fp in flat for fp in fps)


def plan_expunge() -> ExpungePlan:
    from .canon import load_wiki_canon

    plan = ExpungePlan()
    banned = excluded_ids()
    catalog: list[dict[str, Any]] = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    plan.catalog_rows_dropped = sum(1 for e in catalog if is_excluded_entry(e))

    for e in catalog:
        if is_excluded_entry(e):
            for rid in _run_ids_for_entry(e):
                plan.runs[rid] = str(e.get("date") or "")
    for rid in banned:
        if (RUNS_DIR / rid).is_dir() and rid not in plan.runs:
            plan.runs[rid] = str(_load_json(RUNS_DIR / rid / "meta.json").get("date") or "")

    pages = _episode_pages()
    plan.pages_deleted = sorted(p for p, vid in pages.items() if vid and is_excluded(vid))
    dates = {d for d in plan.runs.values() if d} | {p.stem[:10] for p in plan.pages_deleted}

    canon = load_wiki_canon()
    excluded_fps: dict[str, set[str]] = {d: set() for d in dates}
    excluded_chars: dict[str, set[str]] = {d: set() for d in dates}
    survivor_fps: dict[str, set[str]] = {d: set() for d in dates}
    survivor_chars: dict[str, dict[str, str]] = {d: {} for d in dates}
    for rid, d in plan.runs.items():
        ext = _load_json(RUNS_DIR / rid / "extraction.json")
        if d in dates and ext:
            excluded_fps[d] |= _fingerprints(ext)
            excluded_chars[d] |= set(_character_notes(ext, canon))

    survivors_by_date: dict[str, list[str]] = {d: [] for d in dates}
    for e in catalog:
        d = str(e.get("date") or "")
        if d in dates and not is_excluded_entry(e):
            for rid in _run_ids_for_entry(e):
                ext = _load_json(RUNS_DIR / rid / "extraction.json")
                if ext:
                    survivors_by_date[d].append(rid)
                    survivor_fps[d] |= _fingerprints(ext)
                    for slug, notes in _character_notes(ext, canon).items():
                        survivor_chars[d].setdefault(slug, notes)

    remaining = {p: vid for p, vid in pages.items() if p not in plan.pages_deleted}
    for d in sorted(dates):
        left = sorted(p for p in remaining if p.stem[:10] == d)
        if not left:
            paged = set(remaining.values())
            todo = [rid for rid in survivors_by_date[d] if rid not in paged]
            if todo:
                plan.pages_regenerated += [(d, rid) for rid in todo]
                plan.shared_dates.add(d)
            else:
                plan.full_dates.add(d)
            continue
        plan.shared_dates.add(d)
        if not any(p.stem == d for p in left):
            plan.renames[left[0].stem] = d

    from .wiki_updater import _appearance_notes_usable, _short_appearance_notes

    deleted_stems = {p.stem for p in plan.pages_deleted}
    for path in sorted(CONTENT_DIR.rglob("*.md")):
        if path.parent == CONTENT_EPISODES and (path.name == "index.md" or path.stem in deleted_stems):
            continue
        is_episode = path.parent == CONTENT_EPISODES
        section = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                section = line.strip().lower()
            slugs = LINK_RE.findall(line)
            line_dates = {s[:10] for s in slugs if s[:10] in dates and s not in plan.renames}
            if not line_dates:
                continue
            if line_dates & plan.full_dates:
                links_elsewhere = {s[:10] for s in slugs} - plan.full_dates
                if not is_episode and _is_row_or_bullet(line) and not links_elsewhere:
                    plan.lines_removed.append((path, line))
                else:
                    plan.needs_review.append((path, line))
                continue
            if is_episode or not _is_row_or_bullet(line):
                continue
            d = sorted(line_dates)[0]
            if len(line_dates) > 1:
                continue
            slug = path.stem
            in_appearances = section.startswith("## appearances") and line.lstrip().startswith("|")
            from_excluded = _matches(line, excluded_fps[d]) and not _matches(line, survivor_fps[d])
            if in_appearances and path.parent.name == "characters":
                if slug in survivor_chars[d]:
                    if from_excluded:
                        note = _short_appearance_notes(survivor_chars[d][slug]).replace("|", "/")
                        if _appearance_notes_usable(note):
                            plan.lines_replaced.append((path, line, f"| [[episodes/{d}|{d}]] | {note} |"))
                        else:
                            plan.lines_removed.append((path, line))
                elif slug in excluded_chars[d] or from_excluded:
                    plan.lines_removed.append((path, line))
            elif from_excluded:
                plan.lines_removed.append((path, line))
    return plan


def _rewrite_file(path: Path, remove: set[str], replace: dict[str, str]) -> None:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line in remove:
            continue
        out.append(replace.get(line, line))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _recompute_first_seen(plan: ExpungePlan) -> None:
    for path in sorted((CONTENT_DIR / "characters").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = FIRST_SEEN_RE.search(text)
        current = m.group(1).strip("'\"") if m else ""
        dates_left = sorted({s[:10] for s in LINK_RE.findall(text)} - plan.full_dates)
        if m and current in plan.full_dates:
            if dates_left:
                plan.first_seen_changes.append((path, current, dates_left[0]))
                path.write_text(text[: m.start(1)] + dates_left[0] + text[m.end(1) :], encoding="utf-8")
            else:
                plan.orphaned.append(path)


def apply_expunge(plan: ExpungePlan) -> None:
    from .catalog import generate_episodes_index
    from .episode import update_episode_from_extraction
    from .promote import build_appearance_index
    from .wiki_updater import UNKNOWN_CHARACTERS_LOG

    for p in plan.pages_deleted:
        p.unlink()

    for d, rid in plan.pages_regenerated:
        if (CONTENT_EPISODES / f"{d}.md").exists():
            (CONTENT_EPISODES / f"{d}-{rid}.md").write_text(f'---\nvod_id: "{rid}"\n---\n', encoding="utf-8")
        update_episode_from_extraction(rid, _load_json(RUNS_DIR / rid / "extraction.json"))

    removals: dict[Path, set[str]] = {}
    replacements: dict[Path, dict[str, str]] = {}
    for path, line in plan.lines_removed:
        removals.setdefault(path, set()).add(line)
    for path, old, new in plan.lines_replaced:
        replacements.setdefault(path, {})[old] = new
    for path in set(removals) | set(replacements):
        _rewrite_file(path, removals.get(path, set()), replacements.get(path, {}))

    for old, new in plan.renames.items():
        (CONTENT_EPISODES / f"{old}.md").rename(CONTENT_EPISODES / f"{new}.md")
    if plan.renames:
        pattern = re.compile(r"episodes/(" + "|".join(re.escape(o) for o in plan.renames) + r")(?![A-Za-z0-9_-])")
        for path in CONTENT_DIR.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            new_text = pattern.sub(lambda m: f"episodes/{plan.renames[m.group(1)]}", text)
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")

    _recompute_first_seen(plan)

    for rid in plan.runs:
        shutil.rmtree(RUNS_DIR / rid, ignore_errors=True)

    if UNKNOWN_CHARACTERS_LOG.exists():
        kept = [
            ln
            for ln in UNKNOWN_CHARACTERS_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not is_excluded(_load_line(ln).get("vod_id"))
        ]
        UNKNOWN_CHARACTERS_LOG.write_text("\n".join(kept) + "\n", encoding="utf-8")

    catalog = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    kept_rows = [e for e in catalog if not is_excluded_entry(e)]
    if len(kept_rows) != len(catalog):
        CATALOG_JSON.write_text(json.dumps(kept_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    generate_episodes_index()
    build_appearance_index(write=True)


def _load_line(line: str) -> dict[str, Any]:
    try:
        return json.loads(line)
    except Exception:
        return {}
