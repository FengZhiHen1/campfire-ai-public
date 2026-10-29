"""Worker 错误落盘与日志不保留底层异常中的凭据。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from campfire import worker

_SENSITIVE = "postgresql://user:private-sentinel@db/private"


@pytest.mark.asyncio
@pytest.mark.parametrize("permanent", [False, True])
@pytest.mark.parametrize("registration_fails", [False, True])
async def test_worker_error_summary_never_persists_or_logs_exception_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    permanent: bool,
    registration_fails: bool,
) -> None:
    @asynccontextmanager
    async def session_scope(*args: object) -> AsyncIterator[object]:
        yield object()

    registration = AsyncMock(
        return_value=SimpleNamespace(state=worker.STATE_DEAD, attempts=5, last_error=_SENSITIVE),
        side_effect=ValueError(_SENSITIVE) if registration_fails else None,
    )
    monkeypatch.setattr(worker, "session_scope", session_scope)
    monkeypatch.setattr(worker, "mark_dead" if permanent else "mark_retryable_failure", registration)
    handler = worker._mark_dead_and_alert if permanent else worker._register_retryable_failure
    with caplog.at_level(logging.WARNING, logger=worker.__name__):
        await handler("synthetic-pending", RuntimeError(_SENSITIVE), subject="测试")
    assert registration.await_args is not None
    assert registration.await_args.kwargs["error"] == "RuntimeError"
    assert _SENSITIVE not in caplog.text
    assert "private-sentinel" not in caplog.text
    assert "cause=" in caplog.text


@pytest.mark.asyncio
async def test_sweep_failure_does_not_log_exception_payload(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(worker, "sweep_once", AsyncMock(side_effect=[RuntimeError(_SENSITIVE), asyncio.CancelledError]))
    monkeypatch.setattr(worker, "SWEEP_INTERVAL_SECONDS", 0)
    with caplog.at_level(logging.ERROR, logger=worker.__name__):
        with pytest.raises(asyncio.CancelledError):
            await worker._sweep_forever()
    assert "cause=RuntimeError" in caplog.text
    assert "private-sentinel" not in caplog.text
