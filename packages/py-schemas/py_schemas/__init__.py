"""py-schemas — 全平台共享 Pydantic Schema 包。

提供跨应用共享的数据模型和枚举定义，作为前后端及后端模块之间的
数据契约。所有对外接口类型与 docs/contracts/ 下的 JSON Schema 一致。
"""

from py_schemas.auth import (
    LoginRequest,
    PermissionDeniedResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserRole,
)
from py_schemas.cases import (
    AttachmentRef,
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseUpdate,
    PaginatedResponse,
    PiiDetectionResult,
    PiiWarning,
)
from py_schemas.enums import (
    BehaviorType,
    CaseStatus,
    EvidenceLevel,
    FamilyDisplayCategory,
    SceneType,
    SeverityLevel,
    SourceType,
)
from py_schemas.profiles import (
    AccessDecision,
    AccessOperation,
    AccessRequest,
    AgeRange,
    DiagnosisType,
    EventCreate,
    EventListItem,
    EventResponse,
    EventSetting,
    EventUpdate,
    ExpertInfo,
    LanguageLevel,
    ProfileBehaviorType,
    ProfileCreate,
    ProfileListItem,
    ProfileResponse,
    ProfileUpdate,
    SensoryFeature,
    Trigger,
    VisibleScope,
)
from py_schemas.profiles import SeverityLevel as EventSeverityLevel
from py_schemas.streaming import (
    ChunkEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    StreamErrorCode,
    StreamSession,
)

__all__ = [
    # AUTH — 用户认证与授权
    "UserRole",
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    "RegisterRequest",
    "RegisterResponse",
    "PermissionDeniedResponse",
    # PROF-05 — 档案隐私控制
    "AccessOperation",
    "VisibleScope",
    "AccessRequest",
    "AccessDecision",
    "ExpertInfo",
    # PROF-01 — 个人档案管理
    "DiagnosisType",
    "ProfileBehaviorType",
    "LanguageLevel",
    "SensoryFeature",
    "Trigger",
    "AgeRange",
    "ProfileCreate",
    "ProfileUpdate",
    "ProfileResponse",
    "ProfileListItem",
    # PROF-03 — 事件记录管理
    "EventSeverityLevel",
    "EventSetting",
    "EventCreate",
    "EventUpdate",
    "EventResponse",
    "EventListItem",
    # CASE-01 — 案例录入管理
    "CaseStatus",
    "SourceType",
    "BehaviorType",
    "SeverityLevel",
    "SceneType",
    "EvidenceLevel",
    "FamilyDisplayCategory",
    "AttachmentRef",
    "CaseCreateRequest",
    "CaseUpdate",
    "CaseResponse",
    "CaseListItem",
    "PaginatedResponse",
    "PiiWarning",
    "PiiDetectionResult",
    # CSLT-04 — 流式应答推送 SSE 事件模型
    "ChunkEvent",
    "DoneEvent",
    "HeartbeatEvent",
    "ErrorEvent",
    "StreamErrorCode",
    "StreamSession",
]
