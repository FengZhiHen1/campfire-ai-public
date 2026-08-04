"""crisis 模块对外编排——CrisisService（红线安全门 + 此刻安全层）。

职责：
- evaluate_gate：红线判定（词库加载 + 档案叠加判定 + 命中事件落库）
- 安全层供给委托 SafetyLayer（卡供给/阶段推进/分流/走失流程）

红线判定为代码层纯规则，零 LLM（两条底线之一——安全语义不让渡）。
"""

from __future__ import annotations

import uuid

from py_db.models.profiles import EventLog
from py_schemas.crisis import RedlineGateRequest, RedlineGateResult
from py_schemas.enums import BehaviorBucket, GateResult
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crisis.keywords import load_redline_keywords
from app.modules.crisis.redline_event import record_redline_event
from app.modules.crisis.redline_gate import RedlineGate
from app.modules.crisis.safety_layer import SafetyLayer

# 档案叠加规则覆盖的行为类型（历史自伤/攻击记录）
_HARM_BEHAVIOR_TYPES = ("自伤", "攻击")


class CrisisService:
    """红线安全门 + 此刻安全层的对外编排入口。"""

    def __init__(self, safety_layer: SafetyLayer) -> None:
        self.safety_layer = safety_layer

    async def evaluate_gate(
        self,
        session: AsyncSession,
        request: RedlineGateRequest,
        *,
        session_id: uuid.UUID | None = None,
        record_event: bool = True,
    ) -> RedlineGateResult:
        """红线判定（桶分流 + 关键词 + 否定过滤 + 档案叠加）。

        命中时落红线事件（session_id 可空——桶分流发生在会话建立前）。
        """
        keywords = await load_redline_keywords(session)
        gate = RedlineGate(keywords=keywords)

        has_harm_history: bool | None = None
        if request.profile_id:
            has_harm_history = await self._check_harm_history(session, request.profile_id)

        result = await gate.evaluate(request, profile_has_harm_history=has_harm_history)

        if result.gate_result == GateResult.REDLINE and record_event:
            await record_redline_event(
                session,
                session_id=session_id,
                gate_trigger=result.gate_trigger or "",
                text=request.text,
                bucket=request.bucket,
                profile_id=request.profile_id,
            )
            await session.commit()
        return result

    async def _check_harm_history(self, session: AsyncSession, profile_id: str) -> bool:
        """档案叠加数据源：该档案是否有自伤/攻击历史事件。"""
        try:
            pid = uuid.UUID(profile_id)
        except (ValueError, AttributeError):
            return False
        stmt = (
            select(func.count())
            .select_from(EventLog)
            .where(EventLog.profile_id == pid)
            .where(EventLog.behavior_type.in_(_HARM_BEHAVIOR_TYPES))
        )
        result = await session.execute(stmt)
        return int(result.scalar_one()) > 0


__all__ = ["CrisisService"]
