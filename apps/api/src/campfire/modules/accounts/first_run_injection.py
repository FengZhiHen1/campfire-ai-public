"""会话首轮注入的结算标记：读与写 `campfire_session.first_run_injected`。

职责：回答「这个会话的那一次程序注入结算了没有」，以及把它标记为已结算。
边界：不决定注入什么（归面层）、不判定引导状态（归 `onboarding`）、不查账号归属
（归 `sessions.require_session_owner`——本模块的两个入口都不看账号）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.1 节；编排器 T07b 裁决 9。

为什么单独一个模块而不是写进会话仓储：两者共享同一张表，但回答的问题不同。
`sessions.py` 与 `session_repository.py` 的职责陈述都是「会话归属的读写与列表」，
而本模块是「一次性注入的记账」。放进去会让那两份边界陈述当场失效，而边界陈述是
后续维护者判断该往哪加代码的唯一依据。
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.accounts.errors import SessionNotFoundError
from campfire.modules.accounts.models import CampfireSession
from campfire.modules.accounts.session_repository import validate_session_id


async def read_first_run_injected(session: AsyncSession, *, session_id: str) -> bool:
    """读该会话的注入结算标记。

    行不存在时抛 :class:`SessionNotFoundError`（而不是返回 `True` 或 `False`）：
    「没有这一行」与「这一行说未结算」是两个不同的事实，而调用方对前者的正确处理是
    404（越权与不存在同一条文案）。返回值兜底成 `True` 会让一个不存在的会话安静地
    跳过引导注入，兜底成 `False` 会让它的每一次运行都注入——两种猜测都在掩盖错误。

    Args:
        session: 关系库会话（只读，不提交）。
        session_id: 会话标识（来自 URL 路径）。

    Returns:
        已结算为 `True`；未结算（含迁移前的存量行）为 `False`。

    Raises:
        SessionQueryError: 会话标识形状不合法（非字符串、空白或超宽）。
        SessionNotFoundError: 该会话没有归属行。
    """
    normalized = validate_session_id(session_id)
    row = (
        await session.execute(
            select(CampfireSession.first_run_injected).where(CampfireSession.session_id == normalized)
        )
    ).first()
    if row is None:
        raise SessionNotFoundError()
    return bool(row[0])


async def mark_first_run_injected(session: AsyncSession, *, session_id: str) -> None:
    """把该会话的注入结算标记置为真（幂等）。

    为什么是幂等的 UPDATE 而不是「先读后写」：读一次再写一次会在两个并发请求之间
    留出窗口，而两个请求都判到「未结算」时只有一个能真的起运行（会话互斥），
    写法上的竞态只会让第二个偷偷把标记又写一遍——同一个值写两次不出错，但它证明不了
    任何事。调用方要的语义就是「置为真」，一次条件更新足够。

    调用时机（由面层保证，本模块不校验）：在运行已经成功起步之后。起步失败时
    这份标记不该被消耗——这个会话还没有真的做过注入，而标记一旦落下，
    该会话就再也拿不到引导（技能设计第 4 节：误注入的代价是重复一段可跳过的引导，
    漏注入的代价是使用者没有任何入口回到引导；两者不对称）。

    Args:
        session: 关系库会话（调用方负责提交）。
        session_id: 会话标识。

    Raises:
        SessionQueryError: 会话标识形状不合法。
        SessionNotFoundError: 该会话没有归属行——没有行就没有可结算的会话。
    """
    normalized = validate_session_id(session_id)
    result = await session.execute(
        update(CampfireSession).where(CampfireSession.session_id == normalized).values(first_run_injected=True)
    )
    # `rowcount` 只在 `CursorResult` 上声明，而 `AsyncSession.execute` 的静态类型是 `Result`
    # （SQLAlchemy 存根缺口，全仓同一处置：`memory/purge.py`、`core/auth/deletion.py` 等）。
    # DML 实际返回的正是 `CursorResult`，故显式取属性；缺失时按 0 行处理（fail-closed，
    # 与「这个会话没有归属行」同一结论）。
    rowcount = int(getattr(result, "rowcount", 0) or 0)
    if rowcount == 0:
        raise SessionNotFoundError()


__all__ = [
    "mark_first_run_injected",
    "read_first_run_injected",
]
