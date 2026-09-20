from __future__ import annotations

from xml.etree import ElementTree as ET

from app.services import nfo
from app.services.nfo import read_anidb_id_from_nfo, write_tvshow_nfo


def test_read_anidb_id_from_nfo_missing(tmp_anime_dir) -> None:
    assert read_anidb_id_from_nfo(tmp_anime_dir) is None


def test_read_anidb_id_from_nfo_present(tmp_anime_dir) -> None:
    (tmp_anime_dir / "tvshow.nfo").write_text(
        '<?xml version="1.0"?><tvshow><uniqueid type="anidb">17222</uniqueid></tvshow>',
        encoding="utf-8",
    )
    assert read_anidb_id_from_nfo(tmp_anime_dir) == 17222


def test_write_tvshow_nfo_roundtrip(tmp_anime_dir) -> None:
    nfo_path = write_tvshow_nfo(
        tmp_anime_dir,
        anidb_id=17222,
        title="Mushoku Tensei S2",
        original_title="Mushoku Tensei II",
        year=2021,
        description="A jobless man reincarnates.",
        tags=["isekai", "fantasy"],
    )
    assert read_anidb_id_from_nfo(tmp_anime_dir) == 17222
    content = nfo_path.read_text(encoding="utf-8")
    assert "Mushoku Tensei S2" in content
    assert "isekai" in content and "fantasy" in content


def test_write_tvshow_nfo_merge_preserves_foreign_fields(tmp_anime_dir) -> None:
    """FA-09: writing must not destroy elements the app doesn't own."""
    nfo_path = tmp_anime_dir / "tvshow.nfo"
    nfo_path.write_text(
        '<?xml version="1.0"?><tvshow><lockdata>true</lockdata></tvshow>',
        encoding="utf-8",
    )
    write_tvshow_nfo(
        tmp_anime_dir,
        anidb_id=1,
        title="Fate Zero",
        original_title=None,
        year=2011,
        description=None,
        tags=[],
    )
    content = nfo_path.read_text(encoding="utf-8")
    assert "<lockdata>true</lockdata>" in content
    assert "Fate Zero" in content


def test_write_tvshow_nfo_replaces_stale_anidb_uniqueid(tmp_anime_dir) -> None:
    write_tvshow_nfo(
        tmp_anime_dir, anidb_id=1, title="A", original_title=None, year=None, description=None, tags=[]
    )
    write_tvshow_nfo(
        tmp_anime_dir, anidb_id=2, title="B", original_title=None, year=None, description=None, tags=[]
    )
    assert read_anidb_id_from_nfo(tmp_anime_dir) == 2


def test_write_episode_nfo_creates_jellyfin_episodedetails(tmp_path) -> None:
    episode = tmp_path / "Show - S01E05 - Awakening.mkv"
    episode.write_bytes(b"video")

    written = nfo.write_episode_nfo(episode, title="Awakening", ep_number="5", anidb_id=17222)

    nfo_path = tmp_path / "Show - S01E05 - Awakening.nfo"
    assert written is True
    root = ET.parse(nfo_path).getroot()
    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Awakening"
    assert root.findtext("episode") == "5"
    uid = root.find("uniqueid")
    assert uid.get("type") == "anidb"
    assert uid.text == "17222"


def test_write_episode_nfo_falls_back_to_generic_title(tmp_path) -> None:
    episode = tmp_path / "ep.mkv"
    episode.write_bytes(b"video")

    nfo.write_episode_nfo(episode, title=None, ep_number="7", anidb_id=1)

    assert ET.parse(tmp_path / "ep.nfo").getroot().findtext("title") == "Episode 7"


def test_write_episode_nfo_skips_rewriting_identical_content(tmp_path) -> None:
    """There is one of these per episode, so a library-wide refresh would
    otherwise mean tens of thousands of pointless writes over a network share
    on every pass."""
    episode = tmp_path / "ep.mkv"
    episode.write_bytes(b"video")
    assert nfo.write_episode_nfo(episode, title="A", ep_number="1", anidb_id=1) is True

    nfo_path = tmp_path / "ep.nfo"
    mtime_before = nfo_path.stat().st_mtime_ns

    assert nfo.write_episode_nfo(episode, title="A", ep_number="1", anidb_id=1) is False
    assert nfo_path.stat().st_mtime_ns == mtime_before

    # A changed episode title does get written through.
    assert nfo.write_episode_nfo(episode, title="B", ep_number="1", anidb_id=1) is True
    assert ET.parse(nfo_path).getroot().findtext("title") == "B"
