from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.services.artwork import ANIINFO_FILENAME, POSTER_FILENAME, download_poster, write_aniinfo_json


@pytest.mark.asyncio
async def test_download_poster_writes_file_into_anime_dir(tmp_anime_dir) -> None:
    poster_url = "http://img7.anidb.net/pics/anime/12345.jpg"
    fake_bytes = b"\xff\xd8\xff\xe0fake-jpeg-bytes"

    with respx.mock:
        respx.get(poster_url).mock(return_value=httpx.Response(200, content=fake_bytes))
        async with httpx.AsyncClient() as client:
            filename = await download_poster(client, poster_url, tmp_anime_dir)

    assert filename == POSTER_FILENAME
    poster_file = tmp_anime_dir / POSTER_FILENAME
    assert poster_file.exists()
    assert poster_file.read_bytes() == fake_bytes


@pytest.mark.asyncio
async def test_download_poster_returns_none_on_http_error(tmp_anime_dir) -> None:
    poster_url = "http://img7.anidb.net/pics/anime/missing.jpg"

    with respx.mock:
        respx.get(poster_url).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            filename = await download_poster(client, poster_url, tmp_anime_dir)

    assert filename is None
    assert not (tmp_anime_dir / POSTER_FILENAME).exists()


def test_write_aniinfo_json_includes_full_info_and_local_library_block(tmp_anime_dir) -> None:
    full_info = {
        "anidb_id": 1,
        "primary_title": "Crest of the Stars",
        "tags": [{"anidb_tag_id": 30, "name": "space travel", "weight": 600}],
        "episode_count_official": 13,
    }

    path = write_aniinfo_json(
        tmp_anime_dir, full_info, episode_count_local=2, ident_status="identified", match_score=96.5
    )

    assert path == tmp_anime_dir / ANIINFO_FILENAME
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["anidb_id"] == 1
    assert written["primary_title"] == "Crest of the Stars"
    assert written["tags"] == [{"anidb_tag_id": 30, "name": "space travel", "weight": 600}]
    assert written["local_library"]["episode_count_official"] == 13
    assert written["local_library"]["episode_count_local"] == 2
    assert written["local_library"]["ident_status"] == "identified"
    assert written["local_library"]["match_score"] == 96.5
    assert "last_metadata_refresh" in written["local_library"]
