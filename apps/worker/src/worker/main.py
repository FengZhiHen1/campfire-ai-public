"""Campfire-AI Worker — 后台任务消费主循环。

监听 Redis 队列，执行异步任务：
- campfire:case_index → 案例向量化索引入库

MVP Phase 0 精简版。
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys

import redis

from py_config import get_settings
from py_logger import logger
from worker.tasks.case_indexer import index_case

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_REDIS_QUEUE: str = "campfire:case_index"
_BLPOP_TIMEOUT: int = 5

# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

_shutdown_event: asyncio.Event = asyncio.Event()
_redis_client: redis.Redis | None = None

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 信号处理
# ---------------------------------------------------------------------------


def _handle_signal(signum: int, _frame) -> None:
    """处理 SIGTERM / SIGINT，触发优雅关闭。"""
    sig_name = signal.Signals(signum).name
    logger.info("worker", f"收到信号 {sig_name}，开始优雅关闭...")
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Redis 连接
# ---------------------------------------------------------------------------


def _get_redis() -> redis.Redis:
    """获取或创建 Redis 同步客户端。"""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(str(settings.REDIS_URL), decode_responses=True)
    return _redis_client


# ---------------------------------------------------------------------------
# 任务分发
# ---------------------------------------------------------------------------


async def _process_task(raw_message: str) -> None:
    """解析并执行单个任务。"""
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError as exc:
        logger.error("worker", f"任务消息 JSON 解析失败: {exc}", extra={"raw": raw_message})
        return

    task_type = payload.get("task")
    case_id = payload.get("case_id")

    if task_type == "index_case" and case_id:
        logger.info("worker", f"开始处理案例索引: {case_id}")
        try:
            await index_case(case_id)
        except Exception as exc:
            logger.error(
                "worker",
                f"案例索引任务异常: {case_id}",
                extra={"case_id": case_id, "error": str(exc)},
            )
    else:
        logger.warning(
            "worker",
            f"未知任务类型或缺失参数: {task_type}",
            extra={"payload": payload},
        )


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------


async def _main_loop() -> None:
    """Redis BLPOP 消费主循环。"""
    redis_client = _get_redis()
    logger.info("worker", f"Worker 启动，监听队列: {_REDIS_QUEUE}")

    while not _shutdown_event.is_set():
        try:
            # BLPOP 阻塞等待，超时后检查关闭标志
            result = redis_client.blpop(_REDIS_QUEUE, timeout=_BLPOP_TIMEOUT)
            if result is None:
                continue

            _queue_name, raw_message = result
            await _process_task(raw_message)

        except redis.RedisError as exc:
            logger.error("worker", f"Redis 连接错误: {exc}")
            await asyncio.sleep(5)
        except Exception as exc:
            logger.error("worker", f"主循环异常: {exc}")
            await asyncio.sleep(1)

    logger.info("worker", "Worker 主循环已退出")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI 入口。"""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        asyncio.run(_main_loop())
    except KeyboardInterrupt:
        logger.info("worker", "Worker 被键盘中断")
    finally:
        if _redis_client:
            _redis_client.close()
        logger.info("worker", "Worker 已关闭")


if __name__ == "__main__":
    main()
