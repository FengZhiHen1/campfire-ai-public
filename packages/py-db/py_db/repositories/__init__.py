"""py-db Repository 层 — 数据库操作封装。

所有数据库操作必须通过 Repository 类执行，
禁止在 Service 层直接调用 session.execute() 或拼接 SQL。
"""

from py_db.repositories.consultation_repository import (
    ConsultationLogRepository,
    ConsultationRepository,
    ConsultationSessionRepository,
)
from py_db.repositories.credential_repository import CredentialRepository
from py_db.repositories.invite_code_repository import InviteCodeRepository
from py_db.repositories.narrative_repository import NarrativeRepository
from py_db.repositories.profile_repository import (
    EventLogRepository,
    ProfessionalNoteRepository,
    ProfileAccessRepository,
    ProfileRepository,
)
from py_db.repositories.review_repository import (
    ReviewAuditLogRepository,
    ReviewRepository,
)
from py_db.repositories.safety_card_repository import SafetyCardRepository
from py_db.repositories.user_repository import UserRepository

__all__ = [
    "UserRepository",
    "CredentialRepository",
    "InviteCodeRepository",
    "ProfileRepository",
    "EventLogRepository",
    "ProfessionalNoteRepository",
    "ProfileAccessRepository",
    "NarrativeRepository",
    "ReviewRepository",
    "ReviewAuditLogRepository",
    "SafetyCardRepository",
    "ConsultationSessionRepository",
    "ConsultationRepository",
    "ConsultationLogRepository",
]
