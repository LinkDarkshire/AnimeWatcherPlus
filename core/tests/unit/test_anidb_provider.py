from __future__ import annotations

from app.providers.anidb import (
    _extract_error_text,
    _is_error_response,
    _parse_anime_xml,
    parse_full_anime_info,
)

# Trimmed real-world shape (aid=1, "Seikai no Monshou" / "Crest of the Stars"):
# the Japanese official title appears *before* the English one in document
# order, which is exactly what exposed the old "first official title wins"
# bug (it silently picked Japanese kanji as the primary display title).
SAMPLE_ANIME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<anime id="1" restricted="false">
    <type>TV Series</type>
    <episodecount>13</episodecount>
    <startdate>1999-01-03</startdate>
    <enddate>1999-03-28</enddate>
    <titles>
        <title xml:lang="x-jat" type="main">Seikai no Monshou</title>
        <title xml:lang="ru" type="synonym">Zvyozdnyy Gerb</title>
        <title xml:lang="en" type="short">CotS</title>
        <title xml:lang="ja" type="official">星界の紋章</title>
        <title xml:lang="en" type="official">Crest of the Stars</title>
        <title xml:lang="fr" type="official">Crest of the Stars</title>
    </titles>
    <description>A young prince and a girl travel among the stars.</description>
    <picture>12345.jpg</picture>
    <tags>
        <tag id="30" weight="600"><name>space travel</name></tag>
        <tag id="31" weight="400"><name>military</name></tag>
    </tags>
    <episodes>
        <episode id="1"><epno type="1">1</epno><title xml:lang="en">Awakening</title><airdate>1999-01-03</airdate></episode>
    </episodes>
</anime>
"""


def test_parse_anime_xml_prefers_english_official_title() -> None:
    metadata = _parse_anime_xml(SAMPLE_ANIME_XML.encode("utf-8"), aid=1)

    assert metadata is not None
    assert metadata.title == "Crest of the Stars"
    assert metadata.original_title == "Seikai no Monshou"
    assert "星界の紋章" in metadata.alt_titles  # Japanese official kept as alt title
    assert "Zvyozdnyy Gerb" in metadata.alt_titles
    assert metadata.year == 1999
    assert metadata.media_type == "TV Series"
    assert metadata.poster_url == "http://img7.anidb.net/pics/anime/12345.jpg"
    assert {t.name for t in metadata.tags} == {"space travel", "military"}
    assert len(metadata.episodes) == 1
    assert metadata.episodes[0].ep_number == "1"


def test_parse_anime_xml_exposes_all_three_title_variants() -> None:
    """The variants have to reach AnimeMetadata untouched, not just the one
    title the provider's own default order happens to pick -- re-resolving a
    display or folder name from the user's configured order later must not
    need another AniDB request."""
    metadata = _parse_anime_xml(SAMPLE_ANIME_XML.encode("utf-8"), aid=1)

    assert metadata is not None
    assert metadata.title_main == "Seikai no Monshou"
    assert metadata.title_en == "Crest of the Stars"  # "official" beats the "short" CotS
    assert metadata.title_ja == "星界の紋章"


def test_parse_anime_xml_falls_back_to_main_title_without_official() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <anime id="2" restricted="false">
        <type>Movie</type>
        <titles>
            <title xml:lang="x-jat" type="main">Some Movie</title>
        </titles>
    </anime>
    """
    metadata = _parse_anime_xml(xml.encode("utf-8"), aid=2)
    assert metadata is not None
    assert metadata.title == "Some Movie"
    assert metadata.original_title == "Some Movie"
    assert metadata.alt_titles == []


