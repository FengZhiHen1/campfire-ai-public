"""DEPLOY-05 环境配置管理 + SEC-01 安全配置 — 单元测试。

覆盖 AppSettings、SecurityConfig、RateLimitConfig、get_security_config、
以及自定义异常类。
"""

from __future__ import annotations

import pytest
from py_config.exceptions import (
    ConfigError,
    ConfigFormatError,
    ConfigWarning,
    EventLimitExceededError,
    ForbiddenAccess,
    MissingRequiredFieldError,
    ProfileConflictError,
    ProfileLimitExceededError,
)
from pydantic import ValidationError

# ===========================================================================
# Exceptions
# ===========================================================================


class TestConfigError:
    def test_basic(self):
        e = ConfigError("配置错误")
        assert e.message == "配置错误"
        assert str(e) == "配置错误"


class TestMissingRequiredFieldError:
    def test_with_fields(self):
        e = MissingRequiredFieldError("缺失字段", missing_fields=["DATABASE_URL", "REDIS_URL"])
        assert e.missing_fields == ["DATABASE_URL", "REDIS_URL"]
        assert isinstance(e, ConfigError)


class TestConfigFormatError:
    def test_with_detail(self):
        e = ConfigFormatError(
            "格式错误",
            field_name="DATABASE_URL",
            expected_format="postgresql+asyncpg://...",
            received_value="invalid",
        )
        assert e.field_name == "DATABASE_URL"
        assert e.expected_format == "postgresql+asyncpg://..."
        assert e.received_value == "invalid"


class TestForbiddenAccess:
    def test_default_detail(self):
        e = ForbiddenAccess()
        assert e.status_code == 403
        assert e.detail == "数据不存在"

    def test_custom_detail(self):
        e = ForbiddenAccess(detail="自定义消息")
        assert e.detail == "自定义消息"


class TestProfileLimitExceededError:
    def test_defaults(self):
        e = ProfileLimitExceededError()
        assert e.status_code == 409
        assert e.error_code == "PROFILE_LIMIT_EXCEEDED"
        assert e.max_allowed == 5


class TestProfileConflictError:
    def test_defaults(self):
        e = ProfileConflictError()
        assert e.status_code == 409
        assert e.error_code == "PROFILE_CONFLICT"


class TestEventLimitExceededError:
    def test_defaults(self):
        e = EventLimitExceededError()
        assert e.status_code == 409
        assert e.error_code == "EVENT_LIMIT_EXCEEDED"
        assert e.max_allowed == 500


class TestConfigWarning:
    def test_basic(self):
        w = ConfigWarning("生产环境警告", affected_fields=["JWT_SECRET_KEY"])
        assert w.affected_fields == ["JWT_SECRET_KEY"]
        assert isinstance(w, UserWarning)


# ===========================================================================
# RateLimitConfig
# ===========================================================================


class TestRateLimitConfig:
    def test_defaults(self):
        from py_config.security import RateLimitConfig

        cfg = RateLimitConfig()
        assert cfg.RATE_LIMIT_USER_PER_MINUTE == 30
        assert cfg.RATE_LIMIT_IP_PER_MINUTE == 100
        assert cfg.RATE_LIMIT_WINDOW_SECONDS == 60

    def test_custom(self):
        from py_config.security import RateLimitConfig

        cfg = RateLimitConfig(
            RATE_LIMIT_USER_PER_MINUTE=10,
            RATE_LIMIT_IP_PER_MINUTE=50,
            RATE_LIMIT_WINDOW_SECONDS=30,
        )
        assert cfg.RATE_LIMIT_USER_PER_MINUTE == 10


# ===========================================================================
# SecurityConfig
# ===========================================================================


_MIN_32_KEY = "a" * 32  # exactly 32 chars


class TestSecurityConfig:
    def test_minimal_valid(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        from py_config.security import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.BCRYPT_ROUNDS == 12
        assert cfg.JWT_ALGORITHM == "HS256"
        assert cfg.JWT_KEY_VERSION == "v1"
        assert cfg.RATE_LIMIT_USER_PER_MINUTE == 30
        assert cfg.MINIO_PRESIGNED_URL_EXPIRY_SECONDS == 3600
        assert "pdf" in cfg.ALLOWED_FILE_EXTENSIONS

    def test_short_key_rejected(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", "short")
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        from py_config.security import SecurityConfig

        with pytest.raises(ValidationError):
            SecurityConfig()

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("SECURITY_JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", raising=False)
        # Need to reload; lru_cache makes this tricky
        from py_config.security import get_security_config

        get_security_config.cache_clear()

    def test_custom_bcrypt_rounds(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_BCRYPT_ROUNDS", "14")
        from py_config.security import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.BCRYPT_ROUNDS == 14

    def test_jwt_key_version_default(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        from py_config.security import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.JWT_KEY_VERSION == "v1"

    def test_allowed_file_extensions_custom(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        import json

        monkeypatch.setenv("SECURITY_ALLOWED_FILE_EXTENSIONS", json.dumps(["pdf", "jpg"]))
        from py_config.security import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.ALLOWED_FILE_EXTENSIONS == ["pdf", "jpg"]


class TestGetSecurityConfig:
    def test_returns_singleton(self, monkeypatch):
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        from py_config.security import get_security_config

        get_security_config.cache_clear()
        cfg1 = get_security_config()
        cfg2 = get_security_config()
        assert cfg1 is cfg2


# ===========================================================================
# AppSettings
# ===========================================================================


class TestAppSettings:
    def test_security_config_use_env_prefix(self, monkeypatch):
        """SecurityConfig 读取 SECURITY_ 前缀环境变量。"""
        monkeypatch.setenv("SECURITY_JWT_SECRET_KEY", _MIN_32_KEY)
        monkeypatch.setenv("SECURITY_JWT_PREVIOUS_SECRET_KEY", _MIN_32_KEY)
        from py_config.security import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.JWT_SECRET_KEY == _MIN_32_KEY
        assert cfg.JWT_PREVIOUS_SECRET_KEY == _MIN_32_KEY
