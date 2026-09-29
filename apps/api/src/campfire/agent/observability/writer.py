"""运行记录的写入端口与「顺带记录」的事件转发。

写入实现**不在基座内**：``agent/*`` 只允许依赖 ``core/config``（docs/项目结构设计.md
第 7 节），而运行记录要落在我们自己的表里、表由 Alembic 迁移创建（技术栈设计第 1 节记着
「迁移命令仍缺失」）。因此基座只声明端口，实现随 ``core/db`` 与迁移一起落地。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from campfire.agent.runtime import RunEvent

from .records import RunRecord, RunRecorder

logger = logging.getLogger("campfire.agent.observability")


@runtime_checkable
class RunTraceWriter(Protocol):
    """运行记录的持久化端口。

    实现必须让写入失败**抛出异常**：调用方要能区分「记下了」与「没记下」。基座不会把
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

    事件原样透传（顺序、内容都不动），记录是**旁路**：写失败只记日志并继续，
    因为一次已经成功的对话不该因为观测写不进去而变成失败。

    **取消**：调用方取消自己的任务时，本生成器会收到 ``CancelledError``；它会先把
    ``recorder.mark_cancelled()`` 落上（记录里因此能区分「被取消」与「没跑完」），
    再把取消继续抛出——取消优先于一切（基座第 9 节）。

    使用方式（面一侧）：

    ```python
    async for event in record_stream(runner.run(request), writer=writer):
        yield sse(event)          # 转发给使用者
    # 到这里记录已写好（或已记录写失败）
    ```

    Raises:
        asyncio.CancelledError: 消费者取消时先落上 ``mark_cancelled()`` 再原样抛出。
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

    ``CancelledError`` 在 3.8+ 继承 ``BaseException``，与普通失败不同类。
    """
    import asyncio

    return isinstance(error, asyncio.CancelledError)


async def _write_quietly(writer: RunTraceWriter, record: RunRecord) -> None:
    """写记录；失败只记日志。

    只记异常**类型名**：写入异常的消息可能带连接串（AGENTS.md 安全条款）。
    """
    try:
        await writer.write(record)
    except Exception as exc:  # noqa: BLE001 —— 观测失败不得改变运行结果
        logger.warning(
            "运行记录写入失败 run=%s outcome=%s error=%s",
            record.run_id,
            record.outcome,
            type(exc).__name__,
        )
