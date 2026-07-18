from __future__ import annotations

from pydantic import BaseModel


class ProviderManifest(BaseModel):
    plugin_id: str
    name: str
    version: str
    min_app_version: str = "0.1.0"
    min_interval_s: float = 0.0
    daily_cap: int | None = None


class TagInfo(BaseModel):
    name: str
    weight: int = 0
    anidb_tag_id: int | None = None
    description: str | None = None


class EpisodeInfo(BaseModel):
    ep_number: str
    title: str | None = None
    air_date: str | None = None  # ISO date string


class SearchHit(BaseModel):
    external_id: str
    title: str
    year: int | None = None
    media_type: str | None = None


class AnimeMetadata(BaseModel):
    external_id: str
    title: str
    original_title: str | None = None
    alt_titles: list[str] = []
    year: int | None = None
    media_type: str | None = None
    description: str | None = None
    poster_url: str | None = None
    tags: list[TagInfo] = []
    episodes: list[EpisodeInfo] = []
