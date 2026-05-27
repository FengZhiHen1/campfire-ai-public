"""CSLT-05 置信度后校验 — 工单触发模块。

负责异步调用 TICK-01 API 创建工单，含 tenacity 指数退避重试。
当前 TICK-01 未落地，使用 mock 实现占位。

重试策略：最大 3 次，指数退避 1s/3s/5s。
全部失败后抛出异常，由上层 catch 并记录 ERROR 日志。
"""

from __future__ import annotations

import json

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    RetryError,
)

from py_logger import logger

_SERVICE: str = "consult.confidence"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
)
async def trigger_ticket_with_retry(
    request_id: str,
    behavior_description: str,
    crisis_level: str,
    priority: str = "normal",
) -> dict:
    """触发工单创建，含 tenacity 指数退避重试。

    重试策略：最大 3 次，间隔 1s / 3s / 5s。
    每次重试前记录 WARNING 日志。
    3 次全部失败后通过 RetryError 向上传播。

    Args:
        request_id: 咨询追踪 ID。
        behavior_description: 脱敏后的行为描述。
        crisis_level: 危机等级（mild/moderate/severe）。
        priority: 工单优先级（normal / critical）。

    Returns:
        dict: mock 工单响应 {"id": str, "status": str}。

    Raises:
        RetryError: 3 次重试全部失败后抛出。
    """
    # ===== MOCK 实现 =====
    # TICK-01 未落地，使用 mock HTTP 响应占位:
    # 实际时应通过 httpx.AsyncClient 调用 POST /api/v1/tickets:
    #
    # async with httpx.AsyncClient() as client:
    #     response = await client.post(
    #         f"{api_base}/api/v1/tickets",
    #         json={
    #             "request_id": request_id,
    #             "context": context,
    #             "priority": priority,
    #         },
    #         timeout=10.0,
    #     )
    #     response.raise_for_status()
    #     return response.json()
    #
    # 当前返回 mock 响应供 CSLT-05 单元测试使用。

    logger.warning(
        service=_SERVICE,
        message="ticket_creation_retry",
        extra={
            "request_id": request_id,
            "priority": priority,
            "note": "TICK-01 not implemented, using mock",
        },
    )

    mock_response: dict = {
        "id": "00000000-0000-0000-0000-000000000000",
        "status": "open",
    }

    return mock_response


__all__ = [
    "trigger_ticket_with_retry",
]
