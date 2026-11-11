from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .paths import CONTENT_EPISODES, RUNS_DIR

GQL_URL = "https://gql.twitch.tv/gql"
# Public web-player client id; the chat replay endpoint needs no OAuth token.
GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
COMMENTS_QUERY_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"

CHAT_FILENAME = "chat.json"


class ChatUnavailable(RuntimeError):
    """The Twitch VOD (and with it the chat replay) no longer exists."""


def chat_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / CHAT_FILENAME


def _comments_page(vod_id: str, *, cursor: str | None = None, offset: int = 0) -> dict:
    variables: dict = {"videoID": vod_id}
    if cursor:
        variables["cursor"] = cursor
    else:
        variables["contentOffsetSeconds"] = offset
    body = [
        {
            "operationName": "VideoCommentsByOffsetOrCursor",
            "variables": variables,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": COMMENTS_QUERY_HASH}},
        }
    ]
    req = urllib.request.Request(
        GQL_URL,
        data=json.dumps(body).encode(),
        headers={"Client-ID": GQL_CLIENT_ID, "Content-Type": "application/json"},
    )
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(2.0 * attempt)
    entry = payload[0] if isinstance(payload, list) else payload
    if entry.get("errors"):
        raise RuntimeError(f"Twitch GQL error for VOD {vod_id}: {entry['errors']}")
    video = (entry.get("data") or {}).get("video")
    if not video:
        raise ChatUnavailable(f"Twitch VOD {vod_id} is gone (expired or deleted); its chat replay is unavailable.")
    return video["comments"] or {"edges": [], "pageInfo": {"hasNextPage": False}}


def _message_from_node(node: dict) -> dict:
    commenter = node.get("commenter") or {}
    message = node.get("message") or {}
    text = "".join(frag.get("text") or "" for frag in message.get("fragments") or [])
    badges = [b.get("setID") for b in message.get("userBadges") or [] if b.get("setID")]
    return {
        "id": node.get("id"),
        "t": int(node.get("contentOffsetSeconds") or 0),
        "user": commenter.get("displayName") or commenter.get("login") or "",
        "login": commenter.get("login") or "",
        "text": text.strip(),
        "badges": badges,
    }


def fetch_chat(vod_id: str, *, progress: bool = False) -> list[dict]:
    """Download the complete chat replay for a Twitch VOD, oldest message first."""
    # Cursor paging is gated behind a browser integrity token, so walk the VOD by
    # content offset instead and de-duplicate the overlap between pages.
    messages: list[dict] = []
    seen: set[str] = set()
    offset = 0
    while True:
        page = _comments_page(vod_id, offset=offset)
        edges = page.get("edges") or []
        new = 0
        for edge in edges:
            msg = _message_from_node(edge.get("node") or {})
            if msg["id"] in seen:
                continue
            seen.add(msg["id"])
            messages.append(msg)
            new += 1
        if progress and messages:
            t = messages[-1]["t"]
            print(f"\r  {len(messages)} messages, at {t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}", end="", flush=True)
        if not edges or not (page.get("pageInfo") or {}).get("hasNextPage"):
            break
        last_t = max(_message_from_node(e.get("node") or {})["t"] for e in edges)
        offset = last_t if new and last_t > offset else max(offset, last_t) + 1
        time.sleep(0.15)
    if progress:
        print()
    messages.sort(key=lambda m: m["t"])
    return messages


def archive_chat(vod_id: str, run_id: str | None = None, *, force: bool = False, progress: bool = False) -> Path:
    """Save a VOD's chat replay to tools/runs/<run_id>/chat.json (skips if already archived)."""
    out = chat_path(run_id or vod_id)
    if out.exists() and not force:
        return out
    messages = fetch_chat(vod_id, progress=progress)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"vod_id": vod_id, "message_count": len(messages), "messages": messages}, ensure_ascii=False, indent=1)
        + "\n"
    )
    return out


def load_chat(run_id: str) -> list[dict]:
    path = chat_path(run_id)
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("messages") or []


REPORT_FILENAME = "chat-report.md"

# Accounts whose messages are bot replies, not audience chat.
BOT_USERS = {"caseblackwell", "nightbot", "streamelements", "streamlabs", "moobot", "fossabot", "sery_bot"}
WIKI_EDITOR_USERS = {"teflonted"}

# Chat commands that route a viewer's message somewhere on the show.
COMMANDS = {
    "!lore": "lore submission",
    "!c": "thought queue",
    "!tts": "thought queue",
    "!mc": "thought queue (poll)",
    "!ct": "community thought",
    "!th": "thought",
    "!h": "therapy question",
    "!pc": "press conference question",
    "!trip": "Trip on the Street opinion",
    "!cc": "Encircled counter claim",
}

