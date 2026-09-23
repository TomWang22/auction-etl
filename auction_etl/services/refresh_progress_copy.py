"""User-facing marketplace refresh progress copy."""

from __future__ import annotations

FAILURE_STATES = {
    "failed",
    "unavailable",
    "interrupted",
    "awaiting_handoff",
    "authentication_required",
}
RUNNING_STATES = {
    "queued",
    "running",
}


def marketplace_card_captions(
    *,
    state: str,
    processed: int,
    new_records: int,
    reason: str = "",
    identity_caption: str = "",
) -> list[str]:
    """Return processed-only captions for one marketplace card."""
    lines: list[str] = []

    if new_records > 0:
        lines.append(
            f"Processed {processed:,} of {new_records:,}"
        )
    elif state == "running":
        lines.append("Looking for new sales…")

    if state in FAILURE_STATES:
        cleaned = reason.strip()
        if cleaned:
            lines.append(cleaned)

    cleaned_identity = identity_caption.strip()
    if cleaned_identity:
        lines.append(cleaned_identity)

    return lines


def show_processed_metric(
    *,
    new_records: int,
) -> bool:
    """Hide Processed 0/0 when the refresh found nothing new."""
    return new_records > 0


def show_record_processing_bar(
    *,
    state: str,
    new_records: int,
) -> bool:
    """Show the processed bar only for live search or new records."""
    if new_records > 0:
        return True
    return state in RUNNING_STATES
