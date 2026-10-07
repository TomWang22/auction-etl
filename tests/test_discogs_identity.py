"""Catalog tokens, dead-on classification, and Discogs release mapping."""

from __future__ import annotations

import json
from pathlib import Path

from auction_etl.services.discogs_identity import (
    Classification,
    artist_from_english_title,
    artist_overlaps,
    canonical_artist_key,
    canonical_title_key,
    catalog_token,
    is_junk_catalog,
    listing_identity_catalog,
    catalog_printed_on_listing,
    catalog_identity_key,
    catalog_has_range,
    catno_locks_listing,
    covering_hits_for_listing,
    classify_search_hits,
    shortlist_agrees_with_listing,
    discogs_search_format,
    fold_catalog,
    listing_search_artist,
    listing_volume_number,
    cover_fields_from_release,
    map_release_payload,
    parse_search_hits,
    prefers_japan,
    unique_hit_can_auto_fill,
    album_name_in_listing,
    known_album_phrase,
    listing_names_specific_album,
    hit_bundles_other_album,
    visible_shortlist_hits,
)


ROOT = Path(__file__).resolve().parents[1]
RELEASE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "discogs" / "release_10320765.json"
)


SOLL_HIT = {
    "id": 10320765,
    "type": "release",
    "title": "山口百恵* - 15才",
    "catno": "SOLL-114",
    "year": "1974",
    "country": "Japan",
    "format": ["Vinyl", "LP", "Album", "Stereo"],
    "label": ["CBS/Sony", "Golden New Year '75"],
    "thumb": "https://example.invalid/thumb.jpg",
    "uri": "/release/10320765",
}

SECOND_VINYL_HIT = {
    **SOLL_HIT,
    "id": 99999999,
    "title": "Other Artist - Same Catno",
    "country": "Japan",
}


def test_fold_catalog_equates_hyphen_space_and_plain() -> None:
    assert fold_catalog("SOLL114") == "SOLL114"
    assert fold_catalog("SOLL-114") == "SOLL114"
    assert fold_catalog("soll 114") == "SOLL114"
    assert fold_catalog("TACL-2395~6") == fold_catalog("TACL-2395")
    assert fold_catalog("TACL-2395～6") == "TACL2395"
    assert fold_catalog("18TR-2059~2060") == fold_catalog("18TR-2059")
    assert catalog_token(
        title="2LP TERESA TENG Best 20 18TR205960 TAURUS JAPAN OBI",
    ) == "18TR-2059"
    assert catno_locks_listing("18TR-2059~2060", "18TR-2059")
    assert fold_catalog("MRZ 9229/30") == fold_catalog("MRZ-9229")
    assert catalog_identity_key("MHCL-109~10") == "MHCL10910"
    assert catalog_identity_key("MHCL-109/10") == "MHCL10910"
    assert catalog_identity_key("MHCL-109~10") != catalog_identity_key("MHCL-109")
    assert catalog_has_range("MHCL-109~10")
    assert not catalog_has_range("MHCL-109")
    assert catno_locks_listing("MHCL-109~10", "MHCL-109~10")
    assert catno_locks_listing("TACL-2395~6", "TACL-2395")
    assert not catno_locks_listing("MHCL-109", "MHCL-109~10")
    assert not catno_locks_listing("UPCY-6443", "UPCY-6443~5")


def test_ebay_title_yields_soll114_token() -> None:
    token = catalog_token(
        catalog_number=None,
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
    )
    assert token is not None
    assert fold_catalog(token) == "SOLL114"


def test_catalog_field_wins_over_title() -> None:
    token = catalog_token(
        catalog_number="SOLL-114",
        title="Random text without a useful token",
    )
    assert fold_catalog(token) == "SOLL114"


def test_missing_token_is_none() -> None:
    assert catalog_token(title="Pretty vinyl lot no catalog") is None


def test_ebay_sold_month_day_is_not_a_catalog() -> None:
    from auction_etl.services.discogs_identity import (
        is_junk_catalog,
        listing_identity_catalog,
        stored_catalog_fits_listing,
    )

    assert is_junk_catalog("SEP-23")
    assert is_junk_catalog("SEP-21")
    assert is_junk_catalog("OCT-1")
    assert is_junk_catalog("L-11")
    assert not is_junk_catalog("TASL-7920")
    assert not is_junk_catalog("SOLL-114")
    assert not is_junk_catalog("SOLI-70")
    assert not is_junk_catalog("SOLI70")
    assert catalog_token(
        title="MOMOE YAMAGUCHI MOMOE LIVE - FROM THE MOMOE FESTIVAL - CBS SOLI70 2LP"
    ) == "SOLI-70"
    assert is_junk_catalog("TOKYO-99")
    assert is_junk_catalog("CHAN-84")
    assert is_junk_catalog(
        "WOMAN-12",
        title="ANITA MUI original 1986 EVIL WOMAN 12' VINYL RECORD LP",
    )
    assert (
        catalog_token(
            catalog_number="SEP-23",
            title="鄧麗君* - 勢不兩立 (LP) (1980) [Used Vinyl]",
        )
        is None
    )
    assert (
        catalog_token(
            title="Teresa Teng ベスト20 2xLP Gatefold Sold Sep 23, 2026"
        )
        is None
    )
    assert is_junk_catalog(float("nan"))
    assert fold_catalog(float("nan")) == ""
    assert catalog_token(catalog_number=float("nan"), title=None) is None
    assert listing_identity_catalog(
        stored=float("nan"),
        title="buyee teresa teng lp",
        infer=False,
    ) is None
    assert not stored_catalog_fits_listing(
        float("nan"),
        title="buyee teresa teng lp",
    )


def test_cd_lot_sku_is_not_a_catalog() -> None:
    from auction_etl.services.discogs_identity import is_junk_catalog

    assert is_junk_catalog(
        "SEP-21",
        title="The Best of Teresa Teng 1 3 4 CD Lot 1992 Polygram",
    )
    assert (
        catalog_token(
            catalog_number="SEP-21",
            title="The Best of Teresa Teng 1 3 4 CD Lot 1992 Polygram",
        )
        is None
    )


