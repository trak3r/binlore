from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canon import CanonEntity, load_wiki_canon
from .paths import (
    CONTENT_CHARACTERS,
    CONTENT_EPISODES,
    CONTENT_SEGMENTS,
    CONTENT_STORYLINES,
    RUNS_DIR,
)


def _slugify(text: str) -> str:
    s = text.lower().replace("–", "-").replace("—", "-")
    s = "".join(c if c.isalnum() or c in " -" else "" for c in s)
    return "-".join(s.split())


@dataclass
class UpdateReport:
    vod_id: str
    episode_slug: str
    characters_updated: list[str] = field(default_factory=list)
    characters_created: list[str] = field(default_factory=list)
    segments_updated: list[str] = field(default_factory=list)
    storylines_updated: list[str] = field(default_factory=list)
    indexes_updated: list[str] = field(default_factory=list)


def _split_frontmatter_and_body(content: str) -> tuple[str, str]:
    if not content.startswith("---"):
        return "", content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return "", content
    return f"---{parts[1]}---\n\n", parts[2].lstrip()


def _extract_section(body: str, heading: str) -> tuple[str, str, str]:
    """
    Splits body into (before_section, section_content, after_section).
    heading is the exact header e.g. '## Appearances'
    """
    pattern = rf"(^|\n)({re.escape(heading)}\s*\n)"
    match = re.search(pattern, body, re.MULTILINE)
    if not match:
        return body, "", ""

    start_pos = match.end()
    # Find next section heading of same or higher level (# or ##)
    next_match = re.search(r"\n(?=#{1,2}\s)", body[start_pos:])
    if next_match:
        end_pos = start_pos + next_match.start()
        return body[:start_pos], body[start_pos:end_pos].strip(), body[end_pos:]
    else:
        return body[:start_pos], body[start_pos:].strip(), ""


def _append_table_row(
    section_text: str,
    new_row: str,
    dedupe_key: str,
    default_headers: tuple[str, str] = ("| Episode | Notes |", "|---|---|"),
) -> str:
    """Append a table row to markdown section, removing seed/placeholder rows."""
    if dedupe_key in section_text:
        return section_text

    lines = section_text.splitlines()
    filtered_lines: list[str] = []
    for line in lines:
        if "_TBD_" in line or "Seed page" in line or "backfill from streams" in line:
            continue
        filtered_lines.append(line)

    # Find the last table row
    last_table_idx = -1
    for i, line in enumerate(filtered_lines):
        if line.strip().startswith("|") and line.strip().endswith("|"):
            last_table_idx = i

    if last_table_idx != -1:
        filtered_lines.insert(last_table_idx + 1, new_row)
    else:
        # No existing table found in section, create header then add row
        hdr, sep = default_headers
        if filtered_lines and filtered_lines[-1].strip():
            filtered_lines.append("")
        filtered_lines.extend([hdr, sep, new_row])

    return "\n".join(filtered_lines)


def _append_bullet(section_text: str, new_bullet: str, dedupe_key: str) -> str:
    """Append a bullet point to markdown section, removing seed/placeholder bullets."""
    if dedupe_key in section_text:
        return section_text

    lines = section_text.splitlines()
    filtered_lines: list[str] = []
    for line in lines:
        if "_TBD" in line:
            continue
        filtered_lines.append(line)

    filtered_lines.append(new_bullet)
    return "\n".join(filtered_lines)


def _match_character_file(name: str, canon: dict[str, list[CanonEntity]]) -> tuple[Path | None, str]:
    name_clean = name.strip()
    slug = _slugify(name_clean)

    # Check direct file match
    target = CONTENT_CHARACTERS / f"{slug}.md"
    if target.exists():
        return target, slug

    # Check known aliases
    for char in canon.get("characters", []):
        if char.name.lower() == name_clean.lower() or slug == _slugify(char.name):
            return char.file_path, _slugify(char.name)
        for alias in char.aliases:
            if alias.lower() == name_clean.lower() or slug == _slugify(alias):
                return char.file_path, _slugify(char.name)

    return None, slug


