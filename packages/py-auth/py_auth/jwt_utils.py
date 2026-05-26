"""SEC-01 JWT Token 签发与校验。

使用 HMAC-SHA256 (HS256) 对称签名算法签发和校验 JWT 访问令牌。
支持密钥轮换：header 中嵌入 kid 字段，校验时根据 kid 选择对应密钥。

公开函数：
  - create_access_token: 签发 JWT 访问令牌（不幂等）
  - verify_token: 校验 JWT Token 签名和有效期（幂等）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import jwt as jose_jwt
from jose.exceptions import JWTError as JoseJWTError

from py_auth.exceptions import TokenCreationError, TokenDecodeError
from py_config.security import get_security_config


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """签发 JWT 访问令牌（HS256 算法，header 嵌入 kid 字段）。

    Args:
        data: JWT payload 核心数据，必须包含 ``sub`` (str, 用户ID)
              和 ``roles`` (list[str], 角色列表)。
        expires_delta: 自定义过期时长，None 时默认 15 分钟。

    Returns:
        str: JWT token 字符串，header 含 ``{"alg":"HS256","kid":"v1","typ":"JWT"}``，
             标准声明: iss, sub, roles, iat, exp, jti (UUID v4)。

    Raises:
        ValueError: data 缺少 ``sub`` 或 ``roles`` 字段。
        TokenCreationError: JWT 签发失败（密钥长度不足、jose 库内部错误等）。

    Side Effects:
        读取环境变量 ``JWT_SECRET_KEY`` 和 ``JWT_KEY_VERSION``。
    """
    if "sub" not in data:
        raise ValueError("data 必须包含 sub 字段")
    if "roles" not in data:
        raise ValueError("data 必须包含 roles 字段")

    config = get_security_config()

    tz_shanghai = timezone(timedelta(hours=8), name="Asia/Shanghai")
    now = datetime.now(tz_shanghai)

    if expires_delta is None:
        expires_delta = timedelta(minutes=15)

    expire = now + expires_delta

    payload = {
        "iss": "campfire-ai",
        "sub": data["sub"],
        "roles": data["roles"],
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": str(uuid4()),
    }

    headers = {"kid": config.JWT_KEY_VERSION}

    try:
        token: str = jose_jwt.encode(
            payload,
            config.JWT_SECRET_KEY,
            algorithm=config.JWT_ALGORITHM,
            headers=headers,
        )
        return token
    except JoseJWTError as exc:
        raise TokenCreationError(f"JWT 签发失败: {exc}") from exc


def verify_token(token: str) -> dict | None:
    """校验 JWT Token 签名和有效期，根据 header 的 kid 选择对应密钥。

    校验流程：
    1. 解码 token header 提取 kid
    2. kid == 当前版本 → 使用 JWT_SECRET_KEY
    3. kid == 上一版本 → 使用 JWT_PREVIOUS_SECRET_KEY（共栖期支持）
    4. kid 不匹配 → 返回 None
    5. 签名校验 + exp 过期检查 → 通过则返回 payload dict

    Args:
        token: JWT token 字符串。

    Returns:
        dict | None: 解码后的 TokenPayload 字典
                     （包含 sub, roles, kid, exp, iat, iss, jti），
                     校验失败返回 None。

    Raises:
        TokenDecodeError: token 格式无效（非 JWT 格式字符串）。

    Side Effects:
        读取环境变量 ``JWT_SECRET_KEY``、``JWT_PREVIOUS_SECRET_KEY``、
        ``JWT_KEY_VERSION``、``JWT_PREVIOUS_KEY_VERSION``。
    """
    config = get_security_config()

    # 步骤 1：解码 header 提取 kid
    try:
        unverified_headers = jose_jwt.get_unverified_headers(token)
    except JoseJWTError as exc:
        raise TokenDecodeError(f"token 格式无效: {exc}") from exc
    except Exception as exc:
        raise TokenDecodeError(f"token 格式无效: {exc}") from exc

    kid = unverified_headers.get("kid")

    # 步骤 2：根据 kid 选择密钥
    if kid == config.JWT_KEY_VERSION and config.JWT_KEY_VERSION:
        selected_key = config.JWT_SECRET_KEY
    elif (
        config.JWT_PREVIOUS_KEY_VERSION
        and kid == config.JWT_PREVIOUS_KEY_VERSION
    ):
        selected_key = config.JWT_PREVIOUS_SECRET_KEY
    else:
        # kid 不匹配任何已知版本
        return None

    # 步骤 3：签名校验 + 过期检查
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
        # 签名无效、过期等 → 静默返回 None
        return None


__all__ = [
    "create_access_token",
    "verify_token",
]
