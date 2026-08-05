"""档案服务——四层 CRUD（身份基础必填，危机预案渐进完善）。

- 家属创建多档案（一个账号多个患者）
- 分层分步保存（身份/危机预案独立部分更新）
- 默认档案管理（is_default 唯一性）
"""

from __future__ import annotations

import uuid
from datetime import date

from py_db.models.profiles import Profile
from py_db.repositories.profile_repository import ProfileRepository
from py_schemas.profiles import (
    CrisisPlanLayerDto,
    IdentityLayerDto,
    ProfileCreateRequest,
    ProfileListItem,
    ProfileResponse,
    ProfileUpdateRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.guard import ProfileAccessContext


def compute_age_range(birth_date: date) -> str:
    """由出生日期计算年龄区间（全生命周期覆盖）。"""
    today = date.today()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    if age <= 5:
        return "学龄前(0-5岁)"
    if age <= 12:
        return "学龄儿童(6-12岁)"
    if age <= 17:
        return "青少年(13-17岁)"
    if age <= 25:
        return "青年(18-25岁)"
    return "成年(26岁及以上)"


def _to_response(profile: Profile, viewer: ProfileAccessContext | None = None) -> ProfileResponse:
    """ORM → DTO（字段级可见性：medication_notes 仅家属/老师）。"""
    medication_visible = viewer is None or viewer.can_view_medication
    return ProfileResponse(
        profile_id=str(profile.profile_id),
        caregiver_id=str(profile.caregiver_id),
        identity=IdentityLayerDto(
            nickname=profile.nickname,
            birth_date=profile.birth_date,
            diagnosis_type=profile.diagnosis_type,
            primary_behavior=profile.primary_behavior,
            comorbidities=profile.comorbidities or [],
            sensory_profile=profile.sensory_profile or [],
            triggers=profile.triggers or [],
            is_default=profile.is_default,
        ),
        crisis_plan=CrisisPlanLayerDto(
            physical_description=profile.physical_description,
            familiar_places=profile.familiar_places or [],
            water_risk=profile.water_risk or [],
            soothing_items=profile.soothing_items or [],
            avoid_list=profile.avoid_list or [],
            communication_methods=profile.communication_methods or [],
            emergency_contacts=profile.emergency_contacts or [],
            medication_notes=profile.medication_notes if medication_visible else None,
        ),
        age_range=compute_age_range(profile.birth_date),
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


class ProfileService:
    """档案服务。"""

    def __init__(self, profile_repo: ProfileRepository) -> None:
        self._profile_repo = profile_repo

    async def create(
        self,
        session: AsyncSession,
        caregiver_id: str,
        request: ProfileCreateRequest,
    ) -> ProfileResponse:
        """创建档案（家属；身份基础必填 + 危机预案可选）。"""
        profile = Profile(
            caregiver_id=uuid.UUID(caregiver_id),
            nickname=request.identity.nickname,
            birth_date=request.identity.birth_date,
            diagnosis_type=request.identity.diagnosis_type,
            primary_behavior=request.identity.primary_behavior,
            comorbidities=[c.value for c in request.identity.comorbidities],
            sensory_profile=request.identity.sensory_profile,
            triggers=request.identity.triggers,
            is_default=request.identity.is_default,
        )
        if request.crisis_plan:
            cp = request.crisis_plan
            profile.physical_description = cp.physical_description
            profile.familiar_places = cp.familiar_places
            profile.water_risk = cp.water_risk
            profile.soothing_items = cp.soothing_items
            profile.avoid_list = cp.avoid_list
            profile.communication_methods = [m.value for m in cp.communication_methods]
            profile.emergency_contacts = [c.model_dump() for c in cp.emergency_contacts]
            profile.medication_notes = cp.medication_notes

        created = await self._profile_repo.create(session, profile)

        # 默认档案唯一性：设为默认时清除同账号其他默认
        if created.is_default:
            await self._clear_other_defaults(session, created.caregiver_id, created.profile_id)

        await session.commit()
        return _to_response(created)

    async def list_mine(self, session: AsyncSession, caregiver_id: str) -> list[ProfileListItem]:
        """家属名下档案列表。"""
        profiles = await self._profile_repo.list_by_caregiver(session, uuid.UUID(caregiver_id))
        return [
            ProfileListItem(
                profile_id=str(p.profile_id),
                nickname=p.nickname,
                age_range=compute_age_range(p.birth_date),
                diagnosis_type=p.diagnosis_type,
                primary_behavior=p.primary_behavior,
                is_default=p.is_default,
                created_at=p.created_at.isoformat(),
            )
            for p in profiles
        ]

    def to_response(self, profile: Profile, viewer: ProfileAccessContext | None = None) -> ProfileResponse:
        return _to_response(profile, viewer)

    async def update(
        self,
        session: AsyncSession,
        profile: Profile,
        request: ProfileUpdateRequest,
    ) -> ProfileResponse:
        """更新档案（仅家属；分层部分更新）。"""
        if request.identity is not None:
            identity = request.identity
            profile.nickname = identity.nickname
            profile.birth_date = identity.birth_date
            profile.diagnosis_type = identity.diagnosis_type
            profile.primary_behavior = identity.primary_behavior
            profile.comorbidities = [c.value for c in identity.comorbidities]
            profile.sensory_profile = identity.sensory_profile
            profile.triggers = identity.triggers
            profile.is_default = identity.is_default
        if request.crisis_plan is not None:
            cp = request.crisis_plan
            profile.physical_description = cp.physical_description
            profile.familiar_places = cp.familiar_places
            profile.water_risk = cp.water_risk
            profile.soothing_items = cp.soothing_items
            profile.avoid_list = cp.avoid_list
            profile.communication_methods = [m.value for m in cp.communication_methods]
            profile.emergency_contacts = [c.model_dump() for c in cp.emergency_contacts]
            profile.medication_notes = cp.medication_notes

        if profile.is_default:
            await self._clear_other_defaults(session, profile.caregiver_id, profile.profile_id)
        await session.commit()
        return _to_response(profile)

    async def delete(self, session: AsyncSession, profile: Profile) -> None:
        """删除档案（仅家属；级联删除事件/关联）。"""
        await session.delete(profile)
        await session.commit()

    async def _clear_other_defaults(
        self,
        session: AsyncSession,
        caregiver_id: uuid.UUID,
        except_profile_id: uuid.UUID,
    ) -> None:
        """清除同账号其他档案的默认标记（默认档案唯一）。"""
        profiles = await self._profile_repo.list_by_caregiver(session, caregiver_id)
        for p in profiles:
            if p.profile_id != except_profile_id and p.is_default:
                p.is_default = False


__all__ = ["ProfileService", "compute_age_range"]
