"""AI 提取案例失败原因持久化测试。

验证 `_run_extraction_background` 在成功/失败两种情况下，
都会正确维护 `case_narratives.extraction_status` 与 `extraction_error`。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest import mock

import pytest
from app.modules.cases.exceptions import ExtractionError
from app.modules.cases.narrative.routes import (
    _format_extraction_error,
    _run_extraction_background,
)
from sqlalchemy.ext.asyncio import AsyncSession


def _fake_session_factory(session: mock.AsyncMock):
    """构造一个返回指定 session 的异步上下文管理器工厂。"""

    @asynccontextmanager
    async def _factory():
        yield session

    return _factory


def _make_narrative_entity() -> mock.MagicMock:
    entity = mock.MagicMock()
    entity.extraction_status = "extracting"
    entity.extraction_error = None
    entity.derived_card_ids = None
    return entity


@pytest.mark.asyncio
async def test_extraction_failure_persists_extraction_error():
    """当 LLM 提取抛出 ExtractionError 时，错误原因应写入 narrative。"""

    narrative_id = str(uuid.uuid4())
    session = mock.AsyncMock(spec=AsyncSession)
    nar = _make_narrative_entity()
    result_mock = mock.MagicMock()
    result_mock.scalars.return_value.first.return_value = nar
    session.execute.return_value = result_mock

    with mock.patch(
        "app.modules.cases.narrative.routes._get_session_factory",
        return_value=_fake_session_factory(session),
    ):
        with mock.patch(
            "app.modules.cases.extraction.service.ExtractionService",
        ) as mock_service_cls:
            instance = mock.AsyncMock()
            mock_service_cls.return_value = instance
            instance.extract_cards_from_narrative.side_effect = ExtractionError("JSON 解析失败: unexpected token")
            await _run_extraction_background(
                narrative_id=narrative_id,
                narrative_text="测试叙事",
                user_id="user-1",
            )

    assert nar.extraction_status == "failed"
    assert nar.extraction_error == "JSON 解析失败: unexpected token"
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_extraction_success_clears_extraction_error():
    """当 LLM 提取成功时，extraction_error 应被清空。"""

    narrative_id = str(uuid.uuid4())
    session = mock.AsyncMock(spec=AsyncSession)
    nar = _make_narrative_entity()
    nar.extraction_error = "之前的失败原因"
    result_mock = mock.MagicMock()
    result_mock.scalars.return_value.first.return_value = nar
    session.execute.return_value = result_mock

    card_1 = mock.MagicMock()
    card_1.card_id = uuid.uuid4()
    card_2 = mock.MagicMock()
    card_2.card_id = uuid.uuid4()

    with mock.patch(
        "app.modules.cases.narrative.routes._get_session_factory",
        return_value=_fake_session_factory(session),
    ):
        with mock.patch(
            "app.modules.cases.extraction.service.ExtractionService",
        ) as mock_service_cls:
            instance = mock.AsyncMock()
            mock_service_cls.return_value = instance
            instance.extract_cards_from_narrative.return_value = [card_1, card_2]
            await _run_extraction_background(
                narrative_id=narrative_id,
                narrative_text="测试叙事",
                user_id="user-1",
            )

    assert nar.extraction_status == "extracted"
    assert nar.extraction_error is None
    assert nar.derived_card_ids == [str(card_1.card_id), str(card_2.card_id)]
    session.commit.assert_awaited()


def test_format_extraction_error_trims_long_reason():
    """过长错误原因应被截断到 2000 字符。"""

    long_reason = "x" * 3000
    exc = ExtractionError(long_reason)
    assert len(_format_extraction_error(exc)) == 2000


def test_format_extraction_error_for_generic_exception():
    """非 ExtractionError 异常应使用 str(exc) 并截断。"""

    exc = RuntimeError("connection timeout")
    assert _format_extraction_error(exc) == "connection timeout"
