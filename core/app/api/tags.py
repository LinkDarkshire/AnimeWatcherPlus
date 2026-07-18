from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.repositories import TagRepo

router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


class TagOut(BaseModel):
    id: int
    name: str
    description: str | None
    category: str | None
    anime_count: int


@router.get("", response_model=list[TagOut])
async def list_tags(session: AsyncSession = Depends(get_db)) -> list[TagOut]:
    rows = await TagRepo(session).list_with_counts()
    return [
        TagOut(id=tag.id, name=tag.name, description=tag.description, category=tag.category, anime_count=count)
        for tag, count in rows
    ]
