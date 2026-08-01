"""Filtered multi-format exports for Collector Review."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from app.collector_review_support import clean_text, is_missing
from auction_etl.services.export import (
    EXPORT_COLUMNS,
    export_csv,
    export_docx,
    export_json,
    export_markdown,
    export_xlsx,
)

ALL_COMBINED = "All media — one file"
ALL_SPLIT = "All media — ZIP by media"

EXPORT_FORMATS = (
    "CSV",
    "Excel",
    "JSON",
    "Markdown",
    "Word",
    "Plain text",
)

COLUMN_CANDIDATES = {
    "id": ("id",),
    "marketplace": ("marketplace",),
    "listing_id": ("listing_id",),
    "auction_url": ("auction_url",),
    "seller": ("seller",),
    "artist": ("artist_display", "artist"),
    "title": ("title",),
    "media_type": (
        "media_display",
        "effective_media_type",
        "manual_media_type",
        "auto_media_type",
        "media_type",
    ),
    "disc_count": (
        "effective_disc_count",
        "manual_disc_count",
        "auto_disc_count",
        "disc_count",
    ),
    "edition": (
        "effective_pressing_type",
        "manual_pressing_type",
        "auto_pressing_type",
        "edition",
    ),
    "catalog_number": (
        "catalog_display",
        "catalog_number",
    ),
    "condition_media": (
        "effective_condition_media",
        "manual_condition_media",
        "condition_media",
    ),
    "condition_cover": (
        "effective_condition_cover",
        "manual_condition_cover",
        "condition_cover",
    ),
    "bulk_lot": (
        "effective_bulk_lot",
        "manual_bulk_lot",
        "auto_bulk_lot",
        "bulk_lot",
    ),
    "bid_count": (
        "bid_count_display",
        "bid_count",
    ),
    "watch_count": ("watch_count",),
    "start_price": (
        "starting_local",
        "start_price",
    ),
    "hammer_price_local": (
        "hammer_local",
        "final_price",
    ),
    "tax_rate": ("tax_rate",),
    "tax_amount_local": (
        "tax_local",
        "tax_amount",
    ),
    "gross_price_local": (
        "total_local",
        "gross_price",
        "current_price_gross",
    ),
    "price_includes_tax": ("price_includes_tax",),
    "currency": (
        "currency_display",
        "currency",
    ),
    "fx_rate_to_usd": ("fx_rate_to_usd",),
    "fx_rate_date": ("fx_rate_date",),
    "final_price_usd": (
        "hammer_usd",
        "final_price_usd",
    ),
    "tax_usd": (
        "tax_usd_display",
        "tax_usd",
    ),
    "total_usd": (
        "total_usd",
        "gross_price_usd",
    ),
    "shipping_price": ("shipping_price",),
    "shipping_usd": ("shipping_usd",),
    "landed_usd": ("landed_usd",),
    "ended_at": (
        "closing_display",
        "ended_at",
    ),
    "created_at": (
        "created_at",
        "_audit_first_seen_at",
    ),
    "_fx_source": (
        "_fx_source",
        "fx_source",
    ),
}

TEXT_FIELDS = {
    "marketplace",
    "listing_id",
    "auction_url",
    "seller",
    "artist",
    "title",
    "media_type",
    "edition",
    "catalog_number",
    "condition_media",
    "condition_cover",
    "currency",
    "_fx_source",
}

INTEGER_FIELDS = {
    "id",
    "disc_count",
    "bid_count",
    "watch_count",
}

BOOLEAN_FIELDS = {
    "bulk_lot",
    "price_includes_tax",
}

DECIMAL_FIELDS = {
    "start_price",
    "hammer_price_local",
    "tax_rate",
    "tax_amount_local",
    "gross_price_local",
    "fx_rate_to_usd",
    "final_price_usd",
    "tax_usd",
    "total_usd",
    "shipping_price",
    "shipping_usd",
    "landed_usd",
}


def _series(
    dataframe: pd.DataFrame,
    column: str,
    default: Any = "",
) -> pd.Series:
    """Return one Series even when a column label is duplicated."""
    if column not in dataframe.columns:
        return pd.Series(
            default,
            index=dataframe.index,
            dtype="object",
        )

    selected = dataframe.loc[:, column]

    if isinstance(selected, pd.DataFrame):
        return selected.bfill(axis=1).iloc[:, 0]

    return selected


def _first_value(
    row: pd.Series,
    candidates: tuple[str, ...],
) -> Any:
    """Return the first non-empty candidate from one row."""
    for candidate in candidates:
        if candidate not in row.index:
            continue

        value = row[candidate]

        if isinstance(value, pd.Series):
            values = [
                item
                for item in value.tolist()
                if not is_missing(item)
            ]

            if not values:
                continue

            value = values[0]

        if not is_missing(value):
            return value

    return None


def _boolean(value: Any) -> bool | None:
    if is_missing(value):
        return None

    if isinstance(value, bool):
        return value

    normalized = clean_text(value).lower()

    if normalized in {"1", "true", "yes", "y"}:
        return True

    if normalized in {"0", "false", "no", "n"}:
        return False

    return bool(value)


def _normalize(field: str, value: Any) -> Any:
    if is_missing(value):
        return None

    if field in TEXT_FIELDS:
        return clean_text(value)

    if field in INTEGER_FIELDS:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    if field in BOOLEAN_FIELDS:
        return _boolean(value)

    if field in DECIMAL_FIELDS:
        try:
            return Decimal(str(value))
        except (ArithmeticError, TypeError, ValueError):
            return None

    return value


def dataframe_to_export_rows(
    dataframe: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Adapt prepared UI rows to the existing export service."""
    export_rows: list[dict[str, Any]] = []

    for _, source_row in dataframe.iterrows():
        row = {
            field: _normalize(
                field,
                _first_value(
                    source_row,
                    candidates,
                ),
            )
            for field, candidates
            in COLUMN_CANDIDATES.items()
        }

        for column in EXPORT_COLUMNS:
            row.setdefault(column, None)

        row["currency"] = row["currency"] or "USD"
        row["media_type"] = (
            row["media_type"] or "UNCLASSIFIED"
        )
        row["_fx_source"] = (
            row["_fx_source"] or "collector-review"
        )

        if (
            row["currency"] == "USD"
            and row["fx_rate_to_usd"] is None
        ):
            row["fx_rate_to_usd"] = Decimal("1")

        export_rows.append(row)

    return export_rows


