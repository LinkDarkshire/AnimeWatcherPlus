from __future__ import annotations

import gzip

import pytest

from app.services.titledump import (
    import_title_dump,
    normalize_folder_name,
    parse_title_dump,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("[SubsPlease] Mushoku Tensei S2 (2021) [1080p]", "mushoku tensei s2"),
        ("Attack.on.Titan.Complete.BD.1080p", "attack on titan"),
        ("Fate Zero", "fate zero"),
    ],
)
def test_normalize_folder_name(raw: str, expected: str) -> None:
    assert normalize_folder_name(raw) == expected


def _sample_dump_bytes() -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<animetitles>"
        '<anime aid="17222">'
        '<title xml:lang="x-jat" type="main">Mushoku Tensei II</title>'
        '<title xml:lang="en" type="official">Mushoku Tensei: Jobless Reincarnation Season 2</title>'
        "</anime>"
        '<anime aid="1">'
        '<title xml:lang="x-jat" type="main">Fate Zero</title>'
        "</anime>"
        "</animetitles>"
    ).encode("utf-8")
    return gzip.compress(xml)


def test_parse_title_dump() -> None:
    rows = parse_title_dump(_sample_dump_bytes())
    assert len(rows) == 3
    assert rows[0].aid == 17222
    assert rows[0].lang == "x-jat"
    assert rows[1].title == "Mushoku Tensei: Jobless Reincarnation Season 2"


@pytest.mark.asyncio
async def test_import_title_dump_and_fuzzy_match(db_session) -> None:
    from app.services.titledump import fuzzy_match

    count = await import_title_dump(db_session, _sample_dump_bytes())
    assert count == 3

    candidates = await fuzzy_match(db_session, "[Group] Mushoku Tensei II [1080p]")
    assert candidates
    assert candidates[0].aid == 17222
