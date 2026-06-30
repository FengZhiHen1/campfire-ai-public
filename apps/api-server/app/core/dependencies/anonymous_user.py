"""MVP 评委身份适配层。

当前产品面向评委线上操作评审，无普通用户场景。
所有未携带 JWT 的请求默认映射到预置的 expert 评委账号，
实现"打开即用"的稳定身份，避免 X-Device-Id 漂移导致的数据割裂。

所有路由中的 Depends(get_current_user) 可替换为 Depends(get_anonymous_user)。
"""

from __future__ import annotations

import secrets
from typing import cast

from fastapi import Depends, Request
from py_config import get_settings
from py_db.models.auth import User
from py_logger import logger
from py_schemas.auth import UserRole
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import get_db_session

# 评委密码占位值，使用 lazily-initialized 的真实 bcrypt 哈希，
# 避免硬编码非法哈希，同时不在每次请求时重复计算 bcrypt。
_JUDGE_PASSWORD_HASH: str | None = None
_MAX_RETRIES = 10


def _get_judge_password_hash() -> str:
    """获取评委账号密码哈希（首次调用时生成真实 bcrypt 哈希并缓存）。"""
    global _JUDGE_PASSWORD_HASH
    if _JUDGE_PASSWORD_HASH is None:
        from py_auth.hashing import hash_password

        _JUDGE_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))
    return _JUDGE_PASSWORD_HASH


async def _get_or_create_judge_user(
    session: AsyncSession,
) -> User:
    """查找或创建预置评委账号。

    评委账号信息从 AppSettings 读取（JUDGE_USERNAME / JUDGE_PHONE / JUDGE_REAL_NAME），
    默认角色为 expert。如果数据库中已存在同 username 或同 phone 的用户，
    但 device_id 不是评委标识，则按 username 优先返回已有记录（不强制覆盖角色）。

    并发请求同时创建时会通过 IntegrityError 回退到重新 SELECT。
    """
    settings = get_settings()
    username = settings.JUDGE_USERNAME
    phone = settings.JUDGE_PHONE
    real_name = settings.JUDGE_REAL_NAME

    logger.info(
        service="api-server",
        message="judge_user_lookup_started",
        extra={"judge_username": username},
    )

    result = await session.execute(select(User).where(User.username == username))
    existing = result.scalars().first()
    if existing is not None:
        logger.info(
            service="api-server",
            message="judge_user_found",
            extra={
                "user_id": str(existing.id),
                "username": existing.username,
                "role": existing.role.value,
            },
        )
        return existing

    logger.warning(
        service="api-server",
        message="judge_user_not_found_creating",
        extra={"judge_username": username},
    )

    for attempt in range(1, _MAX_RETRIES + 1):
        user = User(
            username=username,
            password_hash=_get_judge_password_hash(),
            role=UserRole.EXPERT,
            phone=phone,
            real_name=real_name,
            device_id="judge",
        )
        session.add(user)
        try:
            await session.flush()
            await session.refresh(user)
            logger.info(
                service="api-server",
                message="judge_user_created",
                op_type="USER_REGISTER",
                extra={"user_id": str(user.id), "username": username},
            )
            return user
        except IntegrityError:
            await session.rollback()
            result = await session.execute(select(User).where(User.username == username))
            existing = result.scalars().first()
            if existing is not None:
                return existing
            if attempt == _MAX_RETRIES:
                logger.error(
                    service="api-server",
                    message="judge_user_creation_failed",
                    extra={"username": username, "attempt": attempt},
                )
                raise

    raise RuntimeError("unreachable")


async def get_anonymous_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """返回预置评委身份。

    当前无普通用户场景，所有未携带 JWT 的请求都映射到同一个 expert 评委账号，
    确保评委在任意设备、任意浏览器打开都能获得稳定的身份和数据视图。

    流程：
    1. 读取 AppSettings 中的评委账号配置
    2. 在数据库中查找或创建该评委账号
    3. 返回兼容现有路由的 payload dict

    Returns:
        dict: 含 sub / user_id / role / device_id 的字典，role 固定为 expert。
    """
    device_id = request.headers.get("X-Device-Id", "judge")

    logger.info(
        service="api-server",
        message="anonymous_auth_start",
        extra={
            "device_id": device_id,
            "path": request.url.path,
        },
    )

    user = await _get_or_create_judge_user(db)
    await db.commit()

    logger.info(
        service="api-server",
        message="anonymous_auth_return_judge",
        extra={
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role.value,
            "device_id": device_id,
        },
    )

    return {
        "sub": str(user.id),
        "user_id": str(user.id),
        "role": cast(str, user.role.value),
        "device_id": device_id,
    }


__all__ = ["get_anonymous_user"]
