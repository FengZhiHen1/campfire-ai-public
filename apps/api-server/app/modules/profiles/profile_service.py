"""PROF-01 个人档案管理 — 契约实现。

继承 BaseProfileService ABC，填充 _do_ 钩子。
按契约模板方法：路由 → @final 公共入口（前置校验） → _do_ 钩子（数据操作） → 后置校验。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.profiles import Profile
from py_db.repositories.profile_repository import ProfileRepository
from py_logger import logger
from py_schemas.profiles import (
    AgeRange,
    DiagnosisType,
    LanguageLevel,
    ProfileBehaviorType,
    ProfileCreate,
    ProfileListItem,
    ProfileResponse,
    ProfileUpdate,
)

from app.modules.profiles.profiles_contract import BaseProfileService


class ProfileServiceImpl(BaseProfileService):
    """PROF-01 档案管理服务实现。

    继承 BaseProfileService，仅覆写 _do_ 钩子方法。
    @final 公共方法由 ABC 模板提供，不可覆写。
    """

    def __init__(self, repository: ProfileRepository | None = None) -> None:
        super().__init__(repository or ProfileRepository(session_factory=None))

    # ------------------------------------------------------------------
    # _do_ 钩子 — 列表
    # ------------------------------------------------------------------

    async def _do_list_profiles(
        self,
        caregiver_id: UUID,
        session: AsyncSession,
        page: int,
        page_size: int,
    ) -> tuple[list[ProfileListItem], int]:
        profiles, total = await self._repository.list_by_caregiver(
            session, caregiver_id, page=page, page_size=page_size
        )
        items = [self._to_list_item(p) for p in profiles]
        return items, total

    # ------------------------------------------------------------------
    # _do_ 钩子 — 详情
    # ------------------------------------------------------------------

    async def _do_get_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse | None:
        profile = await self._repository.get_by_id(session, profile_id, caregiver_id)
        if profile is None:
            return None
        return self._to_response(profile)

    # ------------------------------------------------------------------
    # _do_ 钩子 — 默认档案
    # ------------------------------------------------------------------

    async def _do_get_my_profile(
        self,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse | None:
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
    # _do_ 钩子 — 创建
    # ------------------------------------------------------------------

    async def _do_create_profile(
        self,
        caregiver_id: UUID,
        input_data: ProfileCreate,
        session: AsyncSession,
    ) -> ProfileResponse:
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
            is_default=False,
        )
        created = await self._repository.create(session, profile)

        if count == 0:
            created = await self._repository.set_default(
                session, created.profile_id, caregiver_id
            ) or created

        await session.commit()
        logger.info(
            "profile_service",
            "档案创建成功",
            extra={"profile_id": str(created.profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(created)

    # ------------------------------------------------------------------
    # _do_ 钩子 — 更新
    # ------------------------------------------------------------------

    async def _do_update_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        input_data: ProfileUpdate,
        session: AsyncSession,
    ) -> ProfileResponse | None:
        profile = await self._repository.get_by_id(session, profile_id, caregiver_id)
        if profile is None:
            return None

        update_data: dict[str, Any] = input_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)

        await session.flush()
        await session.commit()
        await session.refresh(profile)
        logger.info(
            "profile_service",
            "档案已更新",
            extra={"profile_id": str(profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(profile)

    # ------------------------------------------------------------------
    # _do_ 钩子 — 删除
    # ------------------------------------------------------------------

    async def _do_delete_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> bool:
        profile = await self._repository.get_by_id(session, profile_id, caregiver_id)
        if profile is None:
            return False

        was_default = profile.is_default
        deleted = await self._repository.delete_profile(session, profile_id, caregiver_id)
        if not deleted:
            return False

        await session.commit()
        logger.info(
            "profile_service",
            "档案已删除",
            extra={"profile_id": str(profile_id), "caregiver_id": str(caregiver_id)},
        )

        if was_default:
            candidate = await self._repository.find_next_default_candidate(
                session, caregiver_id, profile_id
            )
            if candidate:
                await self._repository.set_default(session, candidate.profile_id, caregiver_id)
                await session.commit()
                logger.info(
                    "profile_service",
                    "默认档案已自动提升",
                    extra={
                        "profile_id": str(candidate.profile_id),
                        "caregiver_id": str(caregiver_id),
                    },
                )

        return True

    # ------------------------------------------------------------------
    # _do_ 钩子 — 设为默认
    # ------------------------------------------------------------------

    async def _do_set_default_profile(
        self,
        profile_id: UUID,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse | None:
        profile = await self._repository.set_default(session, profile_id, caregiver_id)
        if profile is None:
            return None
        await session.commit()
        await session.refresh(profile)
        logger.info(
            "profile_service",
            "已设为默认档案",
            extra={"profile_id": str(profile_id), "caregiver_id": str(caregiver_id)},
        )
        return self._to_response(profile)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _to_response(self, profile: Profile) -> ProfileResponse:
        return ProfileResponse(
            profile_id=profile.profile_id,
            caregiver_id=profile.caregiver_id,
            nickname=profile.nickname,
            birth_date=profile.birth_date,
            age_range=self._calc_age_range(profile.birth_date),
            diagnosis_type=DiagnosisType(profile.diagnosis_type),
            primary_behavior=ProfileBehaviorType(profile.primary_behavior),
            language_level=LanguageLevel(profile.language_level) if profile.language_level else None,
            sensory_features=profile.sensory_features or [],
            triggers=profile.triggers or [],
            medication_notes=profile.medication_notes,
            is_default=profile.is_default,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def _to_list_item(self, profile: Profile) -> ProfileListItem:
        return ProfileListItem(
            profile_id=profile.profile_id,
            nickname=profile.nickname,
            age_range=self._calc_age_range(profile.birth_date),
            diagnosis_type=DiagnosisType(profile.diagnosis_type),
            primary_behavior=ProfileBehaviorType(profile.primary_behavior),
            is_default=profile.is_default,
        )

    @staticmethod
    def _calc_age_range(birth_date: date | None) -> AgeRange:
        """根据出生日期计算年龄区间。"""
        if birth_date is None:
            return AgeRange.AGE_18_PLUS
        age = (date.today() - birth_date).days // 365
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


__all__ = ["ProfileServiceImpl"]
