from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canon import CanonEntity, is_excluded_external_subject, load_wiki_canon
from .paths import (
    CONTENT_CHARACTERS,
    CONTENT_EPISODES,
    CONTENT_SEGMENTS,
    CONTENT_STORYLINES,
    RUNS_DIR,
)

FIXTURE_CHARACTER_SLUGS = frozenset({"pepito", "case-blackwell"})
FIXTURE_SEGMENT_SLUGS = frozenset({"news", "pre-show", "preshow", "cold-open"})
UNKNOWN_CHARACTERS_LOG = RUNS_DIR / "unknown-characters.jsonl"
_EP_DATE_RE = re.compile(r"episodes/(\d{4}-\d{2}-\d{2})")
_USUAL_APPEARANCE_RE = re.compile(
    r"opens? (the )?(broadcast|show|episode)|cold[- ]open|"
    r"signature (intro|greeting|line|canine)|"
    r"executive producer\.?$|lead anchor|"
    r"top-of-hour|station sign-on|production countdown|"
    r"canine broadcast executive",
    re.I,
)


def _slugify(text: str) -> str:
    s = text.lower().replace("&", "and").replace("–", "-").replace("—", "-")
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
    unknown_queued: list[str] = field(default_factory=list)


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


def _episode_date_from_row(row: str) -> str:
    match = _EP_DATE_RE.search(row)
    if match:
        return match.group(1)
    return "9999-99-99"


