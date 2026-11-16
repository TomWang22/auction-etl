"""Contracts for Sales by pressing completed-auction analytics."""

from __future__ import annotations

from pathlib import Path


PAGE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "pages"
    / "2_Pressing_Analytics.py"
)


def page_source() -> str:
    return PAGE.read_text(encoding="utf-8")


def function_block(name: str) -> str:
    source = page_source()
    start = source.index(f"def {name}(")
    nxt = source.find("\ndef ", start + 1)
    return source[start:nxt]


def test_completed_sales_include_every_scraped_platform() -> None:
    """BIN, Best Offer, and auctions with a missing bid stay in the chart."""
    source = page_source()

    assert "COALESCE(sale.bid_count, -1) = 0" in source
    assert "FIXED_PRICE_OBO" in source
    assert "Buy It Now" in source
    assert "Best Offer" in source
    assert "display_title" in source
    assert "cover_url" in source
    assert "gross_price_usd" in source
    assert "english_album_title" in source
    assert "ImageColumn" in source
    assert "Original price" in source
    assert "original_release_year" in source
    assert "ANALYTICS_MEDIA_SQL" in function_block("load_catalog_options")
    assert "artist_name" in function_block("_pressing_choice_label")
    assert "pressings_for_tracked_artist" in source
    assert "manual_purchase_price" in source
    assert "ascending=[True, True, True]" in source
    assert "release_year DESC" not in source
    assert "sale.currency = :currency" not in source
    assert "at least one bid" not in source.casefold()
    for name in (
        "load_catalog_options",
        "load_filter_values",
        "load_date_bounds",
        "load_sales",
    ):
        block = function_block(name)
        assert "COMPLETED_SALE_PREDICATE" in block


def test_streamlit_tables_use_printf_money_not_altair_format() -> None:
    """NumberColumn must use $%.2f, not Altair's , .2f which renders literally."""
    source = page_source()
    summary = function_block("render_marketplace_summary")
    sales = function_block("render_comparable_sales")

    assert "def streamlit_money_format(" in source
    assert "format=streamlit_money_format(" in summary
    assert "format=streamlit_money_format(" in sales
    assert "format=currency_format(" not in summary
    assert "format=currency_format(" not in sales
    assert '",.2f"' not in summary
    assert '",.2f"' not in sales


def test_price_history_hover_includes_discogs_condition() -> None:
    """Dot hover must report media/sleeve condition like a Discogs sale."""
    history = function_block("render_price_history")

    assert 'title="Media condition"' in history
    assert 'title="Sleeve condition"' in history
    assert 'title="Bids"' in history
    assert 'title="Listing"' in history
    assert "mark_line" not in history
    assert "mark_circle" in history


def test_sales_history_with_condition_renders_under_the_chart() -> None:
    """The comparable-sale table belongs under the diagram, not only in a tab."""
    history_tab = function_block("main")
    history_start = history_tab.index("with history_tab:")
    next_tab = history_tab.index("with distribution_tab:")
    block = history_tab[history_start:next_tab]

    assert "render_price_history(" in block
    assert "Sales history" in block
    assert "render_comparable_sales(" in block
    assert '"media_condition"' in page_source()
    assert '"cover_condition"' in page_source()