def test_short_false_catalogs_are_junk() -> None:
    from auction_etl.services.discogs_identity import is_junk_catalog

    assert is_junk_catalog("CAL-04", title="1985 Anita Mui Vinyl LP Hong Kong CAL 04 1029")
    assert is_junk_catalog("T-113", title="【鄧麗君 (T113版/金装系列)】CD")
    assert is_junk_catalog("Q-88", title="Q88◆おんな演歌 3枚組CD")
    assert catalog_token(title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP") == "SOLL-114"
    assert not is_junk_catalog("DR1944")
    assert not is_junk_catalog("DR-1944")
    assert catalog_token(
        title="国内盤 テレサ・テン 夜の乗客 YORU NO JOKYAKU POLYDOR DR1944 1x7",
    ) == "DR-1944"
    from auction_etl.services.discogs_identity import catalog_search_variants

    assert "DR-1944" in catalog_search_variants("DR-1944")
    assert "DR1944" in catalog_search_variants("DR-1944")
    assert "DR 1944" in catalog_search_variants("DR-1944")


def test_lot_sku_is_not_a_catalog() -> None:
    assert (
        catalog_token(
            title="【1円スタート】ジャンク 演歌 邦楽 CD まとめ テレサ・テン 182本 Kce053"
        )
        is None
    )


def test_real_catalog_survives_lot_title() -> None:
    assert catalog_token(
        title="まとめ CD テレサ・テン TACL-510 英語編"
    ) == "TACL-510"


def test_buyee_price_yen_is_not_a_catalog() -> None:
    from auction_etl.services.discogs_identity import is_junk_catalog

    assert is_junk_catalog("PRICE-880")
    assert is_junk_catalog("PRICE-541")
    assert is_junk_catalog("CANTOPOP1988")
    assert is_junk_catalog("LPS203FRZ")
    assert is_junk_catalog("8CMCD400ZAF")
    assert is_junk_catalog("5921RZ")
    assert is_junk_catalog("0134RZ")
    assert catalog_token(
        catalog_number="PRICE-281",
        title="【国内盤/7inch】テレサ・テン / 雪化粧 Price 281 YEN",
    ) is None
    assert catalog_token(
        title="Number of Bids 0 Seller abc Price 281 YEN (Price including Tax)",
    ) is None


def test_title_hint_yields_spaced_polydor_catalog() -> None:
    token = catalog_token(
        catalog_number=None,
        title="Teresa Teng 鄧麗君 A Small Wish LP Polydor 2427 333 Hong Kong 1980",
    )
    assert token == "2427 333"
    assert fold_catalog(token) == "2427333"


def test_mashed_hyphen_catalog_is_rewritten_to_spaced_poly() -> None:
    assert catalog_token(catalog_number="242733-3") == "2427 333"
    assert catalog_token(title="POLYDOR 242733-3 LP") == "2427 333"


def test_lp_year_does_not_steal_title_catalog_hint() -> None:
    token = catalog_token(
        catalog_number="LP 1980",
        title="RARE SINGAPORE TERESA TENG POLYDOR 2427 333 LP 1980",
    )
    assert token == "2427 333"


def test_letter_catalog_does_not_peel_last_digit() -> None:
    assert catalog_token(catalog_number="28TR205-7") == "28TR-2057"
    assert catalog_token(title="TAURUS 07TR1115 EP") == "07TR-1115"


def test_title_catalogs_from_live_listings() -> None:
    assert catalog_token(title="テレサ・テン/全曲集/38TT-1178") == "38TT-1178"
    assert catalog_token(title="EP テレサ テン 見本盤 7DX1048") == "7DX-1048"
    assert catalog_token(
        title="香港盤 TERESA TENG POLYDOR 8175561 1LP"
    ) == "817 556-1"
    assert catalog_token(
        title="RUSH MOVING PICTURES EPIC 253P261 Japan OBI VINYL LP"
    ) == "253P-261"
    assert catalog_token(
        title="Diana Ross My Old Piano / Give Up 12''"
    ) is None
    assert catalog_token(
        title="廃盤でゴールドディスクCD★輸入盤★鄧麗君 / 懐念金曲精選 (T3889B)★テレサテン"
    ) == "T3889B"
    assert catalog_token(
        title="シール帯【テレサ テン 全曲集】H32P-20030 51223G MANUFACTURED BY SANYO 鄧麗君"
    ) == "H32P-20030"
    assert catalog_token(
        title='Teresa Teng - "Indonesian Works Complete Collection" All 28 Songs Indonesian'
    ) is None
    assert catalog_token(
        title="ANITA MUI 梅艷芳 original 1986 EVIL WOMAN 12' VINYL RECORD LP HONG KONG SIGNED"
    ) is None
    assert catalog_token(
        catalog_number="TT-0808",
        title="tt0808/鄧麗君/テレサ・テン/中国語全曲集/CD/H32P-20134/音出し動作未確認/現状品",
    ) == "H32P-20134"
    assert catalog_token(
        title="4988009328126;【3CD】山口百恵 / 百恵辞典 SRCL-3281~3"
    ) == "SRCL-3281~3"
    assert catalog_token(
        title="Teresa Teng/Jiu Zui De Tan Ge (100％ Pure LP) PROT7418/9 New LP"
    ) == "PROT-7418~9"
    assert catalog_token(
        catalog_number="DCT-27926",
        title="★ V.A. / 大人のムード歌謡 ~男と女のラブソング集~ (5CD) DCT-2792/6 石原裕次郎 テレサ・テン",
    ) == "DCT-2792~6"
    assert catalog_token(title="ポリドールH50P- 2020 5/6 コンパクトディスク") == "H50P-2020"


def test_title_hints_read_any_artist_catalog_and_region() -> None:
    from auction_etl.services.discogs_identity import listing_preferred_country

    assert (
        catalog_token(
            catalog_number=None,
            title="台湾盤 KUOPIN盤 テレサ・テン 「鄧麗君 心にのこる夜の唄」台湾盤レコード KP-8142",
        )
        == "KP-8142"
    )
    assert (
        catalog_token(
            catalog_number=None,
            title="鄧麗君初次嚐到寂寞/5223 374",
        )
        == "5223 374"
    )
    assert (
        listing_preferred_country(
            listing_title="貴重 未開封品 台湾盤 KUOPIN盤 テレサ・テン 「鄧麗君 心にのこる夜の唄」 KP-8142",
            listing_artist="Teresa Teng",
        )
        == "taiwan"
    )
    junk = parse_search_hits(
        [
            {
                "id": 90016,
                "type": "release",
                "title": "鄧麗君* = テレサ・テン* - 鄧麗君精選全集",
                "catno": "TATL-9001~6",
                "format": ["CD", "Box Set"],
                "label": ["Taurus"],
            }
        ]
    )
    assert covering_hits_for_listing(
        junk,
        title="台湾盤 KUOPIN盤 「鄧麗君 心にのこる夜の唄」台湾盤レコード KP-8142",
    ) == ()
    sibling = parse_search_hits(
        [
            {
                "id": 2427374,
                "type": "release",
                "title": "鄧麗君* - 初次嚐到寂寞",
                "catno": "2427 374",
                "format": ["Vinyl", "LP"],
                "label": ["Polydor"],
            }
        ]
    )
    assert covering_hits_for_listing(
        sibling,
        title="鄧麗君初次嚐到寂寞/5223 374",
    ) == sibling
    classified = classify_search_hits(
        catalog_number=None,
        title="台湾盤 KUOPIN盤 「鄧麗君 心にのこる夜の唄」台湾盤レコード KP-8142",
        artist="Teresa Teng",
        media_type="LP",
        hits=junk,
    )
    assert classified.status == "unmatched"
    assert classified.hits == ()
    from auction_etl.services.discogs_identity import (
        is_junk_catalog,
        listing_barcode,
        search_artist,
    )

    assert listing_barcode(
        "4988009328126;【3CD】山口百恵 / 百恵辞典 SRCL-3281~3"
    ) == "4988009328126"

    assert is_junk_catalog("VINYL-33")
    assert is_junk_catalog("VOCAL 60S")
    assert is_junk_catalog("KWAN 1980S")
    assert is_junk_catalog("THEIR-20")
    assert is_junk_catalog("TENG-10")
    assert is_junk_catalog("ALBUM-19531995")
    assert is_junk_catalog(
        "P-0122",
        title="P0122 テレサ・テン スチール写真(6つ切り) 朝日新聞",
    )
    assert (
        search_artist(
            "4988009328126;【3CD】山口百恵",
            "4988009328126;【3CD】山口百恵 / 百恵辞典 SRCL-3281~3",
        )
        == "Momoe Yamaguchi"
    )


def test_artist_overlap_latin_and_japanese() -> None:
    names = ["Momoe Yamaguchi", "山口百恵"]
    assert artist_overlaps(
        listing_artist=None,
        listing_title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        discogs_names=names,
    )
    assert artist_overlaps(
        listing_artist="山口百恵",
        listing_title="15才 CBS/SONY SOLL-114",
        discogs_names=names,
    )
    assert not artist_overlaps(
        listing_artist="Teresa Teng",
        listing_title="Island of Teresa",
        discogs_names=names,
    )
    assert artist_overlaps(
        listing_artist=None,
        listing_title="テレサ・テン 鄧麗君 スーパーセレクション TACL-2395",
        discogs_names=["Teresa Teng"],
    )


def test_prefers_japan_for_jp_titles() -> None:
    assert prefers_japan(
        listing_title="山口百恵 15才 LP",
        listing_artist=None,
    )
    assert prefers_japan(
        listing_title="Momoe Yamaguchi Japan pressing",
        listing_artist=None,
    )
    assert not prefers_japan(
        listing_title="Beatles UK stereo",
        listing_artist="The Beatles",
    )
    assert not prefers_japan(
        listing_title="Anita Mui 梅艷芳 In Brasil Hong Kong vinyl",
        listing_artist=None,
    )
    assert prefers_japan(
        listing_title="テレサ・テン 夜の乗客 LP 日本盤",
        listing_artist=None,
    )


def test_catalog_token_reads_ep_cd_and_cinepoly_numbers() -> None:
    assert catalog_token(title="山口百恵 31st Single YS-265 シングル") == "YS-265"
    assert catalog_token(title="テレサ・テン CD CDU-104 カラオケ") == "CDU-104"
    assert catalog_token(
        title="ANITA MUI 梅艷芳 似水流年 Cinepoly LP-3973 Hong Kong",
    ) == "LP-3973"
    assert catalog_token(title="テレサ テン EP KRS-3031") == "KRS-3031"
    assert catalog_token(
        title="1985 Anita Mui Vinyl LP Hong Kong CAL 04 1029",
    ) == "CAL-04-1029"
    assert catalog_token(
        title="YS-265 テレサテン / つぐない ※シングル盤",
    ) is None
    assert catalog_token(
        title="Gripsweat - [MusicWall] Anita Mui (梅艷芳) 妖女 LP LP3973",
        catalog_number="LP-3973",
    ) is None


def test_buyee_stock_code_yields_to_the_printed_pressing_catalog() -> None:
    title = "LP0847☆台湾/Yeu Jow「鄧麗君 テレサ・テン / 鳳陽花鼓 / AWK-003-A」"
    assert is_junk_catalog("LP0847")
    assert is_junk_catalog("LP-0847", title=title)
    assert not is_junk_catalog("LP-3973")
    assert not is_junk_catalog("LFLP-486")
    assert listing_search_artist(None, title) == "Teresa Teng"
    assert listing_search_artist("台湾", title) == "Teresa Teng"
    assert catalog_token(title=title) == "AWK-003"
    assert catalog_token(catalog_number="LP-0847", title=title) == "AWK-003"
    assert (
        listing_identity_catalog(stored="LP-0847", title=title, infer=False)
        == "AWK-003"
    )
    assert catalog_token(
        title="ANITA MUI 梅艷芳 似水流年 Cinepoly LP-3973 Hong Kong",
        catalog_number="LP-3973",
    ) == "LP-3973"


def test_inferred_release_catalog_maps_known_albums() -> None:
    from auction_etl.services.discogs_identity import inferred_release_catalog

    assert inferred_release_catalog(
        title="Anita Mui 梅艷芳 Evil Girl 妖女 Hong Kong 1986 Original 1st LP",
        artist="Anita Mui",
        media_type="LP",
    ) == "CAL-04-1039"
    assert inferred_release_catalog(
        title="Momoe Yamaguchi 31th Single Sayonara no Mukougawa Vinyl Record 1980",
        artist="Momoe Yamaguchi",
        media_type="EP_7_INCH",
    ) == "07SH-834"
    assert inferred_release_catalog(
        title="YS-265 テレサテン / つぐない ※シングル盤",
        media_type="EP_7_INCH",
    ) == "07TR-1056"
    assert inferred_release_catalog(
        title="Anita Mui 似水流年 picture vinyl Germany",
        media_type="LP",
    ) is None
    assert inferred_release_catalog(
        title="Gripsweat - 梅艷芳 百變 似火探戈 黑膠唱片 Anita Mui LP",
        artist="Anita Mui",
        media_type="LP",
    ) == "CAL-04-1047"
    assert inferred_release_catalog(
        title="Anita Mui - In Brasil (1991) Rare Original Korean LP",
        artist="Anita Mui",
        media_type="LP",
    ) == "SZPR-096"
    assert inferred_release_catalog(
        title="Gripsweat - 黑膠唱片1987年 梅艷芳 ANITA MUI 烈燄紅唇 胭脂扣",
        media_type="LP",
    ) == "CAL-04-1056"
    shown = visible_shortlist_hits(
        [
            {
                "id": 6599877,
                "title": "梅艷芳* - 梅艷芳",
                "catno": "CAL-04-1056",
                "format": ["Vinyl", "LP", "Album"],
            },
            {
                "id": 1,
                "title": "梅艷芳* - 赤色梅艷芳",
                "catno": "CAL-04-1111",
                "format": ["Vinyl", "LP"],
            },
        ],
        title="Anita Mui [梅艷芳] – Flaming Lips [烈燄紅唇] (1987) Hong Kong Press Vinyl LP",
    )
    assert [hit["id"] for hit in shown] == [6599877]
    assert inferred_release_catalog(
        title="LP / テレサテン / 夜来香/何日君再来 / 帯付 [0820RZ]",
        artist="Teresa Teng",
        media_type="LP",
    ) == "MR 3166"
    assert inferred_release_catalog(
        title="LP / テレサ テン / 夜の乗客/女のいきがい / 帯付 [0134RZ]",
        artist="Teresa Teng",
        media_type="LP",
    ) == "MR 3036"
    assert inferred_release_catalog(
        title="MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
        artist="Momoe Yamaguchi",
        media_type="LP",
    ) is None


def test_stored_catalog_fits_listing_media() -> None:
    from auction_etl.services.discogs_identity import stored_catalog_fits_listing

    ye_lai_xiang = "LP / テレサテン / 夜来香/何日君再来 / 帯付 [0820RZ]"
    yokosuka_lp = (
        "MOMOE YAMAGUCHI Yokosuka Story Japanese Idol "
        "VINYL LP Record With OBI CBS/SONY"
    )
    assert stored_catalog_fits_listing(
        "mr3166",
        title=ye_lai_xiang,
        media_type="LP",
    )
    assert stored_catalog_fits_listing(
        "MR 3166",
        title=ye_lai_xiang,
        media_type="LP",
    )
    assert not stored_catalog_fits_listing(
        "06SH 15",
        title=yokosuka_lp,
        media_type="LP",
    )
    assert stored_catalog_fits_listing(
        "06SH 15",
        title="山口百恵 横須賀ストーリー 06SH 15",
        media_type="EP_7_INCH",
    )
    assert not stored_catalog_fits_listing(
        "PODH-1114",
        title=ye_lai_xiang,
        media_type="LP",
    )


def test_listing_identity_catalog_uses_fitting_stored_or_inferred() -> None:
    from auction_etl.services.discogs_identity import listing_identity_catalog

    ye_lai_xiang = "LP / テレサテン / 夜来香/何日君再来 / 帯付 [0820RZ]"
    yokosuka_lp = (
        "MOMOE YAMAGUCHI Yokosuka Story Japanese Idol "
        "VINYL LP Record With OBI CBS/SONY"
    )
    assert fold_catalog(
        listing_identity_catalog(
            stored="mr3166",
            title=ye_lai_xiang,
            artist="Teresa Teng",
            media_type="LP",
        )
    ) == fold_catalog("MR 3166")
    assert fold_catalog(
        listing_identity_catalog(
            stored=None,
            title=ye_lai_xiang,
            artist="Teresa Teng",
            media_type="LP",
        )
    ) == fold_catalog("MR 3166")
    assert listing_identity_catalog(
        stored=None,
        title=ye_lai_xiang,
        artist="Teresa Teng",
        media_type="LP",
        infer=False,
    ) is None
    assert listing_identity_catalog(
        stored="06SH 15",
        title=yokosuka_lp,
        artist="Momoe Yamaguchi",
        media_type="LP",
    ) is None
    assert catalog_token(title=ye_lai_xiang) is None
    assert listing_search_artist(None, ye_lai_xiang) == "Teresa Teng"
    assert album_name_in_listing(
        ye_lai_xiang,
        "鄧麗君* = テレサ・テン* - 華麗なる熱唱",
    )


def test_anita_hong_kong_title_keeps_hk_pressing() -> None:
    from auction_etl.services.discogs_identity import listing_preferred_country

    assert (
        listing_preferred_country(
            listing_title="ANITA MUI 梅艷芳 似水流年 Hong Kong Lp",
            listing_artist="Anita Mui",
        )
        == "hong kong"
    )
    assert (
        listing_preferred_country(
            listing_title="ANITA MUI 梅艷芳 妖女 LP-3973",
            listing_artist="Anita Mui",
        )
        == "hong kong"
    )
    japan_hit = {
        "id": 11,
        "type": "release",
        "title": "Anita Mui - 似水流年",
        "catno": "28AH-1234",
        "year": "1985",
        "country": "Japan",
        "format": ["Vinyl", "LP"],
        "label": ["CBS/Sony"],
        "thumb": "https://example.invalid/jp.jpg",
        "uri": "/release/11",
    }
    hk_hit = {
        "id": 22,
        "type": "release",
        "title": "Anita Mui - 似水流年",
        "catno": "C-1029",
        "year": "1985",
        "country": "Hong Kong",
        "format": ["Vinyl", "LP"],
        "label": ["Capital Artists"],
        "thumb": "https://example.invalid/hk.jpg",
        "uri": "/release/22",
    }
    result = classify_search_hits(
        catalog_number=None,
        title="ANITA MUI 梅艷芳 似水流年 Hong Kong Lp",
        artist="Anita Mui",
        media_type="LP",
        hits=parse_search_hits([japan_hit, hk_hit]),
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 22


def test_unique_catno_vinyl_hit_is_dead_on() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
        discogs_artist_names=["Momoe Yamaguchi", "山口百恵"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10320765
    assert result.hits[0].catno == "SOLL-114"


def test_range_catalog_unique_cd_is_dead_on() -> None:
    hit = {
        "id": 4242,
        "type": "release",
        "title": "テレサ・テン* - Super Selection",
        "catno": "TACL-2395~6",
        "year": "1995",
        "country": "Japan",
        "format": ["CD", "Compilation"],
        "label": ["Taurus"],
        "thumb": "https://example.invalid/tacl.jpg",
        "uri": "/release/4242",
    }
    result = classify_search_hits(
        catalog_number="TACL-2395",
        title="テレサ・テン スーパーセレクション CD 2枚組 TACL-2395～6 追悼盤",
        artist="Teresa Teng",
        media_type="CD",
        hits=parse_search_hits([hit]),
        discogs_artist_names=["Teresa Teng", "テレサ・テン"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 4242


def test_two_cd_listing_does_not_lock_first_disc_only() -> None:
    hit = {
        "id": 109,
        "type": "release",
        "title": "山口百恵* - ゴールデン・ベスト PLAYBACK MOMOE part2",
        "catno": "MHCL-109",
        "year": "2004",
        "country": "Japan",
        "format": ["CD", "Compilation"],
        "label": ["Sony"],
        "uri": "/release/109",
    }
    result = classify_search_hits(
        catalog_number="MHCL-109~10",
        title="【2CD】山口百恵 / ゴールデン・ベスト PLAYBACK MOMOE part2 MHCL-109~10",
        artist="Momoe Yamaguchi",
        media_type="CD",
        hits=parse_search_hits([hit]),
        discogs_artist_names=["山口百恵"],
    )
    assert result.status == "needs_review"
    assert result.reason == "catno_mismatch"
    assert unique_hit_can_auto_fill(
        result,
        listing_artist="Momoe Yamaguchi",
        listing_title="【2CD】山口百恵 / ゴールデン・ベスト PLAYBACK MOMOE part2 MHCL-109~10",
        release_artist_names=("山口百恵",),
    ) is False


def test_catalog_collision_without_artist_stays_review() -> None:
    hit = {
        "id": 99,
        "type": "release",
        "title": "Random Future - やすきよ漫才てなもんや MIX",
        "catno": "POCH-1782",
        "year": "1994",
        "country": "Japan",
        "format": ["CD"],
        "label": ["Polydor"],
        "thumb": "https://example.invalid/wrong.jpg",
        "uri": "/release/99",
    }
    result = classify_search_hits(
        catalog_number="POCH-1782",
        title="テレサ・テン 鄧麗君 カバー・ベスト・コレクション POCH-1782",
        artist="Teresa Teng",
        media_type="CD",
        hits=parse_search_hits([hit]),
    )
    assert result.status == "needs_review"
    assert result.reason == "artist_mismatch"
    assert unique_hit_can_auto_fill(
        result,
        listing_artist="Teresa Teng",
        listing_title="テレサ・テン 鄧麗君 カバー・ベスト・コレクション POCH-1782",
        release_artist_names=("Random Future",),
    ) is False


def test_two_catno_hits_picks_artist_overlap() -> None:
    result = classify_search_hits(
        catalog_number="SOLL-114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT, SECOND_VINYL_HIT]),
        discogs_artist_names=["Momoe Yamaguchi", "山口百恵"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10320765


def test_two_same_catno_hits_prefer_retail_over_promo() -> None:
    promo = {
        **SOLL_HIT,
        "id": 1,
        "format": ["Vinyl", "LP", "Album", "Promo", "Stereo"],
    }
    retail = {
        **SOLL_HIT,
        "id": 2,
        "format": ["Vinyl", "LP", "Album", "Stereo"],
    }
    result = classify_search_hits(
        catalog_number="SOLL-114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([promo, retail]),
        discogs_artist_names=["Momoe Yamaguchi", "山口百恵"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 2
    assert len(result.hits) == 1


def test_same_album_hits_collapse_without_shared_catno() -> None:
    first = {
        "id": 1,
        "type": "release",
        "title": "山口美央子* - Nirvana",
        "catno": "C28A0172",
        "year": "1981",
        "country": "Japan",
        "format": ["Vinyl", "LP", "Album"],
        "label": ["F-Label"],
        "thumb": "",
        "uri": "/release/1",
    }
    promo = {
        **first,
        "id": 2,
        "catno": "C28A0173",
        "format": ["Vinyl", "LP", "Album", "Promo"],
    }
    result = classify_search_hits(
        catalog_number="C28A0172",
        title="MIOKO YAMAGUCHI NIRVANA F-LABEL C28A0172 1LP",
        artist="Mioko Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([first, promo]),
        discogs_artist_names=["Mioko Yamaguchi", "山口美央子"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert len(result.hits) == 1


def test_catalog_hit_wrong_format_needs_review() -> None:
    cd_hit = {
        **SOLL_HIT,
        "format": ["CD", "Album"],
    }
    result = classify_search_hits(
        catalog_number="SOLL-114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([cd_hit]),
    )
    assert result.status == "needs_review"
    assert result.reason == "media_mismatch"
    assert result.chosen is None
    assert unique_hit_can_auto_fill(
        result,
        listing_artist="Momoe Yamaguchi",
        listing_title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        release_artist_names=("Momoe Yamaguchi", "山口百恵"),
        listing_catalog="SOLL-114",
    )


def test_missing_token_is_unmatched() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="Pretty jacket photo lot",
        artist=None,
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
        discogs_artist_names=["Momoe Yamaguchi"],
    )
    assert result.status == "unmatched"
    assert result.chosen is None


def test_title_search_same_album_cluster_fills() -> None:
    hits = []
    for index, catno in enumerate(
        ("28TR-2134", "28TR-2135", "UPJY-9140", "TA-9001", "TA-9002"),
        start=1,
    ):
        hits.append(
            {
                "id": index,
                "type": "release",
                "title": "Teresa Teng - 酒醉的探戈",
                "catno": catno,
                "year": "1986",
                "country": "Japan",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Taurus"],
                "thumb": "",
                "uri": f"/release/{index}",
            }
        )
    result = classify_search_hits(
        catalog_number=None,
        title="酒醉的探戈 テレサ・テン LP",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits(hits),
    )
    assert result.status == "needs_review"
    assert result.reason == "title_search"
    assert result.chosen is None
    assert {hit.catno for hit in result.hits} == {
        "28TR-2134",
        "28TR-2135",
        "UPJY-9140",
        "TA-9001",
        "TA-9002",
    }
    assert "酒醉的探戈" in result.hits[0].title or "酒酔的探戈" in result.hits[0].title


def test_zenkyokushu_cd_shortlist_stays_review() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "TACL-2395~6",
                "year": "1993",
                "format": ["CD", "Compilation"],
                "label": ["Taurus"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "29TX-1042",
                "year": "1986",
                "format": ["CD", "Compilation"],
                "label": ["Taurus"],
            },
        ]
    )
    result = classify_search_hits(
        catalog_number=None,
        title="1円スタート テレサ・テン CD 全曲集[2CD]",
        artist="Teresa Teng",
        media_type="CD",
        hits=hits,
        require_catalog_token=False,
    )
    assert result.status == "needs_review"
    assert result.chosen is None
    assert {hit.catno for hit in result.hits} == {"TACL-2395~6", "29TX-1042"}
    assert "CD" in {discogs_format_label(hit.formats) for hit in result.hits}


def test_enka_message_promo_lp_matches_album() -> None:
    hits = parse_search_hits(
        [
            {
                "id": 3031,
                "type": "release",
                "title": "テレサ・テン* - 演歌のメッセージ",
                "catno": "MR 3031",
                "year": "1977",
                "format": ["Vinyl", "LP", "Album", "Promo"],
                "label": ["Polydor"],
            }
        ]
    )
    result = classify_search_hits(
        catalog_number=None,
        title="LP/ テレサ テン / 演歌のメッセージ / 見本盤/帯付 [5875RZ]",
        artist="Teresa Teng",
        media_type="LP",
        hits=hits,
        require_catalog_token=False,
    )
    assert result.status in {"filled_auto", "needs_review"}
    assert result.hits
    assert result.hits[0].catno == "MR 3031"


def test_title_search_mixed_albums_stay_unmatched() -> None:
    hits = []
    for index, album in enumerate(
        ("空港", "夜来香", "つぐない", "償還", "別れの予感"),
        start=1,
    ):
        hits.append(
            {
                "id": index,
                "type": "release",
                "title": f"Teresa Teng - {album}",
                "catno": f"XX-{index}",
                "year": "1980",
                "country": "Japan",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Polydor"],
                "thumb": "",
                "uri": f"/release/{index}",
            }
        )
    result = classify_search_hits(
        catalog_number=None,
        title="テレサ・テン ベスト LP",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits(hits),
    )
    assert result.status == "unmatched"
    assert result.reason == "empty_shortlist"
    assert result.chosen is None
    assert result.hits == ()


def test_title_search_picks_listing_album_from_mixed_hits() -> None:
    hits = []
    for index, album in enumerate(
        ("空港", "時の流れに身をまかせ", "夜来香", "つぐない"),
        start=1,
    ):
        hits.append(
            {
                "id": index,
                "type": "release",
                "title": f"テレサ・テン* - {album}",
                "catno": f"28TR-{2100 + index}",
                "year": "1987",
                "country": "Japan",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Taurus"],
                "thumb": "",
                "uri": f"/release/{index}",
            }
        )
    result = classify_search_hits(
        catalog_number=None,
        title="テレサ・テン 時の流れに身をまかせ LP 日本盤",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits(hits),
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert "時の流れに身をまかせ" in result.chosen.title


def test_title_search_cassette_hit_on_lp_stays_review() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="テレサ・テン 夜来香 LP",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits(
            [
                {
                    "id": 88,
                    "type": "release",
                    "title": "テレサ・テン* - 夜来香",
                    "catno": "28CX-123",
                    "year": "1983",
                    "country": "Japan",
                    "format": ["Cassette", "Album"],
                    "label": ["Taurus"],
                    "thumb": "",
                    "uri": "/release/88",
                }
            ]
        ),
    )
    assert result.status == "needs_review"
    assert result.reason == "media_mismatch"
    assert result.chosen is None
    assert unique_hit_can_auto_fill(
        result,
        listing_artist="Teresa Teng",
        listing_title="テレサ・テン 夜来香 LP",
        release_artist_names=("Teresa Teng", "テレサ・テン"),
    ) is False


def test_title_search_artist_mismatch_does_not_dump_hits() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="Kenny Bee Lp Original Hong Kong",
        artist="Kenny Bee",
        media_type="LP",
        hits=parse_search_hits(
            [
                {
                    "id": index,
                    "type": "release",
                    "title": "Bee Gees - Greatest",
                    "catno": f"RSO-{index}",
                    "year": "1979",
                    "country": "US",
                    "format": ["Vinyl", "LP"],
                    "label": ["RSO"],
                    "thumb": "",
                    "uri": f"/release/{index}",
                }
                for index in range(1, 6)
            ]
        ),
    )
    assert result.status == "unmatched"
    assert result.reason == "artist_mismatch"
    assert result.chosen is None


def test_title_fills_when_printed_matrix_is_not_on_discogs() -> None:
    big_hit = {
        "id": 6181274,
        "type": "release",
        "title": "テレサ・テン* - ビッグヒット4",
        "catno": "KRS 3002",
        "year": "1976",
        "country": "Japan",
        "format": ["Vinyl", '7"', "EP", "33 ⅓ RPM"],
        "label": ["Polydor"],
        "uri": "/release/6181274",
    }
    best_hit = {
        "id": 25353913,
        "type": "release",
        "title": "Teresa Teng - Teresa Teng Best Hit 4",
        "catno": "KRS 3021",
        "year": "1977",
        "country": "Japan",
        "format": ["Vinyl", '7"', "EP"],
        "label": ["Polydor"],
        "uri": "/release/25353913",
    }
    big = classify_search_hits(
        catalog_number="KRS3012",
        title="TERESATENG BIG HIT4 POLYDOR KRS3012 1x7",
        artist="Teresa Teng",
        media_type="EP_7_INCH",
        hits=parse_search_hits([big_hit, best_hit]),
        discogs_artist_names=["テレサ・テン", "Teresa Teng"],
    )
    assert big.status == "filled_auto"
    assert big.chosen is not None
    assert big.chosen.discogs_id == 6181274
    assert big.chosen.catno == "KRS 3002"
    best = classify_search_hits(
        catalog_number="KRS 3031",
        title="TERESA TENG Best Hit 4 Japan 4trk 33rpm EP KRS 3031",
        artist="Teresa Teng",
        media_type="EP_7_INCH",
        hits=parse_search_hits([big_hit, best_hit]),
        discogs_artist_names=["Teresa Teng"],
    )
    assert best.status == "filled_auto"
    assert best.chosen is not None
    assert best.chosen.discogs_id == 25353913
    assert best.chosen.catno == "KRS 3021"


def test_title_search_unique_hit_fills() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="Momoe Yamaguchi 15 sai jacket lot",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
    )
    assert result.status == "filled_auto"
    assert result.reason == "title_search"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10320765
    assert unique_hit_can_auto_fill(
        result,
        listing_artist="Momoe Yamaguchi",
        listing_title="Momoe Yamaguchi 15 sai jacket lot",
        release_artist_names=("Momoe Yamaguchi", "山口百恵"),
    )


def test_title_search_promo_picks_shared_catalog() -> None:
    promo = {
        "id": 10426595,
        "type": "release",
        "title": "Teresa Teng - 酒醉的探戈",
        "catno": "28TR-2134",
        "year": "1986",
        "country": "Japan",
        "format": ["Vinyl", "LP", "Album", "Promo", "Stereo"],
        "label": ["Taurus"],
        "thumb": "https://example.invalid/promo.jpg",
        "uri": "/release/10426595",
    }
    retail = {
        **promo,
        "id": 14350774,
        "title": "テレサ・テン* - 酒醉的探戈",
        "format": ["Vinyl", "LP", "Album", "Stereo"],
    }
    reissue = {
        **promo,
        "id": 16070980,
        "catno": "UPJY-9140",
        "title": "Teresa Teng - 酒醉的探戈",
        "format": ["Vinyl", "LP", "Album", "Limited Edition", "Reissue", "Stereo"],
    }
    result = classify_search_hits(
        catalog_number=None,
        title="酒醉的探戈/ テレサ テン(見本盤)",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits([promo, reissue, retail]),
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10426595
    assert result.chosen.catno == "28TR-2134"


def test_title_fallback_ignores_catalog_token() -> None:
    result = classify_search_hits(
        catalog_number="SOLL-114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
        require_catalog_token=False,
    )
    assert result.status == "filled_auto"
    assert result.reason == "title_search"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10320765


def test_unique_japanese_search_title_promotes_with_release_artists() -> None:
    result = classify_search_hits(
        catalog_number="SOLL114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist=None,
        media_type="LP",
        hits=parse_search_hits([SOLL_HIT]),
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 10320765
    assert unique_hit_can_auto_fill(
        result,
        listing_artist=None,
        listing_title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        release_artist_names=("Momoe Yamaguchi", "山口百恵"),
    )
    assert unique_hit_can_auto_fill(
        result,
        listing_artist="Momoe Yamaguchi",
        listing_title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        release_artist_names=("Various",),
    ) is False
    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    draft = map_release_payload(payload)

    assert draft.discogs_release_id == 10320765
    assert draft.discogs_master_id == 1918614
    assert draft.label_name == "CBS/Sony"
    assert draft.discogs_label_id == 33078
    assert draft.catalog_number == "SOLL-114"
    assert draft.country == "Japan"
    assert draft.region == "Japan"
    assert draft.release_year == 1974
    assert draft.media_type == "LP"
    assert draft.disc_count == 1
    assert draft.generation == "UNKNOWN"
    assert draft.requires_label_choice is False
    assert "SOLL-114A2" in draft.matrix_number
    assert "SOLL-114B3" in draft.matrix_number
    assert draft.component_expectations == ()
    assert "lyric sheet" in (draft.notes_hint or "")


def test_disc_count_comes_from_release_qty_or_the_format_name() -> None:
    from auction_etl.services.discogs_identity import _map_formats

    one, _detail, count, _generation = _map_formats(
        [{"name": "Vinyl", "qty": "1", "descriptions": ["LP", "Album"]}]
    )
    assert one == "LP"
    assert count == 1
    _media, _detail, doubled, _generation = _map_formats(
        [{"name": "2×Vinyl", "descriptions": ["LP", "Album"]}]
    )
    assert doubled == 2
    _media, _detail, implied, _generation = _map_formats(
        [{"name": "Vinyl", "descriptions": ["LP", "Album"]}]
    )
    assert implied == 1


def test_two_label_entities_require_explicit_choice() -> None:
    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    payload["labels"] = [
        {
            "id": 33078,
            "name": "CBS/Sony",
            "catno": "SOLL-114",
            "entity_type_name": "Label",
        },
        {
            "id": 1,
            "name": "Sony",
            "catno": "SOLL-114",
            "entity_type_name": "Label",
        },
    ]
    draft = map_release_payload(payload)
    assert draft.requires_label_choice is True
    assert len(draft.labels) == 2


def test_operator_click_locks_primary_label_on_two_label_release() -> None:
    from auction_etl.services.discogs_fill import draft_for_operator_choice

    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    payload["labels"] = [
        {
            "id": 33078,
            "name": "CBS/Sony",
            "catno": "SOLL-114",
            "entity_type_name": "Label",
        },
        {
            "id": 1,
            "name": "Sony",
            "catno": "SOLL-114",
            "entity_type_name": "Label",
        },
    ]
    locked = draft_for_operator_choice(map_release_payload(payload))
    assert locked.requires_label_choice is False
    assert locked.label_name == "CBS/Sony"
    assert locked.discogs_label_id == 33078
    assert locked.catalog_number == "SOLL-114"


def test_cd_album_description_stays_cd() -> None:
    payload = {
        "id": 6624534,
        "title": "淡淡幽情",
        "country": "Taiwan",
        "year": 1991,
        "artists": [{"name": "鄧麗君", "anv": ""}],
        "labels": [
            {
                "id": 1,
                "name": "Kolyn",
                "catno": "SC-6101",
                "entity_type_name": "Label",
            }
        ],
        "formats": [{"name": "CD", "qty": "1", "descriptions": ["Album"]}],
        "identifiers": [],
        "images": [],
    }
    draft = map_release_payload(payload)
    assert draft.media_type == "CD"
    covered = cover_fields_from_release(
        {
            **payload,
            "images": [{"uri": "https://i.discogs.com/example.jpg", "type": "primary"}],
        }
    )
    assert covered["thumb"] == "https://i.discogs.com/example.jpg"
    assert covered["label"] == ["Kolyn"]
    cassette = map_release_payload(
        {
            **payload,
            "id": 2,
            "formats": [
                {"name": "Cassette", "qty": "1", "descriptions": ["Album"]}
            ],
        }
    )
    assert cassette.media_type == "CASSETTE"


def test_promo_description_sets_generation_not_first_press() -> None:
    payload = json.loads(
        RELEASE_FIXTURE.read_text(encoding="utf-8")
    )
    payload["formats"] = [
        {
            "name": "Vinyl",
            "qty": "1",
            "descriptions": ["LP", "Promo"],
        }
    ]
    draft = map_release_payload(payload)
    assert draft.generation == "PROMO"
    assert draft.is_first_press is False


def test_discogs_search_format_maps_records_and_skips_print() -> None:
    assert discogs_search_format("LP") == "Vinyl"
    assert discogs_search_format("CD") == "CD"
    assert discogs_search_format("Cassette") == "Cassette"
    assert discogs_search_format("CASSETTE") == "Cassette"
    assert discogs_search_format("CASSETTE_BOX_SET") == "Cassette"
    assert discogs_search_format("MIXED_MEDIA") == "CD"
    assert discogs_search_format("DVD") == "DVD"
    assert discogs_search_format("EP_7_INCH") == '7"'
    assert discogs_search_format("SINGLE_12_INCH") == '12"'
    assert discogs_search_format("12_INCH_SINGLE") == '12"'
    assert discogs_search_format("magazine") is None
    assert discogs_search_format("stamp") is None
    assert discogs_search_format("toy") is None
    assert discogs_search_format("TOY") is None


def test_seven_inch_title_overrides_lp_classifier() -> None:
    from auction_etl.services.discogs_identity import (
        effective_listing_media,
        listing_title_wants_seven_inch,
    )

    assert listing_title_wants_seven_inch('Sea Gull 7" EP 戀愛有苦也有樂')
    assert listing_title_wants_seven_inch("つぐない シングル盤")
    assert listing_title_wants_seven_inch(
        "山口百恵 直筆サイン入り レコード 「禁じられた遊び」"
    )
    assert not listing_title_wants_seven_inch("似水流年 Hong Kong Lp")
    assert not listing_title_wants_seven_inch(
        "ベストソングス~シングル・コレクション~ TACL-2360"
    )
    assert effective_listing_media(
        "EP_7_INCH",
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, Compilation, Numbered, Taiwan",
    ) == "LP"
    assert not listing_title_wants_seven_inch(
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, Compilation, Numbered, Taiwan"
    )
    from auction_etl.services.discogs_identity import listing_wants_original_pressing

    assert not listing_wants_original_pressing(
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, Compilation, Numbered, Taiwan"
    )
    assert effective_listing_media("LP", 'ANITA MUI 7" EP KRS-3031') == "EP_7_INCH"
    assert effective_listing_media(
        "LP",
        "山口百恵 直筆サイン入り レコード 「禁じられた遊び」",
    ) == "EP_7_INCH"
    assert effective_listing_media("LP", "【CD】テレサ・テン トップ・テン") == "CD"
    assert effective_listing_media("LP", "テレサ・テン 全曲集 カセットテープ") == "CASSETTE"


def test_reissue_range_catalogs_search_both_halves() -> None:
    from auction_etl.services.discogs_identity import (
        catalog_search_variants,
        catalog_token,
        catno_covers_listing_token,
    )

    title = "【2CD】山口百恵 / ゴールデン・ベスト MHCL-109~10"
    token = catalog_token(catalog_number=None, title=title)
    assert token == "MHCL-109~10"
    variants = catalog_search_variants(token)
    assert "MHCL-109~10" in variants
    assert "MHCL-109" in variants
    assert catno_covers_listing_token("MHCL-109~10", "MHCL-109")
    assert catno_covers_listing_token("UPCY-6443/5", "UPCY-6443")
    assert not catno_covers_listing_token("TACL-2510", "TACL-510")
    reissue_title = (
        "美盤 LP テレサ・テン 鄧麗君 夜の乗客／女の生きがい UPJY-9092 帯付 日本盤 1975年"
    )
    assert catalog_token(catalog_number=None, title=reissue_title) == "UPJY-9092"


def test_listing_shape_keeps_lp_off_seven_inch_singles() -> None:
    from auction_etl.services.discogs_identity import prefer_listing_shape

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "テレサ・テン* - つぐない",
                "catno": "07TR-1056",
                "format": ["Vinyl", '7"', "Single"],
                "label": ["Taurus"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "テレサ・テン* - つぐない",
                "catno": "28TR-2032",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Taurus"],
            },
        ]
    )
    shaped = prefer_listing_shape(hits, "LP")
    assert [hit.catno for hit in shaped] == ["28TR-2032"]
    sevens = prefer_listing_shape(hits, "EP_7_INCH")
    assert [hit.catno for hit in sevens] == ["07TR-1056"]
    lp_titled = prefer_listing_shape(
        hits,
        "EP_7_INCH",
        title="鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, Compilation",
    )
    assert [hit.catno for hit in lp_titled] == ["28TR-2032"]
    seven_only = prefer_listing_shape(hits[:1], "LP")
    assert seven_only == ()


def test_discogs_format_label_names_lp_ep_and_cd() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    assert discogs_format_label(["Vinyl", "LP", "Album"]) == "LP"
    assert discogs_format_label(["Vinyl", "LP", "Album", "Promo"]) == "LP · Promo"
    assert discogs_format_label(["Vinyl", '7"', "45 RPM", "Single"]) == '7"'
    assert discogs_format_label(["Vinyl", '7"', "EP"]) == 'EP / 7"'
    assert discogs_format_label(["CD", "Album"]) == "CD"


def test_visible_shortlist_keeps_promo_and_hides_duplicate_retail() -> None:
    from auction_etl.services.discogs_identity import (
        discogs_format_label,
        visible_shortlist_hits,
    )

    visible = visible_shortlist_hits(
        [
            {
                "id": 1,
                "title": "テレサ・テン* - 你(あなた)／まごころ",
                "catno": "28MX-1007",
                "format": ["Vinyl", "LP", "Album"],
            },
            {
                "id": 1,
                "title": "テレサ・テン* - 你(あなた)／まごころ",
                "catno": "28MX-1007",
                "format": ["Vinyl", "LP", "Album"],
            },
            {
                "id": 2,
                "title": "テレサ・テン* - 你(あなた)／まごころ",
                "catno": "28MX-1007",
                "format": ["Vinyl", "LP", "Album", "Promo"],
            },
        ]
    )
    assert [hit["id"] for hit in visible] == [1, 2]
    assert discogs_format_label(visible[1]["format"]) == "LP · Promo"


def test_lp_listing_keeps_seven_inch_as_labeled_mismatch() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    hits = parse_search_hits(
        [
            {
                "id": 5108033,
                "type": "release",
                "title": "山口百恵* - 横須賀ストーリー = Yokosuka Story",
                "catno": "06SH 15",
                "year": "1976",
                "format": ["Vinyl", '7"', "45 RPM", "Single"],
                "label": ["CBS/Sony"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "山口百恵* - 横須賀ストーリー = Yokosuka Story",
                "catno": "25AH 296",
                "year": "1976",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["CBS/Sony"],
            },
            {
                "id": 3,
                "type": "release",
                "title": "山口百恵* - 横須賀ストーリー = Yokosuka Story",
                "catno": "32DH 15",
                "year": "1986",
                "format": ["CD", "Album"],
                "label": ["CBS/Sony"],
            },
        ]
    )
    result = classify_search_hits(
        catalog_number=None,
        title="MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=hits,
    )
    labels = [discogs_format_label(hit.formats) for hit in result.hits]
    assert album_name_in_listing(
        "MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
        "山口百恵* - 横須賀ストーリー",
    )
    assert result.chosen is None or discogs_format_label(result.chosen.formats) == "LP"
    seven_only = classify_search_hits(
        catalog_number=None,
        title="MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=hits[:1],
    )
    assert seven_only.status == "needs_review"
    assert seven_only.reason == "media_mismatch"
    assert seven_only.chosen is None
    assert discogs_format_label(seven_only.hits[0].formats) == '7"'
    stored_seven = classify_search_hits(
        catalog_number="06SH 15",
        title="MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=hits,
    )
    stored_labels = [discogs_format_label(hit.formats) for hit in stored_seven.hits]
    assert stored_labels[0] == "LP"
    assert '7"' in stored_labels
    assert "CD" in stored_labels
    assert stored_seven.chosen is None
    assert not catalog_printed_on_listing(
        "06SH 15",
        "MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
    )
    assert catalog_printed_on_listing("06SH 15", "山口百恵 横須賀ストーリー 06SH 15")


def test_ye_lai_xiang_lp_keeps_mr3166_ahead_of_cd_and_cassette() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    hits = parse_search_hits(
        [
            {
                "id": 1114,
                "type": "release",
                "title": "テレサ・テン* - 夜来香",
                "catno": "PODH-1114",
                "year": "1992",
                "country": "Japan",
                "format": ["CD", "Album"],
                "label": ["Polydor"],
            },
            {
                "id": 2114,
                "type": "release",
                "title": "テレサ・テン* - 夜来香",
                "catno": "POSH-1114",
                "year": "1992",
                "country": "Japan",
                "format": ["Cassette", "Album"],
                "label": ["Polydor"],
            },
            {
                "id": 3166,
                "type": "release",
                "title": "鄧麗君* = テレサ・テン* - 華麗なる熱唱",
                "catno": "MR 3166",
                "year": "1978",
                "country": "Japan",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Polydor"],
            },
        ]
    )
    title = "LP / テレサテン / 夜来香/何日君再来 / 帯付 [0820RZ]"
    result = classify_search_hits(
        catalog_number="mr3166",
        title=title,
        artist="Teresa Teng",
        media_type="LP",
        hits=hits,
    )
    assert result.status == "needs_review"
    assert result.chosen is None
    labels = [discogs_format_label(hit.formats) for hit in result.hits]
    assert labels[0] == "LP"
    assert result.hits[0].catno == "MR 3166"
    assert "CD" in labels
    assert "Cassette" in labels
    inferred = classify_search_hits(
        catalog_number=None,
        title=title,
        artist="Teresa Teng",
        media_type="LP",
        hits=hits,
    )
    assert inferred.hits[0].catno == "MR 3166"


def test_lp_listing_keeps_cd_cassette_and_later_vinyl_as_options() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    hits = parse_search_hits(
        [
            {
                "id": 29306296,
                "type": "release",
                "title": "テレサ・テン* - '91 悲しみと踊らせて",
                "catno": "TATL-2330",
                "year": "1991",
                "format": ["Cassette", "Album", "Stereo"],
                "label": ["Taurus"],
            },
            {
                "id": 15545203,
                "type": "release",
                "title": "テレサ・テン* - '91 悲しみと踊らせて",
                "catno": "TACL-2330",
                "year": "1991",
                "format": ["CD", "Album", "Stereo"],
                "label": ["Taurus"],
            },
            {
                "id": 10300873,
                "type": "release",
                "title": "Teresa Teng - ’91悲しみと踊らせて~ニュー・オリジナル・ソングス~",
                "catno": "PROT-7009",
                "year": "2016",
                "format": ["Vinyl", "LP", "Album", "Reissue", "Stereo"],
                "label": ["Universal"],
            },
        ]
    )
    result = classify_search_hits(
        catalog_number=None,
        title="テレサ・テン ’９１ 悲しみと踊らせて LP 未使用品",
        artist="Teresa Teng",
        media_type="LP",
        hits=hits,
    )
    assert result.status == "needs_review"
    assert result.chosen is None
    by_catno = {hit.catno: discogs_format_label(hit.formats) for hit in result.hits}
    assert by_catno["TACL-2330"] == "CD"
    assert by_catno["TATL-2330"] == "Cassette"
    assert by_catno["PROT-7009"] == "LP"
    assert [hit.catno for hit in result.hits][:2] == ["TACL-2330", "TATL-2330"]


def test_anniversary_lp_keeps_vinyl_cd_and_cassette_options() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    hits = parse_search_hits(
        [
            {
                "id": 20514331,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "KSR 1082",
                "year": "1983",
                "country": "Taiwan",
                "format": ["Vinyl", "LP", "Compilation", "Stereo"],
                "label": ["Kolin"],
            },
            {
                "id": 13526831,
                "type": "release",
                "title": "鄧麗君* - 15週年",
                "catno": "7700930",
                "year": "2018",
                "country": "Taiwan",
                "format": ["Vinyl", "LP", "45 RPM", "Compilation", "Numbered", "Stereo"],
                "label": ["Universal"],
            },
            {
                "id": 11965483,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 131-1",
                "year": "1983",
                "country": "Hong Kong",
                "format": ["Vinyl", "LP", "Album", "Compilation", "Stereo"],
                "label": ["Polydor"],
            },
            {
                "id": 27153936,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 143-2",
                "year": "1983",
                "country": "Hong Kong",
                "format": ["CD", "Compilation"],
                "label": ["Polydor"],
            },
            {
                "id": 22901276,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 143-2",
                "year": "1990",
                "country": "Hong Kong",
                "format": ["CD", "Compilation", "Reissue"],
                "label": ["Polydor"],
            },
            {
                "id": 8171324,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 132-4",
                "year": "1983",
                "country": "Hong Kong",
                "format": ["Cassette", "Compilation"],
                "label": ["Polydor"],
            },
        ]
    )
    title = (
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, "
        "Compilation, Numbered, Taiwan"
    )
    result = classify_search_hits(
        catalog_number=None,
        title=title,
        artist="Teresa Teng",
        media_type="EP_7_INCH",
        hits=hits,
    )
    by_catno = {hit.catno: discogs_format_label(hit.formats) for hit in result.hits}
    assert by_catno["7700930"] == "LP"
    assert by_catno["817 143-2"] == "CD"
    assert by_catno["817 132-4"] == "Cassette"
    assert result.status == "needs_review"
    assert result.chosen is None
    assert result.hits[0].catno == "7700930"


def test_listing_shape_keeps_twelve_inch_off_lp_albums() -> None:
    from auction_etl.services.discogs_identity import prefer_listing_shape

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "Milli Vanilli - Blame It On The Rain",
                "catno": "112 603",
                "format": ["Vinyl", '12"', "Maxi-Single"],
                "label": ["Hansa"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "Milli Vanilli - All Or Nothing",
                "catno": "259 418",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Hansa"],
            },
        ]
    )
    twelves = prefer_listing_shape(hits, "SINGLE_12_INCH")
    assert [hit.catno for hit in twelves] == ["112 603"]
    albums = prefer_listing_shape(hits, "LP")
    assert [hit.catno for hit in albums] == ["259 418"]


def test_discogs_seven_and_twelve_map_to_listing_media() -> None:
    seven = map_release_payload(
        {
            "id": 11,
            "title": "つぐない",
            "formats": [
                {
                    "name": "Vinyl",
                    "qty": "1",
                    "descriptions": ['7"', "Single"],
                }
            ],
            "labels": [{"name": "Taurus", "catno": "07TR-1056"}],
            "artists": [{"name": "テレサ・テン"}],
        }
    )
    assert seven.media_type == "EP_7_INCH"
    twelve = map_release_payload(
        {
            "id": 12,
            "title": "Blame It On The Rain",
            "formats": [
                {
                    "name": "Vinyl",
                    "qty": "1",
                    "descriptions": ['12"', "Maxi-Single", "45 RPM"],
                }
            ],
            "labels": [{"name": "Hansa", "catno": "112 603"}],
            "artists": [{"name": "Milli Vanilli"}],
        }
    )
    assert twelve.media_type == "SINGLE_12_INCH"


def test_listing_media_compatible_keeps_singles_off_albums() -> None:
    from auction_etl.services.discogs_identity import listing_media_compatible

    assert listing_media_compatible("EP_7_INCH", "EP_7_INCH")
    assert listing_media_compatible("EP_7_INCH", "Vinyl")
    assert listing_media_compatible("EP_7_INCH", "LP") is False
    assert listing_media_compatible("SINGLE_12_INCH", "LP") is False
    assert listing_media_compatible("LP", "LP")
    assert listing_media_compatible("CD", "LP") is False


def test_listing_shape_keeps_lp_off_cd_pressings() -> None:
    from auction_etl.services.discogs_identity import prefer_listing_shape

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "テレサ・テン* - ベスト・ヒット・アルバム",
                "catno": "H32P-20134",
                "year": "1986",
                "format": ["CD", "Compilation"],
                "label": ["Polydor"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "テレサ・テン* - ベスト・ヒット・アルバム",
                "catno": "MR 3041",
                "year": "1977",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["Polydor"],
            },
        ]
    )
    shaped = prefer_listing_shape(hits, "LP")
    assert [hit.catno for hit in shaped] == ["MR 3041"]


def test_two_titles_in_one_listing_are_not_one_album() -> None:
    from auction_etl.services.discogs_identity import listing_names_other_work

    both = "LP/ テレサ テン / 愛をあなたに ふるさとはどこですか / 帯付 [5918RZ]"
    assert listing_names_other_work(both, "ふるさとはどこですか")
    assert listing_names_other_work(both, "テレサ・テン - ふるさとはどこですか")
    assert not listing_names_other_work(
        "LP テレサ・テン ふるさとはどこですか 帯付",
        "ふるさとはどこですか",
    )
    assert not listing_names_other_work(
        "LP テレサ・テン ふるさとはどこですか ポスター付",
        "ふるさとはどこですか",
    )
    assert not listing_names_other_work(
        "【国内盤/7inch】テレサ・テン / 別れの予感 / 酒醉的探戈",
        "別れの予感",
    )
    assert not listing_names_other_work(
        "Teresa Teng 假如我是真的 島國之情歌第七集",
        "假如我是真的",
    )
    assert not listing_names_other_work(
        "LP / テレサ テン / 夜の乗客/女のいきがい / 帯付",
        "夜の乗客 / 女の生きがい",
    )


def test_shortlist_hides_a_different_album_and_a_generic_best_selection() -> None:
    both = "LP/ テレサ テン / 愛をあなたに ふるさとはどこですか / 帯付 [5918RZ]"
    hidden = visible_shortlist_hits(
        [
            {
                "id": 9732193,
                "title": "テレサ・テン - ふるさとはどこですか",
                "catno": "MR 3048",
                "format": ["Vinyl", "LP"],
            }
        ],
        title=both,
    )
    assert hidden == []

    star = "CD / テレサ・テン / ベストセレクション 星願 [1198CD]"
    kept = visible_shortlist_hits(
        [
            {
                "id": 9670438,
                "title": "テレサ・テン - 時の流れに身をまかせ / ベスト・セレクション",
                "catno": "32TX-1037",
                "format": ["CD"],
            },
            {
                "id": 2410,
                "title": "テレサ・テン - ベストセレクション ～星願～",
                "catno": "TACL-2410",
                "format": ["CD"],
            },
        ],
        title=star,
    )
    assert [hit["catno"] for hit in kept] == ["TACL-2410"]


def test_promo_copy_stays_on_the_original_catalog() -> None:
    from auction_etl.services.discogs_identity import original_pressing_for_promo_copy

    title = (
        "21120424;【美盤/帯付/Taurus/プロモ】テレサ・テン Teresa Teng 鄧麗君 / 別れの予感"
    )
    candidates = [
        {
            "id": 381,
            "catalog_number": "UPJY-9141",
            "release_year": 2020,
            "generation": "REISSUE",
            "media_type": "LP",
            "display_title": "別れの予感",
        },
        {
            "id": 69,
            "catalog_number": "28TR-2145",
            "release_year": 1987,
            "generation": "UNKNOWN",
            "media_type": "LP",
            "display_title": "別れの予感",
        },
        {
            "id": 94,
            "catalog_number": "34TX-1066",
            "release_year": 1987,
            "generation": "UNKNOWN",
            "media_type": "CD",
            "display_title": "別れの予感",
        },
        {
            "id": 64,
            "catalog_number": "07TR-1150",
            "release_year": 1987,
            "generation": "UNKNOWN",
            "media_type": "Vinyl",
            "display_title": "別れの予感 (襟曲)",
        },
    ]
    chosen = original_pressing_for_promo_copy(
        title,
        listing_media="LP",
        current_catalog="UPJY-9141",
        candidates=candidates,
    )
    assert chosen is not None
    assert chosen["catalog_number"] == "28TR-2145"
    assert (
        original_pressing_for_promo_copy(
            "プロモ UPJY-9141 別れの予感",
            listing_media="LP",
            current_catalog="UPJY-9141",
            candidates=candidates,
        )
        is None
    )
    lover = "11266409;【ほぼ美盤/帯付/プロモ】テレサ・テン Teresa Teng 鄧麗君 / 愛人"
    lover_rows = [
        {
            "id": 380,
            "catalog_number": "UPJY-9137",
            "release_year": 2020,
            "generation": "REISSUE",
            "media_type": "LP",
            "display_title": "愛人",
        },
        {
            "id": 425,
            "catalog_number": "28TR-2062",
            "release_year": 1985,
            "generation": "UNKNOWN",
            "media_type": "LP",
            "display_title": "愛人",
        },
        {
            "id": 190,
            "catalog_number": "28TR-2062",
            "release_year": 1985,
            "generation": "PROMO",
            "media_type": "LP",
            "display_title": "愛人",
        },
        {
            "id": 216,
            "catalog_number": "07TR-1086",
            "release_year": 1985,
            "generation": "UNKNOWN",
            "media_type": "Vinyl",
            "display_title": "愛人",
        },
    ]
    promo = original_pressing_for_promo_copy(
        lover,
        listing_media="LP",
        current_catalog="UPJY-9137",
        candidates=lover_rows,
    )
    assert promo is not None
    assert promo["id"] == 190


def test_original_era_title_skips_universal_reissue_catalog() -> None:
    from auction_etl.services.discogs_identity import (
        catalog_token,
        extract_release_year,
        hit_fits_listing_year,
        listing_wants_original_pressing,
        refine_hits_for_listing,
    )

    original = "美盤 LP テレサ・テン 鄧麗君 夜の乗客／女の生きがい 帯付 日本盤 1975年"
    named_reissue = "美盤 LP テレサ・テン 鄧麗君 夜の乗客／女の生きがい UPJY-9092 帯付 日本盤 1975年"
    reissue = "LP テレサ・テン 鄧麗君 ベスト・アルバム UPJY-9078 2019年復刻盤 帯付"
    assert extract_release_year(original) == 1975
    assert extract_release_year(reissue) == 2019
    assert catalog_token(catalog_number="UPJY-9092", title=original) is None
    assert catalog_token(title=named_reissue) == "UPJY-9092"
    assert catalog_token(title=reissue) == "UPJY-9078"
    assert catalog_token(
        catalog_number="UPCY-6443",
        title="CD テレサ・テン 鄧麗君 全曲集 UPCY-6443",
    ) == "UPCY-6443"
    analog = "LP / テレサ テン / 夜の乗客/女のいきがい / 帯付 [0134RZ]"
    stereo = "Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound"
    assert listing_wants_original_pressing(original)
    assert hit_fits_listing_year(
        "Teresa Teng 鄧麗君 Vol. 3 2017 Japan LP Sealed W/Insert Limited Edition 180g",
        1982,
    ) is False
    assert hit_fits_listing_year(
        "Teresa Teng 鄧麗君 Vol. 3 2017 Japan LP Sealed W/Insert Limited Edition 180g",
        2017,
    ) is True
    assert listing_wants_original_pressing(analog)
    assert not listing_wants_original_pressing(named_reissue)
    assert not listing_wants_original_pressing(reissue)
    assert not listing_wants_original_pressing(stereo)
    nhk_live = (
        "Teresa Teng - One & Only: 1985 NHK Live (Complete) [New Vinyl LP] 180 Gram"
    )
    assert not listing_wants_original_pressing(nhk_live)
    assert not listing_wants_original_pressing("鄧麗君島國情歌六1989 年版CD所有$45以下")
    assert hit_fits_listing_year(nhk_live, 2020) is True
    assert hit_fits_listing_year(original, 2020) is False
    assert hit_fits_listing_year(analog, 2020) is False
    assert hit_fits_listing_year(named_reissue, 2020) is True
    assert hit_fits_listing_year(reissue, 2019) is True
    originals = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
                "catno": "MR 3036",
                "year": "1976",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Polydor"],
            },
            {
                "id": 15983591,
                "type": "release",
                "title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
                "catno": "UPJY-9092",
                "year": "2020",
                "format": ["Vinyl", "LP", "Album", "Reissue"],
                "label": ["Universal"],
            },
        ]
    )
    refined = refine_hits_for_listing(originals, title=analog, media_type="LP")
    assert [hit.catno for hit in refined] == ["MR 3036"]
    only_reissue = refine_hits_for_listing(
        originals[1:],
        title=analog,
        media_type="LP",
    )
    assert only_reissue == ()
    named = refine_hits_for_listing(
        originals,
        title=named_reissue,
        media_type="LP",
    )
    assert [hit.catno for hit in named] == ["UPJY-9092"]
    analog_only = classify_search_hits(
        catalog_number=None,
        title=analog,
        artist="Teresa Teng",
        media_type="LP",
        hits=originals[1:],
        require_catalog_token=False,
    )
    assert analog_only.status == "needs_review"
    assert analog_only.chosen is None
    assert analog_only.hits[0].catno == "UPJY-9092"
    analog_first = classify_search_hits(
        catalog_number=None,
        title=analog,
        artist="Teresa Teng",
        media_type="LP",
        hits=originals,
        require_catalog_token=False,
    )
    assert analog_first.hits
    assert analog_first.hits[0].catno == "MR 3036"
    assert "UPJY-9092" not in {hit.catno for hit in analog_first.hits}