def _sort_table_rows(section_text: str) -> str:
    """Keep header/separator; sort data rows by episode date ascending."""
    lines = section_text.splitlines()
    preamble: list[str] = []
    header: list[str] = []
    data_rows: list[str] = []
    trailing: list[str] = []
    saw_table = False
    in_data = False
    for line in lines:
        stripped = line.strip()
        is_row = stripped.startswith("|") and stripped.endswith("|")
        if is_row:
            saw_table = True
            inner = stripped.strip("|")
            is_sep = set(inner.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")) == set()
            if not in_data:
                header.append(line)
                if is_sep:
                    in_data = True
            else:
                data_rows.append(line)
        elif not saw_table:
            preamble.append(line)
        else:
            trailing.append(line)

    if not header or not data_rows:
        return section_text

    data_rows.sort(key=_episode_date_from_row)
    return "\n".join(preamble + header + data_rows + trailing)


def _is_iso_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


def _backdate_first_seen(frontmatter: str, ep_slug: str) -> tuple[str, bool]:
    if not _is_iso_date(ep_slug):
        return frontmatter, False
    match = re.search(r"^first_seen:\s*(.*)$", frontmatter, re.MULTILINE)
    if match:
        current = match.group(1).strip().strip("'\"")
        if _is_iso_date(current) and current <= ep_slug:
            return frontmatter, False
        start, end = match.start(1), match.end(1)
        return frontmatter[:start] + ep_slug + frontmatter[end:], True

    closing = re.search(r"\n---\s*\n?\s*$", frontmatter)
    if closing:
        return frontmatter[: closing.start()] + f"\nfirst_seen: {ep_slug}\n---\n\n", True
    return frontmatter.rstrip() + f"\nfirst_seen: {ep_slug}\n", True


def _is_usual_fixture_appearance(slug: str, notes: str, lore_facts: list[tuple[str, str]]) -> bool:
    if slug not in FIXTURE_CHARACTER_SLUGS:
        return False
    if lore_facts:
        return False
    notes = (notes or "").strip()
    if not notes:
        return True
    if len(notes) > 180:
        return False
    return bool(_USUAL_APPEARANCE_RE.search(notes))


def queue_unknown_character(
    *,
    vod_id: str,
    episode_slug: str,
    name: str,
    slug: str,
    notes: str,
    confidence: float,
    speaking: bool,
) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "vod_id": vod_id,
        "episode": episode_slug,
        "name": name,
        "slug": slug,
        "notes": notes,
        "confidence": confidence,
        "speaking": speaking,
    }
    with UNKNOWN_CHARACTERS_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _match_character_file(name: str, canon: dict[str, list[CanonEntity]]) -> tuple[Path | None, str]:
    name_clean = name.strip()
    slug = _slugify(name_clean)

    # Check direct file match
    target = CONTENT_CHARACTERS / f"{slug}.md"
    if target.exists():
        return target, target.stem

    # Check known aliases
    for char in canon.get("characters", []):
        if char.name.lower() == name_clean.lower() or slug == _slugify(char.name):
            return char.file_path, (char.file_path.stem if char.file_path else slug)
        for alias in char.aliases:
            if alias.lower() == name_clean.lower() or slug == _slugify(alias):
                return char.file_path, (char.file_path.stem if char.file_path else slug)

    # Heuristic shortcuts for canonical aliases / role titles
    role_to_slug = {
        "lead-anchor-and-managing-editor": "case-blackwell",
        "lead-anchor": "case-blackwell",
        "managing-editor": "case-blackwell",
        "executive-producer": "pepito",
        "musical-and-cultural-correspondent": "hype-train",
        "cultural-and-musical-correspondent": "hype-train",
        "host-of-how-to-with-jeb": "jeb",
        "gaming-and-digital-culture-correspondent": "cryptozeus",
        "gaming-and-culture-correspondent": "cryptozeus",
    }
    if slug in role_to_slug:
        canon_slug = role_to_slug[slug]
        return CONTENT_CHARACTERS / f"{canon_slug}.md", canon_slug

    if "crum" in slug or "crumb" in slug:
        return CONTENT_CHARACTERS / "crum.md", "crum"
    if "munch" in slug or "munchcut" in slug or "ralph" in slug:
        return CONTENT_CHARACTERS / "munch.md", "munch"
    if "chet-ai" in slug or "chetai" in slug or "chetah" in slug:
        return CONTENT_CHARACTERS / "chet-ai.md", "chet-ai"
    if "chet" in slug or "manscape" in slug:
        return CONTENT_CHARACTERS / "chet.md", "chet"
    if "hype" in slug or "hyper" in slug:
        return CONTENT_CHARACTERS / "hype-train.md", "hype-train"
    if "cryptozeus" in slug or "cryptozeu" in slug or "brandon" in slug:
        return CONTENT_CHARACTERS / "cryptozeus.md", "cryptozeus"
    if "ripple" in slug or "hooper" in slug:
        return CONTENT_CHARACTERS / "jeff-ripple.md", "jeff-ripple"
    if "rick" in slug:
        return CONTENT_CHARACTERS / "rick.md", "rick"
    if "peter" in slug or "gibbon" in slug:
        return CONTENT_CHARACTERS / "peter-gibbon.md", "peter-gibbon"
    if "cremus" in slug or "tremando" in slug:
        return CONTENT_CHARACTERS / "cremus-tremando.md", "cremus-tremando"
    if "trip" in slug or "bradstein" in slug:
        return CONTENT_CHARACTERS / "trip-bradstein.md", "trip-bradstein"
    if "rooney" in slug:
        return CONTENT_CHARACTERS / "ai-rooney.md", "ai-rooney"
    if "chath" in slug or "cheth" in slug:
        return CONTENT_CHARACTERS / "dr-chath.md", "dr-chath"
    if "granman" in slug or "grandman" in slug or "grand-man" in slug:
        return CONTENT_CHARACTERS / "granman.md", "granman"
    if "jazz" in slug and "shrimp" in slug:
        return CONTENT_CHARACTERS / "jazz-shrimp.md", "jazz-shrimp"
    if "pepito" in slug:
        return CONTENT_CHARACTERS / "pepito.md", "pepito"
    if "jeb" in slug and "dad" not in slug:
        return CONTENT_CHARACTERS / "jeb.md", "jeb"
    if "case" in slug or "blackwell" in slug:
        return CONTENT_CHARACTERS / "case-blackwell.md", "case-blackwell"

    return None, slug


