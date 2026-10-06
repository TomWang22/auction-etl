"""Media, bulk-lot, and magazine scene classification."""

from __future__ import annotations

import pandas as pd

from auction_etl.classifiers.media import classify_media_details, is_job_lot
from app.collector_review_support import (
    SCENE_ALL,
    SCENE_MAGAZINES,
    SCENE_MAIN_RECORDS,
    SCENE_PRINTS,
    media_matches_scene,
)


def test_japanese_quantity_markers_imply_bulk_lot() -> None:
    assert classify_media_details(
        "昭和の歌謡曲集 LPレコード 43枚 テレサテン他"
    ).bulk_lot is True
    assert classify_media_details(
        "週刊明星 2冊 山口百恵"
    ).bulk_lot is True
    assert classify_media_details(
        "GORO 1980年2冊組◆山口百恵pin"
    ).bulk_lot is True
    assert classify_media_details(
        "GORO 1980年2冊組◆山口百恵pin"
    ).format == "MAGAZINE"
    assert classify_media_details(
        "Teresa Teng Cassette Tape 2pcs 邓丽君磁带"
    ).bulk_lot is True
    assert classify_media_details(
        "アイドル写真 箱壳 まとめ"
    ).bulk_lot is True


def test_job_lots_are_not_individual_discogs_pieces() -> None:
    cassette_mix = (
        "【カセットテープ】杏里 竹内まりや 高橋真梨子 谷村新司 など 邦楽多めテレサテン"
    )
    cd_lot = "The Best of Teresa Teng 1 3 4 CD Lot 1992 Polygram Records Polydor"
    official_va = (
        "★ V.A. / 大人のムード歌謡～男と女のラブソング集～ (5CD) "
        "DCT-27926 石原裕次郎 テレサ・テン ほか"
    )
    official_2cd = "テレサ・テン スーパーセレクション CD 2枚組 TACL-2395～6 追悼盤"
    assert classify_media_details(
        "【４０】『 カセットテープ テレサ テン 鄧麗君/全曲集 』"
    ).bulk_lot is False
    assert is_job_lot(
        "【４０】『 カセットテープ テレサ テン 鄧麗君/全曲集 』"
    ) is False
    assert classify_media_details(cassette_mix).bulk_lot is True
    assert is_job_lot(cassette_mix) is True
    assert classify_media_details(cd_lot).bulk_lot is True
    assert is_job_lot(cd_lot) is True
    assert is_job_lot(official_va) is False
    assert classify_media_details(official_va).bulk_lot is False
    assert is_job_lot(official_2cd) is False
    assert classify_media_details(official_2cd).bulk_lot is False
    assert classify_media_details(
        "「夜の乗客」テレサ・テン レコード 1枚｜LP"
    ).bulk_lot is False
    assert classify_media_details(
        "テレサ・テン スーパーセレクション CD 2枚組 TACL-2395"
    ).bulk_lot is False
    assert classify_media_details(
        "TE1430◆カセットテープ◆42本！ 昭和 歌謡 邦楽 山口百恵 工藤静香"
    ).bulk_lot is True
    assert is_job_lot(
        "TE1430◆カセットテープ◆42本！ 昭和 歌謡 邦楽 山口百恵 工藤静香"
    ) is True
    assert is_job_lot(
        "Gripsweat - ept0271 Yamaguchi Momoe EP 20-Record Set [EX-VG]"
    )
    assert is_job_lot("Gripsweat - Momoe Yamaguchi Ep Record 6-Disc Set")
    assert is_job_lot(
        "Gripsweat - Teresa Teng (鄧麗君) 一封情書, 1978, Polydor – 2427 319 Vinyl Record LP HONG KONG"
    ) is False
    assert is_job_lot(
        "Gripsweat - Teresa Teng (鄧麗君) 少年愛姑娘 LP LTLP 3018 Vintage 1973 Vinyl Record"
    ) is False
    assert classify_media_details(
        "Gripsweat - Teresa Teng (鄧麗君) 少年愛姑娘 LP LTLP 3018 Vintage 1973 Vinyl Record"
    ).format == "LP"
    assert is_job_lot("24 Vinyl Records, John Lennon POB PCS 7124, Queen The Game")
    assert is_job_lot("Gripsweat - ept0271 Yamaguchi Momoe EP 20-Record Set [EX-VG]")
    assert is_job_lot("Momoe Yamaguchi ~ 6 x Singles Set/ Japan 7\"")
    assert is_job_lot("まとめて テレサ・テン CD 4枚組 昭和歌謡") is True
    assert is_job_lot("テレサ・テン スーパーセレクション CD 2枚組 TACL-2395") is False
    assert is_job_lot("4 records by Teresa Teng") is True
    assert is_job_lot("2 records Momoe Yamaguchi") is True
    assert is_job_lot("1 record by Teresa Teng") is False


