from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.models import DownloadIntegration
from app.downloads import service
from app.downloads.base import PluginError, SeriesHit
from app.downloads.isolation import run_plugin
from app.downloads.registry import build_registry, kind_of
from app.state import AppState

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/downloads", tags=["downloads"])


# --- Plugins & configured integrations ---------------------------------------------


class SettingFieldOut(BaseModel):
    key: str
    label: str
    type: str
    default: Any
    required: bool
    help: str | None


class PluginOut(BaseModel):
    id: str
    kind: str
    name: str
    description: str
    builtin: bool
    settings_schema: list[SettingFieldOut]
    # The file in the plugins folder; None for built-in plugins.
    file: str | None = None


class PluginLoadErrorOut(BaseModel):
    file: str
    error: str


class PluginsResponse(BaseModel):
    plugins: list[PluginOut]
    load_errors: list[PluginLoadErrorOut]
    plugins_folder: str


class IntegrationOut(BaseModel):
    id: int
    plugin_id: str
    kind: str | None  # None: its plugin is no longer installed
    name: str
    enabled: bool
    config: dict[str, Any]
    secrets_set: list[str]


class IntegrationCreate(BaseModel):
    plugin_id: str
    name: str
    enabled: bool = True
    config: dict[str, Any] = {}


class IntegrationUpdate(BaseModel):
    name: str
    enabled: bool
    config: dict[str, Any] = {}


class TestResult(BaseModel):
    ok: bool
    message: str


def _integration_out(state: AppState, integration: DownloadIntegration) -> IntegrationOut:
    plugin_class = state.download_plugins.get(integration.plugin_id)
    config, secrets_set = service.public_config(plugin_class, integration.config or {})
    return IntegrationOut(
        id=integration.id,
        plugin_id=integration.plugin_id,
        kind=kind_of(plugin_class) if plugin_class else None,
        name=integration.name,
        enabled=integration.enabled,
        config=config,
        secrets_set=secrets_set,
    )


@router.get("/plugins", response_model=PluginsResponse)
async def list_plugins(state: AppState = Depends(get_app_state)) -> PluginsResponse:
    registry = state.download_plugins
    return PluginsResponse(
        plugins=[
            PluginOut(
                id=plugin_id,
                kind=kind_of(cls),
                name=cls.name,
                description=cls.description,
                builtin=plugin_id in registry.builtin_ids,
                settings_schema=[SettingFieldOut(**asdict(f)) for f in cls.settings_schema],
                file=registry.files.get(plugin_id),
            )
            for plugin_id, cls in sorted(registry.classes.items(), key=lambda item: item[1].name.casefold())
        ],
        load_errors=[PluginLoadErrorOut(**asdict(e)) for e in registry.load_errors],
        plugins_folder=str(state.settings.plugins_dir),
    )


