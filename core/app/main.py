from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    animes,
    folders,
    maintenance,
    pending_actions,
    rename_queue,
    settings_api,
    sort_queue,
    tags,
    ws,
)
from app.api.animes import review_router
from app.api.errors import register_error_handlers
from app.auth import require_token
from app.config import get_settings
from app.logging_config import configure_logging
from app.providers.anidb import AniDBProvider
from app.providers.base import ProviderRegistry
from app.services import pending_actions as pending_actions_service
from app.services.jobs import EventBus, JobQueue
from app.services.scanner import ScannerService
from app.services.titledump import ensure_title_dump_imported
from app.services.titles import run_startup_title_backfill
from app.state import AppState

# A PyInstaller --onefile build extracts itself (plus --add-data, i.e.
# alembic.ini and alembic/) into a temp dir at each startup, exposed via
# sys._MEIPASS -- alembic.ini/alembic/ live there instead of next to this
# source file, so frozen mode needs its own base path.
if getattr(sys, "frozen", False):
    CORE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    CORE_DIR = Path(__file__).resolve().parents[1]

configure_logging(get_settings())

logger = structlog.get_logger(__name__)


def run_migrations() -> None:
    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # alembic's async env.py drives its own asyncio.run(); this must not nest
    # inside uvicorn's already-running loop, so it runs on a separate thread.
    await asyncio.to_thread(run_migrations)
    # alembic/env.py calls logging.config.fileConfig(), which replaces the
    # root logger's handlers wholesale -- re-apply ours or every log after
    # this point (including core_started below) silently stops reaching
    # logs/core.log.
    configure_logging(settings)

    event_bus = EventBus()
    # Must be wired before anything can publish: the nav badge's cached total
    # goes stale the moment an anime is discovered/identified/sorted/removed.
    pending_actions_service.register_invalidation(event_bus)
    job_queue = JobQueue(event_bus)
    provider_registry = ProviderRegistry()
    anidb_provider = AniDBProvider(settings)
    await anidb_provider.load_ban_state()  # restore an active ban across restarts
    provider_registry.register(anidb_provider)
    scanner = ScannerService(settings, provider_registry, event_bus, job_queue)

    app.state.awp = AppState(
        settings=settings,
        event_bus=event_bus,
        job_queue=job_queue,
        provider_registry=provider_registry,
        scanner=scanner,
    )

    job_queue.start()
    job_queue.enqueue("titledump_import", lambda: ensure_title_dump_imported(settings))
    # Before the scans and rescans: they read and write the same titles, and
    # the rename queue must never be computed from the pre-variant ones.
    job_queue.enqueue("title_backfill", lambda: run_startup_title_backfill(settings, event_bus))
    await scanner.start()
    logger.info("core_started", data_dir=str(settings.data_dir))

    yield

    await scanner.stop()
    await job_queue.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="AnimeWatcherPlus Core", version="0.1.2", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    protected = Depends(require_token)
    app.include_router(folders.router, dependencies=[protected])
    app.include_router(animes.router, dependencies=[protected])
    app.include_router(animes.public_router)  # no bearer auth: <img> can't send headers
    app.include_router(review_router, dependencies=[protected])
    app.include_router(tags.router, dependencies=[protected])
    app.include_router(settings_api.router, dependencies=[protected])
    app.include_router(sort_queue.router, dependencies=[protected])
    app.include_router(rename_queue.router, dependencies=[protected])
    app.include_router(pending_actions.router, dependencies=[protected])
    app.include_router(maintenance.router, dependencies=[protected])
    app.include_router(ws.router)

    return app


app = create_app()
