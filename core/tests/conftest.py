from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import Base
from app.db.session import make_test_engine

_FTS_SQL = [
    "CREATE VIRTUAL TABLE anidb_title_fts USING fts5(title, content='anidb_title_index', content_rowid='id')",
    "CREATE TRIGGER anidb_title_ai AFTER INSERT ON anidb_title_index BEGIN "
    "INSERT INTO anidb_title_fts(rowid, title) VALUES (new.id, new.title); END",
    "CREATE TRIGGER anidb_title_ad AFTER DELETE ON anidb_title_index BEGIN "
    "INSERT INTO anidb_title_fts(anidb_title_fts, rowid, title) VALUES ('delete', old.id, old.title); END",
    "CREATE VIRTUAL TABLE anime_search_fts USING fts5(anime_id UNINDEXED, title, alt_titles_text)",
]


@pytest_asyncio.fixture
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """In-memory SQLite DB per test, schema mirrors the Alembic migrations (ORM
    tables via metadata.create_all + hand-applied FTS5 virtual tables).
    """
    engine = make_test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _FTS_SQL:
            await conn.execute(text(stmt))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def tmp_anime_dir(tmp_path):
    anime_dir = tmp_path / "Some Anime (2020)"
    anime_dir.mkdir()
    return anime_dir
