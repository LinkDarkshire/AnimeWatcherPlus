from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.completeness import CompletenessRepo, MissingEpisode
from app.db.models import (
    Anime,
    DownloadIntegration,
    DownloadRequest,
    ExpectedEpisode,
    Folder,
    WishlistEntry,
)
from app.downloads.base import (
    DownloadClient,
    DownloadStatus,
    NothingFound,
    PluginError,
    SearchQuery,
    SearchResult,
    SearchSource,
    SeriesHit,
    SettingField,
    TwoStageSearchSource,
    _Plugin,
)
from app.downloads.registry import DownloadPluginRegistry, kind_of
from app.services import wishlist
from app.services.sorter import sanitize_filename_component

logger = structlog.get_logger(__name__)


class DownloadError(Exception):
    """A request the download service can't carry out; the message is meant
    for the user."""


# --- Configured instances ------------------------------------------------------


def _coerce(field_: SettingField, value: Any) -> Any:
    if value is None or value == "":
        return None
    if field_.type == "bool":
        if isinstance(value, bool):
            return value
        raise DownloadError(f"'{field_.label}' muss Ja/Nein sein")
    if field_.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DownloadError(f"'{field_.label}' muss eine Zahl sein")
        return value
    if not isinstance(value, str):
        raise DownloadError(f"'{field_.label}' muss Text sein")
    return value.strip() or None


