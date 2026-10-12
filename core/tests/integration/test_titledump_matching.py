from __future__ import annotations

import gzip
import time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db.models import AnidbTitleEntry, Setting
from app.services import titledump
from app.services.titledump import TITLE_DUMP_IMPORTED_AT_KEY, fuzzy_match, import_title_dump


def _dump(*animes: tuple[int, list[tuple[str, str, str]]]) -> bytes:
    parts = ['<?xml version="1.0" encoding="UTF-8"?><animetitles>']
    for aid, titles in animes:
        parts.append(f'<anime aid="{aid}">')
        for text, lang, ttype in titles:
            parts.append(f'<title xml:lang="{lang}" type="{ttype}">{text}</title>')
        parts.append("</anime>")
    parts.append("</animetitles>")
    return gzip.compress("".join(parts).encode("utf-8"))


@pytest.mark.asyncio
async def test_same_title_on_two_anime_stays_ambiguous(db_session) -> None:
    """A remake and its original share a title. Collapsing them by title
    would leave a single 100-point candidate and auto-assign one of them."""
    await import_title_dump(
        db_session,
        _dump(
            (100, [("Hunter x Hunter", "x-jat", "main")]),
            (200, [("Hunter x Hunter", "x-jat", "main")]),
        ),
    )

    candidates = await fuzzy_match(db_session, "Hunter x Hunter")

    assert {c.aid for c in candidates[:2]} == {100, 200}
    assert candidates[0].score == candidates[1].score


@pytest.mark.asyncio
async def test_synonyms_of_one_anime_are_one_candidate(db_session) -> None:
    await import_title_dump(
        db_session,
        _dump(
            (1, [("Shingeki no Kyojin", "x-jat", "main"), ("Shingeki no Kyojin", "en", "synonym")]),
        ),
    )

    candidates = await fuzzy_match(db_session, "Shingeki no Kyojin")

    assert [c.aid for c in candidates] == [1]


@pytest.mark.asyncio
async def test_extra_word_in_folder_name_still_finds_the_title(db_session) -> None:
    await import_title_dump(db_session, _dump((5, [("Fate Zero", "x-jat", "main")])))

    candidates = await fuzzy_match(db_session, "Fate Zero Dub")

    assert candidates and candidates[0].aid == 5


@pytest.mark.asyncio
async def test_title_dump_is_refreshed_when_stale(test_engine, monkeypatch) -> None:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(titledump, "session_scope", lambda: factory())
    downloads: list[int] = []

    async def fake_download(client) -> bytes:
        downloads.append(1)
        return _dump((7, [("New Show", "x-jat", "main")]))

    monkeypatch.setattr(titledump, "download_title_dump", fake_download)
    settings = Settings(data_dir="/tmp/awp-test-unused")

    async with factory() as session:
        await import_title_dump(session, _dump((1, [("Old Show", "x-jat", "main")])))
        # Imported before the timestamp existed -> treated as stale.

    await titledump.ensure_title_dump_imported(settings)
    assert len(downloads) == 1

    # Fresh now: a second start doesn't download again.
    await titledump.ensure_title_dump_imported(settings)
    assert len(downloads) == 1

    async with factory() as session:
        titles = (await session.execute(select(AnidbTitleEntry.title))).scalars().all()
        assert titles == ["New Show"]
        row = await session.get(Setting, TITLE_DUMP_IMPORTED_AT_KEY)
        row.value = time.time() - titledump.TITLE_DUMP_MAX_AGE_S - 1
        await session.commit()

    await titledump.ensure_title_dump_imported(settings)
    assert len(downloads) == 2
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(AnidbTitleEntry))).scalar_one() == 1
