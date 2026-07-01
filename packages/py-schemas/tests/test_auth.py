"""AUTH-01 用户注册 & AUTH-02/03/04 认证 — Pydantic Schema 单元测试。

覆盖 RegisterRequest、RegisterResponse、LoginRequest、TokenResponse、
RefreshRequest、PermissionDeniedResponse、UserRole。
"""

from __future__ import annotations

import pytest
from py_schemas.auth import (
    LoginRequest,
    PermissionDeniedResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserRole,
)
from pydantic import ValidationError

# ===========================================================================
# UserRole
# ===========================================================================


class TestUserRole:
    def test_all_roles_exist(self):
        assert UserRole.FAMILY == "family"
        assert UserRole.TEACHER == "teacher"
        assert UserRole.EXPERT == "expert"
        assert UserRole.ADMIN == "admin"
        assert UserRole.MAINTAINER == "maintainer"

    def test_level_values(self):
        assert UserRole.FAMILY.level == 1
        assert UserRole.TEACHER.level == 2
        assert UserRole.EXPERT.level == 3
        assert UserRole.ADMIN.level == 4
        assert UserRole.MAINTAINER.level == 5

    def test_display_names(self):
        assert UserRole.FAMILY.display_name == "家属"
        assert UserRole.TEACHER.display_name == "老师"
        assert UserRole.EXPERT.display_name == "专家"
        assert UserRole.ADMIN.display_name == "管理员"
        assert UserRole.MAINTAINER.display_name == "维护人员"

    def test_level_ordering(self):
        assert UserRole.FAMILY.level < UserRole.TEACHER.level
        assert UserRole.TEACHER.level < UserRole.EXPERT.level
        assert UserRole.EXPERT.level < UserRole.ADMIN.level
        assert UserRole.ADMIN.level < UserRole.MAINTAINER.level


# ===========================================================================
# RegisterRequest
# ===========================================================================


def _valid_register_data(**overrides):
    data = {
        "username": "test_user",
        "password": "Abcdefg1",
        "role": "family",
        "phone": "13800138000",
    }
    data.update(overrides)
    return data


class TestRegisterRequest:
    def test_valid_minimal(self):
        req = RegisterRequest(**_valid_register_data())
        assert req.username == "test_user"
        assert req.role == UserRole.FAMILY

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(username="ab"))

    def test_username_too_long(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(username="a" * 33))

    def test_username_invalid_chars(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(username="user@name"))

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(password="Abc12"))

    def test_phone_invalid_format(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(phone="12345678901"))

    def test_phone_wrong_length(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(phone="1380013800"))

    def test_role_admin_not_allowed(self):
        with pytest.raises(ValidationError) as exc:
            RegisterRequest(**_valid_register_data(role="admin"))
        assert "仅允许" in str(exc.value)

    def test_role_maintainer_not_allowed(self):
        with pytest.raises(ValidationError) as exc:
            RegisterRequest(**_valid_register_data(role="maintainer"))
        assert "仅允许" in str(exc.value)

    def test_role_family_allowed(self):
        req = RegisterRequest(**_valid_register_data(role="family"))
        assert req.role == UserRole.FAMILY

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(), extra_field="bad")

    def test_real_name_optional(self):
        req = RegisterRequest(**_valid_register_data())
        assert req.real_name is None

    def test_real_name_valid(self):
        req = RegisterRequest(**_valid_register_data(), real_name="张三")
        assert req.real_name == "张三"

    def test_real_name_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(), real_name="张")


# ===========================================================================
# RegisterResponse
# ===========================================================================


class TestRegisterResponse:
    def test_valid_response(self):
        resp = RegisterResponse(result="success", user_id="550e8400-e29b-41d4-a716-446655440000")
        assert resp.result == "success"
        assert resp.message == "注册成功"

    def test_missing_user_id(self):
        with pytest.raises(ValidationError):
            RegisterResponse(result="success")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            RegisterResponse(
                result="success",
                user_id="550e8400-e29b-41d4-a716-446655440000",
                token="x",
            )


# ===========================================================================
# LoginRequest / TokenResponse / RefreshRequest
# ===========================================================================


class TestLoginRequest:
    def test_valid(self):
        req = LoginRequest(username="test_user", password="Abcdefg1")
        assert req.username == "test_user"

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="ab", password="Abcdefg1")

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="test_user", password="short")


class TestTokenResponse:
    def test_valid(self):
        resp = TokenResponse(access_token="at", refresh_token="rt")
        assert resp.token_type == "Bearer"

    def test_missing_access_token(self):
        with pytest.raises(ValidationError):
            TokenResponse(refresh_token="rt")


class TestRefreshRequest:
    def test_valid(self):
        req = RefreshRequest(refresh_token="token123")
        assert req.refresh_token == "token123"

    def test_missing_token(self):
        with pytest.raises(ValidationError):
            RefreshRequest()


# ===========================================================================
# PermissionDeniedResponse
# ===========================================================================


class TestPermissionDeniedResponse:
    def test_valid(self):
        resp = PermissionDeniedResponse(detail="当前角色无权执行此操作")
        assert "无权" in resp.detail
