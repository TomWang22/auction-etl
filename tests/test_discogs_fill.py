"""Discogs fill search order: catno+artist, catno, then title query."""

from __future__ import annotations

import re

import httpx
import pytest

from auction_etl.services.discogs_client import DiscogsClient, DiscogsRateLimitError
from auction_etl.services.discogs_fill import (
    IdentityFillStats,
    leftover_printed_catalog_missing_discogs,
    leftover_restore_shortlist,
    leftover_row_needs_research,
    leftover_unmatched_empty_shortlist,
    _hash_shortlist_covers,
    _hit_matches_title_tokens,
    _local_album_search_hits,
    _local_hits_cover_listing,
    _search_hits_for_row,
    _title_query,
    _title_queries,
    _unique_review_candidate,
)
from auction_etl.services.discogs_identity import (
    SearchHit,
    classify_search_hits,
    discogs_format_label,
    fold_catalog,
    parse_search_hits,
    query_looks_like_catalog,
    search_user_catalog,
)


SOLL_HIT = parse_search_hits(
    [
        {
            "id": 10320765,
            "type": "release",
            "title": "山口百恵* - 15才",
            "catno": "SOLL-114",
            "year": "1974",
            "country": "Japan",
            "format": ["Vinyl", "LP", "Album", "Stereo"],
            "label": ["CBS/Sony"],
            "thumb": "https://example.invalid/thumb.jpg",
            "uri": "/release/10320765",
        }
    ]
)[0]


class FakeDiscogs:
    def __init__(self, responses: list[tuple[SearchHit, ...]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str | None]] = []

    def search_releases(
        self,
        *,
        catno: str | None = None,
        artist: str | None = None,
        query: str | None = None,
        title: str | None = None,
        format_name: str | None = "Vinyl",
    ) -> tuple[SearchHit, ...]:
        self.calls.append(
            {
                "catno": catno,
                "artist": artist,
                "query": query,
                "title": title,
                "format_name": format_name,
            }
        )
        if not self.responses:
            return ()
        return self.responses.pop(0)


def test_catno_search_includes_artist_and_format() -> None:
    client = FakeDiscogs([(SOLL_HIT,)])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={"artist": "Momoe Yamaguchi", "title": "15 sai SOLL-114"},
        token="SOLL-114",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == (SOLL_HIT,)
    assert require_token is True
    assert stats.searched >= 1
    assert client.calls[0] == {
        "catno": "SOLL-114",
        "artist": "Momoe Yamaguchi",
        "query": None,
        "title": None,
        "format_name": "Vinyl",
    }


def test_ingest_search_stops_on_discogs_http_error() -> None:
    class BoomDiscogs(FakeDiscogs):
        def search_releases(self, **kwargs: str | None) -> tuple[SearchHit, ...]:
            request = httpx.Request("GET", "https://api.discogs.com/database/search")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("boom", request=request, response=response)

    client = BoomDiscogs([])
    stats = IdentityFillStats()
    stats.ingest_fail_fast = True
    try:
        _search_hits_for_row(
            row={"artist": "Teresa Teng", "title": "Ai no Sekai"},
            token="SOLL-114",
            format_name="Vinyl",
            client=client,  # type: ignore[arg-type]
            search_cache={},
            stats=stats,
        )
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("ingest fill should re-raise Discogs HTTP errors")
    assert stats.stopped_reason and "503" in stats.stopped_reason

    retry_stats = IdentityFillStats()
    hits, _require = _search_hits_for_row(
        row={"artist": "Teresa Teng", "title": "Ai no Sekai"},
        token="SOLL-114",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=retry_stats,
    )
    assert hits == ()
    assert retry_stats.stopped_reason is None


def test_search_timeout_stays_on_the_sale() -> None:
    class SlowDiscogs(FakeDiscogs):
        def search_releases(self, **kwargs: str | None) -> tuple[SearchHit, ...]:
            raise httpx.ReadTimeout("timed out")

    client = SlowDiscogs([])
    stats = IdentityFillStats()
    hits, _require = _search_hits_for_row(
        row={"artist": "Teresa Teng", "title": "ベストセレクション 星願"},
        token=None,
        format_name="CD",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    assert stats.search_errors >= 1
    assert stats.stopped_reason is None

    fail_fast = IdentityFillStats()
    fail_fast.ingest_fail_fast = True
    with pytest.raises(httpx.ReadTimeout):
        _search_hits_for_row(
            row={"artist": "Teresa Teng", "title": "ベストセレクション 星願"},
            token=None,
            format_name="CD",
            client=client,  # type: ignore[arg-type]
            search_cache={},
            stats=fail_fast,
        )


def test_operator_deadline_stops_before_another_discogs_call() -> None:
    client = FakeDiscogs([(SOLL_HIT,)])
    stats = IdentityFillStats()
    stats.deadline = 0.0
    hits, _require = _search_hits_for_row(
        row={"artist": "Momoe Yamaguchi", "title": "15 sai SOLL-114"},
        token="SOLL-114",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    assert client.calls == []
    assert stats.budget_exhausted is True


def test_page_cover_hash_does_not_open_every_release() -> None:
    class ReleaseBoom:
        def get_release(self, release_id: int) -> dict:
            raise AssertionError(release_id)

    class ImageBoom:
        def get(self, url: str) -> None:
            raise httpx.ReadTimeout(url)

    hit = SearchHit(
        discogs_id=22912694,
        title="Best Selection ~星願~",
        catno="TACL-2410",
        year="1995",
        country="Japan",
        formats=("CD",),
        labels=("Taurus",),
        thumb_url="https://example.invalid/tacl-2410.jpg",
        uri="/release/22912694",
    )
    _hashes, thumbs, _sides = _hash_shortlist_covers(
        (hit,),
        client=ReleaseBoom(),  # type: ignore[arg-type]
        release_cache={},
        image_client=ImageBoom(),  # type: ignore[arg-type]
        cache={},
        lookup_releases=False,
    )
    assert thumbs == ["https://example.invalid/tacl-2410.jpg"]


def test_search_walks_every_discogs_page() -> None:
    client = DiscogsClient(token="test-token", min_interval_seconds=0)
    seen: list[dict[str, str]] = []

    def fake_get(
        path: str,
        *,
        params: dict[str, str] | None = None,
        _server_retry: bool = True,
    ) -> dict[str, object]:
        del path, _server_retry
        query = dict(params or {})
        seen.append(query)
        page = int(query["page"])
        results = [
            {
                "id": page,
                "type": "release",
                "title": f"Page {page}",
                "catno": f"P-{page}",
                "format": ["Vinyl", "LP"],
                "label": ["Polydor"],
            }
        ]
        return {
            "pagination": {"page": page, "pages": 2, "per_page": 100},
            "results": results,
        }

    client._get = fake_get  # type: ignore[method-assign]
    hits = client.search_releases(title="淡淡幽情", artist="Teresa Teng", format_name=None)
    assert [hit.discogs_id for hit in hits] == [1, 2]
    assert seen[0]["per_page"] == "100"
    assert seen[1]["page"] == "2"


def test_long_discogs_retry_after_does_not_freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "auction_etl.services.discogs_client.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            request=request,
        )

    monkeypatch.setattr("auction_etl.services.discogs_client.httpx.get", fake_get)
    client = DiscogsClient(token="test-token", min_interval_seconds=0)
    with pytest.raises(DiscogsRateLimitError):
        client.search_releases(query="Teresa Teng", format_name="CD")
    assert all(seconds <= 8 for seconds in sleeps)


def test_empty_artist_filter_falls_back_to_catno_then_title() -> None:
    class NoArtistCatno(FakeDiscogs):
        def search_releases(
            self,
            *,
            catno: str | None = None,
            artist: str | None = None,
            query: str | None = None,
            title: str | None = None,
            format_name: str | None = "Vinyl",
        ) -> tuple[SearchHit, ...]:
            self.calls.append(
                {
                    "catno": catno,
                    "artist": artist,
                    "query": query,
                    "title": title,
                    "format_name": format_name,
                }
            )
            if catno == "SOLL-114" and not artist:
                return (SOLL_HIT,)
            return ()

    client = NoArtistCatno([])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={"artist": "Momoe Yamaguchi", "title": "15 sai jacket"},
        token="SOLL-114",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == (SOLL_HIT,)
    assert require_token is True
    assert client.calls[0]["artist"] == "Momoe Yamaguchi"
    assert client.calls[0]["format_name"] == "Vinyl"
    assert any(
        call["artist"] is None and call["catno"] == "SOLL-114"
        for call in client.calls
    )
    assert {call["format_name"] for call in client.calls} >= {
        "Vinyl",
        None,
    }


def test_wrong_format_recovers_with_unfiltered_catno() -> None:
    client = FakeDiscogs([() for _ in range(12)])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={"artist": "Teresa Teng", "title": "POCH-1782 CD"},
        token="POCH-1782",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    catno_formats = {
        call["format_name"]
        for call in client.calls
        if call.get("catno") == "POCH-1782"
    }
    assert "Vinyl" in catno_formats
    assert None in catno_formats


def test_catno_collision_prefers_title_artist_overlap() -> None:
    wrong = parse_search_hits(
        [
            {
                "id": 99,
                "type": "release",
                "title": "Random Future - MIX",
                "catno": "POCH-1782",
                "format": ["CD"],
                "label": ["Polydor"],
                "uri": "/release/99",
            }
        ]
    )[0]
    right = parse_search_hits(
        [
            {
                "id": 1782,
                "type": "release",
                "title": "テレサ・テン* - カバー・ベスト・コレクション",
                "catno": "POCH-1782",
                "format": ["CD"],
                "label": ["Polydor"],
                "uri": "/release/1782",
            }
        ]
    )[0]
    client = FakeDiscogs([(wrong,), (right,)])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Teresa Teng",
            "title": "テレサ・テン 鄧麗君 カバー・ベスト・コレクション POCH-1782",
        },
        token="POCH-1782",
        format_name="CD",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == (right,)
    assert require_token is True
    assert stats.searched >= 2
    assert any(call.get("catno") == "POCH-1782" for call in client.calls)