def test_parse_anime_xml_prefers_english_synonym_over_japanese_official() -> None:
    """Regression test for a real-world case (AID 16686): AniDB sometimes has
    no English title tagged "official" at all -- only "synonym" -- while the
    Japanese-script title *is* tagged "official". The old fallback chain
    (`_pick_title(ttype="official")`, ignoring language) picked that raw
    Japanese script as the primary title, even though a perfectly good
    English synonym and a romanized (x-jat) main title both existed. English
    must win regardless of its `type`, as long as no higher-priority English
    title exists.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <anime id="16686" restricted="true">
        <type>OVA</type>
        <titles>
            <title xml:lang="x-jat" type="main">Abandon -100 Nuki Shinai to Derarenai Fushigi na Kyoushitsu-</title>
            <title xml:lang="ja" type="official">Abandon -100ヌキしないと出られない不思議な教室-</title>
            <title xml:lang="en" type="synonym">Abandon: 100 Nuki Shinai to Derarenai Fushigi na Kyoushitsu</title>
        </titles>
    </anime>
    """
    metadata = _parse_anime_xml(xml.encode("utf-8"), aid=16686)
    assert metadata is not None
    assert metadata.title == "Abandon: 100 Nuki Shinai to Derarenai Fushigi na Kyoushitsu"
    assert metadata.original_title == "Abandon -100 Nuki Shinai to Derarenai Fushigi na Kyoushitsu-"


def test_parse_anime_xml_prefers_romanized_japanese_over_script_without_english() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <anime id="4" restricted="false">
        <type>TV Series</type>
        <titles>
            <title xml:lang="ja" type="official">日本語のタイトル</title>
            <title xml:lang="x-jat" type="main">Nihongo no Taitoru</title>
        </titles>
    </anime>
    """
    metadata = _parse_anime_xml(xml.encode("utf-8"), aid=4)
    assert metadata is not None
    assert metadata.title == "Nihongo no Taitoru"


def test_parse_anime_xml_picks_preferred_language_per_episode_title() -> None:
    """Episode titles get the same language cascade -- the old code just took
    `ep_el.find("title")` (first child in document order), which for an
    episode listing Japanese before English would silently show raw kanji.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <anime id="5" restricted="false">
        <type>TV Series</type>
        <titles>
            <title xml:lang="en" type="official">Test Show</title>
        </titles>
        <episodes>
            <episode id="1">
                <epno type="1">1</epno>
                <title xml:lang="ja">日本語のエピソード</title>
                <title xml:lang="x-jat">Nihongo no Episōdo</title>
                <title xml:lang="en">Awakening</title>
            </episode>
            <episode id="2">
                <epno type="1">2</epno>
                <title xml:lang="ja">二番目のエピソード</title>
                <title xml:lang="x-jat">Nibanme no Episōdo</title>
            </episode>
        </episodes>
    </anime>
    """
    metadata = _parse_anime_xml(xml.encode("utf-8"), aid=5)
    assert metadata is not None
    assert metadata.episodes[0].title == "Awakening"
    assert metadata.episodes[1].title == "Nibanme no Episōdo"


def test_parse_anime_xml_falls_back_to_placeholder_without_any_title() -> None:
    xml = '<?xml version="1.0" encoding="UTF-8"?><anime id="3"><type>TV Series</type></anime>'
    metadata = _parse_anime_xml(xml.encode("utf-8"), aid=3)
    assert metadata is not None
    assert metadata.title == "AniDB #3"


def test_parse_anime_xml_invalid_xml_returns_none() -> None:
    assert _parse_anime_xml(b"not xml at all", aid=1) is None


def test_is_error_response_detects_error_root() -> None:
    assert _is_error_response(b'<error code="302">client version missing or invalid</error>') is True
    assert _is_error_response(SAMPLE_ANIME_XML.encode("utf-8")) is False


def test_extract_error_text() -> None:
    assert (
        _extract_error_text(b'<error code="302">client version missing or invalid</error>')
        == "client version missing or invalid"
    )


FULL_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<anime id="1" restricted="false">
    <type>TV Series</type>
    <episodecount>13</episodecount>
    <startdate>1999-01-03</startdate>
    <enddate>1999-03-28</enddate>
    <titles>
        <title xml:lang="x-jat" type="main">Seikai no Monshou</title>
        <title xml:lang="ja" type="official">星界の紋章</title>
        <title xml:lang="en" type="official">Crest of the Stars</title>
    </titles>
    <relatedanime>
        <anime id="4" type="Sequel">Seikai no Senki</anime>
    </relatedanime>
    <creators>
        <name id="4303" type="Music">Hattori Katsuhisa</name>
    </creators>
    <description>A young prince and a girl travel among the stars.</description>
    <ratings>
        <permanent count="5069">8.24</permanent>
        <temporary count="5100">8.20</temporary>
        <review count="13">8.57</review>
    </ratings>
    <picture>224618.jpg</picture>
    <tags>
        <tag id="30" weight="600"><name>space travel</name></tag>
    </tags>
    <episodes>
        <episode id="1" update="2021-06-08">
            <epno type="1">1</epno>
            <length>25</length>
            <airdate>1999-01-03</airdate>
            <rating votes="31">3.09</rating>
            <title xml:lang="ja">侵略</title>
            <title xml:lang="en">Invasion</title>
            <summary>The planet Martine is invaded.</summary>
        </episode>
    </episodes>
</anime>
"""


