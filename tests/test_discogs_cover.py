"""Cover-hash matching labels pressings from listing photos."""

from __future__ import annotations

from PIL import Image

from auction_etl.services.discogs_cover import (
    average_hash,
    choose_cover_hit,
    choose_cover_match,
    hamming_distance,
)
from auction_etl.services.discogs_identity import parse_search_hits


def _block_image(left: tuple[int, int, int], right: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (64, 64), left)
    for x in range(32, 64):
        for y in range(64):
            image.putpixel((x, y), right)
    return image


def test_cool_listing_rejects_warm_concert_cover() -> None:
    from auction_etl.services.discogs_cover import (
        image_color_side,
        listing_color_side,
    )

    cool = Image.new("RGB", (64, 64), (40, 90, 140))
    warm = Image.new("RGB", (64, 64), (180, 70, 40))
    table = Image.new("RGB", (128, 96), (250, 250, 250))
    table.paste(cool, (4, 4))
    assert image_color_side(cool) == "cool"
    assert image_color_side(warm) == "warm"
    assert listing_color_side(table) == "cool"


def test_layout_hash_keeps_obi_and_footer_text() -> None:
    from auction_etl.services.discogs_cover import layout_hash

    ssar = Image.new("RGB", (64, 64), (20, 80, 180))
    for x in range(8):
        for y in range(64):
            ssar.putpixel((x, y), (40, 180, 220))
    for y in range(52, 64):
        for x in range(64):
            ssar.putpixel((x, y), (240, 240, 240))
    original = Image.new("RGB", (64, 64), (180, 80, 20))
    listing = ssar.copy()
    assert hamming_distance(layout_hash(listing), layout_hash(ssar)) < hamming_distance(
        layout_hash(listing),
        layout_hash(original),
    )
    listing = average_hash(_block_image((20, 80, 160), (240, 240, 240)))
    match = average_hash(_block_image((24, 84, 155), (230, 230, 230)))
    other = average_hash(_block_image((200, 30, 30), (20, 20, 20)))
    assert hamming_distance(listing, match) < hamming_distance(listing, other)
    assert choose_cover_match(listing, [("keep", match), ("drop", other)]) == "keep"


def test_two_close_covers_stay_unresolved() -> None:
    listing = 0
    near = 0b0011
    other_near = 0b1100
    assert hamming_distance(listing, near) == 2
    assert hamming_distance(listing, other_near) == 2
    assert choose_cover_match(listing, [("a", near), ("b", other_near)]) is None


def test_same_sleeve_hash_picks_one_pressing() -> None:
    listing = average_hash(_block_image((20, 80, 160), (240, 240, 240)))
    same = average_hash(_block_image((20, 80, 160), (240, 240, 240)))
    assert choose_cover_match(listing, [("a", same), ("b", same)]) == "a"


def test_cover_hit_picks_matching_shortlist_release() -> None:
    listing = average_hash(_block_image((20, 80, 160), (240, 240, 240)))
    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "Teresa Teng - 淡淡幽情",
                "catno": "SC-6101",
                "thumb": "https://example.invalid/a.jpg",
            },
            {
                "id": 2,
                "type": "release",
                "title": "Random - Other",
                "catno": "XX-1",
                "thumb": "https://example.invalid/b.jpg",
            },
        ]
    )
    chosen = choose_cover_hit(
        listing,
        hits,
        (
            average_hash(_block_image((20, 80, 160), (240, 240, 240))),
            average_hash(_block_image((200, 30, 30), (20, 20, 20))),
        ),
    )
    assert chosen is not None
    assert chosen.discogs_id == 1
    assert chosen.catno == "SC-6101"


def test_rank_cover_hits_keeps_close_sleeves_in_distance_order() -> None:
    from auction_etl.services.discogs_cover import rank_cover_hits

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "鄧麗君* - 15週年",
                "catno": "817 131-1",
                "thumb": "https://example.invalid/a.jpg",
            },
            {
                "id": 2,
                "type": "release",
                "title": "鄧麗君* - 水上人",
                "catno": "2427 307",
                "thumb": "https://example.invalid/b.jpg",
            },
            {
                "id": 3,
                "type": "release",
                "title": "鄧麗君* - Other",
                "catno": "XX-1",
                "thumb": "https://example.invalid/c.jpg",
            },
        ]
    )
    listing = 0
    ranked = rank_cover_hits(
        (listing,),
        hits,
        (0b1111111111111111, 0, 0b1),
        max_distance=8,
    )
    assert [hit.discogs_id for hit in ranked] == [2, 3]


def test_search_hits_prefer_full_cover_image() -> None:
    hit = parse_search_hits(
        [
            {
                "id": 9,
                "type": "release",
                "title": "Teresa Teng - 淡淡幽情",
                "thumb": "https://example.invalid/thumb.jpg",
                "cover_image": "https://example.invalid/full.jpg",
            }
        ]
    )[0]
    assert hit.thumb_url == "https://example.invalid/full.jpg"


