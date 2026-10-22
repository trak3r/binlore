"""MWF schedule attendance report card from the episode catalog."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .paths import CONTENT_DIR, CONTENT_EPISODES, REPO_ROOT

DATA_PATH = REPO_ROOT / "data" / "schedule-report.json"
PAGE_PATH = CONTENT_DIR / "schedule" / "index.md"

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MWF = (0, 2, 4)
DATE_RE = re.compile(r"^date:\s*[\"']?(\d{4}-\d{2}-\d{2})", re.M)
STEM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _bin_grade(pct: float) -> tuple[str, str]:
    """Return (letter, epithet) on the curved BIN report-card scale."""
    if pct >= 75:
        return "A", "Showed up on purpose"
    if pct >= 55:
        return "B", "Spirit of the schedule"
    if pct >= 40:
        return "C", "Fridays-adjacent competence"
    if pct >= 30:
        return "D", "Sighted in the wild"
    return "F", "Theoretical broadcast day"


def _gpa(letter: str) -> float:
    return {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}[letter]


def load_episode_dates(episodes_dir: Path | None = None) -> set[date]:
    root = episodes_dir or CONTENT_EPISODES
    dates: set[date] = set()
    for path in sorted(root.glob("*.md")):
        if path.name == "index.md":
            continue
        text = path.read_text(encoding="utf-8")
        m = DATE_RE.search(text)
        if m:
            dates.add(date.fromisoformat(m.group(1)))
            continue
        stem = STEM_RE.match(path.stem)
        if stem:
            dates.add(date.fromisoformat(stem.group(1)))
    return dates


def iter_mwf(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() in MWF:
            yield d
        d += timedelta(days=1)


def _day_stats(ep_set: set[date], start: date, end: date) -> dict[str, Any]:
    slots = list(iter_mwf(start, end))
    out: dict[str, Any] = {}
    for wd, key in ((0, "monday"), (2, "wednesday"), (4, "friday")):
        day_slots = [d for d in slots if d.weekday() == wd]
        hits = sum(1 for d in day_slots if d in ep_set)
        pct = round(100.0 * hits / len(day_slots), 1) if day_slots else 0.0
        letter, epithet = _bin_grade(pct)
        out[key] = {
            "hits": hits,
            "slots": len(day_slots),
            "pct": pct,
            "grade": letter,
            "epithet": epithet,
        }
    hits = sum(1 for d in slots if d in ep_set)
    pct = round(100.0 * hits / len(slots), 1) if slots else 0.0
    letter, epithet = _bin_grade(pct)
    out["overall"] = {
        "hits": hits,
        "slots": len(slots),
        "pct": pct,
        "grade": letter,
        "epithet": epithet,
    }
    out["bonus_non_mwf"] = sum(1 for d in ep_set if start <= d <= end and d.weekday() not in MWF)
    out["total_episodes"] = sum(1 for d in ep_set if start <= d <= end)
    return out


def _mwf_streaks(ep_set: set[date], start: date, end: date, *, present: bool) -> list[dict[str, Any]]:
    streaks: list[dict[str, Any]] = []
    cur_start: date | None = None
    cur_end: date | None = None
    cur_count = 0

    def flush():
        nonlocal cur_start, cur_end, cur_count
        if cur_start is not None and cur_end is not None and cur_count:
            streaks.append(
                {
                    "start": cur_start.isoformat(),
                    "end": cur_end.isoformat(),
                    "slots": cur_count,
                    "calendar_days": (cur_end - cur_start).days,
                }
            )
        cur_start = cur_end = None
        cur_count = 0

    for d in iter_mwf(start, end):
        hit = d in ep_set
        if hit == present:
            if cur_start is None:
                cur_start = d
            cur_end = d
            cur_count += 1
        else:
            flush()
    flush()
    streaks.sort(key=lambda s: (-s["slots"], s["start"]))
    return streaks


def build_report(ep_set: set[date] | None = None) -> dict[str, Any]:
    dates = ep_set if ep_set is not None else load_episode_dates()
    if not dates:
        raise RuntimeError("No episode dates found under content/episodes/")
    start, end = min(dates), max(dates)
    weekday_counts = Counter(DAY_NAMES[d.weekday()] for d in dates)

    by_year: dict[str, Any] = {}
    for year in range(start.year, end.year + 1):
        a = max(date(year, 1, 1), start)
        b = min(date(year, 12, 31), end)
        by_year[str(year)] = _day_stats(dates, a, b)

    overall = _day_stats(dates, start, end)
    letters = [overall[k]["grade"] for k in ("monday", "wednesday", "friday")]
    gpa = round(sum(_gpa(L) for L in letters) / 3, 2)

    return {
        "advertised_schedule": ["monday", "wednesday", "friday"],
        "source": "content/episodes/*.md date frontmatter",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "episode_count": len(dates),
        "gpa": gpa,
        "overall": overall,
        "by_year": by_year,
        "last_12_months": _day_stats(dates, end - timedelta(days=365), end),
        "all_episodes_by_weekday": dict(weekday_counts),
        "longest_hit_streaks": _mwf_streaks(dates, start, end, present=True)[:5],
        "longest_miss_streaks": _mwf_streaks(dates, start, end, present=False)[:5],
        "grading_scale": [
            {"min_pct": 75, "grade": "A", "epithet": "Showed up on purpose"},
            {"min_pct": 55, "grade": "B", "epithet": "Spirit of the schedule"},
            {"min_pct": 40, "grade": "C", "epithet": "Fridays-adjacent competence"},
            {"min_pct": 30, "grade": "D", "epithet": "Sighted in the wild"},
            {"min_pct": 0, "grade": "F", "epithet": "Theoretical broadcast day"},
        ],
    }


def _fmt_row(label: str, block: dict[str, Any]) -> str:
    return (
        f"| {label} | {block['hits']}/{block['slots']} | {block['pct']}% | "
        f"**{block['grade']}** — {block['epithet']} |"
    )


def render_markdown(report: dict[str, Any]) -> str:
    o = report["overall"]
    mon, wed, fri = o["monday"], o["wednesday"], o["friday"]
    overall = o["overall"]
    start, end = report["range"]["start"], report["range"]["end"]
    wd = report["all_episodes_by_weekday"]
    ranking = sorted(
        (("Monday", mon), ("Wednesday", wed), ("Friday", fri)),
        key=lambda kv: (-kv[1]["pct"], kv[0]),
    )
    champ = ranking[0][0]
    cellar = ranking[-1][0]

    year_rows = []
    for year, block in report["by_year"].items():
        year_rows.append(
            f"| {year} | {block['monday']['pct']}% | {block['wednesday']['pct']}% | "
            f"{block['friday']['pct']}% | {block['overall']['pct']}% "
            f"({block['overall']['hits']}/{block['overall']['slots']}) | {block['bonus_non_mwf']} |"
        )

    hit_rows = []
    for s in report["longest_hit_streaks"]:
        hit_rows.append(
            f"| {s['start']} → {s['end']} | {s['slots']} consecutive MWF shows |"
        )
    miss_rows = []
    for s in report["longest_miss_streaks"]:
        miss_rows.append(
            f"| {s['start']} → {s['end']} | {s['slots']} MWF slots quiet "
            f"({s['calendar_days']} calendar days) |"
        )

    l12 = report["last_12_months"]

    return f"""---
