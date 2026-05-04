"""
Per-machine app settings persisted at ~/.bicentra/settings.json.

Currently used to store the chosen video-recording tier. Designed to grow
into other knobs later (e.g. action delay, fail-safe corner).
"""

import json
import os
from typing import Any

import system_info as sysinfo

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".bicentra", "settings.json")


DEFAULTS: dict[str, Any] = {
    # "auto" means recompute the recommendation on each launch.
    # Anything else is a literal tier from system_info.ALL_TIERS.
    "video_tier": "auto",
}


def load() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH) as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        if isinstance(data, dict):
            merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULTS)


def save(settings: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


def get_video_tier(settings: dict | None = None) -> str:
    """Resolve 'auto' to the actual recommended tier."""
    settings = settings or load()
    tier = settings.get("video_tier", "auto")
    if tier == "auto":
        return sysinfo.recommend_tier()
    if tier in sysinfo.ALL_TIERS:
        return tier
    return sysinfo.recommend_tier()
