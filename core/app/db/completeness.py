from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Integer, and_, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Anime, ExpectedEpisode, LocalEpisode

# FA-12: soll/ist comparison of the provider's episode list against the files
# actually on disk. Expressed in SQL rather than by loading episode rows into
# Python, because the library list needs it for every card on a page and the
# global view needs it across the whole catalog.


def _is_plain_number(column):
    """SQL predicate matching what `sorter._normalize_ep_number` does in
    Python: the value consists of digits only.

    AniDB numbers specials, credits and trailers with a letter prefix (S1, C1,
    T1). Those are deliberately excluded from the comparison -- they'd
    otherwise be reported as permanently "missing" for nearly every series,
    since the local filename parser never produces such numbers either.
    """
    return and_(column.op("GLOB")("[0-9]*"), ~column.op("GLOB")("*[^0-9]*"))


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

    async def list_incomplete(self, page: int, size: int) -> tuple[list[tuple[Anime, int]], int]:
        """One page of the global "missing episodes" view: every identified
        anime that has at least one expected episode without a file, newest
        gaps first is meaningless here, so ordered by title like the library.

        Anime with no episode structure at all (movies, single-entry OVAs with
        one expected episode already on disk) never appear, because the
        comparison simply finds nothing missing for them -- no special case
        needed (concept Kap. 14, open point 5).
        """
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
