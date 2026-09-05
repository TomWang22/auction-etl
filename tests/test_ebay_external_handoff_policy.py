"""Regression coverage for external-only eBay acquisition policy."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import scripts.run_latest_auction_refresh as refresh


def write_config(
    path: Path,
    *,
    mode: str | None,
    enabled: bool = True,
) -> None:
    """Write one minimal eBay source configuration."""

    source: dict[str, object] = {
        "name": "facerecords",
        "enabled": enabled,
    }

    if mode is not None:
        source["acquisition_mode"] = mode

    path.write_text(
        json.dumps(
            [source],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_external_mode_disables_browser_acquisition(
    tmp_path: Path,
) -> None:
    """Explicit external mode must prohibit browser fallback."""

    config = tmp_path / "ebay.json"

    write_config(
        config,
        mode="external",
    )

    assert (
        refresh.ebay_external_handoff_only(
            config
        )
        is True
    )


def test_missing_mode_preserves_legacy_browser_semantics(
    tmp_path: Path,
) -> None:
    """Old configurations default to browser mode."""

    config = tmp_path / "ebay.json"

    write_config(
        config,
        mode=None,
    )

    assert (
        refresh.ebay_external_handoff_only(
            config
        )
        is False
    )


def test_browser_mode_remains_explicitly_available(
    tmp_path: Path,
) -> None:
    """Explicit browser mode does not claim external-only policy."""

    config = tmp_path / "ebay.json"

    write_config(
        config,
        mode="browser",
    )

    assert (
        refresh.ebay_external_handoff_only(
            config
        )
        is False
    )


def test_unknown_mode_fails_closed(
    tmp_path: Path,
) -> None:
    """Unknown acquisition policies must not silently launch a browser."""

    config = tmp_path / "ebay.json"

    write_config(
        config,
        mode="mystery",
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported eBay acquisition_mode",
    ):
        refresh.ebay_external_handoff_only(
            config
        )


def test_no_enabled_source_fails_closed(
    tmp_path: Path,
) -> None:
    """An empty enabled-source set is invalid."""

    config = tmp_path / "ebay.json"

    write_config(
        config,
        mode="external",
        enabled=False,
    )

    with pytest.raises(
        RuntimeError,
        match="No enabled eBay source exists",
    ):
        refresh.ebay_external_handoff_only(
            config
        )


def test_production_config_uses_public_browser_acquisition() -> None:
    """Production eBay uses anonymous sold/completed browser acquisition."""

    config = Path(
        "config/ebay_sources.json"
    )

    payload = json.loads(
        config.read_text(
            encoding="utf-8",
        )
    )

    assert isinstance(
        payload,
        list,
    )
    assert len(
        payload
    ) == 1

    source = payload[0]

    assert (
        refresh.ebay_external_handoff_only(
            config
        )
        is False
    )

    assert source["acquisition_mode"] == "browser"
    assert source["profile"] == "ebay-public"
    assert source["seller"] == "all-sellers"

    url = str(
        source["url"]
    )

    assert "_ssn=" not in url
    assert "_nkw=teresa+teng" in url
    assert "LH_Complete=1" in url
    assert "LH_Sold=1" in url


def test_external_gate_occurs_after_structured_handoff_priority() -> None:
    """Pending structured raw pages must be processed before external idle."""

    source = inspect.getsource(
        refresh.main
    )

    pending_position = source.index(
        "if pending_ebay_raw_pages > 0:"
    )

    external_position = source.index(
        "elif ebay_external_handoff_only("
    )

    browser_position = source.index(
        '"scripts/crawl_ebay_sources.py"'
    )

    assert (
        pending_position
        < external_position
        < browser_position
    )


def test_external_idle_is_unavailable_and_degraded() -> None:
    """No external handoff must not report a successful eBay check."""

    source = inspect.getsource(
        refresh.main
    )

    start = source.index(
        "elif ebay_external_handoff_only("
    )
    end = source.index(
        "else:\n"
        "            for source_name in enabled_ebay_sources(",
        start,
    )

    branch = source[
        start:end
    ]

    assert '"eBay",' in branch
    assert '"unavailable",' in branch
    assert '"done",' not in branch

    assert (
        "EBAY_EXTERNAL_HANDOFF_IDLE"
        in branch
    )

    assert (
        'status["degraded"] = True'
        in branch
    )

    assert (
        "eBay was not checked."
        in branch
    )

    assert (
        "browser_acquisition_executed=False"
        in branch
    )

    assert (
        "ebay_request_executed=False"
        in branch
    )


def test_existing_structured_handoff_support_remains() -> None:
    """The runner must retain its existing external raw-page path."""

    source = inspect.getsource(
        refresh.main
    )

    assert (
        "pending external eBay raw page(s)"
        in source
    )

    assert (
        "process_ebay_raw_pages("
        in source
    )

    assert (
        "ebay_structured_raw_page_id"
        in source
    )
