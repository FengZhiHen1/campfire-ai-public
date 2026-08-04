"""红线事件落库（红线安全门 §四：事件记录供词库迭代与 M4 冷启动）。

红线事件写入 consultation_logs（event_type='redline_hit'），
含触发规则、输入摘要（脱敏）、桶、时间。
"""

from __future__ import annotations

import uuid

from py_db.models.consultation import ConsultationLog
from py_db.repositories.consultation_repository import ConsultationLogRepository
from py_schemas.enums import BehaviorBucket
from sqlalchemy.ext.asyncio import AsyncSession

_REDACT = "***"


def _summarize_input(text: str | None) -> str:
    """输入摘要（截断，不落完整原文——PII 最小化）。"""
    if not text:
        return ""
    return text[:80]


async def record_redline_event(
    session: AsyncSession,
    *,
    session_id: uuid.UUID | None,
    gate_trigger: str,
    text: str | None,
    bucket: BehaviorBucket | None,
    profile_id: str | None,
) -> None:
    """红线事件落库（异步日志面，供词库迭代与 M4 冷启动）。"""
    repo = ConsultationLogRepository(session_factory=None)  # type: ignore[arg-type]
    log = ConsultationLog(
        session_id=session_id,
        event_type="redline_hit",
        payload={
            "gate_trigger": gate_trigger,
            "input_summary": _summarize_input(text),
            "bucket": bucket.value if bucket else None,
            "profile_id": profile_id,
        },
    )
    await repo.create(session, log)


__all__ = ["record_redline_event"]
