"""Vertical highlight clips (TikTok / Reels / Shorts) cut from episode VODs.

Captions, the watermark, and the end card are rendered with Pillow and
composited with ffmpeg's ``overlay`` filter, so a stock ffmpeg build without
libass/freetype is enough.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw, ImageFont

from .paths import CATALOG_JSON, CONTENT_DIR, CONTENT_EPISODES, REPO_ROOT, TOOLS_ROOT
from .screencap import extract_frame, get_stream_url
from .vods import get_yt_dlp_cmd

CLIPS_DIR = TOOLS_ROOT / "clips"
ASSETS_DIR = CLIPS_DIR / "assets"
PREVIEWS_DIR = CLIPS_DIR / "previews"
STATIC_DIR = REPO_ROOT / "quartz" / "static"
WIKI_BASE = "https://binlore.wiki"
TWITCH_CHANNEL_URL = "twitch.tv/caseblackwell"

OUT_W, OUT_H, FPS = 1080, 1920, 30
SLICE_PAD = 1.0
SEEK_PREROLL = 12.0

# Platform UI covers roughly the top 10% and bottom 15% of a vertical video.
CAPTION_W, CAPTION_H = OUT_W, 440
CAPTION_Y = 1060
CAPTION_MAX_TEXT_W = 960
CAPTION_FONT_SIZE = 92
CAPTION_STROKE = 9
CAPTION_FILL = (255, 255, 255, 255)
CAPTION_ACTIVE_FILL = (255, 225, 77, 255)

WATERMARK_X, WATERMARK_Y = 40, 200
WATERMARK_OPACITY = 0.7

END_CARD_SECONDS = 2.5

BASE_HASHTAGS = ["BarelyInformedNews", "CaseBlackwell", "comedy", "improv", "twitchclips"]

BOLD_FONTS = [
    ASSETS_DIR / "font.ttf",
    Path("/System/Library/Fonts/Supplemental/Arial Black.ttf"),
    Path("/System/Library/Fonts/Supplemental/Impact.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
REGULAR_FONTS = [
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


# ---------------------------------------------------------------------------
# Timestamps


def parse_ts(value: str | float) -> float:
    """Parse ``H:MM:SS(.ms)``, ``MM:SS`` or plain seconds into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = value.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError as e:
        raise ValueError(f"Bad timestamp {value!r}; use H:MM:SS, MM:SS or seconds") from e
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def fmt_hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def twitch_t(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}h{s % 3600 // 60}m{s % 60}s"


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3_600_000:02d}:{ms % 3_600_000 // 60_000:02d}:{ms % 60_000 // 1000:02d},{ms % 1000:03d}"


# ---------------------------------------------------------------------------
# Episode / source resolution


def _is_yt_id(value: str | None) -> bool:
    return bool(value) and not value.isdigit() and re.fullmatch(r"[\w-]{11}", value) is not None


@dataclass
class Episode:
    date: str | None = None
    title: str | None = None
    twitch_id: str | None = None
    yt_id: str | None = None
    characters: list[str] = field(default_factory=list)

    @property
    def twitch_url(self) -> str | None:
        return f"https://www.twitch.tv/videos/{self.twitch_id}" if self.twitch_id else None

    @property
    def yt_url(self) -> str | None:
        return f"https://www.youtube.com/watch?v={self.yt_id}" if self.yt_id else None

    @property
    def sources(self) -> list[str]:
        return [u for u in (self.twitch_url, self.yt_url) if u]

    @property
    def wiki_url(self) -> str | None:
        if self.date and (CONTENT_EPISODES / f"{self.date}.md").exists():
            return f"{WIKI_BASE}/episodes/{self.date}"
        return None

    @property
    def label(self) -> str:
        return self.date or self.twitch_id or self.yt_id or "vod"

    def twitch_link(self, seconds: float) -> str | None:
        return f"{self.twitch_url}?t={twitch_t(seconds)}" if self.twitch_url else None

    def yt_link(self, seconds: float) -> str | None:
        return f"{self.yt_url}&t={int(seconds)}s" if self.yt_url else None


def _frontmatter(path: Path) -> dict[str, Any]:
    m = re.match(r"^---\n(.*?)\n---", path.read_text(encoding="utf-8"), re.DOTALL)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def _ids_from_url(value: str) -> tuple[str | None, str | None]:
    """Return ``(twitch_id, yt_id)`` parsed from a URL or bare id."""
    value = value.strip()
    if m := re.search(r"twitch\.tv/videos/v?(\d+)", value):
        return m.group(1), None
    if m := re.search(r"(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)([\w-]{11})", value):
        return None, m.group(1)
    if value.lstrip("v").isdigit():
        return value.lstrip("v"), None
    if _is_yt_id(value):
        return None, value
    return None, None


def _episode_files() -> list[Path]:
    return sorted(p for p in CONTENT_EPISODES.glob("*.md") if re.match(r"\d{4}-\d{2}-\d{2}", p.stem))


def _find_episode_page(twitch_id: str | None, yt_id: str | None) -> Path | None:
    needles = [n for n in (twitch_id, yt_id) if n]
    for path in reversed(_episode_files()):
        head = path.read_text(encoding="utf-8")[:600]
        if any(n in head for n in needles):
            return path
    return None


def resolve_episode(target: str | None) -> Episode:
    """Resolve an episode date, ``latest``, Twitch/YouTube URL, or VOD id."""
    target = (target or "latest").strip()
    page: Path | None = None
    twitch_id = yt_id = None

    if target == "latest":
        files = _episode_files()
        if not files:
            raise SystemExit("No episode pages found in content/episodes/.")
        page = files[-1]
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}(-\w+)?", target):
        page = CONTENT_EPISODES / f"{target}.md"
        if not page.exists():
            raise SystemExit(f"No episode page at {page.relative_to(REPO_ROOT)}")
    else:
        twitch_id, yt_id = _ids_from_url(target)
        if not (twitch_id or yt_id):
            raise SystemExit(f"Can't tell which VOD {target!r} refers to.")
        page = _find_episode_page(twitch_id, yt_id)

    ep = Episode(twitch_id=twitch_id, yt_id=yt_id)
    if page:
        fm = _frontmatter(page)
        ep.date = str(fm.get("date") or page.stem)[:10]
        ep.title = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", str(fm.get("title") or "")) or None
        for value in (str(fm.get("vod_url") or ""), str(fm.get("vod_id") or "")):
            t, y = _ids_from_url(value) if value else (None, None)
            ep.twitch_id = ep.twitch_id or t
            ep.yt_id = ep.yt_id or y
        ep.characters = [c["name"] for c in fm.get("characters_meta") or [] if isinstance(c, dict) and c.get("name")]

    if CATALOG_JSON.exists():
        catalog = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
        match = next(
            (
                e
                for e in catalog
                if (ep.twitch_id and e.get("twitch_id") == ep.twitch_id)
                or (ep.yt_id and e.get("yt_id") == ep.yt_id)
            ),
            None,
        )
        if match is None and ep.date:
            same_day = [e for e in catalog if e.get("date") == ep.date]
            match = same_day[0] if len(same_day) == 1 else None
        if match:
            ep.twitch_id = ep.twitch_id or match.get("twitch_id")
            if _is_yt_id(match.get("yt_id")):
                ep.yt_id = ep.yt_id or match["yt_id"]
            ep.title = ep.title or match.get("title")
            ep.date = ep.date or match.get("date")

    if not ep.sources:
        raise SystemExit(f"No Twitch or YouTube source known for {target!r}.")
    return ep


