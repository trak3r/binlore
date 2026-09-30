from __future__ import annotations

import json
from typing import Any

from .paths import CATALOG_JSON, CONTENT_EPISODES
from .vods import format_duration, list_vods, resolve_vod


def _format_duration_short(seconds: float | None, fallback: str = "—") -> str:
    """Human-friendly duration for the episodes table, e.g. 2h 10m / 58m / 45s."""
    if seconds is None:
        return fallback
    total = int(round(float(seconds)))
    if total < 0:
        return fallback
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m" if m else f"{h}h"
    if m:
        return f"{m}m"
    return f"{sec}s"


def _normalize_twitch_id(raw: str | None) -> str:
    tid = str(raw or "").strip()
    if tid.startswith("v") and tid[1:].isdigit():
        return tid[1:]
    return tid


def refresh_catalog_from_twitch(*, limit: int = 40, dry_run: bool = False) -> dict[str, Any]:
    """
    Merge recent Twitch VODs into youtube_catalog.json (newest-first).

    Twitch-only rows are allowed until the YouTube archive catches up
    (yt_id / yt_url may be empty).
    """
    if not CATALOG_JSON.exists():
        raise FileNotFoundError(f"Missing {CATALOG_JSON}.")

    streams: list[dict[str, Any]] = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    by_twitch: dict[str, dict[str, Any]] = {}
    for s in streams:
        tid = _normalize_twitch_id(s.get("twitch_id"))
        if tid:
            by_twitch[tid] = s

    recent = list_vods(limit=limit)
    added: list[dict[str, Any]] = []
    updated = 0

    for flat in recent:
        tid = _normalize_twitch_id(flat.id)
        if not tid or not tid.isdigit():
            continue  # skip non-VOD / highlight noise without numeric ids

        title_guess = (flat.title or "").strip()
        if title_guess.lower().startswith("highlight:"):
            continue
        # Skip sub-20-minute Twitch-only clips unless already cataloged
        existing = by_twitch.get(tid)
        dur_guess = flat.duration
        if existing is None and dur_guess is not None and float(dur_guess) < 1200:
            continue

        # Flat playlist often lacks timestamps — resolve full metadata for unknowns
        # or when catalog is missing a date.
        need_meta = existing is None or not existing.get("date")
        meta = resolve_vod(flat.url, latest=False) if need_meta else flat

        date_str = meta.date_str or (existing or {}).get("date") or ""
        raw_date = date_str.replace("-", "") if date_str else ""
        dur_sec = meta.duration if meta.duration is not None else (existing or {}).get("duration_seconds")
        entry = {
            "id": tid if existing is None else (existing.get("id") or tid),
            "title": meta.title or (existing or {}).get("title") or "(untitled)",
            "date": date_str or None,
            "raw_date": raw_date or None,
            "duration_str": format_duration(dur_sec) if dur_sec is not None else (existing or {}).get("duration_str"),
            "duration_seconds": int(dur_sec) if dur_sec is not None else (existing or {}).get("duration_seconds"),
            "yt_id": (existing or {}).get("yt_id"),
            "yt_url": (existing or {}).get("yt_url"),
            "twitch_id": tid,
            "twitch_url": f"https://www.twitch.tv/videos/{tid}",
        }
        # Preserve YouTube ids when refreshing an existing row
        if existing:
            for key in ("id", "yt_id", "yt_url", "title"):
                if existing.get(key) and key in ("id", "yt_id", "yt_url"):
                    entry[key] = existing[key]
            if existing.get("title") and meta.title in (None, "", "(untitled)"):
                entry["title"] = existing["title"]
            # Only count as updated when something useful changed
            if any(existing.get(k) != entry.get(k) for k in ("date", "duration_seconds", "title", "twitch_url")):
                updated += 1
            by_twitch[tid] = {**existing, **{k: v for k, v in entry.items() if v is not None}}
        else:
            # Drop null yt fields for cleaner twitch-only rows
            clean = {k: v for k, v in entry.items() if v is not None}
            if "yt_id" not in clean:
                clean["id"] = tid
            by_twitch[tid] = clean
            added.append(clean)

    # Rebuild list: keep non-twitch-only historical rows, then merge by twitch id
    merged: list[dict[str, Any]] = []
    seen_twitch: set[str] = set()
    # Start with refreshed twitch-known entries + untouched catalog rows without twitch overlap
    for s in streams:
        tid = _normalize_twitch_id(s.get("twitch_id"))
        if tid and tid in by_twitch:
            if tid not in seen_twitch:
                merged.append(by_twitch[tid])
                seen_twitch.add(tid)
        else:
            merged.append(s)
    for tid, entry in by_twitch.items():
        if tid not in seen_twitch:
            merged.append(entry)
            seen_twitch.add(tid)

    def sort_key(s: dict[str, Any]) -> str:
        return str(s.get("date") or "0000-00-00")

    merged.sort(key=sort_key, reverse=True)

    if not dry_run:
        CATALOG_JSON.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        generate_episodes_index()

    return {
        "added": len(added),
        "updated": updated,
        "total": len(merged),
        "new_titles": [a.get("title") for a in added],
        "catalog_path": str(CATALOG_JSON),
    }