def test_known_sleeve_reuse_requires_album_or_catalog() -> None:
    from auction_etl.services.discogs_fill import _pressing_agrees_with_listing

    row = {
        "title": "テレサ・テン/鄧麗君 TERESA TENG カバー・ベスト・コレクション POCH-1782",
        "catalog_number": "POCH-1782",
        "artist": None,
    }
    wrong = {
        "display_artist": "鄧麗君",
        "display_title": "淡淡幽情",
        "catalog_number": "TACL-2400",
    }
    right = {
        "display_artist": "鄧麗君",
        "display_title": "カバー・ベスト・コレクション",
        "catalog_number": "POCH-1782",
    }
    named = {
        "display_artist": "鄧麗君",
        "display_title": "淡淡幽情",
        "catalog_number": "SC-6101",
    }
    named_row = {
        "title": "【CD/taurus盤】テレサ・テン(鄧麗君) / 淡淡幽情",
        "catalog_number": None,
        "artist": None,
    }
    stolen = {
        "title": "Lin Zhimei What is Fate Lp Original Hong Kong",
        "catalog_number": "WB 46 227",
        "artist": None,
    }
    soundtrack = {
        "display_artist": "Alan Price",
        "display_title": "O Lucky Man! - Original Soundtrack",
        "catalog_number": "WB 46 227",
    }
    assert _pressing_agrees_with_listing(row, wrong) is False
    assert _pressing_agrees_with_listing(row, right) is True
    assert _pressing_agrees_with_listing(named_row, named) is True
    assert _pressing_agrees_with_listing(stolen, soundtrack) is False
    same_album_wrong_catno = {
        "display_artist": "鄧麗君",
        "display_title": "淡淡幽情",
        "catalog_number": "2427 377",
    }
    sc_row = {
        "title": "【SC-6101 2A2 TO】 テレサ・テン 鄧麗君 / 淡淡幽情 帯付き",
        "catalog_number": None,
        "artist": None,
    }
    dual = {
        "title": "Teresa Teng Polydor MRM 1003 2488 447 Vinyl LP",
        "catalog_number": None,
        "artist": None,
    }
    dual_pressing = {
        "display_artist": "鄧麗君",
        "display_title": "絲絲小雨",
        "catalog_number": "MRM 1003",
    }
    rock = {
        "title": "Anita Mui Come On Rock Cantopop 1988 Hong Kong",
        "catalog_number": None,
        "artist": None,
    }
    self_titled = {
        "display_artist": "Anita Mui",
        "display_title": "Anita Mui",
        "catalog_number": "CAL-04-1109",
    }
    hits_row = {
        "title": "Teresa Teng Greatest Hits Vol. 2 LP Polydor",
        "catalog_number": None,
        "artist": None,
    }
    hits_pressing = {
        "display_artist": "鄧麗君",
        "display_title": "Greatest Hits Vol.2",
        "catalog_number": "MRM 1005",
    }
    bilingual = {
        "title": "CDo-3540＜帯付＞山口百恵 / ヒットコレクションVol.1",
        "catalog_number": None,
        "artist": None,
    }
    bilingual_wrong = {
        "display_artist": "山口百恵",
        "display_title": "Hit Collection Vol. 1 = ヒットコレクション Vol. 1",
        "catalog_number": "DQCL 5103",
    }
    bilingual_right = {
        "display_artist": "山口百恵",
        "display_title": "Hit Collection Vol. 1 = ヒットコレクション Vol. 1",
        "catalog_number": "CDO-3540",
    }
    assert _pressing_agrees_with_listing(sc_row, same_album_wrong_catno) is False
    assert _pressing_agrees_with_listing(dual, dual_pressing) is True
    assert _pressing_agrees_with_listing(rock, self_titled) is False
    assert _pressing_agrees_with_listing(hits_row, hits_pressing) is True
    assert _pressing_agrees_with_listing(bilingual, bilingual_wrong) is False
    assert _pressing_agrees_with_listing(bilingual, bilingual_right) is True
    shortened = {
        "title": "LP / テレサ・テン / ベスト・ヒット / 帯付 [5184RZ]",
        "catalog_number": None,
        "artist": "Teresa Teng",
    }
    best_hit_album = {
        "display_artist": "Teresa Teng",
        "display_title": "Teresa Teng = テレサ・テン* = 鄧麗君* - ベスト・ヒット・アルバム",
        "catalog_number": "MR 3037",
    }
    other_best = {
        "display_artist": "Teresa Teng",
        "display_title": "Teresa Teng - 全曲集",
        "catalog_number": "28TT-1111",
    }
    assert _pressing_agrees_with_listing(shortened, best_hit_album) is False
    named_album = {
        **shortened,
        "title": "LP / テレサ・テン / ベスト・ヒット・アルバム / 帯付",
    }
    assert _pressing_agrees_with_listing(named_album, best_hit_album) is True
    original_best = {
        "display_artist": "Teresa Teng",
        "display_title": "Original Best Hits",
        "catalog_number": "28TR-2092",
    }
    assert _pressing_agrees_with_listing(shortened, original_best) is True
    assert _pressing_agrees_with_listing(shortened, other_best) is False