def test_weekly_magazine_is_not_main_record_media() -> None:
    media = classify_media_details(
        "週刊実話 令和3年7月29日号 山口百恵 桜田淳子"
    )
    assert media.format == "MAGAZINE"
    assert media_matches_scene(media.format, SCENE_MAIN_RECORDS) is False
    assert media_matches_scene(media.format, SCENE_MAGAZINES) is True


def test_named_kayo_magazines_and_autograph_prints_leave_all_music() -> None:
    magazine = classify_media_details(
        "○プレイファイブ 1977年12月号 小柳ルミ子/テレサ・テン"
    )
    penthouse = classify_media_details(
        "PENTHOUSE ペントハウス 日本版 1984年4月号"
    )
    autograph = classify_media_details(
        "テレサ・テン 欧陽菲菲 直筆サイン色紙"
    )
    assert magazine.format == "MAGAZINE"
    assert penthouse.format == "MAGAZINE"
    assert autograph.format == "PRINT"
    assert media_matches_scene(magazine.format, SCENE_MAIN_RECORDS) is False
    assert media_matches_scene(autograph.format, SCENE_PRINTS) is True


def test_video_and_empty_media_are_not_main_records() -> None:
    from app.collector_review_support import media_matches_scene as matches

    assert matches("DVD", SCENE_MAIN_RECORDS) is False
    assert matches("LASERDISC", SCENE_MAIN_RECORDS) is False
    assert matches("STAMP", SCENE_MAIN_RECORDS) is False
    assert matches("", SCENE_MAIN_RECORDS) is True
    assert matches("LP", SCENE_MAIN_RECORDS) is True
    assert matches("CD_SINGLE_8CM", SCENE_MAIN_RECORDS) is True
    assert matches("CASSETTE", SCENE_MAIN_RECORDS) is True


def test_glued_lp_code_and_saved_choice_land_on_the_lp_chip() -> None:
    from app.collector_review_support import (
        MEDIA_GROUP_LP,
        MEDIA_GROUP_SEVEN,
        automatic_catalog,
        automatic_media_type,
        media_matches_group,
        place_review_media,
        review_media_slot,
    )

    title = "LP0847☆台湾/Yeu Jow「鄧麗君 テレサ・テン / 鳳陽花鼓 / AWK-003-A」"
    assert classify_media_details(title).format == "LP"
    assert classify_media_details("鳳陽花鼓 AWK-003-A").format == "LP"
    assert classify_media_details("山口百恵 15才 SOLL-114").format == "LP"
    assert classify_media_details(
        "Gripsweat - Momoe Yamaguchi Budokan 3xLP 70AH-1141"
    ).format == "LP"
    assert classify_media_details(
        "8 Vintage Hong Kong Cantopop Cassettes Teresa Teng"
    ).format == "CASSETTE"
    assert classify_media_details(
        "Anita Mui Music Collection 3 Audio CDs"
    ).format == "CD"
    assert classify_media_details("Momoe Yamaguchi 09SH 894").format == "EP_7_INCH"
    slot = review_media_slot(None, title, None)
    assert slot == "LP"
    assert media_matches_group(slot, MEDIA_GROUP_LP) is True
    row = {
        "title": title,
        "catalog_number": "LP-0847",
        "effective_catalog_number": "LP-0847",
        "media_type": None,
        "effective_media_type": None,
    }
    options = ("Automatic / unset", "LP", "EP_7_INCH", "CD", "CASSETTE")
    assert automatic_media_type(row, options) == "LP"
    assert automatic_catalog(row) == "AWK-003"
    saved = review_media_slot("EP_7_INCH", title, "LP")
    assert saved == "EP_7_INCH"
    assert media_matches_group(saved, MEDIA_GROUP_SEVEN) is True
    assert media_matches_group(saved, MEDIA_GROUP_LP) is False
    assert is_job_lot(title) is False
    placed = place_review_media(
        pd.DataFrame(
            [
                {
                    "title": title,
                    "manual_media_type": None,
                    "effective_media_type": None,
                    "media_type": None,
                    "bulk_lot": True,
                    "manual_bulk_lot": None,
                }
            ]
        )
    )
    assert placed.loc[0, "media_display"] == "LP"
    assert bool(placed.loc[0, "job_lot"]) is False
    assert media_matches_group(
        placed.loc[0, "media_display"],
        MEDIA_GROUP_LP,
        job_lot=bool(placed.loc[0, "job_lot"]),
    ) is True


