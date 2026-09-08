from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from .paths import CONTENT_CHARACTERS, CONTENT_SEGMENTS, CONTENT_STORYLINES


@dataclass
class CanonEntity:
    name: str
    entity_type: str  # character, segment, storyline
    aliases: list[str] = field(default_factory=list)
    status: str = ""
    summary: str = ""
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


def _clean_summary(body: str, max_chars: int = 140) -> str:
    """Extract a concise single-sentence summary stripped of markdown links, callouts, and disclaimers."""
    lines: list[str] = []
    for line in body.splitlines():
        line_str = line.strip()
        # Skip headings, tables, bullet points, images, HTML, and blockquotes/callouts
        if not line_str or line_str.startswith(("#", "|", "-", "*", "!", "<", ">")):
            continue
        lines.append(line_str)
        if len(lines) >= 2:
            break

    combined = " ".join(lines)
    # Strip wikilinks [[target|label]] -> label, [[target]] -> target
    combined = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", combined)
    # Strip markdown bold/italic
    combined = re.sub(r"\*\*([^*]+)\*\*", r"\1", combined)
    combined = re.sub(r"\*([^*]+)\*", r"\1", combined)
    combined = " ".join(combined.split())

    if len(combined) > max_chars:
        # Cut cleanly at word boundary
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

        summary = _clean_summary(body)

        entities.append(
            CanonEntity(
                name=name,
                entity_type=entity_type,
                aliases=aliases,
                status=status,
                summary=summary,
                file_path=md_path,
            )
        )
    return entities


def load_wiki_canon() -> dict[str, list[CanonEntity]]:
    return {
        "characters": load_canon_entities(CONTENT_CHARACTERS, "character"),
        "segments": load_canon_entities(CONTENT_SEGMENTS, "segment"),
        "storylines": load_canon_entities(CONTENT_STORYLINES, "storyline"),
    }


def format_canon_for_prompt() -> str:
    canon = load_wiki_canon()
    sections: list[str] = []

    sections.append("### Known Characters")
    for char in canon["characters"]:
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
