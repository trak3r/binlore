from __future__ import annotations

import json
from pathlib import Path
from .paths import CONTENT_EPISODES, REPO_ROOT, TOOLS_ROOT

CATALOG_JSON = TOOLS_ROOT / "youtube_catalog.json"


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
            yt_id = s.get("yt_id") or s.get("id")
            twitch_id = s.get("twitch_id")
            s_date = s.get("date")
            if (yt_id and yt_id in text) or (twitch_id and str(twitch_id) in text) or (s_date and stem == s_date):
                ingested_map[yt_id] = stem

    total_streams = len(streams)
    total_seconds = sum(s.get("duration_seconds") or 0 for s in streams)
    total_hours = total_seconds // 3600
    ingested_count = len(ingested_map)
    backlog_count = total_streams - ingested_count
    initial_pages = max(1, (total_streams + 49) // 50)

    rows: list[str] = []
    for idx, s in enumerate(streams):
        yt_id = s.get("yt_id") or s["id"]
        twitch_id = s.get("twitch_id")
        twitch_url = s.get("twitch_url")
        yt_url = s.get("yt_url") or f"https://www.youtube.com/watch?v={yt_id}"
        title = s["title"].replace("|", "/")
        date_str = s.get("date") or "—"
        dur = s.get("duration_str") or "—"

        vod_id_display = str(twitch_id) if twitch_id else yt_id
        vod_id_source = "Twitch" if twitch_id else "YouTube"

        if yt_id in ingested_map:
            ep_slug = ingested_map[yt_id]
            title_cell = f"**[[{ep_slug}|{title}]]**"
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
        watch_links.append(f'<a href="{yt_url}" class="watch-link yt-link" target="_blank" rel="noopener noreferrer">YouTube ↗</a>')
        watch_cell = " ".join(watch_links)

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
> - **Twitch vs. YouTube:** Twitch automatically expires and purges past broadcasts after ~60 days. The complete historical backlog of 370+ streams since November 2023 is permanently preserved on the [Case Blackwell YouTube Archive](https://www.youtube.com/@CaseBlackwell/streams). Older streams without active Twitch VODs can be referenced or ingested using their YouTube video ID (e.g. `ZSjvjEED3KA`).

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
.cell-date code {{
  font-size: 0.82rem;
  background: transparent;
  padding: 0;
  color: var(--dark);
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
