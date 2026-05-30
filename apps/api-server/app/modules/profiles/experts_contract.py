# @contract
"""profiles 专家关联行为契约 — ABC 模板方法骨架。

模块: app.modules.profiles.experts_contract
职责: 定义专家关联管理（PROF-05 消费端）的业务编排契约。覆盖两个操作：
      关联专家列表查询、解除专家关联。
      每个 @final 公共入口强制执行 前置校验 → _do_ 钩子 → 后置校验 三步流程，
      实现者只能覆写 _do_ 前缀的钩子方法。

数据来源:
  - py_db.repositories.teacher_link_repository.TeacherLinkRepository: MUST — 关联持久化
  - py_db.repositories.profile_repository.ProfileRepository: MUST — 档案存在性校验
  - py_db.repositories.user_repository.UserRepository: MUST — 专家用户查询
  - py_schemas.profiles.ExpertInfo: MUST — 数据契约

边界:
  - 依赖: py_db, py_schemas, sqlalchemy (AsyncSession)
  - 被依赖: expert_routes.py (FastAPI 路由层)

禁止行为:
  - 禁止在 @final 方法中直接调用 Repository 方法（必须走 _do_ 钩子）
  - 禁止在 _do_ 钩子中直接操作 FastAPI HTTPException
  - 禁止实现者覆写 @final 方法
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles._profile_guard import ensure_profile_exists
from app.modules.profiles.exceptions import ExpertLinkNotFoundError

if TYPE_CHECKING:
    from py_db.repositories.profile_repository import ProfileRepository
    from py_db.repositories.teacher_link_repository import TeacherLinkRepository
    from py_db.repositories.user_repository import UserRepository
    from py_schemas.profiles import ExpertInfo
    from uuid import UUID


class BaseExpertService(ABC):
    """专家关联管理服务契约 — 业务编排层 ABC。

    实现者只能覆写 _do_ 前缀的钩子方法。
    """

    def __init__(
        self,
        link_repository: "TeacherLinkRepository",
        profile_repository: "ProfileRepository",
        user_repository: "UserRepository",
    ) -> None:
        self._link_repo = link_repository
        self._profile_repo = profile_repository
        self._user_repo = user_repository

    # ======================================================================
    # 关联专家列表 — PROF-05
    # ======================================================================

    @final
    async def list_experts(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> list["ExpertInfo"]:
        """查询指定档案的关联专家列表。

        前置: profile_id 存在且归属 caregiver_id
        后置: 返回 ExpertInfo 列表（可为空）
        异常: ProfileNotFoundError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, caregiver_id, session)
        return await self._do_list_experts(profile_id, session)

    @abstractmethod
    async def _do_list_experts(
        self,
        profile_id: "UUID",
        session: AsyncSession,
    ) -> list["ExpertInfo"]:
        """执行关联专家查询。"""
        ...

    # ======================================================================
    # 解除专家关联 — PROF-05
    # ======================================================================

    @final
    async def unlink_expert(
        self,
        profile_id: "UUID",
        link_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> None:
        """解除指定档案与专家的关联。

        前置: profile_id 存在且归属 caregiver_id，link_id 存在
        后置: 关联已解除
        异常: ProfileNotFoundError, ExpertLinkNotFoundError, ExpertLinkConflictError
        """
        await ensure_profile_exists(self._profile_repo, profile_id, caregiver_id, session)
        success = await self._do_unlink_expert(profile_id, link_id, session)
        if not success:
            raise ExpertLinkNotFoundError(str(link_id), str(profile_id))

    @abstractmethod
    async def _do_unlink_expert(
        self,
        profile_id: "UUID",
        link_id: "UUID",
        session: AsyncSession,
    ) -> bool:
        """执行专家关联解除。返回 True 表示成功。"""
        ...


__all__ = ["BaseExpertService"]
