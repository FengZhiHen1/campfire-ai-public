"""档案快照供给——ProfileSnapshotProvider 实现（现有 profiles 表）。

S3 现状数据源：profiles 表 JSON 字段（triggers/sensory_features 等）。
S4 档案四层落地后切换为危机预案层数据源（soothing_items/avoid_list/
communication_methods/走失专项组）——本文件是 S3↔S4 的衔接点。
"""

from __future__ import annotations

import uuid
from typing import Any

from py_db.models.profiles import Profile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crisis.slot_filler import ProfileSnapshot

# 语言水平 → 沟通方式槽位的近似映射（S4 communication_methods 落地前过渡）
_LANGUAGE_TO_COMMUNICATION: dict[str, str] = {
    "无语言": "视觉提示卡",
    "单字词": "单字短句",
    "short_phrases": "简短句式",
    "可对话": "正常对话",
}


class DbProfileSnapshotProvider:
    """基于现有 profiles 表的快照供给（S3 过渡实现）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_snapshot(self, profile_id: str) -> ProfileSnapshot | None:
        try:
            pid = uuid.UUID(profile_id)
        except (ValueError, AttributeError):
            return None
        result = await self._session.execute(select(Profile).where(Profile.profile_id == pid))
        profile = result.scalars().first()
        if profile is None:
            return None

        triggers = _as_str_list(getattr(profile, "triggers", None))
        language_level = getattr(profile, "language_level", None)
        communication: list[str] = []
        if language_level and language_level in _LANGUAGE_TO_COMMUNICATION:
            communication.append(_LANGUAGE_TO_COMMUNICATION[language_level])

        return ProfileSnapshot(
            nickname=getattr(profile, "nickname", None),
            triggers=triggers,
            soothing_items=[],  # S4 危机预案层落地后接线
            avoid_list=[],  # S4 接线
            communication_methods=communication,
        )


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []


__all__ = ["DbProfileSnapshotProvider"]