# ---------------------------------------------------------------------------
# Pillow helpers


def _font(size: int, candidates: list[Path] = BOLD_FONTS) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _fit_font(text: str, max_w: int, start: int, candidates: list[Path] = BOLD_FONTS) -> ImageFont.FreeTypeFont:
    size = start
    font = _font(size, candidates)
    while font.getlength(text) > max_w and size > 12:
        size -= 2
        font = _font(size, candidates)
    return font


def _draw_centered(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill, **kw) -> None:
    w = font.getlength(text)
    draw.text(((OUT_W - w) / 2, y), text, font=font, fill=fill, **kw)


def _default_watermark(path: Path) -> Path:
    icon = Image.open(STATIC_DIR / "icon.png").convert("RGBA").resize((96, 96), Image.LANCZOS)
    title_font = _font(30)
    sub_font = _font(26, REGULAR_FONTS)
    lines = [("BARELY INFORMED NEWS", title_font), (TWITCH_CHANNEL_URL, sub_font)]
    text_w = int(max(f.getlength(t) for t, f in lines))
    img = Image.new("RGBA", (12 + 96 + 18 + text_w + 28, 120), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=24, fill=(0, 0, 0, 150))
    img.alpha_composite(icon, (12, 12))
    draw.text((126, 20), lines[0][0], font=title_font, fill=(255, 255, 255, 255))
    draw.text((126, 64), lines[1][0], font=sub_font, fill=(203, 213, 225, 255))
    img.save(path)
    return path


