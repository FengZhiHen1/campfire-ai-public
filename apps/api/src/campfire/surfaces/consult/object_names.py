"""会话列表的对象名取数：把 profile 的绑定与对象名汇成一张映射。

职责：实现 `modules/accounts/sessions.list_sessions` 要求的 `ObjectNameReader` 回调。
边界：只读映射；不判归属、不做分页、不构造响应。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.2 节；
docs/项目结构设计.md 第 7 节（依赖白名单）。

为什么需要单独一个模块：`list_sessions` 的签名收一个回调（对象名归 `modules/profile`，
而模块之间禁止互相 import），实现必须由装配处提供。这里就是那个实现，
且它是本包唯一一处需要读 profile 数据的地方——集中在一处，profile 侧的取数只有这里要改。

为什么两张表都批量取：对象表经 `list_objects` 一次查询覆盖整页（一个账号的对象数量级
是个位数），绑定表经 `read_session_bindings` 同样一次查询覆盖整页——逐会话取绑定会让
一页 20 条产生 20 次查询。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.profile import list_objects, read_session_bindings


async def read_object_names(
    session: AsyncSession,
    *,
    account_id: str,
    session_ids: Sequence[str],
) -> dict[str, str]:
    """返回「会话标识 → 支持对象名」；没有绑定或名字取不到的会话不在映射里。

    缺行不出现在映射里（而不是落一个空串）：调用方据此把该字段置为 `None`，
    而契约第 3.2 节对缺失字段的处理是「前端不渲染」——空串会让前端渲染一行空白。

    只取该账号自己的对象（`list_objects` 的账号来自登录态）。一个会话的绑定指向
    别的账号的对象在数据层不可能出现（绑定行由本账号的创建路径写入），因此这里
    不做交叉校验——做了也只是重复一遍存储层的不变量。
    """
    if not session_ids:
        return {}
    names = {str(record.id): record.display_name for record in await list_objects(session, account_id=account_id)}
    bindings = await read_session_bindings(session, session_ids=session_ids)
    resolved: dict[str, str] = {}
    for session_id in session_ids:
        binding = bindings.get(session_id)
        if binding is None:
            continue
        display_name = names.get(str(binding.support_object_id))
        if display_name:
            resolved[session_id] = display_name
    return resolved


__all__ = ["read_object_names"]