def test_counted_records_open_as_a_bulk_lot() -> None:
    from app.collector_review_support import (
        automatic_media_type,
        condition_grade_options,
        condition_profile,
        place_review_media,
    )

    title = "4 records by Teresa Teng"
    options = (
        "Automatic / unset",
        "LP",
        "EP_7_INCH",
        "CD",
        "CASSETTE",
        "BULK_LOT",
    )
    assert automatic_media_type(
        {
            "title": title,
            "manual_bulk_lot": None,
            "media_type": None,
            "effective_media_type": None,
        },
        options,
    ) == "BULK_LOT"
    placed = place_review_media(
        pd.DataFrame(
            [
                {
                    "title": title,
                    "manual_media_type": None,
                    "effective_media_type": None,
                    "media_type": None,
                    "manual_bulk_lot": None,
                }
            ]
        )
    )
    assert placed.loc[0, "media_display"] == "BULK_LOT"
    assert bool(placed.loc[0, "job_lot"]) is True
    assert condition_profile("CD")["cover_label"] == "Jewel case"
    assert condition_profile("CD")["scale"] == "both"
    assert condition_profile("CASSETTE")["media_label"] == "Tape"
    assert condition_profile("CASSETTE")["cover_label"] == "Shell"
    assert condition_profile("EP_7_INCH")["cover_label"] == "Sleeve"
    assert condition_profile("LP")["cover_label"] == "Jacket"
    assert condition_profile("LP")["scale"] == "vinyl"
    assert condition_profile("BULK_LOT")["kind"] == "lot"
    assert condition_profile("BULK_LOT")["cover_label"] == ""
    cd = condition_profile("CD")
    assert cd["insert_label"] == "Booklet"
    assert cd["show_poster"] == "no"
    assert cd["show_obi"] == "yes"
    ep = condition_profile("EP_7_INCH")
    assert ep["insert_label"] == "Insert"
    assert ep["show_obi"] == "yes"
    assert ep["show_poster"] == "no"
    lp = condition_profile("LP")
    assert lp["show_poster"] == "yes"
    assert lp["poster_label"] == "Poster / pin-up"
    cassette = condition_profile("CASSETTE")
    assert cassette["show_obi"] == "no"
    assert cassette["show_poster"] == "no"
    assert cassette["insert_label"] == "Lyric card"
    assert cassette["scale"] == "both"
    cassette_grades = condition_grade_options("both")
    assert "S" in cassette_grades and "F" in cassette_grades and "G" in cassette_grades
    assert "VG+" in cassette_grades
    cd_grades = condition_grade_options(condition_profile("CD")["scale"])
    assert "S" in cd_grades and "F" in cd_grades and "G" in cd_grades
    letter_grades = condition_grade_options("letter")
    assert "F" not in letter_grades and "S" in letter_grades
    lp_grades = condition_grade_options("vinyl")
    assert "F" in lp_grades and "S" not in lp_grades


def test_a_photo_leaves_the_unmatched_record_pile() -> None:
    from app.collector_review_support import apply_local_identity

    frame = apply_local_identity(
        pd.DataFrame(
            [
                {
                    "title": "TERESA TENG #32 8X10 PHOTO",
                    "identity_status_display": "Unmatched",
                    "media_display": "PHOTO",
                    "catalog_display": "",
                    "job_lot": False,
                },
                {
                    "title": "Teresa Teng Best Hits LP",
                    "identity_status_display": "Unmatched",
                    "media_display": "LP",
                    "catalog_display": "",
                    "job_lot": False,
                },
            ]
        )
    )
    assert frame.loc[0, "identity_status_display"] == "Not a record"
    assert frame.loc[1, "identity_status_display"] == "Unmatched"


