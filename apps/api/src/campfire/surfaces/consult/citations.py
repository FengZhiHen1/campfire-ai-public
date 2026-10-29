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

本模块的第二件事（2026-10-29，缺陷 DEMO-03 的另一半）：**读回时核对「这条依据现在
还能不能引用」**。`SqlCitationIndex` 只负责 run → 回指的索引写入；呈现侧需要的
可核对性（`status` / `applicable_scope` / `withdrawn`）随会话条目里的注解持久化，
其中 `withdrawn` 必须是**当前**事实而不是写入时的快照——因此
:func:`refresh_citation_freshness` 在这里现查条目表，把历史水合出的 citation part
里的那一项换掉。判据与「点进去看那条来源」的三态端点（`modules/library` 的
`GET /library/items/{id}`）同源——两边都查条目表自己的 `withdrawn` 列，
因此同一时刻对同一条来源给出同一个答案（不共享代码：那条路走 `_find_item_any_library`）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Mapping, Sequence
from typing import TypeGuard, TypeVar, cast

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
from campfire.modules.accounts.session_items import (
    PART_TYPE_CITATION,
    CitationPart,
    CitationRecordPart,
    HydratedMessage,
    MessagePart,
)
from campfire.modules.library.retrieval import LIBRARY_CASE, LIBRARY_KNOWLEDGE, load_items

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
        """行 → 记录。列与字段的对应关系只此一处（读回路径唯一）。

        ★ **可核对性三项在这里恒为 `None`（未知），这是刻意的**（2026-10-29）：
        `status` / `applicable_scope` / `withdrawn` 不住在这张表里，它们随会话条目里
        助手正文分片的 `annotations` 持久化（设计《咨询对话界面》第 5 节：引用载荷是
        消息 content 的一部分，不是外部索引）。本表只做「run → 回指」的索引，
        **不加列、不改 schema**。因此本函数读回的是**索引形状**的记录：谁要展示，
        就该读会话条目（`modules/accounts/session_items.py` 的 `citation_parts`），
        而不是把这里当成载荷真源——后者会把「表里没有」误读成「来源没有状态」。
        """
        return CitationRecord(
            citation_id=row.citation_id,
            run_id=row.run_id,
            source=row.source,
            reference=row.reference,
            recorded_at=row.recorded_at,
            summary=row.summary,
        )


# ---------------------------------------------------------------------------
# 可核对性：读回时按**当前**真源重判「这条依据现在还能不能引用」
# ---------------------------------------------------------------------------
#
# 为什么必须有这一段（设计《资料与案例检索》第 4 节）：
# 「已经产生的引用：历史对话中的引用保留，但呈现时标注『该来源已撤下』，
# **不得再作为当前依据**分发」。而 citation 载荷是**写入时的快照**——写它的那一刻
# 条目必然未撤下（检索在查询时过滤撤下，查得到才会被引用），因此「事后撤下」这件事
# 只能由读回侧现查。设计《对话页》也把这条钉在服务端：「撤下判定来自 citation 载荷
# 刷新，不由前端猜测」。
#
# 判定的失败方向（与第 8 节的失败语义同一取向）：
# - 回指解析不了（形状不是 `<库别>:<标识>`）⇒ 未知（`None`），**不猜**；
# - 条目已不存在（被删）⇒ 未知，**不是**「已撤下」——「找不到」与「已下架」是两件事，
#   把它们混成一个会让界面为一条查不到的来源编造一段撤下说明；
# - 取数失败（库连不上/超时）⇒ 整批未知并留 warning，**不是**「在库」——
#   说「在库」等于给一条没核对过的来源背书。
# 因此本模块**不抛异常**给水合路径：核对不出来的部分保持未知，历史照常呈现。

#: 回指形状：`<库别>:<标识>`。库别是 `tools/library.py` 写入的既定取值域
#: （`knowledge` / `case`），与前端 `CitationPart.tsx` 的 `REFERENCE_NAMESPACE` 同一份。
#: 标识里不允许出现分隔符与空白：那说明这不是本仓写出来的形状，宁可不解析。
REFERENCE_PATTERN = re.compile(r"^(?P<library>[a-z]+):(?P<item_id>[^:/?#\s]+)$")

