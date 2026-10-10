from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import Setting
from app.domain.titles import normalize_title_order
from app.services import pending_actions
from app.services.settings_store import (
    DISPLAY_TITLE_ORDER,
    FOLDER_TITLE_ORDER,
    RENAME_MODE,
    SORT_MODE,
    STALENESS_RULE_ENABLED,
    STALENESS_THRESHOLD_DAYS,
)
from app.services.titles import resync_titles

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_TITLE_ORDER_KEYS = (DISPLAY_TITLE_ORDER, FOLDER_TITLE_ORDER)


class SettingsOut(BaseModel):
    values: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


@router.get("", response_model=SettingsOut)
async def get_settings_values(session: AsyncSession = Depends(get_db)) -> SettingsOut:
    result = await session.execute(select(Setting))
    return SettingsOut(values={row.key: row.value for row in result.scalars().all()})


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


# The keys a client may write, each with its validity check. The settings
# table also holds the app's own state (`anidb_banned_until`,
# `kept_empty_dirs`, `titledump_imported_at`) -- writable from outside, a
# client could lift an AniDB ban cool-down early and get the user banned for
# longer.
_WRITABLE: dict[str, Callable[[Any], bool]] = {
    STALENESS_THRESHOLD_DAYS: _is_positive_number,
    STALENESS_RULE_ENABLED: lambda value: isinstance(value, bool),
    SORT_MODE: lambda value: value in ("ask", "auto"),
    RENAME_MODE: lambda value: value in ("ask", "auto"),
    # Normalized below, so any list is accepted.
    DISPLAY_TITLE_ORDER: lambda value: isinstance(value, list),
    FOLDER_TITLE_ORDER: lambda value: isinstance(value, list),
}


@router.put("", response_model=SettingsOut)
async def update_settings_values(
    payload: SettingsUpdate, session: AsyncSession = Depends(get_db)
) -> SettingsOut:
    for key, value in payload.values.items():
        check = _WRITABLE.get(key)
        if check is None:
            raise HTTPException(status_code=422, detail=f"Einstellung '{key}' ist nicht änderbar")
        if not check(value):
            raise HTTPException(status_code=422, detail=f"Ungültiger Wert für '{key}'")

    title_order_changed = False
    for key, value in payload.values.items():
        # Store the title orders normalized, so a partial order written by an
        # older UI (or by hand) can't leave the library with a preference that
        # resolves to nothing for anime missing that one variant.
        if key in _TITLE_ORDER_KEYS:
            value = normalize_title_order(value)
        existing = await session.get(Setting, key)
        if existing is not None and existing.value == value:
            continue  # nothing to write, and nothing downstream to redo
        if key in _TITLE_ORDER_KEYS:
            title_order_changed = True
        if existing is None:
            session.add(Setting(key=key, value=value))
        else:
            existing.value = value
    await session.commit()

    # Display names are persisted in anime.title (the column the library list
    # is sorted and searched by), so a changed order has to be applied to the
    # existing rows rather than just to future identifications. Folder-order
    # changes don't rewrite anything on disk here -- they surface as entries
    # in the rename queue -- but they do trigger the same aniinfo.json variant
    # backfill, which is what makes those entries appear at all.
    # Only when an order actually changed: this is a full-library pass, and
    # re-saving the same order (or any unrelated setting) must not pay for it.
    if title_order_changed:
        await resync_titles(session)
        # A new folder order changes which anime count as misnamed, and no
        # event is published for a settings write -- drop the cached badge
        # total explicitly so it isn't stale until the TTL expires.
        pending_actions.invalidate()

    result = await session.execute(select(Setting))
    return SettingsOut(values={row.key: row.value for row in result.scalars().all()})
