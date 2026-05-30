r"""py-db 异步 Repository 基类 — 实现模块。

模块: py_db.base_repository
职责: 提供 BaseRepository 的具体实现，作为所有 Repository 子类的继承入口。
      实际行为（_execute_with_retry、_do_ CRUD 钩子、@final 校验器）
      全部定义在 base_repository_contract.BaseRepository 契约中，
      本模块仅做透明桥接。

设计策略:
  - 契约（base_repository_contract.py）与实现（本模块）分离
  - 子类统一通过 `from py_db.base_repository import BaseRepository` 继承
  - 重试逻辑和日志记录由契约统一管控，使用 py_logger

边界:
  - 依赖: py_db.base_repository_contract
  - 被依赖: 所有具体 Repository 子类（CaseRepository, UserRepository 等）
"""

from __future__ import annotations

from py_db.base_repository_contract import BaseRepository

__all__ = ["BaseRepository"]
