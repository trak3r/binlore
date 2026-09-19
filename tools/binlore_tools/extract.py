from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .canon import (
    format_canon_for_prompt,
    is_core_network_character,
    is_excluded_external_subject,
    load_wiki_canon,
)
from .paths import REPO_ROOT, RUNS_DIR, TOOLS_ROOT


def load_env() -> None:
    """Load .env from tools/.env or REPO_ROOT/.env if present."""
    for env_path in [TOOLS_ROOT / ".env", REPO_ROOT / ".env"]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key not in os.environ:
                    os.environ[key] = val


load_env()

# Capable model only. Never auto-fallback to weaker models — bad lore is worse than no lore.
# Default is an OpenRouter :free model so extract works without purchased credits.
DEFAULT_MODEL = (
    os.environ.get("OPENROUTER_MODEL")
    or os.environ.get("GEMINI_MODEL")  # legacy alias
    or "nvidia/nemotron-3-ultra-550b-a55b:free"
)
FALLBACK_MODELS: list[str] = []

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episode_summary": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "canonical_segment": {"type": "string"},
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "characters": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["start", "end", "canonical_segment", "title"],
            },
        },
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "canonical_name": {"type": "string"},
                    "speaking": {"type": "boolean"},
                    "timestamps": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["name", "speaking"],
            },
        },
        "storylines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "storyline": {"type": "string"},
                    "beat": {"type": "string"},
                    "timestamp": {"type": "string"},
                },
                "required": ["storyline", "beat"],
            },
        },
        "lore_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "fact": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["entity", "fact"],
            },
        },
    },
    "required": ["episode_summary", "segments", "characters"],
}


class DailyQuotaExceeded(RuntimeError):
    """Provider quota / credits exhausted; stop extracting until reset or top-up."""


SYSTEM_PROMPT = """You are the canon lore archivist for 'Barely Informed News' (BIN), documenting the network's broadcast archive (twitch.tv/caseblackwell).

CRITICAL TONE & KAYFABE:
Treat Barely Informed News as a real broadcast news network. Never break kayfabe.
Never say "is a character", "portrayed by", "played by Case", "face filter", "voice changer", "bit", or "persona".
Describe people by broadcast roles (anchor, correspondent, debate analyst, executive producer, legal counsel, call-in guest).
Treat glitches as control-room mix-ups or live studio events.

Do NOT describe clothing below the neck or generic studio equipment. Focus on unique facial features, character-defining props, and on-air behavior.

CHARACTERS vs EXTERNAL SUBJECTS:
Bio tracking is ONLY for on-air network figures who speak in studio scenes.
- Public figures and politicians (Trump, JD Vance, Mitch McConnell, Lindsey Graham, Pete Hegseth, etc.) who appear in news coverage are NOT characters.
- People in news clips, viral videos, or movie clips being watched are NOT characters.
- Twitch chatters and viewers are NOT characters (including Skymer; ASR often garbling the name as S.K.O.A.M.Y.R.).
- Stream raid recipients are NOT characters. Never name the other streamer's channel in overview, segment notes, or wrap-ups — if the broadcast ends with a raid, omit the destination.

CHARACTER NOTES (keep bios short):
- characters[].notes must be ONE short sentence for the Appearances index (role + what mattered this episode). No arc essays.
- Put multi-episode narrative in storylines[].beat, not in character notes.
- lore_notes are sparse durable traits/facts only (new gambling liability, physical transformation, standing rivalry beat). Skip generic jokes and one-offs.
- Prefer linking facts to Known Storylines when an arc already exists (e.g. Crum Dick Punch, Beyblade Tournament).

STORYLINES (overlapping threads):
- A single-episode incident is NOT a storyline.
- Storylines are multi-episode arcs that may overlap and intertwine; climactic events are bookmarks.
- Prefer Known Storylines from the roster. Use empty storylines[] unless the transcript clearly continues a Known Storyline or clearly advances a multi-episode arc.
- storylines[].beat: one concrete dated beat with optional timestamp — not a full recap.

ASR:
Whisper misspells names. Reconcile to the roster when possible:
Crumb/Crumble → Crum; Monch → Munch; Skynce/Chad → Chet; Chetah → ChetAI; Noggin → Nogget; Papita/Pepita → Pepito; S.K.O.A.M.Y.R./SKOAMYR → Skymer (viewer only — never a character).

Match canonical_segment and character names to the Existing Wiki Canon Roster in the user message. Do not invent desks or staff that are not in the roster or clearly on-air in this transcript.

TASK: Extract from the transcript:
1. segments — major blocks with start/end timestamps, canonical_segment from the roster, episode-specific title, notes
2. characters — on-air network figures (speaking or heavily discussed). Not news subjects. notes = one short sentence.
3. storylines — beats of known multi-episode arcs only
4. lore_notes — new canonical facts with an exact timestamp like "[49:58]". No generic one-off jokes.
5. episode_summary — 2-3 sentences, deadpan in-universe journalism

Respond with a single JSON object matching the schema. No markdown, no preamble.
"""


