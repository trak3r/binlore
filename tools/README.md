# Binlore tools (Phase 1)

VOD ingest + full transcript archive for reprocessing later.

## Setup

```bash
# system deps (once)
brew install yt-dlp ffmpeg

# python env
cd tools
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Commands

```bash
# list recent VODs for caseblackwell
binlore vods
binlore vods --limit 10

# ingest latest (or a specific VOD URL)
binlore ingest --latest
binlore ingest "https://www.twitch.tv/videos/XXXXXXXX"
binlore ingest --latest --model small   # tiny|base|small|medium|large-v3
```

Artifacts land in `tools/runs/<vod-id>/` (gitignored audio; commit `meta.json` + transcripts if you want them in-repo later).

Episode stubs are written to `content/episodes/YYYY-MM-DD.md`.