WIKI_RE = re.compile(
    r"\bwiki\b|\blore\b|binlore|\bbin ?lore\b|lore ?bot|\b(?:a|new|own|wiki) page\b|\bpage for\b|\bcanon(?:ical)?\b|\bbio\b",
    re.I,
)
QUESTION_CUE_RE = re.compile(
    r"^(?:who|what|why|when|where|how|is|are|was|were|did|does|do|can|could|will|would|has|have|should)\b"
    r"|\b(?:who is|who's|what is|what's|what happened|whatever happened|is that|was that|remember when|does anyone know)\b",
    re.I,
)
SUGGESTION_RE = re.compile(
    r"\b(?:you should|we should|case should|should (?:do|have|get|bring|make)|can we (?:get|have|do|see)|"
    r"could we|we need|need(?:s)? (?:a|an|more|to)|bring back|how about|what if|next time|"
    r"suggest(?:ion)?|idea:|segment idea|please (?:do|make|bring|add)|make (?:a|an) (?:segment|song|page|character)|"
    r"i (?:want|wanna) (?:a|an|to see|more)|do a\b)",
    re.I,
)
# Generic page names that would match ordinary chatter.
GENERIC_ENTITY_NAMES = {"news", "banter", "gaming", "intern", "the news", "music", "chat"}


def _fmt_ts(seconds: int) -> str:
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _wiki_entities() -> list[tuple[str, str, re.Pattern]]:
    """(wiki link target, display name, matcher) for every character, segment, and storyline page."""
    import yaml

    from .paths import CONTENT_CHARACTERS, CONTENT_SEGMENTS, CONTENT_STORYLINES

    entities = []
    for folder in (CONTENT_CHARACTERS, CONTENT_SEGMENTS, CONTENT_STORYLINES):
        for page in sorted(folder.glob("*.md")):
            if page.stem == "index":
                continue
            m = re.match(r"^---\n(.*?)\n---", page.read_text(encoding="utf-8"), re.DOTALL)
            fm = (yaml.safe_load(m.group(1)) or {}) if m else {}
            title = str(fm.get("title") or page.stem)
            display = str(fm.get("common_name") or re.sub(r"\s*\(.*?\)\s*", " ", title).strip())
            names = {title, display, re.sub(r"\s*\(.*?\)\s*", " ", title).strip(), *map(str, fm.get("aliases") or [])}
            alternatives = []
            for name in names:
                name = name.strip()
                if len(name) < 3 or name.lower() in GENERIC_ENTITY_NAMES:
                    continue
                escaped = re.escape(name)
                # Short names ("Ten", "Tub", "Jan") only count when capitalised.
                alternatives.append(escaped if len(name) <= 4 else f"(?i:{escaped})")
            if not alternatives:
                continue
            pattern = re.compile(r"(?<![\w@])(?:" + "|".join(sorted(alternatives, key=len, reverse=True)) + r")(?!\w)")
            entities.append((f"{folder.name}/{page.stem}", display, pattern))
    return entities


def classify_chat(messages: list[dict], entities: list[tuple[str, str, re.Pattern]] | None = None) -> dict:
    """Sort audience chat into wiki/lore talk, questions, suggestions, routed commands, and page references."""
    entities = entities if entities is not None else _wiki_entities()
    out: dict = {"wiki": [], "editor": [], "questions": [], "suggestions": [], "commands": {}, "references": {}}
    for msg in messages:
        login = (msg.get("login") or msg.get("user") or "").lower()
        text = msg.get("text") or ""
        if not text or login in BOT_USERS:
            continue
        first = text.split()[0].lower()
        command = first if first in COMMANDS else None
        body = text[len(first):].strip() if command else text
        if login in WIKI_EDITOR_USERS:
            if WIKI_RE.search(text):
                out["editor"].append(msg)
        elif command == "!lore" or WIKI_RE.search(text) or any(f"@{u}" in text.lower() for u in WIKI_EDITOR_USERS):
            out["wiki"].append(msg)
        if command and command != "!lore" and body:
            out["commands"].setdefault(command, []).append(msg)
        elif not command and not text.startswith("!") and login not in WIKI_EDITOR_USERS:
            words = len(body.split())
            if "?" in body and words >= 3 and QUESTION_CUE_RE.search(body):
                out["questions"].append(msg)
            elif words >= 4 and SUGGESTION_RE.search(body):
                out["suggestions"].append(msg)
        for target, display, pattern in entities:
            if pattern.search(body):
                out["references"].setdefault(target, {"display": display, "messages": []})["messages"].append(msg)
    return out


