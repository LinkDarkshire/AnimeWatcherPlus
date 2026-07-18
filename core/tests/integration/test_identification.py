from __future__ import annotations

import gzip

import pytest
import pytest_asyncio

from app.config import Settings
from app.db.repositories import AnimeRepo, FolderRepo
from app.domain.metadata import AnimeMetadata, ProviderManifest, SearchHit, TagInfo
from app.providers.base import MetadataProvider, ProviderRegistry
from app.services import identification
from app.services.jobs import EventBus
from app.services.titledump import import_title_dump


@pytest_asyncio.fixture
async def folder_id(db_session) -> int:
    folder = await FolderRepo(db_session).create("/tmp/awp-test-content", "content", "Content")
    return folder.id


class FakeAniDBProvider(MetadataProvider):
    def __init__(
        self,
        responses: dict[str, AnimeMetadata | None],
        full_info: dict[str, dict] | None = None,
    ) -> None:
        self.manifest = ProviderManifest(plugin_id="anidb", name="AniDB", version="1.0")
        self._responses = responses
        self._full_info = full_info or {}
        self.fetch_calls: list[str] = []

    async def search(self, title: str, year: int | None) -> list[SearchHit]:
        return []

    async def fetch(self, external_id: str) -> AnimeMetadata | None:
        self.fetch_calls.append(external_id)
        return self._responses.get(external_id)

    async def get_full_info(self, external_id: str) -> dict | None:
        return self._full_info.get(external_id)


def _make_registry(
    responses: dict[str, AnimeMetadata | None], full_info: dict[str, dict] | None = None
) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(FakeAniDBProvider(responses, full_info))
    return registry


@pytest.fixture
def settings() -> Settings:
    return Settings(data_dir="/tmp/awp-test-unused")


@pytest.mark.asyncio
async def test_identify_via_nfo_uniqueid(db_session, tmp_anime_dir, settings, folder_id) -> None:
    (tmp_anime_dir / "tvshow.nfo").write_text(
        '<?xml version="1.0"?><tvshow><uniqueid type="anidb">17222</uniqueid></tvshow>',
        encoding="utf-8",
    )
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    metadata = AnimeMetadata(
        external_id="17222",
        title="Mushoku Tensei S2",
        year=2021,
        media_type="TV",
        tags=[TagInfo(name="isekai", weight=500)],
    )
    registry = _make_registry({"17222": metadata})
    event_bus = EventBus()

    result = await identification.identify_anime(
        db_session, settings, anime, tmp_anime_dir, registry, event_bus
    )

    assert result.ident_status == "identified"
    assert result.anidb_id == 17222
    assert result.title == "Mushoku Tensei S2"
    assert result.match_score is None  # NFO path bypasses fuzzy scoring
    assert (tmp_anime_dir / "tvshow.nfo").exists()


@pytest.mark.asyncio
async def test_identify_no_nfo_no_titledump_candidates_needs_manual_id(
    db_session, tmp_anime_dir, settings, folder_id
) -> None:
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    registry = _make_registry({})
    event_bus = EventBus()

    result = await identification.identify_anime(
        db_session, settings, anime, tmp_anime_dir, registry, event_bus
    )

    assert result.ident_status == "needs_manual_id"


@pytest.mark.asyncio
async def test_identify_confident_fuzzy_match(db_session, tmp_path, settings, folder_id) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><animetitles>'
        '<anime aid="17222"><title xml:lang="en" type="official">Mushoku Tensei Season 2</title></anime>'
        "</animetitles>"
    ).encode("utf-8")
    await import_title_dump(db_session, gzip.compress(xml))

    anime_dir = tmp_path / "Mushoku Tensei Season 2"
    anime_dir.mkdir()
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(anime_dir), anime_dir.name)

    metadata = AnimeMetadata(external_id="17222", title="Mushoku Tensei Season 2", media_type="TV")
    registry = _make_registry({"17222": metadata})
    event_bus = EventBus()

    result = await identification.identify_anime(db_session, settings, anime, anime_dir, registry, event_bus)

    assert result.ident_status == "identified"
    assert result.anidb_id == 17222
    assert result.match_score is not None and result.match_score >= settings.fuzzy_score_threshold


@pytest.mark.asyncio
async def test_identify_ambiguous_fuzzy_match_goes_to_review(
    db_session, tmp_path, settings, folder_id
) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><animetitles>'
        '<anime aid="1"><title xml:lang="en" type="official">Fate Zero</title></anime>'
        '<anime aid="2"><title xml:lang="en" type="official">Fate Zero Two</title></anime>'
        "</animetitles>"
    ).encode("utf-8")
    await import_title_dump(db_session, gzip.compress(xml))

    anime_dir = tmp_path / "Fate"
    anime_dir.mkdir()
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(anime_dir), anime_dir.name)

    registry = _make_registry({})
    event_bus = EventBus()

    result = await identification.identify_anime(db_session, settings, anime, anime_dir, registry, event_bus)

    assert result.ident_status in ("review", "needs_manual_id")


