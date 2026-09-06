from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .canon import format_canon_for_prompt, load_wiki_canon
from .paths import CONTENT_EPISODES, REPO_ROOT, RUNS_DIR, TOOLS_ROOT

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"
FALLBACK_MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "minimax/minimax-m3:free",
    "google/gemma-4-26b-a4b-it:free",
    "z-ai/glm-5.2:free",
    "google/gemma-4-31b-it:free",
]


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


def get_api_key() -> str:
    load_env()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "\n[Error] OPENROUTER_API_KEY is not set.\n"
            "To use OpenRouter extraction (including free models):\n"
            "  1. Get an API key from https://openrouter.ai/keys\n"
            "  2. Add it to tools/.env:\n"
            "       OPENROUTER_API_KEY=sk-or-v1-...\n"
            "  3. Or export it in your environment:\n"
            "       export OPENROUTER_API_KEY=sk-or-v1-...\n"
        )
    return key


SYSTEM_PROMPT = """You are the canon lore archivist for 'Barely Informed News' (BIN), documenting the network's broadcast archive (twitch.tv/caseblackwell).

CRITICAL TONE & KAYFABE DIRECTIVE:
Maintain strict, 100% in-universe kayfabe. Treat Barely Informed News as a real broadcast news network with real anchors, correspondents, debate analysts, reporters, and staff.
- NEVER use fourth-wall-breaking phrases such as:
  * "is a character" / "show character"
  * "portrayed by" / "played by Case" / "Case's persona"
  * "digital filter" / "face filter" / "baby face filter"
  * "voice changer" / "voice modulation"
  * "bit" / "one-off bit" / "persona"
- Always describe figures by their professional broadcast roles (e.g. "lead news anchor", "senior debate analyst", "chief science correspondent", "executive producer", "legal counsel", "in-studio contributor", "call-in guest").
- Treat live glitches or chaotic moments as real broadcast control room mix-ups or live studio events.

Key network context:
- Lead Anchor & Managing Editor: Case Blackwell.
- Tone: Deadpan satirical broadcast journalism, investigative reports, high-stakes studio debates, and unhinged field dispatches.
- Canonical Network Segments:
  1. "Pre-show / Cold Open": Starts the broadcast. Typically opens with Executive Producer **Pepito** ("I'm Pepito, I'm the dog that produces the show..."), banter with studio guests/crew, and station announcements.
  2. "News": The core news desk broadcast. Case at the desk in front of a Los Angeles cityscape backdrop with a rolling "BREAKING" news ticker, delivering headlines, political scandals, and breaking international and domestic stories.
  3. "Hype Train": Broadcast interruption triggered during a Twitch hype train surge. Features retro synthwave graphics, the sentient locomotive correspondent **Hype Train**, his partner the Panther, freestyle raps, and crypto-universe dispatches.
  4. "Munch & Crum": The flagship on-air debate clash between senior debate analysts **Munch (Ralph Munchcut)** and **Crum**, featuring rotating 3D title cards, scoreboard, chat polling, and bitter political rivalry.
  5. "Chet Guy the Science Eyes": The network's investigative science desk, helmed by Chief Science Correspondent **Chet (Chet Manscape)** alongside his synthetic AI co-host **ChetAI**. IMPORTANT: This desk is triggered spontaneously whenever anyone on the broadcast accidentally utters the word "science" or "scientist" while discussing a story! Chet deploys a high-powered laboratory microscope to the desk and consults ChetAI (a synthetic digital avatar appearing across studio monitors with falling binary data rain, claiming vast boob training data and translating foreign medical literature). Note: Whisper ASR often transcribes "Chet" as "Skynce" or "Chad", and "ChetAI" as "Chetah". Reconcile to Chet and ChetAI!
  6. "Cryptozeus" (Gaming): Live remote dispatch from resident gaming correspondent **Brandon (Cryptozeus)** conducting deep-dive retro playthroughs from his bedroom while his mother yells through the closed door, alongside sponsor dispatches for Gooters chicken wings.
  7. "Amongst the Web": Audience-interactive viral media review desk where a designated network correspondent evaluates viewer-submitted meme videos and online clips while the audience votes.

- Key Network Figures:
  - **Munch (Ralph Munchcut)**: Senior debate analyst with disheveled silver hair.
  - **Crum**: Senior debate analyst, hollow-eyed and bald, plagued by crippling gambling debts.
  - **Chet (Chet Manscape)**: Chief science correspondent with desk microscope.
  - **ChetAI**: Synthetic neural network co-host operating from the studio monitors.
  - **Hype Train**: High-velocity musical and cultural correspondent traveling with his panther companion.
  - **Cryptozeus (Brandon)**: Resident gaming and digital culture correspondent.
  - **Pepito**: Executive producer overseeing broadcast operations.
  - **Jeff Ripple**: Studio news reader and breaking chat correspondent (often misheard in ASR as "Jeff Hooper").
  - **Peter Gibbon**: Disgraced former producer who now inhabits the studio wall crawlspaces as a news stowaway.
  - **Tommy Biglaw**: High-priced infant legal counsel with a baby-talk lisp; also serves as prosecutor "Big Tommy Prosecutor".

- Note on Appearance & Clothing: Do NOT describe or focus on what characters are wearing below the neck (clothes, suits, jackets, ties, etc.) as these vary based on whatever is worn in studio on any given day. Focus on facial features, props (e.g. microscopes), and broadcast behavior.
- Note on ASR transcription: The input transcript was generated by automated speech recognition (Whisper). Names may have phonetic variations (e.g. "Crumb" for "Crum", "Monch" for "Munch", "Skynce" / "Chad" for "Chet", "Chetah" for "ChetAI", "Jeff Hooper" for "Jeff Ripple"). Reconcile them to known canon entities when possible.

Your task:
Analyze the provided stream transcript and extract:
1. "segments": Major show segments with start and end timestamps (e.g. "MM:SS" or "HH:MM:SS"), matching to canonical show segments ("News", "Hype Train", "Munch & Crum", "Chet Guy the Science Eyes", "Cryptozeus", "Amongst the Web", "Pre-show / Cold Open"), a descriptive title for this episode's topic, and concise notes.
2. "characters": Network figures detected on stream (either speaking on air, or heavily discussed/slandered). Mark whether they were actively speaking or merely mentioned, with timestamps. Use professional, in-universe descriptions (e.g. "Anchor", "Debate Analyst", "Legal Counsel").
3. "storylines": Developments, escalations, or callbacks to ongoing storylines (especially the Crum D*ck Punch wager) or new broadcast arcs.
4. "lore_notes": Meaningful canonical lore facts, backstories, broadcast relationships, catchphrases, or recurring network policies. Do NOT include generic one-off jokes. Every lore note MUST include an exact source timestamp like "[49:58]".
5. "episode_summary": A 2-3 sentence high-level overview of the broadcast written in deadpan in-universe journalistic style.

Output format:
IMPORTANT: You MUST respond with a single, raw JSON object ONLY.
Do NOT output any conversational preamble, chain-of-thought, reasoning steps, or markdown formatting outside the JSON object.
Match this schema:
{
  "episode_summary": "...",
  "segments": [
    {
      "start": "00:00",
      "end": "16:00",
      "canonical_segment": "Pre-show / Cold Open",
      "title": "Pepito Intro & Studio Skeleton Bit",
      "notes": "...",
      "characters": ["Pepito"]
    }
  ],
  "characters": [
    {
      "name": "...",
      "canonical_name": "...",
      "speaking": true,
      "timestamps": ["..."],
      "confidence": 0.95,
      "notes": "..."
    }
  ],
  "storylines": [
    {
      "storyline": "Munch–Crum rivalry",
      "beat": "...",
      "timestamp": "..."
    }
  ],
  "lore_notes": [
    {
      "entity": "...",
      "fact": "...",
      "timestamp": "...",
      "confidence": 0.9
    }
  ]
}
"""


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
    # Strip <think>...</think> if emitted by reasoning models
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding outer braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse valid JSON from LLM response:\n{text[:500]}...")


