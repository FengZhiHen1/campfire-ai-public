"""Taskiq Worker 入口。

职责：按 `kind` 分派待处理记录（当前已接上消费者的是 `memory_episode`），
并跑常驻兜底扫描（第 4.1 节）。
边界：只依赖 `core/*` 与 `modules/{profile,memory}`；禁止 import `surfaces/*`。
参考：写入路径第 4、5、6 节。
启动方式：`uv run taskiq worker campfire.worker:broker`
"""

# 归属（见 docs/项目结构设计.md 第 7 节）：worker 入口允许依赖 `core/*` 与
# `modules/{profile,memory}`；禁止 import `surfaces/*`，禁止回查业务用例。
#
# 已注册的任务：
#
# - `consume_memory_episode`：消费 `kind = memory_episode` 的待处理记录
#   （写入链路见 docs/技术设计/technical-details/写入路径.md 第 4、5、6 节）。
# - 兜底扫描（第 4.1 节）：Worker 启动时拉起一个常驻周期任务，回收过期租约并把
#   「该处理却没被处理」的记录重新投递。跑在 Worker 进程内、不新增部署单元
#   （2026-09-30 裁决；重访条件见 `_start_sweep` 的 docstring）。
#
# 投递按 `kind` 分派（第 4 节第 3 条）：分派表是 `_CONSUMER_DISPATCHERS`。
# 表里没有的 kind 显式跳过、不终结记录——`profile_item` 的消费分支归 T12，
# 在它落地之前这些记录必须留在 `pending` 而不是被误投给记忆消费者判 `dead`
# （2026-09-30 修复：此前投递钩子硬编码只投记忆任务）。

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqEvents

from campfire.core.authz import set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.jobs import build_broker, dispatch_pending_write, set_dispatch_hook
from campfire.core.pending_write import (
    KIND_MEMORY_EPISODE,
    MAX_ATTEMPTS,
    STATE_DEAD,
    find_undelivered,
    mark_dead,
    mark_retryable_failure,
    reclaim_expired_leases,
)
from campfire.modules.memory.consumer import consume_memory_episode
from campfire.modules.memory.errors import MemoryDataError
from campfire.modules.memory.graph import MemoryGraph, get_shared_memory_graph
from campfire.modules.profile.authz import OwnerAuthorizer

logger = logging.getLogger(__name__)

broker = build_broker(get_settings())

# 装配点：授权实现（`core/authz` 的端口）由本入口注入。
# Worker 侧必须注入：`write_from_pending` 在领取 `profile_item` 时按第 6 节
# 重新做一次授权判定，而该判定经 `core/authz` 的端口——未注入时端口 fail-closed
# （拒绝），不会静默放行（`core/authz.port` 的 `_require_injected`）。
set_authorizer(OwnerAuthorizer(get_settings()))

#: 记忆图库句柄：懒构造并复用（每次任务重建会新建驱动与连接池，
#: 见 `modules/memory/graph.py` 的实测说明）。
_memory_graph: MemoryGraph | None = None


def _get_memory_graph() -> MemoryGraph:
    """取（或首次构造）进程内复用的记忆图库句柄。

    委托给 `modules/memory/graph.get_shared_memory_graph`：API 侧的工具要读同一张图，
    两个入口必须共用一套句柄（每次重建会新建驱动、模型客户端与 http 客户端）。
    """
    return get_shared_memory_graph()


async def _enqueue_memory_episode(pending_id: str) -> None:
    """把一条 `memory_episode` 投给记忆消费者任务。"""
    await consume_memory_episode_task.kiq(pending_id, lease_owner="api")


#: kind → 投递到队列的函数（分派表，写入路径第 4 节第 3 条）。
#:
#: 每条记录只能交给懂它的消费者：`memory_episode` 交给记忆任务。表里没有的 kind
#: 显式跳过——不投、不改状态、记一条 warning，记录留在 `pending` 等消费者接上。
#:
#: 为什么不给未注册的 kind 一个兜底消费者：那等于把异构载荷塞给不懂它的消费者，
#: 它只能判载荷不合法，结果是记录被永久判 `dead`（2026-09-30 修复前的实际行为）。
#:
#: 当前只有 `memory_episode`：`profile_item` 的用例侧消费已就绪
#: （`modules/profile/consumer.write_from_pending`），缺的是 Worker 侧的任务接线，
#: 归 T12。`KINDS` 的每个取值都必须在这里有键——机械检查见
#: `apps/api/tests/test_pending_write_dispatch.py`（它当前把 T12 的缺口钉住）。
_CONSUMER_DISPATCHERS: dict[str, Callable[[str], Awaitable[None]]] = {
    KIND_MEMORY_EPISODE: _enqueue_memory_episode,
}

