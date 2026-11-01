from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable

import yaml

from .paths import EXCLUDED_STREAMS_YAML


class ExcludedStreamError(RuntimeError):
    pass


def _norm(raw: Any) -> str:
    vid = str(raw or "").strip()
    if vid.startswith("v") and vid[1:].isdigit():
        return vid[1:]
    return vid


@lru_cache(maxsize=1)
def excluded_streams() -> tuple[dict[str, Any], ...]:
    if not EXCLUDED_STREAMS_YAML.exists():
        return ()
    data = yaml.safe_load(EXCLUDED_STREAMS_YAML.read_text(encoding="utf-8")) or {}
    return tuple(data.get("streams") or ())


@lru_cache(maxsize=1)
def excluded_ids() -> frozenset[str]:
    return frozenset(_norm(i) for s in excluded_streams() for i in (s.get("ids") or ()) if _norm(i))


def is_excluded(*ids: Any) -> bool:
    banned = excluded_ids()
    return any(_norm(i) in banned for i in ids if _norm(i))


def is_excluded_entry(entry: dict[str, Any]) -> bool:
    return is_excluded(entry.get("twitch_id"), entry.get("yt_id"), entry.get("id"))


def drop_excluded(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if not is_excluded_entry(e)]


def ensure_not_excluded(vod_id: Any) -> None:
    if not is_excluded(vod_id):
        return
    entry = next(s for s in excluded_streams() if _norm(vod_id) in {_norm(i) for i in s.get("ids") or ()})
    raise ExcludedStreamError(
        f"VOD {_norm(vod_id)} ({entry.get('date')} {entry.get('title')!r}) is listed in "
        f"tools/excluded_streams.yaml as not a BIN episode: {entry.get('reason')}"
    )
