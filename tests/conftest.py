from __future__ import annotations

import os
from typing import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import database.db_controller as db_controller_module
import database.session as db_session
from database.session import Base


@pytest.fixture
async def db_session_fixture(tmp_path, monkeypatch) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    db_path = ":memory:"
    test_url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(test_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "engine", engine, raising=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", async_session, raising=False)
    monkeypatch.setattr(db_controller_module, "AsyncSessionLocal", async_session, raising=False)

    os.environ.setdefault("TG_BOT_TOKEN", "test-token")

    try:
        yield async_session
    finally:
        await engine.dispose()


@pytest.fixture
def context():
    data: dict = {}
    return type("DummyContext", (), {"user_data": data, "chat_data": data})()
