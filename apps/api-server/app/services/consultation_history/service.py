"""CSLT-06 咨询历史管理 — Service 层编排。

提供三个核心业务函数：
- archive_consultation: 归档写入（disclaimer 等值校验 + 幂等插入）
- list_history: 按用户分页查询历史摘要列表
- get_detail: 按 id + user_id 查询完整详情（404 统一模糊提示）

设计原则：
- 所有 I/O 通过 ConsultHistoryRepository 封装
- user_id 强制注入，不接受前端传入
- consultation_time 以服务端 NOW() 为准
- 异常遵循项目统一格式 {"detail": "..."}
"""

from __future__ import annotations

import math
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.consultation import ConsultationHistory as ConsultationHistoryModel
from py_db.repositories.consult_history_repository import ConsultHistoryRepository
from py_logger import logger
from py_schemas.cases import PaginatedResponse
from py_schemas.consultation_history import (
    GENERATION_DISCLAIMER_CONST,
    ConsultationHistoryCreate,
    ConsultationHistoryDetail,
    ConsultationHistoryListItem,
)


# ===========================================================================
# 模块级异常
# ===========================================================================


class ConsultationHistoryIncompleteDataError(Exception):
    """归档写入数据不完整异常。

    当必填字段缺失或 disclaimer 等值校验失败时抛出。
    全局异常处理器捕获后返回 HTTP 422。
    """

    def __init__(
        self,
        detail: str = "归档数据不完整",
        field: str | None = None,
    ) -> None:
        self.status_code: int = 422
        self.detail: str = detail
        self.field: str | None = field
        super().__init__(self.detail)


# ===========================================================================
# Repository 单例（无状态，可复用）
# ===========================================================================

_repository = ConsultHistoryRepository()


# ===========================================================================
# 辅助函数
# ===========================================================================


def _build_detail_response(record: ConsultationHistoryModel) -> ConsultationHistoryDetail:
    """将 ORM 实例转换为 ConsultationHistoryDetail 响应模型。

    Args:
        record: 数据库查询返回的 ConsultationHistory ORM 实例。

    Returns:
        ConsultationHistoryDetail 实例。
    """
    return ConsultationHistoryDetail(
        id=record.id,
        request_id=record.request_id,
        user_id=record.user_id,
        crisis_level=record.crisis_level,
        behavior_description=record.behavior_description,
        consultation_time=record.consultation_time,
        generated_plan=record.generated_plan,
        source_list=record.source_list or [],
        disclaimer=record.disclaimer,
        generation_time_ms=record.generation_time_ms,
        is_partial=record.is_partial,
        referenced_slice_ids=record.referenced_slice_ids or [],
        finish_reason=record.finish_reason,
        ttft_ms=record.ttft_ms,
        has_feedback=record.has_feedback,
        token_input=record.token_input,
        token_output=record.token_output,
        device_info=record.device_info,
    )


# ===========================================================================
# 公共业务函数
# ===========================================================================


async def archive_consultation(
    data: ConsultationHistoryCreate,
    current_user: dict,
    db: AsyncSession,
) -> ConsultationHistoryDetail:
    """将一次应急咨询的完整上下文数据归档存储为一条历史记录。

    幂等语义：重复的 request_id 提交返回已有记录（HTTP 200），不产生重复行。
    consultation_time 以服务端 PostgreSQL NOW() 为准，忽略请求体中的值。
    disclaimer 入库前做等值校验——与 CSLT-03 固定声明文本不一致时拒绝写入。

    Args:
        data: 归档数据，由 CSLT-08 编排层在咨询完成后组装。
        current_user: 当前认证用户 JWT payload 字典。
        db: 数据库异步会话。

    Returns:
        ConsultationHistoryDetail: 归档后的完整记录（含系统生成的 id）。

    Raises:
        ConsultationHistoryIncompleteDataError: 必填字段缺失或 disclaimer 等值校验失败。
    """
    # --- 步骤 1：disclaimer 等值校验 ---
    if data.disclaimer != GENERATION_DISCLAIMER_CONST:
        logger.warning(
            service="api-server",
            message="archive_validation_failed",
            extra={"field": "disclaimer", "reason": "disclaimer 内容与标准声明不一致"},
        )
        raise ConsultationHistoryIncompleteDataError(
            detail="disclaimer 内容与标准声明不一致，请使用 CSLT-03 输出的原始声明文本",
            field="disclaimer",
        )

    # --- 步骤 2：组装归档数据 ---
    record_id = uuid.uuid4()
    archive_data: dict[str, Any] = {
        "id": record_id,
        "request_id": data.request_id,
        "user_id": data.user_id,
        "crisis_level": data.crisis_level,
        "behavior_description": data.behavior_description,
        "generated_plan": data.generated_plan,
        "source_list": data.source_list,
        "disclaimer": data.disclaimer,
        "generation_time_ms": data.generation_time_ms,
        "is_partial": data.is_partial,
        "referenced_slice_ids": [str(sid) for sid in data.referenced_slice_ids],
        "finish_reason": data.finish_reason,
        "ttft_ms": data.ttft_ms,
        "has_feedback": data.has_feedback,
        "token_input": data.token_input,
        "token_output": data.token_output,
        "device_info": data.device_info,
    }

    # --- 步骤 3：幂等插入 ---
    record = await _repository.archive(db, archive_data)

    if record is None:
        # ON CONFLICT DO NOTHING 未插入新行：重复归档
        logger.info(
            service="api-server",
            message="duplicate_archive_detected",
            extra={"request_id": str(data.request_id)},
        )
        record = await _repository.find_by_request_id(db, data.request_id)
        if record is None:
            # 理论上不应发生：无冲突行但 ON CONFLICT 也未返回行
            logger.error(
                service="api-server",
                message="archive_inconsistency_detected",
                extra={"request_id": str(data.request_id)},
            )
            raise ConsultationHistoryIncompleteDataError(
                detail="归档异常，请稍后重试",
            )
        logger.info(
            service="api-server",
            message="duplicate_archive_returned_existing",
            extra={"record_id": str(record.id), "request_id": str(data.request_id)},
        )
    else:
        # 首次插入成功
        await db.flush()
        await db.refresh(record)
        logger.info(
            service="api-server",
            message="archive_success",
            extra={"record_id": str(record.id), "request_id": str(data.request_id), "user_id": str(data.user_id)},
        )

    return _build_detail_response(record)


