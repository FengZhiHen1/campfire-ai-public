"""py-db ORM 模型定义。

所有 SQLAlchemy 2.0 声明式映射模型的集中管理目录。
Alembic 通过 Base.metadata 获取完整表结构用于 autogenerate 和迁移管理。

Usage:
    from py_db.models import Base, User
    from py_db.models.auth import User
"""

from py_db.models.auth import User
from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from py_db.models.case_chunks import CaseChunk
from py_db.models.case_model import Case
from py_db.models.crisis_keyword import CrisisKeyword
from py_db.models.profiles import Profile, TeacherLink
from py_db.models.review_models import CaseReview, ReviewAuditLog

__all__ = [
    "Base",
    "User",
    "Case",
    "CaseChunk",
    "CrisisKeyword",
    "Profile",
    "TeacherLink",
    "CaseReview",
    "ReviewAuditLog",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