def _match_segment_file(title: str, canon: dict[str, list[CanonEntity]]) -> Path | None:
    title_lower = title.lower()
    for seg in canon.get("segments", []):
        seg_lower = seg.name.lower()
        if seg_lower in title_lower or title_lower in seg_lower:
            return seg.file_path
        for alias in seg.aliases:
            if alias.lower() in title_lower or title_lower in alias.lower():
                return seg.file_path
        # Check specific show segment keywords
        if "debate" in title_lower and ("debate" in seg_lower or "munch" in seg_lower):
            return seg.file_path
        if "hype" in title_lower and "hype" in seg_lower:
            return seg.file_path
        if ("cryptozeus" in title_lower or "gameplay" in title_lower or "jill" in title_lower or "gaming" in title_lower) and "cryptozeus" in seg_lower:
            return seg.file_path
        if ("science" in title_lower or "chet" in title_lower or "skynce" in title_lower or "boob" in title_lower) and "chet" in seg_lower:
            return seg.file_path
        if ("news" in title_lower or "breaking" in title_lower) and seg_lower == "news":
            return seg.file_path
    return None


def _match_storyline_file(title: str, canon: dict[str, list[CanonEntity]]) -> Path | None:
    title_lower = title.lower()
    for story in canon.get("storylines", []):
        story_lower = story.name.lower()
        if story_lower in title_lower or title_lower in story_lower:
            return story.file_path
        if ("munch" in title_lower and "crum" in title_lower) or "rivalry" in title_lower:
            if "rivalry" in story_lower:
                return story.file_path
    return None


def update_character_file(
    file_path: Path,
    ep_slug: str,
    char_notes: str,
    lore_facts: list[tuple[str, str]],  # [(timestamp, fact), ...]
    *,
    dry_run: bool = False,
) -> bool:
    """Updates appearances table and notable moments in a character markdown file."""
    content = file_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter_and_body(content)
    modified = False

    # 1. Update Appearances (if appearances section exists, or if not the host)
    if "## Appearances" in body or file_path.stem != "case-blackwell":
        before_app, app_text, after_app = _extract_section(body, "## Appearances")
        if not app_text and "## Appearances" not in body:
            # Add section before Notable moments or at end
            if "## Notable moments" in body:
                parts = body.split("## Notable moments", 1)
                body = f"{parts[0].rstrip()}\n\n## Appearances\n\n## Notable moments{parts[1]}"
            else:
                body = f"{body.rstrip()}\n\n## Appearances\n"
            before_app, app_text, after_app = _extract_section(body, "## Appearances")

        ep_link = f"[[episodes/{ep_slug}|{ep_slug}]]"
        safe_notes = char_notes.replace("|", "/").strip()
        new_row = f"| {ep_link} | {safe_notes} |"
        updated_app = _append_table_row(
            app_text,
            new_row,
            dedupe_key=ep_slug,
            default_headers=("| Episode | Notes |", "|---|---|"),
        )
        if updated_app != app_text:
            body = f"{before_app}\n{updated_app}\n{after_app}"
            modified = True

    # 2. Update Notable moments
    if lore_facts:
        before_mom, mom_text, after_mom = _extract_section(body, "## Notable moments")
        if not mom_text and "## Notable moments" not in body:
            # Append section before Open questions or at end
            if "## Open questions" in body:
                parts = body.split("## Open questions", 1)
                body = f"{parts[0].rstrip()}\n\n## Notable moments\n\n## Open questions{parts[1]}"
            else:
                body = f"{body.rstrip()}\n\n## Notable moments\n"
            before_mom, mom_text, after_mom = _extract_section(body, "## Notable moments")

        updated_mom = mom_text
        for ts, fact in lore_facts:
            fact_snip = fact[:35]
            bullet = f"- **[{ts}]** ([[episodes/{ep_slug}|{ep_slug}]]): {fact}"
            updated_mom = _append_bullet(updated_mom, bullet, dedupe_key=fact_snip)

        if updated_mom != mom_text:
            body = f"{before_mom}\n{updated_mom}\n{after_mom}"
            modified = True

    if modified and not dry_run:
        new_content = f"{fm}{body.strip()}\n"
        file_path.write_text(new_content, encoding="utf-8")

    return modified


