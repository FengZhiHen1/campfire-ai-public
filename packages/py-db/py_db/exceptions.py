"""py-db 异常层次 — 统一错误类型定义。

模块: py_db.exceptions
职责: 定义 py-db 包内所有异常的统一层次结构。所有异常继承自 DbError 基类，
      上层可通过 except DbError 统一捕获本包的所有错误。
数据来源:
  - 无外部数据依赖
边界:
  - 依赖: 无（仅依赖 Python stdlib）
  - 被依赖: py_db.migration, py_db.repositories
禁止行为:
  - 禁止在异常类中混入业务逻辑或 IO 操作
  - 禁止异常缺少诊断字段——构造函数参数即诊断字段
  - 禁止在包外定义 py-db 相关异常——统一由此文件管理
"""

# @contract — py-db 异常层次契约（DbError → MigrationError / RepositoryError）

from __future__ import annotations


# ============================================================================
# 基类
# ============================================================================


class DbError(Exception):
    """py-db 包所有异常的基类。

    触发条件: 数据库操作中任何预期内的错误场景。
    诊断字段:
      - message: 人类可读的错误描述。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(message)


# ============================================================================
# 迁移异常
# ============================================================================


class MigrationError(DbError):
    """迁移操作异常的基类。

    触发条件: 迁移流程（升级/回滚/生成/验证）中的任何错误。
    诊断字段:
      - message: 人类可读的错误描述。
      - error_code: 结构化错误码（如 MIG-ERR-001）。
      - script_name: 失败的迁移脚本文件名（可选）。
      - revision_id: 失败脚本的 revision hash（可选）。
      - current_version: 失败时数据库所处的版本号（可选）。
    """

    error_code: str = "MIG-ERR-000"

    def __init__(
        self,
        message: str,
        script_name: str = "",
        revision_id: str = "",
        current_version: str = "",
    ) -> None:
        self.message: str = message
        self.script_name: str = script_name
        self.revision_id: str = revision_id
        self.current_version: str = current_version
        super().__init__(message)


class MigrationExecutionError(MigrationError):
    """迁移脚本执行失败 (MIG-ERR-001)。

    触发条件: 任一迁移脚本的 upgrade() 函数在执行时抛出异常。
              常见原因：目标表已存在、列名冲突、约束冲突、数据类型不兼容。
    诊断字段:
      - message: 错误描述（含异常消息）。
      - error_code: 错误码 MIG-ERR-001。
      - script_name: 失败的迁移脚本文件名。
      - revision_id: 失败脚本的 revision hash。
      - current_version: 失败时数据库所处的版本号。
    """

    error_code: str = "MIG-ERR-001"


class MigrationRollbackError(MigrationError):
    """迁移脚本回滚失败 (MIG-ERR-002)。

    触发条件: 目标版本的 downgrade() 不存在或执行时抛出异常。
    诊断字段:
      - message: 错误描述。
      - error_code: 错误码 MIG-ERR-002。
      - script_name: 失败的迁移脚本文件名。
      - revision_id: 失败脚本的 revision hash。
      - current_version: 失败时数据库所处的版本号。
    """

    error_code: str = "MIG-ERR-002"


class MigrationConnectionError(MigrationError):
    """数据库连接不可用 (MIG-ERR-003)。

    触发条件: 迁移开始前连接测试失败（PostgreSQL 未启动、网络不可达）
              或执行过程中连接中断。连接重试耗尽后抛出。
    诊断字段:
      - message: 错误描述。
      - error_code: 错误码 MIG-ERR-003。
      - retries_attempted: 已尝试的重试次数。
    """

    error_code: str = "MIG-ERR-003"

    def __init__(
        self,
        message: str,
        retries_attempted: int = 0,
    ) -> None:
        self.retries_attempted: int = retries_attempted
        super().__init__(message)


class MigrationScriptNotFoundError(MigrationError):
    """指定的迁移版本不存在。

    触发条件: migrate_up 或 migrate_down 的 target 参数指向一个
              在 versions/ 目录中不存在的 revision hash 时抛出。
    诊断字段:
      - message: 错误描述。
      - target: 请求的版本标识。
    """

    def __init__(self, message: str, target: str = "") -> None:
        self.target: str = target
        super().__init__(message)


class MigrationGenerationError(MigrationError):
    """迁移脚本生成失败。

    触发条件: 调用 generate_migration 时 Alembic 配置不正确
              或项目结构不完整时抛出。
    诊断字段:
      - message: 错误描述。
    """


class MigrationVerificationError(MigrationError):
    """迁移验证过程中发生非预期错误。

    触发条件: 调用 verify_migration 时，验证过程本身抛出非预期异常。
              不包含可预期的验证失败（如缺少 downgrade——该场景通过返回码表达）。
    诊断字段:
      - message: 错误描述。
    """


# ============================================================================
# 仓储异常
# ============================================================================


class RepositoryError(DbError):
    """仓储操作异常的基类。

    触发条件: 仓储层数据操作中的任何错误。
    诊断字段:
      - message: 人类可读的错误描述。
      - operation_name: 失败的操作名称（可选）。
    """

    def __init__(self, message: str, operation_name: str = "") -> None:
        self.message: str = message
        self.operation_name: str = operation_name
        super().__init__(message)


class RepositoryCommunicationError(RepositoryError):
    """数据库连接不可达（仓储层）。

    触发条件: 仓储操作在最大重试次数后仍无法连接数据库。
              向上层传递到 FastAPI 后应返回 HTTP 503。
    诊断字段:
      - message: 错误描述（含最后异常信息）。
      - operation_name: 失败的操作名称。
      - retries_attempted: 已尝试的重试次数。
    """

    def __init__(
        self,
        message: str,
        operation_name: str = "",
        retries_attempted: int = 0,
    ) -> None:
        self.retries_attempted: int = retries_attempted
        super().__init__(message, operation_name=operation_name)
