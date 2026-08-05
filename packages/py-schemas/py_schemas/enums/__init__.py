"""py-schemas — 枚举定义子包。

所有业务枚举集中在此包中，供 Pydantic Schema 和 ORM 模型引用。
"""

from py_schemas.enums.auth_enums import (
    AccountStatus,
    CredentialType,
    InviteChannel,
    InviteCodeStatus,
)
from py_schemas.enums.case_enums import (
    BehaviorType,
    CaseStatus,
    EvidenceLevel,
    FamilyDisplayCategory,
    SceneType,
    SeverityLevel,
    SourceType,
)
from py_schemas.enums.emergency_enums import (
    ELOPEMENT_BUCKET,
    REDLINE_BUCKETS,
    BehaviorBucket,
    CrisisStage,
    FallbackSignal,
    GateResult,
    MeltdownType,
    TurnType,
)
from py_schemas.enums.profile_enums import (
    AccessRole,
    AccessStatus,
    AntecedentCategory,
    CommunicationMethod,
    Comorbidity,
    EventSetting,
    EvidenceBasis,
    FunctionHypothesis,
    IntensityLevel,
    Outcome,
    PhysicalState,
    RecordedByRole,
)

__all__ = [
    # 认证域
    "AccountStatus",
    "InviteCodeStatus",
    "InviteChannel",
    "CredentialType",
    # 案例域
    "CaseStatus",
    "SourceType",
    "BehaviorType",
    "SeverityLevel",
    "SceneType",
    "EvidenceLevel",
    "FamilyDisplayCategory",
    # 应急域（ADR-009 时刻分层）
    "BehaviorBucket",
    "REDLINE_BUCKETS",
    "ELOPEMENT_BUCKET",
    "CrisisStage",
    "MeltdownType",
    "TurnType",
    "GateResult",
    "FallbackSignal",
    # 档案域（ADR-010 四层与 ABC）
    "IntensityLevel",
    "AntecedentCategory",
    "PhysicalState",
    "EventSetting",
    "Outcome",
    "FunctionHypothesis",
    "Comorbidity",
    "CommunicationMethod",
    "AccessRole",
    "AccessStatus",
    "RecordedByRole",
    "EvidenceBasis",
]
