"""SEC-01/AUTH-02 JWT Token 签发与校验 — 单元测试。

覆盖 create_access_token、create_refresh_token、verify_token、
verify_access_token、verify_refresh_token、TokenType。
"""

from __future__ import annotations

import pytest
from py_auth.exceptions import TokenDecodeError
from py_auth.jwt_utils import (
    TokenType,
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
    verify_token,
)

_VALID_DATA = {"sub": "user-001", "roles": ["family"]}


# ---- TokenType ----


class TestTokenType:
    def test_values(self):
        assert TokenType.ACCESS == "access"
        assert TokenType.REFRESH == "refresh"


# ---- create_access_token ----


class TestCreateAccessToken:
    def test_returns_jwt_string(self):
        token = create_access_token(_VALID_DATA)
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT 三段式

    def test_missing_sub_raises(self):
        with pytest.raises(ValueError, match="sub"):
            create_access_token({"roles": ["family"]})

    def test_missing_roles_raises(self):
        with pytest.raises(ValueError, match="roles"):
            create_access_token({"sub": "user-001"})


# ---- create_refresh_token ----


class TestCreateRefreshToken:
    def test_returns_longer_jwt(self):
        token = create_refresh_token(_VALID_DATA)
        assert isinstance(token, str)
        assert token.count(".") == 2

    def test_missing_sub_raises(self):
        with pytest.raises(ValueError, match="sub"):
            create_refresh_token({"roles": ["family"]})


# ---- verify_token ----


class TestVerifyToken:
    def test_verify_valid_access_token(self):
        token = create_access_token(_VALID_DATA)
        payload = verify_token(token)
        assert payload["sub"] == "user-001"
        assert payload["type"] == "access"

    def test_verify_valid_refresh_token(self):
        token = create_refresh_token(_VALID_DATA)
        payload = verify_token(token)
        assert payload["type"] == "refresh"

    def test_verify_invalid_token_raises(self):
        with pytest.raises(TokenDecodeError):
            verify_token("not.a.valid.jwt.token")

    def test_verify_empty_string_returns_none(self):
        """空字符串 Token 应返回 None（前置校验拒绝，不抛异常）。"""
        assert verify_token("") is None

    def test_verify_garbage_raises(self):
        with pytest.raises(TokenDecodeError):
            verify_token("garbage_string_not_jwt")


# ---- verify_access_token ----


class TestVerifyAccessToken:
    def test_valid_access_token(self):
        token = create_access_token(_VALID_DATA)
        payload = verify_access_token(token)
        assert payload["type"] == "access"

    def test_refresh_token_rejected(self):
        token = create_refresh_token(_VALID_DATA)
        result = verify_access_token(token)
        assert result is None


# ---- verify_refresh_token ----


class TestVerifyRefreshToken:
    def test_valid_refresh_token(self):
        token = create_refresh_token(_VALID_DATA)
        payload = verify_refresh_token(token)
        assert payload["type"] == "refresh"

    def test_access_token_rejected(self):
        token = create_access_token(_VALID_DATA)
        result = verify_refresh_token(token)
        assert result is None
