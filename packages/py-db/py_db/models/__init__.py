"""py-db ORM 模型定义。

所有 SQLAlchemy 2.0 声明式映射模型的集中管理目录。
Alembic 通过 Base.metadata 获取完整表结构用于 autogenerate 和迁移管理。

Usage:
    from py_db.models import Base, User
    from py_db.models.auth import User
"""

from py_db.models.auth import User
from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

__all__ = [
    "Base",
    "User",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
