# @contract
"""profiles 档案管理行为契约 — ABC 模板方法骨架。

模块: app.modules.profiles.profiles_contract
职责: 定义个人档案 CRUD 的业务编排契约。覆盖 PROF-01 的七个核心操作：
      列表查询、详情查询、默认档案查询、创建、更新、删除、设默认。
      每个 @final 公共入口强制执行 前置校验 → _do_ 钩子 → 后置校验 三步流程，
      实现者只能覆写 _do_ 前缀的钩子方法。

数据来源:
  - py_db.repositories.profile_repository.ProfileRepository: MUST — 档案持久化
  - py_schemas.profiles (ProfileCreate, ProfileUpdate, ProfileResponse, ProfileListItem): MUST — 数据契约
  - py_logger: SHOULD — 结构化操作日志

边界:
  - 依赖: py_db, py_schemas, sqlalchemy (AsyncSession)
  - 被依赖: routes.py (FastAPI 路由层)

禁止行为:
  - 禁止在 @final 方法中直接调用 Repository 方法（必须走 _do_ 钩子）
  - 禁止在 _do_ 钩子中直接操作 FastAPI HTTPException（由 @final 方法统一转换异常）
  - 禁止在 Service 层直接操作 HTTP 请求对象
  - 禁止实现者覆写 @final 方法
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.exceptions import (
    ProfileLimitExceededError,
    ProfileNotFoundError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from py_db.repositories.profile_repository import ProfileRepository
    from py_schemas.profiles import (
        ProfileCreate,
        ProfileListItem,
        ProfileResponse,
        ProfileUpdate,
    )


class BaseProfileService(ABC):
    """个人档案管理服务契约 — 业务编排层 ABC。

    实现者只能覆写 _do_ 前缀的钩子方法。
    外部调用者通过 @final 方法进入，无法绕过前置校验和后置处理。
    """

    def __init__(self, repository: "ProfileRepository") -> None:
        self._repository = repository

    # ======================================================================
    # 档案列表 — PROF-01
    # ======================================================================

    @final
    async def list_profiles(
        self,
        caregiver_id: "UUID",
        session: AsyncSession,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list["ProfileListItem"], int]:
        """查询当前用户的档案列表（分页）。

        前置: caregiver_id 有效，session 活跃
        后置: 返回 (items, total) 元组
        异常: 无（空列表合法）
        """
        return await self._do_list_profiles(caregiver_id, session, page, page_size)

    @abstractmethod
    async def _do_list_profiles(
        self,
        caregiver_id: "UUID",
        session: AsyncSession,
        page: int,
        page_size: int,
    ) -> tuple[list["ProfileListItem"], int]:
        """执行档案列表查询。"""
        ...

    # ======================================================================
    # 档案详情 — PROF-01
    # ======================================================================

    @final
    async def get_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "ProfileResponse":
        """按 ID 查询档案详情（带归属校验）。

        前置: profile_id + caregiver_id 有效
        后置: 返回 ProfileResponse 或抛出 ProfileNotFoundError
        异常: ProfileNotFoundError
        """
        result = await self._do_get_profile(profile_id, caregiver_id, session)
        if result is None:
            raise ProfileNotFoundError(str(profile_id))
        return result

    @abstractmethod
    async def _do_get_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "ProfileResponse | None":
        """执行档案详情查询。"""
        ...

    # ======================================================================
    # 默认档案 — PROF-01
    # ======================================================================

    @final
    async def get_my_profile(
        self,
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "ProfileResponse":
        """查询当前用户的默认档案（/me 快捷端点）。

        先查默认标记，若无可降级到最新档案。
        前置: caregiver_id 有效
        后置: 返回 ProfileResponse
        异常: ProfileNotFoundError — 用户无任何档案
        """
        result = await self._do_get_my_profile(caregiver_id, session)
        if result is None:
            raise ProfileNotFoundError(str(caregiver_id), actual_reason="no_profiles")
        return result

    @abstractmethod
    async def _do_get_my_profile(
        self,
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "ProfileResponse | None":
        """执行默认档案查询（含降级逻辑）。"""
        ...

    # ======================================================================
    # 创建档案 — PROF-01
    # ======================================================================

    @final
    async def create_profile(
        self,
        caregiver_id: "UUID",
        input_data: "ProfileCreate",
        session: AsyncSession,
    ) -> "ProfileResponse":
        """创建新档案。

        前置: caregiver_id 有效，input_data 已通过 Pydantic 校验
        后置: 返回新创建的 ProfileResponse
        异常: ProfileLimitExceededError — 已达上限
        Side Effects: 若为第一份档案则自动设为默认
        """
        await self._validate_under_limit(caregiver_id, session)
        result = await self._do_create_profile(caregiver_id, input_data, session)
        self._validate_created(result)
        return result

    @abstractmethod
    async def _do_create_profile(
        self,
        caregiver_id: "UUID",
        input_data: "ProfileCreate",
        session: AsyncSession,
    ) -> "ProfileResponse":
        """执行档案创建（含首档案默认逻辑）。"""
        ...

    # ======================================================================
    # 更新档案 — PROF-01
    # ======================================================================

    @final
    async def update_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        input_data: "ProfileUpdate",
        session: AsyncSession,
    ) -> "ProfileResponse":
        """更新档案（Merge Patch）。

        前置: profile_id 存在，caregiver_id 拥有该档案
        后置: 返回更新后的 ProfileResponse
        异常: ProfileNotFoundError
        """
        result = await self._do_update_profile(profile_id, caregiver_id, input_data, session)
        if result is None:
            raise ProfileNotFoundError(str(profile_id))
        return result

    @abstractmethod
    async def _do_update_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        input_data: "ProfileUpdate",
        session: AsyncSession,
    ) -> "ProfileResponse | None":
        """执行档案更新。"""
        ...

    # ======================================================================
    # 删除档案 — PROF-01
    # ======================================================================

    @final
    async def delete_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> None:
        """删除档案。

        若删除的是默认档案，自动将最新更新的剩余档案提升为默认。
        前置: profile_id 存在
        后置: 档案已删除，可能已提升新的默认档案
        异常: ProfileNotFoundError
        """
        success = await self._do_delete_profile(profile_id, caregiver_id, session)
        if not success:
            raise ProfileNotFoundError(str(profile_id))

    @abstractmethod
    async def _do_delete_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> bool:
        """执行档案删除。返回 True 表示删除成功。"""
        ...

    # ======================================================================
    # 设为默认 — PROF-01
    # ======================================================================

    @final
    async def set_default_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "ProfileResponse":
        """将指定档案设为默认。

        前置: profile_id 存在且归属 caregiver_id
        后置: 该档案 is_default=True，其他档案 is_default=False
        异常: ProfileNotFoundError
        """
        result = await self._do_set_default_profile(profile_id, caregiver_id, session)
        if result is None:
            raise ProfileNotFoundError(str(profile_id))
        return result

    @abstractmethod
    async def _do_set_default_profile(
        self,
        profile_id: "UUID",
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> "ProfileResponse | None":
        """执行默认档案设置。"""
        ...

    # ======================================================================
    # 校验器 — 子类可通过 super() 叠加业务级校验
    # ======================================================================

    async def _validate_under_limit(
        self,
        caregiver_id: "UUID",
        session: AsyncSession,
    ) -> None:
        """档案数量上限校验——单用户最多 MAX_PROFILES_PER_USER 个档案。

        Raises:
            ProfileLimitExceededError: 已达上限。
        """
        from app.modules.profiles._constants import MAX_PROFILES_PER_USER

        count = await self._repository.count_active_by_caregiver(session, caregiver_id)
        if count >= MAX_PROFILES_PER_USER:
            raise ProfileLimitExceededError(count, MAX_PROFILES_PER_USER)

    @staticmethod
    def _validate_created(result: "ProfileResponse") -> None:
        """后置校验——确保创建结果非空。"""
        if result is None:
            raise RuntimeError("创建档案返回结果异常")


__all__ = ["BaseProfileService"]
