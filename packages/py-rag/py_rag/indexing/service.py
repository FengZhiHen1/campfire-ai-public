"""CASE-04 索引服务入口模块（索引管线步骤 1-3）。

对外暴露 RedisIndexService 类和两个模块级便捷函数：
  - enqueue_index_task(case_id, db_session): 将审核通过案例投递到异步队列
  - manual_retry_index(case_id, db_session): 对手动重试案例重新投递

RedisIndexService 实现 BaseIndexService 契约，通过 @final enqueue() 和
@final manual_retry() 获得统一的输入校验、状态分支判断和幂等保护。

同步投递路径（步骤 1-3）：
  1. 输入校验与状态查询（契约统一处理）
  2. 状态分支判断 — 幂等跳转或允许入队（契约统一处理）
  3. 生成任务载荷并 LPUSH 到 Redis List（实现者填充 _do_enqueue 钩子）
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from py_cache import get_redis_client
from py_logger import logger
from py_rag.exceptions import RedisConnectionError
from py_rag.indexing_contract import (
    INDEX_QUEUE_KEY,
    REDIS_LPUSH_RETRY_COUNT,
    REDIS_LPUSH_RETRY_INTERVAL,
    BaseIndexService,
)
from py_rag.models import IndexTaskEnvelope
from py_rag.types import CaseIdStr

# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_service: RedisIndexService | None = None


def _get_service() -> RedisIndexService:
    """获取全局索引服务单例。"""
    global _service
    if _service is None:
        _service = RedisIndexService()
    return _service


# ---------------------------------------------------------------------------
# RedisIndexService — 契约实现类
# ---------------------------------------------------------------------------


class RedisIndexService(BaseIndexService):
    """基于 Redis List 的索引任务投递服务。

    实现 BaseIndexService 契约的 _do_enqueue() 和 _check_case_status() 钩子。
    """

    # === _do_enqueue 钩子实现 ===

    async def _do_enqueue(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """生成任务载荷并 LPUSH 到 Redis List，CAS 更新 index_status。

        Args:
            case_id: 已通过前置校验的案例标识。
            db_session: SQLAlchemy 异步会话。

        Returns:
            {"status": "enqueued"} 或 {"status": "already_queued"}（CAS 冲突）。

        Raises:
            RedisConnectionError: Redis LPUSH 重试耗尽。
        """
        case_id_str = str(case_id)

        trace_id = secrets.token_hex(16)
        enqueued_at = datetime.now(timezone.utc).isoformat()

        envelope = IndexTaskEnvelope(
            case_id=case_id_str,
            trace_id=trace_id,
            enqueued_at=enqueued_at,
        )

        json_str = json.dumps(envelope.model_dump(), ensure_ascii=False)

        redis_client = await get_redis_client()

        last_error: Exception | None = None
        for attempt in range(REDIS_LPUSH_RETRY_COUNT + 1):
            try:
                await redis_client.lpush(INDEX_QUEUE_KEY, json_str)
                break
            except Exception as exc:
                last_error = exc
                if attempt < REDIS_LPUSH_RETRY_COUNT:
                    await asyncio.sleep(REDIS_LPUSH_RETRY_INTERVAL)
                else:
                    logger.critical(
                        "py-rag",
                        "索引队列不可用，案例索引入库暂时中断",
                        op_type="redis_unavailable",
                        extra={
                            "operation": "lpush",
                            "case_id": case_id_str,
                            "retry_count": REDIS_LPUSH_RETRY_COUNT,
                            "error": str(exc),
                        },
                    )
                    raise RedisConnectionError(
                        "索引队列不可用，案例索引入库暂时中断"
                    ) from exc

        # CAS UPDATE case_cards SET index_status = 'pending'
        update_sql = text("""
            UPDATE case_cards
            SET index_status = 'pending'
            WHERE card_id = :card_id
              AND (index_status IS NULL
                   OR index_status = 'indexing_failed'
                   OR index_status NOT IN ('pending', 'processing', 'indexed'))
        """)
        update_result = await db_session.execute(update_sql, {"card_id": case_id_str})
        await db_session.commit()

        if update_result.rowcount == 0:  # type: ignore[attr-defined]
            logger.warning(
                "py-rag",
                "CAS 冲突：任务已入队但状态更新失败",
                op_type="enqueue_cas_conflict",
                extra={"case_id": case_id_str},
            )
            return {"status": "already_queued"}

        logger.info(
            "py-rag",
            "案例索引任务入队成功",
            op_type="enqueue",
            extra={
                "case_id": case_id_str,
                "trace_id": trace_id,
                "index_status": "pending",
            },
        )

        return {"status": "enqueued"}

    # === _check_case_status 钩子实现 ===

    async def _check_case_status(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> str | None:
        """查询案例审核与索引状态。

        Args:
            case_id: 案例标识。
            db_session: SQLAlchemy 异步会话。

        Returns:
            'approved_pending' — 可入队
            'already_indexed' — 已索引，幂等跳过
            'already_queued' — 已在队列中，幂等跳过
            'failed' — 索引失败，可手动重试
            None — 案例不存在
        """
        case_id_str = str(case_id)

        query_sql = text(
            """SELECT card_id, review_status, index_status
               FROM case_cards WHERE card_id = :card_id"""
        )
        result = await db_session.execute(query_sql, {"card_id": case_id_str})
        row = result.fetchone()

        if row is None:
            return None

        row_dict: dict[str, Any] = dict(row._mapping)
        review_status: str | None = row_dict.get("review_status")
        index_status: str | None = row_dict.get("index_status")

        if review_status != "approved":
            raise ValueError(
                f"案例 {case_id_str} 未审核通过，当前状态: {review_status}"
            )

        if index_status == "indexed":
            logger.info(
                "py-rag",
                "案例已索引完成，幂等跳过",
                op_type="enqueue_skipped",
                extra={
                    "case_id": case_id_str,
                    "index_status": index_status,
                    "reason": "already_indexed",
                },
            )
            return "already_indexed"

        if index_status in ("pending", "processing"):
            logger.info(
                "py-rag",
                "案例已在索引队列或处理中，幂等跳过",
                op_type="enqueue_skipped",
                extra={
                    "case_id": case_id_str,
                    "index_status": index_status,
                    "reason": "already_queued",
                },
            )
            return "already_queued"

        if index_status == "indexing_failed":
            return "failed"

        # 默认：审核通过但尚未入队
        return "approved_pending"


# ---------------------------------------------------------------------------
# 模块级便捷函数（向后兼容）
# ---------------------------------------------------------------------------


async def enqueue_index_task(
    case_id: uuid_lib.UUID,
    db_session: AsyncSession,
) -> dict[str, str]:
    """将审核通过的案例卡片投递到索引入库异步队列。

    委托 RedisIndexService.enqueue()，走完整契约管线：
    输入校验 → 状态查询 → 幂等判断 → 投递 Redis List。

    Args:
        case_id: 审核通过的案例唯一标识（UUID v4）。
        db_session: SQLAlchemy 异步会话。

    Returns:
        {"status": "enqueued" | "already_queued" | "already_indexed"}

    Raises:
        ValueError: case_id 格式无效、案例不存在、或案例未审核通过。
        RedisConnectionError: Redis List 连接失败（重试后仍失败）。
    """
    if not isinstance(case_id, uuid_lib.UUID):
        raise ValueError("无效的 case_id 格式")

    return await _get_service().enqueue(
        case_id=CaseIdStr(str(case_id)),
        db_session=db_session,
    )


async def manual_retry_index(
    case_id: uuid_lib.UUID,
    db_session: AsyncSession,
) -> dict[str, str]:
    """对索引入库失败的案例执行手动重新索引。

    仅当案例 index_status = 'indexing_failed' 时允许调用。

    Args:
        case_id: 索引异常的案例唯一标识（UUID v4）。
        db_session: SQLAlchemy 异步会话。

    Returns:
        {"status": "enqueued"}

    Raises:
        ValueError: 案例不存在或 index_status 非 indexing_failed。
    """
    if not isinstance(case_id, uuid_lib.UUID):
        raise ValueError("无效的 case_id 格式")

    case_id_str = str(case_id)

    logger.info(
        "py-rag",
        "手动重试索引",
        op_type="manual_retry",
        extra={"case_id": case_id_str},
    )

    return await _get_service().manual_retry(
        case_id=CaseIdStr(case_id_str),
        db_session=db_session,
    )


__all__ = [
    "RedisIndexService",
    "enqueue_index_task",
    "manual_retry_index",
]
