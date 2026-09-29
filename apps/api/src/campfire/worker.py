"""Taskiq Worker 入口。

归属（见 docs/项目结构设计.md 第 7 节）：worker 入口允许依赖 ``core/*`` 与
``modules/{profile,memory}``；**禁止 import ``surfaces/*``，禁止回查业务用例**。

运行模型（见 docs/技术栈设计.md 第 5 节）：全异步，**不引入同步与异步之间的
桥接**；broker 与 HTTP 入口共用同一份构造（``core/jobs.build_broker``）。

## 已注册的任务

- ``consume_memory_episode``：消费 ``kind = memory_episode`` 的待处理记录
  （写入链路见 docs/技术设计/technical-details/写入路径.md 第 4、5、6 节）。

## 失败语义（第 6 节）

任务**不吞异常**：可重试失败由本入口按状态机记 ``attempts + 1`` 与退避，
超过上限转 ``dead`` 并告警。**图库故障不等于写入成功**——记录留在 ``pending``/``dead``，
「没写进去」绝不能被当作「写进去了」（第 2 节的不变量）。

启动方式：``uv run taskiq worker campfire.worker:broker``
"""

import logging

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.jobs import build_broker
from campfire.core.pending_write import (
    MAX_ATTEMPTS,
    mark_dead,
    mark_retryable_failure,
)
from campfire.modules.memory.consumer import consume_memory_episode
from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.graph import MemoryGraph, build_memory_graph

logger = logging.getLogger(__name__)

broker = build_broker(get_settings())

#: 记忆图库句柄：懒构造并复用（每次任务重建会新建驱动与连接池，
#: 见 `modules/memory/graph.py` 的实测说明）。
_memory_graph: MemoryGraph | None = None


def _get_memory_graph() -> MemoryGraph:
    """取（或首次构造）进程内复用的记忆图库句柄。"""
    global _memory_graph
    if _memory_graph is None:
        _memory_graph = build_memory_graph(get_settings())
    return _memory_graph


@broker.task
async def consume_memory_episode_task(pending_id: str, lease_owner: str = "worker") -> str:
    """消费一条记忆待处理记录。

    返回状态字符串（``written`` / ``skipped``），供 Taskiq 记录与排查。

    Args:
        pending_id: 待处理记录标识（Taskiq 任务载荷）。
        lease_owner: Worker 标识；默认 ``worker``。生产应传实例名，便于排查
            「谁持有租约」。

    Returns:
        ``"written"`` 表示本次写入图库并置 ``done``；``"skipped"`` 表示未领取到
        （已被他人领取/租约未到期/已终结）——**不是错误**。

    Raises:
        MemoryDataError: 载荷不合法（形状错误）。这类失败**重试无用**，因此直接转
            ``dead`` 并抛出，让 Taskiq 记录失败。
        Exception: 基础设施类失败（图库/数据库不可用，含 ``MemoryUnavailableError``）
            按第 6 节记 ``attempts + 1`` 与退避后**原样抛出**——吞掉它会让队列以为
            任务成功。
    """
    graph = _get_memory_graph()
    try:
        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(session, graph, pending_id=pending_id, lease_owner=lease_owner)
    except MemoryUnavailableError as exc:
        # **可重试**：图库/查询暂时不可用（第 6 节的「Worker 处理失败（可重试）」）。
        # ⚠️ 这个分支必须在 `MemoryModuleError` **之前**（2026-09-29 自查发现，实测确认）：
        # `MemoryUnavailableError` 是 `MemoryModuleError` 的子类，若只写基类分支，
        # 图库一次瞬时故障就会被归成「载荷不合法」而直接转 `dead`——**一条本来健康的
        # 记录被永久判死**。按类型分档时，子类分支必须排在父类之前。
        await _register_retryable_failure(pending_id, exc)
        raise
    except MemoryDataError as exc:
        # **不可重试**：载荷/形状不合法，重试不会变好，直接转 `dead`
        # （第 6 节：不得静默丢弃）。`session_scope` 已回滚，故另开会话登记终结状态。
        logger.warning("记忆写入的载荷不合法，转 dead：pending_id=%s cause=%s", pending_id, type(exc).__name__)
        async with session_scope(get_settings()) as session:
            try:
                await mark_dead(session, pending_id=pending_id, error=f"{type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001 —— 登记失败不能掩盖原始错误
                logger.exception("登记 dead 失败：pending_id=%s", pending_id)
        raise
    except Exception as exc:
        # 其它一切（含数据库不可用）：按可重试处理——**宁可多重试几次，也不要把可能
        # 瞬时的失败判成永久 dead**。到上限会自动转 dead（第 6 节）。
        await _register_retryable_failure(pending_id, exc)
        raise

    if not result.written:
        # 未领取到：并发的正常结果，不记失败（记失败会让每次竞争都进 attempts）。
        return "skipped"
    logger.info(
        "记忆已写入：pending_id=%s episode=%s（上限 %d 次重试）",
        pending_id,
        result.episode_uuid,
        MAX_ATTEMPTS,
    )
    return "written"


async def _register_retryable_failure(pending_id: str, exc: BaseException) -> None:
    """记一次可重试失败（`attempts+1` 与退避；到上限自动转 `dead`）。

    登记本身失败**不能掩盖原始错误**：调用方紧接着会重新抛出 `exc`，这里只记日志。
    错误摘要**只写类型名与消息**，不复述连接串或凭据（AGENTS.md 安全条款）。
    """
    logger.warning("记忆写入失败（可重试）：pending_id=%s cause=%s", pending_id, type(exc).__name__)
    async with session_scope(get_settings()) as session:
        try:
            await mark_retryable_failure(session, pending_id=pending_id, error=f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 —— 登记失败不能掩盖原始错误
            logger.exception("登记可重试失败失败：pending_id=%s", pending_id)