def query_openrouter(
    prompt: str,
    *,
    api_key: str,
    models: list[str],
    timeout: float = 75.0,
) -> tuple[dict[str, Any], str]:
    """Query OpenRouter with SSE streaming, live progress ticker, and automatic fallback."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/trak3r/binlore",
        "X-Title": "Binlore Wiki Pipeline",
        "Content-Type": "application/json",
    }

    approx_prompt_tokens = len(prompt) // 4
    last_error: Exception | None = None

    for model in models:
        print(f"\n[OpenRouter] Trying model: {model} (timeout: {timeout:.0f}s)...", flush=True)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "stream": True,
        }

        start_time = time.time()
        stop_heartbeat = threading.Event()
        first_token_event = threading.Event()

        def heartbeat() -> None:
            spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            idx = 0
            while not stop_heartbeat.is_set() and not first_token_event.is_set():
                elapsed = time.time() - start_time
                spin = spinner[idx % len(spinner)]
                sys.stdout.write(
                    f"\r  {spin} Waiting for response (prefilling ~{approx_prompt_tokens:,} tokens)... {elapsed:.1f}s"
                )
                sys.stdout.flush()
                idx += 1
                time.sleep(0.12)

        hb_thread = threading.Thread(target=heartbeat, daemon=True)
        hb_thread.start()

        collected_text: list[str] = []
        try:
            # Enforce connect, read, write timeouts to avoid hanging sockets
            # Use a bounded read timeout (e.g. 40s) so if the model hangs without transmitting packets, we failover
            inactivity_timeout = min(float(timeout), 40.0)
            client_timeout = httpx.Timeout(timeout, connect=20.0, read=inactivity_timeout, write=20.0, pool=10.0)
            with httpx.Client(timeout=client_timeout) as client:
                with client.stream("POST", OPENROUTER_API_URL, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        stop_heartbeat.set()
                        hb_thread.join(timeout=0.5)
                        err_text = resp.read().decode("utf-8", errors="replace")
                        sys.stdout.write(f"\r  ✗ Model returned HTTP {resp.status_code}: {err_text[:180]}\n")
                        sys.stdout.flush()
                        last_error = RuntimeError(f"HTTP {resp.status_code}: {err_text}")
                        continue

                    last_progress_ts = 0.0
                    for line in resp.iter_lines():
                        if not first_token_event.is_set() and (time.time() - start_time) > timeout:
                            raise TimeoutError(f"Model {model} timed out waiting for first token after {timeout:.0f}s")
                        if not line:
                            continue
                        line_str = line.strip()
                        if not line_str.startswith("data:"):
                            continue
                        data_part = line_str[len("data:"):].strip()
                        if data_part == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_part)
                        except Exception:
                            continue

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content_piece = delta.get("content")
                        if content_piece:
                            if not first_token_event.is_set():
                                first_token_event.set()
                                stop_heartbeat.set()
                                hb_thread.join(timeout=0.5)

                            collected_text.append(content_piece)
                            now = time.time()
                            if now - last_progress_ts > 0.15:
                                last_progress_ts = now
                                total_chars = sum(len(c) for c in collected_text)
                                elapsed = now - start_time
                                sys.stdout.write(
                                    f"\r  ⚡ Streaming response: {total_chars:,} chars received ({elapsed:.1f}s)..."
                                )
                                sys.stdout.flush()

            stop_heartbeat.set()
            hb_thread.join(timeout=0.5)

            full_content = "".join(collected_text).strip()
            total_chars = len(full_content)
            elapsed = time.time() - start_time
            sys.stdout.write(
                f"\r  ✓ Response complete: {total_chars:,} chars in {elapsed:.1f}s. Parsing JSON...      \n"
            )
            sys.stdout.flush()

            if not full_content:
                last_error = RuntimeError(f"Empty response from model {model}")
                continue

            parsed = _parse_llm_json(full_content)
            return parsed, model

        except Exception as e:
            stop_heartbeat.set()
            hb_thread.join(timeout=0.5)
            elapsed = time.time() - start_time
            sys.stdout.write(f"\r  ✗ Model {model} failed after {elapsed:.1f}s: {e}\n")
            sys.stdout.flush()
            last_error = e

    raise RuntimeError(f"All candidate models failed. Last error: {last_error}")


def extract_lore_from_vod(
    vod_id: str,
    *,
    model: str = DEFAULT_MODEL,
    dry_run: bool = False,
    timeout: float = 75.0,
) -> dict[str, Any]:
    run_dir = RUNS_DIR / vod_id
    if not run_dir.exists():
        raise SystemExit(f"Run directory not found: {run_dir}. Did you run `binlore ingest` first?")

    transcript_path = run_dir / "transcript.txt"
    if not transcript_path.exists():
        raise SystemExit(f"Transcript not found: {transcript_path}")

    meta_path = run_dir / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    transcript_text = transcript_path.read_text(encoding="utf-8")
    canon = load_wiki_canon()
    canon_text = format_canon_for_prompt()
    user_prompt = build_user_prompt(meta, canon_text, transcript_text)

    char_names = [c.name for c in canon.get("characters", [])]
    print(f"\n--- [Binlore Lore Extraction] ---")
    print(f"Target VOD: {vod_id} ({meta.get('title', 'Unknown')})")
    print(f"Transcript: {len(transcript_text):,} chars (~{len(transcript_text)//4:,} tokens)")
    print(f"Canon roster loaded: {len(char_names)} characters ({', '.join(char_names)})")

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
    for m in FALLBACK_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    extracted_data, used_model = query_openrouter(
        user_prompt,
        api_key=api_key,
        models=models_to_try,
        timeout=timeout,
    )

    extracted_data["_meta"] = {
        "vod_id": vod_id,
        "model": used_model,
        "transcript_lines": len(transcript_text.splitlines()),
    }

    # Save extraction JSON
    out_path = run_dir / "extraction.json"
    out_path.write_text(json.dumps(extracted_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved extraction results to {out_path}", flush=True)

    # Update episode markdown page in content/episodes/
    from .episode import update_episode_from_extraction
    ep_path = update_episode_from_extraction(vod_id, extracted_data)
    print(f"Updated episode page: {ep_path.relative_to(REPO_ROOT)}", flush=True)

    return extracted_data
