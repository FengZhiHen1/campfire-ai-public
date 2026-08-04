"""JWT Token 签发与校验 — 单元测试（ADR-013 目标态）。

覆盖 Token 家族语义：access/refresh 签发携带 sub/role/status/family_id，
轮换在同一家族内延续，旧 refresh 复用触发全家族吊销（由 Service 层编排，
本层提供 family_id claim 承载与校验）。
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

_VALID_DATA = {
    "sub": "user-001",
    "role": "family",
    "status": "active",
    "family_id": "fam-001",
}


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

    def test_payload_claims(self):
        """access token 承载 sub/role/status/jti/exp（认证与访问 §5.1）+ family_id。"""
        token = create_access_token(_VALID_DATA)
        payload = verify_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-001"
        assert payload["role"] == "family"
        assert payload["status"] == "active"
        assert payload["family_id"] == "fam-001"
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "exp" in payload

    def test_missing_sub_raises(self):
        with pytest.raises(ValueError, match="sub"):
            create_access_token({"role": "family", "status": "active", "family_id": "f"})

    def test_missing_role_raises(self):
        with pytest.raises(ValueError, match="role"):
            create_access_token({"sub": "user-001", "status": "active", "family_id": "f"})

    def test_missing_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            create_access_token({"sub": "user-001", "role": "family", "family_id": "f"})

    def test_missing_family_id_raises(self):
        with pytest.raises(ValueError, match="family_id"):
            create_access_token({"sub": "user-001", "role": "family", "status": "active"})


# ---- create_refresh_token ----


class TestCreateRefreshToken:
    def test_returns_longer_jwt(self):
        token = create_refresh_token(_VALID_DATA)
        assert isinstance(token, str)
        assert token.count(".") == 2

    def test_payload_carries_family_id(self):
        """refresh token 同样承载 family_id——轮换在同一家族内延续。"""
        token = create_refresh_token(_VALID_DATA)
        payload = verify_refresh_token(token)
        assert payload is not None
        assert payload["family_id"] == "fam-001"
        assert payload["type"] == "refresh"

    def test_missing_sub_raises(self):
        with pytest.raises(ValueError, match="sub"):
            create_refresh_token({"role": "family", "status": "active", "family_id": "f"})


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
