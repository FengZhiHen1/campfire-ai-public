"""DEPLOY-04 数据库迁移 — 异常定义。

定义了数据库迁移模块的 6 个具名异常类，对应落地规范 §1.9
中描述的三种错误码场景及其扩展。
"""

from __future__ import annotations


class MigrationExecutionError(Exception):
    """迁移脚本执行失败 (MIG-ERR-001)。

    任一迁移脚本的 upgrade() 函数在执行时抛出异常时触发。
    常见原因：目标表已存在、列名冲突、约束冲突、数据类型不兼容。

    Attributes:
        error_code: 错误码标识。
        script_name: 失败的迁移脚本文件名。
        revision_id: 失败脚本的 revision hash。
        current_version: 失败时数据库所处的版本号。
    """

    error_code: str = "MIG-ERR-001"

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
        super().__init__(self.message)


class MigrationRollbackError(Exception):
    """迁移脚本回滚失败 (MIG-ERR-002)。

    目标版本的 downgrade() 不存在或执行时抛出异常时触发。

    Attributes:
        error_code: 错误码标识。
        script_name: 失败的迁移脚本文件名。
        revision_id: 失败脚本的 revision hash。
        current_version: 失败时数据库所处的版本号。
    """

    error_code: str = "MIG-ERR-002"

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
        super().__init__(self.message)


class MigrationConnectionError(Exception):
    """数据库连接不可用 (MIG-ERR-003)。

    迁移开始前连接测试失败（PostgreSQL 未启动、网络不可达）或
    执行过程中连接中断时触发。连接重试 3 次（间隔 5 秒）后抛出。

    Attributes:
        error_code: 错误码标识。
        retries_attempted: 已尝试的重试次数。
    """

    error_code: str = "MIG-ERR-003"

    def __init__(
        self,
        message: str,
        retries_attempted: int = 0,
    ) -> None:
        self.message: str = message
        self.retries_attempted: int = retries_attempted
        super().__init__(self.message)


class MigrationScriptNotFoundError(Exception):
    """指定的迁移版本不存在。

    当 migrate_up 或 migrate_down 的 target 参数指向一个
    在 versions/ 目录中不存在的 revision hash 时抛出。

    Attributes:
        target: 请求的版本标识。
    """

    def __init__(self, message: str, target: str = "") -> None:
        self.message: str = message
        self.target: str = target
        super().__init__(self.message)


class MigrationGenerationError(Exception):
    """迁移脚本生成失败。

    调用 generate_migration 时 Alembic 配置不正确或
    项目结构不完整时抛出。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


class MigrationVerificationError(Exception):
    """迁移验证过程中发生非预期错误。

    调用 verify_migration 时，验证过程本身抛出非预期异常时触发。
    不包含可预期的验证失败（如缺少 downgrade——该场景通过返回码表达）。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)
