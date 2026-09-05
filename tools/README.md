# Binlore tools

VOD ingest, transcript archiving, and LLM-assisted lore extraction for the Binlore wiki.

## Setup

```bash
# System dependencies (once)
brew install yt-dlp ffmpeg

# Python virtual environment
cd tools
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### OpenRouter API Key (for Lore Extraction)

To use `binlore extract` with OpenRouter (including free models):

1. Get a free API key at [https://openrouter.ai/keys](https://openrouter.ai/keys).
2. Create a `tools/.env` file (gitignored):
   ```bash
   OPENROUTER_API_KEY=sk-or-v1-your-key-here
   ```
   *(Or export it in your shell: `export OPENROUTER_API_KEY=sk-or-v1-...`)*

## Commands

### 1. List recent VODs

```bash
binlore vods
binlore vods --limit 10
```

### 2. Ingest stream audio & generate transcript (Whisper)

```bash
# Ingest the latest stream
binlore ingest --latest

# Ingest a specific VOD URL or ID
binlore ingest "https://www.twitch.tv/videos/2863722826"

# Choose whisper model size (default: small; options: tiny, base, small, medium, large-v3)
binlore ingest --latest --model small
```

**Artifacts created in `tools/runs/<vod-id>/`:**
- `audio.m4a` (gitignored)
- `meta.json` (duration, air date, title, VOD ID)
- `transcript.json` (full timestamped segment list)
- `transcript.txt` (timestamped text)
- `transcript.plain.txt` (raw text)
- Initial episode stub in `content/episodes/YYYY-MM-DD.md`

### 3. Extract segments, characters & lore (OpenRouter LLM)

```bash
# Preview prompt & token estimate without sending API request
binlore extract --latest --dry-run

# Extract lore from the latest ingested VOD using default free model (openrouter/free)
binlore extract --latest

# Extract for a specific VOD ID
binlore extract 2863722826

# Specify a specific free or paid OpenRouter model
binlore extract --latest --model minimax/minimax-m3:free
binlore extract --latest --model google/gemma-4-31b-it:free
```

### 4. Propagate lore into the wiki (`binlore update-wiki`)

Once `extraction.json` is generated, push the data across the whole wiki:

```bash
# Preview what will be updated without modifying files
binlore update-wiki --latest --dry-run

# Update character appearance tables, notable moments, and storyline beats
binlore update-wiki --latest

# Or update for a specific VOD
binlore update-wiki 2863722826
```

**What this updates:**
- `content/characters/<name>.md`: Appends rows to `## Appearances` and adds timestamped bullets to `## Notable moments` with links back to the episode.
- Auto-creates pages for new on-air personas (e.g. `hyper-train.md`, `skynce.md`) and updates `content/characters/index.md`.
- `content/storylines/<slug>.md`: Appends beat developments to `## Key beats` timeline.
- `content/segments/<slug>.md`: Appends occurrences to `## Known occurrences`.

### 5. Extract screencaps (`binlore screencap`)

Extract high-quality video frames using `ffmpeg` without downloading the full video:

```bash
# Capture key frames for all detected characters & segments in latest VOD
binlore screencap --latest

# Capture specific timestamp and name
binlore screencap 2863722826 --timestamp 01:14:00 --name crum

# Capture and upload directly to GitHub release 'media-assets'
binlore screencap --latest --upload
```

### 6. Reclaim disk space (`binlore clean`)

Audio files take ~150 MB per 2-hour stream. Once transcribed, you can delete the raw audio/media files while keeping all transcripts, metadata, and wiki entries:

```bash
# Preview what would be deleted and total disk space freed
binlore clean --dry-run

# Delete media across all completed runs
binlore clean

# Keep media for the N most recent runs and delete older ones
binlore clean --keep 1

# Delete media for a specific VOD
binlore clean 2863722826

# Force delete media even if transcription was aborted/incomplete
binlore clean --force
```

