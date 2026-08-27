"""Regression tests for hidden background Buyee CDP production wiring."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[1]

MANAGER = (
    ROOT
    / "auction_etl"
    / "browser"
    / "manager.py"
)

CDP_MODULE = (
    ROOT
    / "auction_etl"
    / "browser"
    / "buyee_cdp.py"
)

VERIFIER = (
    ROOT
    / "scripts"
    / "verify_buyee_session.py"
)

CRAWLER = (
    ROOT
    / "scripts"
    / "crawl_buyee_live_details.py"
)

ENSURE = (
    ROOT
    / "scripts"
    / "ensure_buyee_cdp_browser.py"
)

RUNNER = (
    ROOT
    / "scripts"
    / "run_latest_auction_refresh.py"
)

MULTISOURCE = (
    ROOT
    / "scripts"
    / "run_multisource_ingestion_round.py"
)

ON_DEMAND = (
    ROOT
    / "scripts"
    / "run_auction_refresh_on_demand.sh"
)


def source(
    path: Path,
) -> str:
    """Read one repository source file."""

    value = path.read_text(
        encoding="utf-8",
    )

    if path.suffix == ".py":
        ast.parse(
            value,
            filename=str(path),
        )

    return value


def test_shared_cdp_support_connects_to_existing_browser() -> None:
    """Buyee CDP must attach instead of launching a second profile."""

    value = source(
        CDP_MODULE
    )

    assert (
        'CDP_URL_ENV = "AUCTION_BUYEE_CDP_URL"'
        in value
    )

    assert (
        "connect_over_cdp("
        in value
    )

    assert (
        "launch_persistent_context("
        in value
    )

    assert (
        "return (\n            context,\n            False,"
        in value
    )


def test_verifier_uses_borrowed_context_ownership() -> None:
    """Verifier must not close the shared CDP context."""

    value = source(
        VERIFIER
    )

    assert (
        "open_buyee_context("
        in value
    )

    assert (
        "context, owns_context, _cdp_browser"
        in value
    )

    assert (
        "if owns_context:"
        in value
    )

    assert (
        "context.close()"
        in value
    )


def test_detail_crawler_uses_borrowed_context_ownership() -> None:
    """Detail crawling must share the same background browser."""

    value = source(
        CRAWLER
    )

    assert (
        "open_buyee_context("
        in value
    )

    assert (
        "context, owns_context, _cdp_browser"
        in value
    )

    assert (
        "if owns_context:"
        in value
    )


def test_browser_manager_does_not_close_borrowed_cdp_context() -> None:
    """CLI crawling must not terminate the long-lived Buyee browser."""

    value = source(
        MANAGER
    )

    assert (
        "connect_buyee_cdp_context("
        in value
    )

    assert (
        "self._borrowed_profiles.add(profile)"
        in value
    )

    assert (
        "if profile not in self._borrowed_profiles:"
        in value
    )

    assert (
        "context.close()"
        in value
    )


def test_background_launcher_is_headed_but_hidden() -> None:
    """Production browser must be hidden, not Chromium headless."""

    value = source(
        ENSURE
    )

    assert '"open",' in value
    assert '"-g",' in value
    assert '"-j",' in value
    assert '"-n",' in value
    assert '"Google Chrome",' in value

    assert (
        "--remote-debugging-port="
        in value
    )

    assert (
        "--user-data-dir="
        in value
    )

    assert (
        "--headless"
        not in value
    )

    assert (
        "VISIBLE_BROWSER_LAUNCHED=false"
        in value
    )


def test_runner_defaults_to_dedicated_buyee_profile() -> None:
    """Direct latest refresh must default to the authenticated profile."""

    value = source(
        RUNNER
    )

    assert (
        '"AUCTION_BUYEE_PROFILE",\n'
        '            "buyee",'
        in value
    )

    assert (
        'default="anonymous"'
        not in value[
            value.index(
                '"--buyee-profile"'
            ):
            value.index(
                "return parser.parse_args()"
            )
        ]
    )


def test_multisource_defaults_to_dedicated_buyee_profile() -> None:
    """Outer production refresh must not pass anonymous downstream."""

    value = source(
        MULTISOURCE
    )

    marker = (
        '"--buyee-profile"'
    )

    start = value.index(
        marker
    )

    end = value.index(
        '"--execute"',
        start,
    )

    segment = value[
        start:end
    ]

    assert (
        '"AUCTION_BUYEE_PROFILE"'
        in segment
    )

    assert '"buyee"' in segment
    assert '"anonymous"' not in segment


def test_on_demand_refresh_defaults_to_buyee() -> None:
    """Shell production entry point must use the same profile."""

    value = source(
        ON_DEMAND
    )

    assert (
        "${AUCTION_BUYEE_PROFILE:-buyee}"
        in value
    )

    assert (
        "${AUCTION_BUYEE_PROFILE:-anonymous}"
        not in value
    )


def test_runner_starts_background_service_before_verifier() -> None:
    """Start the reusable owner before HTTPS authentication verification."""
    value = source(
        RUNNER
    )

    profile_index = value.index(
        'environment["AUCTION_BUYEE_PROFILE"]'
    )
    socket_index = value.index(
        'environment["AUCTION_BUYEE_OWNER_SOCKET"]'
    )
    legacy_cdp_removal_index = value.index(
        '"AUCTION_BUYEE_CDP_URL"',
        socket_index,
    )
    owner_index = value.index(
        "scripts/ensure_buyee_owner.py",
        legacy_cdp_removal_index,
    )
    verifier_index = value.index(
        "scripts/verify_buyee_session.py",
        owner_index,
    )
    storage_state_index = value.index(
        "--storage-state",
        verifier_index,
    )

    assert (
        profile_index
        < socket_index
        < legacy_cdp_removal_index
        < owner_index
        < verifier_index
        < storage_state_index
    )

    assert (
        "scripts/ensure_buyee_cdp_browser.py"
        not in value
    )



def test_runner_keeps_headless_fallback_safety() -> None:
    """Keep HTTPS verification noninteractive if browser fallback is needed."""
    value = source(
        RUNNER
    )

    owner_index = value.index(
        "scripts/ensure_buyee_owner.py"
    )
    verifier_index = value.index(
        "scripts/verify_buyee_session.py",
        owner_index,
    )
    storage_state_index = value.index(
        "--storage-state",
        verifier_index,
    )
    profile_argument_index = value.index(
        "--profile-dir",
        storage_state_index,
    )
    headless_index = value.index(
        "--headless",
        profile_argument_index,
    )
    timeout_index = value.index(
        "--timeout-minutes",
        headless_index,
    )

    assert (
        owner_index
        < verifier_index
        < storage_state_index
        < profile_argument_index
        < headless_index
        < timeout_index
    )



def test_production_has_no_anonymous_buyee_fallbacks() -> None:
    """Known production profile fallbacks must no longer be anonymous."""

    runner = source(
        RUNNER
    )

    multisource = source(
        MULTISOURCE
    )

    on_demand = source(
        ON_DEMAND
    )

    assert (
        "${AUCTION_BUYEE_PROFILE:-anonymous}"
        not in on_demand
    )

    runner_profile = runner[
        runner.index(
            '"--buyee-profile"'
        ):
        runner.index(
            "return parser.parse_args()"
        )
    ]

    multisource_profile = multisource[
        multisource.index(
            '"--buyee-profile"'
        ):
        multisource.index(
            '"--execute"'
        )
    ]

    assert '"anonymous"' not in runner_profile
    assert '"anonymous"' not in multisource_profile
