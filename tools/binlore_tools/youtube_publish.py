"""Publish a rendered clip folder to the BIN Lore YouTube channel via the Data API.

Replaces the Studio computer-use upload path for Shorts. YouTube classifies a
vertical video of 3 minutes or less as a Short automatically; there is no
separate Shorts endpoint.

One-time setup (see tools/youtube_api/README.md):

1. Enable YouTube Data API v3 on a Google Cloud project.
2. Create a Desktop OAuth client and save it as tools/youtube_api/client_secret.json.
3. Run ``./binlore clips youtube-auth`` as binlorewiki@gmail.com.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

from .clips import CLIPS_DIR, CLIPS_REGISTRY, sync_clips
from .paths import REPO_ROOT, TOOLS_ROOT

API_DIR = TOOLS_ROOT / "youtube_api"
CLIENT_SECRET_FILE = API_DIR / "client_secret.json"
TOKEN_FILE = API_DIR / "token.json"

# youtube.upload: videos.insert + thumbnails.set
# youtube.force-ssl: videos.list (processing) + captions.insert
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CATEGORY_COMEDY = "23"
BIN_LORE_CHANNEL_ID = "UCuiEeDV0bv5WS4FlpIdD_5Q"
BIN_LORE_GOOGLE_EMAIL = "binlorewiki@gmail.com"
PRIVACY_STATUSES = ("public", "unlisted", "private")


class YoutubePublishError(SystemExit):
    """Fatal publish failure that should exit the CLI with a message."""


def _require_google_libs() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise YoutubePublishError(
            "Missing YouTube upload deps. From tools/: "
            "pip install 'google-api-python-client google-auth-oauthlib google-auth-httplib2'"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, MediaFileUpload


def resolve_clip_dir(target: str | Path) -> Path:
    """Accept an absolute/relative clip folder, or a slug under tools/clips/."""
    raw = Path(target).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(Path.cwd() / raw)
        candidates.append(CLIPS_DIR / raw.name)
        candidates.append(CLIPS_DIR / str(raw))
    for path in candidates:
        path = path.resolve()
        if path.is_dir() and (path / "clip.mp4").exists():
            return path
    raise YoutubePublishError(
        f"No clip folder with clip.mp4 at {target!r}. "
        f"Pass tools/clips/<date>-<slug> or that folder's absolute path."
    )


def parse_post_md(post_path: Path) -> dict[str, Any]:
    """Pull the YouTube Shorts title, description, tags, and recording date from post.md."""
    text = post_path.read_text(encoding="utf-8")
    yt = re.search(r"## YouTube Shorts\n(.*?)(?=\n## |\Z)", text, re.S)
    if not yt:
        raise YoutubePublishError(f"{post_path}: missing ## YouTube Shorts section")
    block = yt.group(1)

    title_m = re.search(r"Title \(.*?\):\n\n```\n(.*?)\n```", block, re.S)
    desc_m = re.search(r"Description:\n\n```\n(.*?)\n```", block, re.S)
    tags_m = re.search(r"Tags \(.*?\):\n\n```\n(.*?)\n```", block, re.S)
    date_m = re.search(r"Recording date:\s*(\d{4}-\d{2}-\d{2})", block)
    if not title_m or not desc_m:
        raise YoutubePublishError(f"{post_path}: could not parse YouTube title/description")

    title = title_m.group(1).strip()
    description = desc_m.group(1).strip()
    tags: list[str] = []
    if tags_m:
        tags = [t.strip() for t in tags_m.group(1).split(",") if t.strip()]
    if len(title) > 100:
        raise YoutubePublishError(f"YouTube title is {len(title)} chars (max 100): {title!r}")
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "recording_date": date_m.group(1) if date_m else None,
    }


def load_clip_bundle(clip_dir: Path) -> dict[str, Any]:
    clip = clip_dir / "clip.mp4"
    post = clip_dir / "post.md"
    meta_path = clip_dir / "meta.json"
    thumb = clip_dir / "thumbnail.jpg"
    captions = clip_dir / "captions.srt"
    if not clip.exists():
        raise YoutubePublishError(f"Missing {clip}")
    if not post.exists():
        raise YoutubePublishError(f"Missing {post}")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    fields = parse_post_md(post)
    return {
        "dir": clip_dir,
        "clip": clip,
        "post": post,
        "meta": meta,
        "thumbnail": thumb if thumb.exists() else None,
        "captions": captions if captions.exists() else None,
        **fields,
    }


def _assert_bin_lore_channel(youtube: Any, *, force: bool = False) -> dict[str, str]:
    """Ensure the authorized account owns BIN Lore. Refuse other Google accounts."""
    mine = youtube.channels().list(part="snippet,id", mine=True).execute()
    items = mine.get("items") or []
    if not items:
        raise YoutubePublishError(
            f"Authorized, but no YouTube channel is on this Google account. "
            f"Sign in as {BIN_LORE_GOOGLE_EMAIL}."
        )
    channel = items[0]
    channel_id = channel["id"]
    title = channel["snippet"]["title"]
    if channel_id != BIN_LORE_CHANNEL_ID and not force:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        raise YoutubePublishError(
            f"Wrong YouTube channel: {title!r} ({channel_id}). "
            f"Expected BIN Lore ({BIN_LORE_CHANNEL_ID}) under {BIN_LORE_GOOGLE_EMAIL}. "
            f"Re-run ./binlore clips youtube-auth and pick that account "
            f"(Google may show several — use the account picker). "
            f"Pass --force only if you intentionally want a different channel."
        )
    return {"id": channel_id, "title": title}


def _register_chrome_browser() -> str:
    """Register Google Chrome with the webbrowser module; return its controller name.

    ``run_local_server(browser=...)`` takes a *name* looked up via ``webbrowser.get``,
    not a controller object. Without this, macOS opens the default browser (Brave here).
    """
    name = "binlore-chrome"

    class _ChromeBrowser(webbrowser.BaseBrowser):
        def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:  # noqa: A003
            chrome_app = Path("/Applications/Google Chrome.app")
            if chrome_app.exists():
                subprocess.run(["open", "-a", "Google Chrome", url], check=False)
                return True
            return bool(webbrowser.open(url, new=new, autoraise=autoraise))

    # preferred=True so accidental webbrowser.open fallbacks also hit Chrome.
    webbrowser.register(name, None, _ChromeBrowser(name), preferred=True)
    return name


def authorize(*, port: int = 0, no_browser: bool = False, force: bool = False) -> Path:
    """Run the OAuth consent flow and save a refresh token to tools/youtube_api/token.json.

    Always hints Google toward ``binlorewiki@gmail.com`` and forces the account
    picker so a laptop with many Google logins does not silently reuse the wrong one.
    Opens Google Chrome explicitly (never the system default browser).
    """
    Request, Credentials, InstalledAppFlow, build, _Media = _require_google_libs()
    API_DIR.mkdir(parents=True, exist_ok=True)
    if not CLIENT_SECRET_FILE.exists():
        raise YoutubePublishError(
            f"Missing {CLIENT_SECRET_FILE}. Download a Desktop OAuth client JSON from "
            "Google Cloud Console (YouTube Data API v3 enabled) and save it there. "
            "See tools/youtube_api/README.md."
        )

    print(
        f"Authorize the BIN Lore channel as {BIN_LORE_GOOGLE_EMAIL}.\n"
        "Opening Google Chrome for the account picker — choose that address, "
        "not another login on this laptop.",
        flush=True,
    )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    # login_hint pre-fills the email; prompt=select_account forces the multi-account chooser.
    auth_kwargs = {
        "login_hint": BIN_LORE_GOOGLE_EMAIL,
        "prompt": "select_account consent",
        "access_type": "offline",
        "include_granted_scopes": "true",
    }

    if no_browser:
        creds = flow.run_local_server(port=port or 8080, open_browser=False, **auth_kwargs)
    else:
        chrome = _register_chrome_browser()
        creds = flow.run_local_server(
            port=port or 0,
            open_browser=True,
            browser=chrome,
            **auth_kwargs,
        )
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    TOKEN_FILE.chmod(0o600)

    youtube = build("youtube", "v3", credentials=creds)
    try:
        channel = _assert_bin_lore_channel(youtube, force=force)
    except YoutubePublishError:
        raise
    print(f"✓ Authorized as {channel['title']} ({channel['id']}) via {BIN_LORE_GOOGLE_EMAIL}")
    print(f"  Token saved to {TOKEN_FILE}")
    return TOKEN_FILE


def get_youtube_service(*, force_channel: bool = False) -> Any:
    Request, Credentials, _Flow, build, _Media = _require_google_libs()
    if not TOKEN_FILE.exists():
        raise YoutubePublishError(
            f"No OAuth token at {TOKEN_FILE}. Run: ./binlore clips youtube-auth"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            TOKEN_FILE.chmod(0o600)
        else:
            raise YoutubePublishError(
                f"OAuth token at {TOKEN_FILE} is invalid. Re-run: ./binlore clips youtube-auth"
            )
    youtube = build("youtube", "v3", credentials=creds)
    _assert_bin_lore_channel(youtube, force=force_channel)
    return youtube


def _video_body(bundle: dict[str, Any], *, privacy: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "snippet": {
            "title": bundle["title"],
            "description": bundle["description"],
            "tags": bundle["tags"],
            "categoryId": CATEGORY_COMEDY,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
            "license": "youtube",
            "embeddable": True,
            "publicStatsViewable": True,
        },
        "paidProductPlacementDetails": {
            "hasPaidProductPlacement": False,
        },
    }
    if bundle.get("recording_date"):
        body["recordingDetails"] = {
            "recordingDate": f"{bundle['recording_date']}T00:00:00.000Z",
        }
    return body


def wait_until_processed(youtube: Any, video_id: str, *, timeout_s: float = 600.0) -> str:
    """Poll until processing finishes. Returns the final processingStatus."""
    deadline = time.time() + timeout_s
    last = "unknown"
    while time.time() < deadline:
        resp = (
            youtube.videos()
            .list(part="processingDetails,status", id=video_id)
            .execute()
        )
        items = resp.get("items") or []
        if not items:
            time.sleep(3)
            continue
        details = items[0].get("processingDetails") or {}
        last = details.get("processingStatus") or items[0].get("status", {}).get("uploadStatus") or "unknown"
        if last in {"succeeded", "failed", "terminated"}:
            return last
        print(f"  processing: {last}…", flush=True)
        time.sleep(5)
    return last


def set_thumbnail(youtube: Any, video_id: str, thumb_path: Path, MediaFileUpload: Any) -> None:
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg", resumable=False),
    ).execute()


def upload_captions(
    youtube: Any, video_id: str, captions_path: Path, MediaFileUpload: Any
) -> None:
    body = {
        "snippet": {
            "videoId": video_id,
            "language": "en",
            "name": "English",
            "isDraft": False,
        }
    }
    youtube.captions().insert(
        part="snippet",
        body=body,
        media_body=MediaFileUpload(str(captions_path), mimetype="application/octet-stream", resumable=True),
    ).execute()


def register_clip_youtube(bundle: dict[str, Any], video_id: str) -> dict[str, Any]:
    """Insert or update this clip's row in data/clips.json with the YouTube id."""
    meta = bundle["meta"]
    clip_dir: Path = bundle["dir"]
    slug = clip_dir.name
    entry = {
        "slug": slug,
        "episode": meta.get("episode") or slug[:10],
        "title": meta.get("title") or bundle["title"].removesuffix(" #Shorts").strip(),
        "wiki": list(meta.get("wiki") or []),
        "youtube": video_id,
    }
    registry: list[dict[str, Any]] = []
    if CLIPS_REGISTRY.exists():
        registry = json.loads(CLIPS_REGISTRY.read_text(encoding="utf-8"))
    for i, existing in enumerate(registry):
        if existing.get("slug") == slug:
            merged = {**existing, **entry}
            # Preserve tiktok fields if already present.
            registry[i] = merged
            CLIPS_REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
            return merged
    registry.append(entry)
    CLIPS_REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return entry


