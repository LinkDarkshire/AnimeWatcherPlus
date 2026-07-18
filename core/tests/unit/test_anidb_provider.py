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
