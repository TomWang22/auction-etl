"""Tests for persistent browser-profile paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from auction_etl.browser.profiles import (
    profile_path,
    profile_root,
)


def test_profile_root_uses_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use configured persistent storage."""
    expected = tmp_path / "profiles"

    monkeypatch.setenv(
        "AUCTION_BROWSER_PROFILE_ROOT",
        str(expected),
    )

    assert profile_root() == expected
    assert expected.is_dir()


def test_named_profile_uses_configured_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Place eBay profiles beneath persistent storage."""
    root = tmp_path / "profiles"

    monkeypatch.setenv(
        "AUCTION_BROWSER_PROFILE_ROOT",
        str(root),
    )

    path = profile_path(
        "facerecords"
    )

    assert path == root / "facerecords"
    assert path.is_dir()


@pytest.mark.parametrize(
    "name",
    (
        "",
        " ",
        ".",
        "..",
        "../escape",
        "nested/profile",
    ),
)
def test_profile_path_rejects_unsafe_names(
    name: str,
) -> None:
    """Keep profile names inside the configured root."""
    with pytest.raises(
        ValueError
    ):
        profile_path(
            name
        )
