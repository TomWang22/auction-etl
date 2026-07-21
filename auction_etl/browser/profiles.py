from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = PROJECT_ROOT / "profiles"


def profile_path(name: str) -> Path:
    """
    Return the filesystem path for a named browser profile.

    The directory is created automatically if it does not already exist.
    """
    path = PROFILE_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_profiles() -> list[str]:
    """
    Return all available browser profile names.
    """
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)

    return sorted(
        p.name
        for p in PROFILE_ROOT.iterdir()
        if p.is_dir()
    )


def profile_exists(name: str) -> bool:
    """
    Return True if a browser profile exists.
    """
    return profile_path(name).exists()
