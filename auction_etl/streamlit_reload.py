"""Reload Streamlit-imported service modules only when files change."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any


def reload_modules_if_changed(
    modules: Sequence[ModuleType],
    *,
    cache_key: str,
) -> bool:
    """Reload ``modules`` when any file mtime advances.

    Returns True when a reload ran. Calling this on every Streamlit interaction
    without an mtime gate remounts AgGrid and feels like UI lag.
    """

    stamp = 0.0
    for module in modules:
        path = getattr(module, "__file__", None)
        if not path:
            continue
        try:
            stamp = max(stamp, Path(path).stat().st_mtime)
        except OSError:
            continue
    cache: dict[str, Any] = sys.modules.setdefault(  # type: ignore[assignment]
        cache_key,
        {"stamp": 0.0},
    )
    if not isinstance(cache, dict):
        cache = {"stamp": 0.0}
        sys.modules[cache_key] = cache  # type: ignore[assignment]
    previous = float(cache.get("stamp") or 0.0)
    if stamp and stamp <= previous:
        return False
    for module in modules:
        importlib.reload(module)
    cache["stamp"] = stamp
    return True