def test_parse_full_anime_info_covers_ratings_creators_relations_and_episode_detail() -> None:
    info = parse_full_anime_info(FULL_SAMPLE_XML.encode("utf-8"), aid=1)

    assert info is not None
    assert info["anidb_id"] == 1
    assert info["restricted"] is False
    assert info["type"] == "TV Series"
    assert info["start_date"] == "1999-01-03"
    assert info["end_date"] == "1999-03-28"
    assert info["episode_count_official"] == 13
    assert info["primary_title"] == "Crest of the Stars"
    assert info["original_title"] == "Seikai no Monshou"
    assert {"language": "ja", "type": "official", "value": "星界の紋章"} in info["titles"]

    assert info["ratings"]["permanent"] == {"value": 8.24, "votes": 5069}
    assert info["ratings"]["review"] == {"value": 8.57, "votes": 13}

    assert info["creators"] == [{"anidb_creator_id": 4303, "name": "Hattori Katsuhisa", "role": "Music"}]
    assert info["related_anime"] == [{"anidb_id": 4, "relation_type": "Sequel", "title": "Seikai no Senki"}]
    assert info["tags"] == [{"anidb_tag_id": 30, "name": "space travel", "weight": 600}]

    assert len(info["episodes"]) == 1
    ep = info["episodes"][0]
    assert ep["ep_number"] == "1"
    assert ep["length_minutes"] == 25
    assert ep["air_date"] == "1999-01-03"
    assert ep["rating"] == {"value": 3.09, "votes": 31}
    assert ep["titles"] == {"ja": "侵略", "en": "Invasion"}
    assert ep["summary"] == "The planet Martine is invaded."


def test_parse_full_anime_info_invalid_xml_returns_none() -> None:
    assert parse_full_anime_info(b"not xml", aid=1) is None


def test_cached_title_variants_reads_the_response_cache(tmp_path) -> None:
    """The backfill source for anime that the staleness rule keeps out of
    rescans: whatever AniDB returned last time, however old."""
    from app.config import Settings
    from app.providers.anidb import cache_dir, cached_title_variants

    settings = Settings(data_dir=tmp_path)
    cache_dir(settings).mkdir(parents=True)
    (cache_dir(settings) / "1.xml").write_text(SAMPLE_ANIME_XML, encoding="utf-8")

    assert cached_title_variants(settings, 1) == {
        "main": "Seikai no Monshou",
        "en": "Crest of the Stars",
        "ja": "星界の紋章",
    }


def test_cached_title_variants_ignores_missing_and_error_responses(tmp_path) -> None:
    from app.config import Settings
    from app.providers.anidb import cache_dir, cached_title_variants

    settings = Settings(data_dir=tmp_path)
    cache_dir(settings).mkdir(parents=True)
    (cache_dir(settings) / "2.xml").write_text("<error>Anime not found</error>", encoding="utf-8")
    (cache_dir(settings) / "3.xml").write_text("not xml", encoding="utf-8")

    assert cached_title_variants(settings, 1) is None  # not cached
    assert cached_title_variants(settings, 2) is None
    assert cached_title_variants(settings, 3) is None
