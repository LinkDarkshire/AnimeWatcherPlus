from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Anime,
    AnimeProviderId,
    AnimeTag,
    ExpectedEpisode,
    Folder,
    JobLog,
    LocalEpisode,
    Tag,
)


class FolderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[Folder]:
        result = await self.session.execute(select(Folder).order_by(Folder.created_at))
        return list(result.scalars().all())

    async def get(self, folder_id: int) -> Folder | None:
        return await self.session.get(Folder, folder_id)

    async def get_by_path(self, path: str) -> Folder | None:
        result = await self.session.execute(select(Folder).where(Folder.path == path))
        return result.scalar_one_or_none()

    async def create(self, path: str, type_: str, name: str) -> Folder:
        folder = Folder(path=path, type=type_, name=name)
        self.session.add(folder)
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def delete(self, folder_id: int) -> None:
        """Deletes the folder and every Anime under it, plus each Anime's
        episodes/tags/provider-ids and FTS mirror row.

        A bare `DELETE FROM folder` violates the `anime.folder_id` foreign key
        (foreign_keys=ON) the moment the folder still has anime rows. ORM
        cascade (`session.delete(folder)`) would handle this, but triggers
        nested lazy-loads (e.g. `Anime.local_episodes`) outside of the async
        greenlet context and raises `MissingGreenlet`. Explicit, dependency-
        ordered bulk deletes sidestep both problems.
        """
        anime_ids = (
            (await self.session.execute(select(Anime.id).where(Anime.folder_id == folder_id)))
            .scalars()
            .all()
        )
        if anime_ids:
            for table in (LocalEpisode, ExpectedEpisode, AnimeTag, AnimeProviderId, JobLog):
                await self.session.execute(delete(table).where(table.anime_id.in_(anime_ids)))
            for anime_id in anime_ids:
                await self.session.execute(
                    text("DELETE FROM anime_search_fts WHERE anime_id = :aid"), {"aid": anime_id}
                )
            await self.session.execute(delete(Anime).where(Anime.id.in_(anime_ids)))
        await self.session.execute(delete(Folder).where(Folder.id == folder_id))
        await self.session.commit()

    async def set_active(self, folder_id: int, active: bool) -> None:
        folder = await self.get(folder_id)
        if folder is not None:
            folder.active = active
            await self.session.commit()