def test_first_concert_analog_listing_keeps_1977_not_upjy() -> None:
    """Buyee sleeve SKUs are not catnos; vintage First Concert is MR 3965."""
    from auction_etl.services.discogs_identity import (
        catalog_token,
        classify_search_hits,
        is_junk_catalog,
        listing_wants_original_pressing,
    )

    title = "LP/テレサテン/ファースト コンサート/ライブ盤/帯付 [5921RZ]"
    assert is_junk_catalog("5921RZ")
    assert catalog_token(title=title) is None
    assert listing_wants_original_pressing(title)
    hits = parse_search_hits(
        [
            {
                "id": 9695,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "UPJY-9695",
                "year": "2020",
                "format": ["Vinyl", "LP", "Album", "Reissue"],
                "label": ["Universal"],
            },
            {
                "id": 3965,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "MR 3965",
                "year": "1977",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Polydor"],
            },
        ]
    )
    classified = classify_search_hits(
        catalog_number=None,
        title=title,
        artist="Teresa Teng",
        media_type="LP",
        hits=hits,
        require_catalog_token=False,
    )
    assert classified.hits
    assert classified.hits[0].catno == "MR 3965"
    assert "UPJY-9695" not in {hit.catno for hit in classified.hits}


def test_first_concert_part_ii_stays_in_program_family() -> None:
    from auction_etl.services.discogs_identity import (
        _same_album_or_catalog_hits,
        concert_program_related,
    )

    title = "LP/ テレサ テン / ファースト コンサート / ライブ盤/帯付 [5921RZ]"
    assert concert_program_related(title, "Teresa Teng - First Concert Part Ⅱ")
    assert concert_program_related(title, "テレサ・テン* - ファースト・コンサート")
    assert not concert_program_related(title, "Teresa Teng - Last Concert Part Ⅱ")
    hits = parse_search_hits(
        [
            {
                "id": 14523719,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "MR 3065",
                "year": "1977",
                "format": ["Vinyl", "LP"],
            },
            {
                "id": 20582395,
                "type": "release",
                "title": "Teresa Teng - First Concert Part Ⅱ",
                "catno": "SSAR-058",
                "year": "2021",
                "format": ["Vinyl", "LP", "Album", "Reissue"],
            },
        ]
    )
    same = _same_album_or_catalog_hits(
        hits,
        artist="Teresa Teng",
        title=title,
        token=None,
    )
    assert {hit.catno for hit in same} == {"MR 3065", "SSAR-058"}


