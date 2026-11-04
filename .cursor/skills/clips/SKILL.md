---
name: clips
description: Find highlight-worthy moments in the latest processed Barely Informed News episode and turn the chosen one into a ready-to-post vertical short (TikTok, Instagram Reels, YouTube Shorts), and publish it to the BIN Lore YouTube channel (Public) or TikTok account (Everyone) when asked, then add it to the wiki's Clips sections. Use when the user types /clips, or asks for clips, highlights, reels, or shorts from an episode.
---

# Clips (Highlights / Reels / Shorts)

Two phases, with two user decisions:

1. **Propose**: read the latest episode, pitch exactly 3 candidate highlights with clickable VOD timestamp links, then STOP and wait for the user to pick.
2. **Produce**: cut the raw window (`clips make --raw`), then STOP and get the user's approval of the in and out points. Only then preview the 9:16 crop, render with `./binlore clips make`, polish `post.md`, and report the output folder.

Distribution is manual by default: the user uploads the files. Only post when the user explicitly asks you to (see Phases 3 and 4), and then **upload YouTube Shorts as Public and TikToks as Everyone**. After every publish, record the clip on the wiki (see "Wiki sync" at the end). Before stating a post's visibility, check it in Studio; the user changes visibility themselves.

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
- **Paid off**: ends on a punchline, reveal, or reaction. Cut right after the best punchline, not at the end of the exchange. Follow-up banter, a second weaker joke, or "what do you mean?" replies all go. When in doubt, end earlier. The user has trimmed every early clip down to the first big laugh: 30 seconds, not 45.
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

### 1. Raw cut for review (STOP for approval)

```bash
./binlore clips make <episode-date> --start 1:22:24 --end 1:23:05 --slug durf-dating-advice --raw
```

This downloads the window, detects shots, transcribes it with word timestamps, writes `raw.mp4` (the uncropped 16:9 window, exactly the in and out points the final clip will use), and prints the transcript with times. It does no cropping, captions, watermark or end card.

Before showing it to the user:

- Make the hook start within about 0.6 seconds (shift `--start`).
- End about 0.3 to 0.6 seconds after the punchline's last word, before the next word starts.
- Check that the tail is not mid-word. Whisper's timings drift by up to a second near cut edges, and it can pin a word that isn't audible to the last second of the clip. Confirm against the audio level:

  ```bash
  ffmpeg -loglevel error -sseof -2.5 -i raw.mp4 -vn -ac 1 -ar 1000 -f s16le - | python3 -c "import sys,array,math;a=array.array('h',sys.stdin.buffer.read());print(''.join(str(min(9,int(math.sqrt(sum(x*x for x in a[i:i+100])/100)/400))) for i in range(0,len(a)-99,100)))"
  ```

  This prints one digit per 0.1 seconds, from 0 (silence) to 9 (loud).

Then report the path to `raw.mp4`, its length, the first and last caption lines, and `shots.jpg`. Ask the user to watch it and approve or give new in and out points. **Do not crop or render until they approve.** Re-running `--raw` with new times re-slices; it's cheap.

### 2. Check the crop

The vertical clip is a 9:16 window cut from the 16:9 stream. `--crop-x` is the window's horizontal center as a fraction of the frame width: `0.5` is centered, lower moves left. On the main desk shot, the chat overlay sits on the right, and values around `0.45` to `0.5` frame the on-camera character without it. Other sets differ: on Trip on the Street the park-goer stands at about `0.36` and Trip at about `0.62`.

```bash
./binlore clips preview <episode-date> --at 1:22:30 --crop-x 0.47
```

This writes `tools/clips/previews/<date>-<HHMMSS>-x<crop>.jpg`: the full frame with the crop box drawn on it, next to the cropped portrait view. The portrait side shades the platform UI zones in red and outlines the caption band (blue) and watermark (white). Read the image. If the character's face isn't comfortably inside the box, adjust `--crop-x` and preview again.

Two-character bits (Trip on the Street, debates, interviews) cut between speakers who stand in different parts of the frame, so one crop can't hold both. `clips make` detects the camera cuts. It prints them and writes `shots.jpg`: one frame per shot, labeled with its time range, with a 0.1-step crop-x ruler under each. Read it and pass a per-shot schedule, where each `time=crop` entry holds until the next:

