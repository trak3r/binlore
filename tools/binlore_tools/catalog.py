from __future__ import annotations

import json
from pathlib import Path
from .paths import CONTENT_EPISODES, REPO_ROOT, TOOLS_ROOT

CATALOG_JSON = TOOLS_ROOT / "youtube_catalog.json"


def generate_episodes_index() -> None:
    if not CATALOG_JSON.exists():
        raise FileNotFoundError(f"Missing {CATALOG_JSON}. Run youtube sync first.")

    with open(CATALOG_JSON, encoding="utf-8") as f:
        streams = json.load(f)

    # Check for ingested episodes
    ingested_map: dict[str, str] = {}
    for ep_file in CONTENT_EPISODES.glob("*.md"):
        if ep_file.name == "index.md":
            continue
        text = ep_file.read_text(encoding="utf-8")
        stem = ep_file.stem
        # Map common titles
        if "High T Wednesday News" in text or "2863722826" in text or "ussukWsFgWI" in text:
            ingested_map["ussukWsFgWI"] = stem
        if "Artificially General News" in text or "2865460780" in text or "LqjPBi9lw_c" in text:
            ingested_map["LqjPBi9lw_c"] = stem

    total_streams = len(streams)
    total_seconds = sum(s.get("duration_seconds") or 0 for s in streams)
    total_hours = total_seconds // 3600
    ingested_count = len(ingested_map)
    backlog_count = total_streams - ingested_count

    rows: list[str] = []
    for s in streams:
        yt_id = s["id"]
        title = s["title"].replace("|", "/")
        dur = s.get("duration_str") or "—"
        idx = s.get("index", 0)
        yt_url = s["url"]

        if yt_id in ingested_map:
            ep_slug = ingested_map[yt_id]
            title_cell = f"**[[{ep_slug}|{title}]]**"
            status_cell = '<span class="badge badge-ingested">✓ Ingested</span>'
            status_raw = "ingested"
        else:
            title_cell = title
            status_cell = '<span class="badge badge-backlog">⏳ Backlog</span>'
            status_raw = "backlog"

        row = (
            f'<tr data-status="{status_raw}" data-title="{title.lower()}">'
            f"<td>#{idx}</td>"
            f"<td>{title_cell}</td>"
            f"<td>{dur}</td>"
            f"<td>{status_cell}</td>"
            f'<td><a href="{yt_url}" target="_blank" rel="noopener noreferrer">YouTube ↗</a></td>'
            f"</tr>"
        )
        rows.append(row)

    table_rows_html = "\n".join(rows)

    md_content = f"""---
title: Episodes
description: Complete broadcast archive and episode backlog for Barely Informed News.
---

# Episodes & Broadcast Backlog

Complete stream archive tracked for *Barely Informed News*. Episodes are ingested from Twitch and YouTube streams to extract characters, segments, storylines, and lore.

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
    <input type="text" id="episode-search" placeholder="Search episode titles..." />
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
      <th style="width: 5rem;">#</th>
      <th>Stream Title</th>
      <th style="width: 6rem;">Length</th>
      <th style="width: 8rem;">Status</th>
      <th style="width: 7rem;">Archive</th>
    </tr>
  </thead>
  <tbody>
{table_rows_html}
  </tbody>
</table>
</div>

<div class="pagination-controls" id="pagination-controls">
  <button id="btn-prev" class="page-btn">← Previous</button>
  <span id="page-info" class="page-info">Page 1 of 1</span>
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
  min-width: 200px;
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
.badge {{
  display: inline-block;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
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

<script>
document.addEventListener("nav", function() {{
  initEpisodesTable();
}});
if (document.readyState !== "loading") {{
  initEpisodesTable();
}} else {{
  document.addEventListener("DOMContentLoaded", initEpisodesTable);
}}

function initEpisodesTable() {{
  const table = document.getElementById("episodes-table");
  if (!table) return;

  const searchInput = document.getElementById("episode-search");
  const statusFilter = document.getElementById("status-filter");
  const pageSizeSelect = document.getElementById("page-size");
  const prevBtn = document.getElementById("btn-prev");
  const nextBtn = document.getElementById("btn-next");
  const pageInfo = document.getElementById("page-info");

  const allRows = Array.from(table.querySelectorAll("tbody tr"));
  let currentPage = 1;

  function filterAndPaginate() {{
    const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
    const status = statusFilter ? statusFilter.value : "all";
    const pageSizeVal = pageSizeSelect ? pageSizeSelect.value : "50";
    const pageSize = pageSizeVal === "all" ? allRows.length : parseInt(pageSizeVal, 10);

    const matchingRows = allRows.filter(function(row) {{
      const rowStatus = row.getAttribute("data-status");
      const rowTitle = row.getAttribute("data-title") || "";
      const matchesStatus = status === "all" || rowStatus === status;
      const matchesSearch = !query || rowTitle.indexOf(query) !== -1;
      return matchesStatus && matchesSearch;
    }});

    const totalPages = Math.max(1, Math.ceil(matchingRows.length / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = startIdx + pageSize;

    allRows.forEach(function(row) {{
      row.style.display = "none";
    }});

    matchingRows.slice(startIdx, endIdx).forEach(function(row) {{
      row.style.display = "";
    }});

    if (pageInfo) {{
      pageInfo.textContent = "Page " + currentPage + " of " + totalPages + " (" + matchingRows.length + " streams)";
    }}
    if (prevBtn) prevBtn.disabled = (currentPage <= 1);
    if (nextBtn) nextBtn.disabled = (currentPage >= totalPages);
  }}

  if (searchInput) searchInput.addEventListener("input", function() {{ currentPage = 1; filterAndPaginate(); }});
  if (statusFilter) statusFilter.addEventListener("change", function() {{ currentPage = 1; filterAndPaginate(); }});
  if (pageSizeSelect) pageSizeSelect.addEventListener("change", function() {{ currentPage = 1; filterAndPaginate(); }});
  if (prevBtn) prevBtn.addEventListener("click", function() {{ if (currentPage > 1) {{ currentPage--; filterAndPaginate(); }} }});
  if (nextBtn) nextBtn.addEventListener("click", function() {{ currentPage++; filterAndPaginate(); }});

  filterAndPaginate();
}}
</script>
"""

    CONTENT_EPISODES.mkdir(parents=True, exist_ok=True)
    (CONTENT_EPISODES / "index.md").write_text(md_content, encoding="utf-8")
    print(f"✓ Generated content/episodes/index.md with {total_streams} streams")


if __name__ == "__main__":
    generate_episodes_index()
