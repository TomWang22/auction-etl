"""Filesystem paths for persistent browser profiles."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_ROOT = PROJECT_ROOT / "profiles"


def profile_root() -> Path:
    """Return the configured browser-profile root."""
    configured = os.environ.get(
        "AUCTION_BROWSER_PROFILE_ROOT",
        "",
    ).strip()

    root = (
        Path(configured).expanduser()
        if configured
        else DEFAULT_PROFILE_ROOT
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    return root


def profile_path(name: str) -> Path:
    """Return the directory for one named browser profile."""
    normalized = name.strip()

    if not normalized:
        raise ValueError(
            "Browser profile name must not be empty."
        )

    if normalized in {".", ".."}:
        raise ValueError(
            "Browser profile name is invalid."
        )

    if Path(normalized).name != normalized:
        raise ValueError(
            "Browser profile name must not contain path separators."
        )

    path = profile_root() / normalized

    path.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def list_profiles() -> list[str]:
    """Return available browser profile names."""
    return sorted(
        path.name
        for path in profile_root().iterdir()
        if path.is_dir()
    )


def profile_exists(name: str) -> bool:
    """Return whether a named browser profile exists."""
    return (
        profile_root()
        / name
    ).is_dir()
