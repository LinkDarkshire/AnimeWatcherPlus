from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
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
