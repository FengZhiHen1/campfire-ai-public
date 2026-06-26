"""CSLT-06 咨询历史管理 — service。

模块: app.modules.consultation.history.service
职责: 咨询历史管理实现。HistoryManagerImpl 继承 BaseHistoryManager ABC，
      提供归档写入（幂等）、分页列表、详情查询三个业务能力。
      模块级便捷函数委托给单例实例。
数据来源:
  - py_db.repositories.ConsultHistoryRepository: MUST — 咨询历史持久化
  - py_schemas.consultation_history: MUST — 归档输入/输出 DTO
边界:
  - 依赖: py_db, py_logger, py_schemas
  - 被依赖: history_routes.py
禁止行为:
  - 禁止在 _do_ 钩子中直接返回 ORM 实体（必须转换为 DTO）
  - 禁止 user_id 信任前端传入的值（强制从认证上下文注入）
  - 禁止 consultation_time 使用客户端传入的时间（以服务端 NOW() 为准）
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Literal, cast
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

from app.modules.consultation.exceptions import (
    ConsultationArchiveError,
    ConsultationNotFoundError,
)

from .history_contract import BaseHistoryManager


# ============================================================================
# 兼容旧引用异常（映射到新异常体系）
# ============================================================================


class ConsultationHistoryIncompleteDataError(ConsultationArchiveError):
    """归档写入数据不完整异常（兼容旧引用，继承自 ConsultationArchiveError）。

    路由层应使用 exc.message（str）而非 exc.detail（dict）。"""
    pass


# ============================================================================
# Repository 单例
# ============================================================================

_repository = ConsultHistoryRepository()


# ============================================================================
# HistoryManagerImpl — 实现 BaseHistoryManager ABC
# ============================================================================


class HistoryManagerImpl(BaseHistoryManager):
    """咨询历史管理实现。继承 BaseHistoryManager ABC，仅覆写 _do_ 钩子。"""

    async def _do_archive(
        self,
        data: Any,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        # disclaimer 等值校验
        if data.disclaimer != GENERATION_DISCLAIMER_CONST:
            logger.warning(
                service="api-server",
                message="archive_validation_failed",
                extra={"field": "disclaimer", "reason": "disclaimer 内容与标准声明不一致"},
            )
            raise ConsultationArchiveError(
                message="disclaimer 内容与标准声明不一致，请使用 CSLT-03 输出的原始声明文本",
                field="disclaimer",
            )

        record_id = uuid.uuid4()
        archive_data: dict[str, Any] = {
            "id": record_id,
            "request_id": data.request_id,
            "user_id": current_user.get("user_id", data.user_id),
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

        record = await _repository.archive(db, archive_data)

        if record is None:
            logger.info(
                service="api-server",
                message="duplicate_archive_detected",
                extra={"request_id": str(data.request_id)},
            )
            record = await _repository.find_by_request_id(db, data.request_id)
            if record is None:
                logger.error(
                    service="api-server",
                    message="archive_inconsistency_detected",
                    extra={"request_id": str(data.request_id)},
                )
                raise ConsultationArchiveError(message="归档异常，请稍后重试")
            logger.info(
                service="api-server",
                message="duplicate_archive_returned_existing",
                extra={"record_id": str(record.id), "request_id": str(data.request_id)},
            )
        else:
            await db.flush()
            await db.refresh(record)
            logger.info(
                service="api-server",
                message="archive_success",
                extra={"record_id": str(record.id), "request_id": str(data.request_id)},
            )

        return _build_detail_response(record)

    async def _do_list_history(
        self,
        page: int,
        page_size: int,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        user_id_str = current_user.get("sub", current_user.get("user_id", ""))
        if not user_id_str:
            logger.warning(service="api-server", message="list_history_missing_user_id")
            return PaginatedResponse(
                items=[], total=0, page=page, page_size=page_size, total_pages=0,
            )

        user_id = UUID(user_id_str)
        items_raw, total = await _repository.list_by_user(db, user_id, page, page_size)
        total_pages = math.ceil(total / page_size) if total > 0 else 0

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
            extra={"user_id": user_id_str, "page": page, "total": total},
        )

        return PaginatedResponse(
            items=items, total=total, page=page, page_size=page_size, total_pages=total_pages,
        )

    async def _do_get_detail(
        self,
        consultation_id: UUID,
        current_user: dict[str, Any],
        db: AsyncSession,
    ) -> Any:
        user_id_str = current_user.get("sub", current_user.get("user_id", ""))
        if not user_id_str:
            logger.warning(
                service="api-server",
                message="get_detail_missing_user_id",
                extra={"consultation_id": str(consultation_id)},
            )
            raise ConsultationNotFoundError(
                consultation_id=str(consultation_id),
                actual_reason="user_id 缺失",
            )

        user_id = UUID(user_id_str)
        record = await _repository.find_by_id_and_user(db, consultation_id, user_id)

        if record is None:
            count = await _repository.count_by_id(db, consultation_id)
            actual_reason = "record_belongs_to_other_user" if count > 0 else "record_not_found"
            logger.warning(
                service="api-server",
                message="consultation_access_denied",
                extra={"consultation_id": str(consultation_id), "actual_reason": actual_reason},
            )
            raise ConsultationNotFoundError(
                consultation_id=str(consultation_id),
                actual_reason=actual_reason,
            )

        logger.info(
            service="api-server",
            message="get_detail_completed",
            extra={"consultation_id": str(consultation_id)},
        )
        return _build_detail_response(record)


# ============================================================================
# 辅助函数
# ============================================================================


def _build_detail_response(record: ConsultationHistoryModel) -> ConsultationHistoryDetail:
    """将 ORM 实例转换为 DTO。"""
    return ConsultationHistoryDetail(
        id=record.id,
        request_id=record.request_id,
        user_id=record.user_id,
        crisis_level=cast(Literal["mild", "moderate", "severe"], record.crisis_level),
        behavior_description=record.behavior_description,
        consultation_time=record.consultation_time,
        generated_plan=record.generated_plan,
        source_list=record.source_list or [],
        disclaimer=record.disclaimer,
        generation_time_ms=record.generation_time_ms,
        is_partial=record.is_partial,
        referenced_slice_ids=record.referenced_slice_ids or [],
        finish_reason=cast(Literal["COMPLETE", "PARTIAL", "BLOCKED", "TIMEOUT", "ERROR"], record.finish_reason),
        ttft_ms=record.ttft_ms,
        has_feedback=record.has_feedback,
        token_input=record.token_input,
        token_output=record.token_output,
        device_info=record.device_info,
    )


# ============================================================================
# 模块级单例 + 便捷函数（history_routes.py 导入入口）
# ============================================================================

_manager = HistoryManagerImpl()


async def archive_consultation(
    data: ConsultationHistoryCreate,
    current_user: dict[str, Any],
    db: AsyncSession,
) -> ConsultationHistoryDetail:
    """归档写入（委托给 HistoryManagerImpl ABC 单例）。"""
    return await _manager.archive_consultation(
        data=data,
        current_user=current_user,
        db=db,
    )


async def list_history(
    page: int,
    page_size: int,
    current_user: dict[str, Any],
    db: AsyncSession,
) -> PaginatedResponse[ConsultationHistoryListItem]:
    """历史列表（委托给 HistoryManagerImpl ABC 单例）。"""
    return await _manager.list_history(
        page=page,
        page_size=page_size,
        current_user=current_user,
        db=db,
    )


async def get_detail(
    consultation_id: UUID,
    current_user: dict[str, Any],
    db: AsyncSession,
) -> ConsultationHistoryDetail:
    """详情查询（委托给 HistoryManagerImpl ABC 单例）。"""
    return await _manager.get_detail(
        consultation_id=consultation_id,
        current_user=current_user,
        db=db,
    )


__all__ = [
    "HistoryManagerImpl",
    "archive_consultation",
    "list_history",
    "get_detail",
    "ConsultationHistoryIncompleteDataError",
]
