"""MVP 匿名用户适配层。

从 X-Device-Id 请求头提取设备标识，在 users 表中自动查找或创建匿名用户记录，
返回与现有 JWT payload 兼容的 user dict。

所有路由中的 Depends(get_current_user) 可替换为 Depends(get_anonymous_user)。
"""

from __future__ import annotations

import secrets
from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.auth import User
from py_schemas.auth import UserRole


_ANON_PASSWORD_HASH: str = (
    "$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
)


async def _get_or_create_anonymous_user(
    session: AsyncSession,
    device_id: str,
) -> User:
    """根据 device_id 查找或创建匿名用户记录。

    Args:
        session: 数据库异步会话。
        device_id: 设备匿名标识。

    Returns:
        User: 已存在的或新创建的匿名用户。
    """
    # 1. 尝试查找已有记录
    result = await session.execute(
        select(User).where(User.device_id == device_id)
    )
    existing = result.scalars().first()
    if existing is not None:
        return existing

    # 2. 创建新的匿名用户（填充占位值以满足非空约束）
    user = User(
        username=device_id,
        password_hash=_ANON_PASSWORD_HASH,
        role=UserRole.FAMILY,
        phone=device_id[:11].ljust(11, "0"),
        device_id=device_id,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def get_anonymous_user(
    request: Request,
) -> dict:
    """提取/创建匿名用户，返回兼容现有路由的 payload dict。

    流程：
    1. 从 X-Device-Id 读取 device_id（缺失则生成随机值）
    2. 在数据库查找或创建匿名用户记录
    3. 返回现有 Service 层兼容的 dict

    Returns:
        dict: 含 sub / user_id / role / device_id 的字典。
    """
    device_id = request.headers.get("X-Device-Id", "")
    if not device_id:
        device_id = secrets.token_urlsafe(12)

    # 使用 auth_dependencies 中的 session factory 获取会话
    from app.dependencies.auth_dependencies import _get_session_factory

    factory = _get_session_factory()
    async with factory() as session:
        user = await _get_or_create_anonymous_user(session, device_id)

    return {
        "sub": str(user.id),
        "user_id": str(user.id),
        "role": "family",
        "device_id": device_id,
    }


__all__ = ["get_anonymous_user"]