def test_island_vol7_cassette_keeps_mrmt_when_discogs_catno_differs() -> None:
    """Printed 3199 287 is the LP number on the cassette; Discogs stores MRMT 1008."""
    from auction_etl.services.discogs_identity import (
        album_name_in_listing,
        classify_search_hits,
        listing_identity_catalog,
    )

    title = "鄧麗君/ 島國之情歌第七集/3199 287"
    assert listing_identity_catalog(
        stored="3199 287",
        title=title,
        artist="Teresa Teng",
        media_type="CASSETTE",
    ) == "3199 287"
    assert album_name_in_listing(title, "鄧麗君* - 假如我是真的")
    hits = parse_search_hits(
        [
            {
                "id": 13093053,
                "type": "release",
                "title": "鄧麗君* - 假如我是真的",
                "catno": "MRMT 1008",
                "year": "1981",
                "format": ["Cassette", "Album", "Stereo"],
                "label": ["Polydor"],
            }
        ]
    )
    classified = classify_search_hits(
        catalog_number="3199 287",
        title=title,
        artist="Teresa Teng",
        media_type="CASSETTE",
        hits=hits,
        require_catalog_token=True,
    )
    assert classified.status == "needs_review"
    assert classified.hits
    assert classified.hits[0].catno == "MRMT 1008"


