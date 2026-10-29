"""数据库探针的构造与清理失败也必须给出脱敏健康结论。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from campfire.core import db
from campfire.core.config import Settings
from campfire.core.health import Status


@pytest.mark.asyncio
async def test_database_probe_reports_malformed_url_without_raising_or_leaking() -> None:
    secret = "private-probe-sentinel"
    report = await db.check_database(Settings(database_url=f"invalid://user:{secret}@db"))
    assert report.status == Status.UNAVAILABLE
    assert secret not in report.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_fails", [False, True])
async def test_database_probe_cleanup_does_not_override_connection_result(
    monkeypatch: pytest.MonkeyPatch, connection_fails: bool
) -> None:
    class Engine:
        @asynccontextmanager
        async def connect(self) -> AsyncIterator[AsyncMock]:
            if connection_fails:
                raise RuntimeError("private-probe-sentinel")
            yield AsyncMock()

        async def dispose(self) -> None:
            raise ValueError("private-cleanup-sentinel")

    def create(*args: object, **kwargs: object) -> AsyncEngine:
        from typing import cast

        return cast(AsyncEngine, Engine())

    monkeypatch.setattr(db, "create_async_engine", create)
    report = await db.check_database(Settings(database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused"))
    assert report.status == (Status.UNAVAILABLE if connection_fails else Status.OK)
    assert "private-" not in report.detail
