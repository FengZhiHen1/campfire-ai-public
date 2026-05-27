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
]
