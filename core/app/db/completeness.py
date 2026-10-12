from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Integer, Select, and_, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Anime, ExpectedEpisode, LocalEpisode

# Compares the provider's episode list with the files actually on disk.
# Done in SQL rather than in Python because the library needs it for every
# card on a page and the missing-episodes view for the whole catalog.


def _is_plain_number(column):
    """SQL predicate matching what `sorter._normalize_ep_number` does in
    Python: the value consists of digits only.

    AniDB numbers specials, credits and trailers with a letter prefix (S1, C1,
    T1). Those are deliberately excluded from the comparison -- they'd
    otherwise be reported as permanently "missing" for nearly every series,
    since the local filename parser never produces such numbers either.
    """
    glob = column.op("GLOB", is_comparison=True)
    return and_(glob("[0-9]*"), ~glob("*[^0-9]*"))


# Episode numbers are stored as text and aren't consistently zero-padded on
# either side ("05" vs "5"), so both are compared as integers -- the same
# normalization `sorter._normalize_ep_number` applies.
_EXPECTED_NUMBER = cast(ExpectedEpisode.ep_number, Integer)
_LOCAL_NUMBER = cast(LocalEpisode.ep_number, Integer)

_EXPECTED_IS_NUMBERED = _is_plain_number(ExpectedEpisode.ep_number)

_LOCAL_FILE_EXISTS = (
    select(LocalEpisode.id)
    .where(
        LocalEpisode.anime_id == ExpectedEpisode.anime_id,
        _is_plain_number(LocalEpisode.ep_number),
        _LOCAL_NUMBER == _EXPECTED_NUMBER,
    )
    .exists()
)

# anime_id -> number of expected episodes with no matching file. Reused as the
# library's `missing=true` filter and as the source of the global view.
missing_counts = (
    select(
        ExpectedEpisode.anime_id.label("anime_id"),
        func.count(distinct(_EXPECTED_NUMBER)).label("missing"),
    )
    .where(_EXPECTED_IS_NUMBERED, ~_LOCAL_FILE_EXISTS)
    .group_by(ExpectedEpisode.anime_id)
    .subquery()
)

anime_ids_with_missing_episodes = select(missing_counts.c.anime_id)


@dataclass
class Completeness:
    expected: int
    present: int
    missing: int

    @property
    def is_complete(self) -> bool:
        return self.missing == 0


@dataclass
class MissingEpisode:
    ep_number: str
    title: str | None
    air_date: dt.date | None


class CompletenessRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def for_animes(self, anime_ids: Sequence[int]) -> dict[int, Completeness]:
        """Expected/present/missing counts for a batch of anime -- two grouped
        queries for a whole page of the library, never one per card."""
        if not anime_ids:
            return {}

        expected: dict[int, int] = {
            anime_id: count
            for anime_id, count in (
                await self.session.execute(
                    select(ExpectedEpisode.anime_id, func.count(distinct(_EXPECTED_NUMBER)))
                    .where(ExpectedEpisode.anime_id.in_(anime_ids), _EXPECTED_IS_NUMBERED)
                    .group_by(ExpectedEpisode.anime_id)
                )
            ).all()
        }
        present: dict[int, int] = {
            anime_id: count
            for anime_id, count in (
                await self.session.execute(
                    select(ExpectedEpisode.anime_id, func.count(distinct(_EXPECTED_NUMBER)))
                    .where(
                        ExpectedEpisode.anime_id.in_(anime_ids),
                        _EXPECTED_IS_NUMBERED,
                        _LOCAL_FILE_EXISTS,
                    )
                    .group_by(ExpectedEpisode.anime_id)
                )
            ).all()
        }

        result: dict[int, Completeness] = {}
        for anime_id in anime_ids:
            total = expected.get(anime_id, 0)
            have = present.get(anime_id, 0)
            result[anime_id] = Completeness(expected=total, present=have, missing=total - have)
        return result

    async def missing_for_anime(self, anime_id: int) -> list[MissingEpisode]:
        """The individual episodes a series is missing, in episode order."""
        rows = (
            await self.session.execute(
                select(ExpectedEpisode.ep_number, ExpectedEpisode.title, ExpectedEpisode.air_date)
                .where(
                    ExpectedEpisode.anime_id == anime_id,
                    _EXPECTED_IS_NUMBERED,
                    ~_LOCAL_FILE_EXISTS,
                )
                .order_by(_EXPECTED_NUMBER)
            )
        ).all()
        seen: set[int] = set()
        missing: list[MissingEpisode] = []
        for ep_number, title, air_date in rows:
            # The provider list can carry the same episode twice under
            # differently padded numbers; report it once.
            key = int(ep_number)
            if key in seen:
                continue
            seen.add(key)
            missing.append(MissingEpisode(ep_number=ep_number, title=title, air_date=air_date))
        return missing

    async def all_missing(self) -> list[tuple[int, MissingEpisode]]:
        """Every missing episode of every identified anime as (anime_id,
        episode), in episode order per anime -- the download page's input.
        One query for the whole library, deduplicated like
        `missing_for_anime`."""
        rows = (
            await self.session.execute(
                select(ExpectedEpisode.anime_id, ExpectedEpisode.ep_number, ExpectedEpisode.title, ExpectedEpisode.air_date)
                .join(Anime, Anime.id == ExpectedEpisode.anime_id)
                .where(Anime.ident_status == "identified", _EXPECTED_IS_NUMBERED, ~_LOCAL_FILE_EXISTS)
                .order_by(ExpectedEpisode.anime_id, _EXPECTED_NUMBER)
            )
        ).all()
        seen: set[tuple[int, int]] = set()
        result: list[tuple[int, MissingEpisode]] = []
        for anime_id, ep_number, title, air_date in rows:
            key = (anime_id, int(ep_number))
            if key in seen:
                continue
            seen.add(key)
            result.append((anime_id, MissingEpisode(ep_number=ep_number, title=title, air_date=air_date)))
        return result

    def _unassigned_query(self) -> Select[LocalEpisode, str]:
        """Video files of identified anime that can't be matched to an
        episode: no number could be read from the name, or the number isn't
        one of the episodes AniDB lists. Only anime that have a numbered
        episode list at all -- without one there is nothing to match against."""
        has_numbered_episodes = (
            select(ExpectedEpisode.id)
            .where(ExpectedEpisode.anime_id == LocalEpisode.anime_id, _EXPECTED_IS_NUMBERED)
            .exists()
        )
        matching_episode = (
            select(ExpectedEpisode.id)
            .where(
                ExpectedEpisode.anime_id == LocalEpisode.anime_id,
                _EXPECTED_IS_NUMBERED,
                _is_plain_number(LocalEpisode.ep_number),
                _LOCAL_NUMBER == _EXPECTED_NUMBER,
            )
            .exists()
        )
        return (
            select(LocalEpisode, Anime.title)
            .join(Anime, Anime.id == LocalEpisode.anime_id)
            .where(Anime.ident_status == "identified", has_numbered_episodes, ~matching_episode)
        )

    async def unassigned_files(self) -> list[tuple[LocalEpisode, str]]:
        rows = (
            await self.session.execute(
                self._unassigned_query().order_by(Anime.title.collate("NOCASE"), LocalEpisode.file_path)
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def count_unassigned_files(self) -> int:
        return (
            await self.session.execute(select(func.count()).select_from(self._unassigned_query().subquery()))
        ).scalar_one()

    async def numbered_episodes(self, anime_ids: Sequence[int]) -> dict[int, list[MissingEpisode]]:
        """The numbered episode list per anime, for picking the right one."""
        if not anime_ids:
            return {}
        rows = (
            await self.session.execute(
                select(ExpectedEpisode.anime_id, ExpectedEpisode.ep_number, ExpectedEpisode.title, ExpectedEpisode.air_date)
                .where(ExpectedEpisode.anime_id.in_(anime_ids), _EXPECTED_IS_NUMBERED)
                .order_by(ExpectedEpisode.anime_id, _EXPECTED_NUMBER)
            )
        ).all()
        result: dict[int, list[MissingEpisode]] = {}
        for anime_id, ep_number, title, air_date in rows:
            episodes = result.setdefault(anime_id, [])
            if not any(int(e.ep_number) == int(ep_number) for e in episodes):
                episodes.append(MissingEpisode(ep_number=str(int(ep_number)), title=title, air_date=air_date))
        return result

    async def assign_lone_file(self, anime_id: int) -> bool:
        """A single video file whose name has no episode number, for an anime
        AniDB lists exactly one episode of (a movie, a one-shot OVA): that
        file can only be that episode. Returns whether a number was set."""
        files = list(
            (await self.session.execute(select(LocalEpisode).where(LocalEpisode.anime_id == anime_id))).scalars()
        )
        if len(files) != 1 or files[0].ep_number is not None or files[0].manual_override:
            return False
        numbers = list(
            (
                await self.session.execute(
                    select(_EXPECTED_NUMBER)
                    .where(ExpectedEpisode.anime_id == anime_id, _EXPECTED_IS_NUMBERED)
                    .distinct()
                )
            ).scalars()
        )
        if len(numbers) != 1:
            return False
        files[0].ep_number = str(numbers[0])
        await self.session.commit()
        return True

    async def list_incomplete(self, page: int, size: int) -> tuple[list[tuple[Anime, int]], int]:
        """One page of the missing-episodes view: every identified anime with
        at least one expected episode that has no file, ordered by title.
        Movies and single-episode OVAs that are on disk simply never show up,
        since nothing is missing for them."""
        base = (
            select(Anime, missing_counts.c.missing)
            .join(missing_counts, missing_counts.c.anime_id == Anime.id)
            .where(Anime.ident_status == "identified")
        )
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await self.session.execute(
                base.order_by(Anime.title).offset((page - 1) * size).limit(size)
            )
        ).all()
        return [(row[0], row[1]) for row in rows], total
