"""账号注销时清除该账号的图库数据（实现 `core/auth` 的 purger 端口）。

归属：`modules/memory`（图库是它的存储）。端口定义在
`core/auth/deletion.py`——见那里的说明：`core/*` 不得依赖 `modules/*`，
因此实现放这边、由装配处注入。
边界：图用 `GRAPH.DELETE` 整图丢弃；账本行一并删（理由与依据见 `MemoryAccountPurger` 的说明）。
参考：`docs/技术设计/technical-details/通用记忆.md` 第 1、7、8 节。
"""

from __future__ import annotations

import logging

from redis.exceptions import ResponseError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.deletion import PurgeOutcome
from campfire.core.config import Settings
from campfire.core.db import session_scope
from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.graph import MemoryGraph, build_memory_graph, release_shared_account_driver
from campfire.modules.memory.identity import to_account_id
from campfire.modules.memory.models import MemoryDeletionLedger

logger = logging.getLogger(__name__)

#: FalkorDB v4.20.7 对「图不存在」的 `GRAPH.DELETE` 报错原文（实测；从模块二进制里核过
#: 这条字符串只对应缺图/空键这一种情形）。只认它，不按前缀或异常类整体吞掉。
_MISSING_GRAPH_ERROR_MARKER = "Invalid graph operation on empty key"


