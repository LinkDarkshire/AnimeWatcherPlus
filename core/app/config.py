from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "AnimeWatcherPlus"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AWP_", env_file=".env", extra="ignore")

    data_dir: Path = _default_data_dir()
    sidecar_token: str = ""
    dev_mode: bool = True

    anidb_client_name: str = "animewatcherplus"
    anidb_client_version: int = 1
    anidb_min_interval_s: float = 4.0
    anidb_daily_cap: int = 400
    # AniDB bans have no documented fixed duration (karma-based per
    # https://wiki.anidb.net/HTTP_API_Definition) -- this is a configurable
    # heuristic cool-down, not a guaranteed recovery time.
    anidb_ban_cooldown_s: float = 24 * 3600

    fuzzy_score_threshold: float = 90.0
    fuzzy_top2_delta_threshold: float = 5.0

    scan_debounce_interval_s: float = 2.0
    scan_debounce_checks: int = 2
    # Pause between anime directories during the background full-scan so it
    # stays "gemächlich" and never competes with interactive API requests.
    scan_yield_interval_s: float = 0.1

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def titledump_path(self) -> Path:
        return self.data_dir / "anime-titles.xml.gz"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.covers_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
