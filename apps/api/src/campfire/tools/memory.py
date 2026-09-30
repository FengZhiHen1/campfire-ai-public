"""记忆侧产品工具：``write_memory`` / ``read_memory``。

归属（[项目结构设计](../../../../../../docs/项目结构设计.md)第 6 节）：``tools/`` 把
``modules/`` 的能力包装成基座可调用的工具。本模块**只做包装**——读写语义、删除账本、
时间模型都在 `modules/memory`，此处不重复实现，也不直接碰表。

## 契约真源

- [write_memory](../../../../../../docs/技术设计/面/consult/tools/write_memory.md)
- [read_memory](../../../../../../docs/技术设计/面/consult/tools/read_memory.md)

## 删除与纠正**不在这里**（2026-09-30 裁决）

记忆的查看 / 纠正 / 删除由**记忆面的 HTTP 契约**承载，**不是模型可见工具**——与档案侧
`confirm` / `correct` / `delete` 同一分工（见[决策记录](../../../../../../docs/技术设计/decisions/记忆删除走用户确认入口.md)）。
因此本模块**没有** ``delete_memory``；`modules/memory` 的 `delete_episode` /
`correct_episode` 由记忆面调用。

## 依赖白名单

``tools/*`` 允许依赖 ``modules/*``、``core/*``；**禁止 import ``surfaces/*``，禁止绕过
用例服务直接写表**（第 7 节）。因此本模块：写走 `core.pending_write.enqueue`（待处理
记录是真相源），读走 `modules.memory` 的用例函数——**没有一条直接构造 SQL**。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from campfire.agent.tools import ToolContext, ToolFailure, ToolResult
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.jobs import dispatch_pending_write
from campfire.core.pending_write import KIND_MEMORY_EPISODE, enqueue
from campfire.modules.memory.errors import MemoryDataError, MemoryModuleError
from campfire.modules.memory.graph import get_shared_memory_graph
from campfire.modules.memory.identity import AccountId, to_account_id
from campfire.modules.memory.store import read_timeline

logger = logging.getLogger(__name__)

#: 从工具上下文里取账号的键。**分区键由装配处经 `payload` 放入，模型无法指定**——
#: 这是归属裁决（`group_id = account_id`）在工具层的落点：模型不能读/写别人的记忆，
#: 「读别人的记忆」在构造查询前就不成立（见通用记忆第 1 节）。
ACCOUNT_PAYLOAD_KEY = "account_id"

#: 一次回看返回的最大条数。与 `store.TIMELINE_MAX_LIMIT` 同源地表达「服务端有上界」；
#: 这里是**工具契约**层的默认值，超出仍由 `store` 收敛（双保险，不是两份定义）。
DEFAULT_READ_LIMIT = 20

#: `origin` 的词表。**与写入路径第 3 节同源**，此处只做工具层的类型收窄，便于模型看到
#: 合法取值；**真正的判据在 `core.pending_write` 的存储层 CHECK**，越界由它拒绝。
Origin = Literal[
    "user_statement",
    "guardian_observation",
    "third_party_report",
    "document",
    "system_observation",
    "ai_inference",
]


def _account_from(context: ToolContext) -> AccountId | ToolFailure:
    """从上下文取出并校验账号标识。

    `payload` 的形状由产品侧决定（基座不解读），因此这里**显式解析**：拿不到就明确
    失败，而不是猜一个默认账号——那会把记忆写到错误的图里。
    """
    payload = context.payload
    raw: object | None = None
    if isinstance(payload, dict):
        raw = payload.get(ACCOUNT_PAYLOAD_KEY)
    if not isinstance(raw, str) or not raw:
        return ToolFailure(
            code="tool_failed",
            message=f"缺少登录账号（装配处应在 payload 里提供 {ACCOUNT_PAYLOAD_KEY!r}）",
        )
    try:
        return to_account_id(raw)
    except Exception:  # noqa: BLE001 —— 校验失败一律转成可读错误，不复述原始值
        return ToolFailure(code="tool_failed", message="登录账号标识不合法")


class _Source(BaseModel):
    """来源定位：这条内容出自哪一次对话的哪条消息。

    `AC-07` 要求记忆条目带来源；来源无法从其他参数还原，因此必填。
    字段收窄成具体形状（而不是 `dict`）是**严格模式的硬要求**：开放对象会让 SDK 的
    `ensure_strict_json_schema` 在注册期失败（见 `agent/tools/spec.py`）。
    """

    session_id: Annotated[str, Field(min_length=1, description="会话标识")]
    message_seq: Annotated[int | None, Field(default=None, description="消息序号（可选）")] = None


class WriteMemoryArgs(BaseModel):
    """`write_memory` 的参数（契约第 2 节）。"""

    content: Annotated[str, Field(min_length=1, description="要记住的内容：一件值得记住的事")]
    occurred_at: Annotated[str, Field(min_length=1, description="这件事发生的时间，ISO 8601 且带时区")]
    origin: Annotated[Origin, Field(description="这条内容是怎么来的")]
    source: Annotated[_Source, Field(description="来源：会话标识与消息序号")]


class ReadMemoryArgs(BaseModel):
    """`read_memory` 的参数（契约第 2 节）。"""

    since: Annotated[str | None, Field(default=None, description="起始时间（含），ISO 8601")] = None
    until: Annotated[str | None, Field(default=None, description="结束时间（含），ISO 8601")] = None
    query: Annotated[str | None, Field(default=None, description="关键词，对内容做子串匹配")] = None
    limit: Annotated[
        int | None,
        Field(default=None, ge=1, le=DEFAULT_READ_LIMIT, description=f"条数上限，最多 {DEFAULT_READ_LIMIT}"),
    ] = None


async def write_memory(context: ToolContext, args: WriteMemoryArgs) -> ToolResult | ToolFailure:
    """`write_memory` 的实现：把一条记忆**提交**为待处理记录。

    按契约第 4 节，本函数只做两件事，且**与业务数据同一事务**：
    1. 落一条 `pending_write`（真相源）；
    2. 事务提交后**投递** Taskiq 任务（投递失败不影响已提交的记录，由兜底扫描重投）。

    回执只承诺 `submitted`——写入由 Worker 异步完成，**不得**表现为已保存（契约第 3 节）。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    try:
        async with session_scope(get_settings()) as session:
            record = await enqueue(
                session,
                kind=KIND_MEMORY_EPISODE,
                account_id=account_id,
                origin=args.origin,
                payload={"content": args.content, "occurred_at": args.occurred_at},
                source={
                    "session_id": args.source.session_id,
                    "message_seq": args.source.message_seq,
                },
                # 记忆属账号：**不得**带支持对象（存储层 CHECK 与用例层同判）。
                support_object_id=None,
            )
            pending_id = str(record.id)
    except MemoryDataError as exc:
        return ToolFailure(code="tool_failed", message=f"记忆未能提交：{exc}")
    except MemoryModuleError as exc:
        return ToolFailure(code="tool_failed", message=f"记忆未能提交：{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 —— 待处理记录写入失败必须明确失败，不回执 submitted
        # 契约第 5 节：待处理记录写入失败 → 明确失败。异常消息可能带连接串，
        # 因此只回类型名（AGENTS.md 安全条款）。
        return ToolFailure(code="tool_failed", message=f"记忆未能提交（{type(exc).__name__}）")

    # **必须 await**：`kiq()` 返回协程，不 await 等于没有投递（mypy 抓过这个错误）。
    # 投递失败不让本次调用失败——记录已落库，由兜底扫描重投（写入路径第 4.1 节）。
    await dispatch_pending_write(pending_id)

    return ToolResult(
        text=json.dumps({"pending_id": pending_id, "state": "submitted"}, ensure_ascii=False),
    )


async def read_memory(context: ToolContext, args: ReadMemoryArgs) -> ToolResult | ToolFailure:
    """`read_memory` 的实现：时间线回看。

    按契约第 4 节：**只读**、**不返回档案条目**、被删除的记忆不返回（删除过滤在
    `modules.memory.store.read_timeline` 内部完成，调用方无法绕过）。

    返回是**片段原文**，不转译、不摘要、不判失效——「现在该信什么」以档案与本次对话为准。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    since, until = _parse_optional_time(args.since, "since"), _parse_optional_time(args.until, "until")
    for parsed in (since, until):
        if isinstance(parsed, ToolFailure):
            return parsed

    try:
        async with session_scope(get_settings()) as session:
            episodes = await read_timeline(
                session,
                # 进程内共享句柄（`modules/memory/graph.py`）：每次重建会泄漏一整套连接池。
                get_shared_memory_graph(),
                account_id,
                since=since,
                until=until,
                query=args.query,
                limit=args.limit if args.limit is not None else DEFAULT_READ_LIMIT,
            )
    except ValueError as exc:
        # 时间区间非法：契约第 5 节要求明确失败（不静默忽略条件）。
        return ToolFailure(code="tool_invalid_arguments", message=str(exc))
    except MemoryDataError as exc:
        return ToolFailure(code="tool_failed", message=f"记忆读取失败：{exc}")
    except Exception as exc:  # noqa: BLE001 —— 图库不可用必须与「没有记忆」严格区分
        return ToolFailure(
            code="tool_failed",
            message=f"未能读取历史记录（{type(exc).__name__}）——不得当作没有历史",
        )

    return ToolResult(
        text=json.dumps(
            {
                "episodes": [
                    {
                        "occurred_at": episode.occurred_at.isoformat(),
                        "content": episode.content,
                        "source": episode.source,
                        "write_state": episode.write_state,
                    }
                    for episode in episodes
                ]
            },
            ensure_ascii=False,
        ),
    )


def _parse_optional_time(raw: str | None, name: str):  # noqa: ANN202
    """把可选的时间参数解析成带时区的 `datetime`。

    非空但解析失败**明确失败**（契约第 5 节「时间区间非法」），不静默当成没传。
    """

    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return ToolFailure(code="tool_invalid_arguments", message=f"{name} 不是合法的 ISO 8601 时间")
    if value.tzinfo is None:
        # 与 consumer 对 `occurred_at` 的严格立场一致：朴素时间会被解释成不同瞬间，
        # 破坏时间区间比较，因此显式拒绝而不是按本地/UTC 猜。
        return ToolFailure(code="tool_invalid_arguments", message=f"{name} 必须带时区（例如 +08:00 或 Z）")
    return value


__all__ = [
    "ACCOUNT_PAYLOAD_KEY",
    "DEFAULT_READ_LIMIT",
    "ReadMemoryArgs",
    "WriteMemoryArgs",
    "read_memory",
    "write_memory",
]