class MemoryAccountPurger:
    """清除某账号的记忆数据：图库整图 + 关系库的删除账本。

    实现 :class:`campfire.core.auth.deletion.AccountDataPurger`（结构性满足，
    不显式继承——Protocol 的用法）。

    为什么账号级删除比单条删除干净：

    [通用记忆] 第 1 节实测：在 FalkorDB 后端 `group_id` 就是图名
    （`driver.clone(database=group_id)`）。因此「删除该账号的全部记忆」是
    丢掉整张图——一次完整操作，不受单条删除的两条约束（共享边不重算、
    物理清理延期）牵连。这正是决策记录里「账号级删除在技术上比单条删除更干净」的依据。

    为什么用 `GRAPH.DELETE` 而不是逐条删：

    逐条删要枚举节点与边、还要处理共享实体，既慢又不完备（`remove_episode`
    只删独占实体，见[通用记忆]第 7 节）。图级删除是存储层提供的原子操作。

    与删除账本的关系：

    该账号的账本行也要删（第 8 节：内容真删）。账本在关系库，不在图库，
    因此本 purger 一并处理——它是「该账号在记忆领域的全部数据」的清除者，
    图与账本都属于记忆领域。

    幂等：

    账号没有图、账本没有行时都正常返回（「无数据可清」），不报错——重试注销是正常
    路径。注意 `GRAPH.DELETE` 对不存在的图**会抛错**（v4.20.7 实测），因此「无图可
    丢弃」只认那一条确证的错误原文（`_MISSING_GRAPH_ERROR_MARKER`），不靠吞掉整类
    报错。也不先查 `GRAPH.LIST`：那多一次往返，且查完到删之间图仍可能被建出来
    （两步之间无锁），挡不住它要挡的情形。

    `name` 属性（`"memory"`）：注销编排的步骤名从它取（如
    `领域清除（memory）`），与 :class:`PurgeOutcome` 的 `name` 同源——
    多个清除者并存时，操作者据此分辨「哪个领域已清过」。
    """

    #: 清除者的领域名（编排步骤名与结果汇总共用，勿与类名耦合）。
    name = "memory"

    def __init__(self, settings: Settings) -> None:
        """记录配置。

        Args:
            settings: 应用配置（图库连接信息与库名的唯一来源）。
        """
        self._settings = settings

    async def purge_account(self, account_id: str) -> PurgeOutcome:
        """丢弃该账号的整张图，并删除其删除账本行。

        Args:
            account_id: 账号标识（在 FalkorDB 后端即图名）。

        Returns:
            :class:`PurgeOutcome`，说明图与账本各自的处置结果。

        Raises:
            Exception: 图库或关系库操作失败。不吞——注销的语义是「内容真删」，
                静默失败会让「已删除」成为谎话（见端口的实现者契约）。
        """
        graph_detail = await self._drop_graph(account_id)
        ledger_deleted = await self._delete_ledger_rows(account_id)
        detail = f"{graph_detail}；删除账本 {ledger_deleted} 行"
        logger.info("记忆清除完成：标识=%s %s", account_id, detail)
        return PurgeOutcome(name=self.name, detail=detail)

    async def _drop_graph(self, account_id: str) -> str:
        """丢弃该账号的图；图不存在时如实说明「无图可丢弃」（幂等）。

        不走 `driver_for(account_id)`：那会为该账号 clone 驱动并调度建索引的后台任务，
        紧接着删同一张图会让在途 `CREATE INDEX` 失败。图名就是账号标识（通用记忆
        第 1 节），直接用 base 驱动持有的共享客户端删即可。

        删之前先收口**本进程内已存在的共享句柄**为该账号派生的驱动
        （:func:`campfire.modules.memory.graph.release_shared_account_driver`）：注销走的是
        本方法自己建的一次性句柄，够不到共享句柄里那些建索引任务，而它们会在
        `GRAPH.DELETE` 之后继续跑。共享句柄不存在（或连接来源不同源）时不动手、也不新建。

        边界（不承诺的部分）：跨进程的共享句柄仍协调不了（另一个进程里的在途任务不在
        本方法视野内）；已在途的写（`add_episode` 正在进行）同样不在收口范围内——本方法
        只取消「已登记」的建索引任务。Worker 领取后复查墓碑；墓碑前已在途的操作仍有残余
        竞态，不能据此承诺完全不重建图（见 docs/TODO.md 的注销竞态登记）。

        Raises:
            AccountIdError: 账号标识不合法。
            MemoryDataError: 目标图就是配置库（拒绝误删）。
            MemoryUnavailableError: 拿不到图库客户端——不静默宣称已清除。
            redis.ResponseError: 图库拒绝该操作且原因不是「图不存在」（不吞）。
        """
        graph_name = str(to_account_id(account_id))
        if graph_name == self._settings.falkordb_database:
            raise MemoryDataError(
                "账号标识命中配置库名，拒绝按账号删除该图",
                operation="purge_memory_graph",
                detail=f"graph={graph_name!r}",
            )
        release_detail = await self._release_shared_drivers(graph_name)
        graph: MemoryGraph = build_memory_graph(self._settings)
        try:
            falkor_db = getattr(graph.driver, "client", None)
            if falkor_db is None:
                raise MemoryUnavailableError(
                    "未取到图库客户端，无法丢弃账号图",
                    operation="purge_memory_graph",
                    cause="missing_client",
                )
            try:
                await falkor_db.select_graph(graph_name).delete()
            except ResponseError as exc:
                # 只把「确证的缺图」当成功；连接、鉴权、语法等一律上抛。
                if _MISSING_GRAPH_ERROR_MARKER not in str(exc):
                    raise
                graph_detail = f"无图可丢弃（{graph_name!r} 不存在）"
            else:
                graph_detail = f"已丢弃图 {graph_name!r}"
        finally:
            # 释放本次为清理新建的驱动与客户端（不使用进程级共享实例：
            # 注销是低频运维操作，不值得为它常驻一个共享图对象）。
            await graph.aclose()
        return f"{graph_detail}；{release_detail}"

    async def _release_shared_drivers(self, graph_name: str) -> str:
        """删图之前收口本进程共享句柄为该账号派生的索引任务（best-effort，返回说明）。

        失败只留痕、不阻断删图：删图才是「内容真删」的承诺，收口只是让它别与在途
        `CREATE INDEX` 竞态；为收口失败而让注销整体失败，会把一个索引竞态升级成
        「账号删不掉」（而删除本身是可重试的正常路径）。
        """
        try:
            released = await release_shared_account_driver(self._settings, graph_name)
        except Exception as exc:  # noqa: BLE001 —— 前置清理失败不得阻断删图
            logger.warning("记忆清除：共享句柄的派生驱动收口失败（异常=%s），继续删图", type(exc).__name__)
            return f"共享句柄派生驱动收口失败（{type(exc).__name__}）"
        if released is None:
            return "本进程无同源共享句柄（未新建）"
        return "共享句柄已收口该账号的派生驱动" if released else "共享句柄无该账号的派生驱动"

    async def _delete_ledger_rows(self, account_id: str) -> int:
        """删除该账号的删除账本行，返回删除条数。

        为什么删账本行（第 8 节「内容真删」）：账本记录「某条 episode 被删」，
        属于该账号的数据。留着它会让「该账号的通用记忆已不再可读」这句话不成立——
        账本本身就是关于该账号的内容残迹。
        """
        async with session_scope(self._settings) as session:
            return await delete_ledger_rows(session, account_id=account_id)


async def delete_ledger_rows(session: AsyncSession, *, account_id: str) -> int:
    """删除某账号的全部删除账本行，返回条数。

    单独抽出成函数（而不是内联在 purger 里）以便测试直接调用，
    也让「账本清除」这一动作只有一个实现点。
    """
    result = await session.execute(delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id == account_id))
    # `rowcount` 在 `CursorResult` 上；`session.execute` 的静态类型是 `Result`
    # （mypy 实测抓到），故显式取属性并给安全默认值。
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "MemoryAccountPurger",
    "delete_ledger_rows",
]
