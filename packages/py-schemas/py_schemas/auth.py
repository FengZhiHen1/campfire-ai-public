# @contract
"""用户认证与授权 — Pydantic Schema 定义（ADR-013 目标态）。

提供全平台共享的认证契约：
- UserRole 六角色枚举（family/volunteer/teacher/expert/admin/maintainer，单角色互斥）
- 注册/登录/刷新/登出/me DTO（手机号登录标识 + 邀请码 + 准入状态）
- 准入审核 DTO（待审列表/通过/驳回含原因/补交材料重提）
- 邀请码管理 DTO（生成含批量/列表/停用）

事实源：docs/技术设计/机制/认证与访问.md（本文不复制其状态机与矩阵语义，
仅落地数据契约）。已废除：username 登录标识、device_id 匿名轨、
UserRole.level 数值继承（改显式角色→能力映射，守卫实现见 py-auth）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from py_schemas.base import CampfireBaseModel
from py_schemas.enums import AccountStatus, InviteChannel, InviteCodeStatus


class UserRole(StrEnum):
    """六角色枚举（单角色互斥，认证与访问 §3.1）。

    显式角色→能力映射取代数值层级继承，角色不再携带 level 语义。
    JWT payload、数据库、Python 代码中统一使用英文枚举值；
    中文名仅通过 display_name 属性在展示层映射。
    """

    FAMILY = "family"
    VOLUNTEER = "volunteer"
    TEACHER = "teacher"
    EXPERT = "expert"
    ADMIN = "admin"
    MAINTAINER = "maintainer"

    @property
    def display_name(self) -> str:
        """角色的中文显示名（仅供 UI 展示和序列化层使用）。"""
        return _DISPLAY_NAME_MAP[self]


_DISPLAY_NAME_MAP: dict[UserRole, str] = {
    UserRole.FAMILY: "家属",
    UserRole.VOLUNTEER: "志愿者",
    UserRole.TEACHER: "老师",
    UserRole.EXPERT: "专家",
    UserRole.ADMIN: "管理员",
    UserRole.MAINTAINER: "维护人员",
}


# ---------------------------------------------------------------------------
# 邀请码 channel → 可注册角色约束（认证与访问 §4.1）
# ---------------------------------------------------------------------------

CHANNEL_ALLOWED_ROLES: dict[InviteChannel, frozenset[UserRole]] = {
    InviteChannel.DEMAND: frozenset({UserRole.FAMILY, UserRole.VOLUNTEER}),
    InviteChannel.SUPPLY: frozenset({UserRole.TEACHER, UserRole.EXPERT}),
}
"""demand 渠道仅可注册家属/志愿者，supply 渠道仅可注册老师/专家。"""

# 注册开放的角色集合（admin/maintainer 由既有 admin 分配，不开放注册）
REGISTRABLE_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.FAMILY, UserRole.VOLUNTEER, UserRole.TEACHER, UserRole.EXPERT}
)

# 注册后进入准入审核（pending_review）的角色集合
REVIEW_REQUIRED_ROLES: frozenset[UserRole] = frozenset({UserRole.TEACHER, UserRole.EXPERT})


# ===========================================================================
# 注册 / 登录 / Token
# ===========================================================================


class RegisterRequest(CampfireBaseModel):
    """用户注册请求体（认证与访问 §4.2）。

    提交：手机号 + 密码 + 邀请码 + 角色（受码 channel 约束）+ real_name。
    邀请码有效性校验与 channel 约束在 Service 层执行；
    real_name 对 teacher/expert 必填的条件校验同样在 Service 层执行
    （与密码复杂度校验同一层，沿用现状分层语义）。
    """

    phone: str = Field(
        ...,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="中国大陆 11 位手机号，全局唯一登录标识与账号合并锚点。",
    )
    password: str = Field(
        ...,
        min_length=8,
        description="登录凭证，至少 8 位。复杂度校验（大小写+数字）由 Service 层执行。",
    )
    invite_code: str = Field(
        ...,
        min_length=8,
        max_length=12,
        description="邀请码（8-12 位可读码），channel 约束可注册角色。",
    )
    role: UserRole = Field(
        ...,
        description="用户身份分类。注册时仅允许 family/volunteer/teacher/expert。",
    )
    real_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=20,
        description="真实姓名。teacher/expert 必填（准入审核依据），其余可选。",
    )

    @field_validator("role")
    @classmethod
    def role_must_be_registrable(cls, v: UserRole) -> UserRole:
        """注册阶段仅开放 family/volunteer/teacher/expert 四种角色。

        admin 和 maintainer 由既有 admin 在管理端分配，不开放注册。
        """
        if v not in REGISTRABLE_ROLES:
            raise ValueError(f"注册阶段仅允许 family/volunteer/teacher/expert 角色，当前值为 {v.value}")
        return v


class RegisterResponse(CampfireBaseModel):
    """用户注册成功响应体。

    注册不自动登录，引导至登录页；status 告知前端账号落态
    （teacher/expert 为 pending_review，其余为 active）。
    """

    result: Literal["success"] = Field(
        default="success",
        description="注册结果，成功时固定为 'success'。",
    )
    user_id: str = Field(
        ...,
        description="系统为用户生成的全局唯一标识（UUIDv4），36 字符标准形式。",
    )
    status: AccountStatus = Field(
        default=AccountStatus.ACTIVE,
        description="注册后账号落态：active 直接可用；pending_review 等待管理员审核。",
    )
    message: str = Field(
        default="注册成功",
        description="面向用户的可读提示信息。",
    )


class LoginRequest(CampfireBaseModel):
    """登录请求体（手机号 + 密码，认证与访问 §4.3）。"""

    phone: str = Field(
        ...,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="中国大陆 11 位手机号。",
    )
    password: str = Field(..., min_length=8, description="登录凭证，至少 8 位。")


class TokenResponse(CampfireBaseModel):
    """认证令牌响应体。

    access_token 有效期 15 分钟，refresh_token 有效期 7 天（单次使用 + 轮换）。
    """

    access_token: str = Field(..., description="JWT 访问令牌，15 分钟有效")
    refresh_token: str = Field(..., description="JWT 续期令牌，7 天有效，单次使用")
    token_type: Literal["Bearer"] = Field(default="Bearer")


class RefreshRequest(CampfireBaseModel):
    """续期请求体。携带当前 Refresh Token 以换取新的 Token 对。"""

    refresh_token: str = Field(..., description="当前的续期令牌")


class MeResponse(CampfireBaseModel):
    """当前用户信息响应（GET /api/v1/auth/me）。

    返回本人手机号完整值（字段级脱敏约束的是查看他人手机号，见认证与访问 §六）。
    """

    user_id: str = Field(..., description="用户 UUID")
    phone: str = Field(..., description="本人手机号（完整值）")
    real_name: str | None = Field(..., description="真实姓名（可空）")
    role: UserRole = Field(..., description="角色")
    status: AccountStatus = Field(..., description="账号状态")


# ===========================================================================
# 准入审核 DTO（admin）
# ===========================================================================


class ReviewListItem(CampfireBaseModel):
    """准入审核列表项——待审/已驳回的 teacher/expert 账号。"""

    user_id: str = Field(..., description="用户 UUID")
    phone: str = Field(..., description="手机号（管理员可见完整值）")
    real_name: str | None = Field(..., description="真实姓名")
    role: UserRole = Field(..., description="申请角色（teacher/expert）")
    status: AccountStatus = Field(..., description="当前账号状态")
    reject_reason: str | None = Field(default=None, description="最近一次驳回原因（rejected 时非空）")
    created_at: str = Field(..., description="注册时间（ISO 8601）")


class ReviewListResponse(CampfireBaseModel):
    """准入审核列表响应。"""

    items: list[ReviewListItem] = Field(default_factory=list)
    total: int = Field(..., ge=0, description="符合条件的记录总数")


class ReviewApproveResponse(CampfireBaseModel):
    """审核通过响应——账号置为 active。"""

    user_id: str
    status: AccountStatus = Field(default=AccountStatus.ACTIVE)
    message: str = Field(default="审核通过")


class ReviewRejectRequest(CampfireBaseModel):
    """审核驳回请求——必须给出面向用户的驳回原因。"""

    reason: str = Field(..., min_length=1, max_length=200, description="驳回原因（展示给用户，供补交材料参考）")


class ReviewResubmitRequest(CampfireBaseModel):
    """驳回后补交材料重提请求（rejected → pending_review）。

    资质材料未独立建模（认证与访问 §2.1 身份模型无资质字段），
    本期补交语义 = 可选更正 real_name 后重新进入待审队列。
    """

    real_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=20,
        description="更正后的真实姓名（可选）",
    )


# ===========================================================================
# 邀请码管理 DTO（admin）
# ===========================================================================


class InviteCodeCreateRequest(CampfireBaseModel):
    """邀请码生成请求（认证与访问 §4.1）。

    count > 1 时为机构批量邀请场景：批量生成 max_uses=1 的单次码。
    """

    channel: InviteChannel = Field(..., description="渠道：demand 需求侧 / supply 供给侧")
    max_uses: int = Field(default=1, ge=1, le=1000, description="单码可用次数，默认 1")
    count: int = Field(default=1, ge=1, le=100, description="生成数量（批量场景按人数生成单次码）")
    expires_at: str = Field(..., description="过期时间（ISO 8601，必填）")


class InviteCodeCreateResponse(CampfireBaseModel):
    """邀请码生成响应——返回本次生成的全部码串。"""

    codes: list[str] = Field(..., description="生成的邀请码列表")


class InviteCodeItem(CampfireBaseModel):
    """邀请码列表项。"""

    code: str
    channel: InviteChannel
    max_uses: int = Field(..., ge=1)
    used_count: int = Field(..., ge=0)
    expires_at: str = Field(..., description="过期时间（ISO 8601）")
    status: InviteCodeStatus
    created_by: str = Field(..., description="生成的管理员用户 UUID")
    created_at: str = Field(..., description="生成时间（ISO 8601）")


class InviteCodeListResponse(CampfireBaseModel):
    """邀请码列表响应。"""

    items: list[InviteCodeItem] = Field(default_factory=list)
    total: int = Field(..., ge=0)


# ===========================================================================
# 权限拒绝响应（沿用）
# ===========================================================================


class PermissionDeniedResponse(CampfireBaseModel):
    """权限拒绝响应模型（信息最小化原则）。

    禁止在响应中返回权限规则细节；仅含 detail 字段。
    """

    detail: str = Field(
        ...,
        description="拒绝原因说明。仅告知无权限事实，不透露权限规则细节。",
        examples=["当前角色无权执行此操作，如需权限请联系管理员"],
    )


__all__ = [
    # 枚举与映射
    "UserRole",
    "CHANNEL_ALLOWED_ROLES",
    "REGISTRABLE_ROLES",
    "REVIEW_REQUIRED_ROLES",
    # 注册/登录/Token
    "RegisterRequest",
    "RegisterResponse",
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    "MeResponse",
    # 准入审核
    "ReviewListItem",
    "ReviewListResponse",
    "ReviewApproveResponse",
    "ReviewRejectRequest",
    "ReviewResubmitRequest",
    # 邀请码
    "InviteCodeCreateRequest",
    "InviteCodeCreateResponse",
    "InviteCodeItem",
    "InviteCodeListResponse",
    # 权限
    "PermissionDeniedResponse",
]