def test_catalog_digits_and_concert_dates_are_not_pressing_years() -> None:
    from auction_etl.services.discogs_identity import extract_release_year

    assert extract_release_year(
        "国内盤 テレサ・テン 夜の乗客 YORU NO JOKYAKU POLYDOR DR1944 1x7"
    ) is None
    assert extract_release_year(
        "国内盤 テレサ・テン Last Concert -1985.12.15 at NHK Hall- 後編 Stereo Sound SSAR-053 1LP"
    ) is None
    assert extract_release_year(
        "鄧麗君 Teresa Teng 難忘的一天 Vinyl LP KL-1176 Rare Vintage 1968"
    ) == 1968
    assert extract_release_year(
        "Teresa Teng - One & Only: 1985 NHK Live (Complete) [New Vinyl LP] 180 Gram"
    ) is None
    assert album_name_in_listing(
        'Japanese Vinyl LP Record: Teresa Teng - "Anata Magokoro"',
        "テレサ・テン* - 你 (あなた) / まごころ",
    )


def test_listing_label_hint_picks_taurus_pressing() -> None:
    from auction_etl.services.discogs_identity import prefer_listing_label

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "Teresa Teng - 別れの予感",
                "catno": "UPJY-9141",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Universal Music"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "テレサ・テン* - 別れの予感",
                "catno": "28TR-2145",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Taurus Records"],
            },
        ]
    )
    narrowed = prefer_listing_label(hits, title="【CD/taurus盤】別れの予感")
    assert [hit.catno for hit in narrowed] == ["28TR-2145"]
    stereo = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "鄧麗君* - 七○年代名曲選—第四輯 = Best Selections From The 70's, Vol. 4",
                "catno": "3199 318",
                "year": "1980",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["Polydor"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "Teresa Teng - Best Vol. 4",
                "catno": "SSAR-001",
                "year": "2018",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["Stereo Sound"],
            },
        ]
    )
    analog_wrong = prefer_listing_label(
        stereo[:1],
        title="Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
    )
    assert analog_wrong == ()
    stereo_hits = prefer_listing_label(
        stereo,
        title="Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
    )
    assert [hit.catno for hit in stereo_hits] == ["SSAR-001"]
    from auction_etl.services.discogs_identity import prefer_listing_volume

    vols = parse_search_hits(
        [
            {
                "id": 5,
                "type": "release",
                "title": "Teresa Teng - Stereo Sound Original Selection Vol.5",
                "catno": "SSMS-037～038",
                "year": "2019",
                "format": ["Vinyl", "LP"],
                "label": ["Stereo Sound"],
            },
            {
                "id": 4,
                "type": "release",
                "title": "Teresa Teng - Stereo Sound Original Selection Vol.4",
                "catno": "SSMS-035～036",
                "year": "2019",
                "format": ["Vinyl", "LP"],
                "label": ["Stereo Sound"],
            },
        ]
    )
    assert [
        hit.catno
        for hit in prefer_listing_volume(
            vols,
            "Teresa Teng Best Vol. 4 Vinyl Stereo Sound",
        )
    ] == ["SSMS-035～036"]


