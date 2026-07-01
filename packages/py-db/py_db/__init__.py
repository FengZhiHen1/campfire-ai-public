"""py-db — SQLAlchemy ORM、Alembic 迁移、仓储契约与实现。

Campfire-AI 共享能力层（L2）的核心数据包。
提供数据库连接管理、ORM 模型定义、Alembic 迁移控制和通用 Repository 基类。

提供 3 大能力：
1. 数据库迁移：基于 Alembic 的版本化 Schema 管理，通过 MigrationServiceImpl
   实现 MigrationService 契约。所有迁移入口（migrate_up / migrate_down /
   generate_migration / verify_migration）由契约 @final 方法执行前置校验
   和后置处理，确保调用安全。
2. ORM 模型：SQLAlchemy 2.0 声明式映射模型，统一 Base 基类 + TimestampMixin +
   UUIDPrimaryKeyMixin。
3. 异步仓储：通用 BaseRepository 契约基类（定义于 base_repository_contract.py，
   通过 base_repository.py 桥接），提供参数化 CRUD + 连接失败重试机制。
   所有具体 Repository 子类继承此基类。

核心类：
  - MigrationServiceImpl: 实现 MigrationService 契约，Alembic 迁移执行
  - BaseRepository: 异步仓储契约 ABC，通用 CRUD 骨架（从 base_repository 导入）
  - NarrativeRepository / UserRepository / ProfileRepository / ...: 具体仓储实现

外部接口：
  - MigrationServiceImpl().migrate_up(target, database_url) -> int
  - MigrationServiceImpl().migrate_down(target, database_url) -> int
  - MigrationServiceImpl().generate_migration(message, autogenerate) -> str
  - MigrationServiceImpl().verify_migration(database_url) -> tuple[int, str]

Usage:
    from py_db import MigrationServiceImpl, Base
    from py_db.repositories import NarrativeRepository

    # 迁移操作
    impl = MigrationServiceImpl()
    impl.migrate_up()
    impl.generate_migration(message="add_user_nickname")
"""

from py_db.exceptions import (
    DbError,
    MigrationConnectionError,
    MigrationError,
    MigrationExecutionError,
    MigrationGenerationError,
    MigrationRollbackError,
    MigrationScriptNotFoundError,
    MigrationVerificationError,
    RepositoryCommunicationError,
    RepositoryError,
)
from py_db.migration import MigrationServiceImpl
from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

__all__ = [
    # 迁移服务实现
    "MigrationServiceImpl",
    # 异常基类
    "DbError",
    "MigrationError",
    "RepositoryError",
    # 迁移异常
    "MigrationExecutionError",
    "MigrationRollbackError",
    "MigrationConnectionError",
    "MigrationScriptNotFoundError",
    "MigrationGenerationError",
    "MigrationVerificationError",
    # 仓储异常
    "RepositoryCommunicationError",
    # ORM 基类
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