def generate_episodes_index() -> None:
    if not CATALOG_JSON.exists():
        raise FileNotFoundError(f"Missing {CATALOG_JSON}.")

    with open(CATALOG_JSON, encoding="utf-8") as f:
        streams = json.load(f)

    # Check for ingested episodes in content/episodes/*.md
    ingested_map: dict[str, str] = {}
    for ep_file in CONTENT_EPISODES.glob("*.md"):
        if ep_file.name == "index.md":
            continue
        text = ep_file.read_text(encoding="utf-8")
        if "draft: true" in text.lower():
            continue
        stem = ep_file.stem
        for s in streams:
            yt_id = s.get("yt_id")
            twitch_id = _normalize_twitch_id(s.get("twitch_id"))
            entry_id = str(s.get("id") or "")
            s_date = s.get("date")
            matched = (
                (yt_id and yt_id in text)
                or (twitch_id and twitch_id in text)
                or (entry_id and entry_id in text)
                or (s_date and stem == s_date)
            )
            if matched:
                for key in (yt_id, twitch_id, entry_id):
                    if key:
                        ingested_map[str(key)] = stem

    total_streams = len(streams)
    total_seconds = sum(s.get("duration_seconds") or 0 for s in streams)
    total_hours = total_seconds // 3600
    # Unique episode pages (not duplicate keys in ingested_map)
    ingested_count = len(set(ingested_map.values()))
    backlog_count = total_streams - ingested_count
    initial_pages = max(1, (total_streams + 49) // 50)

    rows: list[str] = []
    for idx, s in enumerate(streams):
        yt_id = s.get("yt_id")
        twitch_id = _normalize_twitch_id(s.get("twitch_id"))
        entry_id = str(s.get("id") or yt_id or twitch_id or "")
        twitch_url = s.get("twitch_url") or (f"https://www.twitch.tv/videos/{twitch_id}" if twitch_id else None)
        yt_url = s.get("yt_url") or (f"https://www.youtube.com/watch?v={yt_id}" if yt_id else None)
        title = s["title"].replace("|", "/")
        date_str = s.get("date") or "—"
        dur = _format_duration_short(s.get("duration_seconds"), fallback=s.get("duration_str") or "—")

        vod_id_display = twitch_id or yt_id or entry_id

        lookup_keys = [k for k in (yt_id, twitch_id, entry_id) if k]
        ep_slug = next((ingested_map[k] for k in lookup_keys if k in ingested_map), None)
        if ep_slug:
            title_cell = f'<a href="./{ep_slug}" class="internal"><strong>{title}</strong></a>'
            status_cell = '<span class="badge badge-ingested">✓ Ingested</span>'
            status_raw = "ingested"
        else:
            title_cell = title
            status_cell = '<span class="badge badge-backlog">⏳ Backlog</span>'
            status_raw = "backlog"

        # Watch links
        watch_links = []
        if twitch_url:
            watch_links.append(f'<a href="{twitch_url}" class="watch-link twitch-link" target="_blank" rel="noopener noreferrer">Twitch ↗</a>')
        if yt_url:
            watch_links.append(f'<a href="{yt_url}" class="watch-link yt-link" target="_blank" rel="noopener noreferrer">YouTube ↗</a>')
        watch_cell = " ".join(watch_links) if watch_links else "—"

        # VOD ID badge
        if twitch_id:
            vod_cell = f'<code class="vod-pill twitch-id" title="Twitch VOD ID (use with ./binlore)">{twitch_id}</code>'
        else:
            vod_cell = f'<code class="vod-pill yt-id" title="YouTube Archive ID (use with ./binlore)">{yt_id}</code>'

        display_style = ' style="display: none;"' if idx >= 50 else ''
        row = (
            f'<tr data-status="{status_raw}" data-title="{title.lower()}" data-date="{date_str}" data-vod-id="{vod_id_display.lower()}"{display_style}>'
            f'<td class="cell-date"><code>{date_str}</code></td>'
            f'<td class="cell-title">{title_cell}</td>'
            f'<td class="cell-vod">{vod_cell}</td>'
            f'<td class="cell-dur">{dur}</td>'
            f'<td class="cell-status">{status_cell}</td>'
            f'<td class="cell-watch">{watch_cell}</td>'
            f"</tr>"
        )
        rows.append(row)

    table_rows_html = "\n".join(rows)

    md_content = f"""---
title: Episodes
description: Complete broadcast archive and episode backlog for Barely Informed News.
---

# Episodes & Broadcast Backlog

Complete stream archive tracked for *Barely Informed News*. Episodes are ingested from Twitch and YouTube streams to document network correspondents, broadcast segments, developing storylines, and lore.

> **💡 Understanding Stream Dates, VOD IDs & Archives:**
> - **Broadcast Dates:** Listed by air date (`YYYY-MM-DD`). Ingested episode wiki pages are slugified by broadcast date (e.g. `[[2026-09-04|Artificially General News]]`).
> - **VOD IDs:** Live streams air on [Twitch (`caseblackwell`)](https://www.twitch.tv/caseblackwell), where Twitch assigns a numeric video ID (e.g. `2863722826`). These numeric IDs are the identifiers used with `./binlore` CLI commands (e.g. `./binlore ingest 2863722826` or `./binlore extract 2863722826`).
> - **Twitch vs. YouTube:** Twitch automatically expires and purges past broadcasts after ~60 days. The complete historical backlog of 370+ streams since November 2023 is permanently preserved on the [Case Blackwell YouTube Archive](https://www.youtube.com/@CaseBlackwellStreams). Older streams without active Twitch VODs can be referenced or ingested using their YouTube video ID (e.g. `ZSjvjEED3KA`).

<div class="backlog-stats-grid">
  <div class="stat-card">
    <div class="stat-value">{total_streams}</div>
    <div class="stat-label">Total Streams in Archive</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">~{total_hours} hrs</div>
    <div class="stat-label">Total Broadcast Lore</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{ingested_count}</div>
    <div class="stat-label">Ingested & Extracted</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{backlog_count}</div>
    <div class="stat-label">Pending Ingestion Backlog</div>
  </div>
</div>

---

## Stream Archive

Search and filter the complete archive below. Detailed wiki pages exist for ingested episodes; backlog episodes can be ingested using `./binlore ingest <vod-id>`.

<div class="episodes-controls">
  <div class="search-box">
    <input type="text" id="episode-search" placeholder="Search by title, date (YYYY-MM-DD), or VOD ID..." />
  </div>
  <div class="filter-group">
    <select id="status-filter">
      <option value="all">All Statuses ({total_streams})</option>
      <option value="ingested">Ingested Only ({ingested_count})</option>
      <option value="backlog">Backlog Only ({backlog_count})</option>
    </select>
    <select id="page-size">
      <option value="25">25 per page</option>
      <option value="50" selected>50 per page</option>
      <option value="100">100 per page</option>
      <option value="all">Show All</option>
    </select>
  </div>
</div>

<div class="table-wrapper">
<table id="episodes-table" class="episodes-table">
  <thead>
    <tr>
      <th style="width: 7rem;">Date</th>
      <th>Stream Title</th>
      <th style="width: 8.5rem;">VOD ID</th>
      <th style="width: 5.5rem;">Length</th>
      <th style="width: 6.5rem;">Status</th>
      <th style="width: 9.5rem;">Watch</th>
    </tr>
  </thead>
  <tbody>
{table_rows_html}
  </tbody>
</table>
</div>

<div class="pagination-controls" id="pagination-controls">
  <button id="btn-prev" class="page-btn" disabled>← Previous</button>
  <span id="page-info" class="page-info">Page 1 of {initial_pages} ({total_streams} streams)</span>
  <button id="btn-next" class="page-btn">Next →</button>
</div>

<style>
.backlog-stats-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
}}
.stat-card {{
  padding: 1rem;
  background: var(--lightgray);
  border-radius: 8px;
  border-left: 4px solid var(--secondary);
  text-align: center;
}}
.stat-value {{
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--secondary);
}}
.stat-label {{
  font-size: 0.75rem;
  color: var(--gray);
  margin-top: 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
.episodes-controls {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 1.5rem 0 1rem;
  align-items: center;
}}
.search-box {{
  flex: 1;
  min-width: 240px;
}}
.search-box input {{
  width: 100%;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--gray);
  background: var(--light);
  color: var(--dark);
  font-size: 0.9rem;
}}
.filter-group select {{
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--gray);
  background: var(--light);
  color: var(--dark);
  font-size: 0.9rem;
}}
.episodes-table {{
  width: 100%;
  border-collapse: collapse;
}}
.cell-date,
.cell-dur {{
  white-space: nowrap;
}}
.cell-date code {{
  font-size: 0.82rem;
  background: transparent;
  padding: 0;
  color: var(--dark);
  white-space: nowrap;
}}
.cell-dur {{
  font-variant-numeric: tabular-nums;
}}
.cell-vod {{
  white-space: nowrap;
}}
.vod-pill {{
  font-family: var(--codeFont);
  font-size: 0.78rem;
  padding: 0.15rem 0.4rem;
  background: var(--lightgray);
  border-radius: 4px;
  user-select: all;
}}
.vod-pill.twitch-id {{
  color: #9146ff;
  border-left: 3px solid #9146ff;
  font-weight: 600;
}}
.vod-pill.yt-id {{
  color: var(--gray);
}}
.badge {{
  display: inline-block;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}}
.badge-ingested {{
  background: rgba(34, 197, 94, 0.15);
  color: #16a34a;
  border: 1px solid rgba(34, 197, 94, 0.3);
}}
.badge-backlog {{
  background: rgba(148, 163, 184, 0.15);
  color: var(--gray);
  border: 1px solid var(--lightgray);
}}
.cell-watch {{
  white-space: nowrap;
}}
.watch-link {{
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  text-decoration: none;
  margin-right: 0.25rem;
  transition: all 0.15s ease;
  white-space: nowrap;
}}
.twitch-link {{
  background: rgba(145, 70, 255, 0.12);
  color: #9146ff !important;
  border: 1px solid rgba(145, 70, 255, 0.35);
}}
.twitch-link:hover {{
  background: #9146ff;
  color: #fff !important;
  text-decoration: none;
}}
.yt-link {{
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626 !important;
  border: 1px solid rgba(239, 68, 68, 0.3);
}}
.yt-link:hover {{
  background: #dc2626;
  color: #fff !important;
  text-decoration: none;
}}
.pagination-controls {{
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  margin: 1.5rem 0;
}}
.page-btn {{
  padding: 0.4rem 0.9rem;
  border-radius: 6px;
  border: 1px solid var(--gray);
  background: var(--lightgray);
  color: var(--dark);
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s ease;
}}
.page-btn:disabled {{
  opacity: 0.4;
  cursor: not-allowed;
}}
.page-btn:not(:disabled):hover {{
  background: var(--secondary);
  color: #fff;
  border-color: var(--secondary);
}}
.page-info {{
  font-size: 0.85rem;
  color: var(--gray);
}}
</style>
"""

    CONTENT_EPISODES.mkdir(parents=True, exist_ok=True)
    (CONTENT_EPISODES / "index.md").write_text(md_content, encoding="utf-8")
    print(f"✓ Generated content/episodes/index.md with {total_streams} streams")


if __name__ == "__main__":
    generate_episodes_index()