def test_title_query_strips_buyee_sku_and_condition_brackets() -> None:
    query = _title_query(
        "Teresa Teng",
        "21120439;【美盤/Polydor/帯付】テレサ・テン Teresa Teng 鄧麗君 / 夜来香 / 何日君再来",
    )
    assert query is not None
    assert "21120439" not in query
    assert "美盤" not in query
    assert "夜来香" in query
    assert "Teresa Teng" in query
    assert _title_query(
        "Teresa Teng",
        "CD テレサ・テン 鄧麗君 スーパーセレクション 追悼盤",
    ) == "Teresa Teng スーパーセレクション"
    assert "Teresa Teng Super Selection" in _title_queries(
        "Teresa Teng",
        "CD テレサ・テン 鄧麗君 スーパーセレクション 追悼盤",
    )
    assert _title_query(
        None,
        "LP,山口百恵 COSMOS 宇宙 ポスター付き",
    ) == "山口百恵 COSMOS 宇宙"
    assert _title_query(
        "Teresa Teng",
        "テレサ テン LPアナログ盤 別れの予感",
    ) == "Teresa Teng 別れの予感"
    assert _title_query(
        "Teresa Teng",
        "CD / テレサ・テン / ベストセレクション 星願 [1198CD]",
    ) == "Teresa Teng 星願"
    assert _title_query(
        "Teresa Teng",
        "Teresa Teng 鄧麗君 Dan Dan You Qing 淡淡幽情 LP Vinyl Record 1983 Kolin Taiwan",
    ) == "Teresa Teng 淡淡幽情"
    assert _title_query(
        "Teresa Teng",
        "CD《テレサ・テン（鄧麗君）/『オリジナルベストカラオケ』》中古",
    ) == "Teresa Teng オリジナルベストカラオケ"
    assert _title_query(
        "Teresa Teng",
        "「〈中国語〉華麗なる熱唱」鄧麗君(テレサ・テン) レコード ポリドールレコード 1枚｜LP 昭和歌謡",
    ) == "Teresa Teng 華麗なる熱唱"
    assert _title_query(
        "Teresa Teng",
        "1円～ テレサ・テン 酒酔的探戈 ＬＰ レコード 帯付 鄧麗君 中国語盤 昭和歌謡 トーラス 名盤",
    ) == "Teresa Teng 酒酔的探戈"
    assert "Teresa Teng Jiu Zui De Tan Ge" in _title_queries(
        "Teresa Teng",
        "1円～ テレサ・テン 酒酔的探戈 ＬＰ レコード 帯付 鄧麗君 中国語盤 昭和歌謡 トーラス 名盤",
    )
    stereo_title = "Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound"
    stereo_query = _title_query("Teresa Teng", stereo_title)
    assert stereo_query is not None
    assert "Stereo" in stereo_query
    assert "Sound" in stereo_query
    stereo_queries = _title_queries("Teresa Teng", stereo_title)
    assert any("stereo sound" in item.casefold() for item in stereo_queries)
    assert any("Vol. 4" in item for item in stereo_queries)
    wrong = parse_search_hits(
        [
            {
                "id": 318,
                "type": "release",
                "title": "鄧麗君* - 七○年代名曲選—第四輯 = Best Selections From The 70's, Vol. 4",
                "catno": "3199 318",
                "year": "1980",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["Polydor"],
            }
        ]
    )[0]
    assert _hit_matches_title_tokens(wrong, ("Stereo", "Sound")) is False
    from auction_etl.services.discogs_fill import _pressing_agrees_with_listing

    assert _pressing_agrees_with_listing(
        {
            "title": stereo_title,
            "artist": "Teresa Teng",
            "catalog_number": None,
        },
        {
            "display_title": wrong.title,
            "display_artist": "鄧麗君",
            "catalog_number": wrong.catno,
            "labels": wrong.labels,
            "label_name": "Polydor",
        },
    ) is False
    query = _title_query(
        "Teresa Teng",
        "美盤 LP テレサ・テン 鄧麗君 夜の乗客／女の生きがい UPJY-9092 帯付 日本盤 1975年 Teresa Teng",
    )
    assert query is not None
    assert "UPJY" not in query
    assert "夜の乗客" in query
    assert _title_query(
        "Teresa Teng",
        "【鄧麗君 (銀圈T113版/影視名曲精選)】CD",
    ) == "Teresa Teng 影視名曲精選"
    assert "Teresa Teng Movie Hits" in _title_queries(
        "Teresa Teng",
        "【鄧麗君 (銀圈T113版/影視名曲精選)】CD",
    )
    assert "Paula" in (
        _title_query(
            "Paula Tsui",
            'Paula Tsui "Paula" Cantopop Lp Original Hong Kong',
        )
        or ""
    )
    assert _title_query(
        "Anita Mui",
        "Gripsweat - ANITA MUI - 梅艷芳 似水流年 Hong Kong Lp",
    ) == "Anita Mui 似水流年"
    assert _title_query(
        "Anita Mui",
        "ANITA MUI 梅艷芳 妖女 LP Cinepoly",
    ) == "Anita Mui 妖女"
    assert "さよならの向う側" in (
        _title_query(
            "Momoe Yamaguchi",
            "Momoe Yamaguchi 31th Single Sayonara no Mukougawa Vinyl Record 1980 Japan Pop",
        ) or ""
    )
    sku_query = _title_query(
        "Teresa Teng",
        "Teresa Teng BEST20 MKT0723501 佐川80",
    )
    assert sku_query is not None
    assert "MKT0723501" not in sku_query
    assert "佐川" not in sku_query
    coffee_query = _title_query(
        "Teresa Teng",
        "【EP】宝とも子 / コーヒールンバ 検) 美空ひばり テレサ・テン 】カセットテープ",
    )
    assert coffee_query is not None
    assert "宝とも子" in coffee_query
    assert "コーヒールンバ" in coffee_query
    assert "カセットテープ" not in coffee_query
    assert "美空ひばり" not in coffee_query
    query = _title_query(
        "Teresa Teng",
        "★ V.A. / 大人のムード歌謡 " + ("x" * 200),
    )
    assert query is not None
    assert query.startswith("Teresa Teng")
    assert len(query) <= 100
    client = FakeDiscogs([(SOLL_HIT,)])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={"artist": "Teresa Teng", "title": "空港 CD"},
        token=None,
        format_name="CD",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    assert require_token is False
    assert client.calls
    assert client.calls[0]["artist"] == "Teresa Teng"
    assert client.calls[0]["title"] == "空港" or client.calls[0]["query"] == "Teresa Teng 空港"
    assert client.calls[0]["format_name"] == "CD"


def test_unique_title_search_is_auto_fill_candidate() -> None:
    result = classify_search_hits(
        catalog_number=None,
        title="CD テレサ・テン 鄧麗君 スーパーセレクション 追悼盤",
        artist="Teresa Teng",
        media_type="CD",
        hits=parse_search_hits(
            [
                {
                    "id": 2395001,
                    "type": "release",
                    "title": "テレサ・テン* - Super Selection",
                    "catno": "TACL-2395~6",
                    "year": "1995",
                    "country": "Japan",
                    "format": ["CD", "Compilation"],
                    "label": ["Taurus Records"],
                    "thumb": "",
                    "uri": "/release/2395001",
                }
            ]
        ),
    )
    assert result.status == "filled_auto"
    assert result.reason == "title_search"
    assert _unique_review_candidate(result) is result.chosen
    lp_over_seven = classify_search_hits(
        catalog_number=None,
        title="山口百恵 直筆サイン入り レコード 「禁じられた遊び」",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=parse_search_hits(
            [
                {
                    "id": 1,
                    "type": "release",
                    "title": "山口百恵* - 禁じられた遊び",
                    "catno": "SOLB-89",
                    "year": "1974",
                    "country": "Japan",
                    "format": ["Vinyl", "7\""],
                    "label": ["CBS/Sony"],
                    "thumb": "",
                    "uri": "/release/1",
                },
                {
                    "id": 2,
                    "type": "release",
                    "title": "山口百恵* - 禁じられた遊び",
                    "catno": "SOLL-57",
                    "year": "1974",
                    "country": "Japan",
                    "format": ["Vinyl", "LP"],
                    "label": ["CBS/Sony"],
                    "thumb": "",
                    "uri": "/release/2",
                },
            ]
        ),
    )
    assert lp_over_seven.status == "needs_review"
    assert lp_over_seven.chosen is None
    assert _unique_review_candidate(lp_over_seven) is None
    assert [hit.catno for hit in lp_over_seven.hits][0] == "SOLB-89"
    assert {hit.catno for hit in lp_over_seven.hits} == {"SOLB-89", "SOLL-57"}


def test_four_hit_shared_catalog_still_promotes() -> None:
    hits = parse_search_hits(
        [
            {
                "id": 10 + index,
                "type": "release",
                "title": "山口百恵* - 15才",
                "catno": "SOLL-114",
                "year": "1974",
                "country": "Japan",
                "format": ["Vinyl", "LP", "Album", "Stereo"],
                "label": ["CBS/Sony"],
                "thumb": "",
                "uri": f"/release/{10 + index}",
            }
            for index in range(4)
        ]
    )
    result = classify_search_hits(
        catalog_number="SOLL-114",
        title="MOMOE YAMAGUCHI 15 YEARS OLD CBS SOLL114 1LP",
        artist="Momoe Yamaguchi",
        media_type="LP",
        hits=hits,
        discogs_artist_names=["Momoe Yamaguchi", "山口百恵"],
    )
    assert result.status == "filled_auto"
    assert result.chosen is not None
    assert len(result.hits) == 1
    assert _unique_review_candidate(result) is result.chosen


def test_tracked_reset_does_not_replay_discogs_misses() -> None:
    from auction_etl.services.discogs_fill import (
        _promote_unique_shortlists,
        _reset_tracked_artist_pieces,
    )

    reset_sql = _reset_tracked_artist_pieces.__doc__ or ""
    source = _reset_tracked_artist_pieces.__code__.co_consts
    text = " ".join(str(part) for part in source if isinstance(part, str))
    assert "identity_source" in text
    from auction_etl.services.discogs_fill import _reset_format_and_region_misses

    format_text = " ".join(
        str(part)
        for part in _reset_format_and_region_misses.__code__.co_consts
        if isinstance(part, str)
    )
    assert "jsonb_array_length(discogs_shortlist) = 0" in format_text
    assert "catalog_number" in format_text
    assert "EP%" in format_text
    assert "LP%" in format_text
    assert "VINYL%" in format_text
    promote_text = " ".join(
        str(part)
        for part in _promote_unique_shortlists.__code__.co_consts
        if isinstance(part, str)
    )
    assert reset_sql
    assert "BETWEEN 1 AND 12" in promote_text


def test_needs_review_does_not_keep_stale_discogs_thumb() -> None:
    import inspect

    from auction_etl.services.discogs_fill import _set_auction_identity

    source = inspect.getsource(_set_auction_identity)
    assert "WHEN :status IN ('unmatched', 'needs_review')" in source
    assert "THEN :thumb_url" in source


