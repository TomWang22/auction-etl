"""Buyee listing photos come from lazy-load data-src, never spacer.gif."""

from __future__ import annotations

from bs4 import BeautifulSoup

from auction_etl.parsers.buyee import is_placeholder_image, parse_image


def test_spacer_gif_is_placeholder() -> None:
    assert is_placeholder_image(
        "https://cdn.buyee.jp/images/common/spacer.gif"
    )
    assert is_placeholder_image(
        "https://cdn.buyee.jp/images/common/noimage.jpg"
    )
    assert not is_placeholder_image(
        "https://cdnyauction.buyee.jp/image/cover.jpg"
    )


def test_parse_image_prefers_data_src_over_spacer() -> None:
    soup = BeautifulSoup(
        """
        <li class="itemCard">
          <img class="lazyLoadV2 g-thumbnail__image"
               src="https://cdn.buyee.jp/images/common/spacer.gif"
               data-src="https://cdnyauction.buyee.jp/image/cover.jpg">
        </li>
        """,
        "html.parser",
    )
    assert parse_image(soup.find("li")) == (
        "https://cdnyauction.buyee.jp/image/cover.jpg"
    )