def test_ferry_boat_single_uses_discogs_spelling() -> None:
    ferry = "21116681;【国内盤/7inch】テレサ・テン / 夜のフェリーボート / 赤坂たそがれ"
    assert known_album_phrase(ferry) == "夜のフェリーボート"
    assert album_name_in_listing(ferry, "テレサ・テン* - 夜のフェリーポート")
    assert hit_bundles_other_album(
        ferry,
        "Teresa Teng - Best Selection 夜のフェリーボート　女の生きがい",
    )
    assert not hit_bundles_other_album(ferry, "テレサ・テン* - 夜のフェリーポート")
    assert (
        known_album_phrase(
            "Gripsweat - Momoe Yamaguchi 19th Single Cosmos Vinyl Record 1977 Japan Pop"
        )
        == "秋桜"
    )
    assert (
        known_album_phrase(
            "Gripsweat - Anita Mui/Before You Put Your Lips On Single Board Hong Kong Diva"
        )
        == "唇をうばう前に"
    )
    assert (
        known_album_phrase("SIDE A IIHI DABIDACHI (leaving on a good day) SIDE B SCANDAL")
        == "いい日旅立ち"
    )
    assert (
        known_album_phrase(
            "Japanese press 7inch!!! Momoe Yamaguchi, Japan's top star of the 1970s"
        )
        is None
    )


def test_listing_search_artist_maps_cjk_and_ebay_english() -> None:
    assert listing_search_artist(None, "yamaguchi momoe rebirth") == "Momoe Yamaguchi"
    assert listing_search_artist(None, "TERESATENG BIG HIT4 POLYDOR KRS3012 1x7") == "Teresa Teng"
    assert not artist_overlaps(
        listing_artist=None,
        listing_title="yamaguchi momoe rebirth",
        discogs_names=("The Children (4)",),
    )
    assert artist_overlaps(
        listing_artist=None,
        listing_title="yamaguchi momoe rebirth",
        discogs_names=("山口百恵", "Momoe"),
    )
    assert listing_search_artist(None, "テレサテン/ベスト&ベスト~香港・CD") == "Teresa Teng"
    assert listing_search_artist(None, "邓丽君 酒醉的探戈 LP") == "Teresa Teng"
    assert listing_search_artist(
        "Teresa Teng",
        "【EP】宝とも子 / コーヒールンバ 検) 美空ひばり 都はるみ テレサ・テン",
    ) == "宝とも子"
    assert listing_search_artist(
        "Teresa Teng",
        "未開封品 CD 5枚組 BOX / テレサ・テン 永久保存版 The Best 100",
    ) == "Teresa Teng"
    assert known_album_phrase(
        "未開封品 CD 5枚組 BOX / テレサ・テン 永久保存版 The Best 100"
    ) is None
    assert known_album_phrase("【CD/国内盤】テレサ・テン / ベスト10") == "ベスト10"
    assert album_name_in_listing(
        "未開封品 CD 5枚組 BOX / テレサ・テン 永久保存版 The Best 100 ?永遠の歌姫?",
        "テレサ・テン* - Teresa Teng Memorial Best = テレサ・テン メモリアルベスト-永遠の歌姫",
    )
    assert listing_search_artist(
        "Teresa Teng",
        "新品 7” 宝とも子 / コーヒールンバ 検) 美空ひばり テレサ・テン",
    ) == "宝とも子"
    assert listing_search_artist(
        "Teresa Teng",
        "美盤 LP テレサ・テン 鄧麗君 夜の乗客／女の生きがい UPJY-9092",
    ) == "Teresa Teng"
    assert listing_search_artist(
        "Teresa Teng",
        "夜の乗客 / 女の生きがい LP",
    ) == "Teresa Teng"
    assert listing_search_artist(
        "Teresa Teng",
        "LP美品/テレサテン/ラスト コンサート/ライブ盤/帯付 [5919RZ]",
    ) == "Teresa Teng"
    assert album_name_in_listing(
        "LP美品/テレサテン/ラスト コンサート/ライブ盤/帯付 [5919RZ]",
        "Last Concert -1985.12.15 at NHK Hall- 前編",
    )
    assert album_name_in_listing(
        "LP美品/テレサテン/ラスト コンサート/ライブ盤/帯付 [5919RZ]",
        "テレサ・テン - Last Concert -1985.12.15 at NHK Hall- 後編",
    )
    assert not album_name_in_listing(
        "LP美品/テレサテン/ラスト コンサート/ライブ盤/帯付 [5919RZ]",
        "ファースト・コンサート",
    )
    assert (
        artist_from_english_title("Kenny Bee Lp Original Hong Kong 1985")
        == "Kenny Bee"
    )
    assert artist_from_english_title("Dirty Dancing Soundtrack Lp") is None
    assert artist_from_english_title("Anita Mui Lp Original Hong Kong") == "Anita Mui"
    assert (
        artist_from_english_title(
            "THE POLICE REGGATTA DE BLANC SP4792 ORIGINAL A&M LP"
        )
        == "THE POLICE"
    )
    assert artist_from_english_title(
        "Paula Tsui Still Lp Original"
    ) == "Paula Tsui"
    assert artist_from_english_title(
        "George Lam Dearest Lp Original Hong Kong 1986"
    ) == "George Lam"
    assert artist_from_english_title(
        "David Lui Fong Lp Original Hong Kong"
    ) == "David Lui Fong"