def create_character_page(
    name: str,
    slug: str,
    ep_slug: str,
    char_notes: str,
    lore_facts: list[tuple[str, str]],
    *,
    dry_run: bool = False,
) -> Path:
    """Create a new character markdown file and add it to characters/index.md."""
    target_path = CONTENT_CHARACTERS / f"{slug}.md"

    appearances_row = f"| [[episodes/{ep_slug}|{ep_slug}]] | {char_notes.replace('|', '/').strip()} |"
    notable_bullets: list[str] = []
    for ts, fact in lore_facts:
        notable_bullets.append(f"- **[{ts}]** ([[episodes/{ep_slug}|{ep_slug}]]): {fact}")

    if not notable_bullets:
        notable_bullets.append(f"- First identified in [[episodes/{ep_slug}|Episode {ep_slug}]].")

    content = f"""---
title: {name}
type: character
aliases: []
first_seen: {ep_slug}
status: recurring
tags:
  - character
---

# {name}

**{name}** appears on *Barely Informed News*. On-air characters and personas are typically portrayed by [[case-blackwell|Case Blackwell]] using face filters and voice changers.

## Overview

{char_notes}

## Appearances

| Episode | Notes |
|---------|-------|
{appearances_row}

## Notable moments

{chr(10).join(notable_bullets)}

## Open questions

- Full backstory and recurring lore
"""
    if not dry_run:
        target_path.write_text(content, encoding="utf-8")

        # Also add to characters/index.md
        index_path = CONTENT_CHARACTERS / "index.md"
        if index_path.exists():
            idx_content = index_path.read_text(encoding="utf-8")
            char_link = f"[[{slug}|{name}]]"
            if char_link not in idx_content and f"[[characters/{slug}|" not in idx_content:
                short_note = char_notes.split(".")[0].replace("|", "/") if char_notes else "Recurring persona"
                new_row = f"| {char_link} | recurring | {short_note} |"
                fm_idx, body_idx = _split_frontmatter_and_body(idx_content)
                lines = body_idx.splitlines()
                last_tbl = -1
                for i, l in enumerate(lines):
                    if l.strip().startswith("|") and l.strip().endswith("|"):
                        last_tbl = i
                if last_tbl != -1:
                    lines.insert(last_tbl + 1, new_row)
                    new_idx = f"{fm_idx}{chr(10).join(lines)}\n"
                    index_path.write_text(new_idx, encoding="utf-8")

    return target_path


def update_storyline_file(
    file_path: Path,
    ep_slug: str,
    beats: list[tuple[str, str]],  # [(timestamp, beat), ...]
    *,
    dry_run: bool = False,
) -> bool:
    """Updates Key beats in a storyline markdown file."""
    content = file_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter_and_body(content)
    before_beats, beats_text, after_beats = _extract_section(body, "## Key beats")
    if not beats_text:
        return False

    updated_beats = beats_text
    modified = False
    for ts, beat in beats:
        beat_snip = beat[:40]
        date_col = f"[[episodes/{ep_slug}|{ep_slug}]] [{ts}]"
        source_col = f"[[episodes/{ep_slug}#storyline-updates|Episode {ep_slug}]]"
        safe_beat = beat.replace("|", "/")
        new_row = f"| {date_col} | {safe_beat} | {source_col} |"
        res = _append_table_row(
            updated_beats,
            new_row,
            dedupe_key=beat_snip,
            default_headers=("| Date / episode | Beat | Source |", "|---|---|---|"),
        )
        if res != updated_beats:
            updated_beats = res
            modified = True

    if modified:
        body = f"{before_beats}\n{updated_beats}\n{after_beats}"
        if not dry_run:
            file_path.write_text(f"{fm}{body.strip()}\n", encoding="utf-8")

    return modified


def update_segment_file(
    file_path: Path,
    ep_slug: str,
    occurrences: list[tuple[str, str, str]],  # [(start, title, notes), ...]
    *,
    dry_run: bool = False,
) -> bool:
    """Updates Known occurrences in a segment markdown file."""
    content = file_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter_and_body(content)
    before_occ, occ_text, after_occ = _extract_section(body, "## Known occurrences")
    if not occ_text:
        return False

    updated_occ = occ_text
    modified = False
    for start, title, notes in occurrences:
        dedupe_key = f"{ep_slug}"
        safe_desc = f"{title}: {notes}".replace("|", "/") if notes else title.replace("|", "/")
        new_row = f"| [[episodes/{ep_slug}|{ep_slug}]] | {start} | {safe_desc} |"
        res = _append_table_row(
            updated_occ,
            new_row,
            dedupe_key=dedupe_key,
            default_headers=("| Episode | Timestamp | Notes |", "|---|---|---|"),
        )
        if res != updated_occ:
            updated_occ = res
            modified = True

    if modified:
        body = f"{before_occ}\n{updated_occ}\n{after_occ}"
        if not dry_run:
            file_path.write_text(f"{fm}{body.strip()}\n", encoding="utf-8")

    return modified