def _default_end_card(path: Path) -> Path:
    img = Image.new("RGBA", (OUT_W, OUT_H), (13, 17, 28, 255))
    draw = ImageDraw.Draw(img)
    _draw_centered(draw, 320, "BARELY INFORMED NEWS", _fit_font("BARELY INFORMED NEWS", 980, 76), (255, 255, 255, 255))
    _draw_centered(draw, 440, "LIVE ON TWITCH", _font(44), (56, 189, 248, 255))

    og = Image.open(STATIC_DIR / "og-image.png").convert("RGBA")
    # Drop the "CANON WIKI" character bar along the bottom of the site preview image.
    og = og.crop((0, 0, og.width, round(og.height * 0.73)))
    og = og.resize((OUT_W, round(og.height * OUT_W / og.width)), Image.LANCZOS)
    img.alpha_composite(og, (0, 560))

    pill_font = _font(54)
    pill_w = pill_font.getlength(TWITCH_CHANNEL_URL) + 80
    top = 560 + og.height + 90
    draw.rounded_rectangle(((OUT_W - pill_w) / 2, top, (OUT_W + pill_w) / 2, top + 110), radius=28, fill=(239, 68, 68, 255))
    _draw_centered(draw, top + 22, TWITCH_CHANNEL_URL, pill_font, (255, 255, 255, 255))
    _draw_centered(draw, top + 170, "Episode guide & lore: binlore.wiki", _font(40, REGULAR_FONTS), (156, 163, 175, 255))
    img.convert("RGB").save(path)
    return path


# ---------------------------------------------------------------------------
# Preview


def parse_crop(value: str | float) -> list[tuple[float, float]]:
    """Parse ``0.45`` or a per-shot schedule like ``0.40,12.3=0.62,22=0.40``.

    Schedule times are seconds into the clip; each entry holds until the next.
    """
    schedule: list[tuple[float, float]] = []
    for part in str(value).split(","):
        part = part.strip()
        t, _, x = part.rpartition("=")
        at = float(t) if t else 0.0
        cx = float(x)
        if not 0 <= cx <= 1:
            raise SystemExit(f"crop-x {cx} must be between 0 and 1")
        schedule.append((at, cx))
    schedule.sort()
    if schedule[0][0] > 0:
        schedule.insert(0, (0.0, 0.5))
    return schedule


def _crop_x_expr(schedule: list[tuple[float, float]]) -> str:
    def window(cx: float) -> str:
        return f"min(max(iw*{cx:.4f}-{OUT_W // 2},0),iw-{OUT_W})"

    expr = window(schedule[-1][1])
    for (_, cx), (next_t, _) in zip(reversed(schedule[:-1]), reversed(schedule[1:])):
        expr = f"if(lt(t,{next_t:.3f}),{window(cx)},{expr})"
    return expr


