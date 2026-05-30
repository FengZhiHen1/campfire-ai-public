"""py-auth FastAPI 认证依赖注入。

MVP 阶段：从 X-Device-Id 请求头提取匿名用户身份，兼容现有路由。
正式阶段：集成 JoseTokenManager 进行 JWT 校验。

核心函数:
  - get_current_user: FastAPI Depends 兼容的认证依赖

Usage:
    from py_auth.dependencies import get_current_user
    @router.get("/me")
    async def me(user: dict = Depends(get_current_user)):
        ...
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import Request

from py_logger import logger


async def get_current_user(request: Request) -> dict[str, object]:
    """从 X-Device-Id 请求头提取匿名用户身份。

    MVP 阶段不进行 JWT 校验，直接信任前端传入的设备匿名 ID。
    若请求头中无 X-Device-Id，则生成一个随机设备 ID。
    设备 ID 通过 uuid5 确定性映射为 UUID，确保同一设备始终得到同一 UUID。

    Returns:
        dict: 含 sub（UUID 字符串）、roles（固定 ["family"]）、
              jti（固定 "anonymous"）、exp（固定远期时间戳）、
              type（"access"）的 payload 字典。

    Side Effects:
        - 新设备首次访问时记录 info 日志
    """
    device_id = request.headers.get("X-Device-Id", "")
    is_new_device = not device_id

    if not device_id:
        device_id = secrets.token_urlsafe(12)

    user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, device_id)

    if is_new_device:
        logger.info(
            "py-auth",
            "新匿名设备已分配 UUID",
            op_type="认证",
            extra={"device_hash": str(user_uuid)[:8] + "..."},
        )

    return {
        "sub": str(user_uuid),
        "roles": ["family"],
        "jti": "anonymous",
        "exp": 9999999999,
        "type": "access",
    }


__all__ = [
    "get_current_user",
]
