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


def test_completed_analytics_require_at_least_one_bid() -> None:
    """Buy-it-now / 0-bid listings must not enter comparable-sale charts."""
    source = page_source()

    assert "COALESCE(bid_count, 0) > 0" in source
    assert "at least one bid" in source.casefold()
    for name in (
        "load_catalog_options",
        "load_filter_values",
        "load_date_bounds",
        "load_sales",
    ):
        block = function_block(name)
        assert (
            "COMPLETED_AUCTION_PREDICATE" in block
            or "COALESCE(bid_count, 0) > 0" in block
        )


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
