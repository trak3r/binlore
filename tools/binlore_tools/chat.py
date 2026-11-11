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


def _comments_page(vod_id: str, *, offset: int = 0) -> dict:
    body = [
        {
            "operationName": "VideoCommentsByOffsetOrCursor",
            "variables": {"videoID": vod_id, "contentOffsetSeconds": offset},
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
DIGEST_PATH = RUNS_DIR / "chat-digest.md"

# Accounts whose messages are bot replies, not audience chat.
BOT_USERS = {"caseblackwell", "nightbot", "streamelements", "streamlabs", "moobot", "fossabot", "sery_bot"}
WIKI_EDITOR_USERS = {"teflonted"}

CHAT_WIKI_RE = re.compile(
    r"\bwiki|binlore|\bbin ?lore\b|lore ?bot|\b(?:a|new|own|dedicated|wiki|bio) page\b|\bpage (?:for|about)\b|"
    r"\bbio\b|\blore\b|^!lore\b",
    re.I,
)
# Whisper renders "BIN Lore bot" as "Ben Lorbott" and similar.
ON_AIR_WIKI_RE = re.compile(r"\bwiki|binlore|\bbin ?lore\b|\bben ?lor(?:e|bot)|lore ?bot", re.I)
REQUEST_RE = re.compile(
    r"\b(?:make|create|add|update|write|start|need|needs|deserve|deserves|give|gets?|getting)\b.{0,50}"
    r"\b(?:page|wiki|bio|lore)\b|\b(?:add|put) (?:this|that|it|him|her|them)\b|^!lore\b",
    re.I,
)

CHAT_BEFORE_SECONDS = 60
CHAT_BEFORE_MAX = 6
CHAT_AFTER_SECONDS = 30
CHAT_AFTER_MAX = 4
ON_AIR_BEFORE_SECONDS = 30
ON_AIR_AFTER_SECONDS = 8
THREAD_GAP_SECONDS = 90


def _fmt_ts(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _vod_link(vod_id: str, seconds: float) -> str:
    s = max(0, int(seconds))
    return f"https://www.twitch.tv/videos/{vod_id}?t={s // 3600}h{s % 3600 // 60}m{s % 60}s"


def _load_transcript(run_id: str) -> list[dict]:
    path = RUNS_DIR / run_id / "transcript.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("segments", []) if isinstance(data, dict) else data


def _kind(text: str) -> str:
    if REQUEST_RE.search(text):
        return "request"
    if "?" in text:
        return "question"
    return "mention"


def wiki_threads(messages: list[dict], transcript: list[dict]) -> list[dict]:
    """Group wiki mentions (chat and on-air) into threads with the surrounding chat and on-air context."""
    chat = [m for m in messages if (m.get("login") or "").lower() not in BOT_USERS and m.get("text")]
    hits: list[dict] = []
    for i, msg in enumerate(chat):
        text = msg["text"]
        to_editor = any(f"@{u}" in text.lower() for u in WIKI_EDITOR_USERS) and len(text.split()) >= 5
        if CHAT_WIKI_RE.search(text) or to_editor:
            hits.append({"t": msg["t"], "source": "chat", "index": i, "kind": _kind(text)})
    for seg in transcript:
        if ON_AIR_WIKI_RE.search(seg.get("text") or ""):
            hits.append({"t": seg["start"], "source": "on air", "kind": _kind(seg["text"])})
    hits.sort(key=lambda h: h["t"])

    threads: list[dict] = []
    for hit in hits:
        if threads and hit["t"] - threads[-1]["end"] <= THREAD_GAP_SECONDS:
            threads[-1]["hits"].append(hit)
            threads[-1]["end"] = hit["t"]
        else:
            threads.append({"start": hit["t"], "end": hit["t"], "hits": [hit]})

    for thread in threads:
        start, end = thread["start"], thread["end"]
        before = [m for m in chat if start - CHAT_BEFORE_SECONDS <= m["t"] < start][-CHAT_BEFORE_MAX:]
        during = [m for m in chat if start <= m["t"] <= end]
        after = [m for m in chat if end < m["t"] <= end + CHAT_AFTER_SECONDS][:CHAT_AFTER_MAX]
        hit_ids = {id(chat[h["index"]]) for h in thread["hits"] if h["source"] == "chat"}
        thread["chat"] = [{**m, "hit": id(m) in hit_ids} for m in before + during + after]
        thread["on_air"] = [
            s for s in transcript if start - ON_AIR_BEFORE_SECONDS <= s["start"] <= end + ON_AIR_AFTER_SECONDS
        ]
        kinds = {h["kind"] for h in thread["hits"]}
        thread["kind"] = next(k for k in ("request", "question", "mention") if k in kinds)
        thread["on_air_hit"] = any(h["source"] == "on air" for h in thread["hits"])
    return threads


def _render_threads(threads: list[dict], vod_id: str, heading: str = "##") -> list[str]:
    parts: list[str] = []
    for thread in threads:
        first = next((m for m in thread["chat"] if m["hit"]), None)
        if first:
            headline = f"{first['user']}: {first['text']}"
        else:
            seg = next(s for s in thread["on_air"] if ON_AIR_WIKI_RE.search(s.get("text") or ""))
            headline = f"on air: {seg['text'].strip()}"
        headline = headline.replace("\n", " ")
        if len(headline) > 110:
            headline = headline[:107] + "…"
        source = " · on air" if thread["on_air_hit"] else ""
        parts += [
            f"{heading} [{_fmt_ts(thread['start'])}]({_vod_link(vod_id, thread['start'] - 20)}) · {thread['kind']}{source} · {headline}",
            "",
        ]
        if thread["on_air"]:
            said = " ".join((s.get("text") or "").strip() for s in thread["on_air"])
            parts += [f"> **On air ({_fmt_ts(thread['on_air'][0]['start'])}):** {said}", ""]
        for msg in thread["chat"]:
            text = msg["text"].replace("\n", " ")
            line = f"`{_fmt_ts(msg['t'])}` {msg['user']}: {text}"
            parts.append(f"- **{line}**" if msg["hit"] else f"- {line}")
        parts.append("")
    return parts


def write_chat_report(slug: str, vod_id: str, run_id: str) -> Path | None:
    """Render tools/runs/<run_id>/chat-report.md: wiki mentions with context; None when no chat is archived."""
    messages = load_chat(run_id)
    if not messages:
        return None
    threads = wiki_threads(messages, _load_transcript(run_id))
    counts = {k: sum(1 for t in threads if t["kind"] == k) for k in ("request", "question", "mention")}
    parts = [
        f"# Wiki mentions in chat: {slug}",
        "",
        f"[Episode page](../../../content/episodes/{slug}.md) · [Twitch VOD](https://www.twitch.tv/videos/{vod_id}) · "
        f"{counts['request']} requests, {counts['question']} questions, {counts['mention']} mentions",
        "",
        "Each entry is a moment where chat or the broadcast mentioned the wiki or lore. Matching messages are bold; "
        "the surrounding chat and what was being said on air give the context.",
        "",
    ]
    parts += _render_threads(threads, vod_id) or ["_No wiki mentions._", ""]
    out = RUNS_DIR / run_id / REPORT_FILENAME
    out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return out


def write_chat_digest(episodes: list[tuple[str, str, str]]) -> Path:
    """Cross-episode inbox of wiki requests and questions with context, newest episode first."""
    parts = [
        "# Chat digest: wiki requests & questions",
        "",
        "Wiki requests and questions from every archived Twitch chat (and the broadcast itself), newest episode first. "
        "Plain mentions are in each episode's report.",
        "",
    ]
    for slug, vod_id, run_id in sorted(episodes, key=lambda e: e[0], reverse=True):
        messages = load_chat(run_id)
        if not messages:
            continue
        threads = [t for t in wiki_threads(messages, _load_transcript(run_id)) if t["kind"] != "mention"]
        if not threads:
            continue
        parts += [f"## [{slug}](../../content/episodes/{slug}.md) ([full report]({run_id}/{REPORT_FILENAME}))", ""]
        parts += _render_threads(threads, vod_id, heading="###")
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
