from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, text

from auction_etl.classifiers.media import classify_media_details
from auction_etl.database.session import engine
from auction_etl.services.discogs_identity import catalog_token


CATALOG_PATTERNS = (
    re.compile(
        r"\b(?:MRZ|MR|DR|KRS|UPJY|TACL|POCH|UICY|UICZ|"
        r"UPCY|DCT|TRUE|TATL|TT|KL|PWB)[- ]?\d{3,5}"
        r"(?:/\d{1,5})?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:07|28|32|34|35|38)T[RX][- ]?\d{3,5}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b28MX[- ]?\d{3,5}\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d{4}[- ]?\d{3}\b",
        re.IGNORECASE,
    ),
)

REGION_RULES = (
    (
        "Hong Kong",
        (
            "hong kong",
            "香港",
            "港盤",
            "港版",
            "hk press",
            "hk pressing",
        ),
    ),
    (
        "Taiwan",
        (
            "taiwan",
            "taiwanese",
            "台湾",
            "臺灣",
            "台灣",
            "台湾盤",
        ),
    ),
    (
        "Korea",
        (
            "korea",
            "korean",
            "韓国",
            "韓國",
            "韓国盤",
        ),
    ),
    (
        "Malaysia",
        (
            "malaysia",
            "malaysian",
            "マレーシア",
        ),
    ),
    (
        "Singapore",
        (
            "singapore",
            "シンガポール",
        ),
    ),
    (
        "Japan",
        (
            "japan",
            "japanese",
            "日本盤",
            "国内盤",
            "国内版",
            "taurus",
            "トーラス",
            "polydor japan",
        ),
    ),
)

BULK_TERMS = (
    "まとめ",
    "大量",
    "セット",
    "bundle",
    "bulk",
    "lot of",
    "collection of",
    "枚まとめ",
    "本まとめ",
    "巻セット",
    "点セット",
    "本セット",
    "枚セット",
)

NON_BULK_MULTI_DISC_TERMS = (
    "2lp",
    "3lp",
    "4lp",
    "2cd",
    "3cd",
    "4cd",
    "double album",
    "double lp",
    "box set",
    "boxset",
)

TRUE_VALUES = {
    "1",
    "true",
    "t",
    "yes",
    "y",
}

FALSE_VALUES = {
    "0",
    "false",
    "f",
    "no",
    "n",
}