def test_obi_is_only_a_japanese_pressing() -> None:
    from app.collector_review_support import (
        apply_pressing_copy_facts,
        market_catalog_parts,
        obi_for_region,
        obi_label_for_region,
        obi_value_for_region,
    )

    assert obi_for_region("Japan") is True
    assert obi_for_region("Hong Kong") is False
    assert obi_for_region("Taiwan") is False
    assert obi_for_region("") is False
    assert obi_label_for_region("Yes", "Japan") == "Yes"
    assert obi_label_for_region("Yes", "Hong Kong") == "No"
    assert obi_label_for_region("Yes", "Taiwan") == "No"
    assert obi_label_for_region("Yes", "") == "No"
    assert obi_value_for_region(True, "Japan") is True
    assert obi_value_for_region(True, "Hong Kong") is False
    assert obi_value_for_region(True, "Singapore") is False
    assert obi_value_for_region(True, "") is True
    assert market_catalog_parts({"obi", "insert"}, "Japan") == {"obi", "insert"}
    assert market_catalog_parts({"obi", "insert"}, "Hong Kong") == {"insert"}
    assert market_catalog_parts({"obi", "insert"}, "") == {"obi", "insert"}
    rows = pd.DataFrame(
        [
            {
                "pressing_id": 15,
                "title": "鄧麗君 15週年",
                "media_type": "LP",
                "effective_region": "Hong Kong",
                "seller_report_text": "帯：E-\nジャケット：VG",
                "effective_pressing_type": "FIRST_PRESSING",
                "effective_obi": None,
                "effective_insert_present": None,
                "effective_poster_present": None,
                "effective_sticker": None,
                "effective_sealed": None,
                "effective_rental": None,
            }
        ]
    )
    pressings = pd.DataFrame(
        [
            {
                "id": 15,
                "discogs_master_id": 15,
                "release_year": 1984,
                "generation": "UNKNOWN",
                "media_type": "LP",
                "format_detail": "Vinyl, LP",
                "notes": "obi and insert",
            }
        ]
    )
    filled = apply_pressing_copy_facts(rows, pressings).iloc[0]
    assert bool(filled["effective_obi"]) is False
    assert "obi" not in str(filled["catalog_completeness"]).casefold()


def test_factory_pack_says_what_complete_means() -> None:
    from app.collector_review_support import factory_pack_sentence

    full = factory_pack_sentence("Yes", "Yes", "Pin-up is the poster")
    assert "obi, an insert, and a pin-up" in full
    assert "Complete means the obi, the insert, and the pin-up" in full

    obi_insert = factory_pack_sentence("Yes", "Yes", "No")
    assert "the obi and the insert" in obi_insert
    assert "no pin-up" in obi_insert

    insert_only = factory_pack_sentence("Yes", "Insert only", "Pin-up is the poster")
    assert "insert only" in insert_only
    assert "no obi and no pin-up" in insert_only

    pinup = factory_pack_sentence("Yes", "Pin-up is the insert", "No")
    assert "pin-up that is the insert" in pinup
    assert "no separate poster" in pinup
    assert "an obi" in pinup

    pinup_plain = factory_pack_sentence("No", "Pin-up is the insert", "No")
    assert "no obi" in pinup_plain

    factory = factory_pack_sentence("No", "Factory no insert", "No")
    assert "never included an insert" in factory
    assert "sleeve and the record" in factory

    factory_pin = factory_pack_sentence("Yes", "Factory no insert", "Pin-up is the poster")
    assert "never included an insert" in factory_pin
    assert "the obi and the pin-up" in factory_pin

    missing = factory_pack_sentence("Yes", "No", "No")
    assert "missing" in missing
    assert "Factory no insert" in missing