def deduplicate_export_frame(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Prefer native eBay over matching Gripsweat archive rows."""
    if dataframe.empty:
        return dataframe.copy()

    frame = dataframe.copy()

    marketplace = (
        _series(frame, "marketplace")
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    listing_id = (
        _series(frame, "listing_id")
        .fillna("")
        .astype(str)
        .str.strip()
    )

    source_marker = marketplace.copy()

    for source_column in (
        "_activity_source",
        "ingestion_source",
        "record_source",
        "data_source",
        "source",
    ):
        if source_column in frame.columns:
            source_marker = (
                source_marker
                + " "
                + _series(
                    frame,
                    source_column,
                )
                .fillna("")
                .astype(str)
                .str.lower()
            )

    gripsweat = source_marker.str.contains(
        "gripsweat",
        regex=False,
    )

    frame["_export_family"] = marketplace.mask(
        gripsweat,
        "ebay",
    )
    frame["_export_priority"] = gripsweat.astype(int)
    frame["_export_order"] = range(len(frame))
    frame["_export_listing_id"] = listing_id.mask(
        listing_id.eq(""),
        (
            "__missing__:"
            + frame["_export_order"].astype(str)
        ),
    )

    frame.sort_values(
        [
            "_export_priority",
            "_export_order",
        ],
        kind="stable",
        inplace=True,
    )

    frame.drop_duplicates(
        subset=[
            "_export_family",
            "_export_listing_id",
        ],
        keep="first",
        inplace=True,
    )

    frame.sort_values(
        "_export_order",
        kind="stable",
        inplace=True,
    )

    return frame.drop(
        columns=[
            "_export_family",
            "_export_priority",
            "_export_order",
            "_export_listing_id",
        ],
    ).reset_index(drop=True)


def _slug(value: str) -> str:
    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value.lower(),
    ).strip("-")

    return value or "all"


def _format_metadata(
    export_format: str,
) -> tuple[str, str]:
    return {
        "CSV": ("csv", "text/csv"),
        "Excel": (
            "xlsx",
            (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        ),
        "JSON": ("json", "application/json"),
        "Markdown": ("md", "text/markdown"),
        "Word": (
            "docx",
            (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        ),
        "Plain text": ("txt", "text/plain"),
    }[export_format]


def _write_export(
    rows: list[dict[str, Any]],
    path: Path,
    export_format: str,
    title: str,
) -> None:
    if export_format == "CSV":
        export_csv(rows, path)
    elif export_format == "Excel":
        export_xlsx(rows, path)
    elif export_format == "JSON":
        export_json(rows, path)
    elif export_format in {"Markdown", "Plain text"}:
        export_markdown(
            rows,
            path,
            title=title,
        )
    elif export_format == "Word":
        export_docx(
            rows,
            path,
            title=title,
        )
    else:
        raise ValueError(
            f"Unsupported export format: {export_format}"
        )


def build_export_payload(
    dataframe: pd.DataFrame,
    export_format: str,
    media_selection: str,
) -> tuple[bytes, str, str, int]:
    """Build one export file or a ZIP split by media."""
    extension, mime_type = _format_metadata(
        export_format
    )

    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d-%H%M%S")

    media = (
        _series(
            dataframe,
            "media_display",
            "UNCLASSIFIED",
        )
        .fillna("UNCLASSIFIED")
        .astype(str)
        .replace("", "UNCLASSIFIED")
    )

    with TemporaryDirectory(
        prefix="auction-etl-ui-export-"
    ) as directory_name:
        directory = Path(directory_name)

        if media_selection == ALL_SPLIT:
            archive_name = (
                "collector-review-by-media-"
                f"{timestamp}.zip"
            )
            archive_path = directory / archive_name

            with ZipFile(
                archive_path,
                "w",
                compression=ZIP_DEFLATED,
            ) as archive:
                for media_type in sorted(
                    media.unique()
                ):
                    selected = dataframe[
                        media.eq(media_type)
                    ].copy()

                    rows = dataframe_to_export_rows(
                        selected
                    )

                    filename = (
                        "collector-review-"
                        f"{_slug(media_type)}-"
                        f"{timestamp}.{extension}"
                    )

                    output_path = directory / filename

                    _write_export(
                        rows,
                        output_path,
                        export_format,
                        (
                            "Auction Collector Review — "
                            f"{media_type}"
                        ),
                    )

                    archive.write(
                        output_path,
                        arcname=filename,
                    )

            return (
                archive_path.read_bytes(),
                archive_name,
                "application/zip",
                len(dataframe),
            )

        if media_selection == ALL_COMBINED:
            selected = dataframe.copy()
            media_slug = "all-media"
            title = "Auction Collector Review"
        else:
            selected = dataframe[
                media.eq(media_selection)
            ].copy()

            media_slug = _slug(media_selection)
            title = (
                "Auction Collector Review — "
                f"{media_selection}"
            )

        rows = dataframe_to_export_rows(selected)

        filename = (
            "collector-review-"
            f"{media_slug}-"
            f"{timestamp}.{extension}"
        )

        output_path = directory / filename

        _write_export(
            rows,
            output_path,
            export_format,
            title,
        )

        return (
            output_path.read_bytes(),
            filename,
            mime_type,
            len(rows),
        )


def render_export_toolbar(
    dataframe: pd.DataFrame,
) -> None:
    """Render exports for the complete filtered result set."""
    with st.expander(
        "Export filtered listings",
        expanded=False,
    ):
        st.caption(
            "Exports every row matching the sidebar filters. "
            "Pagination does not limit the downloaded data."
        )

        format_column, media_column, dedupe_column = (
            st.columns([2, 3, 1])
        )

        with format_column:
            export_format = st.selectbox(
                "Format",
                EXPORT_FORMATS,
                key="collector_export_format",
            )

        media_values = tuple(
            sorted(
                {
                    clean_text(value)
                    for value in _series(
                        dataframe,
                        "media_display",
                    ).dropna()
                    if clean_text(value)
                }
            )
        )

        with media_column:
            media_selection = st.selectbox(
                "Media",
                (
                    ALL_COMBINED,
                    ALL_SPLIT,
                    *media_values,
                ),
                key="collector_export_media",
            )

        with dedupe_column:
            deduplicate = st.checkbox(
                "Deduplicate",
                value=True,
                key="collector_export_deduplicate",
                help=(
                    "Prefer native eBay over matching "
                    "Gripsweat archive rows."
                ),
            )

        export_frame = (
            deduplicate_export_frame(dataframe)
            if deduplicate
            else dataframe.copy()
        )

        media_series = (
            _series(
                export_frame,
                "media_display",
                "UNCLASSIFIED",
            )
            .fillna("UNCLASSIFIED")
            .astype(str)
            .replace("", "UNCLASSIFIED")
        )

        if media_selection in {
            ALL_COMBINED,
            ALL_SPLIT,
        }:
            row_count = len(export_frame)
        else:
            row_count = int(
                media_series.eq(
                    media_selection
                ).sum()
            )

        signature_frame = pd.DataFrame(
            {
                "marketplace": _series(
                    export_frame,
                    "marketplace",
                ).astype(str),
                "listing_id": _series(
                    export_frame,
                    "listing_id",
                ).astype(str),
                "media": media_series,
                "total": _series(
                    export_frame,
                    "total_local",
                ).astype(str),
            }
        )

        signature_hash = int(
            pd.util.hash_pandas_object(
                signature_frame,
                index=False,
            ).sum()
        )

        signature = (
            f"{export_format}|{media_selection}|"
            f"{deduplicate}|{row_count}|{signature_hash}"
        )

        st.caption(
            f"{row_count:,} listings will be exported."
        )

        if st.button(
            "Prepare export",
            type="primary",
            width="stretch",
            disabled=row_count == 0,
            key="collector_prepare_export",
        ):
            try:
                with st.spinner(
                    "Preparing export…"
                ):
                    result = build_export_payload(
                        export_frame,
                        export_format,
                        media_selection,
                    )

                st.session_state[
                    "_collector_export_result"
                ] = (
                    signature,
                    *result,
                )

            except Exception as error:
                st.error(
                    f"Could not create export: {error}"
                )

        result = st.session_state.get(
            "_collector_export_result"
        )

        if (
            result
            and result[0] == signature
        ):
            (
                _,
                payload,
                filename,
                mime_type,
                prepared_rows,
            ) = result

            st.success(
                f"Prepared {prepared_rows:,} listings."
            )

            st.download_button(
                "Download export",
                data=payload,
                file_name=filename,
                mime=mime_type,
                width="stretch",
                key="collector_download_export",
            )
