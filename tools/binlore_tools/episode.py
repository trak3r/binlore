from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import CONTENT_CHARACTERS, CONTENT_EPISODES, CONTENT_STORYLINES, RUNS_DIR
from .vods import Vod, format_duration


def episode_stub_markdown(vod: Vod, *, run_id: str) -> str:
    date = vod.date_str or "unknown-date"
    title = f"Episode {date}"
    duration = format_duration(vod.duration)
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

- **VOD:** [{vod.title}]({vod.url})
- **Approx length:** {duration}
- **Ingest run:** `tools/runs/{run_id}/`

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

Full timestamped transcript (local, not published by Quartz):

`tools/runs/{run_id}/transcript.txt`
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
        return CONTENT_EPISODES / f"{date}.md"
    return CONTENT_EPISODES / f"vod-{vod_id}.md"


def _slugify(text: str) -> str:
    s = text.lower().replace("&", "and").replace("–", "-").replace("—", "-")
    s = "".join(c if c.isalnum() or c in " -" else "" for c in s)
    return "-".join(s.split())


def _format_character_link(name: str) -> str:
    slug = _slugify(name)
    # Check if a character page exists
    target = CONTENT_CHARACTERS / f"{slug}.md"
    if target.exists():
        return f"[[characters/{slug}|{name}]]"
    # Check common aliases
    if slug in ("crumb", "crum"):
        return "[[characters/crum|Crum]]"
    if "munch" in slug or "munchcut" in slug or "ralph" in slug:
        return "[[characters/munch|Munch (Ralph Munchcut)]]"
    if "blackwell" in slug or slug == "case":
        return "[[characters/case-blackwell|Case Blackwell]]"
    if "chet-ai" in slug or "chetai" in slug or slug == "chetah":
        return "[[characters/chet-ai|ChetAI]]"
    if "chet" in slug or "manscape" in slug or "science" in slug or "skynce" in slug:
        return "[[characters/chet|Chet (Chet Manscape)]]"
    if "cryptozeus" in slug:
        return "[[characters/cryptozeus|Cryptozeus]]"
    if "ripple" in slug or "hooper" in slug:
        return "[[characters/jeff-ripple|Jeff Ripple]]"
    if "pepito" in slug:
        return "[[characters/pepito|Pepito]]"
    if "hype" in slug or "hyper" in slug:
        return "[[characters/hype-train|Hype Train]]"
    return name


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
    if "cryptozeus" in slug or "gaming" in slug:
        return f"[[segments/cryptozeus|{name}]]"
    if "chet" in slug or "science" in slug or "skynce" in slug:
        return f"[[segments/chet-guy-the-science-eyes|{name}]]"
    if "amongst" in slug or "web" in slug:
        return f"[[segments/amongst-the-web|{name}]]"
    return name


def _format_storyline_link(name: str) -> str:
    slug = _slugify(name)
    target = CONTENT_STORYLINES / f"{slug}.md"
    if target.exists():
        return f"[[storylines/{slug}|{name}]]"
    if "rivalry" in slug or ("munch" in slug and "crum" in slug):
        return "[[storylines/munch-crum-rivalry|Munch–Crum rivalry]]"
    return name


def update_episode_from_extraction(vod_id: str, extraction: dict[str, Any]) -> Path:
    """Update or generate episode markdown file with extracted lore and segment rundown."""
    run_dir = RUNS_DIR / vod_id
    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    date = meta.get("date") or "unknown-date"
    title = f"Episode {date}"
    vod_title = meta.get("title") or "Barely Informed News"
    vod_url = meta.get("url") or f"https://www.twitch.tv/videos/{vod_id}"
    duration = meta.get("duration") or "?"
    summary = extraction.get("episode_summary", "").strip()

    # Build Segment Rundown Table
    segments = extraction.get("segments", [])
    seg_rows: list[str] = []
    if segments:
        for s in segments:
            start = s.get("start", "")
            end = s.get("end", "")
            canon_seg = s.get("canonical_segment") or ""
            title = s.get("title", "")
            if canon_seg:
                seg_label = f"{_format_segment_link(canon_seg)}: {title}"
            else:
                seg_label = _format_segment_link(title)
            notes = s.get("notes", "").replace("|", "/")
            seg_rows.append(f"| {start} | {end} | {seg_label} | {notes} |")
    else:
        seg_rows.append("| | | | _No distinct segments identified_ |")
    seg_table = "\n".join(seg_rows)

    # Build Characters List
    characters = extraction.get("characters", [])
    char_bullets: list[str] = []
    if characters:
        for c in characters:
            c_name = c.get("canonical_name") or c.get("name") or "Unknown"
            c_link = _format_character_link(c_name)
            speaking_str = "speaking" if c.get("speaking") else "mentioned"
            ts_list = c.get("timestamps") or []
            ts_str = f" @ {', '.join(ts_list)}" if ts_list else ""
            notes = f" — {c['notes']}" if c.get("notes") else ""
            char_bullets.append(f"- {c_link} ({speaking_str}{ts_str}){notes}")
    else:
        char_bullets.append("- _None detected_")
    chars_text = "\n".join(char_bullets)

    # Build Storylines List
    storylines = extraction.get("storylines", [])
    story_bullets: list[str] = []
    if storylines:
        for st in storylines:
            st_name = st.get("storyline", "Storyline")
            st_link = _format_storyline_link(st_name)
            beat = st.get("beat", "")
            ts = f" [{st['timestamp']}]" if st.get("timestamp") else ""
            story_bullets.append(f"- **{st_link}**{ts}: {beat}")
    else:
        story_bullets.append("- _No specific storyline updates recorded_")
    story_text = "\n".join(story_bullets)

    # Build Lore Notes List
    lore_notes = extraction.get("lore_notes", [])
    lore_bullets: list[str] = []
    if lore_notes:
        for l in lore_notes:
            entity = l.get("entity", "")
            entity_link = _format_character_link(entity) if entity else ""
            prefix = f"**{entity_link}**: " if entity_link else ""
            ts = f"**[{l['timestamp']}]** " if l.get("timestamp") else ""
            fact = l.get("fact", "")
            lore_bullets.append(f"- {ts}{prefix}{fact}")
    else:
        lore_bullets.append("- _No lore notes recorded_")
    lore_text = "\n".join(lore_bullets)

    overview_section = f"\n## Overview\n\n{summary}\n" if summary else ""

    md_content = f"""---
title: "{title}"
type: episode
date: {date if date != 'unknown-date' else ''}
vod_url: {vod_url}
vod_id: "{vod_id}"
run_id: "{vod_id}"
tags:
  - episode
---

# {title}

- **VOD:** [{vod_title}]({vod_url})
- **Approx length:** {duration}
- **Ingest run:** `tools/runs/{vod_id}/`
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

Full timestamped transcript (local, not published by Quartz):

`tools/runs/{vod_id}/transcript.txt`
"""

    ep_file = _find_episode_file(vod_id, date)
    ep_file.parent.mkdir(parents=True, exist_ok=True)
    ep_file.write_text(md_content, encoding="utf-8")
    return ep_file