def detect_shots(source: Path, lead: float, duration: float, threshold: float = 0.3) -> list[float]:
    """Clip-relative times of hard cuts (camera/scene switches) in the slice."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{lead:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
         "-vf", f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    return [round(float(t), 2) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def shot_sheet(source: Path, lead: float, duration: float, shots: list[float], out: Path) -> Path:
    """Contact sheet with one labeled frame per shot and a crop-x ruler under each."""
    bounds = [0.0, *[t for t in shots if 0 < t < duration], duration]
    thumb_w, cols = 480, 4
    tiles = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        frame = out.parent / f".shot{i}.jpg"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{lead + (a + b) / 2:.3f}",
             "-i", str(source), "-frames:v", "1", "-vf", f"scale={thumb_w}:-2", str(frame)],
            check=True,
        )
        img = Image.open(frame).convert("RGB")
        frame.unlink()
        tile = Image.new("RGB", (thumb_w, img.height + 34), (24, 24, 24))
        tile.paste(img, (0, 0))
        d = ImageDraw.Draw(tile)
        for k in range(11):
            x = min(round(k / 10 * thumb_w), thumb_w - 1)
            d.line((x, img.height, x, img.height + 8), fill=(255, 225, 77), width=2)
            if 0 < k < 10:
                d.text((x - 9, img.height + 10), f".{k}", font=_font(16, REGULAR_FONTS), fill=(220, 220, 220))
        d.rectangle((0, 0, 190, 30), fill=(0, 0, 0))
        d.text((6, 4), f"#{i}  {a:.2f}-{b:.2f}s", font=_font(20, REGULAR_FONTS), fill=(255, 255, 255))
        tiles.append(tile)
    rows = -(-len(tiles) // cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * tiles[0].height), (0, 0, 0))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * thumb_w, (i // cols) * tile.height))
    sheet.save(out, quality=85)
    return out


def crop_window(frame_w: int, frame_h: int, crop_x: float) -> tuple[int, int]:
    """Left edge and width (source pixels) of the 9:16 window centered at ``crop_x``."""
    win_w = round(frame_h * OUT_W / OUT_H)
    left = round(min(max(frame_w * crop_x - win_w / 2, 0), frame_w - win_w))
    return left, win_w


def _grab_frame(ep: Episode, at: float, out: Path) -> Path:
    errors = []
    for url in ep.sources:
        try:
            return extract_frame(get_stream_url(url), fmt_hms(at), out)
        except RuntimeError as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("Could not grab a frame from any source:\n" + "\n".join(errors))


def preview(target: str | None, at: str, crop_x: float = 0.5) -> Path:
    ep = resolve_episode(target)
    seconds = parse_ts(at)
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{ep.label}-{fmt_hms(seconds).replace(':', '').zfill(6)}"
    raw = _grab_frame(ep, seconds, PREVIEWS_DIR / f"{stem}-raw.jpg")

    frame = Image.open(raw).convert("RGBA")
    W, H = frame.size
    left, win_w = crop_window(W, H, crop_x)

    shade = Image.new("RGBA", frame.size, (0, 0, 0, 140))
    shade.paste((0, 0, 0, 0), (left, 0, left + win_w, H))
    marked = Image.alpha_composite(frame, shade)
    ImageDraw.Draw(marked).rectangle((left, 0, left + win_w - 1, H - 1), outline=(255, 225, 77, 255), width=6)

    panel = frame.crop((left, 0, left + win_w, H))
    guides = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(guides)
    s = H / OUT_H
    g.rectangle((0, 0, win_w, OUT_H * 0.10 * s), fill=(239, 68, 68, 70))
    g.rectangle((0, OUT_H * 0.85 * s, win_w, H), fill=(239, 68, 68, 70))
    g.rectangle((0, CAPTION_Y * s, win_w - 1, (CAPTION_Y + CAPTION_H) * s), outline=(56, 189, 248, 255), width=3)
    g.rectangle((WATERMARK_X * s, WATERMARK_Y * s, (WATERMARK_X + 520) * s, (WATERMARK_Y + 120) * s), outline=(255, 255, 255, 200), width=2)
    panel = Image.alpha_composite(panel, guides)

    sheet = Image.new("RGB", (W + 24 + win_w, H), (40, 40, 40))
    sheet.paste(marked.convert("RGB"), (0, 0))
    sheet.paste(panel.convert("RGB"), (W + 24, 0))
    out = PREVIEWS_DIR / f"{stem}-x{crop_x:.2f}.jpg"
    sheet.save(out, quality=88)
    raw.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------------------
# Slicing


def _stream_urls(url: str) -> list[str]:
    """Direct media URL(s) for a VOD: one HLS URL for Twitch, video+audio for YouTube."""
    if "twitch.tv" in url:
        fmt = "best[height<=1080]/best"
    else:
        fmt = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b"
    proc = subprocess.run([*get_yt_dlp_cmd(), "-f", fmt, "-g", url], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "yt-dlp failed")
    urls = [line for line in proc.stdout.splitlines() if line.strip()]
    if not urls:
        raise RuntimeError("yt-dlp returned no stream URL")
    return urls


def slice_source(ep: Episode, start: float, end: float, out: Path) -> tuple[str, float]:
    """Download ``[start - pad, end + pad]`` re-encoded to ``out``.

    Returns the source URL used and the lead (seconds of padding before ``start``).
    """
    ss = max(0.0, start - SLICE_PAD)
    lead = start - ss
    duration = (end - start) + lead + SLICE_PAD
    # Input-side seeks into HLS land on the next keyframe *after* the target, so
    # seek coarsely well before it and trim precisely on the output side.
    coarse = max(0.0, ss - SEEK_PREROLL)
    out.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for url in ep.sources:
        try:
            media = _stream_urls(url)
        except RuntimeError as e:
            errors.append(f"{url}: {e}")
            continue
        print(f"Slicing {fmt_hms(ss)} +{duration:.1f}s from {url}", flush=True)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats"]
        for m in media:
            cmd += ["-ss", f"{coarse:.3f}", "-i", m]
        cmd += ["-ss", f"{ss - coarse:.3f}", "-t", f"{duration:.3f}"]
        if len(media) > 1:
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", "-y", str(out)]
        proc = subprocess.run(cmd)
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return url, lead
        errors.append(f"{url}: ffmpeg exited {proc.returncode}")
    raise RuntimeError("Could not slice the clip from any source:\n" + "\n".join(errors))


# ---------------------------------------------------------------------------
# Captions


def transcribe_words(media: Path, model_name: str, prompt: str | None = None) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel

    print(f"Transcribing {media.name} with faster-whisper {model_name} (word timestamps)...", flush=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(media),
        language="en",
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=prompt,
    )
    return [
        {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
        for seg in segments
        for w in seg.words or []
        if w.word.strip()
    ]


def _core(word: str) -> str:
    return re.sub(r"^\W+|\W+$", "", word)


def apply_fixes(words: list[dict[str, Any]], fixes: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Replace misheard words/phrases (``wrong`` may span several words)."""
    for wrong, right in fixes:
        target = [_core(t).lower() for t in wrong.split()]
        n = len(target)
        out: list[dict[str, Any]] = []
        i = 0
        while i < len(words):
            window = words[i : i + n]
            if len(window) == n and [_core(w["word"]).lower() for w in window] == target:
                trail = re.search(r"\W*$", window[-1]["word"]).group()
                out.append({"start": window[0]["start"], "end": window[-1]["end"], "word": right + trail})
                i += n
            else:
                out.append(words[i])
                i += 1
        words = out
    return words


