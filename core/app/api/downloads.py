from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.db.models import DownloadIntegration
from app.downloads import service
from app.downloads.base import PluginError
from app.downloads.registry import kind_of
from app.state import AppState

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
            )
            for plugin_id, cls in sorted(registry.classes.items(), key=lambda item: item[1].name.casefold())
        ],
        load_errors=[PluginLoadErrorOut(**asdict(e)) for e in registry.load_errors],
        plugins_folder=str(state.settings.plugins_dir),
    )


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
        plugin = service.instantiate(state.download_plugins, integration)
    except service.DownloadError as exc:
        return TestResult(ok=False, message=str(exc))
    try:
        await plugin.test_connection()
    except PluginError as exc:
        return TestResult(ok=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - user plugin code
        return TestResult(ok=False, message=f"Interner Fehler: {type(exc).__name__}: {exc}")
    finally:
        await plugin.close()
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


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
    errors: dict[str, str]


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
            )
            for r in outcome.results
        ],
        errors=outcome.errors,
    )


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
