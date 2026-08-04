"""RBAC 显式角色→能力矩阵 — 单元测试（ADR-013 目标态）。

覆盖：
- Capability 能力枚举与 ROLE_CAPABILITIES 矩阵（对照认证与访问 §六）
- DefaultRBACGuard.authorize 显式集合匹配（min_level 数值继承已废除）
- require_roles FastAPI Depends 工厂
- get_masked_phone 字段级脱敏（仅 admin 可见完整手机号）
- has_capability 能力判定
"""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi import HTTPException
from py_auth.auth_contract import RBACGuard
from py_auth.exceptions import PermissionDeniedError
from py_auth.rbac import (
    ROLE_CAPABILITIES,
    Capability,
    DefaultRBACGuard,
    get_masked_phone,
    has_capability,
    require_roles,
)
from py_schemas.auth import UserRole

# ===========================================================================
# Capability 枚举与角色→能力矩阵（认证与访问 §六 逐行对照）
# ===========================================================================


class TestCapabilityMatrix:
    """矩阵即文档——逐角色断言能力集合与机制文档 §六一致。"""

    def test_family_capabilities(self):
        caps = ROLE_CAPABILITIES[UserRole.FAMILY]
        assert caps == frozenset(
            {
                Capability.EMERGENCY_CONSULT,  # 应急咨询/科普
                Capability.PROFILE_OWN,  # 档案（自有家庭全权）
                Capability.TICKET_FAMILY,  # 工单家属侧
            }
        )

    def test_volunteer_capabilities(self):
        caps = ROLE_CAPABILITIES[UserRole.VOLUNTEER]
        assert caps == frozenset(
            {
                Capability.EMERGENCY_CONSULT,  # 应急咨询/科普
                Capability.PROFILE_COLLAB,  # 档案受邀受限
            }
        )

    def test_teacher_capabilities(self):
        caps = ROLE_CAPABILITIES[UserRole.TEACHER]
        assert caps == frozenset(
            {
                Capability.PROFILE_COLLAB,  # 档案受邀共建
                Capability.CASE_CREATE,  # 案例录入
                Capability.TICKET_TEACHER,  # 工单普通/紧急接单
            }
        )

    def test_expert_capabilities(self):
        caps = ROLE_CAPABILITIES[UserRole.EXPERT]
        assert caps == frozenset(
            {
                Capability.PROFILE_COLLAB,  # 档案受邀共建
                Capability.CASE_CREATE,  # 案例录入
                Capability.CASE_REVIEW,  # 案例审核/下架
                Capability.TICKET_EXPERT,  # 工单专家侧（特急仅专家）
            }
        )

    def test_admin_capabilities(self):
        caps = ROLE_CAPABILITIES[UserRole.ADMIN]
        assert caps == frozenset(
            {
                Capability.CASE_FORCE_UNLIST,  # 案例强制下架
                Capability.TICKET_DISPATCH,  # 工单转派
                Capability.PLATFORM_ADMIN,  # 平台管理（用户/准入审核/邀请码）
            }
        )

    def test_maintainer_capabilities(self):
        caps = ROLE_CAPABILITIES[UserRole.MAINTAINER]
        assert caps == frozenset({Capability.SYSTEM_OPS})  # 系统运维

    def test_all_roles_covered(self):
        """矩阵覆盖全部六角色，不允许表外角色。"""
        assert set(ROLE_CAPABILITIES.keys()) == set(UserRole)

    def test_no_implicit_inheritance(self):
        """无数值层级隐式继承——admin 不自动拥有 family 的应急咨询能力。"""
        assert Capability.EMERGENCY_CONSULT not in ROLE_CAPABILITIES[UserRole.ADMIN]
        assert Capability.CASE_CREATE not in ROLE_CAPABILITIES[UserRole.ADMIN]
        assert Capability.PLATFORM_ADMIN not in ROLE_CAPABILITIES[UserRole.EXPERT]


class TestHasCapability:
    def test_hit(self):
        assert has_capability(UserRole.EXPERT, Capability.CASE_REVIEW) is True

    def test_miss(self):
        assert has_capability(UserRole.TEACHER, Capability.CASE_REVIEW) is False


# ===========================================================================
# DefaultRBACGuard — 显式集合匹配
# ===========================================================================


