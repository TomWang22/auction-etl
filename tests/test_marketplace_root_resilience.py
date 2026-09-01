"""Regression coverage for marketplace root-cause fixes."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from auction_etl.models.crawl import CrawlJob


ROOT = Path(__file__).resolve().parents[1]


def test_ebay_composite_crawl_source_is_not_length_limited() -> None:
    """Composite eBay provenance must fit the CrawlJob source column."""

    source = "ebay:b90ab4a1-7fe0-5edb-aea5-3d9b7135325b"
    column = CrawlJob.__table__.c.source

    assert len(source) > 32
    assert isinstance(column.type, sa.Text)
    assert column.type.length is None


def test_gripsweat_detail_failure_is_secondary_after_identity_import() -> None:
    """A detail-enrichment failure must not invalidate imported identities."""

    runner = (
        ROOT
        / "scripts"
        / "run_latest_auction_refresh.py"
    ).read_text(encoding="utf-8")

    phase = 'phase="Apply Gripsweat detail enrichment"'
    phase_index = runner.index(phase)
    block = runner[
        max(0, phase_index - 2200):
        phase_index + 3000
    ]

    assert "gripsweat_detail_status" in block
    assert "gripsweat_detail_command_output" in block
    assert "allow_failure=True" in block
    assert "GRIPSWEAT_DETAIL_ENRICHMENT_PARTIAL" in block
    assert "command_output_tail" in block
    assert (
        "Gripsweat identities were imported and published"
        in block
    )


def test_v25_11_migration_widens_only_crawl_source() -> None:
    """The migration must widen provenance without touching status."""

    migrations = sorted(
        (
            ROOT
            / "alembic"
            / "versions"
        ).glob(
            "25b11c0de001_widen_crawl_job_source.py"
        )
    )

    assert len(migrations) == 1

    source = migrations[0].read_text(
        encoding="utf-8"
    )

    assert '"crawl_job"' in source
    assert '"source"' in source
    assert "type_=sa.Text()" in source
    assert 'type_=sa.String(length=32)' in source
    assert '"status"' not in source