class AnimeRepo:
    """All writes that touch `anime` also keep `anime_search_fts` in sync (Kap. 6.2)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, anime_id: int) -> Anime | None:
        result = await self.session.execute(
            select(Anime)
            .where(Anime.id == anime_id)
            .options(selectinload(Anime.tags).selectinload(AnimeTag.tag), selectinload(Anime.expected_episodes))
        )
        return result.scalar_one_or_none()

    async def get_by_directory(self, directory_path: str) -> Anime | None:
        result = await self.session.execute(select(Anime).where(Anime.directory_path == directory_path))
        return result.scalar_one_or_none()

    async def get_by_anidb_id(self, anidb_id: int) -> Anime | None:
        result = await self.session.execute(select(Anime).where(Anime.anidb_id == anidb_id))
        return result.scalar_one_or_none()

    async def set_poster_path(self, anime_id: int, poster_path: str | None) -> None:
        anime = await self.session.get(Anime, anime_id)
        if anime is not None:
            anime.poster_path = poster_path
            await self.session.commit()

    async def create_pending(self, folder_id: int, directory_path: str, title_guess: str) -> Anime:
        anime = Anime(folder_id=folder_id, directory_path=directory_path, title=title_guess, ident_status="pending")
        self.session.add(anime)
        await self.session.commit()
        await self.session.refresh(anime)
        await self._sync_fts(anime)
        return anime

    async def mark_missing_on_disk(self, anime_id: int, missing: bool) -> None:
        anime = await self.session.get(Anime, anime_id)
        if anime is not None:
            anime.missing_on_disk = missing
            await self.session.commit()

    async def delete(self, anime_id: int) -> None:
        """Removes one anime's catalog entry (e.g. resolving a confirmed
        duplicate) -- does NOT touch the files on disk, only the DB rows.

        Mirrors FolderRepo.delete's reasoning: a bare `DELETE FROM anime`
        violates FK constraints the moment child rows exist, and ORM cascade
        triggers lazy-loads outside a valid greenlet context. Explicit,
        dependency-ordered deletes sidestep both. `duplicate_of_anime_id` is
        a self-referential FK, so any other anime row pointing at this one
        must be cleared first too, then the rest of that duplicate group
        (if any) gets its flags recomputed from scratch.
        """
        anime = await self.session.get(Anime, anime_id)
        if anime is None:
            return
        anidb_id = anime.anidb_id

        for table in (LocalEpisode, ExpectedEpisode, AnimeTag, AnimeProviderId, JobLog):
            await self.session.execute(delete(table).where(table.anime_id == anime_id))
        await self.session.execute(
            update(Anime)
            .where(Anime.duplicate_of_anime_id == anime_id)
            .values(duplicate_of_anime_id=None, is_duplicate=False)
        )
        await self.session.execute(
            text("DELETE FROM anime_search_fts WHERE anime_id = :aid"), {"aid": anime_id}
        )
        await self.session.execute(delete(Anime).where(Anime.id == anime_id))
        await self.session.commit()

        await self.recompute_duplicate_flags(anidb_id)

    async def recompute_duplicate_flags(self, anidb_id: int | None) -> None:
        """Re-derives is_duplicate/duplicate_of_anime_id for every anime
        sharing `anidb_id`, from scratch. Needed after anything that changes
        a duplicate group's membership (deleting one entry, or re-identifying
        one entry to a different AniDB ID) -- apply_identification only ever
        updates the single row it's identifying, which can leave sibling rows
        pointing at a now-stale duplicate_of_anime_id."""
        if anidb_id is None:
            return
        result = await self.session.execute(
            select(Anime).where(Anime.anidb_id == anidb_id).order_by(Anime.id)
        )
        group = list(result.scalars().all())
        if len(group) <= 1:
            for a in group:
                a.is_duplicate = False
                a.duplicate_of_anime_id = None
        else:
            primary, *rest = group
            primary.is_duplicate = False
            primary.duplicate_of_anime_id = None
            for a in rest:
                a.is_duplicate = True
                a.duplicate_of_anime_id = primary.id
        await self.session.commit()

    async def list_duplicate_groups(self) -> list[tuple[int, list[Anime]]]:
        """Groups of 2+ anime sharing the same (non-null) AniDB ID."""
        dup_ids_result = await self.session.execute(
            select(Anime.anidb_id)
            .where(Anime.anidb_id.is_not(None))
            .group_by(Anime.anidb_id)
            .having(func.count(Anime.id) > 1)
        )
        dup_ids = [row[0] for row in dup_ids_result.all()]
        if not dup_ids:
            return []

        result = await self.session.execute(
            select(Anime).where(Anime.anidb_id.in_(dup_ids)).order_by(Anime.anidb_id, Anime.id)
        )
        groups: dict[int, list[Anime]] = {}
        for anime in result.scalars().all():
            groups.setdefault(anime.anidb_id, []).append(anime)
        return list(groups.items())

    async def _sync_fts(self, anime: Anime) -> None:
        await self.session.execute(
            text("DELETE FROM anime_search_fts WHERE anime_id = :aid"), {"aid": anime.id}
        )
        await self.session.execute(
            text(
                "INSERT INTO anime_search_fts(anime_id, title, alt_titles_text) "
                "VALUES (:aid, :title, :alt)"
            ),
            {"aid": anime.id, "title": anime.title, "alt": " ".join(anime.alt_titles or [])},
        )
        await self.session.commit()

    async def apply_identification(
        self,
        anime_id: int,
        *,
        anidb_id: int | None,
        title: str,
        original_title: str | None,
        alt_titles: list[str],
        year: int | None,
        media_type: str | None,
        description: str | None,
        tags: list[tuple[str, int, int | None]],  # (name, weight, anidb_tag_id)
        expected_episodes: list[tuple[str, str | None]],  # (ep_number, title)
        ident_status: str,
        match_score: float | None,
        provider: str | None = None,
        external_id: str | None = None,
    ) -> Anime:
        anime = await self.session.get(Anime, anime_id)
        assert anime is not None

        # FA-29: the same AniDB ID can legitimately exist in two folders
        # (duplicate copies of a series) -- flag it rather than silently
        # overwriting or letting a DB constraint reject the second one.
        if anidb_id is not None:
            existing = await self.session.execute(
                select(Anime).where(Anime.anidb_id == anidb_id, Anime.id != anime_id)
            )
            other = existing.scalars().first()
            anime.is_duplicate = other is not None
            anime.duplicate_of_anime_id = other.id if other is not None else None
        else:
            anime.is_duplicate = False
            anime.duplicate_of_anime_id = None

        anime.anidb_id = anidb_id
        anime.title = title
        anime.original_title = original_title
        anime.alt_titles = alt_titles
        anime.year = year
        anime.media_type = media_type
        anime.description = description
        anime.ident_status = ident_status
        anime.match_score = match_score
        anime.episode_count_expected = len(expected_episodes) or None
        anime.last_metadata_refresh = dt.datetime.now(dt.timezone.utc)

        await self.session.execute(delete(AnimeTag).where(AnimeTag.anime_id == anime_id))
        for name, weight, anidb_tag_id in tags:
            tag = await self._get_or_create_tag(name, anidb_tag_id)
            self.session.add(AnimeTag(anime_id=anime_id, tag_id=tag.id, weight=weight))

        await self.session.execute(delete(ExpectedEpisode).where(ExpectedEpisode.anime_id == anime_id))
        for ep_number, ep_title in expected_episodes:
            self.session.add(ExpectedEpisode(anime_id=anime_id, ep_number=ep_number, title=ep_title))

        if provider and external_id:
            existing = await self.session.execute(
                select(AnimeProviderId).where(
                    AnimeProviderId.anime_id == anime_id, AnimeProviderId.provider == provider
                )
            )
            row = existing.scalar_one_or_none()
            if row is None:
                self.session.add(AnimeProviderId(anime_id=anime_id, provider=provider, external_id=external_id))
            else:
                row.external_id = external_id

        await self.session.commit()
        await self.session.refresh(anime)
        await self._sync_fts(anime)
        return anime

    async def mark_conflicted(self, anime_id: int, anidb_id: int, title: str) -> Anime:
        """Fallback for when apply_identification's write hit a UNIQUE-
        constraint violation despite its own duplicate pre-check (should be
        unreachable on a healthy schema -- see identification.py). Leaves
        anidb_id unset so the row stays valid, and surfaces the conflict in
        the Review-Queue instead of losing the identification attempt.
        """
        anime = await self.session.get(Anime, anime_id)
        assert anime is not None
        anime.ident_status = "review"
        anime.review_candidates = [{"aid": anidb_id, "title": title, "score": 0.0}]
        await self.session.commit()
        await self.session.refresh(anime)
        return anime

    async def _get_or_create_tag(self, name: str, anidb_tag_id: int | None) -> Tag:
        """Looks up by `anidb_tag_id` first when available -- that's the
        actual stable identity AniDB assigns; `name` is just a mutable label
        that AniDB does occasionally rename (or that differs only in case
        between two imports). Looking up by name first (the old behavior)
        misses a renamed tag entirely and then tries to INSERT a second row
        with the same anidb_tag_id, hitting its UNIQUE constraint.
        """
        if anidb_tag_id is not None:
            result = await self.session.execute(select(Tag).where(Tag.anidb_tag_id == anidb_tag_id))
            tag = result.scalar_one_or_none()
            if tag is not None:
                if tag.name != name:
                    # AniDB renamed this tag since we last saw it. Keep our
                    # copy in sync, but don't let a rename collide with a
                    # different tag that already owns the new name string.
                    existing_with_name = await self.session.execute(
                        select(Tag).where(Tag.name == name, Tag.id != tag.id)
                    )
                    if existing_with_name.scalar_one_or_none() is None:
                        tag.name = name
                return tag

        result = await self.session.execute(select(Tag).where(Tag.name == name))
        tag = result.scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name, anidb_tag_id=anidb_tag_id)
            self.session.add(tag)
            await self.session.flush()
        return tag

    async def search(
        self,
        *,
        query: str | None,
        year: int | None,
        media_type: str | None,
        tag: str | None,
        status_filter: str | None,
        page: int,
        size: int,
    ) -> tuple[list[Anime], int]:
        stmt = select(Anime)
        if query:
            fts_ids = await self.session.execute(
                text(
                    "SELECT anime_id FROM anime_search_fts WHERE anime_search_fts MATCH :q"
                ),
                {"q": f'"{query}"*'},
            )
            ids = [row[0] for row in fts_ids.all()]
            if not ids:
                return [], 0
            stmt = stmt.where(Anime.id.in_(ids))
        if year is not None:
            stmt = stmt.where(Anime.year == year)
        if media_type is not None:
            stmt = stmt.where(Anime.media_type == media_type)
        if status_filter is not None:
            stmt = stmt.where(Anime.ident_status == status_filter)
        if tag is not None:
            stmt = stmt.join(AnimeTag, AnimeTag.anime_id == Anime.id).join(Tag, Tag.id == AnimeTag.tag_id).where(
                Tag.name == tag
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Anime.title).offset((page - 1) * size).limit(size)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all()), total

    async def list_needing_review_or_manual(self) -> list[Anime]:
        result = await self.session.execute(
            select(Anime).where(Anime.ident_status.in_(["needs_manual_id", "review"]))
        )
        return list(result.scalars().all())

    async def list_identified(self) -> list[Anime]:
        """Eager-loads `expected_episodes` -- callers need it for the
        last-known-episode-air-date staleness check."""
        result = await self.session.execute(
            select(Anime)
            .where(Anime.ident_status == "identified", Anime.anidb_id.is_not(None))
            .options(selectinload(Anime.expected_episodes))
        )
        return list(result.scalars().all())


class TagRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_with_counts(self) -> list[tuple[Tag, int]]:
        stmt = (
            select(Tag, func.count(AnimeTag.anime_id))
            .outerjoin(AnimeTag, AnimeTag.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(Tag.name)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


class JobLogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, job_type: str, result: str, detail: str | None = None, anime_id: int | None = None
    ) -> JobLog:
        entry = JobLog(job_type=job_type, result=result, detail=detail, anime_id=anime_id)
        self.session.add(entry)
        await self.session.commit()
        return entry

    async def recent(self, limit: int = 100) -> list[JobLog]:
        result = await self.session.execute(
            select(JobLog).order_by(JobLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


class LocalEpisodeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, anime_id: int, file_path: str, file_size: int, file_mtime: float, ep_number: str | None) -> LocalEpisode:
        result = await self.session.execute(select(LocalEpisode).where(LocalEpisode.file_path == file_path))
        episode = result.scalar_one_or_none()
        if episode is None:
            episode = LocalEpisode(
                anime_id=anime_id,
                file_path=file_path,
                file_size=file_size,
                file_mtime=file_mtime,
                ep_number=ep_number,
            )
            self.session.add(episode)
        else:
            episode.file_size = file_size
            episode.file_mtime = file_mtime
            if not episode.manual_override:
                episode.ep_number = ep_number
        await self.session.commit()
        await self.session.refresh(episode)
        return episode

    async def by_anime(self, anime_id: int) -> list[LocalEpisode]:
        result = await self.session.execute(select(LocalEpisode).where(LocalEpisode.anime_id == anime_id))
        return list(result.scalars().all())

    async def delete_by_path(self, file_path: str) -> None:
        await self.session.execute(delete(LocalEpisode).where(LocalEpisode.file_path == file_path))
        await self.session.commit()
