# Binlore

Unofficial fan lore wiki for **[Barely Informed News](https://www.twitch.tv/caseblackwell)** — Case Blackwell's fictional news show on Twitch.

Tracks characters, segments, storylines, and episodes as fans watch VODs. Built with [Quartz](https://quartz.jzhao.xyz/) and meant to publish on GitHub Pages.

> Not affiliated with Case Blackwell or Barely Informed News. Fan project only.

## Browse the wiki

Content lives in [`content/`](content/):

| Folder | What it holds |
|--------|----------------|
| `content/characters/` | People and personas (e.g. Munch, Crum) |
| `content/segments/` | Recurring bits (e.g. Munch vs Crum debate) |
| `content/storylines/` | Multi-episode arcs |
| `content/episodes/` | Per-VOD notes |

Page skeletons for new entries are in [`templates/`](templates/) (not published).

## Local preview

Requires **Node.js 22+**.

```bash
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"   # if needed on macOS Homebrew
npm ci
npx quartz build --serve
```

Open http://localhost:8080

## Publish (GitHub Pages)

1. Create an empty GitHub repo and set it as `origin` (keep Quartz upstream if you want upgrades):

   ```bash
   git remote rename origin upstream   # if still pointing at jackyzha0/quartz
   git remote add origin git@github.com:YOUR_USER/binlore.git
   ```

2. Set `baseUrl` in [`quartz.config.ts`](quartz.config.ts) to your Pages host, e.g. `youruser.github.io/binlore` (no `https://`).

3. In the repo **Settings → Pages**, set Source to **GitHub Actions**.

4. Push `main`. The [deploy workflow](.github/workflows/deploy.yml) builds Quartz and publishes.

## Editing lore

- Prefer wikilinks between pages, e.g. `[[characters/munch|Munch]]`
- Cite episode date + timestamp when you can
- Wrong lore is worse than missing lore — leave `_TBD_` or open questions when unsure
- Keep drafts out of publish with `draft: true` in frontmatter (Quartz removes drafts)

## Roadmap (later phases)

- VOD ingest (audio download + Whisper transcript)
- LLM segment/character extraction
- Proposed wiki edits via PR for human review

## License

Quartz framework code remains under its [MIT license](LICENSE.txt). Wiki content in `content/` is fan documentation for personal/non-commercial use unless otherwise noted.