def get_api_key() -> str:
    load_env()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "\n[Error] OPENROUTER_API_KEY is not set.\n"
            "Lore extraction uses OpenRouter (OpenAI-compatible chat API).\n"
            "  1. Get a key at https://openrouter.ai/keys\n"
            "  2. Add it to tools/.env:\n"
            "       OPENROUTER_API_KEY=...\n"
            "  3. Optional model pin (default free: nvidia/nemotron-3-ultra-550b-a55b:free):\n"
            "       OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free\n"
            "There is no automatic fallback to weaker models.\n"
        )
    return key


def build_user_prompt(meta: dict[str, Any], canon_text: str, transcript_text: str) -> str:
    return f"""### Stream Metadata
- Title: {meta.get('title', 'Unknown')}
- Date: {meta.get('date', 'Unknown')}
- Duration: {meta.get('duration', 'Unknown')}
- URL: {meta.get('url', 'Unknown')}

### Existing Wiki Canon Roster
{canon_text}

### Stream Transcript (with timestamps)
{transcript_text}
"""


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse valid JSON from LLM response:\n{text[:500]}...")


def _is_daily_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "perday",
            "per day",
            "per_day",
            "daily quota",
            "rpd",
            "quota exceeded",
            "insufficient credits",
            "payment required",
        )
    )


def _is_rate_or_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "429",
            "rate limit",
            "rate-limit",
            "quota",
            "insufficient credits",
            "payment required",
            "402",
        )
    )


def _is_not_found_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg or "not_found" in msg or "no endpoints" in msg


def _parse_lore_note_string(raw: str) -> dict[str, Any] | None:
    """Coerce free-form lore strings into {timestamp, entity, fact}."""
    text = " ".join(str(raw).split()).strip()
    if not text:
        return None
    ts = ""
    m = re.match(r"^\[([^\]]+)\]\s*(.*)$", text)
    if m:
        ts = m.group(1).strip()
        text = m.group(2).strip()
    entity = ""
    # "Crum's blanket..." / "Pepito claims..." / "Dr. Chath is..."
    ent_m = re.match(
        r"^(Dr\.?\s+Chath|Peter Gibbon|Case Blackwell|Grandma Crumble Bottom|"
        r"Hype Train|AI Rooney|Trip Bradstein|Jeff Ripple|Jeb Nogget|"
        r"Crum|Munch|Pepito|Chet|Kendelle|Liliana|Rick|Steak|Tommy Biglaw|"
        r"Brandon|CryptoZeu\$?)\b[\s's]*",
        text,
        re.I,
    )
    if ent_m:
        entity = ent_m.group(1).strip()
    return {"timestamp": ts, "entity": entity, "fact": text, "confidence": 0.7}


def normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """
    Coerce provider-specific JSON drift into the binlore schema.
    Free models often emit lore_notes as strings and storyline.name instead of storyline.
    """
    # segments: keep dicts only
    segs: list[dict[str, Any]] = []
    for item in data.get("segments") or []:
        if isinstance(item, dict) and (item.get("title") or item.get("canonical_segment")):
            segs.append(item)
    data["segments"] = segs

    # characters: require name; default speaking=True when role/notes present
    chars: list[dict[str, Any]] = []
    for item in data.get("characters") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("canonical_name") or item.get("name") or "").strip()
        if not name:
            continue
        notes = str(item.get("notes") or "")
        role = str(item.get("role") or "").strip()
        if role and role.lower() not in notes.lower():
            notes = f"{role}. {notes}".strip() if notes else role
        speaking = item.get("speaking")
        if not isinstance(speaking, bool):
            speaking = True
        chars.append(
            {
                **item,
                "name": name,
                "canonical_name": str(item.get("canonical_name") or name),
                "speaking": speaking,
                "notes": notes,
                "timestamps": item.get("timestamps") if isinstance(item.get("timestamps"), list) else [],
                "confidence": float(item.get("confidence") or 0.8),
            }
        )
    data["characters"] = chars

    # storylines: accept name as alias for storyline
    stories: list[dict[str, Any]] = []
    for item in data.get("storylines") or []:
        if isinstance(item, str):
            text = item.strip()
            if text:
                stories.append({"storyline": text, "beat": text, "timestamp": ""})
            continue
        if not isinstance(item, dict):
            continue
        st_name = str(item.get("storyline") or item.get("name") or "").strip()
        beat = str(item.get("beat") or item.get("summary") or "").strip()
        if not st_name or not beat:
            continue
        ts = str(item.get("timestamp") or "")
        # Prefer timestamp embedded in beat like [01:06:24] or [2025-06-17]
        if not ts:
            tm = re.search(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", beat)
            if tm:
                ts = tm.group(1)
        stories.append({"storyline": st_name, "beat": beat, "timestamp": ts})
    data["storylines"] = stories

    # lore_notes: accept strings or dicts
    notes: list[dict[str, Any]] = []
    for item in data.get("lore_notes") or []:
        if isinstance(item, str):
            parsed = _parse_lore_note_string(item)
            if parsed:
                notes.append(parsed)
            continue
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or item.get("note") or item.get("text") or "").strip()
        if not fact and item.get("entity"):
            # sometimes models put the whole line in entity
            fact = str(item.get("entity") or "").strip()
        if not fact:
            continue
        notes.append(
            {
                "entity": str(item.get("entity") or item.get("character") or "").strip(),
                "fact": fact,
                "timestamp": str(item.get("timestamp") or item.get("time") or "").strip(),
                "confidence": float(item.get("confidence") or 0.7),
            }
        )
    data["lore_notes"] = notes
    return data


