"""引用索引的持久化实现：把基座的端口接到 `campfire_citation` 表。

职责：实现 `agent/context/citations.py` 的 `CitationIndex` 端口（写入与按运行读回）。
边界：只做「行 ↔ 记录」的转换与读写；不决定何时写、不构造凭据（那是 `CitationRecorder`）。
参考：docs/技术设计/technical-details/通用基座.md 第 4 节。

为什么这个实现落在 `surfaces/` 而不是 `core/db`（表在那里）：

端口与记录类型（`CitationIndex` / `CitationRecord`）属基座 `agent/context`，而依赖白名单
（docs/项目结构设计.md 第 7 节）规定 `core/*` 只能依赖 `core/*`——`core` 不得 import
`agent`，因此表的声明放 `core/db/citations.py`（只声明列、不 import 记录类型），
「行 ↔ 记录」的映射放这里（`surfaces` 允许同时依赖 `agent` 与 `core`）。
先例：`core/db/sdk_session.py` 声明 SDK 的表，映射由读它的模块做。

为什么需要这个实现（此前全仓只有协议与测试替身）：

`AgentRunner` 构造时必须拿到一个 `CitationIndex`，否则整个咨询链无法装配——生产路径
缺了它，发消息端点会稳定回 503。第 4 节的不变量「没有索引记录的注入消息不得成为
可引用依据」要求写入必然落库：`CitationRecorder` 先调 `add` 再发凭据，所以 `add`
失败必须抛异常（不得降级成「无引用」继续运行，否则使用者会看到一条无法回指的依据）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from typing import TypeVar

from sqlalchemy import Executable, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from campfire.agent.context.citations import CitationRecord
from campfire.core.config import Settings
from campfire.core.db import session_scope
from campfire.core.db.citations import (
    CITATION_TABLE_NAME,
    MAX_CITATION_ID_LENGTH,
    MAX_RUN_ID_LENGTH,
    MAX_SOURCE_LENGTH,
    Citation,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class CitationPersistenceError(Exception):
    """引用索引写入或读回失败（含超时）。

    刻意不继承 `agent/context/errors.py` 的 `ContextError`：那是「引用记录不合法」
    这一族的形状问题，而本错误是持久化失败——`CitationRecorder` 原样放行它
    （见该模块 `record` 的 Raises），基座据异常归类把本次运行标成 `injection_failed`。
    把两者混成一个基类会让「参数写错了」与「库连不上」在排查时不可区分。
    """


class SqlCitationIndex:
    """把引用记录写进 `campfire_citation` 并按运行读回。

    两次操作各自 `session_scope`（一事务一次），不跨调用持有会话：注入渲染在运行路径上，
    持有长事务会把整个模型调用期间圈进同一事务里。

    超时：端口契约（`agent/context/citations.py` 的 `CitationIndex` docstring）要求
    实现自带超时上界，理由是超时属「结果未知」。本实现同时满足契约给出的两条出路：
    写入按 `citation_id` 幂等（`ON CONFLICT DO NOTHING`），因此超时后重试是安全的
    ——不会产生重复记录。
    """

    def __init__(self, settings: Settings, *, timeout_seconds: float | None = None) -> None:
        """绑定配置。

        `timeout_seconds` 默认取配置项（`citation_timeout_seconds`），显式传入供测试
        用一个很短的上界验证超时路径。
        """
        self._settings = settings
        self._timeout_seconds = settings.citation_timeout_seconds if timeout_seconds is None else timeout_seconds

    # quality-floor: ignore docstring-promise 异常由 _validate 与 _run 抛出并原样传播，函数体只做组装
    async def add(self, record: CitationRecord) -> None:
        """写入一条引用记录（按 `citation_id` 幂等）。

        字段长度超出列宽即拒绝：让一次笔误在这里显式失败，而不是被数据库静默截断
        （截断后凭据与索引行对不上，回指会指向一个不存在的标识）。

        Raises:
            CitationPersistenceError: 字段超宽、写入失败或超时。
        """
        self._validate(record)
        statement = (
            pg_insert(Citation)
            .values(
                citation_id=record.citation_id,
                run_id=record.run_id,
                source=record.source,
                reference=record.reference,
                recorded_at=record.recorded_at,
                summary=record.summary,
            )
            # 幂等键即主键：同一凭据重复写入被吸收，不报错也不产生第二行。
            # 这正对应端口契约「要么按 citation_id 幂等，要么超时后按它核实」的第一条。
            .on_conflict_do_nothing(index_elements=["citation_id"])
        )
        await self._run("写入", self._execute_add(statement), detail=record.citation_id)

    # quality-floor: ignore docstring-promise 异常由 _run 抛出并原样传播，函数体只做转发
    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        """按运行读回引用记录，顺序为写入顺序（按自增序号）。

        Raises:
            CitationPersistenceError: 读回失败或超时。
        """
        return await self._run("读回", self._execute_list(run_id), detail=run_id)

    # --- 内部实现 ---------------------------------------------------------

    async def _execute_add(self, statement: Executable) -> None:
        async with session_scope(self._settings) as session:
            await session.execute(statement)

    async def _execute_list(self, run_id: str) -> list[CitationRecord]:
        statement = select(Citation).where(Citation.run_id == run_id).order_by(Citation.seq)
        async with session_scope(self._settings) as session:
            rows = (await session.execute(statement)).scalars().all()
        # 在会话内把行转成记录：`expire_on_commit=False` 让提交后仍可读属性，但显式
        # 在此转换可以避免调用方在事务边界外触碰 ORM 对象。
        return [self._to_record(row) for row in rows]

    async def _run(self, action: str, operation: Awaitable[_T], *, detail: str) -> _T:
        """给一次库操作套上超时上界，并把底层异常转成领域错误。

        为什么在这里统一包一层而不是分散两处：端口契约的超时要求对两个方法都成立，
        两处各写一份 `wait_for` 必然漂移（其中一处漏了，那个方法就没有上界）。

        `detail` 只用于日志，不进异常文案：它是引用标识与运行标识，属业务值，
        而异常文案会被端点上层的 `injection_failed` 事件带上（不必扩大暴露面）。
        """
        try:
            return await asyncio.wait_for(operation, timeout=self._timeout_seconds)
        except TimeoutError as exc:
            # `asyncio.wait_for` 超时抛的是内建 `TimeoutError`（3.11+ 与
            # `asyncio.TimeoutError` 合并为同一个类），故直接捕获内建类型。
            logger.warning("引用索引%s超时：%s", action, detail)
            raise CitationPersistenceError(f"引用索引{action}超时（上界 {self._timeout_seconds} 秒）") from exc
        except CitationPersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 驱动异常一律转成领域错误并只带类型名
            logger.warning("引用索引%s失败（%s）：%s", action, type(exc).__name__, detail)
            raise CitationPersistenceError(f"引用索引{action}失败（{type(exc).__name__}）") from exc

    def _validate(self, record: CitationRecord) -> None:
        """按列宽校验字段。

        只校验长度，不校验非空：`CitationRecorder` 已在构造记录前校验来源与回指非空
        （`CitationError`），重复校验会让「谁负责」变模糊。长度的所有者在本层——
        列宽是存储事实，只有这里知道。
        """
        checks = (
            ("citation_id", record.citation_id, MAX_CITATION_ID_LENGTH),
            ("run_id", record.run_id, MAX_RUN_ID_LENGTH),
            ("source", record.source, MAX_SOURCE_LENGTH),
        )
        for name, value, limit in checks:
            if len(value) > limit:
                raise CitationPersistenceError(f"引用索引字段超宽：{name} 超过 {limit} 字符（{CITATION_TABLE_NAME}）")

    def _to_record(self, row: Citation) -> CitationRecord:
        """行 → 记录。列与字段的对应关系只此一处（读回路径唯一）。"""
        return CitationRecord(
            citation_id=row.citation_id,
            run_id=row.run_id,
            source=row.source,
            reference=row.reference,
            recorded_at=row.recorded_at,
            summary=row.summary,
        )


__all__ = ["CitationPersistenceError", "SqlCitationIndex"]
