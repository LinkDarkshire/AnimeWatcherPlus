from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.downloads.registry import DownloadPluginRegistry, build_registry
from app.providers.base import ProviderRegistry
from app.services.jobs import EventBus, JobQueue
from app.services.scanner import ScannerService


@dataclass
class AppState:
    settings: Settings
    event_bus: EventBus
    job_queue: JobQueue
    provider_registry: ProviderRegistry
    scanner: ScannerService
    # Built-ins only by default; main.py builds it with the plugins folder.
    download_plugins: DownloadPluginRegistry = field(default_factory=lambda: build_registry(None))