```bash
--crop-x "0.36,4.93=0.62,14.17=0.36,26.70=0.62"
```

### 3. Render

Run the same command as the raw cut, with the same `--start` and `--end` and without `--raw`, so the cached slice and transcript are reused:

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

Every render regenerates `post.md` from the title and hook, which overwrites hand-polished copy. Copy `post.md` aside before re-rendering a polished clip and restore it afterwards. Keep the new `Window` line, and re-read the copy against the new cut, since trimmed lines must not be quoted.

### 4. Review

Output goes to `tools/clips/<date>-<slug>/`:

| File | Purpose |
| --- | --- |
| `clip.mp4` | Final 1080x1920 H.264/AAC upload file |
| `raw.mp4` | Uncropped 16:9 cut from the `--raw` review step |
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
4. Polish `post.md`: the YouTube Shorts title must stay at 100 characters or fewer and keep `#Shorts`. Write the TikTok and Reels captions in the show's voice. Keep URLs out of the TikTok caption: links in TikTok captions aren't clickable, so it is just the hook, `(fan clip)` and hashtags.
5. Report the output folder path, the clip length, and the thumbnail (embed it as an image) to the user.

`tools/clips/` is gitignored except `tools/clips/assets/`. Never commit rendered clips.

## Phase 3: Publish to YouTube (only when asked)

The channel is the fan channel **BIN Lore** (binlorewiki@gmail.com), signed in to the user's Chrome. Every Short on it must match this standard, so a new upload looks like the existing ones (Munch `pLlQfMtdxJs`, Durf `YN2Iy3XGsSM`, cheese `4UPba5Z_K_g`):

| Field | Value |
| --- | --- |
| Visibility | **Public** |
| Title | YouTube Shorts title from `post.md` (ends in `#Shorts`, 100 characters max) |
| Description | YouTube description block from `post.md` |
| Thumbnail | `tools/clips/<date>-<slug>/thumbnail.jpg` |
| Audience | No, it's not made for kids |
| Paid promotion | Unchecked |
| Altered or synthetic content | No |
| Tags | Tags block from `post.md`: the base set (Barely Informed News, Case Blackwell, BIN Lore, comedy, funny, parody, improv) plus character, segment and topic tags |
| Video language | English (United States) |
| Title and description language | English (United States) |
| Caption certification | This content has never aired on television in the U.S. |
| Recording date | The episode date (shown in `post.md`) |
| License, category, comments, remixing | Leave the defaults (Standard YouTube License, Comedy, comments on, remixing allowed) |

Leave the external-links "one-time verification" notice alone; it can stay even after the channel is phone-verified.

### Steps

1. Open `https://studio.youtube.com` and click Create > Upload videos, then select `clip.mp4` (the file dialog trick below works here too).
2. On the Details page, set title, description and thumbnail ("Upload file"), answer the audience question, then click **Show more** and set paid promotion, AI disclosure, tags, both languages, caption certification and recording date.
3. Click through Video elements and Checks, choose **Public**, and Save.
4. Edit an existing video at `https://studio.youtube.com/video/<id>/edit`. Click **Save** (top right) after each group of changes and confirm the "Changes saved" toast before moving on. An accidental page reload discards anything unsaved.
5. Report the video id and Studio link, then run the wiki sync.

### Driving Chrome

The user has declined "Allow JavaScript from Apple Events", so Studio is driven with clicks and keystrokes, not page JavaScript.

- Navigate with AppleScript (wait about 8 to 10 seconds for Studio to load):
  `osascript -e 'tell application "Google Chrome" to set URL of active tab of front window to "https://studio.youtube.com/video/<id>/edit"'`
