"""SEC-05 Repository 基类 — CRUD 骨架 + 重试逻辑单元测试。

使用 mock AsyncSession 验证方法调用路径和异常处理。
"""

from __future__ import annotations

from unittest import mock

import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from py_db.repositories.base_repository import BaseRepository, DependencyCommunicationError


class _TestBase(DeclarativeBase):
    pass


class _RealModel(_TestBase):
    __tablename__ = "test_model"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class _FakeModel:
    """用于非 select 操作的 ORM 模型替身。"""
    id: int = 1


class _RealRepo(BaseRepository[_RealModel]):
    model = _RealModel


class _FakeRepo(BaseRepository[_FakeModel]):
    model = _FakeModel


@pytest.fixture
def repo() -> _RealRepo:
    return _RealRepo(session_factory=lambda: mock.AsyncMock(spec=AsyncSession))


@pytest.fixture
def fake_repo() -> _FakeRepo:
    return _FakeRepo(session_factory=lambda: mock.AsyncMock(spec=AsyncSession))


@pytest.fixture
def session() -> mock.AsyncMock:
    return mock.AsyncMock(spec=AsyncSession)


# ---- create ----


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_adds_and_flushes(self, repo, session):
        entity = _RealModel(id=1, name="test")
        result = await repo.create(session, entity)
        session.add.assert_called_once_with(entity)
        session.flush.assert_called_once()
        session.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_retry_on_operational_error(self, repo, session):
        session.flush.side_effect = [
            OperationalError("conn", "lost", "test"),
            None,
        ]
        entity = _RealModel(id=1, name="test")
        result = await repo.create(session, entity)
        assert session.flush.call_count == 2

    @pytest.mark.asyncio
    async def test_create_retry_exhausted(self, repo, session):
        session.flush.side_effect = OperationalError("conn", "lost", "test")
        entity = _RealModel(id=1, name="test")
        with pytest.raises(DependencyCommunicationError):
            await repo.create(session, entity)
        assert session.flush.call_count == 3


# ---- find_by_id ----


class TestFindById:
    @pytest.mark.asyncio
    async def test_find_by_id_returns_entity(self, repo, session):
        fake = _RealModel(id=42, name="test")
        scalars_mock = mock.MagicMock()
        scalars_mock.first.return_value = fake
        result_mock = mock.MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        r = await repo.find_by_id(session, 42)
        assert r is fake

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, repo, session):
        scalars_mock = mock.MagicMock()
        scalars_mock.first.return_value = None
        result_mock = mock.MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        r = await repo.find_by_id(session, 999)
        assert r is None

    @pytest.mark.asyncio
    async def test_find_by_id_retry_on_timeout(self, repo, session):
        scalars_mock = mock.MagicMock()
        scalars_mock.first.return_value = None
        result_mock = mock.MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.side_effect = [
            SQLAlchemyTimeoutError("timeout", "test", None),
            result_mock,
        ]
        r = await repo.find_by_id(session, 1)
        assert r is None
        assert session.execute.call_count == 2


# ---- find_all ----


class TestFindAll:
    @pytest.mark.asyncio
    async def test_find_all_returns_list(self, repo, session):
        scalars_mock = mock.MagicMock()
        scalars_mock.all.return_value = []
        result_mock = mock.MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        r = await repo.find_all(session)
        assert r == []

    @pytest.mark.asyncio
    async def test_find_all_with_pagination(self, repo, session):
        scalars_mock = mock.MagicMock()
        scalars_mock.all.return_value = [_RealModel(id=1, name="a")]
        result_mock = mock.MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        r = await repo.find_all(session, offset=10, limit=20)
        assert len(r) == 1


# ---- update ----


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_merges_and_flushes(self, repo, session):
        entity = _RealModel(id=1, name="test")
        session.merge.return_value = entity
        result = await repo.update(session, entity)
        session.merge.assert_called_once_with(entity)
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_retry_exhausted(self, repo, session):
        session.merge.side_effect = OperationalError("conn", "lost", "test")
        entity = _RealModel(id=1, name="test")
        with pytest.raises(DependencyCommunicationError):
            await repo.update(session, entity)


# ---- delete ----


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_session_delete(self, repo, session):
        entity = _RealModel(id=1, name="test")
        result = await repo.delete(session, entity)
        session.delete.assert_called_once_with(entity)
        session.flush.assert_called_once()
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_retry_exhausted(self, repo, session):
        session.delete.side_effect = OperationalError("conn", "lost", "test")
        entity = _RealModel(id=1, name="test")
        with pytest.raises(DependencyCommunicationError):
            await repo.delete(session, entity)
