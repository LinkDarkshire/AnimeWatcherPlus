from __future__ import annotations

import datetime as dt
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.services import shared_post, wishlist
from app.state import AppState

router = APIRouter(prefix="/api/v1/wishlist", tags=["wishlist"])


class WishlistItemOut(BaseModel):
    id: int
    anidb_id: int
    title: str
    year: int | None
    media_type: str | None
    episode_count: int | None
    details_pending: bool
    # Set once the anime has turned up in the library -- the entry stays
    # until the user removes it, but no longer counts as "not available".
    library_anime_id: int | None
    created_at: dt.datetime


class WishlistCandidateOut(BaseModel):
    anidb_id: int
    title: str
    matched_title: str
    score: float
    in_library: bool
    on_wishlist: bool


class WishlistAdd(BaseModel):
    anidb_id: int


@router.get("", response_model=list[WishlistItemOut])
async def list_wishlist(session: AsyncSession = Depends(get_db)) -> list[WishlistItemOut]:
    return [WishlistItemOut(**vars(item)) for item in await wishlist.list_items(session)]


@router.get("/search", response_model=list[WishlistCandidateOut])
async def search_anime(
    q: str = Query(min_length=1, max_length=200), session: AsyncSession = Depends(get_db)
) -> list[WishlistCandidateOut]:
    """Title search against the local AniDB title dump (or an AniDB ID)."""
    return [WishlistCandidateOut(**vars(c)) for c in await wishlist.search(session, q)]


class SharedIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class SharedOut(BaseModel):
    text: str
    source_url: str | None
    suggestions: list[WishlistCandidateOut]


@router.post("/shared", response_model=SharedOut)
async def shared_post_suggestions(payload: SharedIn, session: AsyncSession = Depends(get_db)) -> SharedOut:
    """Wishlist suggestions for a post shared to the app (e.g. from X)."""
    post = await shared_post.resolve(session, payload.text)
    return SharedOut(
        text=post.text,
        source_url=post.source_url,
        suggestions=[WishlistCandidateOut(**vars(c)) for c in post.suggestions],
    )


@router.post("", response_model=WishlistItemOut, status_code=201)
async def add_to_wishlist(
    payload: WishlistAdd,
    session: AsyncSession = Depends(get_db),
    state: AppState = Depends(get_app_state),
) -> WishlistItemOut:
    try:
        entry = await wishlist.add(session, payload.anidb_id)
    except wishlist.WishlistConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except wishlist.UnknownAnime as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    state.job_queue.enqueue(
        "wishlist_details",
        partial(wishlist.fetch_details, entry.id, state.provider_registry, state.event_bus),
    )
    return WishlistItemOut(
        id=entry.id,
        anidb_id=entry.anidb_id,
        title=entry.title,
        year=entry.year,
        media_type=entry.media_type,
        episode_count=entry.episode_count,
        details_pending=True,
        library_anime_id=None,
        created_at=entry.created_at,
    )


@router.delete("/{entry_id}", status_code=204)
async def remove_from_wishlist(entry_id: int, session: AsyncSession = Depends(get_db)) -> None:
    if not await wishlist.remove(session, entry_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
