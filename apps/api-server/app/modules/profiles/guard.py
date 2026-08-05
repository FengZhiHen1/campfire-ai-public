"""档案访问控制守卫（隐私与权限 §1.1/§1.2）。

访问矩阵（数据级授权——认证与访问 §六矩阵的模块侧落地）：
- 家属（caregiver 本人）：全权（创建/编辑/删除/关联管理）
- 关联老师/专家：查看档案/事件 + 挂载专业评估（不可改家属内容）
- 受邀志愿者：查看受邀档案 + 新增事件（不管理标签、不邀请他人）
- 其他用户：无权限（存在性隐藏，统一 404）
- 解除关联：立即失去全部访问入口

隐私纪律：档案数据绝不入向量索引；查询强制 profile_id 隔离。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from py_db.models.profiles import Profile
from py_db.repositories.profile_repository import ProfileAccessRepository, ProfileRepository
from py_schemas.enums import AccessRole
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import CurrentUser
from app.modules.profiles.exceptions import ProfileNotFoundError


@dataclass(frozen=True)
class ProfileAccessContext:
    """访问判定结果上下文。"""

    profile: Profile
    is_owner: bool
    access_role: AccessRole | None  # 关联者角色（owner 为 None）

    @property
    def can_edit_profile(self) -> bool:
        """仅家属可编辑档案主体。"""
        return self.is_owner

    @property
    def can_create_event(self) -> bool:
        """家属 + 受邀志愿者可新增事件（老师/专家以 Professional Note 表达）。"""
        return self.is_owner or self.access_role == AccessRole.VOLUNTEER

    @property
    def can_add_note(self) -> bool:
        """老师/专家可挂载专业评估。"""
        return self.is_owner is False and self.access_role in (AccessRole.TEACHER, AccessRole.EXPERT)

    @property
    def can_manage_access(self) -> bool:
        """仅家属可管理关联。"""
        return self.is_owner

    @property
    def can_view_medication(self) -> bool:
        """用药记录仅家属和老师可见（数据模型 §3）。"""
        return self.is_owner or self.access_role == AccessRole.TEACHER


async def require_profile_access(
    session: AsyncSession,
    profile_id: str,
    user: CurrentUser,
    profile_repo: ProfileRepository,
    access_repo: ProfileAccessRepository,
) -> ProfileAccessContext:
    """访问控制判定（所有档案数据入口的统一守卫）。

    Returns:
        ProfileAccessContext（含档案实体与角色能力视图）。

    Raises:
        ProfileNotFoundError: 档案不存在或无权访问（统一 404，存在性隐藏）。
    """
    try:
        pid = uuid.UUID(profile_id)
        uid = uuid.UUID(user.user_id)
    except (ValueError, AttributeError):
        raise ProfileNotFoundError() from None

    profile = await profile_repo.get_by_id(session, pid)
    if profile is None:
        raise ProfileNotFoundError()

    # 家属本人：全权
    if profile.caregiver_id == uid:
        return ProfileAccessContext(profile=profile, is_owner=True, access_role=None)

    # 受邀协作方：活跃关联判定
    access = await access_repo.find_active(session, pid, uid)
    if access is None:
        raise ProfileNotFoundError()
    return ProfileAccessContext(profile=profile, is_owner=False, access_role=access.role)


__all__ = ["ProfileAccessContext", "require_profile_access"]
