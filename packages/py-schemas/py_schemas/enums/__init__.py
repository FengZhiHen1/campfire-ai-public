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
from py_schemas.enums.crisis_enums import (
    BehaviorTypeCategory,
    CrisisLevel,
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
    # 危机域
    "CrisisLevel",
    "BehaviorTypeCategory",
]
