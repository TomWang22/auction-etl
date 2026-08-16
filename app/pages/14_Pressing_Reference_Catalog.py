"""Stable physical pressing-reference catalog."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from auction_etl.domain.pressing_reference import (
    ReleaseFormat,
    ReleaseType,
)
from auction_etl.services.pressing_reference_catalog import (
    build_reference_from_mapping,
    list_pressing_references,
    save_pressing_reference,
)
from app.navigation import render_navigation


st.set_page_config(
    page_title="Pressing Reference Catalog",
    page_icon="💿",
    layout="wide",
)
render_navigation(current_page="pages/14_Pressing_Reference_Catalog.py")


@st.cache_resource
def _engine() -> Engine:
    """Create the PostgreSQL engine."""

    database_url = os.environ.get(
        "DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required."
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def _reference_label(
    row: dict[str, Any],
) -> str:
    """Build a physical pressing selector label."""

    catalog = (
        row.get("catalog_number")
        or "No catalog"
    )

    country = (
        row.get("release_country")
        or "Unknown country"
    )

    language = (
        row.get("release_language")
        or "Unknown language"
    )

    matrix_values = [
        str(matrix.get("value"))
        for matrix in (
            row.get("matrices")
            or []
        )
        if matrix.get("value")
    ]

    matrix_label = (
        " / ".join(matrix_values[:2])
        if matrix_values
        else "No matrix"
    )

    return (
        f"#{row['pressing_reference_id']} · "
        f"{row['artist']} — "
        f"{row['canonical_title']} · "
        f"{catalog} · "
        f"{matrix_label} · "
        f"{country} · "
        f"{language} · "
        f"{row['release_format']} / "
        f"{row['release_type']}"
    )


def _matrix_frame(
    row: dict[str, Any] | None,
) -> pd.DataFrame:
    """Build an editable matrix/runout frame."""

    if row is None:
        return pd.DataFrame(
            [
                {
                    "side": "",
                    "value": "",
                }
            ]
        )

    matrices = row.get(
        "matrices"
    ) or []

    if not matrices:
        return pd.DataFrame(
            [
                {
                    "side": "",
                    "value": "",
                }
            ]
        )

    return pd.DataFrame(
        [
            {
                "side":
                    matrix.get("side")
                    or "",
                "value":
                    matrix.get("value")
                    or "",
            }
            for matrix in matrices
        ]
    )


def _year_text(
    row: dict[str, Any] | None,
) -> str:
    """Return a blank-safe release year."""

    if (
        row is None
        or row.get("release_year")
        is None
    ):
        return ""

    return str(
        row["release_year"]
    )


def _enum_index(
    options: list[str],
    value: Any,
    fallback: str,
) -> int:
    """Return a safe selectbox index."""

    candidate = str(
        value
        if value is not None
        else fallback
    )

    try:
        return options.index(
            candidate
        )
    except ValueError:
        return options.index(
            fallback
        )


def main() -> None:
    """Render physical release identity only."""

    st.title(
        "💿 Pressing Reference Catalog"
    )

    st.caption(
        "One row represents a physical pressing/release identity: "
        "artist, canonical title, catalog number, label, matrix/runout, "
        "country, language, year, physical format, and release type."
    )

    st.info(
        "Auction prices, sellers, bids, listing outcomes, copy condition, "
        "and completeness observations are intentionally not part of "
        "this reference."
    )

    engine = _engine()

    search = st.text_input(
        "Search pressing metadata",
        placeholder=(
            "Artist, title, catalog, matrix, country, language..."
        ),
    )

    references = list_pressing_references(
        engine,
        search=search,
    )

    mode = st.radio(
        "Action",
        options=[
            "Create new pressing reference",
            "Edit existing pressing reference",
        ],
        horizontal=True,
        disabled=not bool(
            references
        ),
    )

    selected: dict[str, Any] | None = None
    pressing_id: int | None = None

    if (
        mode
        == "Edit existing pressing reference"
        and references
    ):
        reference_by_id = {
            int(
                row[
                    "pressing_reference_id"
                ]
            ): row
            for row in references
        }

        pressing_id = st.selectbox(
            "Physical pressing",
            options=list(
                reference_by_id
            ),
            format_func=lambda value: (
                _reference_label(
                    reference_by_id[
                        value
                    ]
                )
            ),
        )

        selected = reference_by_id[
            pressing_id
        ]

    release_formats = [
        item.value
        for item in ReleaseFormat
    ]
    release_types = [
        item.value
        for item in ReleaseType
    ]

    with st.form(
        "pressing-reference-editor",
        clear_on_submit=False,
    ):
        left, right = st.columns(2)

        with left:
            artist = st.text_input(
                "Artist",
                value=(
                    str(
                        selected.get(
                            "artist",
                            "",
                        )
                    )
                    if selected
                    else ""
                ),
                disabled=selected is not None,
            )

            canonical_title = st.text_input(
                "Canonical release title",
                value=(
                    str(
                        selected.get(
                            "canonical_title",
                            "",
                        )
                    )
                    if selected
                    else ""
                ),
                disabled=selected is not None,
            )

            catalog_number = st.text_input(
                "Catalog number",
                value=(
                    str(
                        selected.get(
                            "catalog_number"
                        )
                        or ""
                    )
                    if selected
                    else ""
                ),
            )

            label = st.text_input(
                "Label",
                value=(
                    str(
                        selected.get(
                            "label"
                        )
                        or ""
                    )
                    if selected
                    else ""
                ),
            )

            release_country = st.text_input(
                "Release country",
                value=(
                    str(
                        selected.get(
                            "release_country"
                        )
                        or ""
                    )
                    if selected
                    else ""
                ),
                placeholder="Japan",
            )

            release_language = st.text_input(
                "Release language",
                value=(
                    str(
                        selected.get(
                            "release_language"
                        )
                        or ""
                    )
                    if selected
                    else ""
                ),
                placeholder="Japanese",
            )

        with right:
            release_year = st.text_input(
                "Release year",
                value=_year_text(
                    selected
                ),
                placeholder="1983",
            )

            release_format = st.selectbox(
                "Physical format",
                options=release_formats,
                index=_enum_index(
                    release_formats,
                    (
                        selected.get(
                            "release_format"
                        )
                        if selected
                        else None
                    ),
                    ReleaseFormat.OTHER.value,
                ),
                help=(
                    "LP, EP, 7-inch, 10-inch, 12-inch, "
                    "CD, cassette, or other."
                ),
            )

            release_type = st.selectbox(
                "Release type",
                options=release_types,
                index=_enum_index(
                    release_types,
                    (
                        selected.get(
                            "release_type"
                        )
                        if selected
                        else None
                    ),
                    ReleaseType.UNKNOWN.value,
                ),
                help=(
                    "Studio, compilation, live, soundtrack, "
                    "single, EP, promo, box set, or other."
                ),
            )

            edition_notes = st.text_area(
                "Edition / pressing notes",
                value=(
                    str(
                        selected.get(
                            "edition_notes"
                        )
                        or ""
                    )
                    if selected
                    else ""
                ),
                placeholder=(
                    "First Japanese issue, gatefold, red vinyl, "
                    "specific obi variation..."
                ),
            )

            actor = st.text_input(
                "Editor",
                value=(
                    "STREAMLIT_PRESSING_REFERENCE"
                ),
            )

            reason = st.text_area(
                "Reason / evidence note",
                placeholder=(
                    "Catalog scan, matrix inspection, label image, "
                    "manufacturer reference..."
                ),
            )

        st.markdown(
            "#### Matrix / runout inscriptions"
        )

        matrices = st.data_editor(
            _matrix_frame(
                selected
            ),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            column_config={
                "side":
                    st.column_config.TextColumn(
                        "Side",
                        help=(
                            "Examples: A, B, A1, B1. "
                            "May be blank when side is unknown."
                        ),
                    ),
                "value":
                    st.column_config.TextColumn(
                        "Matrix / runout",
                        required=False,
                    ),
            },
        )

        submitted = st.form_submit_button(
            (
                "Create pressing reference"
                if selected is None
                else "Save pressing reference"
            ),
            type="primary",
            width="stretch",
        )

    if submitted:
        try:
            payload = {
                "artist":
                    artist,
                "canonical_title":
                    canonical_title,
                "catalog_number":
                    catalog_number,
                "label":
                    label,
                "release_country":
                    release_country,
                "release_language":
                    release_language,
                "release_year":
                    release_year,
                "release_format":
                    release_format,
                "release_type":
                    release_type,
                "edition_notes":
                    edition_notes,
                "matrices":
                    matrices.to_dict(
                        orient="records"
                    ),
            }

            reference = (
                build_reference_from_mapping(
                    payload
                )
            )

            saved = save_pressing_reference(
                engine,
                reference,
                pressing_id=pressing_id,
                actor=actor,
                reason=reason,
            )
        except (
            ValueError,
            TypeError,
        ) as error:
            st.error(
                str(error)
            )
        else:
            st.success(
                "Saved physical pressing reference "
                f"#{saved['pressing_reference_id']}."
            )

            st.rerun()

    st.divider()
    st.subheader(
        "Physical pressing library"
    )

    if not references:
        st.info(
            "No pressing reference matches the current search."
        )
        return

    library_rows = []

    for row in references:
        matrix_values = []

        for matrix in (
            row.get("matrices")
            or []
        ):
            side = (
                matrix.get("side")
                or ""
            )
            value = (
                matrix.get("value")
                or ""
            )

            matrix_values.append(
                (
                    f"{side}: {value}"
                    if side
                    else value
                )
            )

        library_rows.append(
            {
                "pressing_id":
                    row[
                        "pressing_reference_id"
                    ],
                "artist":
                    row["artist"],
                "canonical_title":
                    row[
                        "canonical_title"
                    ],
                "catalog_number":
                    row.get(
                        "catalog_number"
                    ),
                "label":
                    row.get("label"),
                "matrix_runout":
                    " | ".join(
                        matrix_values
                    ),
                "release_country":
                    row.get(
                        "release_country"
                    ),
                "release_language":
                    row.get(
                        "release_language"
                    ),
                "release_year":
                    row.get(
                        "release_year"
                    ),
                "release_format":
                    row.get(
                        "release_format"
                    ),
                "release_type":
                    row.get(
                        "release_type"
                    ),
                "edition_notes":
                    row.get(
                        "edition_notes"
                    ),
            }
        )

    st.dataframe(
        pd.DataFrame(
            library_rows
        ),
        width="stretch",
        hide_index=True,
    )


main()