def test_shortlist_accepts_a_farther_unique_sleeve() -> None:
    listing = average_hash(_block_image((20, 80, 160), (240, 240, 240)))
    near = average_hash(_block_image((40, 90, 140), (220, 220, 220)))
    far = average_hash(_block_image((200, 30, 30), (20, 20, 20)))
    assert choose_cover_match(
        listing,
        [("keep", near), ("drop", far)],
        max_distance=72,
        unique_gap=8,
    ) == "keep"


def test_listing_cover_hashes_see_left_sleeve() -> None:
    from auction_etl.services.discogs_cover import (
        choose_cover_hit_multi,
        listing_cover_hashes,
    )

    sleeve = _block_image((20, 80, 160), (240, 240, 240))
    vinyl = _block_image((200, 30, 30), (20, 20, 20))
    collage = Image.new("RGB", (128, 64), (0, 0, 0))
    collage.paste(sleeve, (0, 0))
    collage.paste(vinyl, (64, 0))
    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "Teresa Teng - つぐない",
                "catno": "28TR-2032",
                "thumb": "https://example.invalid/a.jpg",
            },
            {
                "id": 2,
                "type": "release",
                "title": "Teresa Teng - つぐない",
                "catno": "07TR-1056",
                "thumb": "https://example.invalid/b.jpg",
            },
        ]
    )
    chosen = choose_cover_hit_multi(
        listing_cover_hashes(collage),
        hits,
        (average_hash(sleeve), average_hash(vinyl)),
    )
    assert chosen is not None
    assert chosen.catno == "28TR-2032"


def test_catalog_search_puts_the_matching_cover_ahead_of_the_pile() -> None:
    from auction_etl.services.discogs_cover import rank_catalog_covers

    listing = _block_image((20, 80, 160), (240, 240, 240))
    other = _block_image((200, 30, 30), (20, 20, 20))
    ranked = rank_catalog_covers(
        [
            {"id": 1, "thumb": "other", "catno": "SSAR-001"},
            {"id": 2, "thumb": "same", "catno": "SSAR-018"},
            {"id": 3, "thumb": "", "catno": "SSAR-099"},
        ],
        images={"other": other, "same": listing},
        listing_image=listing,
    )
    assert [hit["id"] for hit in ranked] == [2, 1, 3]
    assert ranked[0]["photo_same"] is True
    assert ranked[1].get("photo_same") is not True
    assert "photo_distance" not in ranked[2]


def test_a_different_color_portrait_is_not_the_same_cover() -> None:
    from auction_etl.services.discogs_cover import rank_catalog_covers

    def portrait(background: tuple[int, int, int], face: tuple[int, int, int]) -> Image.Image:
        image = Image.new("RGB", (64, 64), background)
        for x in range(20, 44):
            for y in range(12, 48):
                image.putpixel((x, y), face)
        return image

    dark = portrait((15, 18, 28), (70, 75, 90))
    white = portrait((236, 232, 226), (250, 248, 244))
    red = portrait((120, 20, 30), (190, 40, 45))
    ranked = rank_catalog_covers(
        [
            {"id": 1, "thumb": "white", "catno": "CAL-04-1"},
            {"id": 2, "thumb": "red", "catno": "CAL-04-1"},
            {"id": 3, "thumb": "dark", "catno": "CAL-04-1"},
        ],
        images={"white": white, "red": red, "dark": dark},
        listing_image=dark,
    )
    assert ranked[0]["id"] == 3
    assert ranked[0]["photo_same"] is True
    assert all(hit.get("photo_same") is not True for hit in ranked[1:])
    assert {hit["id"] for hit in ranked} == {1, 2, 3}


def test_listing_agrees_with_matching_sleeve_not_a_different_cover() -> None:
    from auction_etl.services.discogs_cover import listing_agrees_with_cover

    sleeve = _block_image((20, 80, 160), (240, 240, 240))
    other = _block_image((200, 30, 30), (20, 20, 20))
    collage = Image.new("RGB", (128, 64), (0, 0, 0))
    collage.paste(sleeve, (0, 0))
    collage.paste(other, (64, 0))
    assert listing_agrees_with_cover(collage, sleeve) is True
    assert listing_agrees_with_cover(sleeve, other) is False
