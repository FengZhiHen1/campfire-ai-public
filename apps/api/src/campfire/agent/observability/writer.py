"""运行记录的写入端口与「顺带记录」的事件转发。

写入实现不在基座内：`agent/*` 只允许依赖 `core/config`（docs/项目结构设计.md
第 7 节），而运行记录要落在我们自己的表里、表由 Alembic 迁移创建（技术栈设计第 1 节记着
「迁移命令仍缺失」）。因此基座只声明端口，实现随 `core/db` 与迁移一起落地。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from campfire.agent.runtime import RunEvent

from .records import RunRecord, RunRecorder

logger = logging.getLogger("campfire.agent.observability")

_FLUSH_TIMEOUT_SECONDS = 5.0
"""取消后给「写记录」收尾的有界等待。取值只需覆盖一次本地数据库写入，不需要容忍长时间阻塞——
记录丢一条比把使用者的请求挂住更可接受，但丢的时候必须留日志。"""


@runtime_checkable
class RunTraceWriter(Protocol):
    """运行记录的持久化端口。

    实现必须让写入失败抛出异常：调用方要能区分「记下了」与「没记下」。基座不会把
    未写入的记录当作已写入（技术栈设计第 5 节第 2 条）。
    """

    async def write(self, record: RunRecord) -> None:
        """写入一条运行记录。"""
        ...


async def record_stream(
    events: AsyncIterator[RunEvent],
    *,
    writer: RunTraceWriter,
    recorder: RunRecorder | None = None,
) -> AsyncIterator[RunEvent]:
    """转发事件，并在流结束后写入一条运行记录。

    事件原样透传（顺序、内容都不动），记录是旁路：写失败只记日志并继续，
    因为一次已经成功的对话不该因为观测写不进去而变成失败。

    取消：调用方取消自己的任务时，本生成器会收到 `CancelledError`；它会先把
    `recorder.mark_cancelled()` 落上（记录里因此能区分「被取消」与「没跑完」），
    再把取消继续抛出——取消优先于一切（基座第 9 节）。写记录过程中被取消也一样：
    记录不会被静默丢掉，写入会有界收尾并留下日志。

    使用方式（面一侧）：

    代码块（python）：
    async for event in record_stream(runner.run(request), writer=writer):
        yield sse(event)          # 转发给使用者
    # 走到这里（流耗尽）记录已写出或已记录写失败

    ⚠️ 提前退出必须显式关闭：`break` / 提前 `return` / 把生成器交给 GC，都不会立刻
    产生收尾——写入发生在生成器被关闭或耗尽的那一刻，而 GC 的时机不确定。要确保记录及时落盘，
    用 `await stream.aclose()`。

    Raises:
        asyncio.CancelledError: 消费者取消时先落上 `mark_cancelled()` 再原样抛出。
        Exception: 上游事件流自身的异常原样抛出（本函数不吞运行失败）。
    """

    active = recorder or RunRecorder()
    try:
        async for event in events:
            active.apply(event)
            yield event
    except BaseException as exc:  # noqa: BLE001 —— 取消与失败都要先把状态记上再抛
        if _is_cancellation(exc):
            active.mark_cancelled()
        raise
    finally:
        await _write_quietly(writer, active.finish())


def _is_cancellation(error: BaseException) -> bool:
    """判断是否是取消。

    `CancelledError` 在 3.8+ 继承 `BaseException`，与普通失败不同类。
    """
    return isinstance(error, asyncio.CancelledError)


async def _write_quietly(writer: RunTraceWriter, record: RunRecord) -> None:
    """写记录；失败与取消都只记日志。

    取消期间的写入不能被静默丢掉：实测第一版在「写记录进行中被取消」时记录丢失、且没有
    任何日志——而技术栈设计第 5 节第 2 条要求「没写进去」不得被当作「写进去了」。
    做法是把写入放进独立任务、用 `shield` 等它；若等待期间收到取消，则先把取消请求挂起
    （`uncancel`）、有界等写入收尾，再把取消继续抛出去（对外行为不变）。

    Raises:
        asyncio.CancelledError: 调用方取消时原样抛出（收尾之后）。
    """
    task = asyncio.ensure_future(_attempt_write(writer, record))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await _flush_after_cancellation(task, record)
        raise


async def _attempt_write(writer: RunTraceWriter, record: RunRecord) -> None:
    """真正写一次；任何形态的失败都只记日志，不改变运行结果。

    捕获 `BaseException`：`writer.write` 自身抛出 `CancelledError` 时（实测确实能构造），
    第一版会把它当成「取消」抛给调用方——一次完全成功的运行因此变成 `CancelledError`，
    且没有任何写失败的日志。
    """
    _warn_if_run_identity_is_missing(record)
    try:
        await writer.write(record)
    except Exception as exc:  # noqa: BLE001 —— 观测失败不得改变运行结果
        _log_write_failure(record, type(exc).__name__, "失败")
    except BaseException as exc:  # noqa: BLE001 —— 含 CancelledError 形态的写失败
        _log_write_failure(record, type(exc).__name__, "被中断")


def _warn_if_run_identity_is_missing(record: RunRecord) -> None:
    """记录里没有运行标识时显式告警——这是观测缺口，不是可以静默接受的常态。

    来路：运行编排在 `run_started` 之前就会以 `run_failed` 结束（会话读取失败、
    注入渲染/准备失败，见 `runtime/runner`）。那类运行的事件流里没有 `run_started`，
    因而记录派生不出 `run_id` / `session_id`，落库后无法回答「这是谁的运行失败了」。

    为什么只告警而不在这里补标识：运行标识不在本层可知（记录只从事件派生，见
    :mod:`campfire.agent.observability.records` 的模块说明）。填补它要么让失败路径也发
    `run_started`，要么给 `run_failed` 加运行标识字段——两者都改 §7 的对外事件形状，
    属需要先确认影响范围的契约变更，因此这里只保证缺口不被静默吞掉。
    """
    if record.run_id is None:
        logger.warning(
            "运行记录缺少运行标识（run_started 未发出）：outcome=%s failure=%s——该记录无法回指到具体运行",
            record.outcome,
            record.failure_code,
        )


async def _flush_after_cancellation(task: "asyncio.Task[None]", record: RunRecord) -> None:
    """取消落在写入过程中：有界地把写入收尾，并如实记录结果。

    必须先 `uncancel()`：任务已收到取消请求时，之后每个 await 都会立刻再抛取消，写入永远
    收不了尾。挂起请求之后用有界等待，超时就如实记「未能收尾」——不假装写成功。
    """
    current = asyncio.current_task()
    if current is not None:
        current.uncancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_FLUSH_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.CancelledError):
        logger.warning("运行记录写入未能在取消后收尾 run=%s outcome=%s", record.run_id, record.outcome)
    except Exception as exc:  # noqa: BLE001 —— 写入失败已在 _attempt_write 里记过
        logger.warning("运行记录写入异常 run=%s error=%s", record.run_id, type(exc).__name__)


def _log_write_failure(record: RunRecord, error_name: str, phase: str) -> None:
    """记一条写失败日志。

    只记异常类型名：写入异常的消息可能带连接串（AGENTS.md 安全条款）。
    """
    logger.warning(
        "运行记录写入%s run=%s outcome=%s error=%s",
        phase,
        record.run_id,
        record.outcome,
        error_name,
    )