#: 已接上消费者的 kind（分派表的键集）。兜底扫描据此过滤候选集：没有消费者的 kind
#: 投出去也没人接，而它们一直停在 `pending`、又排在最前，会白占每轮的条数预算。
CONSUMED_KINDS: frozenset[str] = frozenset(_CONSUMER_DISPATCHERS)


async def dispatch_pending_write_to_queue(pending_id: str, kind: str) -> None:
    """按 `kind` 投递一条待处理记录（装配处注入 `core/jobs` 的钩子实现）。

    运行模型（见 docs/技术栈设计.md 第 5 节）：全异步，不引入同步与异步之间的
    桥接；broker 与 HTTP 入口共用同一份构造（`core/jobs.build_broker`）。

    必须 await：`kiq()` 返回协程，不 await 等于没有投递（mypy 抓过这个错误）。

    未注册消费者的 kind 走显式跳过：记一条 warning 后原样返回，不投给别的消费者、
    不改记录状态。这是「不终结」的处置——记录仍是 `pending`，消费者接上后由兜底扫描
    自动带回（扫描按 `CONSUMED_KINDS` 过滤，见 `sweep_once`）。绝不能因为「暂时没人接」
    把它判 `dead`：`dead` 的含义是「授权不再成立」或「重试耗尽」（第 6 节），
    而分派不到消费者是装配缺口，不是这条记录的失败。
    """
    dispatcher = _CONSUMER_DISPATCHERS.get(kind)
    if dispatcher is None:
        logger.warning(
            "尚无 kind=%s 的消费者，跳过投递（记录留在 pending，待消费者接上后由兜底扫描带回）：pending_id=%s",
            kind,
            pending_id,
        )
        return
    await dispatcher(pending_id)


# 装配点：产品侧工具（`tools/`）与 API 入口只依赖 `core/jobs`，
# 不 import 本入口模块（层白名单）。
set_dispatch_hook(dispatch_pending_write_to_queue)


