from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .paths import CONTENT_CHARACTERS, CONTENT_EPISODES, CONTENT_SEGMENTS, CONTENT_STORYLINES, RUNS_DIR
from .vods import Vod, format_duration
from .wiki_updater import (
    first_embedded_timestamp,
    normalize_timestamp,
    strip_redundant_trailing_timestamps,
)


def episode_stub_markdown(vod: Vod, *, run_id: str) -> str:
    date = vod.date_str or "unknown-date"
    title = f"Episode {date}"
    duration = format_duration(vod.duration)
    date_val = vod.date_str or ""
    is_twitch = "twitch.tv" in vod.url
    vod_lines = []
    if date_val:
        vod_lines.append(f"- **Broadcast Date:** {date_val}")
    if is_twitch:
        vod_lines.append(f"- **Twitch VOD:** [{vod.title}]({vod.url}) (ID: `{vod.id}`)")
    else:
        vod_lines.append(f"- **VOD Archive:** [{vod.title}]({vod.url}) (ID: `{vod.id}`)")
    vod_lines.append(f"- **Approx length:** {duration}")
    vod_lines.append(
        f"- **Ingest run:** [`tools/runs/{run_id}/`](https://github.com/trak3r/binlore/tree/main/tools/runs/{run_id}/)"
    )
    header_block = "\n".join(vod_lines)

    return f"""---
title: "{title}"
type: episode
date: {date if vod.date_str else ""}
vod_url: {vod.url}
vod_id: "{vod.id}"
run_id: "{run_id}"
tags:
  - episode
---

# {title}

{header_block}

## Segment rundown

| Start | End | Segment | Notes |
|-------|-----|---------|-------|
| | | | _Fill after Phase 2 extraction or by hand_ |

## Characters

- _TBD_

## Storyline updates

- _TBD_

## Lore notes

Facts worth promoting to character/storyline pages (with timestamps):

- _TBD_

## Transcript

Full timestamped transcript:

[`tools/runs/{run_id}/transcript.txt`](https://github.com/trak3r/binlore/blob/main/tools/runs/{run_id}/transcript.txt)
"""


def write_episode_stub(vod: Vod, *, run_id: str, force: bool = False) -> Path:
    CONTENT_EPISODES.mkdir(parents=True, exist_ok=True)
    date = vod.date_str or f"vod-{vod.id}"
    path = CONTENT_EPISODES / f"{date}.md"
    if path.exists() and not force:
        existing = path.read_text(encoding="utf-8")
        if f'vod_id: "{vod.id}"' in existing or f"vod_id: {vod.id}" in existing:
            return path
        path = CONTENT_EPISODES / f"{date}-{vod.id}.md"

    path.write_text(episode_stub_markdown(vod, run_id=run_id), encoding="utf-8")
    return path


def _find_episode_file(vod_id: str, date: str | None = None) -> Path:
    """Find existing episode file for vod_id or target date."""
    for p in CONTENT_EPISODES.glob("*.md"):
        if p.name == "index.md":
            continue
        try:
            txt = p.read_text(encoding="utf-8")
            if f'vod_id: "{vod_id}"' in txt or f"vod_id: {vod_id}" in txt:
                return p
        except Exception:
            continue

    if date:
        bare = CONTENT_EPISODES / f"{date}.md"
        return CONTENT_EPISODES / f"{date}-{vod_id}.md" if bare.exists() else bare
    return CONTENT_EPISODES / f"vod-{vod_id}.md"


def _slugify(text: str) -> str:
    s = text.lower().replace("&", "and").replace("–", "-").replace("—", "-")
    s = "".join(c if c.isalnum() or c in " -" else "" for c in s)
    return "-".join(s.split())


# (substrings of the slugified name, character page slug); first match wins.
_CHARACTER_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("scrum",), "scrum"),
    (("crum", "crumb"), "crum"),
    (("munch", "munchcut", "ralph"), "munch"),
    (("blackwell",), "case-blackwell"),
    (("chet-ai", "chetai"), "chet-ai"),
    (("chet", "manscape", "science", "skynce"), "chet"),
    (("cryptozeu", "brandon"), "cryptozeus"),
    (("chath", "cheth"), "dr-chath"),
    (("ripple", "hooper"), "jeff-ripple"),
    (("pepito",), "pepito"),
    (("hype", "hyper"), "hype-train"),
    (("cremus", "tremando"), "cremus-tremando"),
    (("peter", "gibbon"), "peter-gibbon"),
    (("rick",), "rick"),
    (("trip", "bradstein"), "trip-bradstein"),
    (("rooney",), "ai-rooney"),
    (("kendall", "kendelle"), "kendelle"),
    (("jebs-dad", "jeb-s-dad"), "jebs-dad"),
    (("jeb", "nogget", "noggin"), "jeb"),
    (("granman", "grandman", "grand-man"), "granman"),
    (("durf", "derf", "dwarf"), "durf"),
    (("sleazy",), "live-in-sleazy"),
]


