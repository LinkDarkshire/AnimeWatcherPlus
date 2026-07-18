from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Folder(Base):
    __tablename__ = "folder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)
    type: Mapped[str] = mapped_column(String)  # "content" | "download"
    name: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    animes: Mapped[list["Anime"]] = relationship(back_populates="folder", cascade="all, delete-orphan")


class Anime(Base):
    __tablename__ = "anime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("folder.id"))
    directory_path: Mapped[str] = mapped_column(String, unique=True)
    # Intentionally NOT unique: FA-29 requires detecting (not preventing) the
    # same AniDB ID sitting in two folders -- a hard DB constraint here would
    # crash the second identification instead of flagging it as a duplicate.
    anidb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_anime_id: Mapped[int | None] = mapped_column(
        ForeignKey("anime.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, default="")
    original_title: Mapped[str | None] = mapped_column(String, nullable=True)
    alt_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String, nullable=True)  # TV|Movie|OVA|ONA|Special
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String, nullable=True)
    ident_status: Mapped[str] = mapped_column(
        String, default="pending"
    )  # pending|identified|needs_manual_id|review
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_candidates: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    episode_count_expected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_on_disk: Mapped[bool] = mapped_column(Boolean, default=False)
    last_metadata_refresh: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    folder: Mapped[Folder] = relationship(back_populates="animes")
    expected_episodes: Mapped[list["ExpectedEpisode"]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )
    local_episodes: Mapped[list["LocalEpisode"]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )
    tags: Mapped[list["AnimeTag"]] = relationship(back_populates="anime", cascade="all, delete-orphan")
    provider_ids: Mapped[list["AnimeProviderId"]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )


class ExpectedEpisode(Base):
    __tablename__ = "expected_episode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime.id"))
    ep_number: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    air_date: Mapped[dt.date | None] = mapped_column(nullable=True)

    anime: Mapped[Anime] = relationship(back_populates="expected_episodes")


class LocalEpisode(Base):
    __tablename__ = "local_episode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime.id"))
    file_path: Mapped[str] = mapped_column(String, unique=True)
    ep_number: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_mtime: Mapped[float] = mapped_column(Float, default=0.0)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)

    anime: Mapped[Anime] = relationship(back_populates="local_episodes")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anidb_tag_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)

    animes: Mapped[list["AnimeTag"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class AnimeTag(Base):
    __tablename__ = "anime_tag"

    anime_id: Mapped[int] = mapped_column(ForeignKey("anime.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)
    weight: Mapped[int] = mapped_column(Integer, default=0)

    anime: Mapped[Anime] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(back_populates="animes")


class AnimeProviderId(Base):
    __tablename__ = "anime_provider_id"
    __table_args__ = (UniqueConstraint("anime_id", "provider", name="uq_anime_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anime_id: Mapped[int] = mapped_column(ForeignKey("anime.id"))
    provider: Mapped[str] = mapped_column(String)  # anidb|mal|tmdb|plugin-id
    external_id: Mapped[str] = mapped_column(String)

    anime: Mapped[Anime] = relationship(back_populates="provider_ids")


class AnidbTitleEntry(Base):
    """Local copy of one row of the daily AniDB title dump (anime-titles.xml.gz)."""

    __tablename__ = "anidb_title_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aid: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String)
    lang: Mapped[str | None] = mapped_column(String, nullable=True)
    title_type: Mapped[str | None] = mapped_column(String, nullable=True)  # primary|synonym|short|official


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class JobLog(Base):
    __tablename__ = "job_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anime_id: Mapped[int | None] = mapped_column(ForeignKey("anime.id"), nullable=True)
    job_type: Mapped[str] = mapped_column(String)  # scan|identify|analyze|sort|nfo
    result: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