- Click with the computer-use tools against the Chrome app target. Take a fresh screenshot before every click: coordinate tokens go stale quickly, and screenshots can lag a second or two behind the page.
- Keystrokes must go through System Events, and **every keystroke script must activate Chrome and verify it is frontmost in the same script**. Otherwise keys can land in Cursor (this once pasted a file path into the chat and sent it):

  ```applescript
  tell application "Google Chrome" to activate
  delay 0.5
  tell application "System Events"
    set frontApp to name of first process whose frontmost is true
    if frontApp is not "Google Chrome" then error "Chrome not frontmost: " & frontApp
    keystroke "v" using {command down}
  end tell
  ```

  Assign `frontApp` first; testing `name of first process whose frontmost is true` inline raises error -1700. Run these with full permissions. If auto-review blocks one, retry the same call with smart-mode approval.
- Paste text by putting it on the clipboard first (`printf '%s' "..." | pbcopy`), then Cmd+V.
- Before pasting, confirm with a screenshot that the target field has focus. Activating Chrome can leave focus in the address bar, and computer-use clicks on text fields don't take it back. To pull focus into the page, click a blank part of the page, then Tab or Shift+Tab to the field. Don't use `computer_type` in Studio fields: it sets the text without firing input events, so the page ignores it.

### Field tricks

- **File dialogs (video and thumbnail):** enter the file's absolute path straight into the macOS picker; never navigate folders or run a long keystroke script (auto-review blocks those). The picker runs in its own process, so computer-use keys and `computer_type` never reach it; send each key with a one-line System Events call while Chrome is frontmost. Click the upload button, `pbcopy` the absolute path, bring Chrome to the front, then send Cmd+Shift+G, Cmd+A, Cmd+V, wait about 1.5 seconds, Return, confirm with a screenshot that the file is selected, Return:
  `osascript -e 'tell application "System Events" to keystroke "g" using {command down, shift down}'`
- **Keys inside Studio pages** (Tab, Shift+Tab, Cmd+V, Return) work with `computer_key` against the Chrome app target, with no script needed. Wait about a second before screenshotting; screenshots lag and can show focus where it was several keys ago.
- **Focus resets:** toggling a checkbox can send focus back to the top of the upload dialog (the feedback button). From there the tags input is about 43 Tabs away, so it's often faster to set tags on the video's edit page.
- **"We had trouble saving your video":** if the upload wizard's Save keeps failing, press Return to dismiss the alert, then navigate to `https://studio.youtube.com/channel/<channel>/videos/short` (Return accepts any "Leave site?" prompt). One of the retries may already have saved; check the row's visibility, then finish anything missing on the edit page.
- **Description:** clicking the description box does not move focus out of the title (a paste lands in the title). Tab from the title past the suggested-hashtag buttons, about 7 Tabs, until the description box shows the focus border, then paste. After pasting, Cmd+Up then Tab closes the hashtag dropdown.
- **Tags:** clicking the tags input does not focus it, and `computer_type` on its accessibility element doesn't register. After clicking the AI-use "No" radio, Tab about 12 times until the tags "Learn more" link has the focus ring, then one more Tab into the input. Confirm with a screenshot, then paste the comma-separated tags with a trailing comma; each becomes a chip.
- **Custom thumbnail limit:** after a few custom thumbnails in a day, "Upload file" opens a "One-time verification needed" prompt (phone verification). That's the user's call: press Cancel, keep the auto-generated frame, and tell the user the custom thumbnail can be set from the edit page once they verify.
- **Language dropdowns:** typing a name does not jump the list. Open the dropdown and click "English (United States)". If the list opens at the top instead of near "English", scroll it with `computer_scroll` (at most 20 per call; about 46 steps reach English).
- **Caption certification:** open the dropdown and click the second option, "This content has never aired on television in the U.S."
- **Recording date:** open the picker and click the day in the calendar. Never type into the date field: typing a date and pressing Return reloaded the page and lost unsaved changes.

## Phase 4: Publish to TikTok (only when asked)

