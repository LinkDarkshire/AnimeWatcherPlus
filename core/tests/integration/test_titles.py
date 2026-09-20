from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.models import Anime, Setting
from app.db.repositories import AnimeRepo, FolderRepo
from app.services import artwork
from app.services.settings_store import DISPLAY_TITLE_ORDER, get_display_title_order
from app.services.titles import resync_titles

pytestmark = pytest.mark.asyncio


async def _make_anime(
    session,
    folder_id: int,
    directory: Path,
    *,
    title: str,
    main: str | None = None,
    en: str | None = None,
    ja: str | None = None,
    anidb_id: int | None = 100,
) -> Anime:
    directory.mkdir(parents=True, exist_ok=True)
    anime = await AnimeRepo(session).create_pending(folder_id, str(directory), directory.name)
    anime.ident_status = "identified"
    anime.anidb_id = anidb_id
    anime.title = title
    anime.title_main = main
    anime.title_en = en
    anime.title_ja = ja
    await session.commit()
    return anime


async def _fts_ids_for(session, query: str) -> list[int]:
    result = await session.execute(
        text("SELECT anime_id FROM anime_search_fts WHERE anime_search_fts MATCH :q"),
        {"q": f'"{query}"*'},
    )
    return [row[0] for row in result.all()]


async def test_get_display_title_order_defaults_to_english_first(db_session) -> None:
    assert await get_display_title_order(db_session) == ["en", "main", "ja"]


async def test_get_display_title_order_normalizes_a_partial_stored_value(db_session) -> None:
    db_session.add(Setting(key=DISPLAY_TITLE_ORDER, value=["ja"]))
    await db_session.commit()
    assert await get_display_title_order(db_session) == ["ja", "en", "main"]


async def test_resync_titles_rewrites_display_title_for_new_order(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session,
        folder.id,
        tmp_path / "Show",
        title="Crest of the Stars",
        main="Seikai no Monshou",
        en="Crest of the Stars",
        ja="星界の紋章",
    )

    db_session.add(Setting(key=DISPLAY_TITLE_ORDER, value=["main", "en", "ja"]))
    await db_session.commit()
    changed = await resync_titles(db_session)

    assert changed == 1
    await db_session.refresh(anime)
    assert anime.title == "Seikai no Monshou"


async def test_resync_titles_is_idempotent(db_session, tmp_path) -> None:
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    await _make_anime(
        db_session,
        folder.id,
        tmp_path / "Show",
        title="Crest of the Stars",
        main="Seikai no Monshou",
        en="Crest of the Stars",
    )
    assert await resync_titles(db_session) == 0


async def test_resync_titles_keeps_search_finding_the_previous_title(db_session, tmp_path) -> None:
    """`alt_titles` is captured as "everything except the title that was
    primary then", so without folding the variants into the FTS text a
    reordering would make the old display name unsearchable."""
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session,
        folder.id,
        tmp_path / "Show",
        title="Crest of the Stars",
        main="Seikai no Monshou",
        en="Crest of the Stars",
    )

    db_session.add(Setting(key=DISPLAY_TITLE_ORDER, value=["main", "en", "ja"]))
    await db_session.commit()
    await resync_titles(db_session)

    assert await _fts_ids_for(db_session, "Seikai") == [anime.id]
    assert await _fts_ids_for(db_session, "Crest") == [anime.id]


async def test_resync_titles_keeps_title_when_no_variants_are_known(db_session, tmp_path) -> None:
    """Anime identified before the variant columns existed have all three
    NULL and no sidecar to recover them from -- they must keep the name they
    already have instead of resolving to nothing."""
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(db_session, folder.id, tmp_path / "Legacy", title="Legacy Title")

    db_session.add(Setting(key=DISPLAY_TITLE_ORDER, value=["ja", "main", "en"]))
    await db_session.commit()
    assert await resync_titles(db_session) == 0

    await db_session.refresh(anime)
    assert anime.title == "Legacy Title"


async def test_resync_titles_backfills_variants_from_aniinfo_sidecar(db_session, tmp_path) -> None:
    """The whole point of the sidecar backfill: an existing library gets its
    variants without a single AniDB request."""
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    directory = tmp_path / "Legacy"
    anime = await _make_anime(db_session, folder.id, directory, title="Crest of the Stars")
    (directory / artwork.ANIINFO_FILENAME).write_text(
        json.dumps(
            {
                "anidb_id": 100,
                "titles": [
                    {"language": "x-jat", "type": "main", "value": "Seikai no Monshou"},
                    {"language": "en", "type": "official", "value": "Crest of the Stars"},
                    {"language": "ja", "type": "official", "value": "星界の紋章"},
                ],
            }
        ),
        encoding="utf-8",
    )

    db_session.add(Setting(key=DISPLAY_TITLE_ORDER, value=["main", "en", "ja"]))
    await db_session.commit()
    assert await resync_titles(db_session) == 1

    await db_session.refresh(anime)
    assert anime.title == "Seikai no Monshou"
    assert anime.title_main == "Seikai no Monshou"
    assert anime.title_en == "Crest of the Stars"
    assert anime.title_ja == "星界の紋章"


async def test_resync_titles_backfills_from_the_anidb_cache_first(db_session, tmp_path) -> None:
    """The case that mattered in a real library: 410 of 426 anime had no
    variants because the staleness rule keeps them out of rescans, and their
    stored title was raw Japanese script from an older language cascade. The
    local AniDB response cache has everything needed -- no request, no share
    access."""
    from app.config import Settings
    from app.providers.anidb import cache_dir

    settings = Settings(data_dir=tmp_path / "data")
    cache_dir(settings).mkdir(parents=True)
    (cache_dir(settings) / "4242.xml").write_text(
        """<anime id="4242"><titles>
            <title xml:lang="x-jat" type="main">Tsundero</title>
            <title xml:lang="ja" type="official">ツンデロ</title>
        </titles></anime>""",
        encoding="utf-8",
    )
    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    anime = await _make_anime(
        db_session, folder.id, tmp_path / "Tsundero", title="ツンデロ", anidb_id=4242
    )

    changed = await resync_titles(db_session, settings)

    await db_session.refresh(anime)
    assert changed == 1
    assert anime.title == "Tsundero"  # no English title -> romanized main
    assert (anime.title_main, anime.title_ja) == ("Tsundero", "ツンデロ")
    assert await _fts_ids_for(db_session, "Tsundero") == [anime.id]


async def test_resync_titles_skips_anime_that_already_have_variants(db_session, tmp_path) -> None:
    """Startup runs this every time; anime with known variants must cost no
    file access at all."""
    from unittest.mock import patch

    folder = await FolderRepo(db_session).create(str(tmp_path), "content", "Content")
    await _make_anime(db_session, folder.id, tmp_path / "Show", title="Show", main="Show")

    with patch("app.services.titles._recover_variants") as recover:
        await resync_titles(db_session)

    recover.assert_not_called()
