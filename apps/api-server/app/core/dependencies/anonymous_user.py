"""MVP 匿名用户适配层。

从 X-Device-Id 请求头提取设备标识，在 users 表中自动查找或创建匿名用户记录，
返回与现有 JWT payload 兼容的 user dict。

所有路由中的 Depends(get_current_user) 可替换为 Depends(get_anonymous_user)。
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.auth import User
from py_logger import logger
from py_schemas.auth import UserRole

from app.core.dependencies.auth_dependencies import get_db_session

_ANON_PASSWORD_HASH: str = (
    "$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
)

_MAX_RETRIES = 3


def _generate_anon_phone() -> str:
    """生成随机 11 位数字作为匿名用户手机号。"""
    return f"{secrets.randbelow(10 ** 11):011d}"


async def _get_or_create_anonymous_user(
    session: AsyncSession,
    device_id: str,
) -> User:
    """根据 device_id 查找或创建匿名用户记录。

    处理两类唯一约束冲突：
    1. username 冲突 — 并发请求携带相同 device_id 同时到达，
       第二个 INSERT 因 username 已存在而失败。回退到重新 SELECT。
    2. phone 冲突 — 随机生成的手机号小概率碰撞。重新生成 phone 并重试。
    """
    result = await session.execute(
        select(User).where(User.device_id == device_id)
    )
    existing = result.scalars().first()
    if existing is not None:
        return existing

    for attempt in range(1, _MAX_RETRIES + 1):
        user = User(
            username=device_id,
            password_hash=_ANON_PASSWORD_HASH,
            role=UserRole.FAMILY,
            phone=_generate_anon_phone(),
            device_id=device_id,
        )
        session.add(user)
        try:
            await session.flush()
            await session.refresh(user)
            logger.info(
                service="api-server",
                message="anonymous_user_created",
                op_type="USER_REGISTER",
                extra={"user_id": str(user.id), "device_id": device_id},
            )
            return user
        except IntegrityError:
            await session.rollback()
            # 检查是否为 username 冲突（并发同 device_id 插入）
            result = await session.execute(
                select(User).where(User.device_id == device_id)
            )
            existing = result.scalars().first()
            if existing is not None:
                return existing
            # phone 冲突：重试下一次循环（重新生成 phone）
            if attempt == _MAX_RETRIES:
                logger.error(
                    service="api-server",
                    message="anonymous_user_creation_failed",
                    extra={
                        "device_id": device_id,
                        "attempt": attempt,
                    },
                )
                raise

    raise RuntimeError("unreachable")


async def get_anonymous_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """提取/创建匿名用户，返回兼容现有路由的 payload dict。

    复用 get_db_session 的会话，避免每个请求创建两个数据库连接。

    流程：
    1. 从 X-Device-Id 读取 device_id（缺失则生成随机值）
    2. 在当前请求会话中查找或创建匿名用户记录
    3. 返回现有 Service 层兼容的 dict

    Returns:
        dict: 含 sub / user_id / role / device_id 的字典。
    """
    device_id = request.headers.get("X-Device-Id", "")
    if not device_id:
        device_id = secrets.token_urlsafe(12)

    user = await _get_or_create_anonymous_user(db, device_id)
    await db.commit()

    return {
        "sub": str(user.id),
        "user_id": str(user.id),
        "role": "family",
        "device_id": device_id,
    }


__all__ = ["get_anonymous_user"]
