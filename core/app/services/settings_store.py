from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting
from app.domain.titles import DEFAULT_TITLE_ORDER, normalize_title_order

# User-configurable via PUT /api/v1/settings (free-form key/value table) --
# these are just the keys the staleness rule reads, with their defaults.
STALENESS_THRESHOLD_DAYS = "staleness_threshold_days"
STALENESS_RULE_ENABLED = "staleness_rule_enabled"

DEFAULT_STALENESS_THRESHOLD_DAYS = 182  # ~6 Monate
DEFAULT_STALENESS_RULE_ENABLED = True

# "ask": every identified download-folder anime waits in the sort queue for a
# manually-picked target folder. "auto": auto-sorted whenever the target is
# unambiguous (see services.sorter.maybe_auto_sort) -- otherwise it still
# falls back to the queue, since there's no rule engine to guess a target.
SORT_MODE = "sort_mode"
DEFAULT_SORT_MODE = "ask"

# "ask": a mismatched anime directory/episode-filename waits in the rename
# queue for manual confirmation. "auto": renamed immediately on identify --
# unlike sort_mode, renaming has no target-folder ambiguity to worry about.
RENAME_MODE = "rename_mode"
DEFAULT_RENAME_MODE = "ask"

# Two independent preference orders over app.domain.titles.TITLE_VARIANTS:
# one deciding the name shown in the library overview, one deciding the
# on-disk directory/file names.
DISPLAY_TITLE_ORDER = "display_title_order"
FOLDER_TITLE_ORDER = "folder_title_order"


async def get_setting(session: AsyncSession, key: str, default: Any) -> Any:
    row = await session.get(Setting, key)
    return row.value if row is not None else default


async def get_staleness_config(session: AsyncSession) -> tuple[float, bool]:
    """Returns (threshold_days, rule_enabled)."""
    threshold = await get_setting(session, STALENESS_THRESHOLD_DAYS, DEFAULT_STALENESS_THRESHOLD_DAYS)
    enabled = await get_setting(session, STALENESS_RULE_ENABLED, DEFAULT_STALENESS_RULE_ENABLED)
    return float(threshold), bool(enabled)


async def get_sort_mode(session: AsyncSession) -> str:
    return await get_setting(session, SORT_MODE, DEFAULT_SORT_MODE)


async def get_rename_mode(session: AsyncSession) -> str:
    return await get_setting(session, RENAME_MODE, DEFAULT_RENAME_MODE)


async def get_display_title_order(session: AsyncSession) -> list[str]:
    return normalize_title_order(await get_setting(session, DISPLAY_TITLE_ORDER, DEFAULT_TITLE_ORDER))


async def get_folder_title_order(session: AsyncSession) -> list[str]:
    return normalize_title_order(await get_setting(session, FOLDER_TITLE_ORDER, DEFAULT_TITLE_ORDER))


# Directories the user chose to keep when the app offered to delete them for
# being empty. Without this the prompt reappears on every scan, since an
# empty directory never gets an Anime row to remember the decision on.
KEPT_EMPTY_DIRS = "kept_empty_dirs"


async def get_kept_empty_dirs(session: AsyncSession) -> set[str]:
    stored = await get_setting(session, KEPT_EMPTY_DIRS, [])
    return {entry for entry in stored if isinstance(entry, str)} if isinstance(stored, list) else set()


async def remember_kept_empty_dir(session: AsyncSession, path: str) -> None:
    kept = await get_kept_empty_dirs(session)
    if path in kept:
        return
    row = await session.get(Setting, KEPT_EMPTY_DIRS)
    value = sorted(kept | {path})
    if row is None:
        session.add(Setting(key=KEPT_EMPTY_DIRS, value=value))
    else:
        row.value = value
    await session.commit()


async def forget_kept_empty_dir(session: AsyncSession, path: str) -> None:
    """Called when the directory is deleted after all -- no point keeping a
    decision about something that no longer exists."""
    kept = await get_kept_empty_dirs(session)
    if path not in kept:
        return
    row = await session.get(Setting, KEPT_EMPTY_DIRS)
    if row is not None:
        row.value = sorted(kept - {path})
        await session.commit()
