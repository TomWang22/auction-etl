from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.error import URLError
from urllib.request import Request, urlopen


FRANKFURTER_URL = (
    "https://api.frankfurter.dev/v1/latest"
    "?base={base}&symbols={quote}"
)


@dataclass(frozen=True, slots=True)
class FxQuote:
    base: str
    quote: str
    rate: Decimal
    rate_date: date
    source: str


def latest_rate(
    base: str,
    quote: str = "USD",
    *,
    timeout: float = 15.0,
) -> FxQuote:
    base = base.upper()
    quote = quote.upper()

    if base == quote:
        return FxQuote(
            base=base,
            quote=quote,
            rate=Decimal("1"),
            rate_date=date.today(),
            source="identity",
        )

    url = FRANKFURTER_URL.format(
        base=base,
        quote=quote,
    )

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "auction-etl/0.1",
        },
    )

    try:
        with urlopen(
            request,
            timeout=timeout,
        ) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError) as exc:
        raise RuntimeError(
            f"Unable to retrieve {base}/{quote} exchange rate."
        ) from exc

    try:
        rate = Decimal(
            str(payload["rates"][quote])
        )
        rate_date = date.fromisoformat(
            payload["date"]
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            f"Invalid FX response for {base}/{quote}."
        ) from exc

    return FxQuote(
        base=base,
        quote=quote,
        rate=rate,
        rate_date=rate_date,
        source="Frankfurter / ECB reference rate",
    )
