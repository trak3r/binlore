---
name: clips
description: Find highlight-worthy moments in the latest processed Barely Informed News episode and turn the chosen one into a ready-to-post vertical short (TikTok, Instagram Reels, YouTube Shorts). Use when the user types /clips, or asks for clips, highlights, reels, or shorts from an episode.
---

# Clips (Highlights / Reels / Shorts)

Two phases with a user decision in between:

1. **Propose**: read the latest episode, pitch exactly 3 candidate highlights with clickable VOD timestamp links, then STOP and wait for the user to pick one.
2. **Produce**: preview the 9:16 crop, render the chosen clip with `./binlore clips make`, polish `post.md`, and report the output folder.

Distribution is manual by default: the user uploads the files. Only post when the user explicitly asks you to (for example by driving Chrome, signed in as the fan channel binlorewiki@gmail.com), and then **always upload as Unlisted, never Public**. The user makes clips public themselves.

These are fan clips of someone else's show. Keep the fan-clip branding and the "Not affiliated with the show" line in post copy.

## Phase 1: Propose

### Find the episode

- Default to the latest episode: the newest `content/episodes/YYYY-MM-DD.md` (ignore `index.md`). If the user names a date or VOD, use that instead.
- Read its frontmatter for `vod_url`, `vod_id` and `run_id`, plus the rundown table, the Characters list, and the lore notes.
- Read the transcript at `tools/runs/<run_id>/transcript.txt`. Lines look like `[01:22:24 --> 01:22:26] text`. Use the rundown to find the segments with characters in them, then read those transcript stretches closely.

### Highlight rubric

A good candidate is:

- **Self-contained**: makes sense to a stranger with no context about the show. No setup from earlier in the stream is required.
- **Hooked in the first 3 seconds**: the opening line is funny, weird, or provocative on its own. Start ON the hook, not on the lead-in.
- **Paid off**: ends on a punchline, reveal, or reaction. Trim the trailing chatter after the laugh.
- **20 to 75 seconds long** (sweet spot 30 to 50).
- **Character-driven**: prefer Case's recurring characters (they have pages in `content/characters/`) and signature segments over Case speaking as himself.

Avoid:

- Straight news-reading, chat-reading, or tech trouble.
- Third-party media playing on stream (news footage, viral videos, movie clips, music). It is not ours, and it gets clips muted or struck.
- Raid shout-outs and moments that only work with the chat overlay visible.
- Anything that leans on private real-world people (see `.cursor/rules/character-pages.mdc`).

Verify start and end against the transcript lines. The episode transcript only has segment-level timestamps, and they can run several seconds early (on 2026-10-29 a line stamped 2:01:54 was actually spoken at 2:01:58.4). Treat them as approximate: the first `clips make` run gives word-accurate timing to tighten the window with (see Review).

### Output format

Present exactly 3 candidates, best first:

```markdown
### 1. <Punchy working title>
**Character/segment:** [[Durf]] on Amongst the Web
**Window:** 1:22:24 → 1:23:05 (41s)
**Hook (first line):** "<verbatim opening line>"
**Payoff:** <the punchline or reaction it lands on>
**Why it works:** <one sentence>
**Watch:** [Twitch @ 1:22:24](https://www.twitch.tv/videos/<vod_id>?t=1h22m24s) · [YouTube @ 1:22:24](https://www.youtube.com/watch?v=<yt_id>&t=4944s)
```

- Twitch links use `?t=XhYmZs`. YouTube links use `&t=<total seconds>s`. Only include YouTube when the episode or `tools/youtube_catalog.json` has a real YouTube id (11 characters, not all digits).
- Twitch VODs expire after a few weeks. If the episode is old, say so and lead with the YouTube link.

Then ask the user which one to make (use AskQuestion with the 3 titles), plus an option to adjust the timing. Do not render anything before they choose.

## Phase 2: Produce

### 1. Check the crop

The vertical clip is a 9:16 window cut from the 16:9 stream. `--crop-x` is the window's horizontal center as a fraction of the frame width: `0.5` is centered, lower moves left. On the main desk shot, the chat overlay sits on the right, and values around `0.45` to `0.5` frame the on-camera character without it. Other sets differ: on Trip on the Street the park-goer stands at about `0.36` and Trip at about `0.62`.

