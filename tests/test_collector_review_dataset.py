"""Unique-sale dataset stats and media chips for Collector Review."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.collector_review_support import (
    MEDIA_GROUP_ALL_MUSIC,
    MEDIA_GROUP_CASSETTE,
    MEDIA_GROUP_EVERYTHING,
    MEDIA_GROUP_LOTS,
    MEDIA_GROUP_LP,
    MEDIA_GROUP_MAGAZINES,
    MEDIA_GROUP_OPTIONS,
    drop_overlapping_gripsweat_rows,
    marketplace_source_label,
    media_matches_group,
    auction_outcome_chart,
    listing_stays_open,
    no_bid_auction_rows,
    omit_no_bid_auctions,
    sales_without_no_bid_auctions,
)

REVIEW = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "collector_review.py"
)
INTEGRATION = (
    Path(__file__).resolve().parents[1]
    / "auction_etl"
    / "reporting"
    / "main_review_integration.py"
)


def sample_review_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "marketplace": "ebay",
                "listing_id": "188586715117",
                "title": "Teresa Teng LP",
                "media_display": "LP",
            },
            {
                "marketplace": "gripsweat",
                "listing_id": "188586715117",
                "title": "Archive duplicate",
                "media_display": "LP",
            },
            {
                "marketplace": "gripsweat",
                "listing_id": "365844295248",
                "title": "Gripsweat-only Anita LP",
                "media_display": "LP",
            },
            {
                "marketplace": "buyee",
                "listing_id": "h1243668787",
                "title": "Buyee LP",
                "media_display": "LP",
            },
        ]
    )


def test_gripsweat_ebay_overlap_is_dropped_from_unique_sales() -> None:
    result = drop_overlapping_gripsweat_rows(sample_review_rows())
    identities = set(
        zip(
            result["marketplace"],
            result["listing_id"],
            strict=True,
        )
    )
    assert ("ebay", "188586715117") in identities
    assert ("gripsweat", "188586715117") not in identities
    assert ("gripsweat", "365844295248") in identities
    assert len(result) == 3


def test_source_labels_are_stable() -> None:
    assert marketplace_source_label("ebay") == "eBay"
    assert marketplace_source_label("BUYEE") == "Buyee"
    assert marketplace_source_label("gripsweat") == "Gripsweat"


def test_media_group_keeps_lots_off_lp_and_all_music() -> None:
    assert media_matches_group("LP", MEDIA_GROUP_LP, job_lot=False)
    assert media_matches_group("SINGLE_12_INCH", MEDIA_GROUP_LP, job_lot=False)
    assert media_matches_group("12_INCH_SINGLE", MEDIA_GROUP_LP)
    assert media_matches_group("LP", MEDIA_GROUP_LP, job_lot=True) is False
    assert media_matches_group("LP", MEDIA_GROUP_LOTS, job_lot=True)
    assert media_matches_group("CASSETTE", MEDIA_GROUP_CASSETTE, job_lot=False)
    assert media_matches_group("MAGAZINE", MEDIA_GROUP_ALL_MUSIC) is False
    assert media_matches_group("MAGAZINE", MEDIA_GROUP_MAGAZINES)
    assert media_matches_group("MAGAZINE", MEDIA_GROUP_EVERYTHING)


def test_named_pressing_without_discogs_is_filled() -> None:
    from app.collector_review_support import (
        apply_local_identity,
        release_identified_locally,
    )

    assert release_identified_locally(
        catalog="SRCL-3281~3",
        media="CD",
        title="【3CD】山口百恵 / 百恵辞典 SRCL-3281~3",
    )
    assert release_identified_locally(
        catalog="SRCL-3281~3",
        media="CD",
        title="42本 カセット",
        job_lot=True,
    ) is False
    assert release_identified_locally(catalog="", media="CD", title="百恵辞典") is False
    assert release_identified_locally(catalog="SRCL-3281", media="", title="百恵辞典") is False
    frame = apply_local_identity(
        pd.DataFrame(
            [
                {
                    "identity_status_display": "Unmatched",
                    "catalog_display": "SRCL-3281~3",
                    "media_display": "CD",
                    "title": "【3CD】山口百恵 / 百恵辞典 SRCL-3281~3",
                    "job_lot": False,
                },
                {
                    "identity_status_display": "Unmatched",
                    "catalog_display": "",
                    "media_display": "CD",
                    "title": "山口百恵",
                    "job_lot": False,
                },
                {
                    "identity_status_display": "Needs review",
                    "catalog_display": "MR 3037",
                    "media_display": "LP",
                    "title": "ベスト・ヒット",
                    "job_lot": False,
                },
            ]
        )
    )
    assert list(frame["identity_status_display"]) == [
        "Filled",
        "Unmatched",
        "Needs review",
    ]


def test_review_page_shows_unique_dataset_and_media_chips() -> None:
    source = REVIEW.read_text(encoding="utf-8")
    assert "Unique sales" in source
    assert "format_count(unique_sales)" in source
    assert "MEDIA_GROUP_ALL_MUSIC" in source
    assert "_render_identity_reflection" in source
    assert "_open_identity_pile" in source
    assert "_render_identity_queue_cards" in source
    assert "identity-pile-matched" in source
    assert "identity-pile-review" in source
    assert "Need a decision" in source
    assert "In the table" in source
    assert 'st-key-identity-pile-' in source
    assert "#15803d" in source
    assert "#c2410c" in source
    assert 'stack="normalize"' not in source
    assert "Share of each marketplace" not in source
    assert "identity_mix_caption" in source
    load_sql = source.split("def load_records", 1)[-1].split("def prepare_records", 1)[0]
    _skipped, after_skip = load_sql.split('"source_fingerprint"', 1)
    assert "source_fingerprint" not in after_skip
    assert "lower(btrim(visible.marketplace))" not in load_sql
    assert "visible.marketplace = r.marketplace" in load_sql
    assert "drop_overlapping_gripsweat_rows(native_records)" in source
    assert "load_gripsweat_records(" not in source.split("def load_records", 1)[-1].split("def prepare_records", 1)[0]
    assert "MEDIA_GROUP_EVERYTHING" in source
    assert "MEDIA_GROUP_LOTS" in source
    assert '12"' not in MEDIA_GROUP_OPTIONS
    assert "Gripsweat-only" in source
    assert "shortlist_preview_thumb" in source
    assert "bulk lots sit on the Lots chip" in source
    assert "click Lots to open them" in source
    assert "collector_filter_identity" in source
    assert "_identity_queue_changed" in source
    assert "Bulk lot review" in source
    assert '"BULK_LOT"' in source
    assert "Records in the lot" in source
    assert "lot_mode" in source
    assert "queue_records" in source
    assert "TWELVE_INCH_MEDIA" in source
    assert "r.effective_media_type = 'EP_7_INCH'" not in load_sql
    assert "on_click=_open_identity_pile" in source
    assert "apply_local_identity(records)" in source
    assert 'FILTER_WIDGET_KEYS["media_type"]] = "all"' in source
    assert "omit_no_bid_auctions(frame)" in source
    assert "Days to sell" in source


def test_shortlist_preview_exposes_cover_and_label() -> None:
    from app.collector_review_support import (
        shortlist_preview_label,
        shortlist_preview_thumb,
    )

    payload = [
        {
            "thumb": "https://i.discogs.com/example.jpg",
            "label": ["Taurus"],
        }
    ]
    assert shortlist_preview_thumb(payload).endswith("example.jpg")
    assert shortlist_preview_label(payload) == "Taurus"


def test_identity_mix_caption_uses_percentages() -> None:
    from app.collector_review_support import identity_mix_caption

    caption = identity_mix_caption(565, 345, 961)
    assert "565 matched (30%)" in caption
    assert "345 need a decision (18%)" in caption
    assert "961 unmatched (51%)" in caption
    with_lots = identity_mix_caption(609, 539, 689, lots=146)
    assert "146 lots parked" in with_lots
    assert "609 matched" in with_lots
    lots_only = identity_mix_caption(0, 0, 0, lots=170)
    assert lots_only == "170 bulk lots ready for review"


def test_identity_queue_selects_work_piles() -> None:
    from app.collector_review_support import (
        IDENTITY_QUEUE_ALL,
        identity_matches_queue,
    )

    assert identity_matches_queue("Filled", IDENTITY_QUEUE_ALL)
    assert identity_matches_queue("Filled", "Filled")
    assert identity_matches_queue("Needs review", "Filled") is False
    assert identity_matches_queue("Unmatched", "Unmatched")
    assert identity_matches_queue("Unmatched", "Lot", job_lot=False) is False
    assert identity_matches_queue("Unmatched", "Lot", job_lot=True)
    assert identity_matches_queue("Filled", "Filled", job_lot=True) is False
    assert identity_matches_queue("Lot", "Lot", job_lot=True)


def test_matched_form_shows_cd_seven_inch_and_lp_facts() -> None:
    from app.collector_review_support import (
        automatic_catalog,
        automatic_disc_count,
        automatic_media_type,
        automatic_pressing_group,
        automatic_pressing_type,
        automatic_region,
        automatic_sale_type,
        form_choice,
        save_choice,
        save_count,
        save_text,
    )

    media = ("Automatic / unset", "LP", "EP_7_INCH", "CD")
    regions = ("Automatic / unset", "Japan", "Hong Kong")
    pressing_types = ("Automatic / unset", "STANDARD", "PROMO_SAMPLE", "REISSUE")
    sales = ("Automatic / unset", "AUCTION", "FIXED_PRICE", "UNKNOWN")
    seven = {
        "title": "TERESA TENG TOKINO NAGARENI MIWO MAKASE TAURUS 07TR1115 1x7",
        "media_type": "EP_7_INCH",
        "effective_media_type": "Vinyl",
        "effective_catalog_number": "07TR-1115",
        "effective_region": "Japan",
        "effective_disc_count": 1,
        "effective_pressing_type": "STANDARD",
        "identity_status": "filled_auto",
        "pressing_id": 199,
        "auction_format": "AUCTION",
        "pressing_token": "07TR1115",
    }
    assert automatic_media_type(seven, media) == "EP_7_INCH"
    assert automatic_catalog(seven) == "07TR-1115"
    assert automatic_region(seven, regions) == "Japan"
    assert automatic_disc_count(seven) == 1
    assert automatic_pressing_type(seven, pressing_types) == "STANDARD"
    assert automatic_sale_type(seven, sales) == "AUCTION"
    assert automatic_pressing_group(seven) == "07TR1115"
    assert form_choice("CD", "EP_7_INCH", media) == "CD"
    assert save_choice("EP_7_INCH", "EP_7_INCH", manual_already=False) is None
    assert save_choice("LP", "EP_7_INCH", manual_already=False) == "LP"
    assert save_choice("CD", "EP_7_INCH", manual_already=True) == "CD"
    assert save_text("07TR-1115", "07TR-1115", manual_already=False) is None
    assert save_count(1, 1, manual_already=False) is None
    assert save_count(2, 1, manual_already=False) == 2

    cd = {
        **seven,
        "media_type": "CD",
        "effective_media_type": "CD",
        "effective_catalog_number": "837 857-2",
        "effective_region": "Hong Kong",
        "auction_format": "FIXED_PRICE",
    }
    assert automatic_media_type(cd, media) == "CD"
    assert automatic_catalog(cd) == "837 857-2"
    assert automatic_region(cd, regions) == "Hong Kong"
    lp = {**seven, "media_type": "LP", "effective_media_type": "LP", "effective_catalog_number": "SOLL-114"}
    assert automatic_media_type(lp, media) == "LP"
    assert automatic_catalog(lp) == "SOLL-114"
    unmatched = {
        "media_type": "EP_7_INCH",
        "effective_media_type": "EP_7_INCH",
        "effective_region": "Hong Kong",
        "identity_status": "unmatched",
        "effective_pressing_type": "STANDARD",
    }
    assert automatic_media_type(unmatched, media) == "EP_7_INCH"
    assert automatic_region(unmatched, regions) == "Hong Kong"
    assert automatic_pressing_type(unmatched, pressing_types) is None


def test_first_pressing_follows_the_earliest_release_year() -> None:
    from app.collector_review_support import (
        apply_pressing_copy_facts,
        date_pressing_type,
        pressing_type_label,
        stated_completeness,
    )

    assert (
        date_pressing_type(
            generation="UNKNOWN",
            format_detail='Vinyl, 7", Single, Special Edition',
            release_year=1980,
            earliest_year=1980,
        )
        == "FIRST_PRESSING"
    )
    assert (
        date_pressing_type(
            generation="REISSUE",
            format_detail='Vinyl, 7", Reissue',
            release_year=1985,
            earliest_year=1978,
        )
        == "REISSUE"
    )
    assert (
        date_pressing_type(
            generation="PROMO",
            format_detail='Vinyl, 7", 45 RPM, Single, Promo, Stereo',
            release_year=1986,
            earliest_year=1986,
            title="TERESA TENG TOKINO NAGARENI MIWO MAKASE TAURUS 07TR1115 1x7",
        )
        == "FIRST_PRESSING"
    )
    assert (
        date_pressing_type(
            generation="PROMO",
            format_detail='Vinyl, 7", Promo',
            release_year=1986,
            earliest_year=1986,
            title="TERESA TENG HARUWOMATSUHANA POLYDOR 7DX1442 Japan PROMO VINYL 7",
        )
        == "PROMO_SAMPLE"
    )
    assert date_pressing_type(
        generation="UNKNOWN",
        format_detail="Vinyl",
        release_year=None,
        earliest_year=None,
    ) is None
    assert pressing_type_label("FIRST_PRESSING", 1980) == "First pressing (1980)"
    assert pressing_type_label("REISSUE", 1985) == "Later press (1985)"
    assert pressing_type_label("FIRST_PRESSING", 2026) == "First pressing"
    assert pressing_type_label("REISSUE", 2026) == "Later press"
    assert date_pressing_type(
        generation="UNKNOWN",
        format_detail="Vinyl, 7\"",
        release_year=2026,
        earliest_year=2026,
    ) is None
    assert (
        date_pressing_type(
            generation="REISSUE",
            format_detail="Vinyl, LP, Album, Reissue",
            release_year=2020,
            earliest_year=1987,
            title="【美盤/帯付/Taurus/プロモ】テレサ・テン / 別れの予感",
        )
        == "PROMO_SAMPLE"
    )
    assert (
        date_pressing_type(
            generation="UNKNOWN",
            format_detail="Vinyl, LP, Album, Stereo",
            release_year=1987,
            earliest_year=1987,
            title="LP / テレサ・テン / 演歌のメッセージ / 見本盤",
        )
        == "PROMO_SAMPLE"
    )
    assert (
        date_pressing_type(
            generation="UNKNOWN",
            format_detail="Vinyl, LP, Album, Stereo",
            release_year=2011,
            earliest_year=2011,
            title=(
                "Teresa Teng - One & Only: 1985 NHK Live (Complete) "
                "[New Vinyl LP] 180 Gram"
            ),
        )
        == "REISSUE"
    )
    assert pressing_type_label("REISSUE", 2011) == "Later press (2011)"

    notes = (
        "Silver foil obi strip and a card.\n"
        "Gatefold cover with lyrics inside."
    )
    assert stated_completeness(notes, "ICHIE 1x7") == {
        "obi": True,
        "insert": True,
    }
    assert stated_completeness("Factory notes.", "SEALED obi")["sealed"] is True
    assert "sealed" not in stated_completeness("Copy is sealed in the notes.", "ICHIE")

    listings = pd.DataFrame(
        [
            {
                "pressing_id": 498,
                "title": "MOMOE YAMAGUCHI ICHIE CBS 09SH894 1x7",
                "effective_pressing_type": "STANDARD",
                "effective_obi": None,
                "effective_insert_present": None,
                "effective_poster_present": None,
                "effective_sticker": None,
                "effective_sealed": None,
                "effective_rental": None,
            },
            {
                "pressing_id": 2,
                "title": "later copy",
                "effective_pressing_type": "STANDARD",
                "effective_obi": None,
                "effective_insert_present": None,
                "effective_poster_present": None,
                "effective_sticker": None,
                "effective_sealed": None,
                "effective_rental": None,
            },
        ]
    )
    pressings = pd.DataFrame(
        [
            {
                "id": 498,
                "discogs_master_id": 1516956,
                "release_year": 1980,
                "generation": "UNKNOWN",
                "media_type": "EP_7_INCH",
                "format_detail": 'Vinyl, 7", Single, Special Edition',
                "notes": notes,
            },
            {
                "id": 1,
                "discogs_master_id": 99,
                "release_year": 1978,
                "generation": "UNKNOWN",
                "media_type": "EP_7_INCH",
                "format_detail": 'Vinyl, 7"',
                "notes": "",
            },
            {
                "id": 2,
                "discogs_master_id": 99,
                "release_year": 1985,
                "generation": "REISSUE",
                "media_type": "EP_7_INCH",
                "format_detail": 'Vinyl, 7", Reissue',
                "notes": "",
            },
        ]
    )
    filled = apply_pressing_copy_facts(listings, pressings)
    ichie = filled.iloc[0]
    later = filled.iloc[1]
    assert ichie["effective_pressing_type"] == "FIRST_PRESSING"
    assert bool(ichie["effective_obi"]) is True
    assert bool(ichie["effective_insert_present"]) is True
    assert bool(ichie["effective_sealed"]) is False
    assert ichie["catalog_poster"] == "not_included"
    assert "obi and insert" in ichie["catalog_completeness"]
    assert "rental copy carries its own sticker" in ichie["catalog_completeness"]
    assert ichie["effective_poster_present"] is None or (
        str(ichie["effective_poster_present"]) in {"", "None", "nan"}
    )
    assert later["effective_pressing_type"] == "REISSUE"


def test_seller_report_fills_obi_and_grades_for_a_seven_inch() -> None:
    from app.collector_review_support import (
        apply_pressing_copy_facts,
        parse_seller_report,
    )

    report = parse_seller_report(
        "Jacket: E-\nDisc: E-/\nObi: NONE\nComments: Company sleeve Original"
    )
    assert report["obi"] is False
    assert report["cover"] == "E-"
    assert report["media"] == "E-"
    assert "insert" not in report
    from app.collector_review_support import stated_completeness

    titled = stated_completeness(
        "",
        "TERESA TENG BEST HITS ALBUM POLYDOR MR3037 Japan OBI INSERT POSTER VINYL LP",
    )
    assert titled["obi"] is True and titled["insert"] is True and titled["poster"] is True
    assert stated_completeness("", "POLICE REGGATTA DE BLANC US SHRINK VINYL LP")["sealed"] is True
    assert stated_completeness("", "TERESA TENG BEST 20 Japan PIN-UP GATEFOLD VINYL 2LP")["poster"] is True

    listings = pd.DataFrame(
        [
            {
                "pressing_id": 191,
                "title": "国内盤 テレサ・テン スキャンダル TAURUS 07TR1136 1x7",
                "media_type": "EP_7_INCH",
                "seller_report_text": "Obi: NONE\nJacket: E-\nDisc: E-/",
                "effective_pressing_type": "FIRST_PRESSING",
                "effective_obi": None,
                "effective_insert_present": None,
                "effective_poster_present": None,
                "effective_sticker": None,
                "effective_sealed": None,
                "effective_rental": None,
                "effective_condition_cover": None,
                "effective_condition_media": None,
            }
        ]
    )
    pressings = pd.DataFrame(
        [
            {
                "id": 191,
                "discogs_master_id": 1,
                "release_year": 1986,
                "generation": "UNKNOWN",
                "media_type": "EP_7_INCH",
                "format_detail": 'Vinyl, 7", Single',
                "notes": "",
            }
        ]
    )
    filled = apply_pressing_copy_facts(listings, pressings).iloc[0]
    assert bool(filled["effective_obi"]) is False
    assert bool(filled["effective_sealed"]) is False
    assert filled["effective_condition_cover"] == "E-"
    assert filled["effective_condition_media"] == "E-"
    assert filled["catalog_poster"] == "not_included"
    assert "no obi" in filled["catalog_completeness"]
    assert "lyric sheet" in filled["catalog_completeness"]

    rental_rows = listings.copy()
    rental_rows["title"] = "国内盤 テレサ・テン 別れの予感 TAURUS 28TR2145 1LP"
    rental_rows["seller_report_text"] = (
        "ジャケット：VG+\n帯：E\nコメント：帯 インサート\nレンタル落ち"
    )
    rental_rows["effective_sticker"] = False
    rental = apply_pressing_copy_facts(rental_rows, pressings).iloc[0]
    assert bool(rental["effective_rental"]) is True
    assert bool(rental["effective_sticker"]) is True
    assert bool(rental["effective_sealed"]) is False
    sealed_rows = listings.copy()
    sealed_rows["title"] = "POLICE REGGATTA DE BLANC US SHRINK VINYL LP"
    sealed_rows["seller_report_text"] = ""
    sealed = apply_pressing_copy_facts(sealed_rows, pressings).iloc[0]
    assert bool(sealed["effective_sealed"]) is True

    facerecords = parse_seller_report(
        "Seller Notes: “COMPANY SLEEVE ORIGINAL”\n"
        "Sleeve Grading: E-\n"
        "Obi Grading: NONE\n"
        "Record Grading: E-/"
    )
    assert facerecords["obi"] is False
    assert facerecords["cover"] == "E-"
    assert facerecords["media"] == "E-"
    assert "insert" not in facerecords
    noted = parse_seller_report(
        "Seller Notes: “JAPAN Edition with Insert and Obi”\n"
        "Sleeve Grading: E-\n"
        "OBI_Grading: VG+\n"
        "Record Grading: VG+"
    )
    assert noted["obi"] is True
    assert noted["insert"] is True
    assert noted["cover"] == "E-"
    assert noted["media"] == "VG+"

    japanese = parse_seller_report(
        "PRESS：国内盤ジャケット：VG+盤：E-/VG+/帯：E-"
        "コメント：ピンナップ ゲートフォールド商品番号：RSLS"
    )
    assert japanese["obi"] is True
    assert japanese["cover"] == "VG+"
    assert japanese["media"] == "E-"
    assert japanese["poster"] is True
    packed = parse_seller_report("ジャケット：E-盤：E-/帯：E-FMT：LP")
    assert packed["obi"] is True and packed["cover"] == "E-" and packed["media"] == "E-"
    shop = parse_seller_report(
        "ジャケット：NM盤面：VG+（薄いスレ）ライブ盤/帯付付属品無し"
    )
    assert shop["cover"] == "NM" and shop["media"] == "VG+" and shop["obi"] is True
    assert parse_seller_report("盤質：EX-")["media"] == "EX-"
    assert parse_seller_report("盤質：VG++")["media"] == "VG++"
    translated = parse_seller_report(
        "Condition Details\n"
        "Catalog number 07TR-1086\n"
        "/ Jacket: EX- Some scuffs and brown stains are visible, but overall in good condition.\n"
        "/ Record condition: EX Only minor scuffs are visible. Special notes: Company sleeve"
    )
    assert translated["cover"] == "EX-"
    assert translated["media"] == "EX"
    assert "obi" not in translated
    from app.collector_review_support import seller_condition_summary

    assert seller_condition_summary(
        "/ Jacket: EX-\n/ Record condition: EX"
    ) == "Jacket EX-, Record EX"

    lp_rows = pd.DataFrame(
        [
            {
                "pressing_id": 400,
                "title": "国内盤 テレサ テン ベスト20 TAURUS 18TR2059 2LP",
                "media_type": "LP",
                "seller_report_text": (
                    "ジャケット：VG+\n盤：E-/VG+/\n帯：E-\n"
                    "コメント：ピンナップ ゲートフォールド"
                ),
                "effective_pressing_type": "FIRST_PRESSING",
                "effective_obi": None,
                "effective_insert_present": None,
                "effective_poster_present": None,
                "effective_sticker": None,
                "effective_sealed": None,
                "effective_rental": None,
                "effective_condition_cover": None,
                "effective_condition_media": None,
            }
        ]
    )
    lp_pressings = pd.DataFrame(
        [
            {
                "id": 400,
                "discogs_master_id": 2,
                "release_year": 1984,
                "generation": "UNKNOWN",
                "media_type": "LP",
                "format_detail": "Vinyl, LP",
                "notes": "",
            }
        ]
    )
    lp = apply_pressing_copy_facts(lp_rows, lp_pressings).iloc[0]
    assert bool(lp["effective_obi"]) is True
    assert bool(lp["effective_poster_present"]) is True
    assert lp["catalog_poster"] == "included"
    assert lp["effective_condition_cover"] == "VG+"
    assert lp["effective_condition_media"] == "E-"
    assert "not part of this 7" not in lp["catalog_completeness"]

    pictured = listings.copy()
    pictured["image_url"] = "https://example.test/dr1920-sleeve.jpg"
    with_sleeve = apply_pressing_copy_facts(pictured, pressings).iloc[0]
    assert bool(with_sleeve["effective_insert_present"]) is True
    assert "lyric sheet" in with_sleeve["catalog_completeness"]

    refused = listings.copy()
    refused["image_url"] = "https://example.test/sleeve.jpg"
    refused["seller_report_text"] = "Jacket: E-\nDisc: E-\nInsert: NONE"
    no_sheet = apply_pressing_copy_facts(refused, pressings).iloc[0]
    assert bool(no_sheet["effective_insert_present"]) is False

    cd_sheet = (
        "○ケース：C 少し傷み /帯無し/インサートに日焼けによる変色\n"
        "○ディスク：B 概ね良好\n"
        "《付属品》\n・リーフレット\n"
        "レコードグレーディング\nEX+\t美品\nEX\t大変良好\nVG++\t概ね良好\n"
        "CDグレーディング\nS\t新品未開封\nA\t美品\nB\t概ね良好\nC\t少し傷み\nD\t全体的傷み"
    )
    cd_report = parse_seller_report(cd_sheet)
    assert cd_report["cover"] == "C"
    assert cd_report["media"] == "B"
    assert cd_report["obi"] is False
    assert cd_report["insert"] is True
    assert seller_condition_summary(cd_sheet) == (
        "Jewel case C, Disc B, no obi, with booklet"
    )

    cd_rows = pd.DataFrame(
        [
            {
                "pressing_id": 500,
                "title": "TERESA TENG CD TACL-2360",
                "media_type": "CD",
                "seller_report_text": cd_sheet,
                "effective_pressing_type": None,
                "effective_obi": None,
                "effective_insert_present": None,
                "effective_poster_present": None,
                "effective_sticker": None,
                "effective_sealed": None,
                "effective_rental": None,
                "effective_condition_cover": None,
                "effective_condition_media": None,
            }
        ]
    )
    cd_pressings = pd.DataFrame(
        [
            {
                "id": 500,
                "discogs_master_id": 3,
                "release_year": 1985,
                "generation": "UNKNOWN",
                "media_type": "CD",
                "format_detail": "CD",
                "notes": "",
            }
        ]
    )
    cd = apply_pressing_copy_facts(cd_rows, cd_pressings).iloc[0]
    assert cd["effective_condition_cover"] == "C"
    assert cd["effective_condition_media"] == "B"
    assert bool(cd["effective_obi"]) is False
    assert bool(cd["effective_insert_present"]) is True

    from app.collector_review_support import recent_change_facts, recent_change_mark

    mark, detail = recent_change_mark(
        [("Seller report", "2026-10-03T12:00:00Z")],
        now="2026-10-03T18:00:00Z",
    )
    assert mark == "●"
    assert detail.startswith("Seller report")
    fact_mark, fact_detail, when = recent_change_facts(
        [("Saved", "2026-10-03T12:00:00Z")],
        now="2026-10-03T18:00:00Z",
    )
    assert fact_mark == "●" and fact_detail.startswith("Saved")
    assert when is not None
    old, old_detail = recent_change_mark(
        [("Identity", "2026-01-01T00:00:00Z")],
        now="2026-10-03T18:00:00Z",
    )
    assert old == "" and old_detail == ""


def test_catalog_reference_compares_a_complete_copy_with_one_that_never_said() -> None:
    from app.collector_review_support import (
        apply_pressing_copy_facts,
        parse_seller_report,
        seller_condition_summary,
    )

    phrase = parse_seller_report("*ORIGINAL OBI INSERT*")
    assert phrase["obi"] is True
    assert phrase["insert"] is True
    assert "cover" not in phrase and "media" not in phrase
    assert parse_seller_report("Used") == {}
    assert "obi" not in parse_seller_report("Pre-Owned")
    sheet = (
        "Seller Notes: ORIGINAL OBI INSERT STAINS ON SLEEVE The obi (sash) has stains.\n"
        "Sleeve Grading: E-\n"
        "Record Grading: E-/\n"
        "Obi Grading: E-"
    )
    graded = parse_seller_report(sheet)
    assert graded["obi"] is True and graded["insert"] is True
    assert graded["cover"] == "E-" and graded["media"] == "E-"
    assert seller_condition_summary(sheet) == (
        "Jacket E-, Record E-, with obi, with lyric sheet"
    )

    blank = {
        "effective_pressing_type": "FIRST_PRESSING",
        "effective_obi": None,
        "effective_insert_present": None,
        "effective_poster_present": None,
        "effective_sticker": None,
        "effective_sealed": None,
        "effective_rental": None,
        "effective_condition_cover": None,
        "effective_condition_media": None,
    }
    listings = pd.DataFrame(
        [
            {
                **blank,
                "pressing_id": 63,
                "title": "TERESA TENG ORIGINAL BEST HITS TAURUS 28TR2092 1LP",
                "media_type": "LP",
                "seller_report_text": "",
            },
            {
                **blank,
                "pressing_id": 63,
                "title": "TERESA TENG ORIGINAL BEST HITS TAURUS 28TR2092 Japan OBI INSERT VINYL LP",
                "media_type": "LP",
                "seller_report_text": "*ORIGINAL OBI INSERT*",
            },
            {
                **blank,
                "pressing_id": 63,
                "title": "TERESA TENG ORIGINAL BEST HITS TAURUS 28TR2092 1LP",
                "media_type": "LP",
                "seller_report_text": sheet,
            },
            {
                **blank,
                "pressing_id": 63,
                "title": "TERESA TENG ORIGINAL BEST HITS TAURUS 28TR2092 1LP",
                "media_type": "LP",
                "seller_report_text": "Sleeve Grading: E-\nObi Grading: NONE\nRecord Grading: E-",
            },
        ]
    )
    pressings = pd.DataFrame(
        [
            {
                "id": 63,
                "discogs_master_id": 9,
                "release_year": 1985,
                "generation": "UNKNOWN",
                "media_type": "LP",
                "format_detail": "Vinyl, LP, Compilation",
                "notes": "",
            }
        ]
    )
    filled = apply_pressing_copy_facts(listings, pressings)
    quiet, complete, graded_copy, missing = (filled.iloc[i] for i in range(4))
    for row in (quiet, complete, graded_copy, missing):
        assert "obi and insert" in row["catalog_completeness"]
        assert "sleeve and record" in row["catalog_completeness"]
        assert row["catalog_poster"] == "not_included"
    assert quiet["copy_status"] == "Not stated"
    assert "does not say" in quiet["catalog_completeness"]
    assert complete["copy_status"] == "Complete"
    assert bool(complete["effective_obi"]) is True
    assert bool(complete["effective_insert_present"]) is True
    assert graded_copy["copy_status"] == "Complete"
    assert graded_copy["effective_condition_cover"] == "E-"
    assert graded_copy["effective_condition_media"] == "E-"
    assert missing["copy_status"] == "Missing obi; lyric sheet not stated"
    assert bool(missing["effective_obi"]) is False
    assert missing["effective_insert_present"] is None or (
        str(missing["effective_insert_present"]) in {"", "None", "nan"}
    )


def test_cassette_defaults_to_a_lyric_card_and_no_obi_or_poster() -> None:
    from app.collector_review_support import apply_pressing_copy_facts

    blank = {
        "pressing_id": 9,
        "title": "TERESA TENG 愛情更美麗 MRMT-1006",
        "media_type": "CASSETTE",
        "effective_media_type": "CASSETTE",
        "seller_report_text": "",
        "effective_pressing_type": "FIRST_PRESSING",
        "effective_obi": None,
        "effective_insert_present": None,
        "effective_poster_present": None,
        "effective_sticker": None,
        "effective_sealed": None,
        "effective_rental": None,
        "effective_condition_cover": None,
        "effective_condition_media": None,
    }
    pressings = pd.DataFrame(
        [
            {
                "id": 9,
                "discogs_master_id": 4,
                "release_year": 1978,
                "generation": "UNKNOWN",
                "media_type": "CASSETTE",
                "format_detail": "Cassette",
                "notes": "",
            }
        ]
    )
    row = apply_pressing_copy_facts(pd.DataFrame([blank]), pressings).iloc[0]
    assert bool(row["effective_obi"]) is False
    assert bool(row["effective_poster_present"]) is False
    assert bool(row["effective_insert_present"]) is True
    assert bool(row["effective_rental"]) is False
    assert bool(row["effective_sticker"]) is False
    assert "lyric card" in row["catalog_completeness"]
    assert "no obi" in row["catalog_completeness"].casefold() or "Obi and poster" in row["catalog_completeness"]

    refused = dict(blank)
    refused["seller_report_text"] = "Insert: NONE\nObi: YES"
    refused_row = apply_pressing_copy_facts(pd.DataFrame([refused]), pressings).iloc[0]
    assert bool(refused_row["effective_insert_present"]) is False
    assert bool(refused_row["effective_obi"]) is True


def test_rental_no_forces_the_sticker_to_no() -> None:
    from app.collector_review_support import apply_pressing_copy_facts

    blank = {
        "pressing_id": 9,
        "title": "TERESA TENG Original Best Hits 28TR-2092",
        "media_type": "LP",
        "effective_media_type": "LP",
        "seller_report_text": "",
        "effective_pressing_type": "FIRST_PRESSING",
        "effective_obi": True,
        "effective_insert_present": True,
        "effective_poster_present": None,
        "effective_sticker": None,
        "effective_sealed": None,
        "effective_rental": False,
        "effective_condition_cover": None,
        "effective_condition_media": None,
    }
    pressings = pd.DataFrame(
        [
            {
                "id": 9,
                "discogs_master_id": 4,
                "release_year": 1985,
                "generation": "ORIGINAL",
                "media_type": "LP",
                "format_detail": "LP",
                "notes": "",
            }
        ]
    )
    row = apply_pressing_copy_facts(pd.DataFrame([blank]), pressings).iloc[0]
    assert bool(row["effective_rental"]) is False
    assert bool(row["effective_sticker"]) is False


def test_zero_bid_auctions_leave_the_table_and_count_as_cycles() -> None:
    frame = pd.DataFrame(
        [
            {
                "listing_id": "unsold",
                "seller": "facerecords",
                "sale_type_display": "AUCTION",
                "bid_count": 0,
                "pressing_group_key": "DR1900",
                "opening_display": "2026-01-01",
                "closing_display": "2026-01-08",
            },
            {
                "listing_id": "sold",
                "seller": "facerecords",
                "sale_type_display": "AUCTION",
                "bid_count": 4,
                "pressing_group_key": "DR1900",
                "opening_display": "2026-02-01",
                "closing_display": "2026-02-08",
            },
            {
                "listing_id": "archive",
                "seller": "facerecords",
                "sale_type_display": "AUCTION",
                "bid_count": None,
                "pressing_group_key": "DR1900",
                "opening_display": "2026-03-01",
                "closing_display": "2026-03-04",
            },
            {
                "listing_id": "bin",
                "sale_type_display": "FIXED_PRICE",
                "bid_count": None,
                "pressing_group_key": "BIN",
                "opening_display": "2026-03-01",
                "closing_display": "2026-03-02",
            },
            {
                "listing_id": "relist",
                "sale_type_display": "FIXED_PRICE",
                "bid_count": 0,
                "seller": "facerecords",
                "pressing_group_key": "DR1900",
                "opening_display": "2026-01-15",
                "closing_display": "2026-01-22",
            },
            {
                "listing_id": "orphan",
                "sale_type_display": "AUCTION",
                "bid_count": 0,
                "pressing_group_key": "",
                "opening_display": "2026-04-01",
                "closing_display": None,
            },
        ]
    )
    result = omit_no_bid_auctions(frame)
    assert set(result.loc[result["no_bid_auction"], "listing_id"]) == {
        "unsold",
        "orphan",
        "relist",
    }
    sales = sales_without_no_bid_auctions(result)
    assert set(sales["listing_id"]) == {"sold", "archive", "bin"}
    sold = sales.loc[sales["listing_id"].eq("sold")].iloc[0]
    assert int(sold["listing_cycles"]) == 4
    assert int(sold["days_to_sell"]) == 38
    archive = sales.loc[sales["listing_id"].eq("archive")].iloc[0]
    assert int(archive["listing_cycles"]) == 4
    assert int(archive["days_to_sell"]) == 62
    bin_row = sales.loc[sales["listing_id"].eq("bin")].iloc[0]
    assert pd.isna(bin_row["listing_cycles"])
    assert int(result["held_out_auctions"].iloc[0]) == 3
    history = no_bid_auction_rows(result)
    assert set(history["listing_id"]) == {"orphan"}
    chart = auction_outcome_chart(
        sales.assign(media_display="EP_7_INCH", job_lot=False),
        result.loc[result["listing_id"].isin(["unsold", "orphan"])].assign(
            media_display=["LP", "CD"],
            job_lot=[False, False],
        ),
    )
    assert set(chart["Format"]) == {'7"', "LP", "CD"}
    assert int(chart.loc[chart["Format"].eq("LP"), "0-bid auctions"].iloc[0]) == 1
    assert int(chart.loc[chart["Format"].eq("CD"), "0-bid auctions"].iloc[0]) == 1


def test_use_this_keeps_the_editor_open_for_condition() -> None:
    assert listing_stays_open("buyee:1", in_filter=True, in_sales=True)
    assert listing_stays_open("buyee:1", in_filter=False, in_sales=True)
    assert not listing_stays_open("buyee:1", in_filter=False, in_sales=False)
    assert not listing_stays_open(None, in_filter=False, in_sales=True)
    source = REVIEW.read_text(encoding="utf-8")
    assert "open_records=records" in source
    assert "render_listing_editor(\n            records," in source
    condition = source.index("Condition and assessment")
    sale = source.index("Sale and collection")
    assert condition < sale
    assert "_finish_condition:" in source


def test_gripsweat_loader_skips_warehouse_item_ids() -> None:
    source = INTEGRATION.read_text(encoding="utf-8")
    assert "gripsweat_item_id" in source
    assert "item_id in warehouse_ids" in source
