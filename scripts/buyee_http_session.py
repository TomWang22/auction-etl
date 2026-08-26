"""Authenticated Buyee HTTPS access using captured Playwright storage state."""

from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


DEFAULT_WATCHLIST_URL = (
    "https://buyee.jp/myorders/watchlist/closed"
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 "
    "(X11; Linux x86_64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

LOGIN_MARKERS = (
    "/signup/login",
    "/signin",
    "/login",
    "/twofactor",
    "/captcha",
)

BLOCK_MARKERS = (
    "403 forbidden",
    "access denied",
    "temporarily blocked",
    "unusual traffic",
)

MAINTENANCE_MARKERS = (
    "site maintenance",
    "currently unavailable due to maintenance",
    "please checkback later",
)

AUCTION_LINK_PATTERN = re.compile(
    r"""href=["']([^"']*/item/jdirectitems/auction/[^"']*)["']""",
    re.IGNORECASE,
)


class BuyeeHttpState(StrEnum):
    """Canonical Buyee HTTPS session state."""

    AUTHENTICATED = "authenticated"
    AUTHENTICATION_REQUIRED = "authentication_required"
    ACCESS_BLOCKED = "access_blocked"
    MAINTENANCE = "maintenance"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class BuyeeHttpResult:
    """Result of one authenticated Buyee HTTPS request."""

    state: BuyeeHttpState
    status_code: int | None
    final_url: str
    body: str
    auction_links: tuple[str, ...]


class BuyeeHttpSessionError(RuntimeError):
    """Raised when Buyee HTTPS session state cannot be loaded or used."""


def normalize_text(value: str) -> str:
    """Normalize text for deterministic comparisons."""
    return " ".join(
        value.casefold().split()
    )


def is_buyee_domain(domain: str) -> bool:
    """Return whether a cookie belongs to Buyee."""
    normalized = domain.lstrip(".").casefold()

    return (
        normalized == "buyee.jp"
        or normalized.endswith(".buyee.jp")
    )


def _cookie_expiry(
    value: object,
) -> int | None:
    """Convert Playwright cookie expiry to cookiejar format."""
    try:
        expires = float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if expires <= 0:
        return None

    return int(expires)


def _build_cookie(
    payload: dict[str, Any],
) -> http.cookiejar.Cookie:
    """Convert one Playwright storage-state cookie."""
    domain = str(
        payload.get(
            "domain",
            "",
        )
    )

    expires = _cookie_expiry(
        payload.get(
            "expires",
            -1,
        )
    )

    return http.cookiejar.Cookie(
        version=0,
        name=str(
            payload.get(
                "name",
                "",
            )
        ),
        value=str(
            payload.get(
                "value",
                "",
            )
        ),
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path=str(
            payload.get(
                "path",
                "/",
            )
        ),
        path_specified=True,
        secure=bool(
            payload.get(
                "secure",
                False,
            )
        ),
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest={
            "HttpOnly": bool(
                payload.get(
                    "httpOnly",
                    False,
                )
            ),
        },
        rfc2109=False,
    )


def load_buyee_cookie_jar(
    storage_state_path: Path,
) -> http.cookiejar.CookieJar:
    """Load Buyee cookies from a Playwright storage-state file."""
    if not storage_state_path.is_file():
        raise BuyeeHttpSessionError(
            "Buyee storage-state file is missing: "
            f"{storage_state_path}"
        )

    try:
        payload = json.loads(
            storage_state_path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise BuyeeHttpSessionError(
            "Buyee storage-state file could not be read."
        ) from exc

    cookies = payload.get(
        "cookies",
        [],
    )

    if not isinstance(
        cookies,
        list,
    ):
        raise BuyeeHttpSessionError(
            "Buyee storage-state cookies payload is invalid."
        )

    jar = http.cookiejar.CookieJar()
    added = 0

    for raw_cookie in cookies:
        if not isinstance(
            raw_cookie,
            dict,
        ):
            continue

        domain = str(
            raw_cookie.get(
                "domain",
                "",
            )
        )

        if not is_buyee_domain(
            domain
        ):
            continue

        cookie = _build_cookie(
            raw_cookie
        )

        if not cookie.name:
            continue

        jar.set_cookie(
            cookie
        )
        added += 1

    if added == 0:
        raise BuyeeHttpSessionError(
            "Buyee storage-state file contains no Buyee cookies."
        )

    return jar


def extract_auction_links(
    body: str,
) -> tuple[str, ...]:
    """Extract unique Buyee auction-detail links from HTML."""
    links: list[str] = []
    seen: set[str] = set()

    for match in AUCTION_LINK_PATTERN.finditer(
        body
    ):
        href = match.group(1)

        if href.startswith("/"):
            href = (
                "https://buyee.jp"
                + href
            )

        if href in seen:
            continue

        seen.add(
            href
        )
        links.append(
            href
        )

    return tuple(
        links
    )


def classify_response(
    *,
    status_code: int | None,
    final_url: str,
    body: str,
) -> BuyeeHttpState:
    """Classify a Buyee HTTPS response."""
    normalized_url = final_url.casefold()
    normalized_body = normalize_text(
        body
    )

    if (
        status_code
        in {
            401,
            403,
            429,
        }
        or any(
            marker in normalized_body
            for marker in BLOCK_MARKERS
        )
    ):
        return BuyeeHttpState.ACCESS_BLOCKED

    if any(
        marker in normalized_body
        for marker in MAINTENANCE_MARKERS
    ):
        return BuyeeHttpState.MAINTENANCE

    if any(
        marker in normalized_url
        for marker in LOGIN_MARKERS
    ):
        return BuyeeHttpState.AUTHENTICATION_REQUIRED

    if (
        "/myorders/watchlist/closed"
        in normalized_url
    ):
        return BuyeeHttpState.AUTHENTICATED

    return BuyeeHttpState.INDETERMINATE


def fetch_closed_watchlist(
    *,
    storage_state_path: Path,
    url: str = DEFAULT_WATCHLIST_URL,
    timeout_seconds: float = 30.0,
) -> BuyeeHttpResult:
    """Fetch the authenticated Buyee closed watchlist over HTTPS."""
    jar = load_buyee_cookie_jar(
        storage_state_path
    )

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(
            jar
        )
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": (
                "en-US,en;q=0.9"
            ),
        },
    )

    status_code: int | None

    try:
        with opener.open(
            request,
            timeout=timeout_seconds,
        ) as response:
            status_code = response.status
            final_url = response.geturl()
            body = response.read(
                2_000_000
            ).decode(
                "utf-8",
                errors="replace",
            )

    except urllib.error.HTTPError as exc:
        status_code = exc.code
        final_url = exc.geturl()
        body = exc.read(
            2_000_000
        ).decode(
            "utf-8",
            errors="replace",
        )

    except (
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
        raise BuyeeHttpSessionError(
            "Buyee HTTPS request failed."
        ) from exc

    state = classify_response(
        status_code=status_code,
        final_url=final_url,
        body=body,
    )

    return BuyeeHttpResult(
        state=state,
        status_code=status_code,
        final_url=final_url,
        body=body,
        auction_links=extract_auction_links(
            body
        ),
    )