```bash
./binlore clips preview <episode-date> --at 1:22:30 --crop-x 0.47
```

This writes `tools/clips/previews/<date>-<HHMMSS>-x<crop>.jpg`: the full frame with the crop box drawn on it, next to the cropped portrait view. The portrait side shades the platform UI zones in red and outlines the caption band (blue) and watermark (white). Read the image. If the character's face isn't comfortably inside the box, adjust `--crop-x` and preview again.

Two-character bits (Trip on the Street, debates, interviews) cut between speakers who stand in different parts of the frame, so one crop can't hold both. `clips make` detects the camera cuts. It prints them and writes `shots.jpg`: one frame per shot, labeled with its time range, with a 0.1-step crop-x ruler under each. Read it and pass a per-shot schedule, where each `time=crop` entry holds until the next:

```bash
--crop-x "0.36,4.93=0.62,14.17=0.36,26.70=0.62"
```

### 2. Render

```bash
./binlore clips make <episode-date> \
  --start 1:22:24 --end 1:23:05 \
  --slug durf-dating-advice \
  --crop-x 0.47 \
  --title "Durf has dating advice for you" \
  --hook "Durf has never been on a date. He has notes anyway." \
  --wiki characters/durf --wiki segments/amongst-the-web \
  --tags durf,improv
```

- `<episode-date>` can also be a Twitch VOD id or URL, a YouTube URL, or `latest`.
- Downloads only the clip window (plus 1 second of padding on each side) from the Twitch HLS stream, falling back to YouTube when the Twitch VOD is gone. This takes about 10 seconds; the whole first run takes about 1 minute.
- Detects shot changes and writes `shots.jpg` (see above).
- Re-transcribes just the clip with word timestamps and burns in bold 2 to 4 word captions, highlighting the word being spoken.
- Adds the watermark (`tools/clips/assets/watermark.png`, falling back to the site icon), normalizes loudness, and appends the stinger (`tools/clips/assets/stinger.mp4`, or a generated end card). Use `--no-stinger` to skip it.
- Re-running with the same slug and window reuses the downloaded slice and transcript, so changing `--crop-x`, `--title` or `--fix` re-renders in about 35 seconds without network access. Changing `--start` or `--end` re-slices automatically. Omitted options (title, hook, wiki, tags, crop) carry over from the previous run.

Network access is needed for the download (run the command with full permissions).

### 3. Review

Output goes to `tools/clips/<date>-<slug>/`:

| File | Purpose |
| --- | --- |
| `clip.mp4` | Final 1080x1920 H.264/AAC upload file |
| `thumbnail.jpg` | Cover frame (change with `--thumb-at <seconds>`) |
| `captions.srt` | Plain captions, for platforms that accept a caption file |
| `shots.jpg` | One frame per detected shot, for building a crop schedule |
| `words.json` | Word-level transcript of the slice (includes the 1s lead pad), used for re-renders |
| `post.md` | Titles, captions and hashtags per platform, plus source links |
| `source.mp4`, `meta.json` | Cached slice and the settings of the last run |

Then:

1. Check the timing in `captions.srt`. The first caption (the hook) should start within about 0.6 seconds, and the last should be the payoff. If not, shift `--start`/`--end` by the difference and re-run.
2. Extract frames from `clip.mp4` with ffmpeg (one per shot when there's a crop schedule) and look at them to confirm framing and caption legibility.
3. Read `captions.srt` against the transcript. Whisper mishears character names, so fix obvious errors and re-run with `--fix "wrong=>right"` (repeatable; the transcript is reused).
4. Polish `post.md`: the YouTube Shorts title must stay at 100 characters or fewer and keep `#Shorts`. Write the TikTok and Reels captions in the show's voice.
5. Report the output folder path, the clip length, and the thumbnail (embed it as an image) to the user.

`tools/clips/` is gitignored except `tools/clips/assets/`. Never commit rendered clips.
