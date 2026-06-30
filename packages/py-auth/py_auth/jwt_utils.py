"""py-auth JWT Token 管理 — JoseTokenManager 实现。

实现 TokenManager 契约，使用 python-jose 库进行 HMAC-SHA256 对称签名。
支持密钥轮换：header 中嵌入 kid 字段，校验时根据 kid 选择对应密钥。

核心类:
  - JoseTokenManager: 实现 TokenManager 契约，JWT 签发与校验
  - TokenType: Token 类型枚举 (access / refresh)

Usage:
    from py_auth.jwt_utils import JoseTokenManager
    manager = JoseTokenManager()
    token = manager.create_access_token({"sub": "user-123", "roles": ["family"]})
    payload = manager.verify_access_token(token)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, cast
from uuid import uuid4

from jose import jwt as jose_jwt
from jose.exceptions import JWTError as JoseJWTError
from py_config.security import get_security_config
from py_logger import logger

from py_auth.auth_contract import TokenManager
from py_auth.exceptions import TokenCreationError, TokenDecodeError


class TokenType(StrEnum):
    """JWT Token 类型枚举。"""

    ACCESS = "access"
    REFRESH = "refresh"


class JoseTokenManager(TokenManager):
    """python-jose JWT 实现，继承 TokenManager 契约。

    从 py-config 读取密钥、算法和密钥版本配置。
    支持新旧密钥共栖（密钥轮换过渡期）。
    """

    def __init__(self) -> None:
        self._config = get_security_config()
        self._tz = timezone(timedelta(hours=8), name="Asia/Shanghai")

    # ------------------------------------------------------------------
    # 契约钩子
    # ------------------------------------------------------------------

    def _do_create_token(self, data: dict[str, Any], token_type: str, ttl_seconds: int) -> str:
        """执行 JWT 签发——构建 claims，调用 python-jose 编码。"""
        now = datetime.now(self._tz)

        payload = {
            "iss": "campfire-ai",
            "sub": data["sub"],
            "roles": data["roles"],
            "type": token_type,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "jti": str(uuid4()),
        }

        try:
            result = jose_jwt.encode(
                payload,
                self._config.JWT_SECRET_KEY,
                algorithm=self._config.JWT_ALGORITHM,
                headers={"kid": self._config.JWT_KEY_VERSION},
            )
            return cast(str, result)
        except JoseJWTError as exc:
            raise TokenCreationError(
                f"JWT 签发失败: {exc}",
                token_type=token_type,
                detail={"error_type": type(exc).__name__},
            ) from exc

    def _do_verify_token(self, token: str) -> dict[str, Any] | None:
        """执行 JWT 校验——解码 header → 选密钥 → 验证签名+过期。"""
        try:
            unverified_headers = jose_jwt.get_unverified_headers(token)
        except JoseJWTError as exc:
            raise TokenDecodeError(
                f"Token 格式无效: {exc}",
                detail={"error_type": type(exc).__name__},
            ) from exc

        kid = unverified_headers.get("kid")

        # 密钥轮换：当前密钥优先，其次上一版本密钥
        if kid == self._config.JWT_KEY_VERSION and self._config.JWT_KEY_VERSION:
            selected_key = self._config.JWT_SECRET_KEY
        elif self._config.JWT_PREVIOUS_KEY_VERSION and kid == self._config.JWT_PREVIOUS_KEY_VERSION:
            selected_key = self._config.JWT_PREVIOUS_SECRET_KEY
        else:
            logger.warning(
                "py-auth",
                "Token kid 不匹配任何已知密钥版本",
                op_type="认证",
                extra={"kid": kid},
            )
            return None

        try:
            payload: dict[str, Any] = jose_jwt.decode(
                token,
                selected_key,
                algorithms=[self._config.JWT_ALGORITHM],
                options={"verify_exp": True},
            )
            payload["kid"] = kid
            return payload
        except JoseJWTError:
            return None


# ============================================================================
# 惰性初始化（避免 import 时触发 get_security_config）
# ============================================================================

_manager_instance: JoseTokenManager | None = None


def _get_manager() -> JoseTokenManager:
    """获取 JoseTokenManager 单例（惰性初始化）。"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = JoseTokenManager()
    return _manager_instance


# ============================================================================
# 便捷函数（兼容旧 API）
# ============================================================================


def create_access_token(data: dict[str, Any]) -> str:
    """便捷函数——签发访问令牌。"""
    return _get_manager().create_access_token(data)


def create_refresh_token(data: dict[str, Any]) -> str:
    """便捷函数——签发续期令牌。"""
    return _get_manager().create_refresh_token(data)


def verify_token(token: str) -> dict[str, Any] | None:
    """便捷函数——校验 Token 签名和有效期。"""
    return _get_manager().verify_token(token)


def verify_access_token(token: str) -> dict[str, Any] | None:
    """便捷函数——校验访问令牌。"""
    return _get_manager().verify_access_token(token)


def verify_refresh_token(token: str) -> dict[str, Any] | None:
    """便捷函数——校验续期令牌。"""
    return _get_manager().verify_refresh_token(token)


__all__ = [
    "TokenType",
    "JoseTokenManager",
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "verify_access_token",
    "verify_refresh_token",
]
