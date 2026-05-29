"""py-schemas — 全平台共享 Pydantic Schema 包。

提供跨应用共享的数据模型和枚举定义，作为前后端及后端模块之间的
数据契约。所有模型继承 CampfireBaseModel（统一 extra='forbid'），
对外接口类型与 docs/contracts/ 下的 JSON Schema 一致。

子包结构：
- base.py         共享基类 CampfireBaseModel
- auth.py         用户认证与授权（AUTH-01/02/03/04）
- profiles.py     个人档案管理 + 事件记录 + 隐私控制（PROF-01/03/05）
- cases.py        案例录入管理 + 审核工作流（CASE-01/03）
- cards.py        L2 结构化干预卡片
- narratives.py   L1 原始叙事层
- streaming.py    流式应答推送 SSE 事件（CSLT-04）
- consult/        RAG 语义检索（CSLT-02）+ 置信度后校验（CSLT-05）
- consult_start.py    应急咨询触发端点
- consultation_history.py  咨询历史管理（CSLT-06）
- enums/          业务枚举定义
- security/       输入校验模型（SEC-05）
- utils/          工具函数（HTML 清洗、安全检测、文件校验、年龄计算）
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
from py_schemas.cards import (
    CardCreateRequest,
    CardExtractionResult,
    CardResponse,
    CardUpdate,
)
from py_schemas.cases import (
    AiReviewSummary,
    AttachmentRef,
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseReviewResponse,
    CaseUpdate,
    CheckItem,
    PaginatedResponse,
    PiiDetectionResult,
    PiiWarning,
    ReviewAuditAction,
    ReviewQueueItem,
    ReviewRequest,
)
from py_schemas.consult import (
    CaseSliceDto,
    DegradationLevel,
    RetrievalStatus,
    SemanticSearchInput,
    SemanticSearchResult,
    TagFilterDto,
)
from py_schemas.consult.confidence import (
    ConfidenceValidationInput,
    ConfidenceValidationOutput,
    LLMAssessmentResult,
    ValidationVerdict,
)
from py_schemas.consult_start import (
    ConsultStartRequest,
    ConsultStartResponse,
)
from py_schemas.consultation_history import (
    GENERATION_DISCLAIMER_CONST,
    ConsultationHistoryCreate,
    ConsultationHistoryDetail,
    ConsultationHistoryListItem,
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
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeListItem,
    NarrativeResponse,
    NarrativeUpdate,
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
from py_schemas.security.validation_schemas import (
    FileValidationResult,
    FileValidationRule,
    SecurityAuditLogEntry,
    SecurityDetectionType,
    ValidationErrorItem,
    ValidationErrorResponse,
)
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
    # CASE-01 — L1 叙事 / L2 卡片
    "NarrativeCreateRequest",
    "NarrativeResponse",
    "NarrativeListItem",
    "NarrativeUpdate",
    "CardCreateRequest",
    "CardResponse",
    "CardUpdate",
    "CardExtractionResult",
    # CASE-03 — 审核工作流
    "ReviewAuditAction",
    "ReviewRequest",
    "CheckItem",
    "AiReviewSummary",
    "CaseReviewResponse",
    "ReviewQueueItem",
    # CSLT-02 — RAG 语义检索
    "DegradationLevel",
    "RetrievalStatus",
    "TagFilterDto",
    "SemanticSearchInput",
    "CaseSliceDto",
    "SemanticSearchResult",
    # CSLT-04 — 流式应答推送 SSE 事件模型
    "ChunkEvent",
    "DoneEvent",
    "HeartbeatEvent",
    "ErrorEvent",
    "StreamErrorCode",
    "StreamSession",
    # CSLT-05 — 置信度后校验
    "ValidationVerdict",
    "LLMAssessmentResult",
    "ConfidenceValidationInput",
    "ConfidenceValidationOutput",
    # CSLT-06 — 咨询历史管理
    "ConsultationHistoryCreate",
    "ConsultationHistoryListItem",
    "ConsultationHistoryDetail",
    "GENERATION_DISCLAIMER_CONST",
    # CSLT-MVP — 应急咨询触发
    "ConsultStartRequest",
    "ConsultStartResponse",
    # SEC-05 — 输入校验模型
    "SecurityDetectionType",
    "ValidationErrorItem",
    "ValidationErrorResponse",
    "FileValidationRule",
    "FileValidationResult",
    "SecurityAuditLogEntry",
]
# 注意: consult.EvidenceLevel 与 case_enums.EvidenceLevel 冲突，
# 顶层仅导出 case_enums 版本。consult 版本请通过 py_schemas.consult.EvidenceLevel 访问。
