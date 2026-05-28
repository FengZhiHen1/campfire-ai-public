"""SEC-01 密码哈希与校验 — 单元测试。

覆盖 hash_password、verify_password 的正常流程和异常分支。
"""

from __future__ import annotations

from unittest import mock

import pytest

from py_auth.exceptions import HashingError
from py_auth.hashing import hash_password, verify_password


# ---- hash_password ----


class TestHashPassword:
    def test_returns_bcrypt_format(self):
        result = hash_password("ValidP@ss1")
        assert result.startswith("$2b$")
        assert len(result) > 20

    def test_different_salts(self):
        pw = "ValidP@ss1"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2  # random salt

    def test_password_too_short(self):
        with pytest.raises(ValueError, match="长度必须在 8-64"):
            hash_password("Abc12")

    def test_password_too_long(self):
        with pytest.raises(ValueError, match="长度必须在 8-64"):
            hash_password("a" * 65)

    def test_exact_min_length(self):
        result = hash_password("12345678")
        assert result.startswith("$2b$")


# ---- verify_password ----


class TestVerifyPassword:
    def test_matching_password(self):
        pw = "MyTestP@ss1"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_non_matching_password(self):
        hashed = hash_password("CorrectP@ss1")
        assert verify_password("WrongP@ss2", hashed) is False

    def test_plain_too_short(self):
        with pytest.raises(ValueError, match="长度必须在 8-64"):
            verify_password("Abc12", "$2b$12$...")

    def test_invalid_hash_format(self):
        with pytest.raises(ValueError, match="格式不合法"):
            verify_password("ValidP@ss1", "invalid_hash")

    def test_invalid_hash_type(self):
        with pytest.raises(ValueError, match="必须是 str 类型"):
            verify_password("ValidP@ss1", 12345)


# ---- HashingError propagation ----


class TestHashingErrorPropagation:
    def test_hash_password_raises_hashing_error(self):
        with mock.patch("py_auth.hashing.bcrypt.gensalt", side_effect=RuntimeError("boom")):
            with pytest.raises(HashingError, match="bcrypt 哈希计算失败"):
                hash_password("ValidP@ss1")

    def test_verify_password_raises_hashing_error(self):
        with mock.patch("py_auth.hashing.bcrypt.checkpw", side_effect=RuntimeError("boom")):
            with pytest.raises(HashingError, match="bcrypt 密码校验失败"):
                verify_password("ValidP@ss1", "$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