@pytest.mark.asyncio
async def test_manual_identify_bypasses_fuzzy_step(db_session, tmp_anime_dir, settings, folder_id) -> None:
    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    metadata = AnimeMetadata(external_id="999", title="Manually Assigned")
    registry = _make_registry({"999": metadata})
    event_bus = EventBus()

    result = await identification.manual_identify(
        db_session, settings, anime, tmp_anime_dir, 999, registry, event_bus
    )

    assert result.ident_status == "identified"
    assert result.anidb_id == 999
    assert result.title == "Manually Assigned"


@pytest.mark.asyncio
async def test_identify_downloads_poster_and_writes_aniinfo_json(
    db_session, tmp_anime_dir, settings, folder_id
) -> None:
    """User-requested feature: poster saved into the anime's own folder, plus
    an aniinfo.json sidecar holding everything AniDB returned (tags+weights,
    local vs. official episode count, ratings, ...).
    """
    import httpx
    import respx

    from app.services.artwork import ANIINFO_FILENAME, POSTER_FILENAME

    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    poster_url = "http://img7.anidb.net/pics/anime/999.jpg"
    metadata = AnimeMetadata(
        external_id="42",
        title="Test Anime",
        tags=[TagInfo(name="isekai", weight=500, anidb_tag_id=30)],
    )
    full_info = {
        "42": {
            "anidb_id": 42,
            "primary_title": "Test Anime",
            "poster_url": poster_url,
            "episode_count_official": 12,
            "tags": [{"anidb_tag_id": 30, "name": "isekai", "weight": 500}],
        }
    }
    registry = _make_registry({"42": metadata}, full_info)
    event_bus = EventBus()

    with respx.mock:
        respx.get(poster_url).mock(return_value=httpx.Response(200, content=b"fake-jpeg-bytes"))
        result = await identification.manual_identify(
            db_session, settings, anime, tmp_anime_dir, 42, registry, event_bus
        )

    assert result.poster_path == POSTER_FILENAME
    assert (tmp_anime_dir / POSTER_FILENAME).read_bytes() == b"fake-jpeg-bytes"

    aniinfo_path = tmp_anime_dir / ANIINFO_FILENAME
    assert aniinfo_path.exists()
    import json

    aniinfo = json.loads(aniinfo_path.read_text(encoding="utf-8"))
    assert aniinfo["anidb_id"] == 42
    assert aniinfo["tags"] == [{"anidb_tag_id": 30, "name": "isekai", "weight": 500}]
    assert aniinfo["local_library"]["episode_count_official"] == 12
    assert aniinfo["local_library"]["episode_count_local"] == 0
    assert aniinfo["local_library"]["ident_status"] == "identified"

    # NFO should point at the locally saved poster.
    nfo_text = (tmp_anime_dir / "tvshow.nfo").read_text(encoding="utf-8")
    assert '<thumb aspect="poster">poster.jpg</thumb>' in nfo_text


@pytest.mark.asyncio
async def test_identify_without_get_full_info_support_skips_artwork_gracefully(
    db_session, tmp_anime_dir, settings, folder_id
) -> None:
    """Providers that don't implement get_full_info (the ABC default returns
    None) must not break identification -- no poster, no aniinfo.json, but
    everything else still succeeds.
    """
    from app.services.artwork import ANIINFO_FILENAME, POSTER_FILENAME

    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    metadata = AnimeMetadata(external_id="7", title="No Full Info")
    registry = _make_registry({"7": metadata})  # full_info=None -> base class default
    event_bus = EventBus()

    result = await identification.manual_identify(
        db_session, settings, anime, tmp_anime_dir, 7, registry, event_bus
    )

    assert result.ident_status == "identified"
    assert result.poster_path is None
    assert not (tmp_anime_dir / POSTER_FILENAME).exists()
    assert not (tmp_anime_dir / ANIINFO_FILENAME).exists()


@pytest.mark.asyncio
async def test_identify_same_anidb_id_twice_flags_duplicate_instead_of_crashing(
    db_session, tmp_path, settings, folder_id
) -> None:
    """Regression test: `anidb_id` used to have a UNIQUE constraint, so a
    second folder resolving to the same AniDB ID (a real, legitimate
    scenario -- e.g. the same series copied into two places) crashed the
    identify job with sqlite3.IntegrityError instead of being flagged
    per FA-29.
    """
    anime_repo = AnimeRepo(db_session)

    dir_a = tmp_path / "Show Copy A"
    dir_a.mkdir()
    dir_b = tmp_path / "Show Copy B"
    dir_b.mkdir()
    anime_a = await anime_repo.create_pending(folder_id, str(dir_a), dir_a.name)
    anime_b = await anime_repo.create_pending(folder_id, str(dir_b), dir_b.name)

    metadata = AnimeMetadata(external_id="555", title="Same Anime")
    registry = _make_registry({"555": metadata})
    event_bus = EventBus()

    result_a = await identification.manual_identify(
        db_session, settings, anime_a, dir_a, 555, registry, event_bus
    )
    assert result_a.is_duplicate is False

    # Must not raise -- this is the exact scenario that used to crash the job.
    result_b = await identification.manual_identify(
        db_session, settings, anime_b, dir_b, 555, registry, event_bus
    )
    assert result_b.anidb_id == 555
    assert result_b.is_duplicate is True
    assert result_b.duplicate_of_anime_id == anime_a.id


