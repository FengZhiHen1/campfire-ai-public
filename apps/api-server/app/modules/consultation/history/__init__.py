"""history — 咨询历史管理子域（CSLT-06）。

提供 3 大能力：
1. 归档写入：将应急咨询上下文数据持久化（幂等，disclaimer 等值校验）
2. 历史列表：按用户分页查询历史摘要（consultation_time 降序，最多 100 条/页）
3. 详情查询：id + user_id 联合过滤（不区分"不存在"和"无权访问"）

核心类：
  - HistoryManagerImpl: 实现 BaseHistoryManager 契约，历史 CRUD

外部接口：
  - archive_consultation(data, current_user, db) -> ConsultationHistoryDetail
  - list_history(page, page_size, current_user, db) -> PaginatedResponse
  - get_detail(consultation_id, current_user, db) -> ConsultationHistoryDetail

Usage:
    from app.modules.consultation.history import archive_consultation, list_history, get_detail
"""

from __future__ import annotations

from .history_contract import BaseHistoryManager
from .service import (
    ConsultationHistoryIncompleteDataError,
    HistoryManagerImpl,
    archive_consultation,
    get_detail,
    list_history,
)

__all__ = [
    # 契约
    "BaseHistoryManager",
    # 实现
    "HistoryManagerImpl",
    # 实现接口
    "archive_consultation",
    "list_history",
    "get_detail",
    # 异常（兼容旧引用）
    "ConsultationHistoryIncompleteDataError",
]