def test_ingest_fill_combs_leftover_unmatched_and_review() -> None:
    import inspect

    from auction_etl.services.discogs_fill import (
        _load_candidates,
        _research_leftover_identities,
        fill_unmatched_identities,
    )

    source = inspect.getsource(fill_unmatched_identities)
    load = inspect.getsource(_load_candidates)
    leftover = inspect.getsource(_research_leftover_identities)
    leftover_at = source.index("_research_leftover_identities")
    unique_at = source.index("_promote_unique_shortlists")
    unique_retune_at = source.rfind("if retune:", 0, unique_at)
    assert "created_after" in load
    assert "INGEST_IDENTITY_LOOKBACK" in source
    assert "INGEST_IDENTITY_BUDGET_SECONDS" in source
    assert leftover_at != -1
    assert unique_retune_at != -1
    assert unique_at > unique_retune_at
    assert 'stats.stopped_reason == "ingest identity budget"' in source
    assert "INGEST_LEFTOVER_BUDGET_SECONDS" in source
    assert "fast_search=True" in leftover
    assert "ingest leftover budget" in leftover
    assert leftover.index("if deadline is None") < leftover.index(
        "_local_album_search_hits"
    ) < leftover.index("ingest leftover budget")
    assert "fast_search=True" in source
    assert "ingest_fail_fast" in source
    assert "ingest identity budget" in source
    import inspect

    from auction_etl.services.discogs_fill import (
        _cover_hits_from_artist_search,
        _cover_match_one_row,
        _hash_shortlist_covers,
        _promote_cover_matches,
        _promote_unique_shortlists,
        fill_unmatched_identities,
    )

    cover_sql = " ".join(
        str(part)
        for part in _promote_cover_matches.__code__.co_consts
        if isinstance(part, str)
    )
    hash_source = inspect.getsource(_hash_shortlist_covers)
    assert "_unfill_unreliable_auto_identities" in fill_unmatched_identities.__code__.co_names
    assert "_unfill_untracked_auto_identities" in fill_unmatched_identities.__code__.co_names
    assert "_research_leftover_identities" in fill_unmatched_identities.__code__.co_names
    assert "search_cache" in fill_unmatched_identities.__code__.co_varnames or (
        "search_cache=search_cache" in inspect.getsource(fill_unmatched_identities)
    )
    assert "BETWEEN 0 AND 12" in cover_sql
    assert "_pressing_agrees_with_listing" in inspect.getsource(_promote_unique_shortlists)
    assert "cover-artist|" in inspect.getsource(_cover_hits_from_artist_search)
    assert "cover-title|" in inspect.getsource(_cover_hits_from_artist_search)
    assert "discogs_extra_formats" not in inspect.getsource(_cover_hits_from_artist_search)
    assert "_persist_review_shortlist" in inspect.getsource(_cover_match_one_row)
    assert "rank_cover_hits" in inspect.getsource(_cover_match_one_row)
    assert "ranked_agreed" in inspect.getsource(_cover_match_one_row)
    assert "COVER_MAX_DISTANCE" in inspect.getsource(_cover_match_one_row)
    assert hash_source.index("hit.thumb_url") < hash_source.index("_release_draft")
    assert _hash_shortlist_covers.__doc__
    assert "release images" in (_hash_shortlist_covers.__doc__ or "")
    assert _cover_match_one_row.__doc__


def test_artist_cover_search_falls_back_without_format() -> None:
    from auction_etl.services.discogs_fill import _cover_hits_from_artist_search

    class StickyDiscogs(FakeDiscogs):
        def search_releases(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            return (SOLL_HIT,)

    client = StickyDiscogs([])
    stats = IdentityFillStats()
    hits = _cover_hits_from_artist_search(
        {
            "artist": "Momoe Yamaguchi",
            "title": "15 sai SOLL-114",
            "media_type": "LP",
        },
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == (SOLL_HIT,)
    assert stats.searched >= 1
    assert client.calls[0]["format_name"] == "Vinyl"
    assert any(call.get("query") for call in client.calls)


def test_artist_cover_fill_requires_named_album_or_catalog() -> None:
    import inspect

    from auction_etl.services.discogs_fill import (
        _cover_match_one_row,
        _fill_from_cover_hits,
        _hit_agrees_with_listing,
        _pressing_agrees_with_listing,
    )

    source = inspect.getsource(_cover_match_one_row)
    helper = inspect.getsource(_fill_from_cover_hits)
    assert "_hit_agrees_with_listing" in source
    assert "len(agreed) == 1" in helper
    row = {
        "title": "LP / テレサ テン / 夜来香/何日君再来 / 帯付",
        "catalog_number": None,
        "artist": None,
    }
    hit = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "鄧麗君* - 夜来香",
                "catno": "28TR-2032",
            }
        ]
    )[0]
    wrong = parse_search_hits(
        [
            {
                "id": 2,
                "type": "release",
                "title": "鄧麗君* - 淡淡幽情",
                "catno": "TACL-2400",
            }
        ]
    )[0]
    assert _hit_agrees_with_listing(row, hit) is True
    assert _hit_agrees_with_listing(row, wrong) is False
    assert _pressing_agrees_with_listing(
        row,
        {"display_title": hit.title, "catalog_number": hit.catno},
    ) is True
    assert _pressing_agrees_with_listing(
        {
            "title": "LP / テレサ テン / 夜の乗客/女のいきがい / 帯付 [0134RZ]",
            "artist": "Teresa Teng",
            "catalog_number": None,
        },
        {
            "display_title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
            "display_artist": "テレサ・テン",
            "catalog_number": "UPJY-9092",
        },
    ) is False
    assert _pressing_agrees_with_listing(
        {
            "title": "LP / テレサ テン / 夜の乗客/女のいきがい / 帯付 [0134RZ]",
            "artist": "Teresa Teng",
            "catalog_number": None,
        },
        {
            "display_title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
            "display_artist": "テレサ・テン",
            "catalog_number": "MR 2267",
        },
    ) is True
    assert _pressing_agrees_with_listing(
        {
            "title": "美盤 LP テレサ・テン 夜の乗客 UPJY-9092 帯付 日本盤 1975年",
            "artist": "Teresa Teng",
            "catalog_number": None,
        },
        {
            "display_title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
            "display_artist": "テレサ・テン",
            "catalog_number": "UPJY-9092",
        },
    ) is True


def test_bilingual_cd_album_agrees_without_catalog() -> None:
    from auction_etl.services.discogs_fill import _pressing_agrees_with_listing

    assert _pressing_agrees_with_listing(
        {
            "title": "CD テレサ・テン 鄧麗君 スーパーセレクション 追悼盤",
            "artist": "Teresa Teng",
            "catalog_number": None,
        },
        {
            "display_title": "テレサ・テン* - Super Selection",
            "display_artist": "テレサ・テン",
            "catalog_number": "TACL-2395~6",
        },
    ) is True
    assert _pressing_agrees_with_listing(
        {
            "title": "★高音質SACD Hybrid・2CD★テレサ・テン【40/40〜ベスト・セレクション】",
            "artist": "Teresa Teng",
            "catalog_number": None,
        },
        {
            "display_title": "鄧麗君* - 不朽巨星 名曲珍藏 (2)",
            "display_artist": "鄧麗君",
            "catalog_number": "DICD 12002",
        },
    ) is False


def test_title_token_match_ignores_spaces_in_discogs_titles() -> None:
    hit = parse_search_hits(
        [
            {
                "id": 1002,
                "type": "release",
                "title": "鄧麗君* - 島國之情歌 第二集",
                "catno": "MRM-1002",
                "year": "1976",
                "country": "Hong Kong",
                "format": ["Vinyl", "LP"],
                "label": ["Polydor"],
                "thumb": "",
                "uri": "/release/1002",
            }
        ]
    )[0]
    assert _hit_matches_title_tokens(hit, ("島國之情歌第二集",))
    assert _hit_matches_title_tokens(hit, ("岛国之情歌第二集",))
    tango = parse_search_hits(
        [
            {
                "id": 2134,
                "type": "release",
                "title": "テレサ・テン* - 酒醉的探戈",
                "catno": "28TR-2134",
                "year": "1986",
                "country": "Japan",
                "format": ["Vinyl", "LP"],
                "label": ["Taurus"],
                "thumb": "",
                "uri": "/release/2134",
            }
        ]
    )[0]
    assert _hit_matches_title_tokens(tango, ("酒酔的探戈",))


def test_slash_album_becomes_title_query() -> None:
    query = _title_query(
        "Teresa Teng",
        "41193353;【CD/taurus盤】テレサ・テン(鄧麗君) / 淡淡幽情",
    )
    assert query == "Teresa Teng 淡淡幽情"
    query = _title_query(
        "Teresa Teng",
        "【紙ジャケCD】テレサ・テン(鄧麗君)/ つぐない",
    )
    assert query is not None
    assert "つぐない" in query
    split_single = _title_query(
        "Momoe Yamaguchi",
        "11267090;【国内盤/7inch】山口百恵 / 沢田研二 / 私は小鳥 / Oh！この時を",
    )
    assert split_single is not None
    assert "私は小鳥" in split_single
    assert "沢田研二" not in split_single


def test_two_album_title_does_not_lock_without_the_sleeve() -> None:
    from auction_etl.services.discogs_fill import (
        _unique_shortlist_locks_identity,
    )

    hits = parse_search_hits(
        [
            {
                "id": 9732193,
                "type": "release",
                "title": "テレサ・テン* - ふるさとはどこですか",
                "catno": "MR 3048",
                "format": ["Vinyl", "LP"],
                "label": ["Polydor"],
                "uri": "/release/9732193",
            }
        ]
    )
    assert (
        _unique_shortlist_locks_identity(
            {
                "title": "LP/ テレサ テン / 愛をあなたに ふるさとはどこですか / 帯付 [5918RZ]",
                "artist": "Teresa Teng",
                "media_type": "LP",
                "image_url": "https://cdnyauction.buyee.jp/example.jpg",
            },
            hits[0],
            hits,
            "https://i.discogs.com/example.jpg",
            None,
        )
        is False
    )