@broker.task
async def consume_memory_episode_task(pending_id: str, lease_owner: str = "worker") -> str:
    """消费一条记忆待处理记录。

    失败语义（第 6 节）：
    任务不吞异常：可重试失败由本入口按状态机记 `attempts + 1` 与退避，
    超过上限转 `dead` 并告警。图库故障不等于写入成功——记录留在 `pending`/`dead`，
    「没写进去」绝不能被当作「写进去了」（第 2 节的不变量）。

    返回状态字符串（`written` / `skipped`），供 Taskiq 记录与排查。

    Args:
        pending_id: 待处理记录标识（Taskiq 任务载荷）。
        lease_owner: Worker 标识；默认 `worker`。生产应传实例名，便于排查
            「谁持有租约」。

    Returns:
        `"written"` 表示本次写入图库并置 `done`；`"skipped"` 表示未领取到
        （已被他人领取/租约未到期/已终结）——不是错误。

    Raises:
        MemoryDataError: 载荷不合法（形状错误）。这类失败重试无用，因此直接转
            `dead` 并抛出，让 Taskiq 记录失败。
        Exception: 基础设施类失败（图库/数据库不可用，含 `MemoryUnavailableError`）
            按第 6 节记 `attempts + 1` 与退避后原样抛出——吞掉它会让队列以为
            任务成功。
    """
    graph = _get_memory_graph()
    try:
        async with session_scope(get_settings()) as session:
            result = await consume_memory_episode(session, graph, pending_id=pending_id, lease_owner=lease_owner)
    except MemoryDataError as exc:
        # 不可重试：载荷/形状不合法，重试不会变好，直接转 `dead`
        # （第 6 节：不得静默丢弃）。`session_scope` 已回滚，故另开会话登记终结状态。
        logger.warning("记忆写入的载荷不合法，转 dead：pending_id=%s cause=%s", pending_id, type(exc).__name__)
        async with session_scope(get_settings()) as session:
            try:
                await mark_dead(session, pending_id=pending_id, error=f"{type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001 —— 登记失败不能掩盖原始错误
                logger.exception("登记 dead 失败：pending_id=%s", pending_id)
        raise
    except Exception as exc:
        # 其它一切按可重试处理——宁可多重试几次，也不要把可能瞬时的失败判成永久 dead。
        # 到上限会自动转 dead（第 6 节）。
        #
        # ⚠️ 不得在此之上加 `except MemoryModuleError` 收口（2026-09-29 评审 S-1 实测）：
        # `MemoryUnavailableError`（图库瞬时不可用，应可重试）是
        # `MemoryModuleError` 的子类。若用基类收口，图库一次瞬时故障就会走「载荷不合法」
        # 那条路被永久判死。因此这里只放两个精确分支：
        # `MemoryDataError`（不可重试）→ 前面的 `dead` 分支；
        # 其余（含 `MemoryUnavailableError`）→ 落到本分支当可重试。
        # 不需要显式的 `except MemoryUnavailableError` 分支：它是冗余的
        # （删掉后 3 条分档用例仍全绿；CORE-09）。
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

    登记本身失败不能掩盖原始错误：调用方紧接着会重新抛出 `exc`，这里只记日志。
    错误摘要只写类型名与消息，不复述连接串或凭据（AGENTS.md 安全条款）。

    `dead` 必须发专属告警（第 6 节「转 `dead` 并告警」、第 8 节「`dead` 数量
    必须告警」）。2026-09-29 评审 C-5 实测发现：此前这里只打可重试失败的 warning，
    连打 5 条一模一样、`dead` 专属告警 0 条——重试耗尽这件事在日志里看不出来。
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


# ---------------------------------------------------------------------------
# 兜底扫描（写入路径第 4.1 节）
# ---------------------------------------------------------------------------

#: 扫描周期（第 10 节：5 分钟）。
SWEEP_INTERVAL_SECONDS = 300

#: 常驻扫描任务句柄；`None` 表示未启动。
_sweep_task: asyncio.Task[None] | None = None


async def sweep_once(session: AsyncSession | None = None, *, now: datetime | None = None) -> int:
    """跑一轮兜底扫描：回收过期租约 + 按 kind 重投没人处理的记录。返回重投条数。

    两件事的顺序有讲究：先回收租约、再重投。回收把「领取后崩溃」的记录放回
    `pending`，紧接着的查询就能把它们一并重投——否则它们要等下一周期（5 分钟）。

    候选集按 `CONSUMED_KINDS` 过滤（写入路径第 4 节第 3 条）：没有消费者的 kind
    重投也没人接，而且它们会一直停在 `pending`、按 `created_at` 排在最前，于是每轮
    占满条数预算，把该重投的记忆记录挤出候选集。消费者接上后无需改这里——
    把 kind 加进分派表，它自动重新进入候选集。

    Args:
        session: 关系库会话；省略则自行开一个（周期任务走这条）。
        now: 参照时间，显式可传以便测试租约过期与退避到期的确定性
            （与 `reclaim_expired_leases` / `find_undelivered` 的同一约定）。

    Returns:
        本轮重投的记录条数。

    失败语义：本函数不吞异常（调用方 `_sweep_forever` 负责隔离）。
    吞掉会让「扫描一直失败」变成静默——那正是本机制要防的事。
    """
    if session is None:
        async with session_scope(get_settings()) as opened:
            return await sweep_once(opened, now=now)
    reference = now if now is not None else datetime.now(timezone.utc)
    reclaimed = await reclaim_expired_leases(session, now=reference)
    if reclaimed:
        logger.info("兜底扫描：回收 %d 条过期租约", len(reclaimed))
    undelivered = await find_undelivered(session, now=reference, kinds=CONSUMED_KINDS)
    for pending_id, kind in undelivered:
        await dispatch_pending_write(str(pending_id), kind)
    if undelivered:
        logger.info("兜底扫描：重投 %d 条待处理记录", len(undelivered))
    return len(undelivered)


async def _sweep_forever() -> None:
    """周期跑扫描，直到被取消。

    单轮失败不得终止循环：一次数据库抖动就让扫描永久停止，等于把「丢的任务可被
    检测」这条兼底控制静默关掉。因此每轮各自捕获异常，只记日志并继续。

    兜底扫描的失败语义相反：单轮失败不得终止循环（只记日志、下一轮继续）——
    一次数据库抖动就让扫描永久停止，等于把「丢的任务可被检测」这条兼底控制静默关掉。
    """
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 单轮失败继续下一轮，绝不静默停止扫描
            logger.exception("兜底扫描本轮失败，%d 秒后重试", SWEEP_INTERVAL_SECONDS)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start_sweep(_state: object) -> None:
    """Worker 启动时拉起常驻扫描任务。

    为什么跑在 Worker 进程内（2026-09-30 裁决，见第 4.1 节）：一期是单个 worker
    服务，独立 `taskiq scheduler` 的扩容与隔离收益为零，而它会把部署单元从 8 个加到 9 个
    （技术栈设计（docs/技术栈设计.md）第 6 节）、与已确认的定调文档冲突。
    重访条件：worker 要水平扩容到多副本时改独立 scheduler。
    """
    global _sweep_task
    _sweep_task = asyncio.create_task(_sweep_forever())


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _stop_sweep(_state: object) -> None:
    """Worker 停止时收口扫描任务（取消并等它真正结束）。"""
    global _sweep_task
    if _sweep_task is not None:
        _sweep_task.cancel()
        with suppress(asyncio.CancelledError):
            await _sweep_task
        _sweep_task = None