def test_canonical_artist_and_title_keys_fold_scripts() -> None:
    assert canonical_artist_key("鄧麗君") == canonical_artist_key("Teresa Teng")
    assert canonical_artist_key("Deng Lijun") == canonical_artist_key("テレサ・テン")
    assert canonical_artist_key("梅艳芳") == canonical_artist_key("Anita Mui")
    assert canonical_title_key("Tian Mi Mi") == canonical_title_key("甜蜜蜜")
    assert canonical_title_key("Jiu Zui De Tan Ge") == canonical_title_key(
        "Teresa Teng - 酒醉的探戈"
    )
    assert canonical_title_key("Toki no Nagare ni Mi wo Makase") == canonical_title_key(
        "時の流れに身をまかせ"
    )
    assert canonical_title_key(
        "美盤 LP テレサ・テン 夜の乗客／女の生きがい"
    ) == canonical_title_key("夜の乗客")
    assert canonical_title_key("女のいきがい") == canonical_title_key("女の生きがい")
    assert canonical_title_key("影視名曲精選") == canonical_title_key("Movie Hits")
    assert canonical_title_key("你可知道我愛誰") == canonical_title_key(
        "鄧丽君* - 你可知道我愛誰 / 風從那裡來"
    )


def test_artist_overlaps_traditional_and_simplified_names() -> None:
    assert artist_overlaps(
        listing_artist=None,
        listing_title="邓丽君 酒醉的探戈",
        discogs_names=("鄧麗君",),
    )
    assert artist_overlaps(
        listing_artist="Teresa Teng",
        listing_title="酒酔的探戈",
        discogs_names=("邓丽君",),
    )


def test_same_album_review_shortlist_can_auto_fill() -> None:
    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "テレサ・テン* - つぐない",
                "catno": "35TX-1002",
                "format": ["CD", "Album"],
                "label": ["Taurus"],
                "uri": "/release/1",
            },
            {
                "id": 2,
                "type": "release",
                "title": "テレサ・テン* - つぐない",
                "catno": "35TX-1002",
                "format": ["CD", "Album", "Reissue"],
                "label": ["Taurus"],
                "uri": "/release/2",
            },
        ]
    )
    classification = Classification(
        status="needs_review",
        reason="title_search",
        hits=tuple(hits),
        chosen=None,
    )
    assert unique_hit_can_auto_fill(
        classification,
        listing_artist="Teresa Teng",
        listing_title="【紙ジャケCD】テレサ・テン(鄧麗君)/ つぐない",
        release_artist_names=("Teresa Teng", "テレサ・テン", "鄧麗君"),
    ) is True


def test_different_albums_stay_blocked_from_auto_fill() -> None:
    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "山口百恵* - 16才",
                "catno": "SOLL-70",
                "format": ["Vinyl", "LP"],
                "label": ["CBS/Sony"],
                "uri": "/release/1",
            },
            {
                "id": 2,
                "type": "release",
                "title": "山口百恵* - 17才",
                "catno": "SOLL-85",
                "format": ["Vinyl", "LP"],
                "label": ["CBS/Sony"],
                "uri": "/release/2",
            },
        ]
    )
    classification = Classification(
        status="needs_review",
        reason="ambiguous_hits",
        hits=tuple(hits),
        chosen=None,
    )
    assert unique_hit_can_auto_fill(
        classification,
        listing_artist="Momoe Yamaguchi",
        listing_title="MOMOE YAMAGUCHI 16才 LP",
        release_artist_names=("Momoe Yamaguchi", "山口百恵"),
    ) is False


def test_various_artist_catalog_hit_can_auto_fill_without_listing_artist() -> None:
    hits = parse_search_hits(
        [
            {
                "id": 88,
                "type": "release",
                "title": "Various - 2001: A Space Odyssey - Volume Two",
                "catno": "MMF-1018",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["MGM"],
                "uri": "/release/88",
            }
        ]
    )
    classification = Classification(
        status="needs_review",
        reason="artist_mismatch",
        hits=tuple(hits),
        chosen=None,
    )
    assert unique_hit_can_auto_fill(
        classification,
        listing_artist=None,
        listing_title="VA 2001: A SPACE ODYSSEY VOL.2 MGM MMF1018 Japan OBI VINYL LP",
        release_artist_names=("Various",),
        listing_catalog="MMF-1018",
    ) is True


def test_album_name_agrees_on_aliased_titles() -> None:
    assert album_name_in_listing(
        "Teresa Teng With Love From... Teresa Teng 12\" Black Vinyl LP Pop Polydor",
        "Teresa Teng - With Love From... 愛之世界",
    )
    assert album_name_in_listing(
        "TERESA TENG 鄧麗君 Shuishang Ren 水上人 Vinyl LP 1981 Hong Kong Polydor",
        "鄧麗君* - 水上人",
    )
    assert album_name_in_listing(
        "テレサ・テン ’９１ 悲しみと踊らせて LP 未使用品",
        "Teresa Teng - ’91悲しみと踊らせて~ニュー・オリジナル・ソングス~",
    )
    assert album_name_in_listing(
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, Compilation, Numbered, Taiwan",
        "鄧麗君* - 鄧麗君 15週年",
    )
    assert not album_name_in_listing(
        "LP / テレサ テン / 夜来香/何日君再来 / 帯付",
        "鄧麗君* - 青山綠水我和你",
    )
    assert not album_name_in_listing(
        "MOMOE YAMAGUCHI Again CBS/SONY LP VG++ japan w/ inserts s",
        "山口百恵* = Momoe Yamaguchi - 山口百恵 = Momoe Yamaguchi",
    )
    assert album_name_in_listing(
        "MOMOE YAMAGUCHI Again CBS/SONY LP VG++ japan w/ inserts s",
        "山口百恵* - Again 百恵",
    )
    assert not album_name_in_listing(
        "1991 Teresa Teng 鄧麗君 巨星名曲23 世界多變化 Chinese CD Songs Music Sun Light Record Taiwan",
        "Teresa Teng - Teresa Teng = テレサ・テン 全曲中国語歌唱",
    )
    assert album_name_in_listing(
        "LP / テレサ テン / 夜の乗客 [5831RZ]",
        "夜の乗客 / 女の生きがい",
    )
    assert album_name_in_listing(
        "鄧麗君島國情歌六1989 年版CD",
        "鄧麗君* - 小城故事",
    )
    assert album_name_in_listing(
        "41193375;【CD/香港盤/T113】テレサ・テン(鄧麗君) / 永遠的情懐",
        "鄧麗君* = Teresa* - 永遠的情懷",
    )
    assert album_name_in_listing(
        "鄧麗君 – Greatest Hits Vol.2 Teresa Teng RARE 1989 CD Hong Kong Mandopop",
        "鄧麗君* - Greatest Hits Vol.2",
    )
    encore_live = "2-CD Teresa Teng 1988 Encore Live in Japan Concert + Alan Tam 1988 CD"
    assert known_album_phrase(encore_live) == "現場錄音珍藏版"
    assert album_name_in_listing(
        encore_live,
        "鄧麗君* - 鄧麗君演唱會 - 現場錄音珍藏版",
    )
    assert album_name_in_listing(encore_live, "鄧麗君* - 演唱會 = Encore")
    assert not album_name_in_listing(
        encore_live,
        "Teresa Teng / 鄧麗君 - Concert Live",
    )
    assert not album_name_in_listing(
        encore_live,
        "Teresa Teng - Teresa Teng = テレサ・テン 全曲中国語歌唱",
    )
    assert not album_name_in_listing(
        "LP / テレサテン / 我只在乎? / 香港盤 [0028RZ]",
        "テレサ・テン / 鄧麗君 - 香港 = Hong Kong",
    )
    assert album_name_in_listing(
        "LP / テレサテン / 我只在乎? / 香港盤 [0028RZ]",
        "鄧麗君 - 我只在乎你",
    )
    assert not album_name_in_listing(
        "TERESA TENG 1982 LP W/ INSERT HONG KONG CHINESE CHINA RARE POLYDOR 2427 374",
        "テレサ・テン / 鄧麗君 - 香港 = Hong Kong",
    )
    assert not album_name_in_listing(
        "TERESA TENG 1976 LP HONG KONG RARE LFLP 486 THERES",
        "テレサ・テン / 鄧麗君 - 香港 = Hong Kong",
    )
    assert catalog_token(
        title="TERESA TENG 1982 LP W/ INSERT HONG KONG CHINESE CHINA RARE POLYDOR 2427 374",
    ) == "2427 374"
    assert catalog_token(
        title="TERESA TENG 1976 LP HONG KONG RARE LFLP 486 THERES",
    ) == "LFLP-486"
    assert catno_locks_listing("2427 374", "2427 374")
    assert catno_locks_listing("LFLP-486", "LFLP-486")
    hong_kong_region = (
        "TERESA TENG 1982 LP W/ INSERT HONG KONG CHINESE CHINA RARE POLYDOR 2427 374"
    )
    assert not shortlist_agrees_with_listing(
        hong_kong_region,
        [
            {
                "title": "テレサ・テン / 鄧麗君 - 香港 = Hong Kong",
                "catno": "07TR-7208",
            }
        ],
        "2427 374",
    )
    assert shortlist_agrees_with_listing(
        hong_kong_region,
        [
            {
                "title": "テレサ・テン / 鄧麗君 - 初次嚐到寂寞",
                "catno": "2427 374",
            }
        ],
        "2427 374",
    )
    assert album_name_in_listing(
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp",
        "鄧麗君* - 鄧麗君之歌第十一集",
    )
    assert listing_volume_number("鄧麗君之歌第十一集") == 11
    assert listing_volume_number("鄧麗君之歌 (一)") == 1
    assert listing_volume_number(
        "【台盤LP】「鄧麗君（テレサ・テン）/玉女巨星鄧麗君之歌第十六集」宇宙唱片"
    ) == 16
    assert not album_name_in_listing(
        "【台盤LP】「鄧麗君（テレサ・テン）/玉女巨星鄧麗君之歌第十六集」宇宙唱片",
        "鄧麗君 - 鄧麗君之歌",
    )
    assert not album_name_in_listing(
        "【台盤LP】「鄧麗君（テレサ・テン）/玉女巨星鄧麗君之歌第十六集」宇宙唱片",
        "鄧麗君 / Teresa Teng - 鄧麗君之歌 (一)",
    )
    assert album_name_in_listing(
        "Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
        "Teresa Teng - Best Vol. 4",
    )
    assert album_name_in_listing(
        "Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
        "Teresa Teng - Teresa Teng = テレサ・テン",
    )
    assert not album_name_in_listing(
        "Teresa Teng 鄧麗君 Vol. 3 2017 Japan LP Sealed W/Insert Limited Edition 180g",
        "鄧麗君 - Greatest Hits Vol. 3",
    )
    assert album_name_in_listing(
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp",
        "鄧麗君* - 鄧麗君之歌第十一集",
    )
    assert not album_name_in_listing(
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp",
        "鄧麗君* - 鄧麗君之歌第十二集",
    )
    assert album_name_in_listing(
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp",
        "鄧麗君* - 再會吧！十七歲",
    )
    assert not album_name_in_listing(
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp",
        "鄧麗君* - 鄧麗君之歌第一集 - 再會吧！十七歲",
    )
    assert album_name_in_listing(
        "Teresa Teng 70th Anniversary Best Album JAPAN CD New",
        "テレサ・テン* - 生誕70年ベスト・アルバム   没後30年",
    )
    assert not album_name_in_listing(
        "Teresa Teng 70th Anniversary Best Album JAPAN CD New",
        "テレサ・テン* - 夜来香",
    )
    assert album_name_in_listing(
        "鄧麗君 2009 CD Teresa Teng Made In Germany Excellent Condition",
        "鄧麗君* - 鄧麗君 25週年",
    )
    assert not album_name_in_listing(
        "鄧麗君 2009 CD Teresa Teng Made In Germany Excellent Condition",
        "鄧麗君* = Teresa* - 永遠的情懷",
    )
    farewell = "◎Rare out of print.Teresa Teng Premonition of Farewell"
    assert known_album_phrase(farewell) == "別れの予感"
    assert listing_names_specific_album(farewell)
    assert album_name_in_listing(farewell, "テレサ・テン* - 別れの予感")
    assert not album_name_in_listing(farewell, "鄧麗君* = Teresa Teng - 永遠的珍藏")
    assert not album_name_in_listing(
        farewell,
        "テレサ・テン* = 鄧麗君* - 時の流れに身をまかせ",
    )
    assert hit_bundles_other_album(
        farewell,
        "テレサ・テン* - テレサ・テン（鄧麗君） 2 —時の流れに身をまかせ・夜のフェリーボート・別れの予感—",
    )
    assert not hit_bundles_other_album(farewell, "テレサ・テン* - 別れの予感")
    assert not album_name_in_listing(
        "Teresa Teng - One & Only: 1985 NHK Live (Complete) [New Vinyl LP] 180 Gram",
        "テレサ・テン - Teresa Teng = テレサ・テン",
    )
    mistress = "Teresa Teng, Mistress, LP Stereo Sound New JP2"
    assert album_name_in_listing(mistress, "テレサ・テン* = 鄧麗君* - 愛人")
    assert album_name_in_listing(mistress, "愛人")
    assert not album_name_in_listing(mistress, "Teresa Teng - Teresa Teng = テレサ・テン")
    self_titled = (
        "Anita Mui: 梅艷芳 Self Titled (1985) Original HK LP Vinyl Record Factory Sealed"
    )
    assert album_name_in_listing(self_titled, "梅艷芳 - 梅艷芳")
    assert not album_name_in_listing(self_titled, "梅艷芳 - Anita")
    red = "Gripsweat - ANITA MUI-Red Anita (1983) HUAXING ENTERTAINMENT/CHINA STAR LP w/post cards"
    assert known_album_phrase(red) == "赤色梅艷芳"
    assert album_name_in_listing(red, "梅艷芳* - 赤色梅艷芳")
    assert not album_name_in_listing(red, "梅艷芳* - Anita")
    first_love = "Teresa Teng - Unforgettable First Love (CD, 1995) Mandopop Original w/OBI OOP"
    assert known_album_phrase(first_love) == "難忘初戀的情人"
    one_only = "Teresa Teng - One & Only: 1985 NHK Live Best Selection [New Vinyl LP]"
    assert known_album_phrase(one_only) == "One & Only"
    assert not album_name_in_listing(one_only, "Poco - Live")
    assert album_name_in_listing(first_love, "鄧麗君* - 難忘初戀的情人")
    assert not album_name_in_listing(first_love, "鄧麗君* = Teresa* - 永遠的情懷")
    tugunai = (
        'Japanese press 7" Artist from Taiwan TERESA TENG TUGUNAI / WARATTE KANPAI'
    )
    assert known_album_phrase(tugunai) == "つぐない"
    assert album_name_in_listing(tugunai, "テレサ・テン* - つぐない")
    big_hit = "TERESATENG BIG HIT4 POLYDOR KRS3012 1x7"
    assert known_album_phrase(big_hit) == "ビッグヒット4"
    assert album_name_in_listing(big_hit, "テレサ・テン* - ビッグヒット4")
    assert not album_name_in_listing(big_hit, "Teresa Teng - Teresa Teng Best Hit 4")


