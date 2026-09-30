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
from campfire.core.jobs import build_broker, set_dispatch_hook
from campfire.core.pending_write import (
    MAX_ATTEMPTS,
    STATE_DEAD,
    mark_dead,
    mark_retryable_failure,
)
from campfire.modules.memory.consumer import consume_memory_episode
from campfire.modules.memory.errors import MemoryDataError
from campfire.modules.memory.graph import MemoryGraph, get_shared_memory_graph

logger = logging.getLogger(__name__)

broker = build_broker(get_settings())

#: 记忆图库句柄：懒构造并复用（每次任务重建会新建驱动与连接池，
#: 见 `modules/memory/graph.py` 的实测说明）。
_memory_graph: MemoryGraph | None = None


def _get_memory_graph() -> MemoryGraph:
    """取（或首次构造）进程内复用的记忆图库句柄。

    委托给 `modules/memory/graph.get_shared_memory_graph`：**API 侧的工具要读同一张图**，
    两个入口必须共用一套句柄（每次重建会新建驱动、模型客户端与 http 客户端）。
    """
    return get_shared_memory_graph()


async def _dispatch_to_queue(pending_id: str) -> None:
    """投递一条待处理记录（装配处注入 `core/jobs` 的钩子）。

    **必须 await**：`kiq()` 返回协程，不 await 等于没有投递（mypy 抓过这个错误）。
    """
    await consume_memory_episode_task.kiq(pending_id, lease_owner="api")


# 装配点：产品侧工具（`tools/`）只依赖 `core/jobs`，不 import 本入口模块（层白名单）。
set_dispatch_hook(_dispatch_to_queue)


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
        # 其它一切按可重试处理——**宁可多重试几次，也不要把可能瞬时的失败判成永久 dead**。
        # 到上限会自动转 dead（第 6 节）。
        #
        # ⚠️ **不得在此之上加 `except MemoryModuleError` 收口**（2026-09-29 评审 S-1 实测）：
        # `MemoryUnavailableError`（图库瞬时不可用，**应可重试**）**是**
        # `MemoryModuleError` 的子类。若用基类收口，图库一次瞬时故障就会走「载荷不合法」
        # 那条路被**永久判死**。因此这里只放两个精确分支：
        # `MemoryDataError`（不可重试）→ 前面的 `dead` 分支；
        # 其余（含 `MemoryUnavailableError`）→ 落到本分支当可重试。
        # 本轮曾写过一个显式的 `except MemoryUnavailableError` 分支，消融验证它是**冗余的**
        # （删掉后 3 条分档用例仍全绿），故改为本条注释——保留教训、不留无效结构（CORE-09）。
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

    **`dead` 必须发专属告警**（第 6 节「转 `dead` **并告警**」、第 8 节「`dead` 数量
    必须告警」）。2026-09-29 评审 C-5 实测发现：此前这里只打可重试失败的 warning，
    连打 5 条一模一样、**`dead` 专属告警 0 条**——重试耗尽这件事在日志里看不出来。
    `mark_retryable_failure` 的返回值就是「本次是否转 dead」的权威信号，直接据它判定，
    不再单独查库（避免多一次往返与竞态）。
    """
    logger.warning("记忆写入失败（可重试）：pending_id=%s cause=%s", pending_id, type(exc).__name__)
    async with session_scope(get_settings()) as session:
        try:
            record = await mark_retryable_failure(session, pending_id=pending_id, error=f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 —— 登记失败不能掩盖原始错误
            logger.exception("登记可重试失败失败：pending_id=%s", pending_id)
            return
        if record.state == STATE_DEAD:
            # 专属告警：可被日志告警规则单独匹配，与普通重试 warning 区分开。
            logger.error(
                "[alert] 记忆写入重试耗尽，已转 dead：pending_id=%s attempts=%d last_error=%s"
                "（需人工排查，dead 保留 30 天）",
                pending_id,
                record.attempts,
                record.last_error,
            )