def resolve_character_slug(name: str) -> str | None:
    slug = _slugify(name)
    if (CONTENT_CHARACTERS / f"{slug}.md").exists():
        return slug
    if slug in ("case", "chetah"):
        return {"case": "case-blackwell", "chetah": "chet-ai"}[slug]
    if "jazz" in slug and "shrimp" in slug:
        return "jazz-shrimp"
    for needles, target in _CHARACTER_ALIASES:
        if any(n in slug for n in needles):
            return target
    return None


_common_name_cache: dict[str, str | None] = {}


def character_common_name(slug: str) -> str | None:
    """The name the character is called on the show: frontmatter ``common_name``,
    else the page title minus any parenthetical (``Munch (Ralph Munchcut)`` -> ``Munch``)."""
    if slug in _common_name_cache:
        return _common_name_cache[slug]
    path = CONTENT_CHARACTERS / f"{slug}.md"
    name: str | None = None
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        if raw.startswith("---"):
            fm = yaml.safe_load(raw.split("---", 2)[1]) or {}
            name = str(fm.get("common_name") or fm.get("title") or "") or None
        if name:
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    _common_name_cache[slug] = name or None
    return _common_name_cache[slug]


def _format_character_link(name: str) -> str:
    slug = resolve_character_slug(name)
    if not slug:
        return name
    return f"[[characters/{slug}|{character_common_name(slug) or name}]]"


_CHARACTER_LINK_RE = re.compile(r"\[\[((?:\.\./)?characters/)([^|\]#\\]+)(\\?)\|([^\]]+)\]\]")


def normalize_character_links(text: str) -> str:
    """Relabel every character wikilink with the character's common name.

    Labels that name a different page are relinked (Scrum on Crum's page goes to
    Scrum's; "Munch & Crum" goes to the segment). Possessive labels keep the 's outside the link.
    """

    def fix(m: re.Match[str]) -> str:
        prefix, slug, esc, label = m.group(1), m.group(2).strip(), m.group(3), m.group(4).strip()
        if label == "Munch & Crum":
            return f"[[{prefix.replace('characters/', 'segments/')}munch-and-crum{esc}|Munch & Crum]]"
        suffix = ""
        if re.search(r"['’]s$", label):
            label, suffix = label[:-2], label[-2:]
        relinked = resolve_character_slug(label)
        if relinked == "scrum" and slug != "scrum":
            slug = "scrum"
        name = character_common_name(slug)
        if not name:
            return m.group(0)
        return f"[[{prefix}{slug}{esc}|{name}]]{suffix}"

    return _CHARACTER_LINK_RE.sub(fix, text)


def normalize_episode_character_links(dry_run: bool = False) -> list[Path]:
    changed: list[Path] = []
    for path in sorted(CONTENT_EPISODES.glob("*.md")):
        if path.name == "index.md":
            continue
        raw = path.read_text(encoding="utf-8")
        new = normalize_character_links(raw)
        if new != raw:
            changed.append(path)
            if not dry_run:
                path.write_text(new, encoding="utf-8")
    return changed