def validate_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """Fail closed: require the core schema, normalize drift, drop external news subjects."""
    if not isinstance(data, dict):
        raise ValueError("Extraction is not a JSON object")

    summary = data.get("episode_summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("extraction missing episode_summary")

    for key in ("segments", "characters", "storylines", "lore_notes"):
        value = data.get(key, [])
        if value is None:
            data[key] = []
            continue
        if not isinstance(value, list):
            raise ValueError(f"extraction.{key} must be a list")

    data = normalize_extraction(data)

    cleaned_chars: list[dict[str, Any]] = []
    for char in data.get("characters", []):
        if not isinstance(char, dict):
            continue
        name = str(char.get("canonical_name") or char.get("name") or "").strip()
        notes = str(char.get("notes") or "")
        if not name:
            continue
        if is_excluded_external_subject(name, notes):
            continue
        cleaned_chars.append(char)
    data["characters"] = cleaned_chars
    return data


def _resolve_host_ipv4(hostname: str) -> str:
    """Resolve hostname to IPv4; fall back to DNS-over-HTTPS when system DNS is blocked."""
    import socket
    import subprocess
    import urllib.error
    import urllib.request

    pinned = os.environ.get("BINLORE_OPENROUTER_IP", "").strip()
    if hostname == "openrouter.ai" and pinned:
        return pinned

    try:
        return socket.getaddrinfo(hostname, 443, socket.AF_INET)[0][4][0]
    except OSError:
        pass

    # Sandbox / broken resolvers: query Cloudflare DoH by IP (no DNS needed).
    url = f"https://1.1.1.1/dns-query?name={hostname}&type=A"
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        # Last resort: curl with --noproxy
        proc = subprocess.run(
            [
                "curl",
                "-sS",
                "--noproxy",
                "*",
                "-H",
                "accept: application/dns-json",
                url,
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            # Hardcoded Cloudflare edge IPs for openrouter.ai (last-resort).
            if hostname == "openrouter.ai":
                return "104.18.2.115"
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"DNS resolve failed for {hostname}: {err}") from None
        data = json.loads(proc.stdout.decode("utf-8"))

    for ans in data.get("Answer") or []:
        if ans.get("type") == 1 and ans.get("data"):
            return str(ans["data"])
    if hostname == "openrouter.ai":
        return "104.18.2.115"
    raise RuntimeError(f"DNS resolve failed for {hostname}: no A record")


def _openrouter_chat_curl(
    *,
    api_key: str,
    model: str,
    user_prompt: str,
    timeout: float,
    payload_bytes: bytes,
) -> str:
    """POST via curl + --resolve (avoids broken urllib proxies / sandbox DNS)."""
    import subprocess

    ip = _resolve_host_ipv4("openrouter.ai")
    cmd = [
        "curl",
        "-sS",
        "--noproxy",
        "*",
        "--fail-with-body",
        "--max-time",
        str(max(int(timeout), 30)),
        "--resolve",
        f"openrouter.ai:443:{ip}",
        "-X",
        "POST",
        OPENROUTER_URL,
        "-H",
        f"Authorization: Bearer {api_key}",
        "-H",
        "Content-Type: application/json",
        "-H",
        "HTTP-Referer: https://trak3r.github.io/binlore/",
        "-H",
        "X-Title: BIN Lore extract",
        "--data-binary",
        "@-",
    ]
    env = {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    proc = subprocess.run(
        cmd,
        input=payload_bytes,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"OpenRouter curl failed ({proc.returncode}): {err}")
    return proc.stdout.decode("utf-8")


def _openrouter_chat(
    *,
    api_key: str,
    model: str,
    user_prompt: str,
    timeout: float,
) -> str:
    """Single OpenRouter chat completion; returns assistant text."""
    import urllib.error
    import urllib.request

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload).encode("utf-8")
    raw: str | None = None
    try:
        req = urllib.request.Request(
            OPENROUTER_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://trak3r.github.io/binlore/",
                "X-Title": "BIN Lore extract",
            },
        )
        # Prefer a direct connection when a broken local proxy is injected.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=max(timeout, 30.0)) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {err_body}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  [OpenRouter] urllib failed ({e}); retrying via curl --resolve...", flush=True)
        raw = _openrouter_chat_curl(
            api_key=api_key,
            model=model,
            user_prompt=user_prompt,
            timeout=timeout,
            payload_bytes=body,
        )

    assert raw is not None
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(f"OpenRouter error: {data['error']}")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter empty choices: {raw[:400]}")
    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError("OpenRouter returned empty message content")
    return text


def query_openrouter(
    prompt: str,
    *,
    api_key: str,
    model: str,
    timeout: float = 180.0,
    max_retries: int = 3,
) -> tuple[dict[str, Any], str]:
    """
    Call OpenRouter with one capable model only.
    Retries the same model on transient errors; never falls back to a weaker model.
    """
    last_error: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        retry_note = f" (attempt {attempt}/{max_retries})" if attempt > 1 else ""
        print(f"\n[OpenRouter] Trying model: {model}{retry_note} (timeout: {timeout:.0f}s)...", flush=True)

        start_time = time.time()
        stop_heartbeat = threading.Event()

        def heartbeat() -> None:
            spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            idx = 0
            while not stop_heartbeat.is_set():
                elapsed = time.time() - start_time
                spin = spinner[idx % len(spinner)]
                print(f"\r  {spin} waiting for OpenRouter ({elapsed:.0f}s)   ", end="", flush=True)
                idx += 1
                stop_heartbeat.wait(1.0)

        t = threading.Thread(target=heartbeat, daemon=True)
        t.start()
        try:
            text = _openrouter_chat(
                api_key=api_key,
                model=model,
                user_prompt=prompt,
                timeout=timeout,
            )
            stop_heartbeat.set()
            elapsed = time.time() - start_time
            print(f"\r  OpenRouter responded in {elapsed:.1f}s                    ", flush=True)
            parsed = validate_extraction(_parse_llm_json(text))
            return parsed, model
        except Exception as exc:
            stop_heartbeat.set()
            print(flush=True)
            last_error = exc
            msg = str(exc)
            print(f"  [OpenRouter] {model} error: {msg[:300]}", flush=True)

            if _is_rate_or_quota_error(exc) and (
                "insufficient credits" in msg.lower()
                or "payment required" in msg.lower()
                or "402" in msg
                or _is_daily_quota_error(exc)
            ):
                # Hard stop — do not burn more attempts or switch to junk models
                raise DailyQuotaExceeded(
                    f"OpenRouter quota/credits exhausted on {model}. "
                    "Top up or wait for reset; not falling back to a weaker model."
                ) from exc

            if _is_not_found_error(exc):
                raise RuntimeError(
                    f"Model '{model}' is not available on OpenRouter. "
                    "Set OPENROUTER_MODEL to another *capable* model id. "
                    "No automatic fallback is configured."
                ) from exc

            if attempt < max_retries:
                # 503 / transient 429: backoff on the SAME model only
                wait = 15.0 * attempt if ("503" in msg or "429" in msg or "unavailable" in msg.lower()) else 5.0 * attempt
                print(f"  Retrying same model in {wait:.0f}s (no model fallback)...", flush=True)
                time.sleep(wait)
                continue
            break

    raise RuntimeError(f"OpenRouter model {model} failed after {max_retries} attempts: {last_error}")


def format_transcript_for_prompt(run_dir: Path) -> str:
    """Format transcript into compact speech paragraphs anchored by start timestamps."""
    json_path = run_dir / "transcript.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            segments = data.get("segments", [])
            if segments:
                chunked_lines: list[str] = []
                curr_start = None
                curr_texts: list[str] = []
                for s in segments:
                    if curr_start is None:
                        curr_start = s["start"]
                    curr_texts.append(s["text"].strip())
                    dur = s["end"] - curr_start
                    combined = " ".join(curr_texts)
                    if dur >= 30.0 or (dur >= 20.0 and combined.endswith((".", "?", "!", '"'))):
                        m, sec = divmod(int(curr_start), 60)
                        h, m = divmod(m, 60)
                        ts_str = f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
                        chunked_lines.append(f"[{ts_str}] {combined}")
                        curr_start = None
                        curr_texts = []
                if curr_texts and curr_start is not None:
                    m, sec = divmod(int(curr_start), 60)
                    h, m = divmod(m, 60)
                    ts_str = f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
                    chunked_lines.append(f"[{ts_str}] " + " ".join(curr_texts))
                return "\n".join(chunked_lines)
        except Exception:
            pass

    txt_path = run_dir / "transcript.txt"
    if txt_path.exists():
        lines = []
        for line in txt_path.read_text(encoding="utf-8").splitlines():
            clean = re.sub(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\s*-->\s*\d{1,2}:\d{2}(?::\d{2})?\]", r"[\1]", line)
            lines.append(clean)
        return "\n".join(lines)

    return ""


def extract_lore_from_vod(
    vod_id: str,
    *,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
    timeout: float = 180.0,
) -> dict[str, Any]:
    run_dir = RUNS_DIR / vod_id
    if not run_dir.exists():
        raise SystemExit(f"Run directory not found: {run_dir}. Did you run `binlore ingest` first?")

    transcript_path = run_dir / "transcript.txt"
    json_path = run_dir / "transcript.json"
    if not transcript_path.exists() and not json_path.exists():
        raise SystemExit(f"Transcript not found in {run_dir}")

    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    transcript_text = format_transcript_for_prompt(run_dir)
    canon = load_wiki_canon()
    canon_text = format_canon_for_prompt(core_characters_only=True)
    user_prompt = build_user_prompt(meta, canon_text, transcript_text)

    all_chars = canon.get("characters", [])
    core_chars = [c for c in all_chars if is_core_network_character(c)]
    omitted_count = len(all_chars) - len(core_chars)
    core_names = [c.name for c in core_chars]

    print("\n--- [Binlore Lore Extraction] ---")
    print(f"Target VOD: {vod_id} ({meta.get('title', 'Unknown')})")
    print(f"Transcript: {len(transcript_text):,} chars (~{len(transcript_text)//4:,} tokens)")
    print(
        f"Canon roster: {len(core_chars)} core recurring characters "
        f"({omitted_count} one-offs/public figures omitted from prompt)"
    )
    print(f"Core talent: {', '.join(core_names)}")
    print(f"Provider: OpenRouter  model={model}  (no weaker-model fallback)")

    if dry_run:
        print("\n--- [DRY RUN: Prompt Preview] ---")
        print(f"System Prompt Length: {len(SYSTEM_PROMPT)} chars")
        print(f"User Prompt Length: {len(user_prompt)} chars (~{len(user_prompt)//4} tokens)")
        print("\nFirst 1000 chars of User Prompt:")
        print(user_prompt[:1000])
        print("--- [END DRY RUN] ---\n")
        return {"dry_run": True}

    api_key = get_api_key()
    # Policy: one capable model only. Never append FALLBACK_MODELS.
    extracted_data, used_model = query_openrouter(
        user_prompt,
        api_key=api_key,
        model=model,
        timeout=timeout,
    )

    extracted_data["_meta"] = {
        "vod_id": vod_id,
        "model": used_model,
        "provider": "openrouter",
        "prompt_chars": len(user_prompt),
        "approx_prompt_tokens": len(user_prompt) // 4,
        "transcript_lines": len(transcript_text.splitlines()),
    }

    out_path = run_dir / "extraction.json"
    out_path.write_text(json.dumps(extracted_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved extraction results to {out_path}", flush=True)

    from .episode import update_episode_from_extraction

    ep_path = update_episode_from_extraction(vod_id, extracted_data)
    print(f"Updated episode page: {ep_path.relative_to(REPO_ROOT)}", flush=True)

    return extracted_data