@pytest.mark.asyncio
async def test_identify_falls_back_to_review_if_db_still_rejects_duplicate_anidb_id(
    db_session, tmp_anime_dir, settings, folder_id, monkeypatch
) -> None:
    """Defense-in-depth: even if a live database somehow still enforces
    UNIQUE(anidb_id) despite the schema fix (the exact real-world report
    that motivated migration 280262530db1 -- two processes migrating the
    same SQLite file at once left one database stuck with the old
    constraint), the identify job must degrade to a Review-Queue entry
    instead of crashing.

    The mock triggers a *real* flush-time IntegrityError (inserting two
    Tag rows with the same anidb_tag_id) rather than raising immediately:
    an immediate raise leaves the session with nothing dirty, so
    session.rollback() is close to a no-op and doesn't reproduce a second,
    related bug -- rollback expires every attribute on every object in the
    session, so a later plain `anime.id` access (not awaited) tries to
    lazily reload it and blows up with `MissingGreenlet` outside a valid
    async bridge context, unless the id is captured *before* the rollback.
    """

    from app.db.models import Tag
    from app.db.repositories import AnimeRepo as AnimeRepoClass

    original_apply_identification = AnimeRepoClass.apply_identification

    async def _fail_with_real_integrity_error(self, anime_id, **kwargs):
        self.session.add(Tag(name="dup-a", anidb_tag_id=999))
        self.session.add(Tag(name="dup-b", anidb_tag_id=999))
        await self.session.flush()  # raises a genuine IntegrityError
        return await original_apply_identification(self, anime_id, **kwargs)  # pragma: no cover

    monkeypatch.setattr(AnimeRepoClass, "apply_identification", _fail_with_real_integrity_error)

    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    metadata = AnimeMetadata(external_id="777", title="Conflicted Anime")
    registry = _make_registry({"777": metadata})
    event_bus = EventBus()

    # Must not raise (neither IntegrityError nor MissingGreenlet).
    result = await identification.manual_identify(
        db_session, settings, anime, tmp_anime_dir, 777, registry, event_bus
    )

    assert result.ident_status == "review"
    assert result.review_candidates == [{"aid": 777, "title": "Conflicted Anime", "score": 0.0}]


@pytest.mark.asyncio
async def test_identify_syncs_renamed_anidb_tag_instead_of_crashing(
    db_session, tmp_anime_dir, settings, folder_id
) -> None:
    """Regression test: a real crash report showed `UNIQUE constraint
    failed: tag.anidb_tag_id`. _get_or_create_tag used to look up an
    existing tag by *name*, so a tag AniDB renamed (or that differs only in
    case between two imports) wasn't found by its new name, and inserting a
    second row for the same anidb_tag_id hit the UNIQUE constraint.
    """
    from sqlalchemy import select

    from app.db.models import Tag

    db_session.add(Tag(name="old-tag-name", anidb_tag_id=2702))
    await db_session.commit()

    anime_repo = AnimeRepo(db_session)
    anime = await anime_repo.create_pending(folder_id, str(tmp_anime_dir), tmp_anime_dir.name)

    metadata = AnimeMetadata(
        external_id="888",
        title="Renamed Tag Anime",
        tags=[TagInfo(name="boobjob", weight=300, anidb_tag_id=2702)],
    )
    registry = _make_registry({"888": metadata})
    event_bus = EventBus()

    # Must not raise.
    result = await identification.manual_identify(
        db_session, settings, anime, tmp_anime_dir, 888, registry, event_bus
    )
    assert result.ident_status == "identified"

    # result.tags is a lazy relationship not eager-loaded on the object
    # apply_identification returns; re-fetch through AnimeRepo.get(), which
    # eager-loads it, rather than lazy-loading on an AsyncSession object
    # outside a valid context.
    reloaded = await anime_repo.get(result.id)
    assert [at.tag.name for at in reloaded.tags] == ["boobjob"]

    # Exactly one Tag row for anidb_tag_id=2702, renamed in place.
    tags = (await db_session.execute(select(Tag).where(Tag.anidb_tag_id == 2702))).scalars().all()
    assert len(tags) == 1
    assert tags[0].name == "boobjob"
