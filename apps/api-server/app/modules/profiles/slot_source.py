"""槽位数据源实现（S3 slot_filler 的 ProfileSnapshotProvider 落地）。

数据源：危机预案层字段（profiles 表字段组）；
推导兜底（数据模型 §3）：soothing_items 空 → 最近 outcome=有效 事件的
consequence；avoid_list 空 → 最近 outcome=无效 事件的 consequence。
"""

from __future__ import annotations

import uuid

from py_db.repositories.profile_repository import EventLogRepository, ProfileRepository
from py_schemas.enums import Outcome
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crisis.slot_filler import ProfileSnapshot


class ProfileSnapshotProviderImpl:
    """危机预案层快照供给（S4 落地实现）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._profile_repo = ProfileRepository(session_factory=None)  # type: ignore[arg-type]
        self._event_repo = EventLogRepository(session_factory=None)  # type: ignore[arg-type]

    async def get_snapshot(self, profile_id: str) -> ProfileSnapshot | None:
        try:
            pid = uuid.UUID(profile_id)
        except (ValueError, AttributeError):
            return None

        profile = await self._profile_repo.get_by_id(self._session, pid)
        if profile is None:
            return None

        soothing = list(profile.soothing_items or [])
        avoid = list(profile.avoid_list or [])

        # 推导兜底（数据模型 §3：家属未显式维护时从事件推导）
        if not soothing:
            soothing = await self._derive_from_events(pid, Outcome.EFFECTIVE)
        if not avoid:
            avoid = await self._derive_from_events(pid, Outcome.INEFFECTIVE)

        return ProfileSnapshot(
            nickname=profile.nickname,
            triggers=list(profile.triggers or []),
            soothing_items=soothing,
            avoid_list=avoid,
            communication_methods=list(profile.communication_methods or []),
            physical_description=profile.physical_description,
            familiar_places=list(profile.familiar_places or []),
            water_risk=list(profile.water_risk or []),
            emergency_contacts=list(profile.emergency_contacts or []),
        )

    async def _derive_from_events(self, profile_id: uuid.UUID, outcome: Outcome) -> list[str]:
        """从最近有效/无效事件的 consequence 推导安抚/禁忌项。"""
        event = await self._event_repo.find_latest_by_outcome(self._session, profile_id, outcome)
        if event is not None and event.consequence:
            return [event.consequence]
        return []


__all__ = ["ProfileSnapshotProviderImpl"]
