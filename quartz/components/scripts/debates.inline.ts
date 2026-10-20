type Debate = {
  id: string
  date: string
  episode: string
  timestamp: string | null
  topic: string
  participants: string[]
  positions: Record<string, string>
  winner: string | null
  summary: string | null
  night_index?: number
}

type SortKey = "date" | "topic" | "winner" | "episode"
type SortDir = "asc" | "desc"

const LABEL: Record<string, string> = {
  munch: "Munch",
  crum: "Crum",
  draw: "Draw",
  default: "Default",
  scrum: "Scrum",
  plumb: "Plumb",
  "al-manchester": "Al Manchester",
  kendelle: "Kendelle",
  "case-blackwell": "Case",
  fiona: "Fiona",
}

function label(slug: string | null | undefined): string {
  if (!slug) return "—"
  return LABEL[slug] ?? slug
}

function debatesJsonUrl(): string {
  return `${window.location.origin}/static/debates.json`
}

function cmp(a: Debate, b: Debate, key: SortKey, dir: SortDir): number {
  const mul = dir === "asc" ? 1 : -1
  if (key === "date") {
    const av = `${a.date}\t${a.timestamp ?? ""}\t${a.id}`
    const bv = `${b.date}\t${b.timestamp ?? ""}\t${b.id}`
    return mul * av.localeCompare(bv)
  }
  const av = (a[key] ?? "") as string
  const bv = (b[key] ?? "") as string
  return mul * av.localeCompare(bv)
}

function renderScoreboard(root: HTMLElement, debates: Debate[]) {
  const host = root.querySelector<HTMLElement>("[data-scoreboard]")
  if (!host) return

  let munch = 0
  let crum = 0
  const points: { i: number; m: number; c: number; date: string }[] = []
  const chrono = [...debates].sort((a, b) =>
    `${a.date}\t${a.timestamp ?? ""}\t${a.id}`.localeCompare(
      `${b.date}\t${b.timestamp ?? ""}\t${b.id}`,
    ),
  )
  chrono.forEach((d, i) => {
    if (d.winner === "munch" || d.winner === "al-manchester") munch += 1
    else if (d.winner === "crum") crum += 1
    points.push({ i, m: munch, c: crum, date: d.date })
  })

  const w = 720
  const h = 220
  const pad = { t: 16, r: 16, b: 28, l: 36 }
  const maxY = Math.max(munch, crum, 1)
  const innerW = w - pad.l - pad.r
  const innerH = h - pad.t - pad.b
  const x = (i: number) => pad.l + (points.length <= 1 ? 0 : (i / (points.length - 1)) * innerW)
  const y = (v: number) => pad.t + innerH - (v / maxY) * innerH

  const path = (key: "m" | "c") =>
    points
      .map((p, idx) => `${idx === 0 ? "M" : "L"}${x(p.i).toFixed(1)},${y(p[key]).toFixed(1)}`)
      .join(" ")

  const yearTicks = new Map<string, number>()
  points.forEach((p) => {
    const yyyy = p.date.slice(0, 4)
    if (!yearTicks.has(yyyy)) yearTicks.set(yyyy, p.i)
  })

  host.innerHTML = `
    <div class="scoreboard-header">
      <h2>Scoreboard</h2>
      <div class="scoreboard-legend">
        <span class="munch"><i></i> Munch</span>
        <span class="crum"><i></i> Crum</span>
      </div>
    </div>
    <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Cumulative Munch vs Crum debate wins">
      <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${pad.t + innerH}" stroke="currentColor" opacity="0.2" />
      <line x1="${pad.l}" y1="${pad.t + innerH}" x2="${pad.l + innerW}" y2="${pad.t + innerH}" stroke="currentColor" opacity="0.2" />
      <text x="${pad.l - 6}" y="${pad.t + 4}" text-anchor="end" font-size="11" fill="currentColor" opacity="0.55">${maxY}</text>
      <text x="${pad.l - 6}" y="${pad.t + innerH}" text-anchor="end" font-size="11" fill="currentColor" opacity="0.55">0</text>
      ${[...yearTicks.entries()]
        .map(
          ([yyyy, i]) =>
            `<text x="${x(i).toFixed(1)}" y="${h - 8}" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.55">${yyyy}</text>`,
        )
        .join("")}
      <path d="${path("m")}" fill="none" stroke="#c45c26" stroke-width="2.25" />
      <path d="${path("c")}" fill="none" stroke="#2f6fed" stroke-width="2.25" />
    </svg>
    <div class="scoreboard-totals">Running total — Munch <strong>${munch}</strong> · Crum <strong>${crum}</strong> · ${debates.length} catalogued debates</div>
  `
}

function renderTable(root: HTMLElement, rows: Debate[], sortKey: SortKey, sortDir: SortDir) {
  const tbody = root.querySelector<HTMLTableSectionElement>("[data-tbody]")
  const count = root.querySelector<HTMLElement>("[data-count]")
  if (!tbody) return
  if (count) count.textContent = `${rows.length} debate${rows.length === 1 ? "" : "s"}`

  root.querySelectorAll<HTMLElement>("th[data-sort]").forEach((th) => {
    th.classList.remove("sorted-asc", "sorted-desc")
    if (th.dataset.sort === sortKey) th.classList.add(sortDir === "asc" ? "sorted-asc" : "sorted-desc")
  })

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="debates-empty">No debates match these filters.</td></tr>`
    return
  }

  tbody.innerHTML = rows
    .map((d) => {
      const epHref = `../episodes/${d.episode}`
      const winnerClass = d.winner ?? ""
      const participants = d.participants
        .map((p) => `<a href="../characters/${p}">${label(p)}</a>`)
        .join(", ")
      return `<tr>
        <td><a href="${epHref}">${d.date}</a>${d.timestamp ? `<br/><small>${d.timestamp}</small>` : ""}</td>
        <td class="topic">${escapeHtml(d.topic)}</td>
        <td>${participants}</td>
        <td><span class="winner-pill ${winnerClass}">${label(d.winner)}</span></td>
        <td class="summary">${escapeHtml(d.summary ?? "")}</td>
      </tr>`
    })
    .join("")
}