def _format_segment_link(name: str) -> str:
    slug = _slugify(name)
    target = CONTENT_SEGMENTS / f"{slug}.md"
    if target.exists():
        return f"[[segments/{slug}|{name}]]"
    if "debate" in slug or ("munch" in slug and "crum" in slug):
        return f"[[segments/munch-and-crum|{name}]]"
    if "hype" in slug or "hyper" in slug:
        return f"[[segments/hype-train|{name}]]"
    if "news" in slug:
        return f"[[segments/news|{name}]]"
    if "cryptozeus" in slug or "cryptozeu" in slug or "gaming" in slug or "cryptozeu$" in slug:
        return f"[[segments/cryptozeus|{name}]]"
    if "therapy" in slug or "chath" in slug or "cheth" in slug:
        return f"[[segments/therapy|{name}]]"
    if "chet" in slug or "science" in slug or "skynce" in slug:
        return f"[[segments/chet-guy-the-science-eyes|{name}]]"
    if "amongst" in slug or "web" in slug:
        return f"[[segments/amongst-the-web|{name}]]"
    if any(k in slug for k in ("trip", "street", "bradstein", "field-reporting", "man-on-the-street")):
        display_name = "Trip on the Street" if slug in ("field-reporting", "field") else name
        return f"[[segments/trip-on-the-street|{display_name}]]"
    if "rooney" in slug:
        return f"[[segments/ai-rooney|{name}]]"
    return name


def _format_storyline_link(name: str) -> str:
    slug = _slugify(name)
    target = CONTENT_STORYLINES / f"{slug}.md"
    if target.exists():
        return f"[[storylines/{slug}|{name}]]"
    if any(k in slug for k in ("gorilla", "groin", "punch", "dick")):
        return "[[storylines/crum-dick-punch|Crum Dick Punch]]"
    return name