def update_wiki_from_extraction(
    vod_id: str,
    *,
    dry_run: bool = False,
    auto_create_characters: bool = True,
) -> UpdateReport:
    """Propagates structured extraction data into Character, Segment, and Storyline wiki pages."""
    run_dir = RUNS_DIR / vod_id
    ext_path = run_dir / "extraction.json"
    if not ext_path.exists():
        raise SystemExit(
            f"Extraction file not found: {ext_path}\n"
            f"Run `./binlore extract {vod_id}` first to generate extraction.json."
        )

    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    extraction: dict[str, Any] = json.loads(ext_path.read_text(encoding="utf-8"))
    ep_slug = meta.get("date") or f"vod-{vod_id}"

    canon = load_wiki_canon()
    report = UpdateReport(vod_id=vod_id, episode_slug=ep_slug)

    # Group lore notes by entity
    lore_by_entity: dict[str, list[tuple[str, str]]] = {}
    for note in extraction.get("lore_notes", []):
        ent = str(note.get("entity", "")).strip()
        ts = str(note.get("timestamp", ""))
        fact = str(note.get("fact", "")).strip()
        if ent and fact:
            lore_by_entity.setdefault(ent.lower(), []).append((ts, fact))

    # 1. Update or create Character pages
    detected_chars = extraction.get("characters", [])
    for char_info in detected_chars:
        name = char_info.get("canonical_name") or char_info.get("name") or ""
        if not name:
            continue

        notes = char_info.get("notes", "")
        speaking = bool(char_info.get("speaking"))
        confidence = float(char_info.get("confidence", 0.0))

        # Collect lore facts for this character
        facts: list[tuple[str, str]] = []
        name_lower = name.lower()
        for ent_key, ent_facts in lore_by_entity.items():
            if name_lower in ent_key or ent_key in name_lower:
                facts.extend(ent_facts)

        char_file, slug = _match_character_file(name, canon)
        if char_file and char_file.exists():
            updated = update_character_file(char_file, ep_slug, notes, facts, dry_run=dry_run)
            if updated:
                report.characters_updated.append(char_file.stem)
        elif auto_create_characters and (speaking or confidence >= 0.85):
            if slug in ("case-blackwell", "case"):
                continue
            new_file = create_character_page(name, slug, ep_slug, notes, facts, dry_run=dry_run)
            report.characters_created.append(slug)
            if "characters/index.md" not in report.indexes_updated:
                report.indexes_updated.append("characters/index.md")

    # 2. Update Storyline pages
    storyline_beats_by_file: dict[Path, list[tuple[str, str]]] = {}
    for st in extraction.get("storylines", []):
        st_name = st.get("storyline", "")
        beat = st.get("beat", "")
        ts = st.get("timestamp", "")
        if not st_name or not beat:
            continue
        story_file = _match_storyline_file(st_name, canon)
        if story_file and story_file.exists():
            storyline_beats_by_file.setdefault(story_file, []).append((ts, beat))

    for story_file, beats in storyline_beats_by_file.items():
        updated = update_storyline_file(story_file, ep_slug, beats, dry_run=dry_run)
        if updated:
            report.storylines_updated.append(story_file.stem)

    # 3. Update Segment pages
    segment_occ_by_file: dict[Path, list[tuple[str, str, str]]] = {}
    for seg in extraction.get("segments", []):
        seg_title = seg.get("title", "")
        start = seg.get("start", "")
        notes = seg.get("notes", "")
        if not seg_title:
            continue
        seg_file = _match_segment_file(seg_title, canon)
        if seg_file and seg_file.exists():
            segment_occ_by_file.setdefault(seg_file, []).append((start, seg_title, notes))

    for seg_file, occurrences in segment_occ_by_file.items():
        updated = update_segment_file(seg_file, ep_slug, occurrences, dry_run=dry_run)
        if updated:
            report.segments_updated.append(seg_file.stem)

    # 4. Ensure Episode is linked in episodes/index.md
    ep_index = CONTENT_EPISODES / "index.md"
    if ep_index.exists():
        idx_txt = ep_index.read_text(encoding="utf-8")
        ep_entry = f"[[{ep_slug}]]"
        if ep_entry not in idx_txt:
            vod_title = meta.get("title") or "Barely Informed News"
            vod_url = meta.get("url") or f"https://www.twitch.tv/videos/{vod_id}"
            new_row = f"| [[{ep_slug}]] | {ep_slug} | [{vod_title}]({vod_url}) |"
            fm_ep, body_ep = _split_frontmatter_and_body(idx_txt)
            updated_body = _append_table_row(
                body_ep,
                new_row,
                dedupe_key=ep_slug,
                default_headers=("| Episode | Date | Highlights |", "|---|---|---|"),
            )
            if updated_body != body_ep and not dry_run:
                ep_index.write_text(f"{fm_ep}{updated_body.strip()}\n", encoding="utf-8")
                if "episodes/index.md" not in report.indexes_updated:
                    report.indexes_updated.append("episodes/index.md")

    return report
