# YouTube Data API (BIN Lore Shorts)

`./binlore clips publish-youtube` uploads a rendered clip folder to the fan
channel **BIN Lore** without driving Chrome. Auth files in this directory are
gitignored.

## One-time setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create or pick a project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen (External is fine; add yourself as a test user while the app is in Testing).
4. Create credentials → **OAuth client ID** → Application type **Desktop app**.
5. Download the JSON and save it as:

   ```text
   tools/youtube_api/client_secret.json
   ```

6. Authorize as **`binlorewiki@gmail.com`** only (the BIN Lore channel account). This laptop
   likely has several Google logins; the command opens **Google Chrome** (not the system
   default browser), forces Google’s account picker, and pre-fills that email. If you pick
   the wrong account, auth **fails** and deletes the token instead of saving it:

   ```bash
   ./binlore clips youtube-auth
   ```

   That writes `tools/youtube_api/token.json` (also gitignored). Publish also re-checks
   that the token belongs to BIN Lore (`UCuiEeDV0bv5WS4FlpIdD_5Q`) before uploading.

## Publish

```bash
./binlore clips publish-youtube tools/clips/2026-11-14-jan-left-a-note/
# or
./binlore clips publish-youtube 2026-11-14-jan-left-a-note --dry-run
```

Defaults: **Public**, Comedy category, not made for kids, no synthetic-media
disclosure, no paid promotion, custom thumbnail after processing, then
`data/clips.json` + `./binlore sync-clips`.

## Notes

- There is no Shorts-specific API flag. Vertical ≤3‑minute uploads become Shorts automatically.
- Custom thumbnails need a phone-verified channel; if `thumbnails.set` fails, set the thumb in Studio later.
- Default API quota is 100 `videos.insert` calls per day — enough for this channel.