def update_episode_from_extraction(vod_id: str, extraction: dict[str, Any]) -> Path:
    """Update or generate episode markdown file with extracted lore and segment rundown.

    If the existing episode page has frontmatter ``curated: true``, leave the markdown
    untouched (extraction.json may still be refreshed by the caller).
    """
    from .extract import validate_extraction

    extraction = validate_extraction(dict(extraction))
    run_dir = RUNS_DIR / vod_id
    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    date = meta.get("date") or "unknown-date"
    existing = _find_episode_file(vod_id, date)
    if existing.exists():
        try:
            raw = existing.read_text(encoding="utf-8")
            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    fm = yaml.safe_load(parts[1]) or {}
                    if fm.get("curated") is True or str(fm.get("curated", "")).lower() in (
                        "true",
                        "yes",
                        "1",
                    ):
                        return existing
        except Exception:
            pass

    vod_title = meta.get("title") or "Barely Informed News"
    if vod_title and vod_title != "Barely Informed News":
        title = f"{vod_title} ({date})"
    else:
        title = f"Episode {date}"
    # Double-quoted YAML so titles with embedded quotes/colons don't break Quartz.
    title_yaml = json.dumps(title, ensure_ascii=False)
    vod_url = meta.get("url") or f"https://www.twitch.tv/videos/{vod_id}"
    duration = meta.get("duration") or "?"
    summary = extraction.get("episode_summary", "").strip()

    # Build Segment Rundown Table
    segments = extraction.get("segments", [])
    seg_rows: list[str] = []
    if segments:
        for s in segments:
            start = normalize_timestamp(str(s.get("start", ""))) or str(s.get("start", ""))
            end = normalize_timestamp(str(s.get("end", ""))) or str(s.get("end", ""))
            canon_seg = s.get("canonical_segment") or ""
            title_seg = s.get("title", "")
            if canon_seg:
                seg_label = f"{_format_segment_link(canon_seg)}: {title_seg}"
            else:
                seg_label = _format_segment_link(title_seg)
            notes = s.get("notes", "").replace("|", "/")
            seg_rows.append(f"| {start} | {end} | {seg_label} | {notes} |")
    else:
        seg_rows.append("| | | | _No distinct segments identified_ |")
    seg_table = "\n".join(seg_rows)

    # Build Characters List & Metadata
    characters = extraction.get("characters", [])
    char_bullets: list[str] = []
    char_meta_entries: list[str] = []
    if characters:
        for c in characters:
            c_name = c.get("canonical_name") or c.get("name") or "Unknown"
            c_link = _format_character_link(c_name)
            speaking_str = "speaking" if c.get("speaking") else "mentioned"
            notes = f" — {c['notes']}" if c.get("notes") else ""
            char_bullets.append(f"- {c_link} ({speaking_str}){notes}")

            ts_list = c.get("timestamps") or []
            clean_name = c_name.replace('"', '\\"')
            if ts_list:
                ts_json = json.dumps(ts_list)
                char_meta_entries.append(
                    f'  - name: "{clean_name}"\n    role: {speaking_str}\n    timestamps: {ts_json}'
                )
            else:
                char_meta_entries.append(
                    f'  - name: "{clean_name}"\n    role: {speaking_str}'
                )
    else:
        char_bullets.append("- _None detected_")
    chars_text = "\n".join(char_bullets)
    char_meta_yaml = ""
    if char_meta_entries:
        char_meta_yaml = "characters_meta:\n" + "\n".join(char_meta_entries) + "\n"

    # Build Storylines List
    storylines = extraction.get("storylines", [])
    story_bullets: list[str] = []
    if storylines:
        for st in storylines:
            if not isinstance(st, dict):
                continue
            st_name = st.get("storyline") or st.get("name") or "Storyline"
            st_link = _format_storyline_link(str(st_name))
            beat = st.get("beat", "")
            canon_ts = normalize_timestamp(str(st.get("timestamp") or ""))
            ts = f" [{canon_ts}]" if canon_ts else ""
            story_bullets.append(f"- **{st_link}**{ts}: {beat}")
    else:
        story_bullets.append("- _No specific storyline updates recorded_")
    story_text = "\n".join(story_bullets)

    # Build Lore Notes List
    lore_notes = extraction.get("lore_notes", [])
    lore_bullets: list[str] = []
    if lore_notes:
        for l in lore_notes:
            if isinstance(l, str):
                lore_bullets.append(f"- {l}")
                continue
            if not isinstance(l, dict):
                continue
            entity = l.get("entity", "") or l.get("character", "")
            entity_link = _format_character_link(entity) if entity else ""
            prefix = f"**{entity_link}**: " if entity_link else ""
            fact = str(l.get("fact") or l.get("note") or l.get("text") or "").strip()
            if not fact:
                continue
            canon_ts = normalize_timestamp(str(l.get("timestamp") or "")) or first_embedded_timestamp(fact)
            fact = strip_redundant_trailing_timestamps(fact, canon_ts)
            ts = f"**[{canon_ts}]** " if canon_ts else ""
            lore_bullets.append(f"- {ts}{prefix}{fact}")
    else:
        lore_bullets.append("- _No lore notes recorded_")
    lore_text = "\n".join(lore_bullets)

    overview_section = f"\n## Overview\n\n{summary}\n" if summary else ""

    vod_header_lines = []
    if date and date != "unknown-date":
        vod_header_lines.append(f"- **Broadcast Date:** {date}")

    twitch_url = meta.get("twitch_url")
    twitch_id = meta.get("twitch_id")
    yt_url = meta.get("yt_url")
    yt_id = meta.get("yt_id")

    if twitch_url:
        vod_header_lines.append(f"- **Twitch VOD:** [{vod_title}]({twitch_url}) (ID: `{twitch_id or vod_id}`)")
    if yt_url:
        vod_header_lines.append(f"- **YouTube Archive:** [{vod_title}]({yt_url}) (ID: `{yt_id or vod_id}`)")
    elif not twitch_url:
        if "twitch.tv" in vod_url:
            vod_header_lines.append(f"- **Twitch VOD:** [{vod_title}]({vod_url}) (ID: `{vod_id}`)")
        else:
            vod_header_lines.append(f"- **VOD Archive:** [{vod_title}]({vod_url}) (ID: `{vod_id}`)")

    vod_header_lines.append(f"- **Approx length:** {duration}")
    vod_header_lines.append(
        f"- **Ingest run:** [`tools/runs/{vod_id}/`](https://github.com/trak3r/binlore/tree/main/tools/runs/{vod_id}/)"
    )
    vod_header_text = "\n".join(vod_header_lines)

    md_content = f"""---
title: {title_yaml}
type: episode
date: {date if date != 'unknown-date' else ''}
vod_url: {vod_url}
vod_id: "{vod_id}"
run_id: "{vod_id}"
tags:
  - episode
{char_meta_yaml}---

# {title}

{vod_header_text}
{overview_section}
## Segment rundown

| Start | End | Segment | Notes |
|-------|-----|---------|-------|
{seg_table}

## Characters

{chars_text}

## Storyline updates

{story_text}

## Lore notes

{lore_text}

## Transcript

Full timestamped transcript:

[`tools/runs/{vod_id}/transcript.txt`](https://github.com/trak3r/binlore/blob/main/tools/runs/{vod_id}/transcript.txt)
"""

    ep_file = _find_episode_file(vod_id, date)
    ep_file.parent.mkdir(parents=True, exist_ok=True)
    ep_file.write_text(md_content, encoding="utf-8")
    return ep_file
