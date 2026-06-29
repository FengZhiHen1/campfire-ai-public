#!/usr/bin/env python3
"""创建预置评委用户。

当前产品面向评委线上评审，无普通用户场景。
运行本脚本可在数据库中创建固定的 expert 评委账号；
若账号已存在则跳过，不会重复创建。

用法:
    uv run scripts/seed_judge_user.py
    python scripts/seed_judge_user.py
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# 将项目根目录加入 PYTHONPATH，以便导入内部包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "py-config"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "py-db"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "py-auth"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "py-schemas"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "py-logger"))

load_dotenv(PROJECT_ROOT / ".env")

from py_auth.hashing import hash_password  # noqa: E402
from py_config import get_settings  # noqa: E402
from py_db.models.auth import User  # noqa: E402
from py_db.models.base import Base  # noqa: E402
from py_logger import logger  # noqa: E402
from py_schemas.auth import UserRole  # noqa: E402


async def create_judge_user() -> None:
    """查找或创建预置评委账号。"""
    settings = get_settings()
    database_url = str(settings.DATABASE_URL)

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    username = settings.JUDGE_USERNAME
    phone = settings.JUDGE_PHONE
    real_name = settings.JUDGE_REAL_NAME

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        existing = result.scalars().first()

        if existing is not None:
            print(f"评委用户已存在: id={existing.id}, username={existing.username}, role={existing.role.value}")
            await engine.dispose()
            return

        user = User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=UserRole.EXPERT,
            phone=phone,
            real_name=real_name,
            device_id="judge",
        )
        session.add(user)

        try:
            await session.commit()
            await session.refresh(user)
            print(f"评委用户创建成功: id={user.id}, username={user.username}, role={user.role.value}")
            logger.info(
                service="seed",
                message="judge_user_created",
                op_type="USER_REGISTER",
                extra={"user_id": str(user.id), "username": username},
            )
        except IntegrityError as exc:
            await session.rollback()
            print(f"创建评委用户失败（可能已存在）: {exc}")
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_judge_user())
