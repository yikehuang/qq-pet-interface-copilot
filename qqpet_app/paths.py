from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)

PROFILE_NAMES = {
    "legacy": "legacy",
    "mumu": "legacy",
    "legacy_mobile_bridge": "legacy",
    "standalone": "standalone",
    "pc": "standalone",
    "standalone_mobile": "standalone",
}


def normalize_profile(value: str = "") -> str:
    profile = (value or os.environ.get("QQPET_PROFILE") or "legacy").strip().casefold()
    return PROFILE_NAMES.get(profile, "legacy")


def profile_root(profile: str = "") -> Path:
    normalized = normalize_profile(profile)
    if normalized == "legacy":
        return ROOT
    return ROOT / "profiles" / normalized


def config_path(profile: str = "") -> Path:
    return profile_root(profile) / "config.yaml"


def progress_path(profile: str = "") -> Path:
    return profile_root(profile) / "runs" / "daily_progress.json"


def log_dir(profile: str = "") -> Path:
    return profile_root(profile) / "runs" / "logs"


def friend_visit_dir(profile: str = "") -> Path:
    return profile_root(profile) / "runs"
