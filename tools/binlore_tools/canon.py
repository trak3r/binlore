from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .paths import (
    CANON_DENYLIST_YAML,
    CONTENT_CHARACTERS,
    CONTENT_SEGMENTS,
    CONTENT_STORYLINES,
)


@dataclass
class CanonEntity:
    name: str
    entity_type: str  # character, segment, storyline
    aliases: list[str] = field(default_factory=list)
    status: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    file_path: Path | None = None


def _parse_frontmatter_and_body(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return {}, content.strip()

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content.strip()

    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        data = {}
    body = parts[2].strip()
    return data, body


def _strip_md_inline(text: str) -> str:
    text = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return " ".join(text.split())


def _section_body(body: str, heading: str) -> str:
    pattern = rf"(^|\n)({re.escape(heading)}\s*\n)"
    match = re.search(pattern, body, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"\n(?=#{1,2}\s)", body[start:])
    end = start + next_match.start() if next_match else len(body)
    return body[start:end].strip()


def _clean_summary(body: str, max_chars: int = 140) -> str:
    """Legacy short summary from first prose lines."""
    lines: list[str] = []
    for line in body.splitlines():
        line_str = line.strip()
        if not line_str or line_str.startswith(("#", "|", "-", "*", "!", "<", ">")):
            continue
        lines.append(line_str)
        if len(lines) >= 2:
            break

    combined = _strip_md_inline(" ".join(lines))
    if len(combined) > max_chars:
        truncated = combined[:max_chars].rsplit(" ", 1)[0]
        return truncated + "..."
    return combined


def _rich_character_summary(frontmatter: dict[str, Any], body: str, max_chars: int = 900) -> str:
    """
    Durable canon for prompts: frontmatter canon_notes, ## Canon notes,
    ## Overview, and ## Key Attributes — so manual corrections survive re-extract.
    """
    parts: list[str] = []

    fm_notes = frontmatter.get("canon_notes")
    if isinstance(fm_notes, list):
        parts.extend(str(n).strip() for n in fm_notes if str(n).strip())
    elif isinstance(fm_notes, str) and fm_notes.strip():
        parts.append(fm_notes.strip())

    for heading in ("## Canon notes", "## Canon Notes"):
        section = _section_body(body, heading)
        if section:
            for line in section.splitlines():
                cleaned = _strip_md_inline(line.lstrip("-* ").strip())
                if cleaned:
                    parts.append(cleaned)
            break

    overview = _section_body(body, "## Overview")
    if overview:
        prose: list[str] = []
        for line in overview.splitlines():
            s = line.strip()
            if not s or s.startswith(("#", "|", "!", "<", ">")):
                continue
            if s.startswith(("-", "*")):
                prose.append(_strip_md_inline(s.lstrip("-* ").strip()))
            else:
                prose.append(_strip_md_inline(s))
            if len(prose) >= 4:
                break
        if prose:
            parts.append(" ".join(prose))

    attrs = _section_body(body, "## Key Attributes & Lore") or _section_body(body, "## Key Attributes")
    if attrs:
        bullets: list[str] = []
        for line in attrs.splitlines():
            s = line.strip()
            if s.startswith(("-", "*")):
                bullets.append(_strip_md_inline(s.lstrip("-* ").strip()))
            if len(bullets) >= 6:
                break
        if bullets:
            parts.append("Traits: " + "; ".join(bullets))

    if not parts:
        return _clean_summary(body)

    combined = " | ".join(parts)
    combined = _strip_md_inline(combined)
    if len(combined) > max_chars:
        truncated = combined[:max_chars].rsplit(" ", 1)[0]
        return truncated + "..."
    return combined


def load_canon_entities(directory: Path, entity_type: str) -> list[CanonEntity]:
    if not directory.exists():
        return []

    entities: list[CanonEntity] = []
    for md_path in sorted(directory.glob("*.md")):
        if md_path.name == "index.md":
            continue

        frontmatter, body = _parse_frontmatter_and_body(md_path)
        name = str(frontmatter.get("title") or md_path.stem)
        aliases = [str(a) for a in (frontmatter.get("aliases") or [])]
        status = str(frontmatter.get("status") or "")
        tags = [str(t) for t in (frontmatter.get("tags") or [])]

        if entity_type == "character":
            summary = _rich_character_summary(frontmatter, body)
        else:
            summary = _clean_summary(body)
            # Storylines: prefer Background / Status for richer seed
            if entity_type == "storyline":
                bg = _section_body(body, "## Background & Network Record") or _section_body(
                    body, "## Background"
                )
                if bg:
                    summary = _rich_character_summary({}, f"## Overview\n\n{bg}") or summary

        entities.append(
            CanonEntity(
                name=name,
                entity_type=entity_type,
                aliases=aliases,
                status=status,
                summary=summary,
                tags=tags,
                file_path=md_path,
            )
        )
    return entities


_DEFAULT_NAME_TOKENS = (
    "trump",
    "vance",
    "mcconnell",
    "graham",
    "hegseth",
    "biden",
    "nixon",
    "johnson",
    "starmer",
    "bevin",
    "altman",
    "ben hooper",
    "card king",
)

_DEFAULT_NOTE_TOKENS = (
    "senator",
    "president",
    "politician",
    "public figure",
    "secretary of",
    "vice president",
    "biohacker",
    "prime minister",
    "minister",
    "governor",
    "congressman",
    "representative",
    "celebrity",
    "actor in",
    "movie clip",
    "video clip",
    "news clip",
    "clip subject",
    "viral video",
    "being watched",
    "chatter",
    "chat user",
    "twitch chat",
    "raid",
)

_denylist_cache: dict[str, Any] | None = None


def load_canon_denylist() -> dict[str, Any]:
    """Load tools/canon_denylist.yaml merged over built-in defaults."""
    global _denylist_cache
    if _denylist_cache is not None:
        return _denylist_cache

    data: dict[str, Any] = {
        "names": [],
        "name_tokens": list(_DEFAULT_NAME_TOKENS),
        "note_tokens": list(_DEFAULT_NOTE_TOKENS),
    }
    if CANON_DENYLIST_YAML.exists():
        try:
            loaded = yaml.safe_load(CANON_DENYLIST_YAML.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            loaded = {}
        for key in ("names", "name_tokens", "note_tokens"):
            extra = loaded.get(key) or []
            if isinstance(extra, list):
                merged = list(data[key])
                for item in extra:
                    s = str(item).strip()
                    if s and s.lower() not in {x.lower() for x in merged}:
                        merged.append(s)
                data[key] = merged
    _denylist_cache = data
    return data


def is_excluded_external_subject(name: str, notes: str = "") -> bool:
    """True for politicians, clip subjects, chatters, raid targets — not wiki characters."""
    deny = load_canon_denylist()
    lower_name = name.lower().strip()
    lower_notes = notes.lower()

    for exact in deny.get("names") or []:
        if lower_name == str(exact).lower().strip():
            return True
    if any(token in lower_name for token in deny.get("name_tokens") or []):
        return True
    if any(token in lower_notes for token in deny.get("note_tokens") or []):
        return True
    if "hooper" in lower_name:
        return True
    return False


def is_core_network_character(char: CanonEntity) -> bool:
    """
    Returns True if character is a core recurring show persona rather than a public figure,
    community contributor, or one-off/special guest.
    Prompts only include core network cast/talent to conserve prompt tokens and prevent
    confusing LLM with external news subjects or community chat members.
    """
    slug = (char.file_path.stem if char.file_path else "").lower()
    if slug in ("abraham-lincoln", "live-in-sleazy", "live-n-sleazy"):
        return False

    status_lower = (char.status or "").lower()
    # Omit satirized public and historical figures
    if any(k in status_lower for k in ("public figure", "historical figure", "satirized")):
        return False

    # Omit guests, call-ins, and community contributors/moderators
    if any(k in status_lower for k in ("guest", "call-in", "community")):
        return False

    # Check tags
    tags_lower = [t.lower() for t in char.tags]
    if any(
        t in (
            "parody",
            "politics",
            "celebrity",
            "biohacking",
            "historical",
            "guest",
            "call-in",
            "community",
            "technical",
        )
        for t in tags_lower
    ):
        return False

    return True


def load_wiki_canon() -> dict[str, list[CanonEntity]]:
    return {
        "characters": load_canon_entities(CONTENT_CHARACTERS, "character"),
        "segments": load_canon_entities(CONTENT_SEGMENTS, "segment"),
        "storylines": load_canon_entities(CONTENT_STORYLINES, "storyline"),
    }


def format_canon_for_prompt(*, core_characters_only: bool = True) -> str:
    canon = load_wiki_canon()
    sections: list[str] = []

    characters = canon["characters"]
    if core_characters_only:
        characters = [c for c in characters if is_core_network_character(c)]

    sections.append("### Known Recurring Characters")
    for char in characters:
        alias_str = f" (aliases: {', '.join(char.aliases)})" if char.aliases else ""
        status_str = f" [{char.status}]" if char.status else ""
        sections.append(f"- **{char.name}**{alias_str}{status_str}: {char.summary}")

    sections.append("\n### Known Segments")
    for seg in canon["segments"]:
        status_str = f" [{seg.status}]" if seg.status else ""
        sections.append(f"- **{seg.name}**{status_str}: {seg.summary}")

    sections.append("\n### Known Storylines")
    for story in canon["storylines"]:
        status_str = f" [{story.status}]" if story.status else ""
        sections.append(f"- **{story.name}**{status_str}: {story.summary}")

    return "\n".join(sections)