def publish_youtube(
    target: str | Path,
    *,
    privacy: str = "public",
    dry_run: bool = False,
    skip_thumbnail: bool = False,
    skip_captions: bool = True,
    no_wiki: bool = False,
    notify_subscribers: bool = False,
    force_channel: bool = False,
) -> dict[str, Any]:
    if privacy not in PRIVACY_STATUSES:
        raise YoutubePublishError(f"--privacy must be one of {', '.join(PRIVACY_STATUSES)}")

    clip_dir = resolve_clip_dir(target)
    bundle = load_clip_bundle(clip_dir)
    body = _video_body(bundle, privacy=privacy)
    parts = ["snippet", "status", "paidProductPlacementDetails"]
    if "recordingDetails" in body:
        parts.append("recordingDetails")

    print(f"Clip:  {bundle['clip']}")
    print(f"Title: {bundle['title']}")
    print(f"Tags:  {', '.join(bundle['tags'])}")
    print(f"Date:  {bundle.get('recording_date') or '(none)'}")
    print(f"Privacy: {privacy}")
    print(f"Channel: BIN Lore ({BIN_LORE_CHANNEL_ID}) as {BIN_LORE_GOOGLE_EMAIL}")
    if dry_run:
        print("Dry run — not uploading.")
        print(json.dumps(body, indent=2))
        return {"dry_run": True, "body": body, "dir": str(clip_dir)}

    _Request, _Creds, _Flow, _build, MediaFileUpload = _require_google_libs()
    youtube = get_youtube_service(force_channel=force_channel)
    media = MediaFileUpload(str(bundle["clip"]), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    request = youtube.videos().insert(
        part=",".join(parts),
        body=body,
        media_body=media,
        notifySubscribers=notify_subscribers,
    )

    print("Uploading…", flush=True)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)}%", flush=True)
    video_id = response["id"]
    print(f"✓ Uploaded: https://youtube.com/shorts/{video_id}")
    print(f"  Studio:   https://studio.youtube.com/video/{video_id}/edit")

    if not skip_thumbnail and bundle["thumbnail"]:
        print("Waiting for processing before setting thumbnail…", flush=True)
        proc = wait_until_processed(youtube, video_id)
        if proc != "succeeded":
            print(f"  warning: processing status is {proc!r}; trying thumbnail anyway", flush=True)
        try:
            set_thumbnail(youtube, video_id, bundle["thumbnail"], MediaFileUpload)
            print(f"✓ Thumbnail: {bundle['thumbnail'].name}")
        except Exception as exc:  # noqa: BLE001 — surface API errors without aborting wiki sync
            print(f"  warning: thumbnail failed ({exc}). Set it later in Studio if the channel needs phone verification.")

    if not skip_captions and bundle["captions"]:
        try:
            # Captions need processing to finish too.
            proc = wait_until_processed(youtube, video_id)
            if proc == "succeeded":
                upload_captions(youtube, video_id, bundle["captions"], MediaFileUpload)
                print(f"✓ Captions: {bundle['captions'].name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  warning: captions upload failed ({exc})")

    entry = register_clip_youtube(bundle, video_id)
    print(f"✓ Registered in {CLIPS_REGISTRY.relative_to(REPO_ROOT)}: youtube={video_id}")

    if not no_wiki:
        changed = sync_clips()
        print(f"✓ sync-clips: {len(changed)} page(s) updated")
        # Idempotent second pass, matching the skill.
        again = sync_clips()
        if again:
            print(f"  warning: second sync-clips still changed {len(again)} page(s)")

    return {
        "video_id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}",
        "studio": f"https://studio.youtube.com/video/{video_id}/edit",
        "entry": entry,
    }
