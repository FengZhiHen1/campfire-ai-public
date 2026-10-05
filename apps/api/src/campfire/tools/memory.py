"""记忆侧产品工具：`write_memory` / `read_memory`。

职责：把 `modules/memory` 的读写用例包装成基座可调用的 `write_memory` / `read_memory` 工具。
边界：只做包装——读写语义、删除账本、时间模型都在 `modules/memory`，此处不重复实现，
也不直接碰表；禁止 import `surfaces/*`。
参考：docs/技术设计/面/consult/tools/write_memory.md、read_memory.md；
docs/项目结构设计.md 第 6、7 节；删除与纠正的归属见下方说明。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

#: 从工具上下文里取账号的键。分区键由装配处经 `payload` 放入，模型无法指定——
#: 这是归属裁决（`group_id = account_id`）在工具层的落点：模型不能读/写别人的记忆，
#: 「读别人的记忆」在构造查询前就不成立（见通用记忆第 1 节）。
ACCOUNT_PAYLOAD_KEY = "account_id"

#: 一次回看返回的最大条数。与 `store.TIMELINE_MAX_LIMIT` 同源地表达「服务端有上界」；
#: 这里是工具契约层的默认值，超出仍由 `store` 收敛（双保险，不是两份定义）。
DEFAULT_READ_LIMIT = 20

#: `origin` 的词表。与写入路径第 3 节同源，此处只做工具层的类型收窄，便于模型看到
#: 合法取值；真正的判据在 `core.pending_write` 的存储层 CHECK，越界由它拒绝。
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

    `payload` 的形状由产品侧决定（基座不解读），因此这里显式解析：拿不到就明确
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

    `AC-07` 要求记忆条目带来源；来源无法从其他参数还原，因此这个对象必填。
    字段收窄成具体形状（而不是 `dict`）是严格模式的硬要求：开放对象会让 SDK 的
    `ensure_strict_json_schema` 在注册期失败（见 `agent/tools/spec.py`）。

    **刻意不含 `session_id`**（2026-10-06 修正）：会话标识由服务端从
    `ToolContext.session_id` 填，不接受模型传入——与 `ask_user` 的 `batch_id` 同一原则
    （`runtime/ask_user_tool.py:52-58`「不信任模型传标识」）。原因是模型**不知道**
    当前会话：实测（T24 §6-⑦）它传了 `"current-session"`，而真实会话是
    `4993067c8ae34f3db0feb8e9031b44b0`，它自己的 reasoning 里明写
    "Need session_id. I don't have one; I'll use a neutral placeholder."。
    消费侧（`modules/memory/consumer.py:190-197`）要求 `source.session_id` 存在，
    它信任的是工具层写进去的值——因此问题只能在工具层堵掉：**通道开着就会被使用**。

    `extra="forbid"`：模型若仍按旧 schema 传 `session_id`，解析期就拒（错误码
    `tool_invalid_arguments`），而不是被静默丢掉——静默丢会让「模型以为自己指明了一条
    来源」这件事在任何地方都查不到，而显式拒绝会让它在下一轮改对。
    """

    model_config = ConfigDict(extra="forbid")

    message_seq: Annotated[int | None, Field(default=None, description="消息序号（可选）")] = None


class WriteMemoryArgs(BaseModel):
    """`write_memory` 的参数（契约第 2 节）。

    两个字段是**可选**的，缺省由服务端给（2026-10-06 修正，同一个根因的两个表现）：

    `occurred_at` 缺省时取工具调用时刻的真实时间。原设计让模型必填，而**模型没有时钟**
    ——实测它传了 `2025-06-10`（真实时间 `2026-10-05`），于是「我刚说的话」在时间线上
    被标成「半年前」。注入当前时间让模型能填对，缺省兜底则保证它不填时也不会有假时间
    （取舍与代价见模块末的说明）。

    `source` 缺省时服务端只填会话标识（`message_seq` 保持为空）。语义取舍：若有别的
    调用方需要表达「这个消息属于哪条来源」，该走新的显式字段，而不是把会话标识交还给
    模型——实测那条通道一旦存在就会被编造值填满。

    时间约束（解析期，不只靠提示词）：必须是带时区的 ISO 8601，且不得晚于现在过多
    （判据只有一份，在 :func:`_occurred_at_problem`）。
    """

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, description="要记住的内容：一件值得记住的事")]
    occurred_at: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "这件事发生的时间，ISO 8601 且带时区。不填时取当前时间——"
                "当前时间在对话上下文里有注入，请优先按上下文里的时间填"
            ),
        ),
    ] = None
    origin: Annotated[Origin, Field(description="这条内容是怎么来的")]
    source: Annotated[_Source, Field(default_factory=_Source, description="来源：消息序号（可选）")]

    @field_validator("occurred_at")
    @classmethod
    def _check_occurred_at(cls, value: str | None) -> str | None:
        """时间越界与缺时区在解析期被拒（`tool_invalid_arguments`，回给模型可改）。

        判据取自 :func:`_occurred_at_problem`（与工具层的兜底同一份定义）：写在参数模型
        上意味着越界载荷根本到不了 handler，`enqueue` 从不被调用——因此不存在
        「时间被悄悄改写后落库」这条路径。

        Raises:
            ValueError: 时间不可解析、缺时区，或晚于现在过多。
        """
        if value is None:
            return None
        problem = _occurred_at_problem(value)
        if problem is not None:
            raise ValueError(problem)
        return value


