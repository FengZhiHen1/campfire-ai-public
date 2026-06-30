# @contract
"""用户认证与授权 — Pydantic Schema 定义。

提供全平台共享的 UserRole 枚举（含 level/display_name 属性）、
PermissionDeniedResponse 响应模型（AUTH-04）、
RegisterRequest / RegisterResponse（AUTH-01 用户注册）。

UserRole 枚举值统一使用英文小写，JWT payload、数据库、Python 代码
中统一使用英文枚举值。中文名仅通过 display_name 属性在序列化层映射。

契约引用：
- UserRole: docs/contracts/AUTH-01/UserRole.json（注册阶段仅开放前三角色）；
            docs/contracts/AUTH-04/UserRole.json（完整五级角色）
- RegisterRequest: docs/contracts/AUTH-01/RegisterRequest.json
- RegisterResponse: docs/contracts/AUTH-01/RegisterResponse.json
- PermissionDeniedResponse: docs/contracts/AUTH-04/PermissionDeniedResponse.json
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from py_schemas.base import CampfireBaseModel


class UserRole(StrEnum):
    """五级 RBAC 角色枚举。

    角色层级映射（数值越大权限越高）：
    - FAMILY = 1（家属）
    - TEACHER = 2（老师）
    - EXPERT = 3（专家）
    - ADMIN = 4（管理员）
    - MAINTAINER = 5（维护人员）

    Python 实现为 str + Enum，可直接用于 Pydantic 模型字段校验、
    FastAPI 路径参数和 Depends 注入。
    """

    FAMILY = "family"
    TEACHER = "teacher"
    EXPERT = "expert"
    ADMIN = "admin"
    MAINTAINER = "maintainer"

    @property
    def level(self) -> int:
        """角色的权限层级数值（1-5），数值越大权限越高。

        用途：
        - 层级累加模式鉴权：用户最高角色层级 >= 目标资源层级时放行
        - 字段级脱敏判定：level >= 4（admin/maintainer）可见完整手机号
        """
        return _LEVEL_MAP[self]

    @property
    def display_name(self) -> str:
        """角色的中文显示名（仅供 UI 展示和序列化层使用）。

        禁止在 JWT payload 或数据库中使用中文角色值，
        统一使用英文枚举值，中文名仅在此属性中映射。
        """
        return _DISPLAY_NAME_MAP[self]


# ---------------------------------------------------------------------------
# 内部映射表（模块级常量）
# ---------------------------------------------------------------------------

_LEVEL_MAP: dict[UserRole, int] = {
    UserRole.FAMILY: 1,
    UserRole.TEACHER: 2,
    UserRole.EXPERT: 3,
    UserRole.ADMIN: 4,
    UserRole.MAINTAINER: 5,
}

_DISPLAY_NAME_MAP: dict[UserRole, str] = {
    UserRole.FAMILY: "家属",
    UserRole.TEACHER: "老师",
    UserRole.EXPERT: "专家",
    UserRole.ADMIN: "管理员",
    UserRole.MAINTAINER: "维护人员",
}


# ===========================================================================
# AUTH-01 用户注册 — 请求/响应模型
# ===========================================================================


class RegisterRequest(CampfireBaseModel):
    """用户注册请求体。

    与 docs/contracts/AUTH-01/RegisterRequest.json 契约一致。
    接收用户提交的用户名、密码、角色类型、手机号和真实姓名，
    经 Pydantic 校验后进入注册流程。

    role 字段使用全平台共享的 UserRole 枚举，但注册阶段仅开放
    family/teacher/expert 三种角色——admin 和 maintainer 通过
    AUTH-04 管理员操作后分配。

    real_name 在 JSON Schema 中是 required 但 nullable——
    Pydantic 中以 str | None = Field(default=None, ...) 表达，
    即字段可省略（默认 None），也可传入 null 或合法字符串。
    """

    username: str = Field(
        ...,
        min_length=4,
        max_length=32,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="登录名称，全局唯一。长度 4-32 字符，仅允许字母、数字、下划线和连字符。",
    )
    password: str = Field(
        ...,
        min_length=8,
        description="登录凭证，至少 8 位。复杂度校验（大小写+数字）由 Service 层执行。",
    )
    role: UserRole = Field(
        ...,
        description="用户身份分类。注册时仅允许 family/teacher/expert。",
    )
    phone: str = Field(
        ...,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        description="中国大陆 11 位手机号，全局唯一。",
    )
    real_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=20,
        description="真实姓名。家属和老师可选填，专家必填。",
    )

    @field_validator("role")
    @classmethod
    def role_must_be_registrable(cls, v: UserRole) -> UserRole:
        """注册阶段仅开放 family/teacher/expert 三种角色。

        admin 和 maintainer 通过 AUTH-04 管理员操作后分配，
        不可通过注册接口直接获取。
        """
        if v not in (UserRole.FAMILY, UserRole.TEACHER, UserRole.EXPERT):
            raise ValueError(f"注册阶段仅允许 family/teacher/expert 角色，当前值为 {v.value}")
        return v


class RegisterResponse(CampfireBaseModel):
    """用户注册成功响应体。

    与 docs/contracts/AUTH-01/RegisterResponse.json 契约一致。
    注册成功时返回 201 Created，包含固定结果标识和全局唯一 UUID。
    不包含 JWT Token（JWT 签发归属 AUTH-02）。
    """

    result: Literal["success"] = Field(
        default="success",
        description="注册结果，成功时固定为 'success'。",
    )
    user_id: str = Field(
        ...,
        description="系统为用户生成的全局唯一标识（UUIDv4），36 字符标准形式。",
    )
    message: str = Field(
        default="注册成功",
        description="面向用户的可读提示信息。",
    )


# ===========================================================================
# AUTH-04 — 响应模型
# ===========================================================================


class PermissionDeniedResponse(CampfireBaseModel):
    """权限拒绝响应模型。

    当 require_role 校验不通过时返回 HTTP 403 及此响应体。

    约束（信息最小化原则）：
    1. 禁止在响应中返回 expected_role、required_level 等权限规则细节
    2. 格式与 KNOW-01、SEC-01、SEC-05 的统一错误格式一致：{"detail": "错误说明"}
    3. 仅含 detail 字段，无 additional 字段（additionalProperties: false）
    """

    detail: str = Field(
        ...,
        description="拒绝原因说明。仅告知无权限事实，不透露权限规则细节。",
        examples=["当前角色无权执行此操作，如需权限请联系管理员"],
    )


# ===========================================================================
# AUTH-02/03 — 登录/续期请求响应模型
# ===========================================================================


class LoginRequest(CampfireBaseModel):
    """登录请求体。

    username: 登录名称，4-32 字符。
    password: 登录凭证，至少 8 位。
    """

    username: str = Field(..., min_length=4, max_length=32)
    password: str = Field(..., min_length=8)


class TokenResponse(CampfireBaseModel):
    """认证令牌响应体。

    登录成功或续期成功时返回。
    access_token 有效期 15 分钟，refresh_token 有效期 7 天。
    """

    access_token: str = Field(..., description="JWT 访问令牌，15 分钟有效")
    refresh_token: str = Field(..., description="JWT 续期令牌，7 天有效")
    token_type: Literal["Bearer"] = Field(default="Bearer")


class RefreshRequest(CampfireBaseModel):
    """续期请求体。

    携带当前 Refresh Token 以换取新的 Token 对。
    """

    refresh_token: str = Field(..., description="当前的续期令牌")


__all__ = [
    "UserRole",
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    "RegisterRequest",
    "RegisterResponse",
    "PermissionDeniedResponse",
]
