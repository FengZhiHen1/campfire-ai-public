"""py-config 语法契约 — 语义类型与数据结构定义。

通过 NewType 防止原始类型混用，确保配置键、环境名等语义类型
在类型检查期即可区分，而非运行时才发现错误。
"""

from typing import NewType

# === 语义类型 ===

EnvName = NewType("EnvName", str)
"""运行环境标识，允许值：development / testing / production。

使用 NewType 防止将任意字符串错误传入需要环境名的上下文。
"""

ConfigFieldName = NewType("ConfigFieldName", str)
"""配置字段名（如 DATABASE_URL、JWT_SECRET_KEY）。
防止与普通消息字符串混用。
"""
