from __future__ import annotations

from pathlib import Path

# tools/binlore_tools/paths.py -> repo root is parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = REPO_ROOT / "tools"
RUNS_DIR = TOOLS_ROOT / "runs"
CONTENT_EPISODES = REPO_ROOT / "content" / "episodes"

CHANNEL = "caseblackwell"
CHANNEL_VIDEOS_URL = f"https://www.twitch.tv/{CHANNEL}/videos"
