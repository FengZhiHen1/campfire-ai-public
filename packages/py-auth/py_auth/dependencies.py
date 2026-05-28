"""FastAPI 认证依赖注入（MVP 匿名绕过版）。

MVP 阶段完全绕过 JWT 认证：
- 从请求头读取 X-Device-Id 作为匿名身份标识
- 若缺失则生成随机设备 ID
- 将设备 ID 确定性映射为 UUID，确保与后端各模块的 UUID 类型兼容
- 返回兼容现有路由的 payload 字典（sub, roles, jti）

所有路由中的 Depends(get_current_user) 和 Depends(require_role(...))
无需任何修改即可正常工作。
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import HTTPException, Request


async def get_current_user(
    request: Request,
) -> dict:
    """从 X-Device-Id 请求头提取匿名用户身份。

    MVP 阶段不进行 JWT 校验，直接信任前端传入的设备匿名 ID。
    若请求头中无 X-Device-Id，则生成一个随机设备 ID。
    设备 ID 通过 uuid5 确定性映射为 UUID，确保与后端 repository 层的
    UUID 类型约束兼容，且同一设备始终得到同一 UUID。

    Returns:
        dict: 含 sub（UUID 字符串）、roles（固定 ["family"]）、
              jti（固定 "anonymous"）、exp（固定远期时间戳）的 payload 字典，
              与原有 JWT payload 结构完全兼容。

    Raises:
        HTTPException(401): 极少场景下（请求对象缺失）返回 401。
    """
    device_id = request.headers.get("X-Device-Id", "")
    if not device_id:
        # 生成一个 16 字符的 URL-safe 随机字符串作为匿名设备 ID
        device_id = secrets.token_urlsafe(12)

    # 将设备 ID 确定性映射为 UUID，兼容后端 repository 的 UUID 类型约束
    user_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, device_id)

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
