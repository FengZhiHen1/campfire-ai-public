"""py-db 语法契约 — 语义类型定义。

模块: py_db.types
职责: 通过 NewType 定义数据库操作域的语义类型，防止连接串、版本号、迁移消息等
      裸 str 在类型检查期被混淆。所有语义类型在此文件中统一定义，全模块共用。
数据来源:
  - py_logger.types.ServiceName: SHOULD — 复用 py-logger 的 ServiceName 语义类型
边界:
  - 依赖: 无（仅依赖 Python stdlib typing）
  - 被依赖: py_db.migration_contract, py_db.base_repository_contract, py_db.exceptions
禁止行为:
  - 禁止在公共接口中裸用 str 替代 DatabaseUrl、MigrationTarget、RevisionHash
  - 禁止在 types.py 中定义实现代码或类——此文件只放类型
  - 禁止定义零引用的装饰品类型——每个 NewType 必须在至少一个公共接口中使用
"""

from __future__ import annotations

from typing import NewType

# ============================================================================
# 数据库连接
# ============================================================================

# === DatabaseUrl ===
# 前置: 外部环境变量或参数传入的 PostgreSQL 连接串
# 后置: 用于所有数据库连接的统一语义类型，非 PostgreSQL 格式应被前置校验拦截
# 输入约束: postgresql:// 或 postgresql+driver:// 前缀的合法连接串
# 输出约束: 通过 NewType 防止与普通 str（如日志消息、文件名）混用
DatabaseUrl = NewType("DatabaseUrl", str)

# ============================================================================
# 迁移版本
# ============================================================================

# === MigrationTarget ===
# 前置: 调用方指定的目标迁移版本标识
# 后置: 用于 migrate_up / migrate_down 的 target 参数，格式校验后传入 Alembic
# 输入约束: "head" | YYYYMMDD_HHMMSS 格式的 revision hash | 相对标记 "-N"（仅 downgrade）
# 输出约束: 通过 NewType 防止与 DatabaseUrl、MigrationMessage 混用
MigrationTarget = NewType("MigrationTarget", str)

# === RevisionHash ===
# 前置: Alembic 生成的迁移脚本 revision 标识
# 后置: 用于错误报告、日志记录中的脚本标识
# 输入约束: YYYYMMDD_HHMMSS 格式字符串（14 位数字 + 下划线）
# 输出约束: 通过 NewType 防止与 MigrationTarget（语义不同）混用
RevisionHash = NewType("RevisionHash", str)

# === MigrationMessage ===
# 前置: 调用方提供的迁移脚本语义描述
# 后置: 作为 alembic revision --message 的参数和文件名组成部分
# 输入约束: 1-128 字符的非空字符串
# 输出约束: 通过 NewType 防止与 DatabaseUrl、RevisionHash 混用
MigrationMessage = NewType("MigrationMessage", str)