@router.post("/plugins/reload", response_model=PluginsResponse)
async def reload_plugins(state: AppState = Depends(get_app_state)) -> PluginsResponse:
    """Reads the plugins folder again -- for a plugin added or changed while
    the app (or the server) is running."""
    state.download_plugins = build_registry(state.settings.plugins_dir)
    logger.info("download_plugins_reloaded", count=len(state.download_plugins.files))
    return await list_plugins(state)


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(
    session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> list[IntegrationOut]:
    rows = (await session.execute(select(DownloadIntegration).order_by(DownloadIntegration.name))).scalars()
    return [_integration_out(state, row) for row in rows]


@router.post("/integrations", response_model=IntegrationOut, status_code=201)
async def create_integration(
    payload: IntegrationCreate,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> IntegrationOut:
    plugin_class = state.download_plugins.get(payload.plugin_id)
    if plugin_class is None:
        raise HTTPException(status_code=404, detail="Plugin nicht gefunden")
    try:
        config = service.validate_config(plugin_class, payload.config)
    except service.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    integration = DownloadIntegration(
        plugin_id=payload.plugin_id,
        name=payload.name.strip() or plugin_class.name,
        enabled=payload.enabled,
        config=config,
    )
    session.add(integration)
    await session.commit()
    return _integration_out(state, integration)


@router.put("/integrations/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: int,
    payload: IntegrationUpdate,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> IntegrationOut:
    integration = await session.get(DownloadIntegration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    plugin_class = state.download_plugins.get(integration.plugin_id)
    if plugin_class is None:
        raise HTTPException(status_code=409, detail="Das Plugin dieses Eintrags ist nicht mehr installiert")
    try:
        integration.config = service.validate_config(plugin_class, payload.config, integration.config)
    except service.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    integration.name = payload.name.strip() or plugin_class.name
    integration.enabled = payload.enabled
    await session.commit()
    return _integration_out(state, integration)


@router.delete("/integrations/{integration_id}", status_code=204)
async def delete_integration(integration_id: int, session: AsyncSession = Depends(get_db)) -> None:
    integration = await session.get(DownloadIntegration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    await session.delete(integration)
    await session.commit()


@router.post("/integrations/{integration_id}/test", response_model=TestResult)
async def test_integration(
    integration_id: int,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> TestResult:
    integration = await session.get(DownloadIntegration, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        await run_plugin(
            lambda: service.instantiate(state.download_plugins, integration),
            lambda plugin: plugin.test_connection(),
            limit_s=60,
        )
    except service.DownloadError as exc:
        return TestResult(ok=False, message=str(exc))
    except PluginError as exc:
        return TestResult(ok=False, message=str(exc))
    except TimeoutError:
        return TestResult(ok=False, message="Keine Antwort (Zeitüberschreitung)")
    except Exception as exc:
        return TestResult(ok=False, message=f"Interner Fehler: {type(exc).__name__}: {exc}")
    return TestResult(ok=True, message="Verbindung funktioniert")


# --- Wanted / search / send ---------------------------------------------------------


class RequestInfoOut(BaseModel):
    requested_at: dt.datetime
    client_name: str


class WantedEpisodeOut(BaseModel):
    ep_number: str
    title: str | None
    air_date: dt.date | None
    last_request: RequestInfoOut | None


class WantedAnimeOut(BaseModel):
    anime_id: int
    title: str
    year: int | None
    media_type: str | None
    episodes: list[WantedEpisodeOut]


class WantedWishlistOut(BaseModel):
    entry_id: int
    anidb_id: int
    title: str
    year: int | None
    media_type: str | None
    episode_count: int | None
    last_request: RequestInfoOut | None


class WantedResponse(BaseModel):
    missing: list[WantedAnimeOut]
    wishlist: list[WantedWishlistOut]


@router.get("/wanted", response_model=WantedResponse)
async def get_wanted(session: AsyncSession = Depends(get_db)) -> WantedResponse:
    """Everything worth downloading: aired episodes missing from identified
    anime, and wishlist entries that aren't in the library yet."""
    return WantedResponse.model_validate(asdict(await service.wanted(session)))


class TargetIn(BaseModel):
    anime_id: int | None = None
    wishlist_entry_id: int | None = None
    episode: int | None = None


class SearchResultOut(BaseModel):
    source_name: str
    title: str
    link: str
    size_bytes: int | None
    seeders: int | None
    published: str | None
    info_url: str | None
    hoster: str | None
    kind: str
    details: dict[str, str]
    needs_browser: bool


class SeriesHitIn(BaseModel):
    title: str
    url: str
    extra: dict[str, Any] = {}


class SeriesHitOut(SeriesHitIn):
    integration_id: int
    source_name: str


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
    # Two-stage sources with several matching series: the user picks one,
    # then POST /releases lists its links.
    series: list[SeriesHitOut]
    errors: dict[str, str]
    # Source name -> information that isn't an error (e.g. which search
    # terms were tried when nothing was found).
    notes: dict[str, str]


def _search_response(outcome: service.SearchOutcome) -> SearchResponse:
    return SearchResponse(
        results=[
            SearchResultOut(
                source_name=r.source_name,
                title=r.result.title,
                link=r.result.link,
                size_bytes=r.result.size_bytes,
                seeders=r.result.seeders,
                published=r.result.published,
                info_url=r.result.info_url,
                hoster=r.result.hoster,
                kind=r.result.kind,
                details=r.result.details,
                needs_browser=r.result.needs_browser,
            )
            for r in outcome.results
        ],
        series=[
            SeriesHitOut(
                integration_id=s.integration_id,
                source_name=s.source_name,
                title=s.hit.title,
                url=s.hit.url,
                extra=s.hit.extra,
            )
            for s in outcome.series
        ],
        errors=outcome.errors,
        notes=outcome.notes,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: TargetIn,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> SearchResponse:
    try:
        target = await service.resolve_target(session, **payload.model_dump())
    except service.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    outcome = await service.search(session, state.download_plugins, target)
    return _search_response(outcome)


class ReleasesIn(TargetIn):
    integration_id: int
    series: SeriesHitIn


@router.post("/releases", response_model=SearchResponse)
async def list_releases(
    payload: ReleasesIn,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> SearchResponse:
    """Step 2 of a two-stage source: the links on the series page the user
    picked from /search's `series`."""
    try:
        target = await service.resolve_target(
            session, anime_id=payload.anime_id, wishlist_entry_id=payload.wishlist_entry_id, episode=payload.episode
        )
        outcome = await service.releases(
            session,
            state.download_plugins,
            target,
            payload.integration_id,
            SeriesHit(title=payload.series.title, url=payload.series.url, extra=payload.series.extra),
        )
    except service.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _search_response(outcome)


class SendIn(TargetIn):
    client_id: int
    link: str
    folder_id: int | None = None


class SendResponse(BaseModel):
    title: str
    client_name: str


@router.post("/send", response_model=SendResponse)
async def send(
    payload: SendIn,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> SendResponse:
    try:
        target = await service.resolve_target(
            session, anime_id=payload.anime_id, wishlist_entry_id=payload.wishlist_entry_id, episode=payload.episode
        )
        request = await service.send(
            session,
            state.download_plugins,
            client_integration_id=payload.client_id,
            link=payload.link,
            target=target,
            folder_id=payload.folder_id,
        )
    except service.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PluginError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SendResponse(title=request.title, client_name=request.client_name)


# --- Progress ------------------------------------------------------------------------


class DownloadStatusOut(BaseModel):
    state: str
    progress: float | None
    speed_bps: int | None
    eta_seconds: int | None
    message: str | None


class ActiveDownloadOut(BaseModel):
    request_id: int
    title: str
    client_name: str
    requested_at: dt.datetime
    anime_id: int | None
    wishlist_entry_id: int | None
    status: DownloadStatusOut


@router.get("/active", response_model=list[ActiveDownloadOut])
async def get_active_downloads(
    session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> list[ActiveDownloadOut]:
    """Downloads sent in the last two weeks, with live progress from their
    clients (also when those run in a container elsewhere)."""
    return [
        ActiveDownloadOut.model_validate(asdict(item))
        for item in await service.active_downloads(session, state.download_plugins)
    ]


class ClearFinishedOut(BaseModel):
    hidden: int
    removed_from_clients: int
    errors: list[str]


@router.post("/requests/clear-finished", response_model=ClearFinishedOut)
async def clear_finished_downloads(
    session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> ClearFinishedOut:
    """Hides all downloads that are done, and removes the finished ones from
    their client's list (JDownloader, ...) as well -- the files stay."""
    return ClearFinishedOut(**asdict(await service.clear_finished(session, state.download_plugins)))


@router.post("/requests/{request_id}/dismiss", status_code=204)
async def dismiss_download(request_id: int, session: AsyncSession = Depends(get_db)) -> None:
    """Hides a download from the active list (the client isn't touched)."""
    if not await service.dismiss(session, request_id):
        raise HTTPException(status_code=404, detail="Download nicht gefunden")
