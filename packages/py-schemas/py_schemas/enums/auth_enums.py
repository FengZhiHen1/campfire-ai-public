# @contract
"""认证域枚举定义（ADR-013 目标态）。

集中定义认证体系的枚举：
- AccountStatus: 账号状态机（active/pending_review/rejected/disabled）
- InviteCodeStatus: 邀请码状态（active/revoked）
- InviteChannel: 邀请码渠道（demand/supply，约束可注册角色）
- CredentialType: 凭证渠道类型（password/wechat 预留）

机制事实唯一所有者：docs/技术设计/机制/认证与访问.md §2/§3/§4。
"""

from __future__ import annotations

from enum import StrEnum


class AccountStatus(StrEnum):
    """账号状态机（认证与访问 §3.2）。

    - ACTIVE: 正常可用
    - PENDING_REVIEW: 待审核（teacher/expert 注册后置态，可登录仅见状态页）
    - REJECTED: 审核驳回（可登录查看原因并补交材料重提）
    - DISABLED: 管理员禁用（所有凭证即签即拒，refresh 家族吊销）
    """

    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    DISABLED = "disabled"

    @property
    def display_name(self) -> str:
        """中文显示名（仅供 UI 展示层使用）。"""
        return _ACCOUNT_STATUS_DISPLAY[self]


_ACCOUNT_STATUS_DISPLAY: dict[AccountStatus, str] = {
    AccountStatus.ACTIVE: "正常",
    AccountStatus.PENDING_REVIEW: "审核中",
    AccountStatus.REJECTED: "已驳回",
    AccountStatus.DISABLED: "已禁用",
}


class InviteCodeStatus(StrEnum):
    """邀请码状态（认证与访问 §4.1）。"""

    ACTIVE = "active"
    REVOKED = "revoked"


class InviteChannel(StrEnum):
    """邀请码渠道（认证与访问 §4.1）。

    - DEMAND: 需求侧渠道，可注册 family/volunteer
    - SUPPLY: 供给侧渠道，可注册 teacher/expert
    """

    DEMAND = "demand"
    SUPPLY = "supply"


class CredentialType(StrEnum):
    """凭证渠道类型（认证与访问 §2.1）。

    - PASSWORD: 手机号 + 密码（内测期唯一渠道）
    - WECHAT: 微信 code2session（预留，微信开放平台认证完成后落地）
    """

    PASSWORD = "password"
    WECHAT = "wechat"


__all__ = [
    "AccountStatus",
    "InviteCodeStatus",
    "InviteChannel",
    "CredentialType",
]