def test_same_album_shortlist_locks_without_sleeve_photo() -> None:
    from auction_etl.services.discogs_fill import (
        _unique_shortlist_locks_identity,
    )

    hits = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "山口美央子* - Nirvana",
                "catno": "C28A0172",
                "format": ["Vinyl", "LP"],
                "label": ["F-Label"],
                "uri": "/release/1",
            },
            {
                "id": 2,
                "type": "release",
                "title": "山口美央子* - Nirvana",
                "catno": "C28A0173",
                "format": ["Vinyl", "LP", "Promo"],
                "label": ["F-Label"],
                "uri": "/release/2",
            },
        ]
    )

    class Boom:
        def get(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("same-album shortlists must not fetch sleeves")

    assert _unique_shortlist_locks_identity(
        {
            "title": "MIOKO YAMAGUCHI NIRVANA F-LABEL C28A0172 1LP",
            "catalog_number": "C28A0172",
            "image_url": "https://i.ebayimg.com/example.jpg",
        },
        hits[0],
        hits,
        "https://i.discogs.com/example.jpg",
        Boom(),  # type: ignore[arg-type]
    ) is True


def test_empty_unmatched_reset_does_not_wait_for_a_listing_photo() -> None:
    from auction_etl.services.discogs_fill import (
        _reset_photographed_empty_shortlists,
    )

    source = " ".join(
        str(part)
        for part in _reset_photographed_empty_shortlists.__code__.co_consts
        if isinstance(part, str)
    )
    assert "jsonb_array_length(discogs_shortlist) = 0" in source
    assert "image_url" not in source
    assert "TOY" in source


def test_soundtrack_shortlist_locks_from_title_tokens() -> None:
    from auction_etl.services.discogs_fill import (
        _unique_shortlist_locks_identity,
    )

    hits = parse_search_hits(
        [
            {
                "id": 11,
                "type": "release",
                "title": "Various - Dirty Dancing Original Soundtrack",
                "catno": "A1",
                "format": ["Vinyl", "LP"],
                "label": ["RCA"],
                "uri": "/release/11",
            },
            {
                "id": 12,
                "type": "release",
                "title": "Various - Dirty Dancing (Original Soundtrack)",
                "catno": "A2",
                "format": ["Vinyl", "LP"],
                "label": ["RCA"],
                "uri": "/release/12",
            },
        ]
    )

    class Boom:
        def get(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("same-album soundtracks must not fetch sleeves")

    assert _unique_shortlist_locks_identity(
        {
            "title": "Dirty Dancing Soundtrack Lp (Korean pressing)",
            "artist": None,
            "image_url": "https://i.ebayimg.com/example.jpg",
        },
        hits[0],
        hits,
        "https://i.discogs.com/example.jpg",
        Boom(),  # type: ignore[arg-type]
    ) is True


def test_vinyl_search_also_tries_seven_inch() -> None:
    from auction_etl.services.discogs_fill import discogs_extra_formats

    ep_hit = parse_search_hits(
        [
            {
                "id": 3031,
                "type": "release",
                "title": "Anita Mui* - 似是故人來",
                "catno": "KRS-3031",
                "format": ["Vinyl", '7"', "EP"],
                "label": ["Capital Artists"],
            }
        ]
    )[0]
    client = FakeDiscogs([(), (ep_hit,)])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Anita Mui",
            "title": 'ANITA MUI 似是故人來 7" EP KRS-3031',
        },
        token="KRS-3031",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert discogs_extra_formats("Vinyl")[:3] == ("Vinyl", '7"', '12"')
    assert discogs_extra_formats("Vinyl")[-1] is None
    assert {"CD", "SACD", "Cassette", "DVD"} <= set(discogs_extra_formats("Vinyl"))
    assert discogs_extra_formats("CD")[0] == "CD"
    assert {"Vinyl", '7"', "Cassette"} <= set(discogs_extra_formats("CD"))
    assert discogs_extra_formats("Cassette")[0] == "Cassette"
    assert {"Vinyl", "CD"} <= set(discogs_extra_formats("Cassette"))
    assert hits == (ep_hit,)
    assert require_token is True
    assert client.calls[0]["format_name"] == "Vinyl"
    assert None in {call["format_name"] for call in client.calls}


def test_title_search_keeps_every_discogs_format() -> None:
    lp_hit = parse_search_hits(
        [
            {
                "id": 11965483,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 131-1",
                "year": "1983",
                "format": ["Vinyl", "LP", "Album", "Compilation"],
                "label": ["Polydor"],
            }
        ]
    )[0]
    cd_hit = parse_search_hits(
        [
            {
                "id": 27153936,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 143-2",
                "year": "1983",
                "format": ["CD", "Compilation"],
                "label": ["Polydor"],
            }
        ]
    )[0]
    cassette_hit = parse_search_hits(
        [
            {
                "id": 8171324,
                "type": "release",
                "title": "鄧麗君* - 鄧麗君 15週年",
                "catno": "817 132-4",
                "year": "1983",
                "format": ["Cassette", "Compilation"],
                "label": ["Polydor"],
            }
        ]
    )[0]

    class ByFormat(FakeDiscogs):
        def search_releases(self, **kwargs: str | None) -> tuple[SearchHit, ...]:
            self.calls.append(
                {
                    "catno": kwargs.get("catno"),
                    "artist": kwargs.get("artist"),
                    "query": kwargs.get("query"),
                    "title": kwargs.get("title"),
                    "format_name": kwargs.get("format_name"),
                }
            )
            if kwargs.get("catno"):
                return ()
            fmt = kwargs.get("format_name")
            if fmt == "Vinyl":
                return (lp_hit,)
            if fmt == "CD":
                return (cd_hit,)
            if fmt == "Cassette":
                return (cassette_hit,)
            if fmt is None:
                return (lp_hit, cd_hit, cassette_hit)
            return ()

    client = ByFormat([])
    stats = IdentityFillStats()
    title = (
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, "
        "Compilation, Numbered, Taiwan"
    )
    hits, require_token = _search_hits_for_row(
        row={"artist": "Teresa Teng", "title": title},
        token="NOCAT-1",
        format_name="CD",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert require_token is False
    assert {hit.catno for hit in hits} == {"817 131-1", "817 143-2", "817 132-4"}
    formats_called = {call["format_name"] for call in client.calls}
    assert "CD" in formats_called
    assert None in formats_called
    assert any(call.get("catno") == "NOCAT-1" for call in client.calls)


def test_anniversary_title_keeps_year_in_discogs_query() -> None:
    from auction_etl.services.discogs_fill import (
        _distinctive_title_tokens,
        _title_queries,
    )

    title = (
        "鄧麗君 Teresa Teng – 15週年 - 2 X Vinyl, LP, 45 RPM, "
        "Compilation, Numbered, Taiwan"
    )
    assert "15週年" in _distinctive_title_tokens(title, "Teresa Teng")
    queries = _title_queries("Teresa Teng", title)
    assert any("15週年" in query or "15周年" in query for query in queries)


def test_leftover_research_covers_empty_ep_and_unmatched() -> None:
    from auction_etl.services.discogs_fill import leftover_row_needs_research
    from auction_etl.services.discogs_identity import (
        effective_listing_media,
        listing_title_wants_seven_inch,
    )

    assert listing_title_wants_seven_inch('ANITA MUI 戀愛有苦也有樂 7" EP')
    assert effective_listing_media("LP", 'ANITA MUI 戀愛有苦也有樂 7" EP') == "EP_7_INCH"
    assert leftover_row_needs_research(
        {
            "identity_status": "unmatched",
            "title": "【3CD】テレサ・テン シングル・コレクション UPCY-6443/5",
            "media_type": "CD",
            "catalog_number": "UPCY-6443",
            "discogs_shortlist": [],
        }
    )
    assert leftover_row_needs_research(
        {
            "identity_status": "needs_review",
            "title": "CD テレサ・テン 鄧麗君 スーパーセレクション 追悼盤",
            "media_type": "CD",
            "discogs_shortlist": [
                {
                    "id": 1,
                    "type": "release",
                    "title": "テレサ・テン* - Super Selection",
                    "catno": "TACL-2395~6",
                    "format": ["CD"],
                }
            ],
        }
    )
    assert leftover_row_needs_research(
        {
            "identity_status": "needs_review",
            "title": "Teresa Teng つぐない 07TR-1056",
            "media_type": "LP",
            "discogs_shortlist": [
                {
                    "id": 1,
                    "type": "release",
                    "title": "テレサ・テン* - つぐない",
                    "catno": "28TR-2032",
                    "format": ["Vinyl", "LP"],
                }
            ],
        }
    )
    assert leftover_row_needs_research(
        {
            "identity_status": "needs_review",
            "title": "VA salsa hits Lp Original Hong Kong",
            "media_type": "LP",
            "discogs_shortlist": [
                {
                    "id": n,
                    "type": "release",
                    "title": f"Various - Salsa Hits {n}",
                    "catno": f"SL-{n}",
                    "format": ["Vinyl", "LP"],
                }
                for n in range(1, 9)
            ],
        }
    ) is False
    assert leftover_row_needs_research(
        {
            "identity_status": "unmatched",
            "title": "Japanese press 7\" Artist from Taiwan TERESA TENG TUGUNAI",
            "media_type": "EP_7_INCH",
            "discogs_shortlist": [],
        }
    )
    assert leftover_row_needs_research(
        {
            "identity_status": "needs_review",
            "title": "山口百恵 直筆サイン入り レコード 「禁じられた遊び」",
            "media_type": "LP",
            "discogs_shortlist": [
                {
                    "id": 1,
                    "type": "release",
                    "title": "山口百恵* - 青い果実 / 禁じられた遊び",
                    "catno": "SOLL 57",
                    "format": ["Vinyl", "LP", "Album"],
                }
            ],
        }
    )
    assert leftover_row_needs_research(
        {
            "identity_status": "unmatched",
            "title": "テレサ・テン 全曲集 カセットテープ 34TX-1066",
            "media_type": "CASSETTE",
            "catalog_number": "34TX-1066",
            "discogs_shortlist": [],
        }
    )
    assert leftover_row_needs_research(
        {
            "identity_status": "unmatched",
            "title": "MOMOE YAMAGUCHI 15 YEARS OLD CBS jacket",
            "media_type": "LP",
            "discogs_shortlist": [],
        }
    )
    junk = [
        {
            "id": 90016,
            "title": "鄧麗君* = テレサ・テン* - 鄧麗君精選全集",
            "catno": "TATL-9001~6",
            "format": ["CD", "Box Set"],
            "label": ["Taurus"],
        }
    ]
    assert leftover_restore_shortlist(
        outcome="unmatched",
        previous_status="needs_review",
        previous_shortlist=junk,
        title="台湾盤 KUOPIN盤 「鄧麗君 心にのこる夜の唄」台湾盤レコード KP-8142",
        catalog_number="KP-8142",
    ) is None
    restored = leftover_restore_shortlist(
        outcome="unmatched",
        previous_status="needs_review",
        previous_shortlist=junk,
        title="テレサ・テン スーパーセレクション",
        catalog_number=None,
    )
    assert restored is not None
    assert restored[0]["id"] == 90016
    covering = leftover_restore_shortlist(
        outcome="unmatched",
        previous_status="needs_review",
        previous_shortlist=[
            {
                "id": 8142,
                "title": "鄧麗君 - 心にのこる夜の唄",
                "catno": "KP-8142",
                "format": ["Vinyl", "LP"],
                "label": ["Kuopin"],
            },
            junk[0],
        ],
        title="台湾盤 KUOPIN盤 「鄧麗君 心にのこる夜の唄」台湾盤レコード KP-8142",
        catalog_number="KP-8142",
    )
    assert covering is not None
    assert [item["id"] for item in covering] == [8142]
    analog_title = "LP / テレサ テン / 夜の乗客/女のいきがい / 帯付 [0134RZ]"
    modern_only = [
        {
            "id": 15983591,
            "title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
            "catno": "UPJY-9092",
            "year": "2020",
            "format": ["Vinyl", "LP", "Album", "Reissue"],
            "label": ["Universal"],
        }
    ]
    assert leftover_restore_shortlist(
        outcome="unmatched",
        previous_status="needs_review",
        previous_shortlist=modern_only,
        title=analog_title,
        catalog_number=None,
        media_type="LP",
    ) is None
    ye_lai_xiang = (
        "21117778;【美盤/国内盤/Polydor】テレサ・テン Teresa Teng 鄧麗君 "
        "/ 夜来香 / 何日君再来"
    )
    cd_cassette_only = [
        {
            "id": 22863596,
            "title": "テレサ・テン* - 夜来香／何日君再来",
            "catno": "PODH-1114",
            "year": "1992",
            "format": ["CD", "Album"],
            "label": ["Polydor"],
        },
        {
            "id": 28420936,
            "title": "テレサ・テン* - 夜来香／何日君再来",
            "catno": "POSH-1114",
            "year": "1992",
            "format": ["Cassette", "Album"],
            "label": ["Polydor"],
        },
    ]
    assert leftover_restore_shortlist(
        outcome="unmatched",
        previous_status="needs_review",
        previous_shortlist=cd_cassette_only,
        title=ye_lai_xiang,
        catalog_number=None,
        media_type="LP",
    ) is None
    assert leftover_row_needs_research(
        {
            "identity_status": "needs_review",
            "title": ye_lai_xiang,
            "artist": "Teresa Teng",
            "media_type": "LP",
            "catalog_number": None,
            "discogs_shortlist": cd_cassette_only,
        }
    ) is True
    first_press = leftover_restore_shortlist(
        outcome="unmatched",
        previous_status="needs_review",
        previous_shortlist=[
            {
                "id": 3036,
                "title": "テレサ・テン* - 夜の乗客 / 女の生きがい",
                "catno": "MR 3036",
                "year": "1976",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Polydor"],
            },
            modern_only[0],
        ],
        title=analog_title,
        catalog_number=None,
        media_type="LP",
    )
    assert first_press is not None
    assert first_press[0]["id"] == 3036
    assert first_press[0]["catno"] == "MR 3036"


def test_range_catno_keeps_searching_after_unrelated_hit() -> None:
    junk = parse_search_hits(
        [
            {
                "id": 1,
                "type": "release",
                "title": "Momoe Yamaguchi - Other Best",
                "catno": "MHCL-999",
                "format": ["CD"],
                "label": ["Sony"],
            }
        ]
    )[0]
    right = parse_search_hits(
        [
            {
                "id": 10910,
                "type": "release",
                "title": "山口百恵* - ゴールデン・ベスト PLAYBACK MOMOE part2",
                "catno": "MHCL-109~10",
                "format": ["CD", "Compilation"],
                "label": ["Sony"],
            }
        ]
    )[0]
    client = FakeDiscogs([(junk,), (right,)])
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Momoe Yamaguchi",
            "title": "【2CD】山口百恵 / ゴールデン・ベスト PLAYBACK MOMOE part2 MHCL-109~10",
        },
        token="MHCL-109~10",
        format_name="CD",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert require_token is True
    assert hits == (right,)
    assert any(call.get("catno") == "MHCL-109~10" for call in client.calls)


def test_known_catno_ignores_unrelated_prefix_siblings() -> None:
    junk = parse_search_hits(
        [
            {
                "id": 16677849,
                "type": "release",
                "title": "山口百恵* = Momoe Yamaguchi - メビウス・ゲーム",
                "catno": "MHCL 10049~50",
                "format": ["SACD", "CD"],
                "label": ["Sony"],
            }
        ]
    )[0]
    sticky = FakeDiscogs([])

    def always_junk(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "catno": kwargs.get("catno"),
                "artist": kwargs.get("artist"),
                "query": kwargs.get("query"),
                "title": kwargs.get("title"),
                "format_name": kwargs.get("format_name"),
            }
        )
        return (junk,)

    sticky.search_releases = always_junk.__get__(sticky, FakeDiscogs)  # type: ignore[method-assign]
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Momoe Yamaguchi",
            "title": "【2CD】山口百恵 / ゴールデン・ベスト PLAYBACK MOMOE part2 MHCL-109~10",
        },
        token="MHCL-109~10",
        format_name="CD",
        client=sticky,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    assert require_token is True