title: Schedule Report Card
description: Good-natured attendance audit of Case's advertised Mon/Wed/Fri stream schedule versus the episode catalog.
---

# Schedule Report Card

[[../characters/case-blackwell|Case Blackwell]] advertises a tidy **Monday / Wednesday / Friday** *Barely Informed News* schedule. The [[../episodes/index|episode catalog]] tells a warmer, messier story.

This page grades **advertised-slot attendance** only — did a wiki episode land on that calendar Mon, Wed, or Fri? Bonus Tuesday chaos is celebrated separately. Figures are computed from ingested episode dates ({start} → {end}, **{report['episode_count']}** distinct broadcast days).

> **House curve:** BIN does not use your high school's grading scale. Clearing 40% of Fridays is already a solid C. Mondays are graded on a spiritual curve and still somehow fail.

## Report card

| Course | Attendance | Rate | Grade |
|---|---:|---:|---|
{_fmt_row("Monday (Honors)", mon)}
{_fmt_row("Wednesday (Elective)", wed)}
{_fmt_row("Friday (Core)", fri)}
{_fmt_row("**MWF composite**", overall)}

**Term GPA:** **{report['gpa']}** / 4.00  
*(Average of the three day-letter GPAs. Extra-credit Tue/Thu streams do not inflate this number, no matter how hard they try.)*

