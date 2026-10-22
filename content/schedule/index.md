---
title: Schedule Report Card
description: Good-natured attendance audit of Case's advertised Mon/Wed/Fri stream schedule versus the episode catalog.
---

# Schedule Report Card

[[../characters/case-blackwell|Case Blackwell]] advertises a tidy **Monday / Wednesday / Friday** *Barely Informed News* schedule. The [[../episodes/index|episode catalog]] tells a warmer, messier story.

This page grades **advertised-slot attendance** only — did a wiki episode land on that calendar Mon, Wed, or Fri? Bonus Tuesday chaos is celebrated separately. Figures are computed from ingested episode dates (2023-11-22 → 2026-10-19, **342** distinct broadcast days).

> **House curve:** BIN does not use your high school's grading scale. Clearing 40% of Fridays is already a solid C. Mondays are graded on a spiritual curve and still somehow fail.

## Report card

| Course | Attendance | Rate | Grade |
|---|---:|---:|---|
| Monday (Honors) | 43/152 | 28.3% | **F** — Theoretical broadcast day |
| Wednesday (Elective) | 57/152 | 37.5% | **D** — Sighted in the wild |
| Friday (Core) | 63/152 | 41.4% | **C** — Fridays-adjacent competence |
| **MWF composite** | 163/456 | 35.7% | **D** — Sighted in the wild |

**Term GPA:** **1.0** / 4.00  
*(Average of the three day-letter GPAs. Extra-credit Tue/Thu streams do not inflate this number, no matter how hard they try.)*

### Teacher's comments

- **Valedictorian of the trifecta:** Friday — the day most likely to actually happen.
- **Needs improvement:** Monday — frequently excused by vibes, travel, sty, or "next week for sure."
- **Hidden curriculum:** Across the whole archive the busiest broadcast weekdays are **Thursday (68)** and **Tuesday (64)**, with Friday (63) close behind. Monday (43) remains the rarest weekday on the books. The *real* schedule appears to be "whenever the newsroom assembles," with Friday as the closest thing to a promise.
- **Last 12 months:** MWF hit rate **30.6%** (Mon 30.2% · Wed 26.9% · Fri 34.6%); **56** non-MWF bonus shows. Even the recent form guide agrees — Fridays lead, Mondays sulk, Wednesdays flip a coin and then pocket it.

## Year-by-year

| Year | Mon | Wed | Fri | MWF overall | Bonus (non-MWF) |
|---|---:|---:|---:|---:|---:|
| 2023 | 40.0% | 66.7% | 50.0% | 52.9% (9/17) | 12 |
| 2024 | 18.9% | 48.1% | 40.4% | 35.7% (56/157) | 62 |
| 2025 | 34.6% | 28.3% | 44.2% | 35.7% (56/157) | 61 |
| 2026 | 31.0% | 31.7% | 38.1% | 33.6% (42/125) | 44 |

## Honor roll & detention

### Longest on-schedule streaks

| Span | Feat |
|---|---|
| 2025-01-15 → 2025-02-03 | 9 consecutive MWF shows |
| 2023-12-06 → 2023-12-18 | 6 consecutive MWF shows |
| 2026-04-22 → 2026-05-04 | 6 consecutive MWF shows |
| 2024-06-05 → 2024-06-14 | 5 consecutive MWF shows |
| 2026-05-29 → 2026-06-08 | 5 consecutive MWF shows |

### Longest advertised-slot droughts

| Span | Quiet stretch |
|---|---|
| 2024-11-08 → 2024-12-20 | 19 MWF slots quiet (42 calendar days) |
| 2025-11-05 → 2025-12-17 | 19 MWF slots quiet (42 calendar days) |
| 2025-06-23 → 2025-07-16 | 11 MWF slots quiet (23 calendar days) |
| 2026-02-09 → 2026-03-04 | 11 MWF slots quiet (23 calendar days) |
| 2025-08-13 → 2025-09-01 | 9 MWF slots quiet (19 calendar days) |

*(Droughts measure consecutive missed Mon/Wed/Fri slots — they happily coexist with surprise Tuesday specials.)*

## Extra credit

Case does not owe the universe a sparse calendar. **179** catalogued broadcasts landed on Tue/Thu/Sat/Sun in this window — more "off-schedule" shows than successful Mondays (43). Truancy on the brochure; overachievement in the lab.

| Weekday | Episodes in catalog |
|---|---:|
| Monday | 43 |
| Tuesday | 64 |
| Wednesday | 57 |
| Thursday | 68 |
| Friday | 63 |
| Saturday | 42 |
| Sunday | 5 |

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
