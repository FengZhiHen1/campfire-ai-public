"""FastAPI 认证依赖注入。

提供 Bearer Token 提取和当前用户解析，供路由层 Depends 注入。

用法:
    from py_auth.dependencies import get_current_user
    from fastapi import Depends

    @router.get("/me")
    async def me(user: dict = Depends(get_current_user)):
        return {"user_id": user["sub"], "roles": user["roles"]}
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from py_auth.blacklist import is_blacklisted
from py_auth.jwt_utils import verify_access_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    scheme_name="Bearer",
    description="在 /api/v1/auth/login 获取 Token，后续请求携带 Authorization: Bearer <token>",
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> dict:
    """从 Bearer Token 解析当前用户。

    校验链路：Bearer 提取 → JWT 校验 → 黑名单检查 → 返回 payload。

    Returns:
        dict: 含 sub, roles, jti, exp 等字段的 JWT payload。

    Raises:
        HTTPException(401): Token 无效、过期、已被撤销或类型错误。
    """
    payload = verify_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="未登录或 Token 已过期")

    if await is_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token 已被撤销")

    return payload


__all__ = [
    "oauth2_scheme",
    "get_current_user",
]