### Teacher's comments

- **Valedictorian of the trifecta:** {champ} — the day most likely to actually happen.
- **Needs improvement:** {cellar} — frequently excused by vibes, travel, sty, or "next week for sure."
- **Hidden curriculum:** Across the whole archive the busiest broadcast weekdays are **Thursday ({wd.get('Thursday', 0)})** and **Tuesday ({wd.get('Tuesday', 0)})**, with Friday ({wd.get('Friday', 0)}) close behind. Monday ({wd.get('Monday', 0)}) remains the rarest weekday on the books. The *real* schedule appears to be "whenever the newsroom assembles," with Friday as the closest thing to a promise.
- **Last 12 months:** MWF hit rate **{l12['overall']['pct']}%** (Mon {l12['monday']['pct']}% · Wed {l12['wednesday']['pct']}% · Fri {l12['friday']['pct']}%); **{l12['bonus_non_mwf']}** non-MWF bonus shows. Even the recent form guide agrees — Fridays lead, Mondays sulk, Wednesdays flip a coin and then pocket it.

## Year-by-year

| Year | Mon | Wed | Fri | MWF overall | Bonus (non-MWF) |
|---|---:|---:|---:|---:|---:|
{chr(10).join(year_rows)}

## Honor roll & detention

### Longest on-schedule streaks

| Span | Feat |
|---|---|
{chr(10).join(hit_rows)}

### Longest advertised-slot droughts

| Span | Quiet stretch |
|---|---|
{chr(10).join(miss_rows)}

*(Droughts measure consecutive missed Mon/Wed/Fri slots — they happily coexist with surprise Tuesday specials.)*

## Extra credit

Case does not owe the universe a sparse calendar. **{o['bonus_non_mwf']}** catalogued broadcasts landed on Tue/Thu/Sat/Sun in this window — more "off-schedule" shows than successful Mondays ({mon['hits']}). Truancy on the brochure; overachievement in the lab.

| Weekday | Episodes in catalog |
|---|---:|
| Monday | {wd.get('Monday', 0)} |
| Tuesday | {wd.get('Tuesday', 0)} |
| Wednesday | {wd.get('Wednesday', 0)} |
| Thursday | {wd.get('Thursday', 0)} |
| Friday | {wd.get('Friday', 0)} |
| Saturday | {wd.get('Saturday', 0)} |
| Sunday | {wd.get('Sunday', 0)} |

## Grading key (BIN curve)

| Grade | Attendance | Official epithet |
|---|---:|---|
| A | ≥ 75% | Showed up on purpose |
| B | ≥ 55% | Spirit of the schedule |
| C | ≥ 40% | Fridays-adjacent competence |
| D | ≥ 30% | Sighted in the wild |
| F | < 30% | Theoretical broadcast day |

## Methodology

1. Collect distinct `date:` values from `content/episodes/*.md` (filename date used if frontmatter is missing).
2. Enumerate every Monday, Wednesday, and Friday from the earliest episode through the latest.
3. A **hit** is any advertised slot that has at least one ingested episode that day.
4. Regenerated with `./binlore schedule-report` (writes this page + `data/schedule-report.json`).

This is affectionate scorekeeping, not a HR file. Streams get cancelled for holidays, travel, illness, apartment moves, Thailand arcs, and the occasional mechanical gorilla. The joke is the brochure — the catalog is the punchline.

See also: [[../episodes/index|Episodes & Broadcast Archive]], [[../characters/case-blackwell|Case Blackwell]].
"""


def write_report(*, sync_page: bool = True) -> dict[str, Any]:
    report = build_report()
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if sync_page:
        PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PAGE_PATH.write_text(render_markdown(report), encoding="utf-8")
    return report
