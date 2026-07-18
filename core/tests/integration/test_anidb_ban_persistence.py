from __future__ import annotations

import time

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.providers.anidb import BAN_SETTING_KEY, AniDBProvider


@pytest.fixture
def anidb_provider(test_engine, monkeypatch) -> AniDBProvider:
    """Regression coverage for the user-reported gap: `_banned_until` used to
    live only in process memory (time.monotonic()), so a restart during the
    ~24h AniDB ban silently forgot it and could resume hammering the API.

    anidb.py imports `session_scope` lazily inside its methods (`from
    app.db.session import session_scope`), so the patch target is the
    source module, not `app.providers.anidb`'s namespace.
    """
    import app.db.session as session_module

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "session_scope", lambda: factory())

    settings = Settings(data_dir="/tmp/awp-test-unused")
    return AniDBProvider(settings)


@pytest.mark.asyncio
async def test_load_ban_state_is_noop_when_nothing_persisted(anidb_provider) -> None:
    await anidb_provider.load_ban_state()
    assert anidb_provider._banned_until == 0.0


@pytest.mark.asyncio
async def test_ban_state_persists_and_reloads_across_a_new_provider_instance(
    anidb_provider, test_engine, monkeypatch
) -> None:
    future = time.time() + 3600
    anidb_provider._banned_until = future
    await anidb_provider._persist_ban_state()

    # Simulate a restart: a brand-new provider instance loading from the
    # same (persisted) DB state, not the same Python object.
    import app.db.session as session_module

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "session_scope", lambda: factory())

    new_provider = AniDBProvider(Settings(data_dir="/tmp/awp-test-unused"))
    await new_provider.load_ban_state()

    assert new_provider._banned_until == pytest.approx(future, abs=1.0)


@pytest.mark.asyncio
async def test_persisted_ban_blocks_fetch_after_reload(anidb_provider, test_engine, monkeypatch) -> None:
    from app.providers.base import ProviderBannedError

    anidb_provider._banned_until = time.time() + 3600
    await anidb_provider._persist_ban_state()

    import app.db.session as session_module

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "session_scope", lambda: factory())

    new_provider = AniDBProvider(Settings(data_dir="/tmp/awp-test-unused"))
    await new_provider.load_ban_state()

    with pytest.raises(ProviderBannedError):
        await new_provider.fetch("1")


@pytest.mark.asyncio
async def test_expired_ban_does_not_block_after_reload(anidb_provider, test_engine, monkeypatch) -> None:
    anidb_provider._banned_until = time.time() - 10  # already expired
    await anidb_provider._persist_ban_state()

    import app.db.session as session_module

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "session_scope", lambda: factory())

    new_provider = AniDBProvider(Settings(data_dir="/tmp/awp-test-unused"))
    await new_provider.load_ban_state()

    assert time.time() >= new_provider._banned_until


def test_ban_setting_key_is_stable() -> None:
    # Guards against an accidental rename silently orphaning already-persisted rows.
    assert BAN_SETTING_KEY == "anidb_banned_until"