def _match_segment_file(title: str, canon: dict[str, list[CanonEntity]], canonical_segment: str = "") -> Path | None:
    title_lower = f"{canonical_segment} {title}".lower()
    # 1. Exact or substring match on segment name or aliases
    for seg in canon.get("segments", []):
        seg_lower = seg.name.lower()
        if seg_lower in title_lower or title_lower in seg_lower:
            return seg.file_path
        for alias in seg.aliases:
            if alias.lower() in title_lower or title_lower in alias.lower():
                return seg.file_path

    # 2. Targeted keyword heuristics
    for seg in canon.get("segments", []):
        seg_lower = seg.name.lower()
        if ("munch" in title_lower or "crum" in title_lower or "debate" in title_lower) and "munch" in seg_lower:
            return seg.file_path
        if "hype" in title_lower and "hype" in seg_lower:
            return seg.file_path
        if any(k in title_lower for k in ("cryptozeus", "cryptozeu$", "cryptozeu", "gameplay", "jill", "gaming")) and ("cryptozeus" in seg_lower or "cryptozeu$" in seg_lower or "cryptozeu" in seg_lower):
            return seg.file_path
        if any(k in title_lower for k in ("science", "chet", "skynce", "microscope", "cult")) and "chet" in seg_lower:
            return seg.file_path
        if any(k in title_lower for k in ("news", "breaking", "pentagon", "epstein", "gpt")) and seg_lower == "news":
            return seg.file_path
        if any(k in title_lower for k in ("amongst", "memes", "web")) and "amongst" in seg_lower:
            return seg.file_path
        if any(k in title_lower for k in ("trip on the street", "trip on the streets", "on the street", "on-street", "bradstein", "field reporting", "man on the street")) and "trip" in seg_lower:
            return seg.file_path
        if any(k in title_lower for k in ("ai rooney", "rooney", "andy rooney")) and "rooney" in seg_lower:
            return seg.file_path
        if any(k in title_lower for k in ("therapy", "chath", "cheth", "counseling", "healing")) and "therapy" in seg_lower:
            return seg.file_path
    return None


