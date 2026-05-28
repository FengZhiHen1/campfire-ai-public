"""PROF-01 个人档案管理 — MVP Phase 1 简化版 Service。

去除 RBAC、隐私控制、档案数量上限、事件管理等非核心逻辑。
保留：档案创建/更新/查询（单条，按 caregiver_id = user_id）。
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.profiles import Profile
from py_db.repositories.profile_repository import ProfileRepository
from py_logger import logger
from py_schemas.profiles import AgeRange, ProfileCreate, ProfileResponse, ProfileUpdate


class ProfileService:
    """MVP 简化版档案管理 Service。"""

    def __init__(self, repository: ProfileRepository | None = None) -> None:
        self._repository = repository or ProfileRepository(session_factory=None)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    async def get_or_create_profile(
        self,
        caregiver_id: UUID,
        input_data: ProfileCreate,
        session: AsyncSession,
    ) -> ProfileResponse:
        """创建或更新档案（MVP 单档案模式）。

        若该 caregiver_id 下已有档案，则更新；否则创建新档案。
        """
        existing = await self._repository.get_default(session, caregiver_id)
        if existing is None:
            # 兜底：查找任意一条记录
            profiles, _ = await self._repository.list_by_caregiver(
                session, caregiver_id, page=1, page_size=1
            )
            existing = profiles[0] if profiles else None

        if existing:
            # 更新现有档案
            update_data: dict[str, Any] = input_data.model_dump(exclude_unset=True)
            # 处理 tags 字段（JSONB 列表）
            if "tags" in update_data and isinstance(update_data["tags"], str):
                update_data["tags"] = [
                    t.strip() for t in update_data["tags"].split(",") if t.strip()
                ]
            # 直接用 SQLAlchemy ORM 更新
            for key, value in update_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await session.flush()
            await session.commit()
            await session.refresh(existing)
            logger.info(
                service="api-server",
                message="profile_updated",
                extra={"profile_id": str(existing.profile_id), "caregiver_id": str(caregiver_id)},
            )
            return self._to_response(existing)

        # 创建新档案
        profile = Profile(
            profile_id=uuid.uuid4(),
            caregiver_id=caregiver_id,
            nickname=input_data.nickname,
            birth_date=input_data.birth_date,
            diagnosis_type=input_data.diagnosis_type,
            primary_behavior=input_data.primary_behavior,
            language_level=input_data.language_level,
            sensory_features=input_data.sensory_features or [],
            triggers=input_data.triggers or [],
            medication_notes=input_data.medication_notes,
            is_default=True,
        )
        created = await self._repository.create(session, profile)
        await session.commit()
        logger.info(
            service="api-server",
            message="profile_created",
            extra={"profile_id": str(created.profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(created)

    async def get_my_profile(
        self,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse | None:
        """查询当前用户的档案（单条）。"""
        existing = await self._repository.get_default(session, caregiver_id)
        if existing is None:
            profiles, _ = await self._repository.list_by_caregiver(
                session, caregiver_id, page=1, page_size=1
            )
            existing = profiles[0] if profiles else None

        if existing is None:
            return None
        return self._to_response(existing)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _to_response(self, profile: Profile) -> ProfileResponse:
        """将 ORM 实例转为响应模型。"""
        from datetime import date

        age = None
        if profile.birth_date:
            age = (date.today() - profile.birth_date).days // 365

        return ProfileResponse(
            profile_id=profile.profile_id,
            caregiver_id=profile.caregiver_id,
            nickname=profile.nickname,
            birth_date=profile.birth_date,
            age_range=self._calc_age_range(age),
            diagnosis_type=profile.diagnosis_type,
            primary_behavior=profile.primary_behavior,
            language_level=profile.language_level,
            sensory_features=profile.sensory_features or [],
            triggers=profile.triggers or [],
            medication_notes=profile.medication_notes,
            is_default=profile.is_default,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _calc_age_range(age: int | None) -> AgeRange:
        if age is None:
            return AgeRange.AGE_18_PLUS
        if age <= 3:
            return AgeRange.AGE_0_3
        elif age <= 6:
            return AgeRange.AGE_4_6
        elif age <= 12:
            return AgeRange.AGE_7_12
        elif age <= 18:
            return AgeRange.AGE_13_18
        else:
            return AgeRange.AGE_18_PLUS


__all__ = ["ProfileService"]