def test_pinup_in_the_insert_stays_with_the_notes() -> None:
    from app.collector_review_support import (
        FACTORY_NO_INSERT_NOTE,
        INSERT_ONLY_NOTE,
        notes_insert_fact,
        notes_pinup_is_insert,
        notes_with_insert_fact,
        notes_with_pinup,
        notes_without_insert_fact,
        notes_without_pinup,
    )

    stored = notes_with_pinup("obi is worn", True)
    assert notes_pinup_is_insert(stored) is True
    assert notes_without_pinup(stored) == "obi is worn"
    assert notes_with_pinup(stored, False) == "obi is worn"
    assert notes_pinup_is_insert(notes_with_pinup("", True)) is True
    insert_only = notes_with_insert_fact("obi is worn", INSERT_ONLY_NOTE)
    assert notes_insert_fact(insert_only) == INSERT_ONLY_NOTE
    assert notes_without_insert_fact(insert_only) == "obi is worn"
    factory = notes_with_insert_fact(insert_only, FACTORY_NO_INSERT_NOTE)
    assert notes_insert_fact(factory) == FACTORY_NO_INSERT_NOTE
    assert INSERT_ONLY_NOTE not in factory
    assert notes_with_insert_fact(factory, None) == "obi is worn"


def test_album_titled_magazine_stays_lp() -> None:
    media = classify_media_details(
        "The Partridge Family Sound Magazine Lp"
    )
    assert media.format == "LP"
    assert media_matches_scene(media.format, SCENE_MAIN_RECORDS) is True
    shakuhachi = classify_media_details(
        "GORO YAMAGUCHI WORLD OF SHAKUHACHI DENON WP7008 1LP"
    )
    assert shakuhachi.format == "LP"


def test_live_user_facing_titles_classify() -> None:
    assert classify_media_details(
        "Diana Ross My Old Piano / Give Up 12''"
    ).format == "SINGLE_12_INCH"
    assert classify_media_details(
        "テレサ テン LPアナログ盤 別れの予感"
    ).format == "LP"
    assert classify_media_details(
        "2枚組CD●山口百恵 / 33 SINGLES MOMOE 60DH51~2"
    ).format == "CD"
    assert classify_media_details(
        "テレサ・テン/全曲集/38TT-1178"
    ).format == "CASSETTE"
    assert classify_media_details(
        "Taiwan Stamp-2015 S621-Teresa Teng鄧麗君"
    ).format == "STAMP"
    assert classify_media_details(
        "TERESA TENG TOKINO NAGARENI MIWO MAKASE TAURUS 07TR1115 7"
    ).format == "EP_7_INCH"
    assert classify_media_details(
        'Teresa Teng Kuko Airport DR 1865 7" Vinyl Single Japan Pressing 1974 45 RPM'
    ).format == "EP_7_INCH"
    assert classify_media_details(
        "12'' Singles Vol. 8 Various Artist Lp (Foreign Pressing)"
    ).format == "LP"
    poster = classify_media_details(
        "#3981,TERESA TENG,11X17 POSTER SIZE PHOTO"
    )
    assert poster.format == "PRINT"
    assert classify_media_details(
        "TERESA TENG #32,taiwan,chinese singer,tang,deng,8X10 PHOTO"
    ).format == "PHOTO"
    assert poster.bulk_lot is False
    assert classify_media_details(
        "楽譜[ギター弾き語りで楽しむ 演歌の花道50 タブ譜で弾ける簡単ソロアレンジ付き]"
    ).format == "SHEET_MUSIC"
    assert classify_media_details(
        "テレサ・テン カセットテープ 鄧麗君 酒醉的探戈 中国語盤 28TT-1134"
    ).format == "CASSETTE"
    assert classify_media_details(
        "テレサ・テン/償還(つぐない)/28TT-1057"
    ).format == "CASSETTE"
    assert classify_media_details(
        "シール帯【テレサ テン 全曲集】H32P-20030 51223G MANUFACTURED BY SANYO 鄧麗君"
    ).format == "CD"
    assert classify_media_details(
        "テレサ・テン/鄧麗君 カバー・ベスト・コレクション POCH-1782 見本品"
    ).format == "CD"


