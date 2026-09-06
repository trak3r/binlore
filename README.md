# BIN Lore

Unofficial fan lore wiki for **[Barely Informed News](https://www.twitch.tv/caseblackwell)** — Case Blackwell's fictional news show stream on Twitch.

Tracks characters, segments, storylines, and episodes as streams happen. Built with [Quartz](https://quartz.jzhao.xyz/) and hosted on [GitHub Pages](https://trak3r.github.io/binlore/).

> **Legal Disclaimer:** Unofficial, non-commercial fan wiki and documentation project. Not affiliated with, endorsed by, or sponsored by Case Blackwell, Barely Informed News, or Twitch. All character names, likenesses, trademarks, and media assets belong to their respective copyright holders and are referenced under fair use (17 U.S.C. § 107) for commentary, criticism, and archival purposes. Not operated for profit. See [`content/disclaimer.md`](content/disclaimer.md) for full legal disclosures.

---

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
- **YouTube Archive IDs:** Twitch purges VODs after ~60 days. The complete historical backlog of 370+ streams is preserved on YouTube. For archived streams beyond Twitch's retention window, the YouTube video ID (e.g. `ZSjvjEED3KA`) shown on the episodes list can be passed directly to `./binlore ingest <id>`.

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
`tools/runs/` and all media files (`*.m4a`, `*.mp4`, etc.) are listed in `.gitignore` so large binary files and raw transcripts are never pushed to GitHub. The wiki pages in `content/` are the public, reviewed canon.

---

## Setup & Prerequisites

### 1. System Dependencies (Mac)

Install Node.js 22+ (for Quartz) and media tools (for VOD download and audio conversion):

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

### 4. OpenRouter API Key (for LLM Lore Extraction)

To extract segments, characters, and lore using OpenRouter (free models available):

1. Get a free API key at [https://openrouter.ai/keys](https://openrouter.ai/keys).
2. Create a `tools/.env` file (gitignored):
   ```bash
   OPENROUTER_API_KEY="sk-or-v1-your-key-here"
   ```
   _(Or export it in your shell: `export OPENROUTER_API_KEY="sk-or-v1-..."`)_

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

# Or ingest a specific VOD by URL or ID
./binlore ingest "https://www.twitch.tv/videos/2863722826"

# Optional: choose Whisper model size (default is 'small')
# Options: tiny, base, small, medium, large-v3
./binlore ingest --latest --model small
```

This creates the run folder in `tools/runs/<vod-id>/` and stubs an episode page in `content/episodes/YYYY-MM-DD.md`.

### Step 3: Extract Lore, Characters & Segments (OpenRouter LLM)

Run the LLM extraction pipeline over the transcript:

```bash
# Preview prompt & token counts without calling the API (dry-run)
./binlore extract --latest --dry-run

# Run extraction using the default free router (openrouter/free)
./binlore extract --latest

# Or specify a particular model (e.g. minimax-m3, nemotron) or timeout
./binlore extract --latest --model minimax/minimax-m3:free
./binlore extract 2863722826 --timeout 90
```

**What this does automatically:**

1. Loads current wiki canon (`content/characters/`, `content/segments/`, `content/storylines/`) so the model knows established characters (like Munch and Crum) and reconciles ASR phonetic errors (e.g. "Crumb" $\to$ "Crum").
2. Saves `tools/runs/<vod-id>/extraction.json`.
3. Populates `content/episodes/YYYY-MM-DD.md` with:
   - Stream overview
   - Segment rundown table (`| Start | End | Segment | Notes |`)
   - On-air characters detected (speaking vs mentioned) with Quartz wikilinks (`[[characters/crum|Crum]]`)
   - Storyline developments (`[[storylines/munch-crum-rivalry|Munch–Crum rivalry]]`)
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
- **New personas**: Automatically creates pages for newly detected on-air characters/personas (e.g. `hyper-train.md`, `skynce.md`) and indexes them in `content/characters/index.md`.
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
./binlore process-all
# Or directly via Python:
python3 tools/process_all.py
```

### What It Does per Episode

1. **Backlog Discovery:** Cross-references `tools/youtube_catalog.json` with `content/episodes/` to identify unprocessed streams.
2. **Audio Ingest & Resilient Fallback:** Downloads audio using `yt-dlp`. If a Twitch VOD has expired (Twitch retention is ~60 days), it automatically falls back to the permanent YouTube archive stream.
3. **Local Whisper Transcription:** Transcribes audio via `faster-whisper` (default model: `small`).
4. **Immediate Disk Cleanup:** **Deletes the audio file immediately** once transcription finishes and is saved. Peak disk usage is capped to at most *one* temporary audio file at any moment (~150 MB).
5. **Lore Extraction:** Sends the transcript and canon roster to OpenRouter (`openrouter/free` with automatic fallbacks) to extract segments, characters, storylines, and lore notes.
6. **Wiki Population:** Updates `content/episodes/<date>.md`, creates or updates character pages in `content/characters/`, updates segment occurrences in `content/segments/`, and storyline beat timelines in `content/storylines/`.
7. **Catalog Synchronization:** Regenerates `content/episodes/index.md` so the episode is marked `✓ Ingested` with links to both Twitch and YouTube archives.
8. **Fault-Tolerant Loop:** If an individual stream fails (e.g. video removed, network glitch), it cleans up any partial files, logs the failure, and automatically moves on to the next episode without stopping the batch.

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

# 2. Start the batch processor
./binlore process-all

# 3. Detach from the session: Press Ctrl+b, then press d
# The processor continues running in the background!

# 4. To reattach and view progress later:
tmux attach -t binlore
```

#### Option B: Using `nohup`

```bash
# Run in background and redirect stdout
nohup ./binlore process-all > tools/runs/batch_stdout.log 2>&1 &
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
# Ingested & Extracted:  5
# Remaining in Backlog:  371 (1.3% complete)
# Free Disk Space:       110.96 GB
# Next in queue:         2026-08-19 — Upsetting Wednesday News
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
| `--oldest-first` | `False` | Process backlog chronologically from oldest to newest (default: newest first) |
| `--model MODEL` | `small` | `faster-whisper` model: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--openrouter-model` | `openrouter/free` | OpenRouter model slug for lore extraction |
| `--delay SECONDS` | `5.0` | Cool-down sleep in seconds between episodes to respect API rate limits |
| `--timeout SECONDS` | `90.0` | Extraction timeout per model before trying fallback models |
| `--min-disk-gb GB` | `1.0` | Minimum free disk space in GB required before ingesting |
| `--status` | — | Display backlog progress and disk space, then exit |
| `--dry-run` | — | Preview the queue of unprocessed episodes without downloading or modifying files |
| `--keep-audio` | `False` | Retain audio files on disk (warning: consumes ~150 MB per episode) |
| `--skip-extract` | `False` | Download & transcribe only; skip OpenRouter extraction and wiki edits |
| `--no-clean-existing` | `False` | Do not sweep `tools/runs/` for old media files on startup |
| `--no-skip-drafts` | `False` | Do not skip episodes marked with `draft: true` |
| `--git-commit` | `False` | Automatically create a local git commit for each processed episode |
| `--build-quartz` | `False` | Run `npx quartz build` after completing the batch |
| `--log-file PATH` | `tools/runs/batch.log` | Destination path for the structured log file |

---

## Wiki Structure & Writing Lore

Content lives in [`content/`](content/):

| Folder                | What it holds                                                         |
| --------------------- | --------------------------------------------------------------------- |
| `content/characters/` | People and personas (e.g. Munch, Crum, Case Blackwell)                |
| `content/segments/`   | Recurring show formats and bits (e.g. Munch & Crum, News, Hype Train) |
| `content/storylines/` | Arcs spanning multiple streams (e.g. Munch–Crum rivalry)              |
| `content/episodes/`   | Per-stream episode notes and rundowns                                 |

- Use `[[wikilinks]]` between pages (e.g. `[[characters/munch|Munch]]`).
- Always cite timestamps when adding lore facts.
- Use `draft: true` in page frontmatter to prevent unfinished pages from publishing.

---

## Roadmap

- [x] Phase 0: Repo bootstrap, Quartz setup, GitHub Pages CI/CD, seed pages
- [x] Phase 1: VOD listing, audio download, local Whisper transcription, runs archive
- [x] Phase 2: LLM segment and lore extraction via OpenRouter free tier
- [ ] Automated git branch/PR generation for proposed wiki edits
- [ ] Optional: face-filter reference gallery and voice-FX matching

---

## License

Quartz framework code is licensed under [MIT](LICENSE.txt). Wiki content is unofficial fan documentation for personal and non-commercial use.
