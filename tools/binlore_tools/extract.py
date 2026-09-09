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

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# Same-family fallback only when the primary model is unavailable (404), never on quota.
FALLBACK_MODELS = ["gemini-2.5-flash-lite"]

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
    """Gemini free-tier daily quota is exhausted; stop extracting until reset."""


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
- Twitch chatters and viewers are NOT characters.
- Stream raid recipients are NOT characters.

STORYLINES:
A single-episode incident is NOT a storyline. Storylines are multi-episode arcs (e.g. Crum Dick Punch, Beyblade Tournament). Prefer empty storylines[] unless the transcript clearly continues a Known Storyline from the roster.

ASR:
Whisper misspells names. Reconcile to the roster when possible:
Crumb/Crumble → Crum; Monch → Munch; Skynce/Chad → Chet; Chetah → ChetAI; Noggin → Nogget; Papita/Pepita → Pepito.

Match canonical_segment and character names to the Existing Wiki Canon Roster in the user message. Do not invent desks or staff that are not in the roster or clearly on-air in this transcript.

TASK: Extract from the transcript:
1. segments — major blocks with start/end timestamps, canonical_segment from the roster, episode-specific title, notes
2. characters — on-air network figures (speaking or heavily discussed). Not news subjects.
3. storylines — beats of known multi-episode arcs only
4. lore_notes — new canonical facts with an exact timestamp like "[49:58]". No generic one-off jokes.
5. episode_summary — 2-3 sentences, deadpan in-universe journalism

Respond with a single JSON object matching the schema. No markdown, no preamble.
"""


def get_api_key() -> str:
    load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "\n[Error] GEMINI_API_KEY is not set.\n"
            "Lore extraction uses the Google AI Studio free tier (not OpenRouter).\n"
            "  1. Get a key at https://aistudio.google.com/apikey\n"
            "  2. Add it to tools/.env:\n"
            "       GEMINI_API_KEY=...\n"
            "Do not attach a billing account.\n"
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
            "generate_content_free_tier_requests",
            "quota exceeded for metric",
        )
    )


def _is_not_found_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "404" in msg or "not found" in msg or "not_found" in msg


def validate_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """Fail closed: require the core schema, drop external news subjects."""
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


def query_gemini(
    prompt: str,
    *,
    api_key: str,
    models: list[str],
    timeout: float = 180.0,
    max_retries_per_model: int = 2,
) -> tuple[dict[str, Any], str]:
    """Call Google AI Studio with JSON schema. Halt on daily quota; do not fall back to other vendors."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise SystemExit(
            "google-genai is not installed. From the tools venv run:\n"
            "  pip install google-genai\n"
        ) from e

    timeout_ms = max(int(timeout * 1000), 30_000)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))

    last_error: BaseException | None = None
    for model_idx, model in enumerate(models):
        if model_idx > 0:
            time.sleep(2.0)

        for attempt in range(1, max_retries_per_model + 1):
            retry_note = f" (attempt {attempt}/{max_retries_per_model})" if attempt > 1 else ""
            print(f"\n[Gemini] Trying model: {model}{retry_note} (timeout: {timeout:.0f}s)...", flush=True)

            start_time = time.time()
            stop_heartbeat = threading.Event()

            def heartbeat() -> None:
                spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                idx = 0
                while not stop_heartbeat.is_set():
                    elapsed = time.time() - start_time
                    spin = spinner[idx % len(spinner)]
                    print(f"\r  {spin} waiting for Gemini ({elapsed:.0f}s)   ", end="", flush=True)
                    idx += 1
                    stop_heartbeat.wait(1.0)

            t = threading.Thread(target=heartbeat, daemon=True)
            t.start()
            try:
                config_kwargs: dict[str, Any] = {
                    "system_instruction": SYSTEM_PROMPT,
                    "temperature": 0.2,
                    "response_mime_type": "application/json",
                    "response_schema": EXTRACT_SCHEMA,
                }
                try:
                    config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                except (TypeError, AttributeError):
                    pass

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            except Exception as exc:
                stop_heartbeat.set()
                print(flush=True)
                last_error = exc
                msg = str(exc)
                print(f"  [Gemini] {model} error: {msg[:300]}", flush=True)
                if _is_daily_quota_error(exc):
                    raise DailyQuotaExceeded(
                        f"Gemini daily quota exhausted on {model}. Stop extracting until the quota resets (midnight Pacific)."
                    ) from exc
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if status == 429 or "429" in msg:
                    if attempt < max_retries_per_model:
                        wait = 30.0 * attempt
                        print(f"  Rate limited. Sleeping {wait:.0f}s...", flush=True)
                        time.sleep(wait)
                        continue
                    raise DailyQuotaExceeded(
                        f"Gemini 429 on {model} after {max_retries_per_model} retries. "
                        "Treating as quota exhaustion; not falling back to another vendor."
                    ) from exc
                if _is_not_found_error(exc):
                    break
                if attempt < max_retries_per_model:
                    time.sleep(2.0 * attempt)
                    continue
                break
            else:
                stop_heartbeat.set()
                elapsed = time.time() - start_time
                print(f"\r  Gemini responded in {elapsed:.1f}s                    ", flush=True)
                text = (getattr(response, "text", None) or "").strip()
                if not text:
                    last_error = ValueError(f"Empty response from {model}")
                    print(f"  [Gemini] empty response from {model}", flush=True)
                    if attempt < max_retries_per_model:
                        continue
                    break
                try:
                    parsed = validate_extraction(_parse_llm_json(text))
                except (ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    print(f"  [Gemini] schema/parse failure: {exc}", flush=True)
                    if attempt < max_retries_per_model:
                        continue
                    break
                return parsed, model

    raise RuntimeError(f"All Gemini models failed: {last_error}")


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
    print(f"Provider: Google AI Studio  model={model}")

    if dry_run:
        print("\n--- [DRY RUN: Prompt Preview] ---")
        print(f"System Prompt Length: {len(SYSTEM_PROMPT)} chars")
        print(f"User Prompt Length: {len(user_prompt)} chars (~{len(user_prompt)//4} tokens)")
        print("\nFirst 1000 chars of User Prompt:")
        print(user_prompt[:1000])
        print("--- [END DRY RUN] ---\n")
        return {"dry_run": True}

    api_key = get_api_key()
    models_to_try = [model]
    if not str(model).startswith("gemini-"):
        print(
            f"  Warning: '{model}' is not a Gemini model id. "
            f"Using {DEFAULT_MODEL}. Set GEMINI_MODEL in tools/.env.",
            flush=True,
        )
        models_to_try = [DEFAULT_MODEL]
    for m in FALLBACK_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    extracted_data, used_model = query_gemini(
        user_prompt,
        api_key=api_key,
        models=models_to_try,
        timeout=timeout,
    )

    extracted_data["_meta"] = {
        "vod_id": vod_id,
        "model": used_model,
        "provider": "google-ai-studio",
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
