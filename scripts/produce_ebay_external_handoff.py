#!/usr/bin/env python3
"""Produce an external eBay handoff using an established browser profile.

Acquisition is external to Railway. The command validates and writes a
structured artifact first, runs the importer in dry-run mode, and writes no
database state unless --apply is explicitly supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import (
    parse_qs,
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

from bs4 import BeautifulSoup

from scripts.acquire_ebay_structured import (
    EbayAcquisitionError,
    acquire_page,
    atomic_write_json,
    build_payload_from_html,
    collector_url_for_source,
    utc_now,
)


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG = (
    ROOT
    / "config"
    / "ebay_sources.json"
)

IMPORTER = (
    ROOT
    / "scripts"
    / "import_ebay_structured.py"
)

NEXT_SELECTORS = (
    "a.pagination__next[href]",
    "a[aria-label='Next page'][href]",
    "a[rel='next'][href]",
)


class ExternalProducerError(RuntimeError):
    """Raised when a safe external handoff cannot be produced."""


@dataclass(frozen=True, slots=True)
class ExternalSource:
    """Validated external eBay acquisition configuration."""

    name: str
    seller: str
    url: str
    profile: str
    max_pages: int
    wait_seconds: float
    min_items: int


def positive_integer(
    value: object,
    *,
    field: str,
) -> int:
    """Return one required positive integer."""

    if isinstance(
        value,
        bool,
    ):
        raise ExternalProducerError(
            f"{field} must be a positive integer."
        )

    try:
        result = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise ExternalProducerError(
            f"{field} must be a positive integer."
        ) from error

    if result < 1:
        raise ExternalProducerError(
            f"{field} must be a positive integer."
        )

    return result


def nonnegative_float(
    value: object,
    *,
    field: str,
) -> float:
    """Return one required nonnegative duration."""

    try:
        result = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise ExternalProducerError(
            f"{field} must be nonnegative."
        ) from error

    if result < 0:
        raise ExternalProducerError(
            f"{field} must be nonnegative."
        )

    return result


def load_source(
    path: Path,
    requested_name: str | None = None,
) -> ExternalSource:
    """Load exactly one validated external seller-scoped source."""

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise ExternalProducerError(
            f"Could not read eBay config {path}: {error}"
        ) from error

    if not isinstance(
        payload,
        list,
    ):
        raise ExternalProducerError(
            "eBay source configuration must be a list."
        )

    enabled = [
        row
        for row in payload
        if (
            isinstance(
                row,
                dict,
            )
            and row.get(
                "enabled",
                True,
            )
            is not False
        )
    ]

    if requested_name is not None:
        requested = (
            requested_name
            .strip()
            .casefold()
        )

        enabled = [
            row
            for row in enabled
            if str(
                row.get(
                    "name",
                    "",
                )
            ).strip().casefold()
            == requested
        ]

    if len(enabled) != 1:
        raise ExternalProducerError(
            "Expected exactly one matching enabled eBay source; "
            f"found {len(enabled)}."
        )

    row = enabled[0]

    name = str(
        row.get(
            "name",
            "",
        )
    ).strip()

    seller = str(
        row.get(
            "seller",
            "",
        )
    ).strip()

    url = str(
        row.get(
            "url",
            "",
        )
    ).strip()

    profile = str(
        row.get(
            "profile",
            name,
        )
    ).strip()

    acquisition_mode = str(
        row.get(
            "acquisition_mode",
            "browser",
        )
    ).strip().casefold()

    if not name:
        raise ExternalProducerError(
            "Configured source name is empty."
        )

    if not seller:
        raise ExternalProducerError(
            "External eBay source must define an exact seller."
        )

    if not profile:
        raise ExternalProducerError(
            "External eBay source must define a browser profile."
        )

    if acquisition_mode != "external":
        raise ExternalProducerError(
            "External producer requires acquisition_mode='external'."
        )

    parsed = urlsplit(
        url
    )

    hostname = (
        parsed.hostname
        or ""
    ).casefold()

    if (
        parsed.scheme.casefold()
        != "https"
        or not (
            hostname == "ebay.com"
            or hostname.endswith(
                ".ebay.com"
            )
        )
    ):
        raise ExternalProducerError(
            "Configured source URL must be HTTPS eBay."
        )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    seller_filter = (
        query.get(
            "_ssn",
            [""],
        )[0]
        .strip()
    )

    if (
        seller_filter.casefold()
        != seller.casefold()
    ):
        raise ExternalProducerError(
            "Configured _ssn seller filter does not match "
            f"seller={seller!r}."
        )

    if query.get(
        "LH_Sold"
    ) != ["1"]:
        raise ExternalProducerError(
            "Configured source must be sold-only."
        )

    if query.get(
        "LH_Complete"
    ) != ["1"]:
        raise ExternalProducerError(
            "Configured source must be completed-only."
        )

    if query.get(
        "_sop"
    ) != ["13"]:
        raise ExternalProducerError(
            "Configured source must remain newest-first."
        )

    return ExternalSource(
        name=name,
        seller=seller,
        url=url,
        profile=profile,
        max_pages=positive_integer(
            row.get(
                "max_pages",
                1,
            ),
            field="max_pages",
        ),
        wait_seconds=nonnegative_float(
            row.get(
                "wait_seconds",
                2.0,
            ),
            field="wait_seconds",
        ),
        min_items=positive_integer(
            row.get(
                "min_items",
                1,
            ),
            field="min_items",
        ),
    )


def page_url(
    url: str,
    page_number: int,
) -> str:
    """Return one deterministic eBay result-page URL."""

    if page_number < 1:
        raise ExternalProducerError(
            "page_number must be positive."
        )

    parts = urlsplit(
        url
    )

    query = [
        (
            key,
            value,
        )
        for key, value
        in parse_qsl(
            parts.query,
            keep_blank_values=True,
        )
        if key != "_pgn"
    ]

    if page_number > 1:
        query.append(
            (
                "_pgn",
                str(
                    page_number
                ),
            )
        )

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(
                query,
                doseq=True,
            ),
            parts.fragment,
        )
    )


def has_next_page(
    html: str,
) -> bool:
    """Return whether the captured result page exposes a usable next link."""

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for selector in NEXT_SELECTORS:
        link = soup.select_one(
            selector
        )

        if link is None:
            continue

        href = str(
            link.get(
                "href",
                "",
            )
        ).strip()

        disabled = str(
            link.get(
                "aria-disabled",
                "",
            )
        ).strip().casefold()

        if (
            href
            and disabled != "true"
        ):
            return True

    return False


def profile_directory(
    source: ExternalSource,
) -> Path:
    """Resolve the established profile without creating a replacement."""

    configured_root = os.environ.get(
        "AUCTION_BROWSER_PROFILE_ROOT",
        "",
    ).strip()

    root = (
        Path(
            configured_root
        ).expanduser()
        if configured_root
        else ROOT / "profiles"
    )

    path = (
        root
        / source.profile
    ).resolve()

    if not path.is_dir():
        raise ExternalProducerError(
            "Established eBay browser profile does not exist: "
            f"{path}"
        )

    try:
        next(
            path.iterdir()
        )
    except StopIteration as error:
        raise ExternalProducerError(
            "Established eBay browser profile is empty: "
            f"{path}"
        ) from error

    return path


def merge_listings(
    destination: dict[
        str,
        dict[str, str],
    ],
    listings: object,
) -> int:
    """Merge one page while rejecting conflicting identities."""

    if not isinstance(
        listings,
        list,
    ):
        raise ExternalProducerError(
            "Structured page listings are malformed."
        )

    added = 0

    for value in listings:
        if not isinstance(
            value,
            dict,
        ):
            raise ExternalProducerError(
                "Structured listing is malformed."
            )

        listing = {
            str(
                key
            ): str(
                field_value
            )
            for key, field_value
            in value.items()
        }

        item_id = listing.get(
            "item_id",
            "",
        ).strip()

        if not item_id:
            raise ExternalProducerError(
                "Structured listing has no item_id."
            )

        previous = destination.get(
            item_id
        )

        if previous is None:
            destination[
                item_id
            ] = listing
            added += 1
            continue

        if previous != listing:
            raise ExternalProducerError(
                "Conflicting cross-page eBay identity "
                f"{item_id}."
            )

    return added


def importer_command(
    artifact: Path,
    source_name: str,
    *,
    apply: bool,
) -> list[str]:
    """Return the canonical structured importer command."""

    command = [
        sys.executable,
        str(
            IMPORTER
        ),
        str(
            artifact
        ),
        "--source-name",
        source_name,
    ]

    if apply:
        command.append(
            "--apply"
        )

    return command


def run_importer(
    artifact: Path,
    source_name: str,
    *,
    apply: bool,
) -> None:
    """Validate or explicitly apply the resulting structured handoff."""

    completed = subprocess.run(
        importer_command(
            artifact,
            source_name,
            apply=apply,
        ),
        cwd=ROOT,
        check=False,
    )

    if completed.returncode != 0:
        mode = (
            "apply"
            if apply
            else "dry-run"
        )

        raise ExternalProducerError(
            f"Structured importer {mode} failed with "
            f"status {completed.returncode}."
        )


def parse_arguments() -> argparse.Namespace:
    """Parse external producer arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Acquire seller-scoped eBay sold results through an existing "
            "persistent local browser profile and build an external handoff."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
    )

    parser.add_argument(
        "--source",
        default=None,
        help="Configured source name.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Structured artifact destination.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=(
            "Optional tighter page limit. It may not exceed the "
            "configured max_pages."
        ),
    )

    parser.add_argument(
        "--headless",
        action="store_true",
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=45.0,
    )

    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=None,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "After successful acquisition and importer dry-run, "
            "explicitly create/reuse the external raw.page."
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Produce one bounded seller-scoped structured eBay handoff."""

    arguments = parse_arguments()

    try:
        source = load_source(
            arguments.config
            .expanduser()
            .resolve(),
            arguments.source,
        )

        profile = profile_directory(
            source
        )

        configured_pages = (
            source.max_pages
        )

        if arguments.max_pages is None:
            max_pages = configured_pages
        else:
            max_pages = positive_integer(
                arguments.max_pages,
                field="--max-pages",
            )

            if max_pages > configured_pages:
                raise ExternalProducerError(
                    "--max-pages may not exceed configured max_pages."
                )

        settle_seconds = (
            source.wait_seconds
            if arguments.settle_seconds
            is None
            else nonnegative_float(
                arguments.settle_seconds,
                field="--settle-seconds",
            )
        )

        if arguments.timeout_seconds <= 0:
            raise ExternalProducerError(
                "--timeout-seconds must be positive."
            )

        collected_at = utc_now()

        merged: dict[
            str,
            dict[str, str],
        ] = {}

        page_metadata: list[
            dict[str, Any]
        ] = []

        for page_number in range(
            1,
            max_pages + 1,
        ):
            requested_url = page_url(
                source.url,
                page_number,
            )

            acquired = acquire_page(
                url=requested_url,
                profile_dir=profile,
                storage_state=None,
                headless=arguments.headless,
                timeout_seconds=arguments.timeout_seconds,
                settle_seconds=settle_seconds,
            )

            payload = build_payload_from_html(
                html=acquired.html,
                source_name=source.name,
                requested_url=acquired.requested_url,
                final_url=acquired.final_url,
                http_status=acquired.http_status,
                item_link_count=acquired.item_link_count,
                expected_seller=source.seller,
                collected_at_utc=collected_at,
            )

            page_count = int(
                payload[
                    "listing_count"
                ]
            )

            if page_count < source.min_items:
                raise ExternalProducerError(
                    f"Page {page_number} produced only {page_count} "
                    f"seller-scoped listings; minimum is "
                    f"{source.min_items}."
                )

            added = merge_listings(
                merged,
                payload[
                    "listings"
                ],
            )

            if added == 0:
                raise ExternalProducerError(
                    f"Page {page_number} repeated only already-seen "
                    "identities; refusing ambiguous pagination."
                )

            page_metadata.append(
                {
                    "page_number": page_number,
                    "requested_url": acquired.requested_url,
                    "final_url": acquired.final_url,
                    "http_status": acquired.http_status,
                    "item_link_count": acquired.item_link_count,
                    "seller_scoped_listings": page_count,
                    "new_unique_listings": added,
                }
            )

            print(
                "EBAY_EXTERNAL_PAGE="
                + json.dumps(
                    page_metadata[
                        -1
                    ],
                    sort_keys=True,
                    ensure_ascii=False,
                ),
                flush=True,
            )

            if not has_next_page(
                acquired.html
            ):
                break

        if not merged:
            raise ExternalProducerError(
                "External producer acquired zero seller-scoped listings."
            )

        listings = [
            merged[
                item_id
            ]
            for item_id in sorted(
                merged
            )
        ]

        document: dict[
            str,
            object,
        ] = {
            "schema": "auction-etl/ebay-structured-acquisition/v1",
            "source_name": source.name,
            "source_url": source.url,
            "collector_url": collector_url_for_source(
                source.name
            ),
            "seller_filter": source.seller,
            "collected_at_utc": collected_at,
            "page": {
                "page_count": len(
                    page_metadata
                ),
                "pages": page_metadata,
            },
            "listing_count": len(
                listings
            ),
            "listings": listings,
        }

        output = (
            arguments.output
            .expanduser()
            .resolve()
        )

        atomic_write_json(
            output,
            document,
        )

        print()
        print(
            f"EBAY_EXTERNAL_SOURCE={source.name}"
        )
        print(
            f"EBAY_EXTERNAL_SELLER={source.seller}"
        )
        print(
            f"EBAY_EXTERNAL_PROFILE={profile}"
        )
        print(
            f"EBAY_EXTERNAL_PAGES_ACQUIRED={len(page_metadata)}"
        )
        print(
            f"EBAY_EXTERNAL_LISTINGS={len(listings)}"
        )
        print(
            f"EBAY_EXTERNAL_ARTIFACT={output}"
        )

        print()
        print(
            "================ IMPORTER DRY RUN ================"
        )

        run_importer(
            output,
            source.name,
            apply=False,
        )

        print(
            "EBAY_EXTERNAL_IMPORTER_DRY_RUN=PASS"
        )

        if not arguments.apply:
            print()
            print(
                "EBAY_EXTERNAL_HANDOFF_PRODUCER=PASS"
            )
            print(
                "MODE=DRY_RUN"
            )
            print(
                "DATABASE_SESSION_OPENED=false"
            )
            print(
                "DATABASE_WRITE=false"
            )
            print(
                "EXTERNAL_RAW_PAGE_CREATED=false"
            )
            print(
                "REFRESH_EXECUTED=false"
            )
            print(
                "AUTOMATIC_RETRY=false"
            )
            return 0

        print()
        print(
            "================ EXPLICIT APPLY ================"
        )

        run_importer(
            output,
            source.name,
            apply=True,
        )

        print(
            "EBAY_EXTERNAL_HANDOFF_PRODUCER=PASS"
        )
        print(
            "MODE=APPLY"
        )
        print(
            "EXTERNAL_RAW_PAGE_APPLY_REQUESTED=true"
        )
        print(
            "REFRESH_EXECUTED=false"
        )
        print(
            "AUTOMATIC_RETRY=false"
        )

        return 0

    except (
        EbayAcquisitionError,
        ExternalProducerError,
        OSError,
        ValueError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        print(
            "EBAY_EXTERNAL_HANDOFF_PRODUCER=FAIL",
            file=sys.stderr,
        )
        print(
            "AUTOMATIC_RETRY=false",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
