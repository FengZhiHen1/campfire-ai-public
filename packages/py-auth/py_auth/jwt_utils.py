"""JWT Token 签发与校验。

使用 HMAC-SHA256 (HS256) 对称签名算法签发和校验 JWT Token。
支持两种 Token 类型：access（15分钟）和 refresh（7天）。
支持密钥轮换：header 中嵌入 kid 字段，校验时根据 kid 选择对应密钥。

公开函数：
  - create_access_token: 签发访问令牌
  - create_refresh_token: 签发续期令牌
  - verify_token: 校验 Token 签名和有效期
  - verify_access_token: 校验访问令牌（含类型检查）
  - verify_refresh_token: 校验续期令牌（含类型检查）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import uuid4

from jose import jwt as jose_jwt
from jose.exceptions import JWTError as JoseJWTError

from py_auth.exceptions import TokenCreationError, TokenDecodeError
from py_config.security import get_security_config


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


_ACCESS_TTL = timedelta(minutes=15)
_REFRESH_TTL = timedelta(days=7)


def _build_token(
    data: dict,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    if "sub" not in data:
        raise ValueError("data 必须包含 sub 字段")
    if "roles" not in data:
        raise ValueError("data 必须包含 roles 字段")

    config = get_security_config()
    tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
    now = datetime.now(tz)

    payload = {
        "iss": "campfire-ai",
        "sub": data["sub"],
        "roles": data["roles"],
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid4()),
    }

    try:
        return jose_jwt.encode(
            payload,
            config.JWT_SECRET_KEY,
            algorithm=config.JWT_ALGORITHM,
            headers={"kid": config.JWT_KEY_VERSION},
        )
    except JoseJWTError as exc:
        raise TokenCreationError(f"JWT 签发失败: {exc}") from exc


def create_access_token(data: dict) -> str:
    """签发访问令牌（15 分钟有效，type=access）。

    Args:
        data: 必须包含 ``sub`` (用户ID) 和 ``roles`` (角色列表)。

    Raises:
        ValueError: 缺少必要字段。
    """
    return _build_token(data, TokenType.ACCESS, _ACCESS_TTL)


def create_refresh_token(data: dict) -> str:
    """签发续期令牌（7 天有效，type=refresh）。

    Args:
        data: 必须包含 ``sub`` (用户ID) 和 ``roles`` (角色列表)。
    """
    return _build_token(data, TokenType.REFRESH, _REFRESH_TTL)


def verify_token(token: str) -> dict | None:
    """校验 Token 签名和有效期（不检查 type）。

    校验流程：
    1. 解码 header 提取 kid
    2. 根据 kid 选择对应版本密钥（支持新旧密钥共栖）
    3. 签名校验 + exp 过期检查 → 通过则返回 payload dict

    Returns:
        dict | None: 解码后的 payload，校验失败返回 None。
    """
    config = get_security_config()

    try:
        unverified_headers = jose_jwt.get_unverified_headers(token)
    except JoseJWTError as exc:
        raise TokenDecodeError(f"token 格式无效: {exc}") from exc
    except Exception as exc:
        raise TokenDecodeError(f"token 格式无效: {exc}") from exc

    kid = unverified_headers.get("kid")

    if kid == config.JWT_KEY_VERSION and config.JWT_KEY_VERSION:
        selected_key = config.JWT_SECRET_KEY
    elif (
        config.JWT_PREVIOUS_KEY_VERSION
        and kid == config.JWT_PREVIOUS_KEY_VERSION
    ):
        selected_key = config.JWT_PREVIOUS_SECRET_KEY
    else:
        return None

    try:
        payload: dict = jose_jwt.decode(
            token,
            selected_key,
            algorithms=[config.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
        payload["kid"] = kid
        return payload
    except JoseJWTError:
        return None


def verify_access_token(token: str) -> dict | None:
    """校验访问令牌：签名 + 有效期 + type == access。"""
    payload = verify_token(token)
    if payload is None:
        return None
    if payload.get("type") != TokenType.ACCESS.value:
        return None
    return payload


def verify_refresh_token(token: str) -> dict | None:
    """校验续期令牌：签名 + 有效期 + type == refresh。"""
    payload = verify_token(token)
    if payload is None:
        return None
    if payload.get("type") != TokenType.REFRESH.value:
        return None
    return payload


__all__ = [
    "TokenType",
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "verify_access_token",
    "verify_refresh_token",
]
