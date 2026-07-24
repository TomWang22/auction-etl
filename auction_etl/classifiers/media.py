from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaClassification:
    format: str | None
    disc_count: int | None
    bulk_lot: bool


_BULK_PATTERNS = (
    r"\blot\b",
    r"\bbundle\b",
    r"\bcollection\b",
    r"\bbulk\b",
    r"\bjob\s*lot\b",
    r"\bvarious\s+artists\b",
    r"まとめ",
    r"大量",
    r"セット",
    r"一括",
    r"約\s*\d+\s*枚",
)

_BOX_PATTERNS = (
    r"\bbox\s*set\b",
    r"\bbox\b",
    r"\bboxed\s*set\b",
    r"ボックス",
    r"全集",
    r"complete\s+collection",
)

_MEDIA_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "CD_SINGLE_8CM",
        (
            r"\b8\s*cm\s*cd\b",
            r"\b3\s*inch\s*cd\b",
            r"8センチ",
            r"8cmシングル",
        ),
    ),
    (
        "SHM_CD",
        (
            r"\bshm[\s-]*cd\b",
        ),
    ),
    (
        "SACD",
        (
            r"\bsacd\b",
            r"super\s*audio\s*cd",
        ),
    ),
    (
        "BLU_SPEC_CD",
        (
            r"\bblu[\s-]*spec\b",
        ),
    ),
    (
        "EP_7_INCH",
        (
            r"\bep\b",
            r"7\s*(?:inch|インチ|[\"”])",
            r"\b45\s*rpm\b",
            r"7インチ",
            r"ドーナツ盤",
        ),
    ),
    (
        "12_INCH_SINGLE",
        (
            r"12\s*(?:inch|インチ|[\"”])\s*(?:single|シングル)",
        ),
    ),
    (
        "LASERDISC",
        (
            r"\blaserdisc\b",
            r"\blaser\s*disc\b",
            r"レーザーディスク",
        ),
    ),
    (
        "CASSETTE",
        (
            r"\bcassette\b",
            r"cassette\s*tape",
            r"カセット",
            r"カセットテープ",
            r"磁带",
        ),
    ),
    (
        "REEL_TO_REEL",
        (
            r"\breel[\s-]*to[\s-]*reel\b",
            r"オープンリール",
        ),
    ),
    (
        "VHS",
        (
            r"\bvhs\b",
            r"ビデオテープ",
        ),
    ),
    (
        "DVD",
        (
            r"\bdvd\b",
            r"ＤＶＤ",
        ),
    ),
    (
        "CD",
        (
            r"\bcd\b",
            r"compact\s*disc",
            r"ＣＤ",
        ),
    ),
    (
        "LP",
        (
            r"\blp\b",
            r"\bvinyl\b",
            r"\brecord\b",
            r"12\s*(?:inch|インチ|[\"”])",
            r"レコード",
            r"ＬＰ",
            r"黑胶",
            r"唱片",
        ),
    ),
)


def _matches_any(
    text: str,
    patterns: tuple[str, ...],
) -> bool:
    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE,
        )
        for pattern in patterns
    )


def _extract_disc_count(
    text: str,
    media_format: str | None,
) -> int | None:
    patterns: list[str] = []

    if media_format in {
        "CD",
        "SHM_CD",
        "SACD",
        "BLU_SPEC_CD",
        "CD_SINGLE_8CM",
    }:
        patterns.extend(
            (
                r"(?<!\d)(\d{1,2})\s*cds?\b",
                r"(?<!\d)(\d{1,2})\s*枚組",
                r"(?<!\d)(\d{1,2})\s*枚セット",
                r"(?<!\d)(\d{1,2})\s*disc\b",
            )
        )

    elif media_format in {
        "LP",
        "EP_7_INCH",
        "12_INCH_SINGLE",
    }:
        patterns.extend(
            (
                r"(?<!\d)(\d{1,2})\s*lps?\b",
                r"(?<!\d)(\d{1,2})\s*枚組",
                r"(?<!\d)(\d{1,2})\s*枚セット",
                r"(?<!\d)(\d{1,2})\s*records?\b",
            )
        )

    elif media_format == "CASSETTE":
        patterns.extend(
            (
                r"(?<!\d)(\d{1,3})\s*(?:cassettes?|tapes?)\b",
                r"(?<!\d)(\d{1,3})\s*本組",
                r"(?<!\d)(\d{1,3})\s*本セット",
            )
        )

    elif media_format == "DVD":
        patterns.extend(
            (
                r"(?<!\d)(\d{1,2})\s*dvds?\b",
                r"(?<!\d)(\d{1,2})\s*枚組",
            )
        )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match is None:
            continue

        count = int(match.group(1))

        if 1 <= count <= 500:
            return count

    return None


def classify_media_details(
    title: str | None,
) -> MediaClassification:
    if not title:
        return MediaClassification(
            format=None,
            disc_count=None,
            bulk_lot=False,
        )

    text = re.sub(
        r"\s+",
        " ",
        title,
    ).strip()

    bulk_lot = _matches_any(
        text,
        _BULK_PATTERNS,
    )

    found_formats: list[str] = []

    for media_format, patterns in _MEDIA_PATTERNS:
        if _matches_any(text, patterns):
            found_formats.append(media_format)

    distinct_base_formats = {
        "CD"
        if value in {
            "CD",
            "SHM_CD",
            "SACD",
            "BLU_SPEC_CD",
            "CD_SINGLE_8CM",
        }
        else value
        for value in found_formats
    }

    if len(distinct_base_formats) > 1:
        media_format = "MIXED_MEDIA"
    elif found_formats:
        media_format = found_formats[0]
    else:
        media_format = None

    disc_count = _extract_disc_count(
        text,
        media_format,
    )

    if media_format and _matches_any(
        text,
        _BOX_PATTERNS,
    ):
        if media_format == "CD":
            media_format = "CD_BOX_SET"
        elif media_format == "LP":
            media_format = "LP_BOX_SET"
        elif media_format == "CASSETTE":
            media_format = "CASSETTE_BOX_SET"

    return MediaClassification(
        format=media_format,
        disc_count=disc_count,
        bulk_lot=bulk_lot,
    )


def classify_media(
    title: str | None,
) -> str | None:
    return classify_media_details(title).format
