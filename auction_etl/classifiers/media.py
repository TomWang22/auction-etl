from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaClassification:
    format: str | None
    disc_count: int | None
    bulk_lot: bool


_JOB_LOT_PATTERNS = (
    r"\blot\b",
    r"\bbundle\b",
    r"\bjob\s*lot\b",
    r"まとめ",
    r"大量",
    r"一括",
    r"箱売り",
    r"など",
    r"ほか",
    r"used cds",
    r"ジャンク",
)
_BULK_PATTERNS = (
    *_JOB_LOT_PATTERNS,
    r"\bcollection of\b",
    r"\bbulk\b",
    r"(?<!カ)セット",
    r"約\s*\d+\s*枚",
    r"箱壳",
)
_OFFICIAL_MULTI_DISC = re.compile(
    r"(?:\d+\s*枚組|\(\s*\d+\s*CDs?\s*\)|\b\d+\s*cd\s*box\b|\bbox\s*set\b)",
    re.IGNORECASE,
)

_QUANTITY_UNIT_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*(pcs\b|枚|点|箱|壳|冊|本)",
    re.IGNORECASE,
)
_SHIPPING_BOX_RE = re.compile(r"輸送箱")
_RECORDS_LOT_RE = re.compile(
    r"\b([2-9]|\d{2,})[-\s]?(?:vinyl\s+)?records?\b",
    re.IGNORECASE,
)
_SINGLES_SET_RE = re.compile(
    r"\b([6-9]|\d{2,})\s*[x×]\s*singles?\b"
    r"|\b([6-9]|\d{2,})[-\s](?:disc|ep)s?\s+set\b",
    re.IGNORECASE,
)
_MAGAZINE_LOT_RE = re.compile(
    r"\b(\d{2,})\b.{0,40}\bmagazines?\b",
    re.IGNORECASE,
)
_MAGAZINE_PATTERNS = (
    r"\bmagazines?\b",
    r"雑誌",
    r"週刊",
    r"月刊",
    r"週刊誌",
    r"切り抜き",
    r"\bgoro\b.{0,20}(?:年|冊|号)",
    r"明星",
    r"平凡",
    r"プレイボーイ",
    r"\bplayboy\b",
    r"女性自身",
    r"マイアイドル",
    r"近代映画",
    r"セブンティーン",
    r"ポポロ",
    r"プレイファイブ",
    r"ペントハウス",
    r"\bpenthouse\b",
    r"ヤングレディ",
    r"年\d{1,2}月号",
)
_PHOTOBOOK_PATTERNS = (
    r"写真集",
    r"\bphotobook\b",
    r"\bphoto\s*book\b",
)
_PRINT_PATTERNS = (
    r"生写真",
    r"白黒写真",
    r"ブロマイド",
    r"スナップ写真",
    r"スチール写真",
    r"スチール",
    r"6つ切り",
    r"写真家",
    r"\bposter\b",
    r"ポスター",
    r"11\s*x\s*17",
    r"色紙",
    r"直筆サイン",
)
_PHOTO_PATTERNS = (
    r"\b\d+\s*x\s*\d+\s*photos?\b",
    r"\bphotos?\b",
)
_TOY_PATTERNS = (
    r"ソフトチップ",
    r"カラオケソフト",
    r"グランドピアニスト",
    r"\bsega\s*toys\b",
    r"\bgrand\s*pianist\b",
)
_STAMP_PATTERNS = (
    r"\bstamps?\b",
    r"切手",
    r"小型シート",
    r"未使用糊",
)
_USB_PATTERNS = (
    r"\busb\b",
    r"u\s*disk",
    r"flash\s*drive",
)
_CASSETTE_CATNO = re.compile(
    r"\b(?:28TT|30TT|32TX|34TX|35TX|38TT|28MX|CRQ|TATL)[- ]?\d{2,5}\b"
    r"|\b(?:3[0-2]\d{2})\s+\d{3}\b",
    re.IGNORECASE,
)
_VINYL_EP_CATNO = re.compile(
    r"\b(?:07TR|06SH|07SH|04SH|09SH|SOLB)[- ]?\d{2,5}\b",
    re.IGNORECASE,
)
_VINYL_LP_CATNO = re.compile(
    r"\b(?:MRZ?|DR|TASL|AWK|SOLL)[- ]?\d{2,5}\b",
    re.IGNORECASE,
)
_POLYDOR_CD_CATNO = re.compile(
    r"\b(?:H32P|H50P)[- ]?\d{4,6}\b",
    re.IGNORECASE,
)
_CD_CATNO = re.compile(
    r"\b(?:POCH|PCCA|PCJA|UPCY|UICZ|UICY|SRCL|MHCL|TRUE|TACL|DCT|WPCV|AMCM)[- ]?\d{3,6}\b",
    re.IGNORECASE,
)
_DVD_CATNO = re.compile(
    r"\b(?:UPBH|PKDA)[- ]?\d{3,6}\b",
    re.IGNORECASE,
)
_AUDIO_MEDIA = frozenset(
    {
        "CD",
        "SHM_CD",
        "SACD",
        "BLU_SPEC_CD",
        "CD_SINGLE_8CM",
        "EP_7_INCH",
        "12_INCH_SINGLE",
        "SINGLE_12_INCH",
        "LP",
        "CASSETTE",
        "REEL_TO_REEL",
        "CD_BOX_SET",
        "LP_BOX_SET",
        "CASSETTE_BOX_SET",
        "MIXED_MEDIA",
        "LASERDISC",
        "DVD",
        "VHS",
    }
)

