"""py-db — SQLAlchemy ORM、Alembic 迁移、仓储实现。

Campfire-AI 共享能力层（L2）的核心数据包。
提供数据库连接管理、ORM 模型定义、Alembic 迁移控制和通用 Repository 基类。

对外暴露：
    - migration: migrate_up, migrate_down, generate_migration, verify_migration
    - exceptions: 迁移专用异常类
    - models.base: SQLAlchemy 声明式基类 Base
    - repositories.base_repository: 通用异步 Repository 基类
"""

from py_db.exceptions import (
    MigrationConnectionError,
    MigrationExecutionError,
    MigrationGenerationError,
    MigrationRollbackError,
    MigrationScriptNotFoundError,
    MigrationVerificationError,
)
from py_db.migration import (
    generate_migration,
    migrate_down,
    migrate_up,
    verify_migration,
)
from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

__all__ = [
    # 迁移公共接口
    "migrate_up",
    "migrate_down",
    "generate_migration",
    "verify_migration",
    # 迁移异常
    "MigrationExecutionError",
    "MigrationRollbackError",
    "MigrationConnectionError",
    "MigrationScriptNotFoundError",
    "MigrationGenerationError",
    "MigrationVerificationError",
    # ORM 基类
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