def test_printed_catno_does_not_keep_unrelated_title_hits() -> None:
    wrong = parse_search_hits(
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
    )[0]
    sticky = FakeDiscogs([])

    def always_wrong(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "catno": kwargs.get("catno"),
                "artist": kwargs.get("artist"),
                "query": kwargs.get("query"),
                "title": kwargs.get("title"),
                "format_name": kwargs.get("format_name"),
            }
        )
        return (wrong,)

    sticky.search_releases = always_wrong.__get__(sticky, FakeDiscogs)  # type: ignore[method-assign]
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Teresa Teng",
            "title": "台湾盤 KUOPIN盤 「鄧麗君 心にのこる夜の唄」台湾盤レコード KP-8142",
        },
        token="KP-8142",
        format_name="Vinyl",
        client=sticky,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    assert require_token is True
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
    )[0]

    def always_sibling(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "catno": kwargs.get("catno"),
                "artist": kwargs.get("artist"),
                "query": kwargs.get("query"),
                "title": kwargs.get("title"),
                "format_name": kwargs.get("format_name"),
            }
        )
        return (sibling,)

    sticky.search_releases = always_sibling.__get__(sticky, FakeDiscogs)  # type: ignore[method-assign]
    sticky.calls = []
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Teresa Teng",
            "title": "鄧麗君初次嚐到寂寞/5223 374",
        },
        token="5223 374",
        format_name="Cassette",
        client=sticky,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    assert hits == ()
    assert require_token is True


def test_catno_lock_still_combs_same_title_other_formats() -> None:
    seven = parse_search_hits(
        [
            {
                "id": 5108033,
                "type": "release",
                "title": "山口百恵* - 横須賀ストーリー = Yokosuka Story",
                "catno": "06SH 15",
                "year": "1976",
                "format": ["Vinyl", '7"', "45 RPM", "Single"],
                "label": ["CBS/Sony"],
            }
        ]
    )[0]
    lp = parse_search_hits(
        [
            {
                "id": 296,
                "type": "release",
                "title": "山口百恵* - 横須賀ストーリー = Yokosuka Story",
                "catno": "25AH 296",
                "year": "1976",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["CBS/Sony"],
            }
        ]
    )[0]
    cd = parse_search_hits(
        [
            {
                "id": 15,
                "type": "release",
                "title": "山口百恵* - 横須賀ストーリー = Yokosuka Story",
                "catno": "32DH 15",
                "year": "1986",
                "format": ["CD", "Album"],
                "label": ["CBS/Sony"],
            }
        ]
    )[0]

    class YokosukaDiscogs:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

        def search_releases(
            self,
            *,
            catno: str | None = None,
            artist: str | None = None,
            query: str | None = None,
            title: str | None = None,
            format_name: str | None = "Vinyl",
        ) -> tuple[SearchHit, ...]:
            self.calls.append(
                {
                    "catno": catno,
                    "artist": artist,
                    "query": query,
                    "title": title,
                    "format_name": format_name,
                }
            )
            if catno:
                return (seven,)
            if format_name in {None, "Vinyl", '12"'}:
                return (lp,)
            if format_name == '7"':
                return (seven,)
            if format_name == "CD":
                return (cd,)
            return ()

    client = YokosukaDiscogs()
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Momoe Yamaguchi",
            "title": (
                "MOMOE YAMAGUCHI Yokosuka Story Japanese Idol "
                "VINYL LP Record With OBI CBS/SONY"
            ),
        },
        token="06SH 15",
        format_name="Vinyl",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    catnos = {fold_catalog(hit.catno) for hit in hits or ()}
    assert fold_catalog("06SH 15") in catnos
    assert fold_catalog("25AH 296") in catnos
    assert fold_catalog("32DH 15") in catnos
    assert require_token is False
    labels = {discogs_format_label(hit.formats) for hit in hits or ()}
    assert "LP" in labels
    assert '7"' in labels
    assert "CD" in labels
    queries = _title_queries(
        "Momoe Yamaguchi",
        "MOMOE YAMAGUCHI Yokosuka Story Japanese Idol VINYL LP Record With OBI CBS/SONY",
    )
    assert "横須賀ストーリー" in queries[0]
    assert any("sony" in query.casefold() for query in queries)


def test_sony_hint_keeps_same_album_lp_without_label() -> None:
    lp = parse_search_hits(
        [
            {
                "id": 1222,
                "type": "release",
                "title": "山口百惠* - Again 百恵 あなたへの子守唄",
                "catno": "30AH 1222",
                "year": "1980",
                "format": ["Vinyl", "LP", "Album"],
                "label": [],
            }
        ]
    )[0]
    cassette = parse_search_hits(
        [
            {
                "id": 25,
                "type": "release",
                "title": "山口百恵* - Again百恵",
                "catno": "KKL 25",
                "year": "1980",
                "format": ["Cassette", "Album"],
                "label": ["King"],
            }
        ]
    )[0]
    cd = parse_search_hits(
        [
            {
                "id": 5,
                "type": "release",
                "title": "山口百惠* - Again 百恵 あなたへの子守唄",
                "catno": "35DH 5",
                "year": "1982",
                "format": ["CD", "Album"],
                "label": ["CBS/Sony"],
            }
        ]
    )[0]

    class AgainDiscogs:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

        def search_releases(
            self,
            *,
            catno: str | None = None,
            artist: str | None = None,
            query: str | None = None,
            title: str | None = None,
            format_name: str | None = "Vinyl",
        ) -> tuple[SearchHit, ...]:
            self.calls.append(
                {
                    "catno": catno,
                    "artist": artist,
                    "query": query,
                    "title": title,
                    "format_name": format_name,
                }
            )
            if catno:
                return ()
            if format_name in {None, "Vinyl", "LP", '12"'}:
                return (lp,)
            if format_name == "CD":
                return (cd,)
            if format_name == "Cassette":
                return (cassette,)
            return ()

    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Momoe Yamaguchi",
            "title": "MOMOE YAMAGUCHI Again CBS/SONY LP VG++ japan w/ inserts s",
        },
        token=None,
        format_name="Vinyl",
        client=AgainDiscogs(),  # type: ignore[arg-type]
        search_cache={},
        stats=IdentityFillStats(),
    )
    catnos = {hit.catno for hit in hits or ()}
    labels = {discogs_format_label(hit.formats) for hit in hits or ()}
    assert require_token is False
    assert "30AH 1222" in catnos
    assert "35DH 5" in catnos
    assert "KKL 25" in catnos
    assert "LP" in labels
    assert "CD" in labels
    assert "Cassette" in labels
    queries = _title_queries(
        "Momoe Yamaguchi",
        "MOMOE YAMAGUCHI Again CBS/SONY LP VG++ japan w/ inserts s",
    )
    assert queries[0] == "Momoe Yamaguchi Again"
    assert not any("inserts" in query.casefold() for query in queries)


def test_fill_uses_fitting_stored_catalog_and_listing_photo() -> None:
    import inspect

    from auction_etl.services.discogs_fill import (
        _cover_close_hits_for_row,
        _fill_one_row,
        _rank_classification_by_listing_photo,
    )

    source = inspect.getsource(_fill_one_row)
    helper = inspect.getsource(_rank_classification_by_listing_photo)
    cover = inspect.getsource(_cover_close_hits_for_row)
    assert "listing_identity_catalog" in source
    assert "_rank_classification_by_listing_photo" in source
    assert "if token:" in source
    assert "catno_locks_listing(hit.catno, token)" in source
    assert "_merge_cover_hits(locked, cover_hits, album_hits, series_hits)" in source
    assert "_cover_close_hits_for_row" in helper
    assert "rank_cover_hits" in cover
    assert "listing_cover_hashes" in cover


