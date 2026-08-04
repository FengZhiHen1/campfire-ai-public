"""app.modules.emergency — 应急咨询模块（ADR-009 时刻分层）。

链路：此刻安全层（零 LLM）→ 完整方案层（Agent 单轮四段式）→ 追问轮
→ 确定性兜底信号。红线安全门经 crisis 模块（代码层纯规则）。
"""

from app.modules.emergency.emergency_service import EmergencyService
from app.modules.emergency.routes import router as emergency_router
from app.modules.emergency.session_flow import EmergencySessionState, get_session_registry
from app.modules.emergency.stream_hub import ConsultStreamHub, get_stream_hub

__all__ = [
    "EmergencyService",
    "EmergencySessionState",
    "ConsultStreamHub",
    "emergency_router",
    "get_session_registry",
    "get_stream_hub",
]
