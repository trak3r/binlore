# Binlore

Unofficial fan lore wiki for **[Barely Informed News](https://www.twitch.tv/caseblackwell)** — Case Blackwell's fictional news show stream on Twitch.

Tracks characters, segments, storylines, and episodes as streams happen. Built with [Quartz](https://quartz.jzhao.xyz/) and hosted on [GitHub Pages](https://trak3r.github.io/binlore/).

> Not affiliated with Case Blackwell or Barely Informed News. Fan project only.

---

## Where Downloaded VODs & Transcripts Live Locally

When you ingest a stream, all downloaded media and processed artifacts are saved in:

```
tools/runs/<vod-id>/
```

For example, for VOD `2863722826` (*High T Wednesday News*):
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
   *(Or export it in your shell: `export OPENROUTER_API_KEY="sk-or-v1-..."`)*

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

## Wiki Structure & Writing Lore

Content lives in [`content/`](content/):

| Folder | What it holds |
|--------|----------------|
| `content/characters/` | People and personas (e.g. Munch, Crum, Case Blackwell) |
| `content/segments/` | Recurring show formats and bits (e.g. Munch vs Crum debate) |
| `content/storylines/` | Arcs spanning multiple streams (e.g. Munch–Crum rivalry) |
| `content/episodes/` | Per-stream episode notes and rundowns |

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
