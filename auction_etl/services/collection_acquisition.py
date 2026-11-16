"""Counts of how copies on the shelf were acquired."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from auction_etl.services.discogs_identity import canonical_artist_display


_SALE_TYPES = frozenset({"AUCTION", "FIXED_PRICE", "FIXED_PRICE_OBO"})
_SALE_TYPE_LABELS = {
    "AUCTION": "Auction",
    "FIXED_PRICE": "Fixed",
    "FIXED_PRICE_OBO": "OBO",
}
_STORED_SALE_SHOPS = frozenset({"ebay", "gripsweat"})
_DEFAULT_SALE_TYPES = {
    "buyee": "AUCTION",
    "recordcity": "FIXED_PRICE",
}
_DEFAULT_DELIVERY_LAG = {
    "buyee": 4,
    "recordcity": 4,
}
_TYPE_ORDER = ("Auction", "Fixed", "OBO", "Unlabeled")
_SHOP_ORDER = ("eBay", "Buyee", "Discogs", "Other")
_PACKAGE_ORDER = (
    "EP",
    "Single sleeve LP",
    "Single gatefold",
    "Double LP gatefold",
    "Trifold",
    "Box set",
    "CD",
    "Cassette",
    "DVD",
    "Laserdisc",
    "Bulk lot",
    "Unset",
)
_ARTIST_LIMIT = 8
_BULK_MEDIA = frozenset(
    {
        "LP_BULK_LOT",
        "EP_BULK_LOT",
        "CD_BULK_LOT",
        "CASSETTE_BULK_LOT",
        "MIXED_BULK_LOT",
        "MAGAZINE_BULK_LOT",
        "BULK_LOT",
    }
)
_BOX_MEDIA = frozenset({"LP_BOX_SET", "CD_BOX_SET", "CASSETTE_BOX_SET", "BOX_SET"})
_EP_MEDIA = frozenset({"EP_7_INCH", "EP"})
_CD_MEDIA = frozenset(
    {"CD", "SHM_CD", "SACD", "BLU_SPEC_CD", "CD_SINGLE_8CM"}
)
_LP_MEDIA = frozenset({"LP", "VINYL", "SINGLE_12_INCH", "12_INCH_SINGLE"})


def sale_type_code(value: object) -> str:
    """Auction / fixed / OBO, or blank when the copy is still unlabeled."""

    if value is None:
        return ""
    code = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    if code in {"", "NONE", "NAN", "<NA>", "NAT"}:
        return ""
    if code in _SALE_TYPES:
        return code
    return ""


def sale_type_label(value: object) -> str:
    return _SALE_TYPE_LABELS.get(sale_type_code(value), "Unlabeled")


def default_sale_type(marketplace: object) -> str:
    """Buyee is an auction unless the operator says otherwise. Record City is fixed."""

    market = str(marketplace or "").strip().lower()
    return _DEFAULT_SALE_TYPES.get(market, "")


def default_delivered_on(
    marketplace: object,
    paid_on: date | None,
    delivered_on: date | None,
) -> date | None:
    """Buyee and Record City land about four days after the order date."""

    if delivered_on is not None:
        return delivered_on
    if paid_on is None:
        return None
    market = str(marketplace or "").strip().lower()
    lag = _DEFAULT_DELIVERY_LAG.get(market)
    if lag is None:
        return None
    return paid_on + timedelta(days=lag)


def effective_sale_type(
    *,
    marketplace: object,
    stored: object,
    manual: object,
) -> str:
    """Manual label wins. eBay/Gripsweat can default to the Review format.

    Buyee is auction and Record City is fixed unless the operator overrides.
    """

    chosen = sale_type_code(manual)
    if chosen:
        return chosen
    market = str(marketplace or "").strip().lower()
    if market in _STORED_SALE_SHOPS:
        stored_code = sale_type_code(stored)
        if stored_code:
            return stored_code
    return default_sale_type(market)


def shop_bucket(marketplace: object) -> str:
    """Gripsweat is the same eBay item. Everything else keeps its shop."""

    market = str(marketplace or "").strip().lower()
    if market in {"ebay", "gripsweat"}:
        return "eBay"
    if market == "buyee":
        return "Buyee"
    if market in {"discogs", "log"}:
        return "Discogs"
    return "Other"


def _paid_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text or text.lower() in {"nat", "none", "nan"}:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _period_key(paid_on: date, grain: str) -> str:
    if grain == "year":
        return str(paid_on.year)
    if grain == "week":
        iso = paid_on.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return f"{paid_on.year}-{paid_on.month:02d}"


def collection_artist_label(row: dict[str, Any]) -> str:
    """One bar per artist, even when Discogs and bills spell the name differently."""

    for field in ("artist_section", "artist_name"):
        label = canonical_artist_display(row.get(field))
        if label and label.casefold() != "unknown":
            return label
    for field in ("album_title", "listing_title"):
        label = canonical_artist_display(row.get(field), known_only=True)
        if label and label.casefold() != "unknown":
            return label
    return "Unknown"


def _positive_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    try:
        count = int(value)
    except (TypeError, ValueError):
        text = str(value or "").strip()
        if not text or text.casefold() in {"nan", "none", "nat"}:
            return None
        try:
            count = int(float(text))
        except (TypeError, ValueError):
            return None
    return count if count > 0 else None


def collection_package_label(row: dict[str, Any]) -> str:
    """Sleeve and disc shape for the collection breakdown."""

    media = str(
        row.get("manual_media_type") or row.get("media_type") or ""
    ).strip().upper()
    detail = str(row.get("format_detail") or "").casefold()
    discs = _positive_int(row.get("manual_disc_count"))
    if discs is None:
        discs = _positive_int(row.get("disc_count"))
    if media in _BULK_MEDIA:
        return "Bulk lot"
    if (
        media in _BOX_MEDIA
        or "box set" in detail
        or "box-set" in detail
    ):
        return "Box set"
    if media in _EP_MEDIA:
        return "EP"
    if media in _CD_MEDIA:
        return "CD"
    if media == "CASSETTE":
        return "Cassette"
    if media in {"DVD", "VHS"}:
        return "DVD"
    if media == "LASERDISC":
        return "Laserdisc"
    vinyl = media in _LP_MEDIA
    if not vinyl:
        return "Unset"
    if discs is not None and discs >= 4:
        return "Box set"
    if discs == 3 or "trifold" in detail:
        return "Trifold"
    if discs == 2:
        return "Double LP gatefold"
    if "gatefold" in detail:
        return "Single gatefold"
    if discs == 1:
        return "Single sleeve LP"
    return "Unset"


def acquisition_breakdown(
    rows: list[dict[str, Any]],
    *,
    grain: str = "month",
) -> dict[str, Any]:
    """Type, shop, package, paid-on period, and artist counts. One row is one record."""

    types = {label: 0 for label in _TYPE_ORDER}
    shops = {label: 0 for label in _SHOP_ORDER}
    packages = {label: 0 for label in _PACKAGE_ORDER}
    periods: dict[str, int] = {}
    artists: dict[str, int] = {}
    undated = 0
    for row in rows:
        label = sale_type_label(
            effective_sale_type(
                marketplace=row.get("marketplace"),
                stored=row.get("stored_sale_type"),
                manual=row.get("sale_type"),
            )
        )
        types[label] = types.get(label, 0) + 1
        shop = shop_bucket(row.get("marketplace"))
        shops[shop] = shops.get(shop, 0) + 1
        paid_on = _paid_date(row.get("paid_on"))
        if paid_on is None:
            undated += 1
        else:
            key = _period_key(paid_on, grain)
            periods[key] = periods.get(key, 0) + 1
        artist = collection_artist_label(row)
        artists[artist] = artists.get(artist, 0) + 1
        package = collection_package_label(row)
        packages[package] = packages.get(package, 0) + 1
    ranked = sorted(artists.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > _ARTIST_LIMIT:
        head = ranked[:_ARTIST_LIMIT]
        other = sum(count for _name, count in ranked[_ARTIST_LIMIT:])
        head.append(("Other", other))
        ranked = head
    return {
        "types": [(label, types[label]) for label in _TYPE_ORDER],
        "shops": [(label, shops[label]) for label in _SHOP_ORDER if shops[label]],
        "packages": [
            (label, packages[label])
            for label in _PACKAGE_ORDER
            if packages[label]
        ],
        "periods": sorted(periods.items()),
        "artists": ranked,
        "undated": undated,
    }
