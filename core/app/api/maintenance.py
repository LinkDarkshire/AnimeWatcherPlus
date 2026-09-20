from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_state, get_db
from app.services import pending_actions, repair
from app.state import AppState

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])


class RepairScanResult(BaseModel):
    checked: int
    titles_backfilled: int
    titles_changed: int
    episode_numbers_fixed: int
    metadata_filled: int
    expected_episodes_added: int
    posters_relinked: int
    without_local_source: int


@router.post("/repair-scan", response_model=RepairScanResult)
async def run_repair_scan(
    session: AsyncSession = Depends(get_db), state: AppState = Depends(get_app_state)
) -> RepairScanResult:
    """Fills in everything derivable from local data for the whole library,
    `no_scan` entries included. Runs in the request rather than as a queued
    job so the caller gets the actual counts back; it touches no network, so
    it finishes in seconds even on a large library."""
    report = await repair.run_repair_scan(session, state.settings, state.event_bus)
    pending_actions.invalidate()
    return RepairScanResult(**vars(report))
