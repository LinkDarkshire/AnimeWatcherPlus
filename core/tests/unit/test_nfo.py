from __future__ import annotations

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