def test_missing_printed_catno_searches_shared_prefix() -> None:
    nearby = parse_search_hits(
        [
            {
                "id": 20826127,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "38TT-1145",
                "year": "1987",
                "format": ["Cassette", "Compilation"],
                "label": ["Taurus Records"],
            }
        ]
    )[0]
    older = parse_search_hits(
        [
            {
                "id": 1070,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "38TT-1070",
                "year": "1985",
                "format": ["Cassette", "Compilation"],
                "label": ["Taurus Records"],
            }
        ]
    )[0]
    tatl = parse_search_hits(
        [
            {
                "id": 2365,
                "type": "release",
                "title": "テレサ・テン* - 全曲集 ~あなたの共に生きてゆく~",
                "catno": "TATL-2365",
                "year": "1993",
                "format": ["Cassette", "Compilation"],
                "label": ["Taurus Records"],
            }
        ]
    )[0]
    cd = parse_search_hits(
        [
            {
                "id": 1042,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "29TX-1042",
                "year": "1986",
                "format": ["CD", "Compilation"],
                "label": ["Taurus Records"],
            }
        ]
    )[0]

    class PrefixDiscogs:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []

        def search_releases(
            self,
            *,
            catno: str | None = None,
            artist: str | None = None,
            query: str | None = None,
            title: str | None = None,
            format_name: str | None = "Vinyl",
        ) -> tuple[SearchHit, ...]:
            self.calls.append(
                {
                    "catno": catno,
                    "artist": artist,
                    "query": query,
                    "title": title,
                    "format_name": format_name,
                }
            )
            folded = fold_catalog(catno)
            if folded == "38TT":
                if format_name == "Cassette":
                    return (nearby, older)
                if format_name == "CD":
                    return (cd,)
                return ()
            if catno:
                return ()
            if format_name == "Cassette":
                return (tatl, nearby)
            if format_name == "CD":
                return (cd,)
            return ()

    client = PrefixDiscogs()
    stats = IdentityFillStats()
    hits, require_token = _search_hits_for_row(
        row={
            "artist": "Teresa Teng",
            "title": "テレサ・テン/全曲集/38TT-1120",
        },
        token="38TT-1120",
        format_name="Cassette",
        client=client,  # type: ignore[arg-type]
        search_cache={},
        stats=stats,
    )
    catnos = {fold_catalog(hit.catno) for hit in hits or ()}
    assert fold_catalog("38TT-1145") in catnos
    assert fold_catalog("38TT-1070") in catnos
    assert require_token is False
    assert any(call["catno"] == "38TT" for call in client.calls)
    assert leftover_row_needs_research(
        {
            "identity_status": "needs_review",
            "title": "テレサ・テン/全曲集/38TT-1120",
            "media_type": "CASSETTE",
            "catalog_number": "38TT-1120",
            "discogs_shortlist": [
                {
                    "id": 2365,
                    "title": "テレサ・テン* - 全曲集 ~あなたの共に生きてゆく~",
                    "catno": "TATL-2365",
                    "format": ["Cassette"],
                }
            ],
        }
    )
    ghost = {
        "identity_status": "needs_review",
        "title": "テレサ・テン/全曲集/38TT-1120",
        "media_type": "CASSETTE",
        "catalog_number": "38TT-1120",
        "discogs_shortlist": [
            {
                "id": 2365,
                "title": "テレサ・テン* - 全曲集 ~あなたの共に生きてゆく~",
                "catno": "TATL-2365",
                "format": ["Cassette"],
            }
        ],
    }
    assert leftover_printed_catalog_missing_discogs(ghost) is True
    nearby_family = {
        **ghost,
        "discogs_shortlist": [
            {
                "id": 1145,
                "title": "テレサ・テン* - 全曲集",
                "catno": "38TT-1145",
                "format": ["Cassette"],
            }
        ],
    }
    assert leftover_printed_catalog_missing_discogs(nearby_family) is False
    empty_printed = {
        "identity_status": "unmatched",
        "title": "台湾盤 KUOPIN盤 テレサ・テン 鄧麗君 心にのこる夜の唄 KP-8142",
        "media_type": "LP",
        "catalog_number": "KP-8142",
        "discogs_shortlist": [],
        "image_url": "https://example.invalid/kp8142.jpg",
    }
    assert leftover_printed_catalog_missing_discogs(empty_printed) is True
    assert leftover_row_needs_research(empty_printed) is True


def test_cover_rank_keeps_printed_catalog_prefix() -> None:
    from auction_etl.services.discogs_fill import _cover_may_lead_shortlist

    nearby = parse_search_hits(
        [
            {
                "id": 1145,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "38TT-1145",
                "format": ["Cassette"],
            }
        ]
    )[0]
    canyon = parse_search_hits(
        [
            {
                "id": 1220,
                "type": "release",
                "title": "テレサ・テン* - 全曲集",
                "catno": "30CX-1220",
                "format": ["Cassette"],
            }
        ]
    )[0]
    row = {
        "title": "テレサ・テン/全曲集/38TT-1120",
        "artist": "Teresa Teng",
        "catalog_number": "38TT-1120",
        "media_type": "CASSETTE",
    }
    assert _cover_may_lead_shortlist(nearby, row=row) is True
    assert _cover_may_lead_shortlist(canyon, row=row) is False