def chunk_words(
    words: list[dict[str, Any]], *, max_words: int = 4, max_chars: int = 20, max_gap: float = 0.5
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        if cur:
            prev = cur[-1]["word"]
            too_long = len(" ".join(x["word"] for x in cur + [w])) > max_chars
            if (
                len(cur) >= max_words
                or too_long
                or w["start"] - cur[-1]["end"] > max_gap
                or prev[-1:] in ".?!"
                or (prev[-1:] in ",;:" and len(cur) >= 2)
            ):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _display(word: str) -> str:
    return word.strip().strip("\"'“”").upper().rstrip(",.;:")


def _chunk_times(chunks: list[list[dict[str, Any]]], duration: float) -> list[tuple[float, float]]:
    times = []
    for i, chunk in enumerate(chunks):
        end = chunk[-1]["end"] + 0.35
        if i + 1 < len(chunks):
            end = min(end, chunks[i + 1][0]["start"])
        times.append((chunk[0]["start"], min(end, duration)))
    return times


def write_srt(chunks: list[list[dict[str, Any]]], duration: float, path: Path) -> Path:
    blocks = []
    for n, (chunk, (s, e)) in enumerate(zip(chunks, _chunk_times(chunks, duration)), 1):
        text = " ".join(w["word"] for w in chunk)
        blocks.append(f"{n}\n{_srt_ts(s)} --> {_srt_ts(e)}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def _layout_caption(texts: list[str]):
    """Wrap a chunk onto at most two centered lines, shrinking the font if needed."""
    for size in range(CAPTION_FONT_SIZE, 47, -6):
        font = _font(size)
        space = font.getlength(" ")
        lines: list[list[tuple[int, str, float]]] = [[]]
        widths = [0.0]
        for i, t in enumerate(texts):
            w = font.getlength(t) + 2 * CAPTION_STROKE
            extra = w if not lines[-1] else space + w
            if lines[-1] and widths[-1] + extra > CAPTION_MAX_TEXT_W:
                lines.append([(i, t, w)])
                widths.append(w)
            else:
                lines[-1].append((i, t, w))
                widths[-1] += extra
        if len(lines) <= 2 and max(widths) <= CAPTION_MAX_TEXT_W:
            break
    return font, space, lines, widths


def _draw_caption(layout, active: int) -> Image.Image:
    font, space, lines, widths = layout
    img = Image.new("RGBA", (CAPTION_W, CAPTION_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line_h = font.size * 1.18
    y = (CAPTION_H - line_h * len(lines)) / 2
    for line, width in zip(lines, widths):
        x = (CAPTION_W - width) / 2
        for i, text, w in line:
            draw.text(
                (x + CAPTION_STROKE, y),
                text,
                font=font,
                fill=CAPTION_ACTIVE_FILL if i == active else CAPTION_FILL,
                stroke_width=CAPTION_STROKE,
                stroke_fill=(0, 0, 0, 255),
            )
            x += w + space
        y += line_h
    return img


def build_caption_track(chunks: list[list[dict[str, Any]]], duration: float, workdir: Path) -> Path:
    """Render one PNG per spoken word and an ffconcat list timing them to the clip."""
    frames = workdir / "captions"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    blank = frames / "blank.png"
    Image.new("RGBA", (CAPTION_W, CAPTION_H), (0, 0, 0, 0)).save(blank)

    timeline: list[tuple[Path, float, float]] = []
    for ci, (chunk, (c_start, c_end)) in enumerate(zip(chunks, _chunk_times(chunks, duration))):
        texts = [_display(w["word"]) for w in chunk]
        layout = _layout_caption(texts)
        for wi in range(len(chunk)):
            s = c_start if wi == 0 else chunk[wi]["start"]
            e = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else c_end
            png = frames / f"c{ci:04d}_{wi}.png"
            _draw_caption(layout, wi).save(png)
            timeline.append((png, s, e))

    lines = ["ffconcat version 1.0"]
    t = 0.0
    last = blank
    for png, s, e in timeline:
        s = max(s, t)
        if e - s < 1 / FPS:
            continue
        if s - t >= 1 / FPS:
            lines += [f"file '{blank}'", f"duration {s - t:.3f}"]
        lines += [f"file '{png}'", f"duration {e - s:.3f}"]
        t, last = e, png
    if duration - t >= 1 / FPS:
        lines += [f"file '{blank}'", f"duration {duration - t:.3f}"]
        last = blank
    lines.append(f"file '{last}'")
    listing = workdir / "captions.ffconcat"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


# ---------------------------------------------------------------------------
# Render


def _probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
        "video": next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}),
    }


def render(
    source: Path,
    *,
    lead: float,
    duration: float,
    crop: list[tuple[float, float]],
    captions: Path,
    watermark: Path,
    stinger: Path | None,
    out: Path,
) -> Path:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y"]
    cmd += ["-ss", f"{lead:.3f}", "-t", f"{duration:.3f}", "-i", str(source)]
    cmd += ["-i", str(watermark)]
    cmd += ["-f", "concat", "-safe", "0", "-i", str(captions)]

    fade_at = max(duration - 0.25, 0)
    graph = [
        f"[0:v]scale=-2:{OUT_H}:flags=lanczos,"
        f"crop={OUT_W}:{OUT_H}:x='{_crop_x_expr(crop)}':y=0,"
        f"setsar=1,fps={FPS}[base]",
        f"[2:v]format=rgba[cap]",
        f"[base][cap]overlay=x=0:y={CAPTION_Y}[v1]",
        f"[1:v]format=rgba,colorchannelmixer=aa={WATERMARK_OPACITY}[wm]",
        f"[v1][wm]overlay=x={WATERMARK_X}:y={WATERMARK_Y},format=yuv420p[main]",
        f"[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,"
        f"aformat=sample_fmts=fltp:channel_layouts=stereo,afade=t=out:st={fade_at:.3f}:d=0.25[a]",
    ]

    if stinger is None:
        maps = ["-map", "[main]", "-map", "[a]"]
    else:
        if stinger.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            sting_len, sting_audio = END_CARD_SECONDS, False
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{sting_len}", "-i", str(stinger)]
        else:
            info = _probe(stinger)
            sting_len, sting_audio = info["duration"], info["has_audio"]
            cmd += ["-i", str(stinger)]
        if not sting_audio:
            cmd += ["-f", "lavfi", "-t", f"{sting_len:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_in = "3:a" if sting_audio else "4:a"
        graph += [
            f"[3:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},"
            f"fade=t=in:st=0:d=0.25,format=yuv420p[sv]",
            f"[{audio_in}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[sa]",
            "[main][a][sv][sa]concat=n=2:v=1:a=1[outv][outa]",
        ]
        maps = ["-map", "[outv]", "-map", "[outa]"]

    cmd += ["-filter_complex", ";".join(graph), *maps]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
        str(out),
    ]
    print("Rendering vertical clip...", flush=True)
    subprocess.run(cmd, check=True)
    return out


# ---------------------------------------------------------------------------
# Packaging


def _hashtags(tags: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for t in [*BASE_HASHTAGS, *tags]:
        t = re.sub(r"[^\w]", "", t.lstrip("#"))
        if t and t.lower() not in seen:
            seen[t.lower()] = t
    return [f"#{t}" for t in seen.values()]


def write_post(
    out_dir: Path,
    *,
    ep: Episode,
    start: float,
    end: float,
    crop_x: str,
    title: str,
    hook: str,
    wiki: list[str],
    tags: list[str],
    clip_len: float,
) -> Path:
    shorts_title = title if len(title) + len(" #Shorts") <= 100 else title[: 100 - len("… #Shorts")].rstrip() + "…"
    shorts_title += " #Shorts"
    hashtags = _hashtags(tags)
    vod_link = ep.twitch_link(start) or ep.yt_link(start)

    wiki_links = []
    for page in wiki:
        page = page.strip("/").removesuffix(".md")
        if not (CONTENT_DIR / f"{page}.md").exists():
            print(f"warning: no wiki page content/{page}.md", flush=True)
        wiki_links.append(f"{WIKI_BASE}/{page}")
    if ep.wiki_url:
        wiki_links.append(ep.wiki_url)

    sources = [
        f"[Twitch @ {fmt_hms(start)}]({ep.twitch_link(start)})" if ep.twitch_url else None,
        f"[YouTube @ {fmt_hms(start)}]({ep.yt_link(start)})" if ep.yt_url else None,
    ]
    episode_name = f"{ep.title} ({ep.date})" if ep.title else ep.label
    episode_line = f"[{episode_name}]({ep.wiki_url})" if ep.wiki_url else episode_name

    yt_description = "\n".join(
        [
            hook,
            "",
            f"Full episode: {vod_link}",
            f"Live on Twitch: https://{TWITCH_CHANNEL_URL}",
            *(f"Lore: {u}" for u in wiki_links),
            "",
            " ".join(hashtags[:5]),
        ]
    )
    tiktok = f"{hook}\n\n" + " ".join([t.lower() for t in hashtags] + ["#fyp"])
    reels = "\n".join(
        [
            hook,
            "",
            f"Barely Informed News, live on {TWITCH_CHANNEL_URL}",
            "Lore & episode guide: binlore.wiki",
            "",
            " ".join(hashtags + ["#reels"]),
        ]
    )

    md = f"""# {title}

- **Episode:** {episode_line}
- **Source:** {" · ".join(s for s in sources if s)}
- **Window:** {fmt_hms(start)} → {fmt_hms(end)} ({end - start:.0f}s clip, {clip_len:.1f}s total), crop-x `{crop_x}`
- **Files:** `clip.mp4`, `thumbnail.jpg`, `captions.srt`

## YouTube Shorts

Title ({len(shorts_title)}/100):

```
{shorts_title}
```

Description:

```
{yt_description}
```

## TikTok

```
{tiktok}
```

## Instagram Reels

```
{reels}
```
"""
    path = out_dir / "post.md"
    path.write_text(md, encoding="utf-8")
    return path


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise SystemExit("--slug must contain letters or digits")
    return slug


def make_clip(
    target: str | None,
    *,
    start: str,
    end: str,
    slug: str,
    crop_x: str | None = None,
    title: str | None = None,
    hook: str | None = None,
    wiki: list[str] | None = None,
    tags: list[str] | None = None,
    stinger: bool = True,
    redownload: bool = False,
    retranscribe: bool = False,
    whisper_model: str = "small",
    thumb_at: float | None = None,
    fixes: list[str] | None = None,
) -> Path:
    start_s, end_s = parse_ts(start), parse_ts(end)
    duration = end_s - start_s
    if duration <= 0:
        raise SystemExit("--end must be after --start")
    if duration > 180:
        raise SystemExit(f"Clip is {duration:.0f}s; YouTube Shorts caps at 180s.")
    if not 20 <= duration <= 75:
        print(f"note: {duration:.0f}s is outside the 20-75s sweet spot", flush=True)

    ep = resolve_episode(target)
    out_dir = CLIPS_DIR / f"{ep.label}-{_slugify(slug)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "meta.json"
    meta: dict[str, Any] = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    source = out_dir / "source.mp4"
    window = [round(start_s, 3), round(end_s, 3)]
    if redownload or not source.exists() or meta.get("window") != window:
        source_url, lead = slice_source(ep, start_s, end_s, source)
        meta.update(window=window, source_url=source_url, lead=lead)
        meta["shots"] = detect_shots(source, lead, duration)
        shot_sheet(source, lead, duration, meta["shots"], out_dir / "shots.jpg")
        retranscribe = True
    lead = meta["lead"]
    if meta.get("shots"):
        print("Shot changes (seconds into clip): " + ", ".join(f"{t:.2f}" for t in meta["shots"]), flush=True)
        print(f"Shot contact sheet: {out_dir / 'shots.jpg'}", flush=True)

    words_path = out_dir / "words.json"
    if retranscribe or not words_path.exists() or meta.get("whisper_model") != whisper_model:
        prompt = "Barely Informed News with Case Blackwell."
        if ep.characters:
            prompt += " Characters: " + ", ".join(ep.characters[:25]) + "."
        words_path.write_text(json.dumps(transcribe_words(source, whisper_model, prompt), indent=1), encoding="utf-8")
        meta["whisper_model"] = whisper_model
    raw_words = json.loads(words_path.read_text(encoding="utf-8"))

    all_fixes = list(dict.fromkeys([*meta.get("fixes", []), *(fixes or [])]))
    pairs = []
    for f in all_fixes:
        if "=>" not in f:
            raise SystemExit(f"--fix {f!r} must look like 'wrong=>right'")
        wrong, right = (p.strip() for p in f.split("=>", 1))
        pairs.append((wrong, right))
    words = []
    for w in apply_fixes(raw_words, pairs):
        s, e = w["start"] - lead, w["end"] - lead
        if e <= 0.05 or s >= duration - 0.05:
            continue
        words.append({"start": max(s, 0.0), "end": min(e, duration), "word": w["word"]})
    chunks = chunk_words(words)
    write_srt(chunks, duration, out_dir / "captions.srt")

    crop_x = str(crop_x if crop_x is not None else meta.get("crop_x", "0.5"))
    crop = parse_crop(crop_x)
    title = title or meta.get("title") or slug.replace("-", " ").title()
    hook = hook or meta.get("hook") or title
    wiki = wiki or meta.get("wiki", [])
    tags = tags or meta.get("tags", [])

    workdir = out_dir / ".work"
    workdir.mkdir(exist_ok=True)
    captions = build_caption_track(chunks, duration, workdir)
    watermark = ASSETS_DIR / "watermark.png"
    if not watermark.exists():
        watermark = _default_watermark(workdir / "watermark.png")
    sting = None
    if stinger:
        sting = ASSETS_DIR / "stinger.mp4"
        if not sting.exists():
            sting = _default_end_card(workdir / "end_card.png")

    clip = render(
        source,
        lead=lead,
        duration=duration,
        crop=crop,
        captions=captions,
        watermark=watermark,
        stinger=sting,
        out=out_dir / "clip.mp4",
    )
    clip_len = _probe(clip)["duration"]

    thumb_t = thumb_at if thumb_at is not None else min(2.0, duration / 2)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{thumb_t:.3f}", "-i", str(clip),
         "-frames:v", "1", "-q:v", "2", str(out_dir / "thumbnail.jpg")],
        check=True,
    )
    write_post(
        out_dir, ep=ep, start=start_s, end=end_s, crop_x=crop_x, title=title, hook=hook,
        wiki=wiki, tags=tags, clip_len=clip_len,
    )

    meta.update(
        episode=ep.label, start=fmt_hms(start_s), end=fmt_hms(end_s), crop_x=crop_x, title=title,
        hook=hook, wiki=wiki, tags=tags, fixes=all_fixes, stinger=stinger, clip_seconds=round(clip_len, 2),
    )
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    shutil.rmtree(workdir, ignore_errors=True)
    return out_dir
