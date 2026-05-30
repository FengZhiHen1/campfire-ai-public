"""py-db Repository 基类 — 向后兼容重导出模块。

自 py-db 契约重构后，BaseRepository 已迁移至 py_db.base_repository，
DependencyCommunicationError 已迁移至 py_db.exceptions.RepositoryCommunicationError。

本文件保留向后兼容重导出，所有符号指向新的规范位置。
建议新代码直接引用新路径：
  - from py_db.base_repository import BaseRepository
  - from py_db.exceptions import RepositoryCommunicationError
"""

from __future__ import annotations

from py_db.base_repository import BaseRepository
from py_db.exceptions import RepositoryCommunicationError

# 向后兼容别名 —— 旧代码中使用的 DependencyCommunicationError
# 映射到新的 RepositoryCommunicationError
DependencyCommunicationError = RepositoryCommunicationError

__all__ = [
    "BaseRepository",
    "RepositoryCommunicationError",
    "DependencyCommunicationError",
]