_BOX_PATTERNS = (
    r"\bbox\s*set\b",
    r"\bbox\b",
    r"\bboxed\s*set\b",
    r"ボックス",
    r"cdbox",
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
            r"(?<![A-Za-z])ep(?![A-Za-z])",
            r"7\s*(?:inch|インチ|[\"”''′″])",
            r"\b45\s*rpm\b",
            r"7インチ",
            r"ドーナツ盤",
            r"シングル盤",
            r"シングルレコード",
            r"シングル(?!コレクション)",
            r"\b\d+(?:st|nd|rd|th)\s+singles?\b",
            r"\bsingles?\b(?!\s*collection)",
            r"\b(?:SOLB|07SH|06SH|04SH|09SH|07TR)[- ]?\d{2,5}\b",
            r"(?<![A-Za-z])\d+\s*[x×]\s*7\b",
        ),
    ),
    (
        "SINGLE_12_INCH",
        (
            r"12\s*(?:inch|インチ|''+|\"+|”|″)",
            r"12インチ",
        ),
    ),
    (
        "LASERDISC",
        (
            r"\blaserdisc\b",
            r"\blaser\s*disc\b",
            r"レーザーディスク",
            r"(?<![A-Za-z0-9])ld(?![A-Za-z0-9])",
        ),
    ),
    (
        "CASSETTE",
        (
            r"\bcassettes?\b",
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
        "SHEET_MUSIC",
        (
            r"楽譜",
            r"タブ譜",
            r"\bsheet\s*music\b",
            r"\bsong\s*book\b",
        ),
    ),
    (
        "CD",
        (
            r"(?<![A-Za-z])cds?(?![A-Za-z])",
            r"compact\s*disc",
            r"ＣＤ",
            r"コンパクトディスク",
            r"cdbox",
            r"single\s*collection",
            r"シングルコレクション",
        ),
    ),
    (
        "LP",
        (
            r"(?<![A-Za-z0-9])lp(?![A-Za-z0-9])",
            r"(?<![A-Za-z])lp[- ]?\d{3,5}(?!\d)",
            r"(?<![A-Za-z0-9])\d+\s*lp(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9])\d+\s*[x×]\s*lp(?![A-Za-z0-9])",
            r"triple\s*lp",
            r"\bwax\b",
            r"\bvinyl\b",
            r"\brecord\b",
            r"\bpicture\s*disc\b",
            r"アナログ盤",
            r"アナログ",
            r"レコード",
            r"ＬＰ",
            r"黑胶",
            r"黑膠",
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


def _twelve_inch_shape(text: str) -> str:
    """Sellers say 12\" for both albums and maxi-singles. Keep albums on LP."""
    single = bool(
        re.search(
            r"maxi|45\s*rpm|12インチ|remix|"
            r"12\s*(?:inch|[\"”'′″]+)\s*(?:single|promo)",
            text,
            re.IGNORECASE,
        )
    )
    album = bool(
        re.search(
            r"(?<![A-Za-z0-9])lp(?![A-Za-z0-9])|"
            r"アルバム|\balbum\b|2\s*lp|with lyrics",
            text,
            re.IGNORECASE,
        )
    )
    compilation = bool(
        re.search(
            r"\bvol\.?\b|compilation|various|ベスト|全集|シングルス",
            text,
            re.IGNORECASE,
        )
    )
    if album and (compilation or not single):
        return "LP"
    if single or not album:
        return "SINGLE_12_INCH"
    return "LP"


def _records_quantity_lot(text: str) -> bool:
    """A count of records is a lot. A year or catno before 'Vinyl Record' is not."""
    for match in _RECORDS_LOT_RE.finditer(text):
        count = int(match.group(1))
        if 1940 <= count <= 2035:
            continue
        phrase = match.group(0)
        if re.search(r"vinyl\s+record$", phrase, re.IGNORECASE) and not re.search(
            r"\bsets?\b",
            text,
            re.IGNORECASE,
        ):
            continue
        if 2 <= count <= 500:
            return True
    return False


def _quantity_implies_bulk(text: str) -> bool:
    if _records_quantity_lot(text):
        return True
    if _SINGLES_SET_RE.search(text):
        return True

    if _MAGAZINE_LOT_RE.search(text):
        return True

    for match in _QUANTITY_UNIT_RE.finditer(text):
        count = int(match.group(1))
        if count < 2:
            continue

        unit = match.group(2).casefold()
        rest = text[match.end(): match.end() + 2]
        if unit in {"枚", "本"} and rest.startswith("組"):
            continue

        if unit == "箱" and _SHIPPING_BOX_RE.search(text):
            continue

        return True

    return False


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
        "SINGLE_12_INCH",
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
    ) or _quantity_implies_bulk(text)
    if (
        bulk_lot
        and _OFFICIAL_MULTI_DISC.search(text)
        and not re.search(r"\blot\b", text, re.IGNORECASE)
    ):
        bulk_lot = False

    found_formats: list[str] = []

    for media_format, patterns in _MEDIA_PATTERNS:
        if _matches_any(text, patterns):
            found_formats.append(media_format)

    if _CASSETTE_CATNO.search(text):
        found_formats.append("CASSETTE")
    if _POLYDOR_CD_CATNO.search(text) or _CD_CATNO.search(text):
        found_formats.append("CD")
    if _VINYL_EP_CATNO.search(text) or re.search(
        r"(?<![A-Za-z])\d+\s*[x×]\s*7\b",
        text,
        re.IGNORECASE,
    ):
        found_formats.append("EP_7_INCH")

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
        if distinct_base_formats <= {"SINGLE_12_INCH", "LP"}:
            media_format = _twelve_inch_shape(text)
        elif "SINGLE_12_INCH" in distinct_base_formats and distinct_base_formats <= {
            "SINGLE_12_INCH",
            "EP_7_INCH",
            "LP",
        }:
            media_format = _twelve_inch_shape(text)
        elif distinct_base_formats <= {"EP_7_INCH", "LP"}:
            compilation = bool(
                re.search(
                    r"ベスト|全集|collection|compilation|アルバム",
                    text,
                    re.IGNORECASE,
                )
            )
            album_named = bool(
                re.search(
                    r"(?<![A-Za-z0-9])lp(?![A-Za-z0-9])|"
                    r"アルバム|\balbum\b|2枚組|"
                    r"2\s*[x×]\s*vinyl",
                    text,
                    re.IGNORECASE,
                )
            )
            seven_inch = bool(
                _VINYL_EP_CATNO.search(text)
                or re.search(
                    r"7\s*(?:inch|インチ)|ドーナツ|"
                    r"\b\d+(?:st|nd|rd|th)\s+singles?\b|"
                    r"\d+\s*[x×]\s*7\b",
                    text,
                    re.IGNORECASE,
                )
            )
            media_format = (
                "LP"
                if (compilation or album_named) and not seven_inch
                else "EP_7_INCH"
            )
        elif distinct_base_formats <= {"CD", "EP_7_INCH"}:
            media_format = "CD"
        elif distinct_base_formats <= {"CD", "LP"}:
            media_format = "CD"
        elif distinct_base_formats <= {"CASSETTE", "LP"}:
            media_format = "CASSETTE"
        elif distinct_base_formats <= {"DVD", "LP"}:
            media_format = "DVD"
        else:
            media_format = "MIXED_MEDIA"
    elif found_formats:
        media_format = found_formats[0]
    else:
        media_format = None

    if media_format not in _AUDIO_MEDIA:
        if _matches_any(text, _MAGAZINE_PATTERNS):
            media_format = "MAGAZINE"
        elif _matches_any(text, _PHOTOBOOK_PATTERNS):
            media_format = "PHOTOBOOK"
        elif _matches_any(text, _PRINT_PATTERNS):
            media_format = "PRINT"
        elif _matches_any(text, _STAMP_PATTERNS):
            media_format = "STAMP"
        elif _matches_any(text, _PHOTO_PATTERNS):
            media_format = "PHOTO"
        elif _matches_any(text, _USB_PATTERNS):
            media_format = "USB"
        elif _matches_any(text, _TOY_PATTERNS):
            media_format = "TOY"
        elif _CASSETTE_CATNO.search(text):
            media_format = "CASSETTE"
        elif _POLYDOR_CD_CATNO.search(text) or _CD_CATNO.search(text):
            media_format = "CD"
        elif _DVD_CATNO.search(text):
            media_format = "DVD"
        elif _VINYL_EP_CATNO.search(text):
            media_format = "EP_7_INCH"
        elif _VINYL_LP_CATNO.search(text):
            media_format = "LP"
        elif re.search(r"\d+\s*本セット", text):
            media_format = "CASSETTE"

    if media_format == "12_INCH_SINGLE":
        media_format = "SINGLE_12_INCH"

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


def is_job_lot(title: str | None) -> bool:
    """True for mixed leftover boxes, not an official multi-disc release."""
    if not title:
        return False
    text = re.sub(r"\s+", " ", title).strip()
    leftover = _matches_any(text, _JOB_LOT_PATTERNS)
    official = bool(_OFFICIAL_MULTI_DISC.search(text))
    leftover_box = bool(re.search(r"まとめ|大量|一括|箱売り|ジャンク", text))
    if leftover:
        if leftover_box:
            return True
        if official and not re.search(r"\blot\b", text, re.IGNORECASE):
            return False
        return True
    details = classify_media_details(text)
    return bool(details.bulk_lot and not official)
