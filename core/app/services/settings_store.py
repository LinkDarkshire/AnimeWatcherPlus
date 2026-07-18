from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting

# User-configurable via PUT /api/v1/settings (free-form key/value table) --
# these are just the keys the staleness rule reads, with their defaults.
STALENESS_THRESHOLD_DAYS = "staleness_threshold_days"
STALENESS_RULE_ENABLED = "staleness_rule_enabled"

DEFAULT_STALENESS_THRESHOLD_DAYS = 182  # ~6 Monate
DEFAULT_STALENESS_RULE_ENABLED = True


async def get_setting(session: AsyncSession, key: str, default: Any) -> Any:
    row = await session.get(Setting, key)
    return row.value if row is not None else default


async def get_staleness_config(session: AsyncSession) -> tuple[float, bool]:
    """Returns (threshold_days, rule_enabled)."""
    threshold = await get_setting(session, STALENESS_THRESHOLD_DAYS, DEFAULT_STALENESS_THRESHOLD_DAYS)
    enabled = await get_setting(session, STALENESS_RULE_ENABLED, DEFAULT_STALENESS_RULE_ENABLED)
    return float(threshold), bool(enabled)
