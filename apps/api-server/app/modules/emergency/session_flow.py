"""应急会话状态机（内存态运行时，DB 持久化由 emergency_service 负责）。

会话阶段（phase）：
- stage_qa：阶段问答进行中（此刻安全层）
- generating：方案生成中
- followup：追问轮
- redline：红线命中（锁定，无方案层）
- elopement：走失一键流程（独立）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from py_schemas.enums import BehaviorBucket, CrisisStage, MeltdownType

SessionPhase = Literal["stage_qa", "generating", "followup", "redline", "elopement"]


@dataclass
class EmergencySessionState:
    """应急会话运行时状态（预注入与续接的事实源）。"""

    session_id: str
    user_id: str
    profile_id: str | None
    bucket: BehaviorBucket
    phase: SessionPhase
    stage: CrisisStage | None = None
    meltdown_type: MeltdownType | None = None
    pending_question_id: str | None = None
    cards_shown: list[str] = field(default_factory=list)
    followup_count: int = 0
    unresolved_marked: bool = False
    retrieval_insufficient: bool = False


class SessionRegistry:
    """活跃会话注册表（内存态）。

    进程内会话状态索引；重启后由 DB 重建（bucket/stage/meltdown_type 落库）。
    """

    def __init__(self) -> None:
        self._states: dict[str, EmergencySessionState] = {}

    def put(self, state: EmergencySessionState) -> None:
        self._states[state.session_id] = state

    def get(self, session_id: str) -> EmergencySessionState | None:
        return self._states.get(session_id)

    def remove(self, session_id: str) -> None:
        self._states.pop(session_id, None)


# 模块级单例（api-server 进程内共享）
_registry: SessionRegistry | None = None


def get_session_registry() -> SessionRegistry:
    global _registry
    if _registry is None:
        _registry = SessionRegistry()
    return _registry


__all__ = ["EmergencySessionState", "SessionPhase", "SessionRegistry", "get_session_registry"]