@dataclass(frozen=True, slots=True)
class Classification:
    catalog_number: str | None
    region: str | None
    media_type: str | None
    disc_count: int | None
    bulk_lot: bool
    obi: bool | None
    insert_present: bool | None
    poster_present: bool | None
    rental: bool | None
    sticker: bool | None
    promo: bool | None
    sealed: bool | None
    reissue: bool | None
    first_press: bool | None
    importance_score: int
    verdict: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically reclassify collector fields "
            "without touching manual overrides."
        )
    )
    parser.add_argument(
        "--marketplace",
        choices=("all", "buyee", "ebay", "gripsweat"),
        default="all",
    )
    parser.add_argument(
        "--seller",
        help="Optional case-insensitive seller filter.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    return parser.parse_args()


def normalized_text(*values: Any) -> str:
    return " ".join(
        str(value)
        for value in values
        if value is not None
    ).casefold()


def normalize_catalog(value: str) -> str:
    token = catalog_token(title=value) or catalog_token(
        catalog_number=value
    )
    if token:
        return token
    return re.sub(r"\s+", " ", value.strip().upper())


def extract_catalog(text_value: str) -> str | None:
    return catalog_token(title=text_value)


def extract_region(text_value: str) -> str | None:
    for region, terms in REGION_RULES:
        if any(term.casefold() in text_value for term in terms):
            return region

    return None


def extract_disc_count(
    text_value: str,
) -> int | None:
    patterns = (
        re.compile(
            r"\b(\d{1,2})\s*(?:x\s*)?lp\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(\d{1,2})\s*(?:x\s*)?cd\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(\d{1,2})\s*(?:x\s*)?"
            r"(?:cassette|tape|カセット)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(\d{1,2})\s*(?:disc|disk|枚組|本組)\b",
            re.IGNORECASE,
        ),
    )

    for pattern in patterns:
        match = pattern.search(text_value)

        if match is None:
            continue

        count = int(match.group(1))

        if 2 <= count <= 99:
            return count

    return None


def extract_media_type(
    text_value: str,
) -> str | None:
    classified = classify_media_details(text_value).format
    if classified:
        return classified

    if re.search(
        r"\b(?:cd\s*/\s*dvd|cd\+dvd|cd dvd)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "CD_DVD_SET"

    if re.search(
        r"\b(?:12\s*cd|12cd)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "CD_BOX_SET"

    if re.search(
        r"\b(?:cd box|cd box set|cdbox)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "CD_BOX_SET"

    if re.search(
        r"\b(?:cassette|cassette tape|カセット|テープ)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "CASSETTE"

    if re.search(
        r"\b(?:dvd|blu[- ]?ray)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "DVD"

    if re.search(
        r"\b(?:1x7|7\s*inch|7-inch|7\"|7''|ep盤|"
        r"ep single|single record)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "EP_7_INCH"

    if re.search(
        r"\b(?:12\s*inch|12-inch|12\"|12'')\b",
        text_value,
        re.IGNORECASE,
    ):
        return "12_INCH_SINGLE"

    if re.search(
        r"\b(?:\d{1,2}\s*cd|cd盤|compact disc|cd)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "CD"

    if re.search(
        r"\b(?:\d{1,2}\s*lp|1lp|2lp|3lp|"
        r"lp盤|vinyl lp|vinyl record|lp record|lp)\b",
        text_value,
        re.IGNORECASE,
    ):
        return "LP"

    if re.search(
        r"(?:ＬＰ|レコード)",
        text_value,
        re.IGNORECASE,
    ):
        return "LP"

    return None


def extract_bulk_lot(
    text_value: str,
    media_type: str | None,
    disc_count: int | None,
) -> bool:
    has_bulk_term = (
        classify_media_details(text_value).bulk_lot
        or any(
            term.casefold() in text_value
            for term in BULK_TERMS
        )
    )

    if not has_bulk_term:
        return False

    if any(
        term in text_value
        for term in NON_BULK_MULTI_DISC_TERMS
    ):
        explicit_large_count = re.search(
            r"\b(?:[5-9]|[1-9]\d{1,2})\s*"
            r"(?:cd|lp|records?|枚|本|点|巻)\b",
            text_value,
            re.IGNORECASE,
        )

        return explicit_large_count is not None

    if disc_count is not None and disc_count >= 5:
        return True

    if media_type in {
        "CD_BOX_SET",
        "CD_DVD_SET",
    }:
        return False

    return True


def positive_flag(
    text_value: str,
    positive_terms: tuple[str, ...],
    negative_terms: tuple[str, ...] = (),
) -> bool | None:
    if any(
        term.casefold() in text_value
        for term in negative_terms
    ):
        return False

    if any(
        term.casefold() in text_value
        for term in positive_terms
    ):
        return True

    return None


def completeness_flags(
    text_value: str,
) -> dict[str, bool | None]:
    return {
        "obi": positive_flag(
            text_value,
            (
                " obi",
                "obi ",
                "with obi",
                "obi strip",
                "帯付",
                "帯付き",
                "帯あり",
            ),
            (
                "no obi",
                "without obi",
                "帯なし",
                "帯無し",
            ),
        ),
        "insert_present": positive_flag(
            text_value,
            (
                "with insert",
                "insert included",
                "insert付き",
                "インサート付",
                "歌詞カード付",
                "lyric sheet",
            ),
            (
                "no insert",
                "without insert",
                "insert missing",
                "インサートなし",
            ),
        ),
        "poster_present": positive_flag(
            text_value,
            (
                "with poster",
                "poster included",
                "poster付き",
                "ポスター付",
                "pin-up",
                "pin up",
            ),
            (
                "no poster",
                "without poster",
                "poster missing",
                "ポスターなし",
            ),
        ),
        "rental": positive_flag(
            text_value,
            (
                "rental",
                "レンタル",
            ),
        ),
        "sticker": positive_flag(
            text_value,
            (
                "sticker",
                "ステッカー",
                "シール",
            ),
        ),
        "promo": positive_flag(
            text_value,
            (
                "promo",
                "promotional",
                "見本盤",
                "sample copy",
            ),
        ),
        "sealed": positive_flag(
            text_value,
            (
                "sealed",
                "unopened",
                "未開封",
                "new old stock",
            ),
            (
                "resealed",
            ),
        ),
        "reissue": positive_flag(
            text_value,
            (
                "reissue",
                "re-issue",
                "再発",
                "復刻",
                "heavyweight vinyl",
            ),
        ),
        "first_press": positive_flag(
            text_value,
            (
                "first press",
                "first pressing",
                "初回盤",
                "初版",
                "original pressing",
            ),
        ),
    }


def calculate_score(
    *,
    catalog_number: str | None,
    region: str | None,
    media_type: str | None,
    bulk_lot: bool,
    obi: bool | None,
    insert_present: bool | None,
    poster_present: bool | None,
    promo: bool | None,
    sealed: bool | None,
    reissue: bool | None,
    first_press: bool | None,
    gross_price: Decimal | None,
    bid_count: int | None,
) -> int:
    score = 20

    if catalog_number:
        score += 8

    if region in {
        "Hong Kong",
        "Taiwan",
        "Korea",
        "Malaysia",
        "Singapore",
    }:
        score += 7

    if media_type == "LP":
        score += 5
    elif media_type == "EP_7_INCH":
        score += 3
    elif media_type == "CD":
        score += 2

    if obi is True:
        score += 8

    if insert_present is True:
        score += 5

    if poster_present is True:
        score += 5

    if promo is True:
        score += 10

    if sealed is True:
        score += 5

    if first_press is True:
        score += 8

    if reissue is True:
        score -= 7

    if bulk_lot:
        score -= 15

    if bid_count is not None:
        if bid_count >= 40:
            score += 12
        elif bid_count >= 20:
            score += 8
        elif bid_count >= 10:
            score += 4

    if gross_price is not None:
        if gross_price >= Decimal("30000"):
            score += 10
        elif gross_price >= Decimal("10000"):
            score += 6
        elif gross_price >= Decimal("5000"):
            score += 3

    return max(
        0,
        min(score, 100),
    )


def verdict_for(
    score: int,
    *,
    bulk_lot: bool,
    reissue: bool | None,
) -> str:
    if bulk_lot:
        return "BULK_REVIEW"

    if reissue is True and score < 45:
        return "LOW_PRIORITY_REISSUE"

    if score >= 70:
        return "STRONG_INTEREST"

    if score >= 50:
        return "WATCH"

    if score >= 35:
        return "REFERENCE_ONLY"

    return "PASS"


def classify(row: dict[str, Any]) -> Classification:
    text_value = normalized_text(
        row.get("title"),
        row.get("description"),
        row.get("condition_text"),
    )

    catalog_number = extract_catalog(
        text_value
    )
    region = extract_region(
        text_value
    )
    disc_count = extract_disc_count(
        text_value
    )
    media_type = extract_media_type(
        text_value
    )

    bulk_lot = extract_bulk_lot(
        text_value,
        media_type,
        disc_count,
    )

    flags = completeness_flags(
        text_value
    )

    gross_price = row.get("gross_price")

    if gross_price is not None:
        gross_price = Decimal(
            str(gross_price)
        )

    bid_count = row.get("bid_count")

    score = calculate_score(
        catalog_number=catalog_number,
        region=region,
        media_type=media_type,
        bulk_lot=bulk_lot,
        obi=flags["obi"],
        insert_present=flags[
            "insert_present"
        ],
        poster_present=flags[
            "poster_present"
        ],
        promo=flags["promo"],
        sealed=flags["sealed"],
        reissue=flags["reissue"],
        first_press=flags["first_press"],
        gross_price=gross_price,
        bid_count=bid_count,
    )

    return Classification(
        catalog_number=catalog_number,
        region=region,
        media_type=media_type,
        disc_count=disc_count,
        bulk_lot=bulk_lot,
        obi=flags["obi"],
        insert_present=flags[
            "insert_present"
        ],
        poster_present=flags[
            "poster_present"
        ],
        rental=flags["rental"],
        sticker=flags["sticker"],
        promo=flags["promo"],
        sealed=flags["sealed"],
        reissue=flags["reissue"],
        first_press=flags["first_press"],
        importance_score=score,
        verdict=verdict_for(
            score,
            bulk_lot=bulk_lot,
            reissue=flags["reissue"],
        ),
    )


RECLASSIFICATION_FIELDS = (
    "auto_catalog_number",
    "auto_region",
    "auto_media_type",
    "auto_disc_count",
    "auto_bulk_lot",
    "auto_obi",
    "auto_insert_present",
    "auto_poster_present",
    "auto_rental",
    "auto_sticker",
    "auto_promo",
    "auto_sealed",
    "auto_reissue",
    "auto_first_press",
    "auto_importance_score",
    "auto_verdict",
)


def automatic_classification_changed(
    row: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    """Return whether a calculated automatic value differs from storage."""

    return any(
        row.get(
            f"stored_{field}"
        )
        != payload[field]
        for field in RECLASSIFICATION_FIELDS
    )


def available_columns(
    schema: str,
    table_name: str,
) -> set[str]:
    inspector = inspect(engine)

    return {
        column["name"]
        for column in inspector.get_columns(
            table_name,
            schema=schema,
        )
    }


def main() -> int:
    args = parse_args()

    collector_columns = available_columns(
        "warehouse",
        "auction_collector",
    )

    required_columns = {
        "marketplace",
        "listing_id",
        "account_id",
        "auto_catalog_number",
        "auto_region",
        "auto_media_type",
        "auto_disc_count",
        "auto_bulk_lot",
        "auto_obi",
        "auto_insert_present",
        "auto_poster_present",
        "auto_rental",
        "auto_sticker",
        "auto_promo",
        "auto_sealed",
        "auto_reissue",
        "auto_first_press",
        "auto_importance_score",
        "auto_verdict",
    }

    missing = sorted(
        required_columns
        - collector_columns
    )

    if missing:
        raise SystemExit(
            "Missing collector columns: "
            + ", ".join(missing)
        )

    clauses: list[str] = []
    parameters: dict[str, Any] = {}

    if args.marketplace != "all":
        clauses.append(
            "a.marketplace = :marketplace"
        )
        parameters[
            "marketplace"
        ] = args.marketplace

    if args.seller:
        clauses.append(
            "COALESCE(a.seller, '') "
            "ILIKE :seller"
        )
        parameters[
            "seller"
        ] = f"%{args.seller}%"

    where_clause = ""

    if clauses:
        where_clause = (
            "WHERE "
            + " AND ".join(clauses)
        )

    auction_columns = available_columns(
        "warehouse",
        "auction",
    )

    def optional_expression(
        column_name: str,
        sql_type: str = "text",
    ) -> str:
        """Return a real column or a typed NULL fallback."""
        if column_name in auction_columns:
            return f"a.{column_name}"

        return f"NULL::{sql_type}"

    select_sql = f"""
        SELECT
            a.marketplace,
            a.listing_id,
            {optional_expression("title")} AS title,
            {optional_expression("description")} AS description,
            {optional_expression("condition_text")} AS condition_text,
            {optional_expression("gross_price", "numeric")} AS gross_price,
            {optional_expression("bid_count", "integer")} AS bid_count,
            c.auto_catalog_number AS stored_auto_catalog_number,
            c.auto_region AS stored_auto_region,
            c.auto_media_type AS stored_auto_media_type,
            c.auto_disc_count AS stored_auto_disc_count,
            c.auto_bulk_lot AS stored_auto_bulk_lot,
            c.auto_obi AS stored_auto_obi,
            c.auto_insert_present AS stored_auto_insert_present,
            c.auto_poster_present AS stored_auto_poster_present,
            c.auto_rental AS stored_auto_rental,
            c.auto_sticker AS stored_auto_sticker,
            c.auto_promo AS stored_auto_promo,
            c.auto_sealed AS stored_auto_sealed,
            c.auto_reissue AS stored_auto_reissue,
            c.auto_first_press AS stored_auto_first_press,
            c.auto_importance_score AS stored_auto_importance_score,
            c.auto_verdict AS stored_auto_verdict
        FROM warehouse.auction AS a
        LEFT JOIN warehouse.auction_collector AS c
          ON c.marketplace = a.marketplace
         AND c.listing_id = a.listing_id
         AND c.account_id IS NULL
        {where_clause}
        ORDER BY
            a.marketplace,
            a.listing_id
    """

    insert_legacy_sql = text(
        """
        INSERT INTO warehouse.auction_collector (
            marketplace,
            listing_id,
            auto_catalog_number,
            auto_region,
            auto_media_type,
            auto_disc_count,
            auto_bulk_lot,
            auto_obi,
            auto_insert_present,
            auto_poster_present,
            auto_rental,
            auto_sticker,
            auto_promo,
            auto_sealed,
            auto_reissue,
            auto_first_press,
            auto_importance_score,
            auto_verdict,
            updated_at
        )
        VALUES (
            :marketplace,
            :listing_id,
            :auto_catalog_number,
            :auto_region,
            :auto_media_type,
            :auto_disc_count,
            :auto_bulk_lot,
            :auto_obi,
            :auto_insert_present,
            :auto_poster_present,
            :auto_rental,
            :auto_sticker,
            :auto_promo,
            :auto_sealed,
            :auto_reissue,
            :auto_first_press,
            :auto_importance_score,
            :auto_verdict,
            NOW()
        )
        ON CONFLICT (marketplace, listing_id)
        WHERE account_id IS NULL
        DO UPDATE SET
            auto_catalog_number =
                EXCLUDED.auto_catalog_number,
            auto_region =
                EXCLUDED.auto_region,
            auto_media_type =
                EXCLUDED.auto_media_type,
            auto_disc_count =
                EXCLUDED.auto_disc_count,
            auto_bulk_lot =
                EXCLUDED.auto_bulk_lot,
            auto_obi =
                EXCLUDED.auto_obi,
            auto_insert_present =
                EXCLUDED.auto_insert_present,
            auto_poster_present =
                EXCLUDED.auto_poster_present,
            auto_rental =
                EXCLUDED.auto_rental,
            auto_sticker =
                EXCLUDED.auto_sticker,
            auto_promo =
                EXCLUDED.auto_promo,
            auto_sealed =
                EXCLUDED.auto_sealed,
            auto_reissue =
                EXCLUDED.auto_reissue,
            auto_first_press =
                EXCLUDED.auto_first_press,
            auto_importance_score =
                EXCLUDED.auto_importance_score,
            auto_verdict =
                EXCLUDED.auto_verdict,
            updated_at = NOW()
        """
    )

    insert_account_sql = text(
        """
        INSERT INTO warehouse.auction_collector (
            account_id,
            marketplace,
            listing_id,
            auto_catalog_number,
            auto_region,
            auto_media_type,
            auto_disc_count,
            auto_bulk_lot,
            auto_obi,
            auto_insert_present,
            auto_poster_present,
            auto_rental,
            auto_sticker,
            auto_promo,
            auto_sealed,
            auto_reissue,
            auto_first_press,
            auto_importance_score,
            auto_verdict,
            updated_at
        )
        SELECT
            visible.account_id,
            CAST(:marketplace AS varchar),
            CAST(:listing_id AS varchar),
            CAST(:auto_catalog_number AS varchar),
            CAST(:auto_region AS varchar),
            CAST(:auto_media_type AS varchar),
            CAST(:auto_disc_count AS integer),
            CAST(:auto_bulk_lot AS boolean),
            CAST(:auto_obi AS boolean),
            CAST(:auto_insert_present AS boolean),
            CAST(:auto_poster_present AS boolean),
            CAST(:auto_rental AS boolean),
            CAST(:auto_sticker AS boolean),
            CAST(:auto_promo AS boolean),
            CAST(:auto_sealed AS boolean),
            CAST(:auto_reissue AS boolean),
            CAST(:auto_first_press AS boolean),
            CAST(:auto_importance_score AS integer),
            CAST(:auto_verdict AS varchar),
            NOW()
        FROM account.auction_listing AS visible
        WHERE lower(btrim(visible.marketplace)) =
              lower(btrim(CAST(:marketplace AS text)))
          AND visible.listing_id = CAST(:listing_id AS text)
        ON CONFLICT (account_id, marketplace, listing_id)
        WHERE account_id IS NOT NULL
        DO UPDATE SET
            auto_catalog_number =
                EXCLUDED.auto_catalog_number,
            auto_region =
                EXCLUDED.auto_region,
            auto_media_type =
                EXCLUDED.auto_media_type,
            auto_disc_count =
                EXCLUDED.auto_disc_count,
            auto_bulk_lot =
                EXCLUDED.auto_bulk_lot,
            auto_obi =
                EXCLUDED.auto_obi,
            auto_insert_present =
                EXCLUDED.auto_insert_present,
            auto_poster_present =
                EXCLUDED.auto_poster_present,
            auto_rental =
                EXCLUDED.auto_rental,
            auto_sticker =
                EXCLUDED.auto_sticker,
            auto_promo =
                EXCLUDED.auto_promo,
            auto_sealed =
                EXCLUDED.auto_sealed,
            auto_reissue =
                EXCLUDED.auto_reissue,
            auto_first_press =
                EXCLUDED.auto_first_press,
            auto_importance_score =
                EXCLUDED.auto_importance_score,
            auto_verdict =
                EXCLUDED.auto_verdict,
            updated_at = NOW()
        """
    )

    scanned = 0
    changed = 0
    media_counts: dict[str, int] = {}
    suspicious_disc_counts = 0

    with engine.begin() as connection:
        rows = connection.execute(
            text(select_sql),
            parameters,
        ).mappings().all()

        if args.marketplace in {"all", "gripsweat"}:
            gripsweat_rows = connection.execute(
                text(
                    """
                    SELECT
                        'gripsweat' AS marketplace,
                        COALESCE(
                            NULLIF(g.original_listing_id, ''),
                            g.gripsweat_item_id,
                            g.gripsweat_item_key
                        ) AS listing_id,
                        g.title AS title,
                        g.raw_text AS description,
                        NULL::text AS condition_text,
                        g.sold_price AS gross_price,
                        0 AS bid_count,
                        c.auto_catalog_number AS stored_auto_catalog_number,
                        c.auto_region AS stored_auto_region,
                        c.auto_media_type AS stored_auto_media_type,
                        c.auto_disc_count AS stored_auto_disc_count,
                        c.auto_bulk_lot AS stored_auto_bulk_lot,
                        c.auto_obi AS stored_auto_obi,
                        c.auto_insert_present AS stored_auto_insert_present,
                        c.auto_poster_present AS stored_auto_poster_present,
                        c.auto_rental AS stored_auto_rental,
                        c.auto_sticker AS stored_auto_sticker,
                        c.auto_promo AS stored_auto_promo,
                        c.auto_sealed AS stored_auto_sealed,
                        c.auto_reissue AS stored_auto_reissue,
                        c.auto_first_press AS stored_auto_first_press,
                        c.auto_importance_score AS stored_auto_importance_score,
                        c.auto_verdict AS stored_auto_verdict
                    FROM warehouse.gripsweat_sale AS g
                    LEFT JOIN warehouse.auction_collector AS c
                      ON c.marketplace = 'gripsweat'
                     AND c.listing_id = COALESCE(
                            NULLIF(g.original_listing_id, ''),
                            g.gripsweat_item_id,
                            g.gripsweat_item_key
                        )
                     AND c.account_id IS NULL
                    WHERE COALESCE(
                            NULLIF(g.original_listing_id, ''),
                            g.gripsweat_item_id,
                            g.gripsweat_item_key
                        ) IS NOT NULL
                      AND NOT EXISTS (
                            SELECT 1
                            FROM warehouse.auction AS a
                            WHERE a.marketplace = 'ebay'
                              AND a.listing_id = COALESCE(
                                    NULLIF(g.original_listing_id, ''),
                                    g.gripsweat_item_id,
                                    g.gripsweat_item_key
                                )
                        )
                    """
                )
            ).mappings().all()
            rows = [*rows, *gripsweat_rows]

        for row_mapping in rows:
            row = dict(row_mapping)
            classification = classify(row)
            scanned += 1

            if (
                classification.disc_count
                is not None
                and classification.disc_count > 99
            ):
                suspicious_disc_counts += 1

            if classification.media_type:
                media_counts[
                    classification.media_type
                ] = (
                    media_counts.get(
                        classification.media_type,
                        0,
                    )
                    + 1
                )

            payload = {
                "marketplace": row[
                    "marketplace"
                ],
                "listing_id": row[
                    "listing_id"
                ],
                "auto_catalog_number": (
                    classification.catalog_number
                ),
                "auto_region": (
                    classification.region
                ),
                "auto_media_type": (
                    classification.media_type
                ),
                "auto_disc_count": (
                    classification.disc_count
                ),
                "auto_bulk_lot": (
                    classification.bulk_lot
                ),
                "auto_obi": (
                    classification.obi
                ),
                "auto_insert_present": (
                    classification.insert_present
                ),
                "auto_poster_present": (
                    classification.poster_present
                ),
                "auto_rental": (
                    classification.rental
                ),
                "auto_sticker": (
                    classification.sticker
                ),
                "auto_promo": (
                    classification.promo
                ),
                "auto_sealed": (
                    classification.sealed
                ),
                "auto_reissue": (
                    classification.reissue
                ),
                "auto_first_press": (
                    classification.first_press
                ),
                "auto_importance_score": (
                    classification.importance_score
                ),
                "auto_verdict": (
                    classification.verdict
                ),
            }

            if not args.dry_run:
                if row["marketplace"] != "gripsweat":
                    connection.execute(
                        text(
                            """
                            UPDATE warehouse.auction
                            SET
                                catalog_number = :catalog_number,
                                media_type = COALESCE(
                                    :media_type,
                                    media_type
                                ),
                                bulk_lot = :bulk_lot
                            WHERE marketplace = :marketplace
                              AND listing_id = :listing_id
                            """
                        ),
                        {
                            "marketplace": row["marketplace"],
                            "listing_id": row["listing_id"],
                            "catalog_number": classification.catalog_number,
                            "media_type": classification.media_type,
                            "bulk_lot": classification.bulk_lot,
                        },
                    )
                legacy = connection.execute(
                    insert_legacy_sql,
                    payload,
                )
                account = connection.execute(
                    insert_account_sql,
                    payload,
                )
                changed += legacy.rowcount + account.rowcount
                continue

            if not automatic_classification_changed(
                row,
                payload,
            ):
                continue

        if args.dry_run:
            connection.rollback()

    print()
    print("Collector reclassification")
    print("--------------------------")
    print("Scanned              :", scanned)
    print("Rows updated         :", changed)
    print(
        "Suspicious disc count:",
        suspicious_disc_counts,
    )

    print()
    print("Media classifications")
    print("---------------------")

    for media_type, count in sorted(
        media_counts.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    ):
        print(
            f"{media_type:20}: {count}"
        )

    if args.dry_run:
        print()
        print("Dry run complete; no rows changed.")
    else:
        print()
        print(
            "Manual override columns were preserved."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
