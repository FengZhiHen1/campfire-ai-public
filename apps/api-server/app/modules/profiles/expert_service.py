"""PROF-05 专家关联管理 — 契约实现。

继承 BaseExpertService ABC，填充 _do_ 钩子。
按契约模板方法：路由 → @final 公共入口（前置校验） → _do_ 钩子（数据操作） → 后置校验。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.auth import User
from py_schemas.profiles import ExpertInfo
from py_db.repositories.profile_repository import ProfileRepository
from py_db.repositories.teacher_link_repository import TeacherLinkRepository, StaleDataError
from py_db.repositories.user_repository import UserRepository

from py_logger import logger

from app.modules.profiles.exceptions import ExpertLinkConflictError
from app.modules.profiles.experts_contract import BaseExpertService


class ExpertServiceImpl(BaseExpertService):
    """PROF-05 专家关联管理服务实现。

    继承 BaseExpertService，仅覆写 _do_ 钩子方法。
    """

    def __init__(
        self,
        link_repository: TeacherLinkRepository | None = None,
        profile_repository: ProfileRepository | None = None,
        user_repository: UserRepository | None = None,
    ) -> None:
        super().__init__(
            link_repository=link_repository or TeacherLinkRepository(session_factory=None),
            profile_repository=profile_repository or ProfileRepository(session_factory=None),
            user_repository=user_repository or UserRepository(session_factory=None),
        )

    # ------------------------------------------------------------------
    # _do_ 钩子 — 关联专家列表
    # ------------------------------------------------------------------

    async def _do_list_experts(
        self,
        profile_id: UUID,
        session: AsyncSession,
    ) -> list[ExpertInfo]:
        links = await self._link_repo.find_links_by_profile(session, profile_id)
        if not links:
            return []

        # 批量查询所有关联专家用户（避免 N+1）
        teacher_ids = [link.teacher_id for link in links]
        result = await session.execute(
            select(User).where(User.id.in_(teacher_ids))
        )
        users_by_id = {u.id: u for u in result.scalars().all()}

        experts: list[ExpertInfo] = []
        for link in links:
            user = users_by_id.get(link.teacher_id)
            if user is None:
                continue
            name = user.real_name or user.username
            experts.append(
                ExpertInfo(
                    expert_id=str(link.teacher_id),
                    link_id=str(link.link_id),
                    name=name,
                    role=link.role,
                    created_at=link.created_at,
                )
            )

        logger.info(
            "expert_list",
            extra={"profile_id": str(profile_id), "count": len(experts)},
        )
        return experts

    # ------------------------------------------------------------------
    # _do_ 钩子 — 解除专家关联
    # ------------------------------------------------------------------

    async def _do_unlink_expert(
        self,
        profile_id: UUID,
        link_id: UUID,
        session: AsyncSession,
    ) -> bool:
        links = await self._link_repo.find_links_by_profile(session, profile_id)
        target_link = next((lnk for lnk in links if lnk.link_id == link_id), None)
        if target_link is None:
            return False

        try:
            await self._link_repo.unlink_teacher(
                session, link_id, expected_version=target_link.version
            )
        except StaleDataError:
            logger.warning(
                "expert_unlink_conflict",
                extra={"link_id": str(link_id), "profile_id": str(profile_id)},
            )
            raise ExpertLinkConflictError(str(link_id))

        logger.info(
            "expert_unlinked",
            extra={"profile_id": str(profile_id), "link_id": str(link_id)},
        )
        return True


__all__ = ["ExpertServiceImpl"]