class ReadMemoryArgs(BaseModel):
    """`read_memory` 的参数（契约第 2 节）。"""

    model_config = ConfigDict(extra="forbid")

    since: Annotated[str | None, Field(default=None, description="起始时间（含），ISO 8601")] = None
    until: Annotated[str | None, Field(default=None, description="结束时间（含），ISO 8601")] = None
    query: Annotated[str | None, Field(default=None, description="关键词，对内容做子串匹配")] = None
    limit: Annotated[
        int | None,
        Field(default=None, ge=1, le=DEFAULT_READ_LIMIT, description=f"条数上限，最多 {DEFAULT_READ_LIMIT}"),
    ] = None


#: 工具层的时钟。与 `agent/context/citations.py` 的 `_utc_now` 同一种做法
#: （模块级函数、可被测试替换）：注入时钟是为了让「缺省取现在」这条路径可判定，
#: 而不是让它依赖测试跑在哪个时刻。
def _utc_now() -> datetime:
    """默认时钟：带时区的当前时间。"""
    return datetime.now(timezone.utc)


#: `occurred_at` 允许的最大未来偏移（秒）。给一点余量而不是「严格不得晚于现在」：
#: 调用方与工具侧可能对同一瞬间取到相差毫秒的时钟读数，严格比较会把一条合法写入
#: 判成非法。超出这个余量只可能是编造（T24 实测模型编出半年前的过去，方向相反，
#: 由消费侧与界面兜底呈现，不在此拒绝——见下方取舍说明）。
OCCURRED_AT_FUTURE_TOLERANCE_SECONDS = 300


def _occurred_at_problem(raw: str) -> str | None:
    """判定一个 `occurred_at` 取值的问题；没问题返回 `None`，否则返回给模型看的说明。

    只有一份定义、两个调用点（参数模型的校验器与工具层的兜底），两边因此不可能分叉。
    返回**说明文本**而不是布尔：回给模型的话要能指出该怎么改（它据此重试）。

    Args:
        raw: 模型给的时间字符串（已确认非空）。

    Returns:
        `None` 表示合法；否则是一句中文说明。
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return "occurred_at 不是合法的 ISO 8601 时间"
    if parsed.tzinfo is None:
        # 与 `read_memory` 的 `_parse_optional_time` 及消费侧同一条立场：朴素时间会被
        # 解释成不同瞬间，污染时间线顺序。
        return "occurred_at 必须带时区（例如 +08:00 或 Z）"
    if parsed > _utc_now() + timedelta(seconds=OCCURRED_AT_FUTURE_TOLERANCE_SECONDS):
        return (
            "occurred_at 晚于现在：这件事还没有发生。请用这件事真实发生的时间；不确定就省略该字段，服务端会取当前时间。"
        )
    return None


def _resolve_occurred_at(raw: str | None) -> str | ToolFailure:
    """定下这条记忆的发生时间：模型给了就用（已校验），没给取当前时间。

    返回 ISO 8601 字符串（消费侧 `_parse_occurred_at` 要求带时区）。

    参数模型上已有同一个校验器，因此这里的 `ToolFailure` 分支在实践中不可达——留着它
    不是冗余：`WriteMemoryArgs` 可能被别处用 `model_construct` 绕开校验构造出来，而
    「绕开校验就直接落一条非法时间进时间线」不是可以接受的失败方向。
    """
    if raw is None:
        return _utc_now().isoformat()
    problem = _occurred_at_problem(raw)
    if problem is not None:
        return ToolFailure(code="tool_invalid_arguments", message=problem)
    return datetime.fromisoformat(raw).isoformat()


async def write_memory(context: ToolContext, args: WriteMemoryArgs) -> ToolResult | ToolFailure:
    """`write_memory` 的实现：把一条记忆提交为待处理记录。

    归属（docs/项目结构设计.md第 6 节）：`tools/` 把
    `modules/` 的能力包装成基座可调用的工具。本模块只做包装——读写语义、删除账本、
    时间模型都在 `modules/memory`，此处不重复实现，也不直接碰表。

    依赖白名单：

    `tools/*` 允许依赖 `modules/*`、`core/*`；禁止 import `surfaces/*`，禁止绕过
    用例服务直接写表（第 7 节）。因此本模块：写走 `core.pending_write.enqueue`（待处理
    记录是真相源），读走 `modules.memory` 的用例函数——没有一条直接构造 SQL。

    契约真源：docs/技术设计/面/consult/tools/write_memory.md

    按契约第 4 节，本函数只做两件事，且与业务数据同一事务：
    1. 落一条 `pending_write`（真相源）；
    2. 事务提交后投递 Taskiq 任务（投递失败不影响已提交的记录，由兜底扫描重投）。

    回执只承诺 `submitted`——写入由 Worker 异步完成，不得表现为已保存（契约第 3 节）。

    ★ 两处服务端兜底（2026-10-06，同一个根因「模型需要一个它没有的事实」）：
    `occurred_at` 缺省取当前时间、`source.session_id` 一律取 `context.session_id`。
    两者的理由与代价见 :func:`_resolve_occurred_at` 与 :class:`_Source`。
    """
    account_id = _account_from(context)
    if isinstance(account_id, ToolFailure):
        return account_id

    occurred_at = _resolve_occurred_at(args.occurred_at)
    if isinstance(occurred_at, ToolFailure):
        return occurred_at

    try:
        async with session_scope(get_settings()) as session:
            record = await enqueue(
                session,
                kind=KIND_MEMORY_EPISODE,
                account_id=account_id,
                origin=args.origin,
                payload={"content": args.content, "occurred_at": occurred_at},
                source={
                    # 会话标识取运行上下文，**不取模型给的**（参数模型里已无该字段）：
                    # 消费侧要求 `source.session_id` 存在且为 str，它信任工具层写的值。
                    "session_id": context.session_id,
                    "message_seq": args.source.message_seq,
                },
                # 记忆属账号：不得带支持对象（存储层 CHECK 与用例层同判）。
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

    # 必须 await：`kiq()` 返回协程，不 await 等于没有投递（mypy 抓过这个错误）。
    # 投递失败不让本次调用失败——记录已落库，由兜底扫描重投（写入路径第 4.1 节）。
    # kind 必传：投给谁由它决定（第 4 节第 3 条），省掉就只能一律投给同一个消费者。
    await dispatch_pending_write(pending_id, KIND_MEMORY_EPISODE)

    return ToolResult(
        text=json.dumps({"pending_id": pending_id, "state": "submitted"}, ensure_ascii=False),
    )


async def read_memory(context: ToolContext, args: ReadMemoryArgs) -> ToolResult | ToolFailure:
    """`read_memory` 的实现：时间线回看。

    契约真源：docs/技术设计/面/consult/tools/read_memory.md

    按契约第 4 节：只读、不返回档案条目、被删除的记忆不返回（删除过滤在
    `modules.memory.store.read_timeline` 内部完成，调用方无法绕过）。

    返回是片段原文，不转译、不摘要、不判失效——「现在该信什么」以档案与本次对话为准。
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
                # 进程内共享句柄（`modules/memory/graph.py`）：
                # 每次重建会泄漏一整套连接池。
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

    非空但解析失败明确失败（契约第 5 节「时间区间非法」），不静默当成没传。
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