async def list_history(
    page: int,
    page_size: int,
    current_user: dict,
    db: AsyncSession,
) -> PaginatedResponse[ConsultationHistoryListItem]:
    """查询当前用户的所有咨询历史记录摘要列表。

    按 consultation_time 降序排列。每页最多显示 page_size 条。
    page 超出总页数时返回空列表 + 正确的 total 和 total_pages（HTTP 200）。

    Args:
        page: 页码（1-based）。
        page_size: 每页记录数。
        current_user: 当前认证用户 JWT payload 字典。
        db: 数据库异步会话。

    Returns:
        PaginatedResponse[ConsultationHistoryListItem]: 分页响应。
    """
    user_id_str = current_user.get("sub", current_user.get("user_id", ""))
    if not user_id_str:
        logger.warning(service="api-server", message="list_history_missing_user_id")
        return PaginatedResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
        )

    user_id = UUID(user_id_str)

    # 执行分页查询
    items_raw, total = await _repository.list_by_user(db, user_id, page, page_size)

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    # 转换 items 为 ConsultationHistoryListItem
    items: list[ConsultationHistoryListItem] = [
        ConsultationHistoryListItem(
            id=item["id"],
            consultation_time=item["consultation_time"],
            behavior_description=item["behavior_description"],
            crisis_level=item["crisis_level"],
            has_feedback=item["has_feedback"],
        )
        for item in items_raw
    ]

    logger.info(
        service="api-server",
        message="list_history_completed",
        extra={
            "user_id": user_id_str,
            "page": page,
            "page_size": page_size,
            "total": total,
            "returned": len(items),
        },
    )

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


async def get_detail(
    consultation_id: UUID,
    current_user: dict,
    db: AsyncSession,
) -> ConsultationHistoryDetail:
    """查询单次咨询的完整详情。

    仅返回当前用户本人的记录。记录不存在或 user_id 不匹配时统一返回
    HTTPException(404)，对外不区分两种情况（保护用户隐私）。
    内部日志中记录实际拒绝原因供运维排查。

    Args:
        consultation_id: 咨询记录 ID（UUID 格式）。
        current_user: 当前认证用户 JWT payload 字典。
        db: 数据库异步会话。

    Returns:
        ConsultationHistoryDetail: 咨询完整详情。

    Raises:
        HTTPException(404): 记录不存在或无权查看。
    """
    from fastapi import HTTPException, status

    user_id_str = current_user.get("sub", current_user.get("user_id", ""))
    if not user_id_str:
        logger.warning(
            service="api-server",
            message="get_detail_missing_user_id",
            extra={"consultation_id": str(consultation_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该咨询记录不存在或无权查看",
        )

    user_id = UUID(user_id_str)

    # 主查询：id + user_id 联合过滤
    record = await _repository.find_by_id_and_user(db, consultation_id, user_id)

    if record is None:
        # 辅助查询：区分不存在 vs 无权访问
        count = await _repository.count_by_id(db, consultation_id)
        if count > 0:
            logger.warning(
                service="api-server",
                message="consultation_access_denied",
                extra={"consultation_id": str(consultation_id), "actual_reason": "record_belongs_to_other_user"},
            )
        else:
            logger.warning(
                service="api-server",
                message="consultation_access_denied",
                extra={"consultation_id": str(consultation_id), "actual_reason": "record_not_found"},
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该咨询记录不存在或无权查看",
        )

    logger.info(
        service="api-server",
        message="get_detail_completed",
        extra={"consultation_id": str(consultation_id), "user_id": user_id_str},
    )

    return _build_detail_response(record)


__all__ = [
    "archive_consultation",
    "list_history",
    "get_detail",
    "ConsultationHistoryIncompleteDataError",
]
