"""档案快照供给——S4 接线完成（危机预案层数据源）。

S3 过渡期曾直接读 profiles 旧字段；现委托 profiles 模块的
ProfileSnapshotProviderImpl（危机预案层 + 事件推导兜底）。
本模块保留以维持 emergency_service 的 import 路径稳定。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crisis.slot_filler import ProfileSnapshot
from app.modules.profiles.slot_source import ProfileSnapshotProviderImpl


class DbProfileSnapshotProvider:
    """档案快照供给（委托 profiles 模块的危机预案层实现）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._impl = ProfileSnapshotProviderImpl(session)

    async def get_snapshot(self, profile_id: str) -> ProfileSnapshot | None:
        return await self._impl.get_snapshot(profile_id)


__all__ = ["DbProfileSnapshotProvider"]
