from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Device
from app.security.keys import b64decode


def fingerprint(public_key: str) -> str:
    """A short, readable hash of a public key ("3F9A-12C0-77DE"), shown on
    both the joining device and the admin's screen so they can be compared."""
    digest = hashlib.sha256(b64decode(public_key)).hexdigest().upper()
    return "-".join(digest[i : i + 4] for i in range(0, 12, 4))


async def active_device(session: AsyncSession, device_id: int) -> Device | None:
    device = await session.get(Device, device_id)
    return device if device is not None and device.revoked_at is None else None


async def has_active_admin(session: AsyncSession) -> bool:
    count = await session.scalar(
        select(func.count()).select_from(Device).where(Device.is_admin.is_(True), Device.revoked_at.is_(None))
    )
    return bool(count)


async def key_in_use(session: AsyncSession, public_key: str) -> bool:
    return await session.scalar(select(Device.id).where(Device.public_key == public_key)) is not None


async def create_device(session: AsyncSession, name: str, public_key: str, is_admin: bool) -> Device:
    device = Device(name=name, public_key=public_key, is_admin=is_admin)
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


async def touch(session: AsyncSession, device: Device) -> None:
    device.last_seen_at = dt.datetime.now(dt.UTC)
    await session.commit()
