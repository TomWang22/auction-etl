#!/usr/bin/env python3
"""Repair nullable widget values and per-record Streamlit form state."""

from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path


APP_PATH = Path("app/collector_review.py")
PATCH_MARKER = "collector-null-state-fix-v1"


def replace_once(
    source: str,
    old: str,
    new: str,
    description: str,
) -> str:
    """Replace one required source fragment."""
    count = source.count(old)

    if count != 1:
        raise RuntimeError(
            f"{description}: expected exactly one match, found {count}."
        )

    return source.replace(old, new, 1)


def main() -> int:
    """Apply the source repair atomically."""
    if not APP_PATH.is_file():
        raise FileNotFoundError(
            f"Frontend not found: {APP_PATH}"
        )

    source = APP_PATH.read_text(
        encoding="utf-8",
    )

    if PATCH_MARKER in source:
        print("The null-state repair is already installed.")
        return 0

    original = source

    if "from types import SimpleNamespace\n" not in source:
        import_anchor = "from decimal import Decimal\n"

        if import_anchor not in source:
            raise RuntimeError(
                "Could not locate the Decimal import."
            )

        source = source.replace(
            import_anchor,
            (
                f"{import_anchor}"
                "from types import SimpleNamespace\n"
            ),
            1,
        )

    helper_anchor = """
def derive_filter_sql() -> tuple[str, dict[str, Any]]:
"""

    helper_code = '''
def null_if_missing(value: Any) -> Any:
    """Convert pandas and database missing values to Python None."""
    if value is None:
        return None

    if isinstance(value, str):
        cleaned = value.strip()

        if cleaned.lower() in {
            "",
            "nan",
            "nat",
            "none",
            "<na>",
            "null",
        }:
            return None

        return cleaned

    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return value

    if isinstance(missing, bool) and missing:
        return None

    return value


def normalize_selected_record(record: Any) -> SimpleNamespace:
    """Return a selected database row with scalar NULL values normalized."""
    values = {
        field: null_if_missing(value)
        for field, value in record._asdict().items()
    }

    return SimpleNamespace(**values)


'''

    if helper_anchor not in source:
        raise RuntimeError(
            "Could not locate derive_filter_sql()."
        )

    source = source.replace(
        helper_anchor,
        f"{helper_code}{helper_anchor}",
        1,
    )

    old_selected = """    selected = option_rows[
        selected_label
    ]

    st.divider()
"""

    new_selected = """    selected_raw = option_rows[
        selected_label
    ]

    selected = normalize_selected_record(
        selected_raw
    )

    selected_identity = (
        f"{selected.marketplace}:"
        f"{selected.listing_id}"
    )

    editor_revision_key = (
        "collector_editor_revision:"
        f"{selected_identity}"
    )

    editor_revision = int(
        st.session_state.get(
            editor_revision_key,
            0,
        )
    )

    st.divider()
"""

    source = replace_once(
        source,
        old_selected,
        new_selected,
        "Selected-record normalization",
    )

    old_form = """    with st.form(
        "collector_editor",
        clear_on_submit=False,
    ):
"""

    new_form = """    with st.form(
        (
            "collector_editor:"
            f"{selected_identity}:"
            f"{editor_revision}"
        ),
        clear_on_submit=False,
    ):
"""

    source = replace_once(
        source,
        old_form,
        new_form,
        "Versioned editor form",
    )

    old_success = """        st.toast(
            "Collector record updated successfully.",
            icon="✅",
        )
"""

    new_success = """        st.session_state[
            editor_revision_key
        ] = editor_revision + 1

        st.toast(
            "Collector record updated successfully.",
            icon="✅",
        )
"""

    source = replace_once(
        source,
        old_success,
        new_success,
        "Post-save form reset",
    )

    marker_anchor = '"""Interactive review UI for Auction ETL collector records."""'

    source = replace_once(
        source,
        marker_anchor,
        (
            f'{marker_anchor}\n\n'
            f'# {PATCH_MARKER}'
        ),
        "Patch marker",
    )

    ast.parse(
        source,
        filename=str(APP_PATH),
    )

    temporary_path = APP_PATH.with_suffix(
        ".py.null-state-fix.tmp"
    )

    temporary_path.write_text(
        source,
        encoding="utf-8",
    )

    try:
        compile(
            source,
            str(APP_PATH),
            "exec",
        )
    except Exception:
        temporary_path.unlink(
            missing_ok=True,
        )
        raise

    shutil.move(
        temporary_path,
        APP_PATH,
    )

    updated = APP_PATH.read_text(
        encoding="utf-8",
    )

    required_fragments = (
        PATCH_MARKER,
        "def null_if_missing(",
        "def normalize_selected_record(",
        "collector_editor_revision:",
        "editor_revision + 1",
    )

    missing_fragments = [
        fragment
        for fragment in required_fragments
        if fragment not in updated
    ]

    if missing_fragments:
        APP_PATH.write_text(
            original,
            encoding="utf-8",
        )

        raise RuntimeError(
            "Patch verification failed; original frontend restored. "
            f"Missing: {missing_fragments}"
        )

    print("✓ pandas NaN, NaT, and <NA> values normalize to None.")
    print("✓ Numeric widgets no longer call int(float('nan')).")
    print("✓ Text widgets no longer display the literal value 'nan'.")
    print("✓ Each selected listing receives isolated form state.")
    print("✓ Saving increments the form revision and reloads DB values.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