#: 一次查询里最多放多少个标识（CORE-11 有界性）。单个正文分片最多 200 条注解
#: （`CITATION_ANNOTATION_MAX`），而一条消息可以有多个分片，因此这里按批切。
MAX_REFERENCE_LOOKUP = 200

#: 认识的库别（与 `tools/library.py` 写回指时用的取值域一致）。
#: 不在这里的库别 ⇒ 直接当未知：不拿库名去拼表名。
KNOWN_REFERENCE_LIBRARIES: frozenset[str] = frozenset({LIBRARY_KNOWLEDGE, LIBRARY_CASE})


def parse_citation_reference(reference: str) -> tuple[str, uuid.UUID] | None:
    """把 `<库别>:<标识>` 解析成 `(库别, 条目 UUID)`；解析不了返回 `None`。

    解析不了**不抛异常**：回指是历史数据，可能来自更早的写侧、也可能是伪造条目，
    一条解析不了的引用不该让整段历史失败（它照常呈现，只是「无法核对」）。
    """
    matched = REFERENCE_PATTERN.match(reference)
    if matched is None:
        return None
    library = matched.group("library")
    if library not in KNOWN_REFERENCE_LIBRARIES:
        return None
    try:
        item_uuid = uuid.UUID(matched.group("item_id"))
    except ValueError:
        return None
    return library, item_uuid


async def resolve_citation_freshness(settings: Settings, references: Sequence[str]) -> dict[str, bool]:
    """按当前真源核对一批回指：返回 `{reference: 是否已撤下}`。

    **只返回核对得到的那部分**：字典里没有的键就是「未知」，调用方据此保持 `None`，
    不得把缺键当成 `False`（那会把一条查不到的来源说成仍在库）。

    查询形状：每个库按 :data:`MAX_REFERENCE_LOOKUP` 切批，调用例层的
    `load_items`（按库别取对应条目表，**不过滤撤下**——撤下的条目正是要取回来的）；
    库别由回指前缀决定，不跨库猜：同一个 uuid 在两表里可能同时存在，混查会张冠李戴。

    失败方向：任何取数失败都**整批返回空**并记 warning（= 全部未知），
    不把「库连不上」当成「都还在库」。

    Args:
        settings: 配置（提供连接与超时）。
        references: 引用回指（`<库别>:<标识>`），可重复、可含解析不了的值。

    Returns:
        `{reference: withdrawn}`，仅含核对到的那些回指。
    """
    targets: dict[str, list[tuple[str, uuid.UUID]]] = {}
    for reference in references:
        parsed = parse_citation_reference(reference)
        if parsed is None:
            continue
        library, item_uuid = parsed
        targets.setdefault(library, []).append((reference, item_uuid))
    if not targets:
        return {}

    resolved: dict[str, bool] = {}
    try:
        async with session_scope(settings) as session:
            for library, entries in targets.items():
                for start in range(0, len(entries), MAX_REFERENCE_LOOKUP):
                    chunk = entries[start : start + MAX_REFERENCE_LOOKUP]
                    # ★ 走用例层的 `load_items`（模块边界的白名单：面层不得直连存储层模块，
                    # 见 `tests/test_layer_boundaries.py::test_surfaces_do_not_import_storage_modules`）。
                    # 它按条目表取回整行**且不过滤撤下**——正是这里需要的语义：撤下的条目
                    # 也必须取得到（取不到就会把「已撤下」误判成「不存在」）。
                    # 代价是可能多取几列正文；单个会话的引用条数由注解上界（200/分片）兜住。
                    rows = await load_items(session, [str(item_uuid) for _, item_uuid in chunk], library=library)
                    for reference, item_uuid in chunk:
                        row = rows.get(str(item_uuid))
                        if row is not None:
                            # `KnowledgeItem` 与 `CaseItem` 都有这一列（撤下标记是两库共有字段）。
                            resolved[reference] = bool(row.withdrawn)
    except Exception as exc:  # noqa: BLE001 —— 取数失败一律「未知」，不冒充「在库」
        # 只记异常类型：不回显连接串/凭据（安全条款）。
        logger.warning("引用可核对性核对失败（%s），本批按「未知」呈现", type(exc).__name__)
        return {}
    return resolved