def validate_config(
    plugin_class: type[_Plugin], values: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Keeps only declared keys, checks their types and required fields. A
    password left empty keeps the stored one -- the UI never receives it, so
    it can't send it back."""
    previous = previous or {}
    config: dict[str, Any] = {}
    for field_ in plugin_class.settings_schema:
        value = _coerce(field_, values.get(field_.key))
        if value is None and field_.type == "password":
            value = previous.get(field_.key)
        if value is None and field_.required:
            raise DownloadError(f"'{field_.label}' ist ein Pflichtfeld")
        if value is not None:
            config[field_.key] = value
    return config


def public_config(plugin_class: type[_Plugin] | None, config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The config as the UI may see it: stored passwords are blanked and only
    reported as "set"."""
    secret_keys = {f.key for f in plugin_class.settings_schema if f.type == "password"} if plugin_class else set()
    visible = {k: v for k, v in config.items() if k not in secret_keys}
    return visible, sorted(k for k in secret_keys if config.get(k))


def instantiate(registry: DownloadPluginRegistry, integration: DownloadIntegration) -> _Plugin:
    plugin_class = registry.get(integration.plugin_id)
    if plugin_class is None:
        raise DownloadError(f"Plugin '{integration.plugin_id}' ist nicht (mehr) installiert")
    return plugin_class(dict(integration.config or {}))


async def _enabled(session: AsyncSession, registry: DownloadPluginRegistry, kind: str) -> list[DownloadIntegration]:
    rows = (
        await session.execute(
            select(DownloadIntegration).where(DownloadIntegration.enabled.is_(True)).order_by(DownloadIntegration.name)
        )
    ).scalars()
    return [
        row
        for row in rows
        if (plugin_class := registry.get(row.plugin_id)) is not None and kind_of(plugin_class) == kind
    ]


# --- What's wanted ---------------------------------------------------------------


@dataclass
class RequestInfo:
    requested_at: dt.datetime
    client_name: str


@dataclass
class WantedEpisode:
    ep_number: str
    title: str | None
    air_date: dt.date | None
    last_request: RequestInfo | None


@dataclass
class WantedAnime:
    anime_id: int
    title: str
    year: int | None
    media_type: str | None
    episodes: list[WantedEpisode]


@dataclass
class WantedWishlistItem:
    entry_id: int
    anidb_id: int
    title: str
    year: int | None
    media_type: str | None
    episode_count: int | None
    last_request: RequestInfo | None


@dataclass
class Wanted:
    missing: list[WantedAnime] = field(default_factory=list)
    wishlist: list[WantedWishlistItem] = field(default_factory=list)


def _has_aired(
    episode: MissingEpisode, anime_has_dates: bool, latest_aired: int | None, today: dt.date
) -> bool:
    """Only episodes that are out can be downloaded. AniDB often lists
    upcoming episodes without a date -- an undated one only counts when an
    episode at or after it has already aired (an old gap AniDB never
    dated), or when the anime carries no dates at all (older titles)."""
    if not anime_has_dates:
        return True
    if episode.air_date is not None:
        return episode.air_date <= today
    return latest_aired is not None and int(episode.ep_number) <= latest_aired


async def wanted(session: AsyncSession, today: dt.date | None = None) -> Wanted:
    today = today or dt.date.today()
    missing = await CompletenessRepo(session).all_missing()

    number = cast(ExpectedEpisode.ep_number, Integer)
    latest_aired = dict(
        (
            await session.execute(
                select(ExpectedEpisode.anime_id, func.max(number))
                .where(ExpectedEpisode.air_date.is_not(None), ExpectedEpisode.air_date <= today)
                .group_by(ExpectedEpisode.anime_id)
            )
        ).all()
    )
    has_dates = set(
        (
            await session.execute(
                select(ExpectedEpisode.anime_id).where(ExpectedEpisode.air_date.is_not(None)).distinct()
            )
        ).scalars()
    )

    requests: dict[tuple[str, int, str | None], RequestInfo] = {}
    for row in (await session.execute(select(DownloadRequest).order_by(DownloadRequest.created_at))).scalars():
        info = RequestInfo(requested_at=row.created_at, client_name=row.client_name)
        if row.anime_id is not None:
            requests[("anime", row.anime_id, row.episode)] = info
        if row.wishlist_entry_id is not None:
            requests[("wish", row.wishlist_entry_id, None)] = info

    episodes_by_anime: dict[int, list[WantedEpisode]] = {}
    for anime_id, episode in missing:
        if not _has_aired(episode, anime_id in has_dates, latest_aired.get(anime_id), today):
            continue
        key = str(int(episode.ep_number))
        episodes_by_anime.setdefault(anime_id, []).append(
            WantedEpisode(
                ep_number=key,
                title=episode.title,
                air_date=episode.air_date,
                last_request=requests.get(("anime", anime_id, key)),
            )
        )

    result = Wanted()
    if episodes_by_anime:
        animes = (
            await session.execute(
                select(Anime.id, Anime.title, Anime.year, Anime.media_type)
                .where(Anime.id.in_(episodes_by_anime))
                .order_by(Anime.title.collate("NOCASE"))
            )
        ).all()
        result.missing = [
            WantedAnime(
                anime_id=a.id, title=a.title, year=a.year, media_type=a.media_type, episodes=episodes_by_anime[a.id]
            )
            for a in animes
        ]

    result.wishlist = [
        WantedWishlistItem(
            entry_id=item.id,
            anidb_id=item.anidb_id,
            title=item.title,
            year=item.year,
            media_type=item.media_type,
            episode_count=item.episode_count,
            last_request=requests.get(("wish", item.id, None)),
        )
        for item in await wishlist.list_items(session)
        if item.library_anime_id is None
    ]
    return result


# --- Search --------------------------------------------------------------------


@dataclass
class Target:
    """What a search or a download is for: an episode of a library anime, or
    a wishlist series as a whole."""

    title: str
    titles: list[str]
    anidb_id: int | None
    anime_id: int | None = None
    wishlist_entry_id: int | None = None
    episode: int | None = None

    @property
    def package_name(self) -> str:
        """Readable name for the download, also used as a folder name by some
        clients -- so without characters like ? or * that folders can't have."""
        name = f"{self.title} - {self.episode:02d}" if self.episode is not None else self.title
        return sanitize_filename_component(name)


async def resolve_target(
    session: AsyncSession, *, anime_id: int | None, wishlist_entry_id: int | None, episode: int | None
) -> Target:
    if (anime_id is None) == (wishlist_entry_id is None):
        raise DownloadError("Genau eins von anime_id und wishlist_entry_id angeben")
    if anime_id is not None:
        anime = await session.get(Anime, anime_id)
        if anime is None:
            raise DownloadError("Anime nicht gefunden")
        names = [anime.title, anime.title_main, anime.title_en, *(anime.alt_titles or [])]
        return Target(
            title=anime.title,
            titles=list(dict.fromkeys(n for n in names if n)),
            anidb_id=anime.anidb_id,
            anime_id=anime.id,
            episode=episode,
        )
    entry = await session.get(WishlistEntry, wishlist_entry_id)
    if entry is None:
        raise DownloadError("Wunschlisten-Eintrag nicht gefunden")
    return Target(
        title=entry.title, titles=[entry.title], anidb_id=entry.anidb_id, wishlist_entry_id=entry.id, episode=episode
    )


@dataclass
class SourceResult:
    source_name: str
    result: SearchResult


@dataclass
class SourceSeries:
    """A series hit of a two-stage source the user still has to pick."""

    integration_id: int
    source_name: str
    hit: SeriesHit


@dataclass
class SearchOutcome:
    results: list[SourceResult] = field(default_factory=list)
    series: list[SourceSeries] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    # Not errors, just information (NothingFound: which terms were tried).
    notes: dict[str, str] = field(default_factory=dict)


async def _guarded(outcome: SearchOutcome, source_name: str, coro: Any) -> Any:
    """Runs one source call; any failure becomes an entry in
    `outcome.errors` instead of an exception, so other sources' results
    survive it."""
    try:
        return await asyncio.wait_for(coro, timeout=60)
    except NothingFound as exc:
        outcome.notes[source_name] = str(exc)
    except PluginError as exc:
        outcome.errors[source_name] = str(exc)
    except TimeoutError:
        outcome.errors[source_name] = "Zeitüberschreitung"
    except Exception as exc:  # user plugin code: any failure is reported, never raised
        logger.exception("search_source_failed", source=source_name)
        outcome.errors[source_name] = f"Interner Fehler: {type(exc).__name__}: {exc}"
    return None


async def search(session: AsyncSession, registry: DownloadPluginRegistry, target: Target) -> SearchOutcome:
    """Asks every enabled search source at once. One failing or slow source
    doesn't cost the others' results -- its error is reported next to
    them."""
    query = SearchQuery(titles=target.titles, anidb_id=target.anidb_id, episode=target.episode)
    sources = await _enabled(session, registry, "source")
    outcome = SearchOutcome()

    async def run(integration: DownloadIntegration) -> None:
        plugin = instantiate(registry, integration)
        assert isinstance(plugin, SearchSource)
        name = integration.name
        try:
            if isinstance(plugin, TwoStageSearchSource):
                hits = await _guarded(outcome, name, plugin.search_series(query)) or []
                if len(hits) == 1:
                    # Unambiguous: skip the pick and go straight to the releases.
                    results = await _guarded(outcome, name, plugin.list_releases(hits[0], query)) or []
                    outcome.results.extend(SourceResult(source_name=name, result=r) for r in results)
                else:
                    outcome.series.extend(
                        SourceSeries(integration_id=integration.id, source_name=name, hit=hit) for hit in hits
                    )
            else:
                results = await _guarded(outcome, name, plugin.search(query)) or []
                outcome.results.extend(SourceResult(source_name=name, result=r) for r in results)
        finally:
            await plugin.close()

    await asyncio.gather(*(run(integration) for integration in sources))
    return outcome


async def releases(
    session: AsyncSession,
    registry: DownloadPluginRegistry,
    target: Target,
    integration_id: int,
    hit: SeriesHit,
) -> SearchOutcome:
    """Step 2 of a two-stage source, after the user picked a series."""
    integration = await session.get(DownloadIntegration, integration_id)
    if integration is None:
        raise DownloadError("Quelle nicht gefunden")
    plugin = instantiate(registry, integration)
    if not isinstance(plugin, TwoStageSearchSource):
        await plugin.close()
        raise DownloadError(f"'{integration.name}' hat keine Serienauswahl")
    query = SearchQuery(titles=target.titles, anidb_id=target.anidb_id, episode=target.episode)
    outcome = SearchOutcome()
    try:
        results = await _guarded(outcome, integration.name, plugin.list_releases(hit, query)) or []
    finally:
        await plugin.close()
    outcome.results.extend(SourceResult(source_name=integration.name, result=r) for r in results)
    return outcome


# --- Send ------------------------------------------------------------------------


async def _destination(session: AsyncSession, folder_id: int | None) -> Folder | None:
    """The download folder the files should land in, so the scanner sees
    them. Without an explicit choice: the (first) active download folder."""
    if folder_id is not None:
        folder = await session.get(Folder, folder_id)
        if folder is None or folder.type != "download":
            raise DownloadError("Ziel ist kein Download-Ordner")
        return folder
    return await session.scalar(
        select(Folder)
        .where(Folder.type == "download", Folder.active.is_(True))
        .order_by(Folder.created_at)
        .limit(1)
    )


async def send(
    session: AsyncSession,
    registry: DownloadPluginRegistry,
    *,
    client_integration_id: int,
    link: str,
    target: Target,
    folder_id: int | None = None,
) -> DownloadRequest:
    link = link.strip()
    if not link:
        raise DownloadError("Kein Link angegeben")
    integration = await session.get(DownloadIntegration, client_integration_id)
    if integration is None:
        raise DownloadError("Download-Client nicht gefunden")
    plugin = instantiate(registry, integration)
    if not isinstance(plugin, DownloadClient):
        raise DownloadError(f"'{integration.name}' ist kein Download-Client")
    destination = await _destination(session, folder_id)
    try:
        if not plugin.accepts(link):
            raise DownloadError(f"'{integration.name}' kann diesen Link nicht verarbeiten")
        handle = await plugin.add(
            link, destination=destination.path if destination else None, package_name=target.package_name
        )
    finally:
        await plugin.close()

    request = DownloadRequest(
        anime_id=target.anime_id,
        wishlist_entry_id=target.wishlist_entry_id,
        episode=str(target.episode) if target.episode is not None else None,
        title=target.package_name,
        link=link,
        client_name=integration.name,
        client_integration_id=integration.id,
        external_id=handle if isinstance(handle, str) and handle else None,
        folder_id=destination.id if destination else None,
    )
    session.add(request)
    await session.commit()
    logger.info("download_requested", client=integration.name, title=target.package_name)
    return request


# --- Progress ----------------------------------------------------------------------

ACTIVE_WINDOW = dt.timedelta(days=14)


@dataclass
class ActiveDownload:
    request_id: int
    title: str
    client_name: str
    requested_at: dt.datetime
    anime_id: int | None
    wishlist_entry_id: int | None
    status: DownloadStatus


async def _recent(session: AsyncSession, now: dt.datetime) -> list[DownloadRequest]:
    """Everything sent in the last two weeks and not hidden."""
    return list(
        (
            await session.execute(
                select(DownloadRequest)
                .where(DownloadRequest.dismissed.is_(False), DownloadRequest.created_at >= now - ACTIVE_WINDOW)
                .order_by(DownloadRequest.created_at.desc())
            )
        ).scalars()
    )


async def _with_client(
    session: AsyncSession, registry: DownloadPluginRegistry, integration_id: int
) -> tuple[DownloadIntegration | None, DownloadClient | str]:
    """The configured client, or why there is none."""
    integration = await session.get(DownloadIntegration, integration_id)
    if integration is None:
        return None, "Client wurde entfernt"
    try:
        plugin = instantiate(registry, integration)
    except DownloadError as exc:
        return integration, str(exc)
    if not isinstance(plugin, DownloadClient):
        return integration, "Kein Download-Client"
    return integration, plugin


async def poll_statuses(
    session: AsyncSession, registry: DownloadPluginRegistry, rows: list[DownloadRequest]
) -> dict[int, DownloadStatus]:
    """Live progress for these requests. One status call per client, for all
    of its downloads at once; a client that can't be reached marks its
    downloads as unknown instead of failing everything."""
    statuses: dict[int, DownloadStatus] = {}
    by_client: dict[int, list[DownloadRequest]] = {}
    for row in rows:
        if row.client_integration_id is not None and row.external_id:
            by_client.setdefault(row.client_integration_id, []).append(row)
        else:
            statuses[row.id] = DownloadStatus("unknown", message="Dieser Client meldet keinen Fortschritt")

    async def poll(integration_id: int, requests: list[DownloadRequest]) -> None:
        def mark_all(message: str) -> None:
            for r in requests:
                statuses[r.id] = DownloadStatus("unknown", message=message)

        integration, plugin = await _with_client(session, registry, integration_id)
        if isinstance(plugin, str) or integration is None:
            mark_all(plugin if isinstance(plugin, str) else "Client wurde entfernt")
            return
        try:
            found = await asyncio.wait_for(plugin.status([r.external_id or "" for r in requests]), timeout=30)
        except PluginError as exc:
            mark_all(f"Status nicht abrufbar: {exc}")
            return
        except TimeoutError:
            mark_all("Status nicht abrufbar: Zeitüberschreitung")
            return
        except Exception as exc:  # user plugin code
            logger.exception("download_status_failed", client=integration.name)
            mark_all(f"Status nicht abrufbar: {type(exc).__name__}: {exc}")
            return
        finally:
            await plugin.close()
        for r in requests:
            statuses[r.id] = found.get(r.external_id or "") or DownloadStatus(
                "unknown", message=f"Nicht (mehr) in {integration.name} gefunden"
            )

    # Sequential, not gathered: the clients share this request's DB session.
    for integration_id, requests in by_client.items():
        await poll(integration_id, requests)
    return statuses


async def active_downloads(
    session: AsyncSession, registry: DownloadPluginRegistry, now: dt.datetime | None = None
) -> list[ActiveDownload]:
    """Everything sent in the last two weeks and not hidden, with live
    progress from its client (also when it runs in a container elsewhere)."""
    rows = await _recent(session, now or dt.datetime.now(dt.UTC))
    statuses = await poll_statuses(session, registry, rows)
    return [
        ActiveDownload(
            request_id=row.id,
            title=row.title,
            client_name=row.client_name,
            requested_at=row.created_at,
            anime_id=row.anime_id,
            wishlist_entry_id=row.wishlist_entry_id,
            status=statuses[row.id],
        )
        for row in rows
    ]


DONE_STATES = ("finished", "seeding")


@dataclass
class ClearResult:
    hidden: int = 0
    removed_from_clients: int = 0
    errors: list[str] = field(default_factory=list)


async def clear_finished(session: AsyncSession, registry: DownloadPluginRegistry) -> ClearResult:
    """Hides every download that is done, and removes the finished ones from
    their client's list too (seeding torrents stay in the client)."""
    result = ClearResult()
    rows = await _recent(session, dt.datetime.now(dt.UTC))
    statuses = await poll_statuses(session, registry, rows)
    to_remove: dict[int, list[DownloadRequest]] = {}
    for row in rows:
        state = statuses[row.id].state
        if state not in DONE_STATES:
            continue
        row.dismissed = True
        result.hidden += 1
        if state == "finished" and row.client_integration_id is not None and row.external_id:
            to_remove.setdefault(row.client_integration_id, []).append(row)
    await session.commit()

    for integration_id, requests in to_remove.items():
        integration, plugin = await _with_client(session, registry, integration_id)
        if isinstance(plugin, str) or integration is None:
            continue
        try:
            await asyncio.wait_for(plugin.remove([r.external_id or "" for r in requests]), timeout=30)
            result.removed_from_clients += len(requests)
        except Exception as exc:  # also user plugin code: the list is cleared regardless
            logger.warning("download_client_cleanup_failed", client=integration.name, error=str(exc))
            result.errors.append(f"{integration.name}: {exc}")
        finally:
            await plugin.close()
    logger.info("downloads_cleared", hidden=result.hidden, removed=result.removed_from_clients)
    return result


async def newly_finished(session: AsyncSession, registry: DownloadPluginRegistry) -> list[DownloadRequest]:
    """Downloads whose client reports them done for the first time; marks
    them, so each is reported once. Only asks clients when something is
    still pending."""
    now = dt.datetime.now(dt.UTC)
    pending = [
        row
        for row in await _recent(session, now)
        if row.finished_at is None and row.client_integration_id is not None and row.external_id
    ]
    if not pending:
        return []
    statuses = await poll_statuses(session, registry, pending)
    done = [row for row in pending if statuses[row.id].state in DONE_STATES]
    for row in done:
        row.finished_at = now
    if done:
        await session.commit()
    return done


async def dismiss(session: AsyncSession, request_id: int) -> bool:
    row = await session.get(DownloadRequest, request_id)
    if row is None:
        return False
    row.dismissed = True
    await session.commit()
    return True