def write_chat_report(slug: str, vod_id: str, run_id: str, *, max_refs: int = 4) -> Path | None:
    """Render tools/runs/<run_id>/chat-report.md from the archived chat; None when no chat is archived."""
    messages = load_chat(run_id)
    if not messages:
        return None
    result = classify_chat(messages)
    vod_url = f"https://www.twitch.tv/videos/{vod_id}"

    def line(msg: dict) -> str:
        text = (msg.get("text") or "").replace("|", "\\|").replace("\n", " ")
        return f"- [{_fmt_ts(msg['t'])}]({vod_url}?t={msg['t'] // 3600}h{msg['t'] % 3600 // 60}m{msg['t'] % 60}s) **{msg['user']}**: {text}"

    audience = sum(1 for m in messages if (m.get("login") or "").lower() not in BOT_USERS)
    parts = [
        f"# Chat report: {slug}",
        "",
        f"[Episode page](../../../content/episodes/{slug}.md) · [Twitch VOD]({vod_url}) · {audience} audience messages",
        "",
    ]
    sections = [
        ("Wiki & lore talk", result["wiki"], "Mentions of the wiki, lore, or pages, `!lore` submissions, and messages addressed to the wiki editor."),
        ("Wiki editor notes", result["editor"], "Wiki-related notes from the wiki editor's own account."),
        ("Questions", result["questions"], "Audience questions (plain chat, not command submissions)."),
        ("Suggestions", result["suggestions"], "Ideas and requests for the show."),
    ]
    for title, msgs, blurb in sections:
        parts += [f"## {title} ({len(msgs)})", "", blurb, ""]
        parts += [line(m) for m in msgs] or ["_None._"]
        parts.append("")

    parts += ["## Command submissions", ""]
    if result["commands"]:
        for command, msgs in sorted(result["commands"].items(), key=lambda kv: -len(kv[1])):
            parts += [f"### `{command}`: {COMMANDS[command]} ({len(msgs)})", ""]
            parts += [line(m) for m in msgs]
            parts.append("")
    else:
        parts += ["_None._", ""]

    refs = sorted(result["references"].items(), key=lambda kv: -len(kv[1]["messages"]))
    parts += [f"## Wiki page references ({len(refs)} pages)", ""]
    for target, info in refs:
        msgs = info["messages"]
        parts += [f"### [{info['display']}](../../../content/{target}.md) ({len(msgs)})", ""]
        parts += [line(m) for m in msgs[:max_refs]]
        if len(msgs) > max_refs:
            parts.append(f"- _…and {len(msgs) - max_refs} more_")
        parts.append("")

    out = RUNS_DIR / run_id / REPORT_FILENAME
    out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return out


DIGEST_PATH = RUNS_DIR / "chat-digest.md"


def write_chat_digest(episodes: list[tuple[str, str, str]]) -> Path:
    """Cross-episode inbox of wiki & lore talk and editor notes, newest episode first."""
    entities = _wiki_entities()
    parts = [
        "# Chat digest: wiki & lore",
        "",
        "Wiki and lore mentions, `!lore` submissions, and wiki editor notes from every archived Twitch chat, newest episode first. "
        "Per-episode questions, suggestions, and page references live in each run's `chat-report.md`.",
        "",
    ]
    for slug, vod_id, run_id in sorted(episodes, key=lambda e: e[0], reverse=True):
        messages = load_chat(run_id)
        if not messages:
            continue
        result = classify_chat(messages, entities)
        picked = sorted(result["wiki"] + result["editor"], key=lambda m: m["t"])
        if not picked:
            continue
        vod_url = f"https://www.twitch.tv/videos/{vod_id}"
        parts += [f"## [{slug}](../../content/episodes/{slug}.md) ([report]({run_id}/{REPORT_FILENAME}))", ""]
        for msg in picked:
            t = msg["t"]
            text = (msg.get("text") or "").replace("\n", " ")
            parts.append(f"- [{_fmt_ts(t)}]({vod_url}?t={t // 3600}h{t % 3600 // 60}m{t % 60}s) **{msg['user']}**: {text}")
        parts.append("")
    DIGEST_PATH.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return DIGEST_PATH


def twitch_episodes() -> list[tuple[str, str, str]]:
    """(episode slug, vod_id, run_id) for every episode page backed by a Twitch VOD."""
    out = []
    for page in sorted(CONTENT_EPISODES.glob("*.md")):
        head = page.read_text().split("\n---", 1)[0]
        vod = re.search(r'^vod_id:\s*"?(\d+)"?\s*$', head, re.M)
        if not vod:
            continue
        run = re.search(r'^run_id:\s*"?([^"\n]+)"?\s*$', head, re.M)
        out.append((page.stem, vod.group(1), run.group(1).strip() if run else vod.group(1)))
    return out
