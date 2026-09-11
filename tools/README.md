# Binlore tools

VOD ingest, transcript archiving, and LLM-assisted lore extraction for the Binlore wiki.

## Setup

### System dependencies

**Linux / Remote Server (Ubuntu / Debian):**
```bash
sudo apt update && sudo apt install -y ffmpeg
# yt-dlp is installed automatically via pip into the venv below.
# (Optional) To install yt-dlp system-wide:
# sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp
```

**macOS:**
```bash
brew install yt-dlp ffmpeg
```

### Python virtual environment

```bash
cd tools
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```
*(Running `pip install -e .` installs `faster-whisper`, `yt-dlp`, and `google-genai` into `.venv`.)*

### Environment configuration (`tools/.env`)

Copy the sample environment file:
```bash
cp .env.example .env
```

#### Google AI Studio API Key (extract only)

Transcription does not need a key. Extraction calls Gemini directly:

1. Get a free API key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey). Do not attach billing.
2. Set it in `tools/.env`:
   ```bash
   GEMINI_API_KEY=your-key-here
   ```
3. *(Optional)* Pin a model:
   ```bash
   GEMINI_MODEL=gemini-2.5-flash
   # GEMINI_MODEL=gemini-2.5-flash-lite
   ```

#### Hugging Face Token (Optional, Recommended for Remote Servers)

`faster-whisper` downloads model weights from Hugging Face Hub. Unauthenticated requests on remote server / VPS IP ranges may encounter download throttling or HTTP 429 rate-limit warnings.

1. Generate a free **Read** token at [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. Set it in `tools/.env`:
   ```bash
   HF_TOKEN=hf_your_token_here
   ```
This provides higher download speeds, avoids rate limits, and silences the unauthenticated HF Hub warning.

#### YouTube cookies (required on most VPS / datacenter IPs)

YouTube will refuse `yt-dlp` without a logged-in session (`Sign in to confirm you’re not a bot`). Twitch downloads are unaffected.

1. In a **throwaway** Google account, open a private/incognito window, log into YouTube, then go to `https://www.youtube.com/robots.txt` (keep only that tab).
2. Export `youtube.com` cookies with a Netscape cookies.txt extension ([yt-dlp cookie export notes](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)). Close the private window so the session is not rotated.
3. Copy the file to the harvester host as `tools/cookies.txt` (gitignored; auto-detected). Or set in `tools/.env`:
   ```
   YTDLP_COOKIES=cookies.txt
   ```
   On a Mac with a local browser instead:
   ```
   YTDLP_COOKIES_FROM_BROWSER=chrome
   ```
4. Re-export when downloads start failing again. Do not use your main Google account on a VPS.

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

### 3. Extract segments, characters & lore (Gemini)

```bash
# Preview prompt & token estimate without sending API request
binlore extract --latest --dry-run

# Extract lore from the latest ingested VOD (GEMINI_API_KEY required)
binlore extract --latest

# Extract for a specific VOD ID
binlore extract 2863722826

binlore extract --latest --model gemini-2.5-flash-lite
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
- Auto-creates pages only with `--create-characters` (default: queue unknown names to `tools/runs/unknown-characters.jsonl`).
- `content/storylines/<slug>.md`: not updated unless `--update-storylines` (corpus pass).
- `content/segments/<slug>.md`: Appends occurrences except fixture desks (News / pre-show).

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

### 7. Unattended batch processing (`binlore process-all`)

Process the entire historical backlog unattended with automatic audio cleanup, Quartz build validation, and git commits:

```bash
# Check status and remaining backlog
binlore process-all --status

# Preview next queue of episodes (dry-run)
binlore process-all --dry-run --limit 10

# Run unattended transcribe-all (default)
binlore transcribe-all

# Mine transcripts oldest-first after the corpus exists
binlore process-all --extract
```


