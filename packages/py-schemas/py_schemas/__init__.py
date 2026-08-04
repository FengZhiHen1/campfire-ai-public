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
"""

from py_schemas.auth import (
    CHANNEL_ALLOWED_ROLES,
    REGISTRABLE_ROLES,
    REVIEW_REQUIRED_ROLES,
    InviteCodeCreateRequest,
    InviteCodeCreateResponse,
    InviteCodeItem,
    InviteCodeListResponse,
    LoginRequest,
    MeResponse,
    PermissionDeniedResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ReviewApproveResponse,
    ReviewListItem,
    ReviewListResponse,
    ReviewRejectRequest,
    ReviewResubmitRequest,
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
from py_schemas.crisis import (
    RedlineEventRecord,
    RedlineGateRequest,
    RedlineGateResult,
)
from py_schemas.emergency import (
    DISCLAIMER_TEXT,
    ConsultationSessionDetailDto,
    ConsultationSessionListItem,
    ConsultationTurnDto,
    ConsultStreamCreateRequest,
    ConsultStreamCreateResponse,
    EmergencyPlan,
    FallbackNoticeDto,
    FollowupRequest,
    RedlineGuideDto,
    SafetyCardDto,
    SourceRef,
    StageQuestionDto,
    UnresolvedMarkRequest,
)
from py_schemas.enums import (
    AccountStatus,
    BehaviorBucket,
    BehaviorType,
    CaseStatus,
    CredentialType,
    CrisisStage,
    EvidenceLevel,
    FallbackSignal,
    FamilyDisplayCategory,
    GateResult,
    InviteChannel,
    InviteCodeStatus,
    MeltdownType,
    SceneType,
    SeverityLevel,
    SourceType,
    TurnType,
)
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeListItem,
    NarrativeResponse,
    NarrativeUpdate,
)
from py_schemas.profiles import (
    CrisisPlanLayerDto,
    EmergencyContact,
    EventCompleteRequest,
    EventCreateRequest,
    EventListResponse,
    EventResponse,
    IdentityLayerDto,
    ProfessionalNoteCreateRequest,
    ProfessionalNoteResponse,
    ProfileAccessCreateRequest,
    ProfileAccessItem,
    ProfileAccessListResponse,
    ProfileCreateRequest,
    ProfileListItem,
    ProfileResponse,
    ProfileUpdateRequest,
)
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
    FallbackNoticeEvent,
    HeartbeatEvent,
    RedlineGuideEvent,
    ResultEvent,
    SafetyCardEvent,
    SseEventType,
    StageQuestionEvent,
    StreamErrorCode,
    StreamSession,
)

__all__ = [
    # AUTH — 用户认证与授权（ADR-013 目标态）
    "UserRole",
    "CHANNEL_ALLOWED_ROLES",
    "REGISTRABLE_ROLES",
    "REVIEW_REQUIRED_ROLES",
    "AccountStatus",
    "CredentialType",
    "InviteChannel",
    "InviteCodeStatus",
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    "RegisterRequest",
    "RegisterResponse",
    "MeResponse",
    "ReviewListItem",
    "ReviewListResponse",
    "ReviewApproveResponse",
    "ReviewRejectRequest",
    "ReviewResubmitRequest",
    "InviteCodeCreateRequest",
    "InviteCodeCreateResponse",
    "InviteCodeItem",
    "InviteCodeListResponse",
    "PermissionDeniedResponse",
    # 档案库（ADR-010 四层与 ABC）
    "IdentityLayerDto",
    "CrisisPlanLayerDto",
    "EmergencyContact",
    "ProfileCreateRequest",
    "ProfileUpdateRequest",
    "ProfileResponse",
    "ProfileListItem",
    "EventCreateRequest",
    "EventCompleteRequest",
    "EventResponse",
    "EventListResponse",
    "ProfessionalNoteCreateRequest",
    "ProfessionalNoteResponse",
    "ProfileAccessCreateRequest",
    "ProfileAccessItem",
    "ProfileAccessListResponse",
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
    # SSE 流式协议（ADR-015 统一族 + 应急面消息事件）
    "SseEventType",
    "ChunkEvent",
    "ResultEvent",
    "DoneEvent",
    "HeartbeatEvent",
    "ErrorEvent",
    "SafetyCardEvent",
    "StageQuestionEvent",
    "RedlineGuideEvent",
    "FallbackNoticeEvent",
    "StreamErrorCode",
    "StreamSession",
    # 应急咨询（ADR-009 时刻分层）
    "BehaviorBucket",
    "CrisisStage",
    "MeltdownType",
    "TurnType",
    "GateResult",
    "FallbackSignal",
    "DISCLAIMER_TEXT",
    "ConsultStreamCreateRequest",
    "ConsultStreamCreateResponse",
    "FollowupRequest",
    "UnresolvedMarkRequest",
    "SafetyCardDto",
    "StageQuestionDto",
    "RedlineGuideDto",
    "FallbackNoticeDto",
    "SourceRef",
    "EmergencyPlan",
    "ConsultationTurnDto",
    "ConsultationSessionDetailDto",
    "ConsultationSessionListItem",
    # 红线安全门（ADR-008 二元判定）
    "RedlineGateRequest",
    "RedlineGateResult",
    "RedlineEventRecord",
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