class _FakeUser:
    def __init__(self, roles: list[UserRole], user_id: str = "user-1"):
        self.roles = roles
        self.id = user_id


class TestRBACGuardContract:
    def test_no_min_level_param(self):
        """min_level 数值继承语义已废除——authorize 不再接受该参数。"""
        guard = DefaultRBACGuard()
        with pytest.raises(TypeError):
            guard.authorize(_FakeUser([UserRole.ADMIN]), min_level=UserRole.ADMIN)

    def test_exact_roles_pass(self):
        guard = DefaultRBACGuard()
        guard.authorize(_FakeUser([UserRole.EXPERT]), exact_roles=[UserRole.EXPERT, UserRole.ADMIN])

    def test_exact_roles_denied(self):
        guard = DefaultRBACGuard()
        with pytest.raises(PermissionDeniedError) as exc:
            guard.authorize(_FakeUser([UserRole.FAMILY]), exact_roles=[UserRole.ADMIN])
        assert exc.value.reason == "permission_denied"

    def test_user_missing(self):
        guard = DefaultRBACGuard()
        with pytest.raises(PermissionDeniedError) as exc:
            guard.authorize(None, exact_roles=[UserRole.ADMIN])
        assert exc.value.reason == "user_missing"

    def test_empty_roles(self):
        guard = DefaultRBACGuard()
        with pytest.raises(PermissionDeniedError) as exc:
            guard.authorize(_FakeUser([]), exact_roles=[UserRole.ADMIN])
        assert exc.value.reason == "no_roles"

    def test_default_deny_when_no_requirement(self):
        """未指定任何要求时默认放行（任何已认证用户）。"""
        guard = DefaultRBACGuard()
        guard.authorize(_FakeUser([UserRole.FAMILY]))

    def test_guard_implements_contract(self):
        assert isinstance(DefaultRBACGuard(), RBACGuard)


# ===========================================================================
# require_roles — FastAPI Depends 工厂
# ===========================================================================


def _fake_request(user=None):
    req = mock.MagicMock()
    if user is not None:
        req.state.user = user
    else:
        req.state.user = None
    return req


class TestRequireRoles:
    @pytest.mark.asyncio
    async def test_in_whitelist_passes(self):
        checker = require_roles(UserRole.EXPERT, UserRole.ADMIN)
        req = _fake_request(user=_FakeUser([UserRole.EXPERT]))
        assert await checker(req) is None

    @pytest.mark.asyncio
    async def test_not_in_whitelist_403(self):
        checker = require_roles(UserRole.ADMIN)
        req = _fake_request(user=_FakeUser([UserRole.FAMILY]))
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_user_401(self):
        checker = require_roles(UserRole.ADMIN)
        req = _fake_request(user=None)
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_roles_401(self):
        checker = require_roles(UserRole.ADMIN)
        req = _fake_request(user=_FakeUser([]))
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 401

    def test_empty_required_roles_raises(self):
        """必须显式声明角色集合——空调用是编程错误。"""
        with pytest.raises(ValueError):
            require_roles()


# ===========================================================================
# get_masked_phone — 字段级脱敏（NFR：手机号仅管理员可见）
# ===========================================================================


class TestGetMaskedPhone:
    def test_admin_sees_full_phone(self):
        assert get_masked_phone("13800138000", [UserRole.ADMIN]) == "13800138000"

    def test_maintainer_sees_masked(self):
        """maintainer 无业务数据权限（认证与访问 §3.1），同见脱敏。"""
        assert get_masked_phone("13800138000", [UserRole.MAINTAINER]) == "138****8000"

    def test_family_sees_masked(self):
        assert get_masked_phone("13800138000", [UserRole.FAMILY]) == "138****8000"

    def test_expert_sees_masked(self):
        assert get_masked_phone("13800138000", [UserRole.EXPERT]) == "138****8000"

    def test_none_phone_fallback(self):
        assert get_masked_phone(None, [UserRole.ADMIN]) == "****"

    def test_empty_roles_masked(self):
        assert get_masked_phone("13800138000", []) == "138****8000"

    def test_malformed_phone_fallback(self):
        assert get_masked_phone("123", [UserRole.FAMILY]) == "****"
