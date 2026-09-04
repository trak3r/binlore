from __future__ import annotations

from pathlib import Path

from .paths import CONTENT_EPISODES
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
        # if same vod already stubbed, leave content; else write alongside
        existing = path.read_text(encoding="utf-8")
        if f'vod_id: "{vod.id}"' in existing or f"vod_id: {vod.id}" in existing:
            return path
        path = CONTENT_EPISODES / f"{date}-{vod.id}.md"

    path.write_text(episode_stub_markdown(vod, run_id=run_id), encoding="utf-8")
    return path
