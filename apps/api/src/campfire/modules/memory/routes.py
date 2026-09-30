"""记忆面的 HTTP 路由：episode 时间线查看、删除与纠正。

职责：把 `modules/memory` 的两个用例（`store.read_timeline`、`deletion.delete_episode` /
`deletion.correct_episode`）暴露成记忆面契约的 HTTP 形状，并把图库不可用与
「没有记忆」严格区分开。
边界：只做 HTTP 形状、载荷校验与错误码映射——时间模型、账本过滤、分区键都归
      `modules/memory` 的既有用例。两处图库访问都经用例层函数转发
      （`store.episode_exists` 判存在性、纠正时写新片段），本模块不自建查询，
      也不装配 Agent 运行。
参考：docs/技术设计/面/profile/记忆面HTTP契约.md 第 2～6 节；
      docs/技术设计/technical-details/通用记忆.md 第 3、4、7 节；
      docs/技术设计/decisions/记忆删除走用户确认入口.md。

为什么路由放在本模块而不是 `surfaces/`（本包裁决 1）：项目的「面」指产品入口与
Agent 运行装配（docs/项目结构设计.md 第 5 节），而记忆面不装配 skill 与工具池，
它只是本模块用例的 HTTP 皮肤——与认证不建面同构。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supertokens_python.recipe.session import SessionContainer

from campfire.core.auth.supertokens import require_session
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.memory import deletion
from campfire.modules.memory.errors import (
    EpisodeKeyOwnedByAnotherAccountError,
    MemoryConfigurationError,
    MemoryDataError,
    MemoryUnavailableError,
)
from campfire.modules.memory.graph import get_shared_memory_graph
from campfire.modules.memory.identity import (
    AccountId,
    EpisodeUuid,
    PendingId,
    derive_episode_uuid,
    to_account_id,
    to_episode_key,
)
from campfire.modules.memory.ledger import recorded_deletion_reason
from campfire.modules.memory.store import MemoryEpisode, episode_exists, read_timeline, write_episode

router = APIRouter(prefix="/memory", tags=["memory"])

#: 时间线单页条数的默认值与上界（本包裁决 8）。
#:
#: 裁决值：档案与资料库取 50、记忆取 100。理由：记忆是「回看」语义的时间线，
#: 使用者的核对动作需要一次看到较多行（按日期分组呈现），而档案条目与资料条目
#: 是「一条一条读」的形态。默认值 20 与会话列表同档（HTTP/SSE 契约第 3.2 节），
#: 避免同一产品里出现两套分页尺度。
MEMORY_DEFAULT_LIMIT = 20
MEMORY_MAX_LIMIT = 100

#: 可翻页的总窗口（CORE-11）。游标是本面自定的偏移量，而用例层只接 `limit`，
#: 因此本面用「多取 offset+limit+1 行再切片」实现分页；上限取记忆模块自己的
#: 时间线上界（`store.TIMELINE_MAX_LIMIT`），超过它之后 `next_cursor` 为 null。
PAGE_WINDOW_MAX = 200

#: `source_description` 里承载来源会话标识的键名。写入侧由
#: `modules/memory/consumer._source_description` 拼成 `session=<id> message=<seq> …`。
_SESSION_TOKEN = "session="

#: 「episode 不存在或不属于当前账号」的统一文案（契约第 2 节的 404 行）。
#:
#: 越权与不存在必须逐字相同（本项目被机械守卫的不变量）：区分它们等于提供
#: episode 枚举通道。本文件里出现 404 的地方一律引用本常量，不另写文案。
NOT_FOUND_MESSAGE = "该记忆不存在"

#: 账本状态不可信（不变量破坏）时的 503 文案。与图库故障同一状态码：都表示
#: 「现在答不了」，而不得伪装成「标识写错了」——形状校验在入口已经做过。
LEDGER_UNUSABLE_MESSAGE = "记忆存储暂时不可用"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 会话依赖
# ---------------------------------------------------------------------------


async def current_account(session: SessionContainer | None = Depends(require_session())) -> str:
    """从登录态取得当前账号标识，作为本面全部分区键的唯一来源。

    分区键取登录态、不接受调用方传入，且这里取的账号直接就是 `group_id`
    （记忆归属账号，通用记忆第 1 节）——因此"读别人的记忆"在构造查询前就不成立，
    不需要在返回后过滤（契约第 2 节）。

    `require_session()` 固定 `session_required=True` 与 `check_database=True`
    （见 `core/auth/supertokens.require_session`）：撤销即时生效靠后者，漏传不会
    报错只会静默失去撤销能力，因此这一层不得绕过它。

    为什么每个面各有一份同名函数（而不是共用一份）：`modules/*` 之间不得互相
    import（docs/项目结构设计.md 第 7 节的依赖白名单，`test_layer_boundaries`
    机械检查），而这份函数要读的 `require_session` 在 `core/auth`——把共享实现
    放进 `core/*` 是唯一的归处，但那超出了本任务包允许改动的文件范围。
    因此本批三个面各写一份，差异被压到「返回值取哪个字段」这一行。

    Args:
        session: SDK 注入的会话容器；`session_required=True` 时必不为 None。

    Returns:
        账号标识（即身份服务的用户标识，认证与账号第 3 节）。

    Raises:
        RuntimeError: 会话容器缺失。这在 `session_required=True` 下不可达；
            显式失败而不是回落到空账号——空账号不满足分区键判据，会被读成
            「这个账号没有记忆」，把一次装配缺陷伪装成正常空态。
    """
    if session is None:  # pragma: no cover —— session_required=True 时不可达
        raise RuntimeError("require_session 返回了空会话：拒绝按无账号处理请求")
    return session.get_user_id()


# ---------------------------------------------------------------------------
# 错误映射
# ---------------------------------------------------------------------------


def _error(status_code: int, message: str, code: str) -> JSONResponse:
    """构造带机器可读 code 的错误响应（与档案面同一形状）。"""
    return JSONResponse(status_code=status_code, content={"detail": message, "code": code})


def _unavailable(detail: str) -> JSONResponse:
    """图库或记忆存储不可用 → 503。

    与「没有记忆」严格分开是契约第 6 节的硬要求：缺凭据、图库连不上、账本触顶
    都不得被呈现成「空数组」——那会让使用者以为系统没有记住任何事，
    而真相是读不到了。`detail` 只给异常类别，不复述连接串与凭据。
    """
    return _error(503, detail, "memory_unavailable")


async def _episode_presence(account: AccountId, episode_key: EpisodeUuid) -> bool | None:
    """这条 episode 在本账号的时间线里是否存在；判不了时返回 None。

    三值返回是本面「删除与纠正」共用的判据形状，不要压成两值：

    - `True`：图库里有这条已完成的片段；
    - `False`：本账号没有这条片段（不存在，或属于别人）→ 404，文案与「不存在」
      逐字相同（契约第 2 节：区分两者等于提供 episode 枚举通道）；
    - `None`：图库未配置或不可用 → 判不了存在性，既不报 404 也不报 503，
      由调用方按契约第 6 节继续——删除与纠正的「撤下」步骤写的是本库账本，
      与图库是两回事，图库故障不该让撤下失效。

    为什么两处共用一处实现：删除与纠正必须给出逐字相同的 404，而两处各写一遍
    正是「纠正漏了这一步」这个缺陷的成因——同一条判据复制两份就会有一份漂移。

    异常类型是唯一判据（见 `errors.MemoryModuleError`），不靠异常消息文本：
    文案一改就会让「图库不可用」静默变成「不存在」。
    """
    try:
        return await episode_exists(get_shared_memory_graph(), account, episode_key=episode_key)
    except (MemoryConfigurationError, MemoryUnavailableError):
        return None


# ---------------------------------------------------------------------------
# 载荷模型
# ---------------------------------------------------------------------------


class MemoryEpisodePayload(BaseModel):
    """时间线里的一条 episode 原文（契约第 3 节）。

    `episode_key` 是本面必须暴露的标识：`read_memory` 的工具返回刻意不含它
    （模型不需要），而本面没有它就无法「列表 → 指认 → 删除」。两者分开定义
    不是同一份形状的两个视图（契约第 3 节）。
    """

    episode_key: str
    occurred_at: datetime
    content: str
    source_session_id: str


class EpisodeListPayload(BaseModel):
    """时间线响应；已删除与在途记录都不返回（契约第 3 节）。"""

    items: list[MemoryEpisodePayload]
    next_cursor: str | None


class DeleteEpisodePayload(BaseModel):
    """删除响应（契约第 4 节）。

    `newly_deleted` 为假表示此前已删除（幂等命中）；`reason` 如实回报账本里的
    原原因——一条记忆先按 `correction` 撤下、之后又收到删除请求时，账本里仍是
    `correction`。如实回报，避免审计与文案读到与账本不符的信息。
    """

    episode_key: str
    newly_deleted: bool
    reason: str


class CorrectEpisodeRequest(BaseModel):
    """纠正请求（契约第 5 节）：新内容而不是补丁。

    只收这两项：`occurred_at` 是纠正所指的发生时间（新片段的 `valid_at`），
    `content` 是新原文。分区键取登录态，不接受调用方传入（契约第 2 节）。
    """

    occurred_at: str
    content: str


class CorrectEpisodePayload(BaseModel):
    """纠正响应（契约第 5 节 + 本包裁决 3 的中间态形状）。

    三个字段承载两步各自的结果，缺一个调用方就无法判断自己处在哪一步：

    - `superseded`：旧记忆是否已撤下（本库事务，成功即生效）；
    - `new_episode_written`：新记忆是否已写入图库（走模型抽取，可能失败）；
    - `episode_key`：新记忆的标识；未写入时为 `null`（不得编造一个不存在的标识）；
    - `supersedes`：被撤下的旧记忆标识（契约第 5 节原名）。

    为什么必须区分（契约第 5 节）：笼统报成功会让使用者以为纠正生效了，
    笼统报失败会让他重复纠正——而旧记忆此时已经撤下，重复提交只会再产生一条
    新记忆。中间态是「原记录已不再作为依据，但新记录没写成，请重试」。
    """

    superseded: bool
    new_episode_written: bool
    episode_key: str | None
    supersedes: str


# ---------------------------------------------------------------------------
# 形状转换与载荷校验
# ---------------------------------------------------------------------------


def _session_id_from(source_description: str) -> str:
    """从 `source_description` 里取出来源会话标识。

    存储里的来源是一个复合串（`session=<id> message=<seq> pending=<id>`，
    见 `modules/memory/consumer._source_description`），而本面契约的字段是
    `source_session_id`——字段名承诺的是一个标识，因此这里做一次显式解析。

    取不到 `session=` 词元时原样返回整串，不返回空串：空串会被读成
    「这条记忆没有来源」，而 `write_episode` 拒绝写入无来源的记忆——也就是说
    空串在本系统里不可能表示「没有来源」，只会表示「解析失败」，那会把一次
    解析缺陷伪装成缺失的来源。原样返回至少保住了可核对的定位。
    """
    for token in source_description.split():
        if token.startswith(_SESSION_TOKEN):
            value = token[len(_SESSION_TOKEN) :]
            if value:
                return value
    return source_description


def _episode_payload(episode: MemoryEpisode) -> MemoryEpisodePayload:
    """把用例层的片段转成对外形状。"""
    return MemoryEpisodePayload(
        episode_key=episode.episode_uuid,
        occurred_at=episode.occurred_at,
        content=episode.content,
        source_session_id=_session_id_from(episode.source),
    )


def _parse_time(raw: str) -> datetime | None:
    """解析 ISO 8601 时间；非法或缺少时区返回 None 由调用方转 422。

    不接受朴素时间：记忆的时间线要跨机器与跨时区看，没有时区的时间会被解释成
    不同瞬间，而时间顺序正是回看的组织方式（与 `tools/memory` 同一立场）。

    只有「给了但用不了」这一种失败：本函数不拼错误文案——参数名与文案由调用方
    掌握（它才知道这是 `since` 还是 `occurred_at`），因此不接受字段名形参。
    """
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _parse_cursor(cursor: str | None) -> int | None:
    """把游标解析成偏移量；None 表示非法（由调用方转 422）。"""
    if cursor is None:
        return 0
    if not cursor.isdigit():
        return None
    return int(cursor)


def _parse_time_range(
    since: str | None, until: str | None
) -> tuple[datetime | None, datetime | None, JSONResponse | None]:
    """解析并校验时间区间，返回 `(since, until, 错误响应或 None)`。

    抽成一处的原因有两条，都不是风格问题：

    1. `list_episodes` 的校验分支（两个参数各自「给了但解析不了」+ 区间倒置）
       让它逼近复杂度上限；这些分支与「查时间线」是两件事，混在一个函数里
       会掩盖主流程。
    2. 同一条判据（必须带时区、区间不得倒置）将来若被第二个端点需要，
       复制一份必然漂移出一处「少校验了时区」。

    缺时区与无法解析并入同一条错误：两者对调用方是同一件事（这个时间用不了），
    分开报只会多一个分支而不多一条信息。
    """
    parsed_since = None if since is None else _parse_time(since)
    parsed_until = None if until is None else _parse_time(until)
    for raw, parsed, name in ((since, parsed_since, "since"), (until, parsed_until, "until")):
        if raw is not None and parsed is None:
            return None, None, _error(422, f"{name} 不是合法的 ISO 8601 时间（且必须带时区）", "invalid_payload")
    if parsed_since is not None and parsed_until is not None and parsed_since > parsed_until:
        return None, None, _error(422, "时间区间非法：since 晚于 until", "invalid_payload")
    return parsed_since, parsed_until, None


# ---------------------------------------------------------------------------
# 查看（契约第 3 节）
# ---------------------------------------------------------------------------


@router.get("/episodes", response_model=EpisodeListPayload)
async def list_episodes(
    account_id: Annotated[str, Depends(current_account)],
    since: Annotated[str | None, Query(description="起始发生时间（含），ISO 8601 带时区")] = None,
    until: Annotated[str | None, Query(description="结束发生时间（含），ISO 8601 带时区")] = None,
    query: Annotated[str | None, Query(description="关键词，对内容做子串匹配")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MEMORY_MAX_LIMIT)] = MEMORY_DEFAULT_LIMIT,
) -> EpisodeListPayload | JSONResponse:
    """查看记忆时间线（契约第 3 节）。

    返回的是 episode 原文时间线（回看语义）：不转译、不摘要、不判失效；
    派生事实（应急预注入那条路径）不在本面暴露。

    三件事由用例层保证，本函数不重复做：已删除的记忆不返回（账本过滤在
    `read_timeline` 内部完成，调用方无法漏传）、只返回 `pending_write.state = done`
    的片段、分区键取自登录态。

    对外状态码（在函数体内映射，不通过抛异常）：
        422: 时间无法解析、缺时区、区间倒置，或游标不是本面发出的。
        503: 图库不可用、引擎未配置，或删除账本触顶——后者无法完整排除已删内容，
            返回部分结果等于让删除静默失效，因此明确失败。

    未归入上面两类的意外异常原样冒出：把未知缺陷报成「记忆暂时无法读取」
    会掩盖真实的程序错误。
    """
    parsed_since, parsed_until, problem = _parse_time_range(since, until)
    if problem is not None:
        return problem

    offset = _parse_cursor(cursor)
    if offset is None:
        return _error(422, "cursor 不是本面发出的游标", "invalid_payload")

    try:
        account = to_account_id(account_id)
    except MemoryDataError:
        # 登录态给出的账号标识不满足分区键判据：这是环境/身份侧的异常，
        # 不是使用者能修正的载荷问题，因此归 503 而不是 422。
        return _unavailable("记忆分区键不可用")

    window = min(offset + limit + 1, PAGE_WINDOW_MAX)
    try:
        async with session_scope(get_settings()) as session:
            episodes = await read_timeline(
                session,
                get_shared_memory_graph(),
                account,
                since=parsed_since,
                until=parsed_until,
                query=query,
                limit=window,
            )
    except (MemoryConfigurationError, MemoryUnavailableError):
        return _unavailable("记忆图库暂时不可用")
    except MemoryDataError:
        # 账本触顶或图库里的数据不合法：两者都意味着这次读不可信，
        # 不得降级成「没有记忆」。
        return _unavailable("记忆暂时无法读取")

    page = episodes[offset : offset + limit]
    has_more = len(episodes) > offset + limit
    return EpisodeListPayload(
        items=[_episode_payload(episode) for episode in page],
        next_cursor=str(offset + limit) if has_more else None,
    )


# ---------------------------------------------------------------------------
# 删除（契约第 4 节）
# ---------------------------------------------------------------------------


@router.delete("/episodes/{episode_key}", response_model=DeleteEpisodePayload)
async def delete_episode(
    episode_key: str,
    account_id: Annotated[str, Depends(current_account)],
) -> DeleteEpisodePayload | JSONResponse:
    """删除一条记忆（契约第 4 节）。

    语义删除 = 写删除账本，不是图库物理删除：账本过滤是唯一生效点，因此删除
    不会因图库不可用而失败——账本写入是本库事务。图库内残留不判失败。

    两个判据分开判定，顺序不可换（2026-09-30 编排器裁决 2）
    ------------------------------------------------------

    1. 账本判据（先做）：本账号已把这条 key 记入账本 → 幂等命中，200 与
       `newly_deleted: false`。必须先看账本——账本过滤会让已删记忆从时间线里
       消失，只看图库会把「重复删除」误判成「不存在」。
    2. 图库判据：这条 episode 在本账号的时间线里不存在 → 404，文案与「不存在」
       逐字相同（越权与不存在同形，不提供 episode 枚举通道）。
    3. 判不了（图库未配置或不可用）不阻断删除：契约第 6 节要求「图库不可用时
       删除的撤下步骤仍可用」。此时账本照记并返回成功——因为图库故障而让使用者
       的删除请求失败，等于让一次本该生效的删除静默失效。

    幂等：重复删除返回 200 并带 `newly_deleted: false`。二次确认是前端交互，
    服务端不做「猜你不是故意的」。

    标识形状在入口校验（本包裁决 7）：非法形状 → 422，与「episode 不存在」
    （404）分开——形状校验是载荷问题，重试同样的请求不会变好。

    错误码按异常类型分派，不按消息文本（2026-09-30，D-40）
    ------------------------------------------------------

    跨账号守卫在产生判据的地方（`ledger.record_deletion`）抛
    `EpisodeKeyOwnedByAnotherAccountError` → 404；其余 `MemoryDataError` 是账本
    不变量问题 → 503。判据不能用 `str(exc)` 做子串匹配：文案一改就会把跨账号命中
    静默降级成 422「标识形状非法」。

    Raises（对外映射）:
        404: 该 episode 不存在，或不属于当前账号（越权与不存在逐字同文案）。
        422: 标识形状非法。
        503: 本库（账本）不可用或账本状态不可信。
    """
    try:
        key = to_episode_key(episode_key)
    except MemoryDataError:
        return _error(422, "episode 标识形状非法", "invalid_payload")

    try:
        account = to_account_id(account_id)
    except MemoryDataError:
        return _unavailable("记忆分区键不可用")

    try:
        async with session_scope(get_settings()) as session:
            recorded = await recorded_deletion_reason(session, account_id=account, episode_key=key)
            if recorded is not None:
                return DeleteEpisodePayload(episode_key=key, newly_deleted=False, reason=recorded)

            # `None` = 图库判定不了（未配置或不可用）：不报 404，也不报 503，
            # 继续走账本写入——见函数说明第 3 条。
            if await _episode_presence(account, key) is False:
                return _error(404, NOT_FOUND_MESSAGE, "not_found")

            result = await deletion.delete_episode(session, account_id=account, episode_key=key)
    except EpisodeKeyOwnedByAnotherAccountError:
        # 跨账号守卫（`record_deletion`）的兜底：账本判据通过之后，同一 key 仍可能
        # 被别的账号抢先写进账本（`episode_key` 由 uuid5 派生，可跨账号撞车，
        # 见 `record_deletion` 的 Note）。与「不存在」同形处理——判据是异常类型，
        # 不是异常文案（`errors.py` 的纪律：文案一改就会静默降级成 422）。
        return _error(404, NOT_FOUND_MESSAGE, "not_found")
    except MemoryDataError as exc:
        # 其余 `MemoryDataError`（形状非法、原因不在词表、账本状态不一致）落在这里。
        # 形状不可能有问题：本函数开头已把同一个 `key` 校验过，非法标识到不了这里。
        # 因此不再自称「标识形状非法」（那会把排查方向引向载荷），而是如实报存储不可用，
        # 并把真正的 operation/detail 留给日志——响应不复述内部细节。
        logger.error(
            "删除的账本写入失败：operation=%s detail=%s",
            exc.operation,
            exc.detail,
        )
        return _unavailable(LEDGER_UNUSABLE_MESSAGE)
    except MemoryConfigurationError:  # pragma: no cover —— 删除不构造图库，防御性保留
        return _unavailable("记忆图库暂时不可用")
    except MemoryUnavailableError:
        return _unavailable("记忆存储暂时不可用")

    return DeleteEpisodePayload(
        episode_key=result.episode_key,
        newly_deleted=result.newly_deleted,
        reason=result.reason,
    )


# ---------------------------------------------------------------------------
# 纠正（契约第 5 节）
# ---------------------------------------------------------------------------


@router.post("/episodes/{episode_key}/correct", response_model=CorrectEpisodePayload)
async def correct_episode(
    episode_key: str,
    account_id: Annotated[str, Depends(current_account)],
    payload: Annotated[CorrectEpisodeRequest, Body()],
) -> CorrectEpisodePayload | JSONResponse:
    """纠正一条记忆：先撤下旧的，再写新的（契约第 5 节）。

    纠正为什么是「删旧 + 写新」而不是「改」：旧派生边不会因纠正指向更早时间而
    自动失效（通用记忆第 7 节的实测结论），正确性落在账本过滤上——旧 episode
    一进账本，引用它的派生边就不再注入。

    顺序是不可换的：反过来会有一段「新旧同时有效」的窗口。最坏情形是
    「暂时没有这条记忆」，比「旧错误内容继续被当作当前认识」安全。

    两步分属两个事务，因此失败语义必须分述（契约第 5 节）
    ---------------------------------------------------------

    1. 撤下旧记忆：本库事务，要么成功要么回滚。它在自己的事务里先提交，
       然后才尝试第二步——这不是实现便利，而是顺序要求：若两者共用一个事务，
       第二步失败会把撤下一起回滚，于是旧错误内容继续有效（正是纠正要避免的）。
    2. 写新记忆：走图库与模型抽取，可能失败、可重试。失败时不回滚第一步，
       返回 200 与中间态 `{superseded: true, new_episode_written: false}`。

    为什么这里直接调 `store.write_episode` 而不经 `pending_write` 队列
    ---------------------------------------------------------

    队列路径只能回执 `submitted`（`write_memory` 工具契约第 3 节明令不得表现为
    已保存），而本端点必须告诉调用方新记忆是否已写入——两步的中间态正是
    本契约的核心要求。`deletion.correct_episode` 的 docstring 也把「写新记忆」
    明确划给调用方，因此本函数承担这一步。

    代价如实写明：本端点同步等一次模型抽取（受图库与模型超时约束），
    且不产生 `pending_write` 记录，因此没有「重试不重复抽取」的幂等标记
    ——每次请求都是一个新的新片段（新记忆本来就是一具新记录，语义上无需幂等）。
    该取舍登记在交付报告的未决问题节。

    先判「这条 episode 在不在」再撤下（契约第 2 节的 404 行）
    ------------------------------------------------------

    账本的唯一约束是全局的，且账本行没有回收路径：为一条从未存在的 key 记一行
    `correction`，会让该 key 日后成为真实 episode（`identity.derive_episode_uuid`）
    时从诞生起就被账本过滤隐去。判据与删除逐字同源（`_episode_presence`）；
    位置在写账本之前——撤下一旦提交，404 就只能在副作用之后判出来。
    载荷校验（标识形状、时间、内容）仍先于存在性判定：载荷问题重试不会变好，
    而存在性问题换个请求可能就成立。

    图库判不了存在性（`None`）时不阻断纠正：照旧撤下并尝试写新片段，与契约第 6 节
    「删除与纠正的撤下步骤仍可用」一致——图库故障期间让纠正整体失败，等于让本已
    生效于本库的撤下静默失效。代价与删除同笔：图库故障窗口内可能为一条判不了
    存在性的 key 记一行账本，这是三分支里判不了那一支的固有代价。

    Raises（对外映射）:
        404: 该 episode 不存在，或不属于当前账号（越权与不存在逐字同文案）；
             跨账号命中账本守卫时同样 404（按异常类型分派，同删除）。
        422: 标识形状非法、内容为空、时间无法解析或缺时区。
        503: 本库（账本）不可用或账本状态不可信。
    """
    try:
        key = to_episode_key(episode_key)
    except MemoryDataError:
        return _error(422, "episode 标识形状非法", "invalid_payload")

    occurred_at = _parse_time(payload.occurred_at)
    if occurred_at is None:
        return _error(422, "occurred_at 不是合法的 ISO 8601 时间（且必须带时区）", "invalid_payload")
    if not payload.content.strip():
        # 空内容必须显式拒绝：`write_episode` 也会拒（content 为空），但那时
        # 旧记忆已经撤下——在入口拦掉，避免一次注定失败的请求先把旧记忆撤掉。
        return _error(422, "content 不得为空", "invalid_payload")

    try:
        account = to_account_id(account_id)
    except MemoryDataError:
        return _unavailable("记忆分区键不可用")

    # 存在性判据与删除同源（见 `_episode_presence`）：`False` → 404 与「不存在」
    # 逐字同文案；`None`（图库不可用）不阻断撤下。必须早于账本写入——账本行
    # 全局唯一且无回收路径，为一条从未存在的 key 记 `correction` 会永久隐去
    # 该 key 日后可能出现的真实记忆。
    if await _episode_presence(account, key) is False:
        return _error(404, NOT_FOUND_MESSAGE, "not_found")

    # --- 第一步：撤下旧记忆（本库事务，独立提交） ---
    try:
        async with session_scope(get_settings()) as session:
            superseded = await deletion.correct_episode(session, account_id=account, corrected_episode_key=key)
    except EpisodeKeyOwnedByAnotherAccountError:
        # 与删除同一判据（同一段分派，见 `delete_episode` 的说明）。
        return _error(404, NOT_FOUND_MESSAGE, "not_found")
    except MemoryDataError as exc:
        logger.error(
            "纠正撤下旧记忆失败：operation=%s detail=%s",
            exc.operation,
            exc.detail,
        )
        return _unavailable(LEDGER_UNUSABLE_MESSAGE)
    except MemoryConfigurationError:  # pragma: no cover —— 撤下不构造图库，防御性保留
        return _unavailable("记忆图库暂时不可用")

    # --- 第二步：写新记忆（图库 + 模型抽取，失败即中间态） ---
    new_pending_id = PendingId(str(uuid.uuid4()))
    new_episode_key = derive_episode_uuid(new_pending_id)
    try:
        await _write_corrected_episode(
            account=account,
            episode_key=new_episode_key,
            content=payload.content,
            occurred_at=occurred_at,
            supersedes=superseded.episode_key,
        )
    except (MemoryConfigurationError, MemoryUnavailableError, MemoryDataError):
        # 中间态：旧记忆已撤下（已提交），新记忆没写成。
        # 返回 200 而不是 5xx：请求本身没有失败，它部分成功了，而
        # 「部分成功」必须让调用方看见（契约第 5 节明令不得笼统报成功或失败）。
        return JSONResponse(
            status_code=200,
            content=CorrectEpisodePayload(
                superseded=True,
                new_episode_written=False,
                episode_key=None,
                supersedes=superseded.episode_key,
            ).model_dump(mode="json"),
        )

    return JSONResponse(
        status_code=201,
        content=CorrectEpisodePayload(
            superseded=True,
            new_episode_written=True,
            episode_key=new_episode_key,
            supersedes=superseded.episode_key,
        ).model_dump(mode="json"),
    )


# quality-floor: ignore docstring-promise 异常由 get_shared_memory_graph 与 write_episode 抛出并原样传播
async def _write_corrected_episode(
    *,
    account: AccountId,
    episode_key: EpisodeUuid,
    content: str,
    occurred_at: datetime,
    supersedes: str,
) -> None:
    """把一个纠正后的新片段写进图库。

    来源定位写成 `correction_of=<旧标识>`：契约第 5 节的请求体只有
    `occurred_at` 与 `content`——纠正的新内容由使用者在记忆页重新输入，
    它不来自任何一次对话，而 `write_episode` 拒绝没有来源的记忆
    （「没有来源的记忆无法核对」）。`correction_of` 是如实且可核对的定位：
    它指向图库里仍保留的那条旧片段。

    Raises:
        MemoryConfigurationError: 未配置模型凭据（图库装配不出来）。
        MemoryUnavailableError: 图库写入失败。
        MemoryDataError: 内容或来源不合法（本函数已保证非空，防御性保留）。
    """
    graph = get_shared_memory_graph()
    await write_episode(
        graph,
        account,
        episode_key,
        content=content,
        occurred_at=occurred_at,
        source_description=f"correction_of={supersedes}",
    )


__all__ = [
    "MEMORY_DEFAULT_LIMIT",
    "MEMORY_MAX_LIMIT",
    "PAGE_WINDOW_MAX",
    "current_account",
    "router",
]
