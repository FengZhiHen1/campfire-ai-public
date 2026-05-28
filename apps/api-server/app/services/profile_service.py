"""PROF-01 个人档案管理 — MVP Phase 1 多档案版 Service。

去除 RBAC、隐私控制、事件管理等非核心逻辑。
保留：档案创建/列表/详情/更新/删除/设默认。
"""

from __future__ import annotations

import math
import uuid
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.profiles import Profile
from py_db.repositories.profile_repository import ProfileRepository
from py_logger import logger
from py_schemas.profiles import AgeRange, ProfileCreate, ProfileListItem, ProfileResponse, ProfileUpdate


class ProfileService:
    """MVP 多档案版档案管理 Service。"""

    def __init__(self, repository: ProfileRepository | None = None) -> None:
        self._repository = repository or ProfileRepository(session_factory=None)

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    async def list_profiles(
        self,
        caregiver_id: UUID,
        session: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[ProfileListItem], int]:
        """查询当前用户的档案列表。"""
        profiles, total = await self._repository.list_by_caregiver(
            session, caregiver_id, page=page, page_size=page_size
        )
        items = [self._to_list_item(p) for p in profiles]
        return items, total

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------

    async def get_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse | None:
        """按 ID 查询单条档案（带归属校验）。"""
        profile = await self._repository.get_by_id(session, profile_id, caregiver_id)
        if profile is None:
            return None
        return self._to_response(profile)

    async def get_my_profile(
        self,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse | None:
        """查询当前用户的默认档案（/me 快捷端点）。"""
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
    # 创建
    # ------------------------------------------------------------------

    async def create_profile(
        self,
        caregiver_id: UUID,
        input_data: ProfileCreate,
        session: AsyncSession,
    ) -> ProfileResponse:
        """创建新档案。

        若用户当前没有任何档案，自动将新档案设为默认。
        """
        count = await self._repository.count_active_by_caregiver(session, caregiver_id)

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
            is_default=(count == 0),
        )
        created = await self._repository.create(session, profile)
        await session.commit()
        logger.info(
            service="api-server",
            message="profile_created",
            extra={"profile_id": str(created.profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(created)

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    async def update_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        input_data: ProfileUpdate,
        session: AsyncSession,
    ) -> ProfileResponse:
        """更新档案（Merge Patch）。"""
        profile = await self._repository.get_by_id(session, profile_id, caregiver_id)
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="档案不存在",
            )

        update_data: dict[str, Any] = input_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        await session.flush()
        await session.commit()
        await session.refresh(profile)
        logger.info(
            service="api-server",
            message="profile_updated",
            extra={"profile_id": str(profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(profile)

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def delete_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> None:
        """删除档案。

        若删除的是默认档案，自动将最新更新的剩余档案提升为默认。
        """
        profile = await self._repository.get_by_id(session, profile_id, caregiver_id)
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="档案不存在",
            )

        was_default = profile.is_default
        deleted = await self._repository.delete(session, profile_id, caregiver_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="档案不存在",
            )

        await session.commit()
        logger.info(
            service="api-server",
            message="profile_deleted",
            extra={"profile_id": str(profile_id), "caregiver_id": str(caregiver_id)},
        )

        # 若删除的是默认档案，自动提升下一候选
        if was_default:
            candidate = await self._repository.find_next_default_candidate(
                session, caregiver_id, profile_id
            )
            if candidate:
                await self._repository.set_default(session, candidate.profile_id, caregiver_id)
                await session.commit()
                logger.info(
                    service="api-server",
                    message="default_profile_promoted",
                    extra={
                        "profile_id": str(candidate.profile_id),
                        "caregiver_id": str(caregiver_id),
                    },
                )

    # ------------------------------------------------------------------
    # 设默认
    # ------------------------------------------------------------------

    async def set_default_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse:
        """将指定档案设为默认。"""
        profile = await self._repository.set_default(session, profile_id, caregiver_id)
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="档案不存在",
            )
        await session.commit()
        await session.refresh(profile)
        logger.info(
            service="api-server",
            message="profile_set_default",
            extra={"profile_id": str(profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(profile)

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

    def _to_list_item(self, profile: Profile) -> ProfileListItem:
        """将 ORM 实例转为列表项模型。"""
        from datetime import date

        age = None
        if profile.birth_date:
            age = (date.today() - profile.birth_date).days // 365

        return ProfileListItem(
            profile_id=profile.profile_id,
            nickname=profile.nickname,
            age_range=self._calc_age_range(age),
            diagnosis_type=profile.diagnosis_type,
            primary_behavior=profile.primary_behavior,
            is_default=profile.is_default,
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
