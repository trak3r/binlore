# BIN Lore

**Autonomous media → knowledge pipeline:** watch a Twitch broadcast, transcribe it locally, extract structured lore with an LLM, and publish a searchable wiki — unattended.

Live site: **[trak3r.github.io/binlore](https://trak3r.github.io/binlore/)** · Source domain: [Barely Informed News](https://www.twitch.tv/caseblackwell) (Case Blackwell)

[![Wiki homepage](https://github.com/trak3r/binlore/releases/download/media-assets/binlore-wiki-home.png)](https://trak3r.github.io/binlore/)

## Why this exists

Most “AI demos” stop at a chat transcript. BIN Lore is an end-to-end production loop: resilient VOD ingest, local speech-to-text, canon-aware LLM extraction, idempotent wiki writes, Quartz compile validation, and GitHub Pages deploy. The public artifact is a living fan wiki; the engineering is a repeatable agentic content factory.

## Features

- **VOD ingest** — `yt-dlp` audio-only download from Twitch, with automatic YouTube-archive fallback when Twitch retention expires
- **Local transcription** — `faster-whisper` timestamped transcripts (no cloud STT required)
- **Canon-aware extraction** — Google AI Studio (Gemini free tier) prompts seeded with existing characters / segments / storylines so ASR name errors reconcile to wiki canon
- **Idempotent wiki updates** — episode rundowns, character appearance tables, storyline beats, segment occurrence logs
- **Screencap CDN** — ffmpeg frame capture hosted on a permanent GitHub Release asset CDN (repo stays binary-light)
- **Unattended batch** — `binlore process-all` with disk hygiene, retries, Quartz build gates, and per-episode git commits
- **Published site** — Quartz wiki on GitHub Pages with graph view, backlinks, and full-text search

## Pipeline

```text
Twitch / YouTube VOD
        │
        ▼
┌───────────────────┐
│  binlore ingest   │  audio-only download + Whisper transcript
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  binlore extract  │  Gemini (AI Studio) → structured lore JSON
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ binlore update-wiki│  characters · segments · storylines · episodes
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Quartz + Pages   │  validate build → deploy live wiki
└───────────────────┘
```

[![Character page](https://github.com/trak3r/binlore/releases/download/media-assets/binlore-character-page.png)](https://trak3r.github.io/binlore/characters/case-blackwell)

## Quick start

```bash
# deps: ffmpeg, Node 22+, Python 3.11+
npm ci
cd tools && python3 -m venv .venv && source .venv/bin/activate && pip install -e . && cd ..
cp tools/.env.example tools/.env   # add GEMINI_API_KEY (extract only)

./binlore vods
./binlore ingest --latest
./binlore extract --latest
./binlore update-wiki --latest
npx quartz build --serve          # http://localhost:8080
```

Unattended backlog (370+ historical streams). Default is transcribe-only:

```bash
./binlore process-all --status
./binlore transcribe-all           # ingest + Whisper; no LLM
./binlore process-all --extract    # mine existing transcripts oldest-first via Gemini
```

> **Legal Disclaimer:** Unofficial, non-commercial fan wiki and documentation project. Not affiliated with, endorsed by, or sponsored by Case Blackwell, Barely Informed News, or Twitch. All character names, likenesses, trademarks, and media assets belong to their respective copyright holders and are referenced under fair use (17 U.S.C. § 107) for commentary, criticism, and archival purposes. Not operated for profit. See [`content/disclaimer.md`](content/disclaimer.md) for full legal disclosures.

---

## Operator guide

Detail below is for running and extending the pipeline. Skip to [Setup & Prerequisites](#setup--prerequisites) if you already know the shape of the system.

## Where Downloaded VODs & Transcripts Live Locally

When you ingest a stream, all downloaded media and processed artifacts are saved in:

```
tools/runs/<vod-id>/
```

### Where Does `<vod-id>` Come From?

- **Twitch VOD IDs:** Live streams air on [Twitch (`caseblackwell`)](https://www.twitch.tv/caseblackwell), where Twitch assigns a numeric video ID to each broadcast (e.g. `2863722826` from `https://www.twitch.tv/videos/2863722826`).
- **Finding VOD IDs:**
  1. **Wiki Episodes List:** The complete [Episodes & Broadcast Archive](https://trak3r.github.io/binlore/episodes/) has a dedicated **VOD ID** column for every stream.
  2. **CLI:** Run `./binlore vods` to print recent Twitch streams with their IDs, broadcast dates, and lengths.
- **YouTube Archive IDs:** Twitch purges VODs after ~60 days. The complete historical backlog of 370+ streams is preserved on the [YouTube Archive (`@CaseBlackwellStreams`)](https://www.youtube.com/@CaseBlackwellStreams). For archived streams beyond Twitch's retention window, the YouTube video ID (e.g. `ZSjvjEED3KA`) shown on the episodes list can be passed directly to `./binlore ingest <id>`.

For example, for VOD `2863722826` (_High T Wednesday News_):

```
tools/runs/2863722826/
├── audio.m4a              # Downloaded stream audio (high-quality audio-only)
├── meta.json              # VOD metadata (title, Twitch ID, duration, air date)
├── transcript.json        # Full timestamped Whisper transcript (segments array)
├── transcript.txt         # Human-readable transcript with [MM:SS] timestamps
├── transcript.plain.txt   # Plain un-timestamped transcript text
└── extraction.json        # Structured LLM output (segments, characters, lore)
```

**Why audio instead of full video?**
`yt-dlp` pulls the Twitch `Audio_Only` stream directly (~150 MB instead of a 6+ GB video file). This saves disk space and allows local Whisper transcription to process significantly faster.

**Git tracking:**
Media files (`*.m4a`, `*.mp4`, etc.) and batch logs are listed in `.gitignore` to prevent large binary bloat. Raw Whisper transcripts (`transcript.json`, `transcript.txt`) and stream metadata (`meta.json`) in `tools/runs/` are tracked in the repository so episodes can be reprocessed or re-analyzed in the future without requiring another VOD scrape or audio re-transcription. The wiki pages in `content/` are the public, reviewed canon.

---

## Setup & Prerequisites

### 1. System Dependencies

**Linux / Remote Server (Ubuntu / Debian):**
```bash
# Media tools for Twitch VOD download & audio processing
sudo apt update && sudo apt install -y ffmpeg

# Node.js 22+ (required for Quartz wiki build)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

**macOS:**
```bash
# Media tools for Twitch VOD download & audio processing
brew install yt-dlp ffmpeg

# Node.js 22+ (required for Quartz)
brew install node@22
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
```

### 2. Quartz Wiki Setup

From the repository root:

```bash
npm ci
```

### 3. Python Tools Setup (Ingest & Extraction CLI)

```bash
cd tools
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. Environment Configuration (`tools/.env`)

Copy the template configuration file:

```bash
cp tools/.env.example tools/.env
```

#### Google AI Studio API Key & Model Configuration

Lore extraction uses the Gemini API free tier directly (not OpenRouter). Transcription does not need a key.

1. Get a free API key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey). Do not attach a billing account.
2. Add your key to `tools/.env`:
   ```bash
   GEMINI_API_KEY="your-gemini-api-key-here"
   ```
3. *(Optional)* Pin a model. Default is `gemini-2.5-flash`. If daily quota is tiny, switch to Flash-Lite:
   ```bash
   GEMINI_MODEL="gemini-2.5-flash"
   # GEMINI_MODEL="gemini-2.5-flash-lite"
   ```

#### Hugging Face Token (Optional, Recommended for Cloud Servers)

When `faster-whisper` downloads speech-to-text models (such as `small` or `medium`), it downloads weights from Hugging Face Hub. On remote servers (AWS, Hetzner, DigitalOcean), unauthenticated requests can be aggressively rate-limited or throttled by Hugging Face (triggering `Warning: You are sending unauthenticated requests to the HF Hub`).

Setting a token provides:
- **Faster, prioritized downloads** with higher bandwidth.
- **Higher rate limits**, preventing HTTP `429 Too Many Requests` errors on shared datacenter IP ranges.
- **Clean logs** by suppressing unauthenticated hub warnings.

To set it up:
1. Create a free account at [huggingface.co](https://huggingface.co) if needed.
2. Generate a free access token with default **Read** permission at [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
3. Add it to `tools/.env`:
   ```bash
   HF_TOKEN="hf_your_token_here"
   ```

#### YouTube cookies (required for the YouTube archive on most servers)

Twitch VODs download without login. The YouTube archive fallback (`@CaseBlackwellStreams`) usually does not: datacenter IPs get `Sign in to confirm you’re not a bot`.

1. Use a **throwaway** Google account. Open a private/incognito window, log into YouTube, then visit `https://www.youtube.com/robots.txt` (only that tab).
2. Export `youtube.com` cookies to a Netscape `cookies.txt` ([yt-dlp instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)). Close the private window immediately so YouTube does not rotate the session.
3. Copy the file onto the harvester as `tools/cookies.txt` (gitignored; picked up automatically). Alternatively set in `tools/.env`:
   ```
   YTDLP_COOKIES=cookies.txt
   # local Mac only:
   # YTDLP_COOKIES_FROM_BROWSER=chrome
   ```
4. Restart `transcribe-all`. Re-export cookies when the bot check returns.

---

## Execution Guide

You can run commands in two ways:

- **Directly from repo root (recommended):** Use `./binlore <command>` (e.g. `./binlore extract --latest`)
- **From within the virtualenv:** Run `source tools/.venv/bin/activate` once, then use `binlore <command>` directly.

### Step 1: List Recent VODs

See the latest streams available on Case Blackwell's Twitch channel:

```bash
./binlore vods
./binlore vods --limit 10
```

### Step 2: Ingest a VOD (Download Audio + Transcribe)

Download the stream audio and generate a full timestamped transcript using local Whisper:

```bash
# Ingest the newest stream automatically
./binlore ingest --latest

# Or ingest with immediate audio cleanup to save disk space
./binlore ingest --latest --clean-audio

# Or ingest a specific VOD by URL or ID
./binlore ingest "https://www.twitch.tv/videos/2863722826"

# Optional: choose Whisper model size (default is 'small')
# Options: tiny, base, small, medium, large-v3
./binlore ingest --latest --model small
```

This creates the run folder in `tools/runs/<vod-id>/` and stubs an episode page in `content/episodes/YYYY-MM-DD.md`.

### Step 3: Extract Lore, Characters & Segments (Gemini)

Run the LLM extraction pipeline over the transcript:

```bash
# Preview prompt & token counts without calling the API (dry-run)
./binlore extract --latest --dry-run

# Run extraction using Gemini Flash (requires GEMINI_API_KEY)
./binlore extract --latest

# Or specify Flash-Lite / a timeout
./binlore extract --latest --model gemini-2.5-flash-lite
./binlore extract 2863722826 --timeout 180
```

**What this does automatically:**

1. Loads current wiki canon (`content/characters/`, `content/segments/`, `content/storylines/`) so the model knows established talent (like Munch, Crum, Jeb Nogget, Kendelle, Brandon/Cryptozeus) and reconciles ASR phonetic errors (e.g. "Crumb" $\to$ "Crum", "Noggin" $\to$ "Nogget").
2. Saves `tools/runs/<vod-id>/extraction.json`.
3. Populates `content/episodes/YYYY-MM-DD.md` with:
   - Stream overview
   - Segment rundown table (`| Start | End | Segment | Notes |`)
   - On-air talent detected (speaking vs mentioned) with Quartz wikilinks (`[[characters/crum|Crum]]`)
   - Storyline developments (`[[storylines/crum-dick-punch|Crum's Robotic Gorilla Groin Punch Bet]]`)
   - Timestamped candidate lore notes

### Step 4: Propagate Lore into the Wiki (`binlore update-wiki`)

Once extraction is complete, populate the rest of the wiki (Character appearance tables, Notable moments, Storyline beat timelines, and Segment occurrence tables) from the extraction data:

```bash
# Preview changes without modifying files (dry-run)
./binlore update-wiki --latest --dry-run

# Update wiki pages from the latest extraction
./binlore update-wiki --latest

# Or update for a specific VOD
./binlore update-wiki 2863722826
```

**What this does automatically:**

- **Character pages** (`content/characters/<name>.md`): Appends to `## Appearances` and adds timestamped quotes/facts to `## Notable moments` with links back to the episode.
- **New contributors & correspondents**: Automatically creates profiles for newly detected on-air personalities (e.g. `hype-train.md`, `tommy-biglaw.md`) and indexes them in `content/characters/index.md`.
- **Storyline pages** (`content/storylines/<slug>.md`): Appends new beat entries to the `## Key beats` timeline with exact timestamps and episode anchors.
- **Segment pages** (`content/segments/<slug>.md`): Appends occurrences to `## Known occurrences`.
- **Idempotent**: Safe to run repeatedly without creating duplicate rows or notes.

### Step 5: Capture & Host Screencaps (`binlore screencap`)

Extract sharp, lightweight video frames for characters and segments via ffmpeg without downloading the entire video, and host them on the permanent GitHub release `media-assets` CDN:

```bash
# Capture key frames for all detected characters & segments in latest VOD
./binlore screencap --latest

# Capture a specific frame by timestamp
./binlore screencap 2863722826 --timestamp 01:14:00 --name crum

# Capture and immediately upload to GitHub release media-assets
./binlore screencap --latest --upload
```

Image assets are served directly from GitHub's Fastly CDN (`https://github.com/trak3r/binlore/releases/download/media-assets/<name>.jpg`), keeping the git repository 100% lightweight and clean of binary files.

### Step 6: Preview the Wiki Locally

Preview your wiki in your browser with live-reload:

```bash
# From repository root:
npx quartz build --serve
```

Open [http://localhost:8080](http://localhost:8080).

### Step 7: Review & Publish to GitHub Pages

Check the generated episode notes, make any edits or promote new lore facts to character pages, then push to GitHub:

```bash
git status
git add content/
git commit -m "Add notes for episode YYYY-MM-DD"
git push origin main
```

The GitHub Actions workflow automatically builds and deploys to [https://trak3r.github.io/binlore/](https://trak3r.github.io/binlore/).

### Step 8: Reclaim Disk Space (`binlore clean`)

Stream audio files take ~150 MB per 2-hour VOD. Once transcription is finished, you can safely remove the audio files to free up disk space while preserving all transcripts, metadata, and wiki content:

```bash
# Preview which files would be deleted and space saved
./binlore clean --dry-run

# Delete audio files across all completed runs
./binlore clean

# Keep the most recent stream's audio and delete older ones
./binlore clean --keep 1

# Clean a specific VOD
./binlore clean 2863722826
```

---

## Unattended Batch Processing on a Server (`binlore process-all`)

To process the entire 370+ episode backlog unattended on a home server, VPS, or cloud instance, use the autonomous batch processor:

```bash
./binlore transcribe-all
# Or:
./binlore process-all
python3 tools/process_all.py
```

Mining (after transcripts exist):

```bash
./binlore process-all --extract
```

### What It Does per Episode

1. **Backlog Discovery:** Cross-references `tools/youtube_catalog.json` with `tools/runs/` transcripts. Default queue is untranscribed streams (oldest first). `--extract` queues transcribed streams that lack `extraction.json`.
2. **Audio Ingest & Resilient Fallback:** Downloads audio using `yt-dlp`. If a Twitch VOD has expired (Twitch retention is ~60 days), it automatically falls back to the permanent YouTube archive stream. Skipped when a transcript already exists.
3. **Local Whisper Transcription:** Transcribes audio via `faster-whisper` (default model: `small`). Does not write episode stubs in transcribe-only mode.
4. **Immediate Disk Cleanup:** **Deletes the audio file immediately** once transcription finishes and is saved. Peak disk usage is capped to at most *one* temporary audio file at any moment (~150 MB).
5. **Lore Extraction (`--extract` only):** Sends the transcript and a compact canon roster to Google AI Studio (Gemini Flash, JSON schema). Unknown names are queued to `tools/runs/unknown-characters.jsonl` instead of auto-creating pages. Storyline wiki pages are left for a later corpus pass. On daily-quota 429s the batch **stops until reset**, rather than falling back to other vendors.
6. **Wiki Population (`--extract` only):** Updates `content/episodes/<date>.md` and existing character/segment pages. Fixture cold-opens (Pepito, Case, News) do not get a row for “did the usual thing.” Appearance tables are sorted by date; `first_seen` is backdated.
7. **Catalog Synchronization:** Regenerates `content/episodes/index.md` after extract.
8. **Wiki Compilation (`--extract` only):** Quartz build is skipped during transcribe-all.
9. **Automatic Git Commit:** Transcript ingest commits `tools/runs/<id>/`. Extract commits also include `content/`.
10. **Fault-Tolerant Loop:** If an individual stream fails, it cleans up partial files, logs the failure, and continues. Gemini daily quota exhaustion pauses the extract batch cleanly.

### Disk Space & Hygiene Guarantees

Running on a server with limited disk space requires strict hygiene:

- **Zero Media Accumulation:** Audio files are deleted *immediately* after transcription completes. The script never leaves audio files waiting for batch completion.
- **Cleanup on Error / Interrupt:** If a download fails or you press `Ctrl+C` (SIGINT/SIGTERM), a signal handler sweeps and deletes any temporary `.part`, `.ytdl`, or incomplete `.m4a` files.
- **Pre-flight Disk Monitoring:** Before downloading each episode, free disk space is checked against `--min-disk-gb` (default: `1.0` GB). If host disk space drops below this threshold, the script halts safely rather than crashing the filesystem.
- **Pre-run Sweep:** Automatically cleans any orphaned media files in `tools/runs/` left by previous manual runs before starting.
- **Bounded Logs:** Structured, single-line logs are written to `tools/runs/batch.log` (gitignored), ensuring log files never grow out of control.

### How to Run Unattended in the Background

#### Option A: Using `tmux` (Recommended)

```bash
# 1. Start a new tmux session
tmux new -s binlore

# 2. Start the batch processor (transcribe-only by default)
./binlore transcribe-all

# 3. Detach from the session: Press Ctrl+b, then press d
# The processor continues running in the background!

# 4. To reattach and view progress later:
tmux attach -t binlore
```

#### Option B: Using `nohup`

```bash
# Run in background and redirect stdout
nohup ./binlore transcribe-all > tools/runs/batch_stdout.log 2>&1 &
echo $! > tools/runs/batch.pid

# Check running process
tail -f tools/runs/batch.log

# Stop the process if needed
kill $(cat tools/runs/batch.pid)
```

#### Option C: As a `systemd` Service (Linux Servers)

Create `/etc/systemd/system/binlore.service`:

```ini
[Unit]
Description=BIN Lore Autonomous Batch Processor
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/binlore
ExecStart=/path/to/binlore/tools/.venv/bin/python3 /path/to/binlore/tools/process_all.py --delay 5.0
Restart=on-failure
RestartSec=30
EnvironmentFile=/path/to/binlore/tools/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now binlore
sudo journalctl -u binlore -f
```

### Checking Status & Monitoring Progress

```bash
# Print current backlog status and exit
./binlore process-all --status

# Output:
# --- [BIN Lore Backlog Status] ---
# Total catalog streams: 376
# Ingested & Extracted:  20
# Remaining in Backlog:  356 (5.3% complete)
# Free Disk Space:       108.72 GB
# Next in queue:         2026-06-22 — Don't Kier the Reaper, it's MONDAY NEWS
# ---------------------------------

# Preview the queue of unprocessed streams without modifying files
./binlore process-all --dry-run --limit 10

# Live-tail the log file
tail -f tools/runs/batch.log
```

### CLI Options Reference

| Flag | Default | Description |
| --- | --- | --- |
| `--limit N` | all | Process up to N episodes (useful for testing batches, e.g. `--limit 5`) |
| `--oldest-first` | `True` | Process backlog from oldest to newest (default) |
| `--newest-first` | `False` | Process newest unprocessed items first |
| `--model MODEL` | `small` | `faster-whisper` model: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--extract-model` | `gemini-2.5-flash` | Gemini model id (`--openrouter-model` is an alias) |
| `--delay SECONDS` | `5.0` | Cool-down sleep in seconds between episodes |
| `--timeout SECONDS` | `180.0` | Extraction timeout per model |
| `--min-disk-gb GB` | `1.0` | Minimum free disk space in GB required before ingesting |
| `--status` | — | Display backlog progress and disk space, then exit |
| `--dry-run` | — | Preview the queue without downloading or modifying files |
| `--keep-audio` | `False` | Retain audio files on disk (warning: consumes ~150 MB per episode) |
| `--skip-extract` | `True` | Transcribe only (default). `transcribe-all` forces this |
| `--extract` | — | Mine existing transcripts with Gemini, oldest-first |
| `--no-clean-existing` | `False` | Do not sweep `tools/runs/` for old media files on startup |
| `--no-skip-drafts` | `False` | Do not skip episodes marked with `draft: true` |
| `--build-quartz` / `--no-build` | extract only | Quartz is skipped during transcribe-all |
| `--git-commit` / `--no-git-commit` | `True` | Automatically create a local git commit for each processed episode |
| `--log-file PATH` | `tools/runs/batch.log` | Destination path for the structured log file |

---

## Wiki Structure & Writing Lore

Content lives in [`content/`](content/):

| Folder                | What it holds                                                         |
| --------------------- | --------------------------------------------------------------------- |
| `content/characters/` | On-air anchors, correspondents, contributors, and guests (e.g. Munch, Crum, Case Blackwell) |
| `content/segments/`   | Recurring broadcast formats and desks (e.g. Munch & Crum, News, Hype Train) |
| `content/storylines/` | Multi-broadcast storylines and investigative sagas (e.g. Crum's Robotic Gorilla Groin Punch Bet, Beyblade Tournament) |
| `content/episodes/`   | Per-broadcast episode logs, rundowns, and candidate lore notes        |

- Use `[[wikilinks]]` between pages (e.g. `[[characters/munch|Munch]]`).
- Always cite timestamps when adding lore facts.
- Use `draft: true` in page frontmatter to prevent unfinished pages from publishing.

---

## Roadmap

- [x] Phase 0: Repo bootstrap, Quartz setup, GitHub Pages CI/CD, seed pages
- [x] Phase 1: VOD listing, audio download, local Whisper transcription, runs archive
- [x] Phase 2: LLM segment and lore extraction via Google AI Studio (Gemini free tier)
- [x] Phase 3: Unattended server batch pipeline (`binlore process-all`) with auto-cleanup & validation
- [ ] Automated git branch/PR generation for proposed wiki edits
- [ ] Broadcast screencap gallery and on-air graphic asset index

---

## License

MIT — see [LICENSE.txt](LICENSE.txt). Quartz is © jackyzha0; binlore tooling and customizations are © Thomas Davis. Wiki content is unofficial fan documentation for personal and non-commercial use.
