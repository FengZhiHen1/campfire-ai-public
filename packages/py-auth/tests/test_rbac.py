"""AUTH-04 RBAC — require_role / get_masked_phone / PrivacyGuard 单元测试。"""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi import HTTPException
from py_auth.rbac import PrivacyGuard, get_masked_phone, require_role
from py_schemas.auth import UserRole

# ---- require_role ----


class _FakeUser:
    def __init__(self, roles: list[UserRole], user_id: str = "user-1"):
        self.roles = roles
        self.id = user_id


def _fake_request(user=None):
    req = mock.MagicMock()
    if user is not None:
        req.state.user = user
    return req


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_family_user_with_min_level_family(self):
        """family 用户应该能通过 min_level=UserRole.FAMILY 检查。"""
        checker = require_role(min_level=UserRole.FAMILY)
        user = _FakeUser([UserRole.FAMILY])
        req = _fake_request(user=user)
        result = await checker(req)
        assert result is None  # pass

    @pytest.mark.asyncio
    async def test_family_user_blocked_by_min_level_admin(self):
        """family 用户无法通过 min_level=UserRole.ADMIN 检查。"""
        checker = require_role(min_level=UserRole.ADMIN)
        user = _FakeUser([UserRole.FAMILY])
        req = _fake_request(user=user)
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_exact_role_whitelist(self):
        """精确角色白名单检查。"""
        checker = require_role(exact_roles=[UserRole.EXPERT, UserRole.ADMIN])
        user = _FakeUser([UserRole.EXPERT])
        req = _fake_request(user=user)
        result = await checker(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_exact_role_not_in_whitelist(self):
        """用户角色不在白名单中应返回 403。"""
        checker = require_role(exact_roles=[UserRole.ADMIN])
        user = _FakeUser([UserRole.FAMILY])
        req = _fake_request(user=user)
        with pytest.raises(HTTPException, match="403"):
            await checker(req)

    @pytest.mark.asyncio
    async def test_no_user_on_request(self):
        """无用户信息应返回 401。"""
        checker = require_role(min_level=UserRole.FAMILY)
        req = _fake_request(user=None)
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_roles(self):
        """空角色列表应返回 401。"""
        checker = require_role(min_level=UserRole.FAMILY)
        user = _FakeUser([])
        req = _fake_request(user=user)
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_request_state(self):
        """请求无 state 属性应返回 401。"""
        checker = require_role(min_level=UserRole.FAMILY)
        req = mock.MagicMock(spec=[])  # no state attr
        with pytest.raises(HTTPException) as exc:
            await checker(req)
        assert exc.value.status_code == 401

    def test_mutual_exclusion(self):
        with pytest.raises(ValueError, match="不能同时使用"):
            require_role(min_level=UserRole.FAMILY, exact_roles=[UserRole.FAMILY])

    @pytest.mark.asyncio
    async def test_no_params_allows_any_authenticated(self):
        """无参数时任何已认证用户均可通过。"""
        checker = require_role()
        user = _FakeUser([UserRole.FAMILY])
        req = _fake_request(user=user)
        result = await checker(req)
        assert result is None


# ---- get_masked_phone ----


class TestGetMaskedPhone:
    def test_admin_sees_full_phone(self):
        result = get_masked_phone("13800138000", [UserRole.ADMIN])
        assert result == "13800138000"

    def test_maintainer_sees_full_phone(self):
        result = get_masked_phone("13800138000", [UserRole.MAINTAINER])
        assert result == "13800138000"

    def test_family_sees_masked_phone(self):
        result = get_masked_phone("13800138000", [UserRole.FAMILY])
        assert result == "138****8000"

    def test_teacher_sees_masked_phone(self):
        result = get_masked_phone("13800138000", [UserRole.TEACHER])
        assert result == "138****8000"

    def test_none_phone_returns_fallback(self):
        result = get_masked_phone(None, [UserRole.ADMIN])  # type: ignore[arg-type]
        assert result == "****"

    def test_empty_roles_returns_masked(self):
        result = get_masked_phone("13800138000", [])
        assert result == "138****8000"

    def test_invalid_phone_returns_fallback(self):
        result = get_masked_phone("12345", [UserRole.FAMILY])
        assert result == "****"

    def test_non_standard_length_returns_fallback(self):
        result = get_masked_phone("1234567890", [UserRole.FAMILY])  # 10 digits
        assert result == "****"

    def test_phone_with_spaces(self):
        result = get_masked_phone(" 13800138000 ", [UserRole.FAMILY])
        assert result == "138****8000"


# ---- PrivacyGuard ----


class TestPrivacyGuard:
    @pytest.mark.asyncio
    async def test_check_access_allows_all(self):
        decision = await PrivacyGuard.check_access(mock.MagicMock(), mock.MagicMock())
        assert decision.allowed is True
        assert decision.visible_scope == "all_fields"