# 删除与纠正不在这里（2026-09-30 裁决）：
#
# 记忆的查看 / 纠正 / 删除由记忆面的 HTTP 契约承载，不是模型可见工具——与档案侧
# `confirm` / `correct` / `delete` 同一分工（见决策记录（docs/技术设计/decisions/记忆删除走用户确认入口.md））。
# 因此本模块没有 `delete_memory`；`modules/memory` 的 `delete_episode` /
# `correct_episode` 由记忆面调用。
#
# --- 设计取舍（T27，2026-10-06）：注入当前时间 vs 服务端兜底 ---
#
# 两条都做，各自承担不同的失败方向，因此不是二选一：
#
# ① **注入当前时间**（`agent/runtime/runner.py` 的 `pending` 注入，来源
#    `current-time`）让「当前时间」成为**模型真的能拿到的事实**。代价是每轮多一条
#    注入消息（约几十字符，压缩策略第 8 节允许它作为尾部消息；系统提示仍保持静态）。
#    只做兜底而不注入的代价更大：模型仍要凭空猜「发生时间」，而它猜出来的值会**通过**
#    兜底（兜底只知道「不能是未来」，分不出「昨天」与「半年前」）。实测 T24 就是
#    这个形态——模型编的是**过去**的时间，任何「不得晚于现在」的约束都拦不住它。
#
# ② **服务端兜底**（本模块的 `_resolve_occurred_at`）保证「模型没给」时不会落一个
#    假时间。代价是：若模型给了但给了个错的过去时间，兜底不覆盖它（那会把使用者
#    明确提供的时间也一并抹掉——更正对话框确实允许使用者指定发生时间，见 T24 §5-⑥）。
#    因此边界写清楚：**本包修的是「模型缺事实时编造」，不是「使用者给的时间被改写」**。
#
# 会话标识不做①：模型不需要知道 session_id（它没有要表达这件事的场景），而 `ask_user`
# 的 `batch_id` 先例已经确立「标识由工具侧生成、不进模型输入」。因此那一条只做②。
__all__ = [
    "ACCOUNT_PAYLOAD_KEY",
    "DEFAULT_READ_LIMIT",
    "OCCURRED_AT_FUTURE_TOLERANCE_SECONDS",
    "ReadMemoryArgs",
    "WriteMemoryArgs",
    "read_memory",
    "write_memory",
]