async def refresh_citation_freshness(
    settings: Settings,
    messages: Sequence[HydratedMessage],
) -> list[HydratedMessage]:
    """把水合消息里每条 `citation` part 的 `withdrawn` 换成**当前**真源的结果。

    这是历史水合路径上唯一需要现查库的一步：载荷里的 `status` / `applicable_scope`
    是写入时的快照（不刷新——那是「当时这么说过」的事实），而 `withdrawn` 回答的是
    「现在还能不能作为依据」，因此必须现查。

    只改这一项：返回值里每条消息的 `parts` 顺序、其它 part、以及 citation 的
    其余八个字段逐字不变。没有 `citation` part 的历史**原样返回**（不做任何查询）。

    核对不出来的情形写回 `None`（未知）而不是保留快照里的 `False`：
    快照说「当时在库」，而呈现方要回答的是「现在还能不能引用」，后者核不出来就是未知。

    Args:
        settings: 配置。
        messages: 水合出的消息序列（`modules/accounts/session_items.py` 的 `HydratedMessage`）。

    Returns:
        新的消息列表；输入不被修改（水合结果可能被上层持有）。
    """
    references = _citation_references(messages)
    if not references:
        return list(messages)
    resolved = await resolve_citation_freshness(settings, references)
    return [_refreshed_message(message, resolved) for message in messages]


def _is_citation_part(part: MessagePart) -> TypeGuard[CitationPart]:
    """`part` 是不是引用 part。

    写成 `TypeGuard` 而不是在调用点加断言：判别联合靠 `type` 收窄，而
    `part["type"] == …` 这个写法在静态上收窄不了——取 `part["citation"]` 时
    mypy 会把它当成联合里另外五个成员（它们没有这个键）。收窄规则只此一份，
    同 `modules/accounts/session_items._is_tool_call_part` 的做法。
    """
    return part["type"] == PART_TYPE_CITATION


def _citation_references(messages: Sequence[HydratedMessage]) -> list[str]:
    """收集全部 citation part 的回指（去重，保留出现顺序）。"""
    seen: dict[str, None] = {}
    for message in messages:
        for part in message.get("parts", []):
            if not _is_citation_part(part):
                continue
            reference = part["citation"].get("reference")
            if isinstance(reference, str) and reference:
                seen.setdefault(reference, None)
    return list(seen)


def _refreshed_message(message: HydratedMessage, resolved: Mapping[str, bool]) -> HydratedMessage:
    """重写一条消息里的 citation part（只换 `withdrawn`，其余逐字保留）。"""
    parts = message.get("parts", [])
    new_parts: list[MessagePart] = []
    for part in parts:
        if not _is_citation_part(part):
            new_parts.append(part)
            continue
        payload = dict(cast(CitationRecordPart, part["citation"]))
        reference = payload.get("reference")
        # 核对没覆盖到的回指（解析不了/条目不存在/取数失败）一律未知。
        payload["withdrawn"] = resolved.get(reference) if isinstance(reference, str) else None
        new_parts.append(cast(MessagePart, {"type": PART_TYPE_CITATION, "citation": payload}))
    return HydratedMessage(id=message["id"], role=message["role"], parts=new_parts)


__all__ = [
    "CitationPersistenceError",
    "MAX_REFERENCE_LOOKUP",
    "REFERENCE_PATTERN",
    "SqlCitationIndex",
    "parse_citation_reference",
    "refresh_citation_freshness",
    "resolve_citation_freshness",
]
