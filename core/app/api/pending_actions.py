from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services import pending_actions

router = APIRouter(prefix="/api/v1/pending-actions", tags=["pending-actions"])


class PendingActionsCount(BaseModel):
    total: int


@router.get("/count", response_model=PendingActionsCount)
async def get_pending_actions_count(session: AsyncSession = Depends(get_db)) -> PendingActionsCount:
    """Drives the nav-tab badge. See services.pending_actions for how the
    total is derived and why it's cached."""
    return PendingActionsCount(total=await pending_actions.pending_actions_total(session))