function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

function applyFilters(all: Debate[], root: HTMLElement): Debate[] {
  const q = (root.querySelector<HTMLInputElement>("[data-q]")?.value ?? "").trim().toLowerCase()
  const year = root.querySelector<HTMLSelectElement>("[data-year]")?.value ?? ""
  const winner = root.querySelector<HTMLSelectElement>("[data-winner]")?.value ?? ""
  const participant = root.querySelector<HTMLSelectElement>("[data-participant]")?.value ?? ""

  return all.filter((d) => {
    if (year && !d.date.startsWith(year)) return false
    if (winner === "__none__" && d.winner) return false
    if (winner && winner !== "__none__" && d.winner !== winner) return false
    if (participant && !d.participants.includes(participant)) return false
    if (!q) return true
    const hay = [d.topic, d.summary ?? "", d.winner ?? "", ...d.participants, ...Object.values(d.positions)]
      .join(" ")
      .toLowerCase()
    return hay.includes(q)
  })
}

document.addEventListener("nav", async () => {
  const root = document.querySelector<HTMLElement>(".debates-catalog")
  if (!root) return

  let debates: Debate[] = []
  try {
    const res = await fetch(debatesJsonUrl())
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    debates = await res.json()
  } catch (err) {
    root.querySelector("[data-main]")!.innerHTML =
      `<p class="debates-error">Could not load debate catalog (${String(err)}).</p>`
    return
  }

  // populate filters
  const years = [...new Set(debates.map((d) => d.date.slice(0, 4)))].sort()
  const winners = [...new Set(debates.map((d) => d.winner).filter(Boolean) as string[])].sort()
  const participants = [...new Set(debates.flatMap((d) => d.participants))].sort()

  const yearSel = root.querySelector<HTMLSelectElement>("[data-year]")!
  const winnerSel = root.querySelector<HTMLSelectElement>("[data-winner]")!
  const partSel = root.querySelector<HTMLSelectElement>("[data-participant]")!

  yearSel.innerHTML =
    `<option value="">All years</option>` + years.map((y) => `<option value="${y}">${y}</option>`).join("")
  winnerSel.innerHTML =
    `<option value="">All winners</option><option value="__none__">(unrecorded)</option>` +
    winners.map((w) => `<option value="${w}">${label(w)}</option>`).join("")
  partSel.innerHTML =
    `<option value="">All participants</option>` +
    participants.map((p) => `<option value="${p}">${label(p)}</option>`).join("")

  let sortKey: SortKey = "date"
  let sortDir: SortDir = "desc"

  const refresh = () => {
    const filtered = applyFilters(debates, root).sort((a, b) => cmp(a, b, sortKey, sortDir))
    renderTable(root, filtered, sortKey, sortDir)
  }

  renderScoreboard(root, debates)
  refresh()

  root.querySelector("[data-q]")?.addEventListener("input", refresh)
  yearSel.addEventListener("change", refresh)
  winnerSel.addEventListener("change", refresh)
  partSel.addEventListener("change", refresh)

  root.querySelectorAll<HTMLElement>("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort as SortKey
      if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc"
      else {
        sortKey = key
        sortDir = key === "date" ? "desc" : "asc"
      }
      refresh()
    })
  })
})
