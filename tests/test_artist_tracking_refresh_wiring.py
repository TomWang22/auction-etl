"""Source-contract tests for artist-aware marketplace refresh wiring."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[
    1
]

EBAY_CRAWLER = (
    ROOT
    / "scripts"
    / "crawl_ebay_sources.py"
)

GRIPSWEAT_PROBE = (
    ROOT
    / "scripts"
    / "probe_gripsweat.py"
)

MULTISOURCE_RUNNER = (
    ROOT
    / "scripts"
    / "run_multisource_ingestion_round.py"
)


def source(
    path: Path,
) -> str:
    """Return valid Python source."""

    value = path.read_text(
        encoding="utf-8"
    )

    ast.parse(
        value,
        filename=str(
            path
        ),
    )

    return value


def test_ebay_crawler_accepts_runtime_artist_config() -> None:
    """Allow the refresh runner to supply generated eBay sources."""

    value = source(
        EBAY_CRAWLER
    )

    assert (
        "AUCTION_EBAY_SOURCES_CONFIG"
        in value
    )


def test_gripsweat_probe_accepts_runtime_artist_config() -> None:
    """Allow the refresh runner to supply generated Gripsweat sources."""

    value = source(
        GRIPSWEAT_PROBE
    )

    assert (
        "AUCTION_GRIPSWEAT_SOURCES_CONFIG"
        in value
    )


def test_multisource_runner_materializes_artist_configs() -> None:
    """Prepare effective artist sources before marketplace execution."""

    value = source(
        MULTISOURCE_RUNNER
    )

    assert (
        "prepare_runtime_marketplace_configs"
        in value
    )

    assert (
        "prepare_runtime_marketplace_configs()"
        in value
    )