def test_cover_rank_does_not_lead_with_upjy_on_vintage_concert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same jacket art on a 2020 repress must not beat the 1977 analog copy."""
    from auction_etl.services import discogs_fill as fill
    from auction_etl.services.discogs_fill import (
        _cover_may_lead_shortlist,
        _rank_classification_by_listing_photo,
    )
    from auction_etl.services.discogs_identity import Classification

    title = "LP/テレサテン/ファースト コンサート/ライブ盤/帯付 [5921RZ]"
    hits = parse_search_hits(
        [
            {
                "id": 9695,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "UPJY-9695",
                "year": "2020",
                "format": ["Vinyl", "LP", "Album", "Reissue"],
            },
            {
                "id": 3965,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "MR 3965",
                "year": "1977",
                "format": ["Vinyl", "LP", "Album"],
            },
        ]
    )
    row = {
        "title": title,
        "artist": "Teresa Teng",
        "catalog_number": None,
        "media_type": "LP",
        "image_url": "https://example.invalid/first-concert.jpg",
    }
    leftover = Classification(
        status="needs_review",
        reason="title_search",
        hits=hits,
        chosen=None,
    )
    monkeypatch.setattr(
        fill,
        "_cover_close_hits_for_row",
        lambda *args, **kwargs: hits,
    )
    ranked = _rank_classification_by_listing_photo(
        leftover,
        row=row,
        client=None,  # type: ignore[arg-type]
        release_cache={},
        image_client=object(),  # type: ignore[arg-type]
    )
    assert ranked.hits[0].catno == "MR 3965"


def test_cover_rank_leads_with_distinct_ssar_jacket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Stereo Sound jacket in the listing photo is not the 1977 Polydor original."""
    from auction_etl.services import discogs_fill as fill
    from auction_etl.services.discogs_fill import _rank_classification_by_listing_photo
    from auction_etl.services.discogs_identity import Classification

    title = "LP/テレサテン/ファースト コンサート/ライブ盤/帯付 [5921RZ]"
    hits = parse_search_hits(
        [
            {
                "id": 3065,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "MR 3065",
                "year": "1977",
                "format": ["Vinyl", "LP", "Album"],
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
    row = {
        "title": title,
        "artist": "Teresa Teng",
        "catalog_number": None,
        "media_type": "LP",
        "image_url": "https://example.invalid/ssar.jpg",
    }
    leftover = Classification(
        status="needs_review",
        reason="title_search",
        hits=hits[:1],
        chosen=None,
    )
    monkeypatch.setattr(
        fill,
        "_cover_close_hits_for_row",
        lambda *args, **kwargs: (hits[1],),
    )
    ranked = _rank_classification_by_listing_photo(
        leftover,
        row=row,
        client=None,  # type: ignore[arg-type]
        release_cache={},
        image_client=object(),  # type: ignore[arg-type]
        extra_hits=hits,
    )
    assert ranked.hits[0].catno == "SSAR-058"


def test_distinct_ssar_jacket_not_overridden_by_vintage_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct Stereo Sound sleeve stays first even when the 1977 LP is also close."""
    from auction_etl.services import discogs_fill as fill
    from auction_etl.services.discogs_fill import _rank_classification_by_listing_photo
    from auction_etl.services.discogs_identity import Classification

    title = "LP/テレサテン/ファースト コンサート/ライブ盤/帯付 [5921RZ]"
    hits = parse_search_hits(
        [
            {
                "id": 3065,
                "type": "release",
                "title": "テレサ・テン* - ファースト・コンサート",
                "catno": "MR 3065",
                "year": "1977",
                "format": ["Vinyl", "LP", "Album"],
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
    row = {
        "title": title,
        "artist": "Teresa Teng",
        "catalog_number": None,
        "media_type": "LP",
        "image_url": "https://example.invalid/ssar.jpg",
    }
    leftover = Classification(
        status="needs_review",
        reason="title_search",
        hits=hits[:1],
        chosen=None,
    )
    monkeypatch.setattr(
        fill,
        "_cover_close_hits_for_row",
        lambda *args, **kwargs: (hits[1], hits[0]),
    )
    ranked = _rank_classification_by_listing_photo(
        leftover,
        row=row,
        client=None,  # type: ignore[arg-type]
        release_cache={},
        image_client=object(),  # type: ignore[arg-type]
        extra_hits=hits,
    )
    assert ranked.hits[0].catno == "SSAR-058"


def test_cover_rank_leads_with_cassette_not_lp_jacket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Island vol.7 cassette must not lead with the sibling LP jacket."""
    from auction_etl.services import discogs_fill as fill
    from auction_etl.services.discogs_fill import _rank_classification_by_listing_photo
    from auction_etl.services.discogs_identity import Classification

    title = "鄧麗君/ 島國之情歌第七集/3199 287"
    hits = parse_search_hits(
        [
            {
                "id": 5711939,
                "type": "release",
                "title": "鄧麗君* - 假如我是真的",
                "catno": "MRM 1008",
                "year": "1981",
                "format": ["Vinyl", "LP", "Album", "Stereo"],
            },
            {
                "id": 13093053,
                "type": "release",
                "title": "鄧麗君* - 假如我是真的",
                "catno": "MRMT 1008",
                "year": "1981",
                "format": ["Cassette", "Album", "Stereo"],
            },
        ]
    )
    row = {
        "title": title,
        "artist": "Teresa Teng",
        "catalog_number": "3199 287",
        "media_type": "CASSETTE",
        "image_url": "https://example.invalid/mrmt.jpg",
    }
    leftover = Classification(
        status="needs_review",
        reason="title_search",
        hits=hits,
        chosen=None,
    )
    monkeypatch.setattr(
        fill,
        "_cover_close_hits_for_row",
        lambda *args, **kwargs: hits,
    )
    ranked = _rank_classification_by_listing_photo(
        leftover,
        row=row,
        client=None,  # type: ignore[arg-type]
        release_cache={},
        image_client=object(),  # type: ignore[arg-type]
        extra_hits=hits,
    )
    assert ranked.hits[0].catno == "MRMT 1008"
    assert "MRM 1008" in {hit.catno for hit in ranked.hits}


def test_cover_rank_does_not_lead_1989_cd_with_2012_reissue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auction_etl.services import discogs_fill as fill
    from auction_etl.services.discogs_fill import _rank_classification_by_listing_photo
    from auction_etl.services.discogs_identity import Classification

    title = "鄧麗君島國情歌六1989 年版CD"
    hits = parse_search_hits(
        [
            {
                "id": 5010295,
                "type": "release",
                "title": "鄧麗君* - 小城故事",
                "catno": "8898232",
                "year": "2012",
                "format": ["CD", "Album", "Reissue"],
            },
            {
                "id": 29786113,
                "type": "release",
                "title": "鄧麗君* - 小城故事",
                "catno": "837 857-2",
                "year": "1989",
                "format": ["CD", "Album", "Reissue", "Stereo"],
            },
        ]
    )
    row = {
        "title": title,
        "artist": "Teresa Teng",
        "catalog_number": None,
        "media_type": "CD",
        "image_url": "https://example.invalid/xiaocheng.jpg",
    }
    leftover = Classification(
        status="needs_review",
        reason="title_search",
        hits=hits,
        chosen=None,
    )
    monkeypatch.setattr(
        fill,
        "_cover_close_hits_for_row",
        lambda *args, **kwargs: hits[:1],
    )
    ranked = _rank_classification_by_listing_photo(
        leftover,
        row=row,
        client=None,  # type: ignore[arg-type]
        release_cache={},
        image_client=object(),  # type: ignore[arg-type]
        extra_hits=hits,
    )
    assert ranked.hits[0].catno == "837 857-2"


def test_unmatched_empty_album_title_needs_research() -> None:
    row = {
        "identity_status": "unmatched",
        "title": "1円スタート テレサ・テン CD 全曲集[2CD]",
        "artist": "Teresa Teng",
        "media_type": "CD",
        "catalog_number": None,
        "discogs_shortlist": [],
    }
    assert leftover_unmatched_empty_shortlist(row) is True
    assert leftover_row_needs_research(row) is True
    enka = {
        "identity_status": "unmatched",
        "title": "LP/ テレサ テン / 演歌のメッセージ / 見本盤/帯付 [5875RZ]",
        "artist": "Teresa Teng",
        "media_type": "LP",
        "catalog_number": None,
        "discogs_shortlist": [],
    }
    assert leftover_unmatched_empty_shortlist(enka) is True


def test_local_album_hits_reuse_identified_discogs_pressing() -> None:
    hits = _local_album_search_hits(
        {
            "title": "LP/ テレサ テン / 演歌のメッセージ / 見本盤/帯付 [5875RZ]",
            "artist": "Teresa Teng",
            "media_type": "LP",
        },
        [
            {
                "discogs_release_id": 3031,
                "catalog_number": "MR 3031",
                "release_year": 1977,
                "country": "Japan",
                "media_type": "LP",
                "discogs_uri": "/release/3031",
                "display_artist": "テレサ・テン",
                "display_title": "演歌のメッセージ",
            },
            {
                "discogs_release_id": 1114,
                "catalog_number": "PODH-1114",
                "release_year": 1992,
                "country": "Japan",
                "media_type": "CD",
                "discogs_uri": "/release/1114",
                "display_artist": "テレサ・テン",
                "display_title": "夜来香",
            },
        ],
    )
    assert [hit.catno for hit in hits] == ["MR 3031"]
    assert hits[0].discogs_id == 3031


def test_vintage_listing_does_not_stop_at_modern_local_reissue() -> None:
    modern = _local_album_search_hits(
        {
            "title": "LP/ テレサ テン / 演歌のメッセージ / 見本盤/帯付 [5875RZ]",
            "artist": "Teresa Teng",
            "media_type": "LP",
        },
        [
            {
                "discogs_release_id": 15983538,
                "catalog_number": "UPJY-9099",
                "release_year": 2020,
                "country": "Japan",
                "media_type": "LP",
                "discogs_uri": "/release/15983538",
                "display_artist": "テレサ・テン",
                "display_title": "演歌のメッセージ",
            }
        ],
    )
    row = {
        "title": "LP/ テレサ テン / 演歌のメッセージ / 見本盤/帯付 [5875RZ]",
        "artist": "Teresa Teng",
        "media_type": "LP",
    }
    assert [hit.catno for hit in modern] == ["UPJY-9099"]
    assert _local_hits_cover_listing(row, modern) is False
    cd_row = {
        "title": "1円スタート テレサ・テン CD 全曲集[2CD]",
        "artist": "Teresa Teng",
        "media_type": "CD",
    }
    cd_hits = _local_album_search_hits(
        cd_row,
        [
            {
                "discogs_release_id": 2301,
                "catalog_number": "TACL-2301",
                "release_year": 1992,
                "country": "Japan",
                "media_type": "CD",
                "discogs_uri": "/release/2301",
                "display_artist": "テレサ・テン",
                "display_title": "全曲集",
            }
        ],
    )
    assert _local_hits_cover_listing(cd_row, cd_hits) is True


def test_last_concert_buyee_title_queries_english_alias() -> None:
    from auction_etl.services.discogs_fill import _title_queries
    from auction_etl.services.discogs_identity import listing_search_artist

    title = "LP美品/テレサテン/ラスト コンサート/ライブ盤/帯付 [5919RZ]"
    assert listing_search_artist("Teresa Teng", title) == "Teresa Teng"
    queries = _title_queries("Teresa Teng", title)
    assert any("Last Concert" in query for query in queries)
    first = "LP/テレサテン/ファースト コンサート/ライブ盤/帯付 [5921RZ]"
    assert listing_search_artist("Teresa Teng", first) == "Teresa Teng"
    first_queries = _title_queries("Teresa Teng", first)
    assert any("First Concert" in query for query in first_queries)
    assert any("stereo sound" in query.casefold() for query in first_queries)
    assert any("Part" in query or "後編" in query for query in first_queries)


def test_momoe_festival_queries_use_printed_soli_and_japanese_album() -> None:
    from auction_etl.services.discogs_fill import _title_queries
    from auction_etl.services.discogs_identity import catalog_token

    title = "MOMOE YAMAGUCHI MOMOE LIVE - FROM THE MOMOE FESTIVAL - CBS SOLI70 2LP"
    assert catalog_token(title=title) == "SOLI-70"
    queries = _title_queries("Momoe Yamaguchi", title, label="CBS/Sony")
    assert any("百恵ライブ" in query for query in queries)
    assert not any(query.casefold().endswith(" from the festival") for query in queries)


def test_sun_light_title_queries_drop_issue_digits() -> None:
    from auction_etl.services.discogs_fill import _title_queries
    from auction_etl.services.discogs_identity import listing_volume_number

    title = (
        "1991 Teresa Teng 鄧麗君 巨星名曲23 世界多變化 "
        "Chinese CD Songs Music Sun Light Record Taiwan"
    )
    assert listing_volume_number(title) == 23
    queries = _title_queries("Teresa Teng", title)
    assert any("巨星名曲" in query and "巨星名曲23" not in query for query in queries)
    assert queries[0].endswith("巨星名曲23 世界多變化") or "巨星名曲23" in queries[0]


def test_mistress_and_self_titled_queries_use_discogs_titles() -> None:
    from auction_etl.services.discogs_fill import _title_queries

    mistress = _title_queries(
        "Teresa Teng",
        "Teresa Teng, Mistress, LP Stereo Sound New JP2",
        label="Stereo Sound",
    )
    assert any("愛人" in query for query in mistress)
    assert not any(query.endswith(" SSAR") for query in mistress)
    best = _title_queries(
        "Teresa Teng",
        "Teresa Teng Best Vol. 4 Vinyl 鄧麗君 テレサ・テン Stereo Sound",
        label="Stereo Sound",
    )
    assert best[0].endswith("SSAR")
    assert any("stereo sound" in query.casefold() and "愛人" in query for query in mistress)
    anita = _title_queries(
        "Anita Mui",
        "Anita Mui: 梅艷芳 Self Titled (1985) Original HK LP Vinyl Record Factory Sealed",
    )
    assert any("梅艷芳" in query for query in anita)
    assert any("1985" in query for query in anita)
    assert not any("Self Titled" in query for query in anita)
    touch = _title_queries(
        "Teresa Teng",
        "鄧麗君淡淡幽情全新末拆黑膠唱片LP",
    )
    assert touch[0].endswith("淡淡幽情")
    care = _title_queries(
        "Teresa Teng",
        "LP / テレサテン / 我只在乎? / 香港盤 [0028RZ]",
    )
    assert care[0].endswith("我只在乎你")
    gold = _title_queries(
        "Teresa Teng",
        "Teresa Teng 邓丽君 – Greatest Hits 寶麗金金裝系列 Hong Kong CD Polydor",
        label="Polydor",
    )
    assert gold[0].casefold().endswith("greatest hits")
    assert not gold[0].endswith("寶麗金金裝系列")


def test_specific_album_queries_are_not_zenshu() -> None:
    from auction_etl.services.discogs_fill import _title_queries, _quoted_album_phrases

    encore = _title_queries(
        "Teresa Teng",
        "2-CD Teresa Teng 1988 Encore Live in Japan Concert + Alan Tam 1988 CD",
    )
    assert any("演唱會" in query or "Encore" in query for query in encore)
    assert not any("Alan" in query for query in encore)
    hits = _title_queries(
        "Teresa Teng",
        "鄧麗君 – Greatest Hits Vol.2 Teresa Teng RARE 1989 CD Hong Kong Mandopop",
    )
    assert any("Greatest Hits" in query for query in hits)
    island = _title_queries(
        "Teresa Teng",
        "鄧麗君島國情歌六1989 年版CD所有$45以下",
    )
    assert any(re.search(r"(?:^|\s)小城故事(?:\s|$)", query) for query in island)
    assert not any("鄧麗君小城故事" in query for query in island)
    assert not any("四張" in query or "45以下" in query for query in island)
    forever = _title_queries(
        "Teresa Teng",
        "41193375;【CD/香港盤/T113】テレサ・テン(鄧麗君) / 永遠的情懐",
    )
    assert any("永遠的情懷" in query for query in forever)
    best10 = _title_queries(
        "Teresa Teng",
        "41193366;【CD/国内盤】テレサ・テン(鄧麗君) / ベスト10",
    )
    assert any("Best 10" in query for query in best10)
    romantic = _title_queries(
        None,
        "★テレサテン 浪漫主義 CD 帯付き 国内正規品★",
    )
    assert any(query == "Teresa Teng 浪漫主義" for query in romantic)
    assert not any("国内正規" in query for query in romantic)
    golden = _title_queries(
        "Teresa Teng",
        "CD / テレサ・テン ゴールデン☆ベスト / Teresa Teng A1-15",
    )
    assert any("Golden Best" in query for query in golden)
    best100 = _title_queries(
        "Teresa Teng",
        "未開封品 CD 5枚組 BOX / テレサ・テン 永久保存版 The Best 100 ?永遠の歌姫? 全100曲 鄧麗君 / 国内正規品",
    )
    assert not any("ベスト10" in query or "Best 10" in query for query in best100)
    assert any("永遠の歌姫" in query for query in best100)
    assert not any("5枚組" in query or "永久保存版" in query for query in best100)
    space = _title_queries(
        "Teresa Teng",
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp",
    )
    assert any("Vol. 11" in query for query in space)
    assert any("之歌第十一集" in query for query in space)
    assert any("再會吧" in query for query in space)
    assert any("之歌第" in query for query in space)
    songbook16 = _title_queries(
        "Teresa Teng",
        "【台盤LP】「鄧麗君（テレサ・テン）/玉女巨星鄧麗君之歌第十六集」宇宙唱片",
    )
    assert any("之歌第十六集" in query for query in songbook16)
    assert not any(query.strip() == "鄧麗君 AWK" or query.endswith(" AWK") for query in songbook16)
    assert not any("玉女巨星" in query for query in songbook16)
    taurus = _title_queries(
        "Teresa Teng",
        "2LP TERESA TENG Best 20 18TR205960 TAURUS JAPAN OBI",
        label="Taurus",
    )
    assert not any("2LP" == token for query in taurus for token in query.split())
    assert any("ベスト20" in query for query in taurus)
    polygram = _title_queries(
        "Teresa Teng",
        "Teresa Teng, PolyGram Records Hong Kong (CD 1985 Polydor) Chinese Music * RARE!",
        label="Polydor",
    )
    assert any("1985" in query for query in polygram)
    assert not any("Chinese Music" in query for query in polygram)
    stroll = _title_queries(
        "Teresa Teng",
        "Teresa Teng CD 漫步人生路 A Stroll Through Life 1989 RARE! MINT!",
    )
    assert any("漫步人生路" in query for query in stroll)
    assert not any("MINT" in query for query in stroll)
    magokoro = _title_queries(
        "Teresa Teng",
        'Japanese Vinyl LP Record: Teresa Teng - "Anata Magokoro"',
    )
    assert any("まごころ" in query or "Anata Magokoro" in query for query in magokoro)
    nhk = _title_queries(
        "Teresa Teng",
        "Teresa Teng - One & Only: 1985 NHK Live (Complete) [New Vinyl LP] 180 Gram",
    )
    assert any("One & Only" in query or "NHK Live" in query for query in nhk)
    vol3 = _title_queries(
        "Teresa Teng",
        "Teresa Teng 鄧麗君 Vol. 3 2017 Japan LP Sealed W/Insert Limited Edition 180g",
        label="Polydor",
    )
    assert any("Vol. 3" in query for query in vol3)
    assert any("Analog Record Collection" in query or "stereo sound" in query for query in vol3)
    assert _quoted_album_phrases(
        "新品未開封！限定盤・テレサテン・（鄧麗君）・3CD & DVD・「テレサテン 伝説の歌姫」"
    ) == ("伝説の歌姫",)


def test_space_record_volume_drops_neighbor_songbook_hits() -> None:
    from auction_etl.services.discogs_fill import (
        _hits_agree_with_listing_volume,
        _series_shortlist_hits,
        _distinctive_title_tokens,
    )
    from auction_etl.services.discogs_identity import SearchHit

    def hit(release_id: int, title: str, catno: str) -> SearchHit:
        return SearchHit(
            discogs_id=release_id,
            title=title,
            catno=catno,
            year="1969",
            country="Taiwan",
            formats=("Vinyl", "LP"),
            labels=("Space Record",),
            thumb_url=None,
            uri=None,
        )

    listing = (
        "TERESA TENG 鄧麗君 Taiwan space record vol 11 early recording 1968 vinyl lp"
    )
    twelfth = hit(1, "鄧麗君* - 鄧麗君之歌第十二集", "AWK-035")
    first = hit(2, "鄧麗君* - 鄧麗君之歌第一集", "AWK-034")
    eleventh = hit(3, "鄧麗君* - 鄧麗君之歌第十一集", "AWK-xxx")
    assert _hits_agree_with_listing_volume(
        listing,
        (twelfth, first, eleventh),
    ) == (eleventh,)
    assert _series_shortlist_hits(listing, (twelfth, first, eleventh)) == (eleventh,)
    stroll_tokens = _distinctive_title_tokens(
        "Teresa Teng CD 漫步人生路 A Stroll Through Life 1989 RARE! MINT!",
        "Teresa Teng",
    )
    assert "漫步人生路" in stroll_tokens
    assert "MINT" not in stroll_tokens


def test_label_year_queries_use_discogs_q_not_title() -> None:
    from auction_etl.services.discogs_fill import _use_discogs_title_param

    assert _use_discogs_title_param("polydor") is False
    assert _use_discogs_title_param("polydor 1985") is False
    assert _use_discogs_title_param("One & Only") is True
    assert _use_discogs_title_param("まごころ") is True


def test_operator_research_keeps_unmatched_shortlist_for_use_this() -> None:
    import inspect

    from auction_etl.services.discogs_fill import (
        research_listing_identity,
        _fill_one_row,
    )

    fill_source = inspect.getsource(_fill_one_row)
    research_source = inspect.getsource(research_listing_identity)
    assert "operator_choice: bool = False" in fill_source
    assert "operator_choice=True" in research_source
    assert "fast_search=False" in research_source
    assert "image_client=http" in research_source
    assert "image_client=None" not in research_source
    assert "source_hits = remaining_classification.hits or hits" in fill_source
    assert "shortlist_format_options" in fill_source


def test_typed_catalog_search_lists_the_listing_format_first() -> None:
    lp = SearchHit(
        discogs_id=2,
        title="Teresa Teng - Best Hits Album",
        catno="MR 3037",
        year="1976",
        country="Japan",
        formats=("Vinyl", "LP", "Album"),
        labels=("Polydor",),
        thumb_url=None,
        uri=None,
    )
    seven = SearchHit(
        discogs_id=1,
        title="Teresa Teng - Best Hit 4",
        catno="KRS 3021",
        year="1977",
        country="Japan",
        formats=("Vinyl", '7"', "EP"),
        labels=("Polydor",),
        thumb_url=None,
        uri=None,
    )
    assert query_looks_like_catalog("MR 3037") is True
    assert query_looks_like_catalog("28TR-2092") is True
    assert query_looks_like_catalog("Best Hits") is False
    assert query_looks_like_catalog("Best Hit 4") is False
    catalog = FakeDiscogs([(seven, lp)])
    found = search_user_catalog(
        catalog,
        artist="Teresa Teng",
        title="LP / Teresa Teng / Best Hits / With Obi [5184RZ]",
        query="MR 3037",
        listing_media="LP",
    )
    assert catalog.calls[0]["catno"] == "MR 3037"
    assert catalog.calls[0]["format_name"] == "LP"
    assert catalog.calls[0]["artist"] == "Teresa Teng"
    assert [hit["catno"] for hit in found] == ["MR 3037", "KRS 3021"]
    album = FakeDiscogs([(lp,)])
    named = search_user_catalog(
        album,
        artist="Teresa Teng",
        title="LP / Teresa Teng / Best Hits / With Obi [5184RZ]",
        query="Best Hits",
        listing_media="LP",
    )
    assert album.calls[0]["title"] == "Best Hits"
    assert album.calls[0]["catno"] is None
    assert album.calls[0]["format_name"] is None
    assert named[0]["id"] == 2
    aliased = FakeDiscogs(
        [
            (),
            (lp,),
        ]
    )
    alias_hits = search_user_catalog(
        aliased,
        artist="Teresa Teng",
        title="鄧麗君淡淡幽情全新未拆黑膠唱片LP",
        query="淡淡幽情",
        listing_media="LP",
    )
    assert aliased.calls[0]["title"] == "淡淡幽情"
    assert aliased.calls[0]["format_name"] is None
    assert any(call["title"] == "Dan Dan You Qing" for call in aliased.calls)
    assert alias_hits[0]["id"] == 2
    flaming = parse_search_hits(
        [
            {
                "id": 6599877,
                "type": "release",
                "title": "梅艷芳* - 梅艷芳",
                "catno": "CAL-04-1056",
                "year": "1987",
                "country": "Hong Kong",
                "format": ["Vinyl", "LP", "Album", "Stereo"],
                "label": ["Capital Artists Ltd."],
                "thumb": "",
                "uri": "/release/6599877",
            }
        ]
    )[0]
    taiwan = parse_search_hits(
        [
            {
                "id": 16712367,
                "type": "release",
                "title": "梅艷芳* - 百變梅艷芳 烈焰紅唇 (國語專輯)",
                "catno": "RR-164",
                "year": "1988",
                "country": "Taiwan",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["Rock Records & Tapes"],
                "thumb": "",
                "uri": "/release/16712367",
            }
        ]
    )[0]
    named_lp = FakeDiscogs([(flaming,), (taiwan,), (), (), ()])
    flaming_hits = search_user_catalog(
        named_lp,
        artist="Anita Mui",
        title="Anita Mui [梅艷芳] – Flaming Lips [烈燄紅唇] (1987) Hong Kong Press Vinyl LP",
        query="烈燄紅唇",
        listing_media="LP",
    )
    assert named_lp.calls[0]["catno"] == "CAL-04-1056"
    assert named_lp.calls[0]["format_name"] is None
    assert flaming_hits[0]["id"] == 6599877
    assert flaming_hits[0]["catno"] == "CAL-04-1056"
    assert flaming_hits[1]["catno"] == "RR-164"
    stereo = parse_search_hits(
        [
            {
                "id": 12607090,
                "type": "release",
                "title": "Teresa Teng - Teresa Teng = テレサ・テン",
                "catno": "SSAR-018",
                "year": "2017",
                "country": "Japan",
                "format": ["Vinyl", "LP", "Compilation"],
                "label": ["Stereo Sound"],
                "thumb": "",
                "uri": "/release/12607090",
            }
        ]
    )[0]
    peanuts = parse_search_hits(
        [
            {
                "id": 9,
                "type": "release",
                "title": "The Peanuts - The Peanuts",
                "catno": "SSAR-90",
                "year": "1960",
                "country": "Japan",
                "format": ["Vinyl", "LP"],
                "label": ["Stereo Sound"],
                "thumb": "",
                "uri": "/release/9",
            }
        ]
    )[0]
    stem = FakeDiscogs([(stereo, peanuts), (stereo, peanuts)])
    stem_hits = search_user_catalog(
        stem,
        artist="Teresa Teng",
        title="Teresa Teng Stereo Sound SSAR LP",
        query="ssar",
        listing_media="LP",
    )
    assert stem.calls[0]["catno"] == "ssar"
    assert stem.calls[0]["artist"] == "Teresa Teng"
    assert stem.calls[0]["title"] is None
    assert stem.calls[1]["query"] == "ssar"
    assert stem.calls[1]["artist"] == "Teresa Teng"
    assert all(call["title"] != "ssar" for call in stem.calls)
    assert [hit["catno"] for hit in stem_hits] == ["SSAR-018"]
    assert search_user_catalog(
        FakeDiscogs([]),
        artist="Teresa Teng",
        title="Best Hits",
        query="M",
        listing_media="LP",
    ) == []


def test_catalog_search_finds_a_soundtrack_filed_under_another_artist() -> None:
    """LFLP 269 is a Various soundtrack. Teresa Teng is a track credit."""
    soundtrack = parse_search_hits(
        [
            {
                "id": 5436423,
                "type": "release",
                "title": "左宏元, Various - 彩雲飛 電影原聲帶插曲",
                "catno": "",
                "year": "1973",
                "country": "Singapore",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["LIFE Records", "樂風"],
                "thumb": "",
                "uri": "/release/5436423",
            },
            {
                "id": 99,
                "type": "release",
                "title": "Various - Something Else",
                "catno": "",
                "year": "1974",
                "country": "Singapore",
                "format": ["Vinyl", "LP", "Album"],
                "label": ["LIFE Records"],
                "thumb": "",
                "uri": "/release/99",
            },
        ]
    )

    class CatalogDiscogs(FakeDiscogs):
        def get_release(self, release_id: int) -> dict[str, object]:
            if release_id == 5436423:
                return {
                    "id": 5436423,
                    "labels": [{"name": "樂風", "catno": "LFLP 269"}],
                }
            return {"id": release_id, "labels": [{"name": "LIFE Records", "catno": "LFLP 370"}]}

    client = CatalogDiscogs([(), (), soundtrack])
    found = search_user_catalog(
        client,
        artist="Teresa Teng",
        title="鄧麗君 彩雲飛 LP",
        query="LFLP 269",
        listing_media="LP",
    )
    assert client.calls[0]["artist"] == "Teresa Teng"
    assert client.calls[0]["catno"] == "LFLP 269"
    assert client.calls[2]["artist"] is None
    assert client.calls[2]["catno"] == "LFLP 269"
    assert [hit["id"] for hit in found] == [5436423]
    assert found[0]["catno"] == "LFLP 269"