def test_polydor_dr_catalog_is_seven_inch_not_lp() -> None:
    from auction_etl.services.discogs_identity import (
        SearchHit,
        _is_seven_inch,
        catalog_fits_listing_media,
        catalog_implies_seven_inch,
        prefer_listing_shape,
        stored_catalog_fits_listing,
    )

    assert catalog_implies_seven_inch("DR 1944")
    assert catalog_implies_seven_inch("DR-1944")
    assert catalog_fits_listing_media("DR 1944", "LP") is False
    assert catalog_fits_listing_media("DR 1944", "7_inch") is True
    assert stored_catalog_fits_listing(
        "DR-1944",
        title="LP / テレサ テン / 夜の乗客",
        media_type="LP",
    ) is False
    hit = SearchHit(
        discogs_id=10843318,
        title="テレサ・テン / 鄧麗君 - 夜の乗客",
        catno="DR 1944",
        year="1975",
        country="Japan",
        formats=("Vinyl", "LP"),
        labels=("Polydor",),
        thumb_url=None,
        uri="/release/10843318",
    )
    assert _is_seven_inch(hit)
    album = SearchHit(
        discogs_id=12314624,
        title="テレサ・テン* - 夜の乗客 / 女の生きがい",
        catno="MR2267",
        year="1975",
        country="Japan",
        formats=("Vinyl", "LP", "Album"),
        labels=("Polydor",),
        thumb_url=None,
        uri="/release/12314624",
    )
    assert prefer_listing_shape((hit, album), "LP") == (album,)


def test_sun_light_series_volume_does_not_fall_back_to_other_issue() -> None:
    from auction_etl.services.discogs_identity import (
        listing_volume_number,
        prefer_listing_volume,
        parse_search_hits,
    )

    listing = (
        "1991 Teresa Teng 鄧麗君 巨星名曲23 世界多變化 "
        "Chinese CD Songs Music Sun Light Record Taiwan"
    )
    assert listing_volume_number(listing) == 23
    assert listing_volume_number("鄧麗君* - 巨星名曲3") == 3
    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "鄧麗君* - 巨星名曲3",
                "catno": "SL-6026",
                "format": ["Cassette", "Compilation"],
                "label": ["興來唱片"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "Teresa Teng - Teresa Teng = テレサ・テン 全曲中国語歌唱",
                "catno": "SSMS-046～047",
                "format": ["CD"],
                "label": ["Stereo Sound"],
            },
        ]
    )
    assert prefer_listing_volume(hits, listing) == ()


def test_self_titled_discogs_does_not_steal_again_listing() -> None:
    from auction_etl.services.discogs_identity import discogs_format_label

    hits = parse_search_hits(
        [
            {
                "id": 38,
                "type": "release",
                "title": "山口百恵* = Momoe Yamaguchi - 山口百恵 = Momoe Yamaguchi",
                "catno": "38AH217~8",
                "year": "1977",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["CBS/Sony"],
            },
            {
                "id": 530,
                "type": "release",
                "title": "山口百恵* - Again 百恵",
                "catno": "25AH 530",
                "year": "1980",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["CBS/Sony"],
            },
            {
                "id": 531,
                "type": "release",
                "title": "山口百恵* - Again 百恵",
                "catno": "35DH 50",
                "year": "1982",
                "format": ["CD", "Album"],
                "label": ["CBS/Sony"],
            },
        ]
    )
    result = classify_search_hits(
        catalog_number=None,
        title="MOMOE YAMAGUCHI Again CBS/SONY LP VG++ japan w/ inserts s",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=hits,
    )
    catnos = {hit.catno for hit in result.hits}
    labels = {discogs_format_label(hit.formats) for hit in result.hits}
    assert "38AH217~8" not in catnos
    assert "25AH 530" in catnos
    assert "35DH 50" in catnos
    assert "LP" in labels
    assert "CD" in labels
    assert result.chosen is None
    assert result.status == "needs_review"


def test_unique_wrong_album_does_not_enter_review() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="TERESA TENG 鄧麗君 Shuishang Ren 水上人 Vinyl LP 1981 Hong Kong Polydor NM w/ INSERT",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits(
            [
                {
                    "id": 11965483,
                    "type": "release",
                    "title": "鄧麗君* - 鄧麗君 15週年",
                    "catno": "817 131-1",
                    "year": "1983",
                    "country": "Hong Kong",
                    "format": ["Vinyl", "LP", "Album", "Stereo"],
                    "label": ["Polydor"],
                    "thumb": "",
                    "uri": "/release/11965483",
                }
            ]
        ),
    )
    assert result.status == "unmatched"
    assert result.reason == "empty_shortlist"
    assert result.chosen is None
    assert result.hits == ()


def test_with_love_from_locks_ai_zhi_shi_jie() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="Teresa Teng With Love From... Teresa Teng 12\" Black Vinyl LP Pop Polydor",
        artist="Teresa Teng",
        media_type="LP",
        hits=parse_search_hits(
            [
                {
                    "id": 2488368,
                    "type": "release",
                    "title": "Teresa Teng = 鄧麗君* - With Love From... 愛之世界",
                    "catno": "",
                    "year": "1976",
                    "country": "Hong Kong",
                    "format": ["Vinyl", "LP", "Album", "Stereo"],
                    "label": ["Polydor"],
                    "thumb": "",
                    "uri": "/release/2488368",
                }
            ]
        ),
    )
    assert result.status == "filled_auto"
    assert result.reason == "title_search"
    assert result.chosen is not None
    assert result.chosen.discogs_id == 2488368


def test_catalog_prefix_distance_ranks_nearby_38tt_ahead_of_tatl() -> None:
    from auction_etl.services.discogs_identity import (
        catalog_letter_prefix,
        catalog_number_distance,
        discogs_format_label,
    )

    assert catalog_letter_prefix("38TT-1120") == "38TT"
    assert catalog_letter_prefix("38TT-1145") == "38TT"
    assert catalog_letter_prefix("TATL-2365") == "TATL"
    assert catalog_number_distance("38TT-1120", "38TT-1145") < catalog_number_distance(
        "38TT-1120",
        "38TT-1070",
    )
    hits = parse_search_hits(
        [
            {
                "id": 2365,
                "type": "release",
                "title": "テレサ・テン* - 全曲集 ~あなたの共に生きてゆく~",
                "catno": "TATL-2365",
                "year": "1993",
                "country": "Japan",
                "format": ["Cassette", "Album", "Compilation"],
                "label": ["Taurus Records"],
            },
            {
                "id": 1220,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "30CX-1220",
                "year": "1983",
                "country": "Japan",
                "format": ["Cassette", "Compilation"],
                "label": ["Canyon"],
            },
            {
                "id": 1145,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "38TT-1145",
                "year": "1987",
                "country": "Japan",
                "format": ["Cassette", "Compilation"],
                "label": ["Taurus Records"],
            },
            {
                "id": 1070,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "38TT-1070",
                "year": "1985",
                "country": "Japan",
                "format": ["Cassette", "Compilation"],
                "label": ["Taurus Records"],
            },
            {
                "id": 1042,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "29TX-1042",
                "year": "1986",
                "country": "Japan",
                "format": ["CD", "Compilation"],
                "label": ["Taurus Records"],
            },
        ]
    )
    result = classify_search_hits(
        catalog_number="38TT-1120",
        title="テレサ・テン/全曲集/38TT-1120",
        artist="Teresa Teng",
        media_type="CASSETTE",
        hits=hits,
        require_catalog_token=False,
    )
    assert result.status == "needs_review"
    assert result.chosen is None
    assert result.hits[0].catno == "38TT-1145"
    labels = {discogs_format_label(hit.formats) for hit in result.hits}
    assert "Cassette" in labels
    assert "CD" in labels


def test_island_volume_six_cd_leads_with_1989_cd_not_cassette() -> None:
    from auction_etl.services.discogs_identity import (
        classify_search_hits,
        discogs_format_label,
        parse_search_hits,
    )

    title = "鄧麗君島國情歌六1989 年版CD所有$45以下"
    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "鄧麗君* = Teresa Teng - 小城故事",
                "catno": "3199 203",
                "year": "1979",
                "country": "Singapore, Malaysia & Hong Kong",
                "format": ["Cassette", "Album", "Stereo"],
            },
            {
                "id": 2,
                "type": "release",
                "title": "鄧麗君* - 小城故事",
                "catno": "KL-1161",
                "year": "1979",
                "country": "Taiwan",
                "format": ["Vinyl", "LP", "Album"],
            },
            {
                "id": 4991732,
                "type": "release",
                "title": "鄧麗君* - 小城故事",
                "catno": "2731715",
                "year": "2010",
                "country": "Hong Kong",
                "format": ["CD", "Album", "Reissue"],
            },
            {
                "id": 29786113,
                "type": "release",
                "title": "鄧麗君* - 小城故事",
                "catno": "837 857-2",
                "year": "1989",
                "country": "Hong Kong",
                "format": ["CD", "Album", "Reissue", "Stereo"],
            },
            {
                "id": 30588850,
                "type": "release",
                "title": "邓丽君* - 小城故事",
                "catno": "JCD-4001",
                "year": "1993",
                "country": "Taiwan",
                "format": ["CD", "Compilation"],
            },
        ]
    )
    result = classify_search_hits(
        catalog_number=None,
        title=title,
        artist="Teresa Teng",
        media_type="CD",
        hits=hits,
        require_catalog_token=False,
    )
    assert result.status == "needs_review"
    assert result.hits[0].catno == "837 857-2"
    assert discogs_format_label(result.hits[0].formats) == "CD"
    labels = [discogs_format_label(hit.formats) for hit in result.hits]
    assert labels[0] == "CD"
    assert "Cassette" in labels or "LP" in labels


def test_yeu_jow_volume_sixteen_is_awk_039_not_generic_songbook() -> None:
    from auction_etl.services.discogs_identity import (
        classify_search_hits,
        listing_label_hints,
        parse_search_hits,
        prefer_listing_volume,
        shortlist_agrees_with_listing,
    )

    title = "【台盤LP】「鄧麗君（テレサ・テン）/玉女巨星鄧麗君之歌第十六集」宇宙唱片"
    assert listing_label_hints(title=title) == ("space record",)
    hits = parse_search_hits(
        [
            {
                "id": 15198418,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君之歌",
                "catno": "LFLP 199",
                "year": "1971",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Life"],
            },
            {
                "id": 16723890,
                "type": "release",
                "title": "鄧麗君* = Teresa Teng - 鄧麗君之歌 (一)",
                "catno": "HV-5011",
                "year": "1980",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["Hai Shan"],
            },
            {
                "id": 11837412,
                "type": "release",
                "title": "鄧麗君* - 戀愛的路多麼甜",
                "catno": "AWK-039",
                "year": "1970",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Yeu Jow Record"],
            },
        ]
    )
    refined = prefer_listing_volume(hits, title)
    assert [hit.catno for hit in refined] == ["AWK-039"]
    result = classify_search_hits(
        catalog_number=None,
        title=title,
        artist="Teresa Teng",
        media_type="LP",
        hits=hits,
        require_catalog_token=False,
    )
    assert result.status in {"needs_review", "filled_auto"}
    assert result.hits[0].catno == "AWK-039"
    assert shortlist_agrees_with_listing(
        title,
        [{"title": "鄧麗君* - 戀愛的路多麼甜", "catno": "AWK-039"}],
    )
    assert not shortlist_agrees_with_listing(
        title,
        [{"title": "鄧麗君 - 鄧麗君之歌", "catno": "LFLP 199"}],
    )

