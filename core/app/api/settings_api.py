from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import Setting

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class SettingsOut(BaseModel):
    values: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


@router.get("", response_model=SettingsOut)
async def get_settings_values(session: AsyncSession = Depends(get_db)) -> SettingsOut:
    result = await session.execute(select(Setting))
    return SettingsOut(values={row.key: row.value for row in result.scalars().all()})


@router.put("", response_model=SettingsOut)
async def update_settings_values(
    payload: SettingsUpdate, session: AsyncSession = Depends(get_db)
) -> SettingsOut:
    for key, value in payload.values.items():
        existing = await session.get(Setting, key)
        if existing is None:
            session.add(Setting(key=key, value=value))
        else:
            existing.value = value
    await session.commit()
    result = await session.execute(select(Setting))
    return SettingsOut(values={row.key: row.value for row in result.scalars().all()})