def test_photobook_and_print_are_separate_from_records() -> None:
    photobook = classify_media_details("山口百恵 写真集 篠山紀信")
    print_item = classify_media_details("白黒写真 １枚 1974.11 テレサテン")
    still = classify_media_details(
        "P0122 テレサ・テン スチール写真(6つ切り) 朝日新聞 掲載用 1987年前後"
    )
    assert photobook.format == "PHOTOBOOK"
    assert print_item.format == "PRINT"
    assert still.format == "PRINT"
    assert media_matches_scene(photobook.format, SCENE_PRINTS) is True
    assert media_matches_scene("PHOTO", SCENE_PRINTS) is True
    from app.collector_review_support import condition_profile

    photo = condition_profile("PHOTO")
    assert photo["kind"] == "paper"
    assert photo["show_obi"] == "no"
    assert photo["cover_label"] == ""
    assert media_matches_scene("LP", SCENE_PRINTS) is False
    assert media_matches_scene("LP", SCENE_ALL) is True
    assert media_matches_scene("MAGAZINE", SCENE_ALL) is True


def test_momoe_singles_classify_as_seven_inch() -> None:
    assert classify_media_details(
        "Gripsweat - Momoe Yamaguchi 31th Single Sayonara no Mukougawa Vinyl Record 1980"
    ).format == "EP_7_INCH"
    assert classify_media_details(
        "山口百恵 シングル レコード SOLB-89 禁じられた遊び"
    ).format == "EP_7_INCH"
    assert classify_media_details(
        "山口百恵 シングル ベスト コレクション LP"
    ).format == "LP"
    assert classify_media_details(
        "テレサ・テン(鄧麗君)/ Best Songs ～Single Collection"
    ).format == "CD"


def test_obi_and_domestic_do_not_turn_cds_or_sevens_into_lp() -> None:
    assert classify_media_details(
        "最終値下げ 帯付き テレサ・テン スーパー・ベスト・コレクション POCH-1761"
    ).format == "CD"
    assert classify_media_details(
        "国内盤 テレサ・テン 夜の乗客 YORU NO JOKYAKU POLYDOR DR1944 1x7"
    ).format == "EP_7_INCH"


def test_lp_compilation_is_not_seven_inch_because_of_45_rpm() -> None:
    details = classify_media_details(
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, Compilation, Numbered, Taiwan"
    )
    assert details.format == "LP"


def test_twelve_inch_albums_are_not_maxi_singles() -> None:
    assert classify_media_details(
        '1980 Polydor Chinese Record【Teresa Teng 鄧麗君】在水一方 12" LP with lyrics'
    ).format == "LP"
    assert classify_media_details(
        "Gripsweat - ANITA MUI 梅艷芳 original 1985 bad girl 12' VINYL RECORD LP HONG KONG"
    ).format == "LP"
    assert classify_media_details(
        "Gripsweat - Rare Anita Mui In Concert '90 12\" Vinyl Record 2LP 梅艷芳"
    ).format == "LP"
    assert classify_media_details(
        "☆鄧麗君☆時の流れに身をまかせ 希少国内非売品 廃盤12インチ MAXI 45RPM"
    ).format == "SINGLE_12_INCH"
    assert classify_media_details(
        "Milli Vanilli Blame It On The Rain 12''"
    ).format == "SINGLE_12_INCH"


def test_karaoke_toys_and_songbooks_leave_all_music() -> None:
    from app.collector_review_support import (
        MEDIA_GROUP_ALL_MUSIC,
        media_matches_group,
    )

    chip = classify_media_details(
        "クラリオンシンセサイザーカラオケソフトチップ ＳＶＣ-11"
    )
    pianist = classify_media_details(
        "グランドピアニスト ホワイト SEGA TOYS Grand Pianist"
    )
    songbook = classify_media_details(
        "old Hong Kong Hit Tops #9 English song book Teresa Teng Sam Hui cover"
    )
    vinyl = classify_media_details(
        "Gripsweat - Teresa Teng鄧麗君-漫步人生路 1983 台版 附拉斯維加斯特刊歌本 黑膠"
    )
    assert chip.format == "TOY"
    assert pianist.format == "TOY"
    assert songbook.format == "SHEET_MUSIC"
    assert vinyl.format == "LP"
    assert classify_media_details(
        "鄧麗君/初次嚐到寂寞/3225 374"
    ).format == "CASSETTE"
    assert media_matches_group(chip.format, MEDIA_GROUP_ALL_MUSIC) is False
    assert media_matches_group(songbook.format, MEDIA_GROUP_ALL_MUSIC) is False
    assert media_matches_group(vinyl.format, MEDIA_GROUP_ALL_MUSIC) is True