The account is the fan account **@binlore.wiki** (signed in to the user's Chrome), uploaded through TikTok Studio on the web. The first post is Chet `7704398113158548749`.

| Field | Value |
| --- | --- |
| Who can see this post | **Everyone** (the default) |
| Description | TikTok block from `post.md` (no URLs) |
| Cover | Edit cover > Upload cover > `tools/clips/<date>-<slug>/thumbnail.jpg` |
| When to post | Now |
| Location | Empty |
| Allow users to | Comment and Reuse of content, both left checked |
| Disclose post content | Off |
| AI-generated content | Off |
| Audience control | Off |
| Content check lite | On (it reports "No issues found") |
| High-quality uploads, music copyright check | Leave the defaults |

### Steps

1. Open the upload page with the red upload button at the top of the Studio sidebar (`https://www.tiktok.com/tiktokstudio/upload`), click Select video, and enter the absolute path of `clip.mp4` in the file picker (same trick as YouTube). Dismiss any "Got it" tips.
2. Replace the description (it defaults to the file name, `clip`) with the TikTok caption.
3. Confirm with a screenshot that **Who can see this post** reads Everyone. If it doesn't, change it with the dropdown trick below.
4. Set the cover, click Show more, and check the toggles in the table.
5. Scroll to the bottom and click **Post**. Studio opens `https://www.tiktok.com/tiktokstudio/content`, where the new row shows "Everyone" and "Content under review" for a few minutes.
6. Read the post URL from that row with `computer_app_state`: the description is a link to `https://www.tiktok.com/@binlore.wiki/video/<id>`. Report it, then run the wiki sync.

### TikTok field tricks

- **Who can see this post:** it defaults to Everyone, so normally leave it alone. To change it, note that computer-use clicks on this dropdown go to its text label and never open it, whether you click the text, the arrow, or the padding. Open it from the keyboard instead: get focus into the page just above it, then send Tab through System Events one key at a time, screenshotting after each, until the dropdown shows a dark focus border. Then press Space to open it and click the option you need. The order is description, two invisible stops, the Location box (it gets a border), one or two invisible stops for the When-to-post radios, then the dropdown. Never press Space until the border is on the dropdown: with focus in the description it types a space. Blank-page clicks don't reliably set the starting point (Tab sometimes jumps to the sidebar), so start right after pasting the caption, while focus is still in the description.
- **Description:** while it still reads `clip`, a computer-use click in the box focuses it. Once it has text, clicks go to the text label and don't focus it. Then Cmd+A and Cmd+V through System Events, in one script that checks Chrome is frontmost (the first paste after a click sometimes doesn't land; check the character counter). A hashtag suggestion list opens under the last tag; press Escape to close it without picking one, which keeps focus in the description for the Tab route to the visibility dropdown (about six Tabs).
- **Cover:** Edit cover opens a dialog with a frame strip and an Upload cover button that opens the macOS picker. After the image loads, click Save (top right). The profile preview crops it to 4:3.
- **File picker timing:** the picker can take 2 to 3 seconds to open. Screenshot to confirm it is open before sending Cmd+Shift+G. If the path sheet is still showing after the script, press Return once more. The "Go to" suggestion can lag a screenshot behind the typed path.
- **Auto-review:** clicks on Select video and Post may be blocked; retry the same click with approval.
- Screenshots lag about a second, and the page scrolls itself after dialogs close; take a fresh screenshot before every click.

## Wiki sync (after every publish)

Published clips are listed in `data/clips.json`, which is tracked in git (the clip folders are not). `./binlore sync-clips` turns it into a generated `## Clips` section, a list of clip titles with YouTube and TikTok links, on the episode page and on every `characters/*` page in the clip's `wiki` list.

1. Add the clip to `data/clips.json`, or update its entry if it is already there. Copy `slug`, `episode`, `title` and `wiki` from the clip's `meta.json`, then set `youtube` (the video id), `tiktok` (the post id) and `tiktok_public`. A clip goes in once it has a YouTube id, because the YouTube link is always shown.
2. `tiktok_public` controls the TikTok link, which only appears when it is `true`, so the wiki never links to a private post. Set it to `true` for posts made as Everyone. When the user flips an old Only-you post, set it to `true` and sync again.
3. Run `./binlore sync-clips`. Then run it again: the second run must report 0 pages updated.
4. Commit `data/clips.json` and the changed pages on main. Push only when asked.

Never hand-edit the generated section between the `clips:start` and `clips:end` markers. Re-extracting an episode rewrites its page, so run `./binlore sync-clips` again afterwards.