def _match_storyline_file(title: str, canon: dict[str, list[CanonEntity]]) -> Path | None:
    title_lower = title.lower()
    for story in canon.get("storylines", []):
        story_lower = story.name.lower()
        if story_lower in title_lower or title_lower in story_lower:
            return story.file_path
        for alias in story.aliases:
            if alias.lower() in title_lower or title_lower in alias.lower():
                return story.file_path
    if any(k in title_lower for k in ("gorilla", "groin", "penis", "punch", "gambling", "dick")):
        target = CONTENT_STORYLINES / "crum-dick-punch.md"
        if target.exists():
            return target
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
    slug = file_path.stem

    new_fm, fm_changed = _backdate_first_seen(fm, ep_slug)
    if fm_changed:
        fm = new_fm
        modified = True

    skip_appearance = _is_usual_fixture_appearance(slug, char_notes, lore_facts)

    # 1. Update Appearances (if appearances section exists, or if not the host)
    if not skip_appearance and ("## Appearances" in body or slug != "case-blackwell"):
        before_app, app_text, after_app = _extract_section(body, "## Appearances")
        if not app_text and "## Appearances" not in body:
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
        updated_app = _sort_table_rows(updated_app)
        if updated_app != app_text:
            body = f"{before_app}\n{updated_app}\n{after_app}"
            modified = True

    # 2. Update Notable moments
    if lore_facts:
        before_mom, mom_text, after_mom = _extract_section(body, "## Notable moments")
        if not mom_text and "## Notable moments" not in body:
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
) -> Path | None:
    """Create a new character markdown file and add it to characters/index.md."""
    # Exclude stream raid recipients: external streamers Case raids at stream close
    lower_notes = char_notes.lower()
    lower_name = name.lower()
    if "raid" in lower_notes or "raid" in lower_name:
        return None

    # Exclude Ben Hooper: external real-world UPI reporter, not a character
    if "hooper" in lower_name or slug in ("ben-hooper", "hooper", "jeff-hooper"):
        return None

    # Exclude job-title / role stubs that map to existing characters
    role_slugs = {
        "lead-anchor-and-managing-editor",
        "lead-anchor",
        "managing-editor",
        "executive-producer",
        "musical-and-cultural-correspondent",
        "cultural-and-musical-correspondent",
        "host-of-how-to-with-jeb",
        "gaming-and-digital-culture-correspondent",
        "gaming-and-culture-correspondent",
    }
    if slug in role_slugs or any(
        k in lower_name
        for k in (
            "lead anchor",
            "managing editor",
            "executive producer",
            "musical & cultural",
            "musical and cultural",
            "host of 'how to",
            "host of how to",
            "gaming & digital",
            "gaming and digital",
        )
    ):
        return None

    # Exclude chatters / Twitch viewers / Discord members
    if any(k in lower_notes for k in ("chatter", "chat user", "viewer", "twitch chat", "in chat", "chat member")) or any(
        k in lower_name for k in ("card king", "card-king", "chatter")
    ):
        return None

    # Exclude video clip / movie clip / news clip subjects
    if any(k in lower_notes for k in ("actor in", "movie clip", "video clip", "news clip", "clip subject", "viral video", "being watched")):
        return None

    target_path = CONTENT_CHARACTERS / f"{slug}.md"

    appearances_row = f"| [[episodes/{ep_slug}|{ep_slug}]] | {char_notes.replace('|', '/').strip()} |"
    notable_bullets: list[str] = []
    for ts, fact in lore_facts:
        notable_bullets.append(f"- **[{ts}]** ([[episodes/{ep_slug}|{ep_slug}]]): {fact}")

    if not notable_bullets:
        notable_bullets.append(f"- First identified in [[episodes/{ep_slug}|Episode {ep_slug}]].")

    # Mandatory character picture embed per wiki conventions
    img_tag = f"![{name} on Barely Informed News](https://github.com/trak3r/binlore/releases/download/media-assets/{slug}.jpg)\n\n"

    # Check for real-life public figures / politicians: do not auto-create character pages for external public figures
    is_public_figure = any(
        k in lower_notes
        for k in (
            "senator", "president", "politician", "public figure", "secretary of",
            "vice president", "biohacker", "prime minister", "minister", "governor",
            "congressman", "representative", "celebrity", "actor"
        )
    ) or any(
        k in lower_name
        for k in (
            "trump", "vance", "mcconnell", "graham", "hegseth", "biden", "nixon",
            "johnson", "neill", "starmer", "bevin", "altman"
        )
    )

    if is_public_figure:
        # Do not auto-create character wiki pages for real-world politicians or news subjects
        return None

    cya_block = ""
    intro_lead = f"**{name}** is a persona and contributor featured on *Barely Informed News*."
    status_tag = "recurring"
    index_role = "recurring"

    content = f"""---
title: {name}
type: character
aliases: []
first_seen: {ep_slug}
status: {status_tag}
tags:
  - character
---

# {name}

{img_tag}{cya_block}{intro_lead}

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
            char_link = f"[[characters/{slug}|{name}]]"
            if char_link not in idx_content and f"[[characters/{slug}|" not in idx_content and f"[[{slug}|" not in idx_content:
                short_note = char_notes.split(".")[0].replace("|", "/") if char_notes else "Recurring persona"
                new_row = f"| {char_link} | {index_role} | {short_note} |"
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
        updated_beats = _sort_table_rows(updated_beats)
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
    if file_path.stem in FIXTURE_SEGMENT_SLUGS:
        return False

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
        updated_occ = _sort_table_rows(updated_occ)
        body = f"{before_occ}\n{updated_occ}\n{after_occ}"
        if not dry_run:
            file_path.write_text(f"{fm}{body.strip()}\n", encoding="utf-8")

    return modified


def update_wiki_from_extraction(
    vod_id: str,
    *,
    dry_run: bool = False,
    auto_create_characters: bool = False,
    update_storylines: bool = False,
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

    # 1. Update existing Character pages; queue unknowns instead of auto-creating
    detected_chars = extraction.get("characters", [])
    for char_info in detected_chars:
        name = char_info.get("canonical_name") or char_info.get("name") or ""
        if not name:
            continue

        notes = char_info.get("notes", "")
        speaking = bool(char_info.get("speaking"))
        confidence = float(char_info.get("confidence", 0.0))

        if is_excluded_external_subject(str(name), str(notes)):
            continue

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
        elif auto_create_characters and speaking and confidence >= 0.85:
            if slug in ("case-blackwell", "case"):
                continue
            new_file = create_character_page(name, slug, ep_slug, notes, facts, dry_run=dry_run)
            if new_file is not None:
                report.characters_created.append(slug)
                if "characters/index.md" not in report.indexes_updated:
                    report.indexes_updated.append("characters/index.md")
        else:
            if not dry_run:
                queue_unknown_character(
                    vod_id=vod_id,
                    episode_slug=ep_slug,
                    name=str(name),
                    slug=slug,
                    notes=str(notes),
                    confidence=confidence,
                    speaking=speaking,
                )
            report.unknown_queued.append(str(name))

    # 2. Update Storyline pages (opt-in; default deferred to a corpus pass)
    if update_storylines:
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

    # 3. Update Segment pages (fixture desks like News are skipped)
    segment_occ_by_file: dict[Path, list[tuple[str, str, str]]] = {}
    for seg in extraction.get("segments", []):
        seg_title = seg.get("title", "")
        start = seg.get("start", "")
        notes = seg.get("notes", "")
        if not seg_title:
            continue
        canon_seg = seg.get("canonical_segment", "")
        seg_file = _match_segment_file(seg_title, canon, canonical_segment=canon_seg)
        if seg_file and seg_file.exists():
            segment_occ_by_file.setdefault(seg_file, []).append((start, seg_title, notes))

    for seg_file, occurrences in segment_occ_by_file.items():
        updated = update_segment_file(seg_file, ep_slug, occurrences, dry_run=dry_run)
        if updated:
            report.segments_updated.append(seg_file.stem)

    # 4. Sync episodes/index.md catalog
    if not dry_run:
        try:
            from .catalog import generate_episodes_index
            generate_episodes_index()
            if "episodes/index.md" not in report.indexes_updated:
                report.indexes_updated.append("episodes/index.md")
        except Exception:
            pass

    return report


def _repair_page_tables(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter_and_body(content)
    modified = False

    dates = _EP_DATE_RE.findall(body)
    if dates and path.parent.name == "characters":
        earliest = min(dates)
        new_fm, fm_changed = _backdate_first_seen(fm, earliest)
        if fm_changed:
            fm = new_fm
            modified = True

    for heading in ("## Appearances", "## Known occurrences", "## Key beats"):
        if heading not in body:
            continue
        before, section, after = _extract_section(body, heading)
        if not section:
            continue
        sorted_section = _sort_table_rows(section)
        if sorted_section != section:
            body = f"{before}\n{sorted_section}\n{after}"
            modified = True

    if modified:
        path.write_text(f"{fm}{body.strip()}\n", encoding="utf-8")
    return modified


def repair_existing_wiki_pages() -> list[str]:
    """Date-sort appearance/occurrence/beat tables and backdate first_seen from earliest row."""
    changed: list[str] = []
    for directory in (CONTENT_CHARACTERS, CONTENT_SEGMENTS, CONTENT_STORYLINES):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "index.md":
                continue
            if _repair_page_tables(path):
                changed.append(str(path.relative_to(directory.parent.parent)))
    return changed

