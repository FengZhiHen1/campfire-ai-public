#!/usr/bin/env python3
"""Campfire-AI 统一种子注入脚本（ADR-013 重构版）。

本脚本为本地开发/内测环境提供唯一的数据初始化入口。
阶段 S1 起承担全库种子职责，后续阶段（S3 应急 / S4 档案 / S5 案例）随模块重构扩充。

当前注入范围（认证域）：
1. 六角色演示账号（family/volunteer/teacher/expert/admin/maintainer 各一，
   teacher/expert 直接落 active——演示已审核通过形态）
2. 演示邀请码（demand/supply 各两个，多次码便于内测分发）

用法:
    uv run scripts/seed.py              # 幂等注入全部种子数据
    uv run scripts/seed.py --clean      # 清空认证域数据后重新注入

设计约束:
- 完全幂等：按手机号/邀请码查重，重复运行不产生重复数据。
- 演示密码统一从环境变量 SEED_DEMO_PASSWORD 读取，缺省仅用于本地开发；
  生产/内测环境必须注入独立随机密码（安全规范：禁止硬编码密钥）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 将项目根目录加入 PYTHONPATH，以便导入 workspace packages
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from py_auth.hashing import hash_password  # noqa: E402
from py_config import get_settings  # noqa: E402
from py_db.models.auth import Credential, InviteCode, User  # noqa: E402
from py_logger import logger  # noqa: E402
from py_schemas.auth import UserRole  # noqa: E402
from py_schemas.enums import AccountStatus, CredentialType, InviteChannel, InviteCodeStatus  # noqa: E402

# ---------------------------------------------------------------------------
# 演示账号配置（六角色各一）
# ---------------------------------------------------------------------------

# 演示密码：环境变量注入，缺省值仅限本地开发使用
_DEMO_PASSWORD: str = os.environ.get("SEED_DEMO_PASSWORD", "Campfire123")

# (角色, 手机号, 真实姓名, 落态)
_DEMO_USERS: list[tuple[UserRole, str, str, AccountStatus]] = [
    (UserRole.FAMILY, "13800000001", "演示家属", AccountStatus.ACTIVE),
    (UserRole.VOLUNTEER, "13800000002", "演示志愿者", AccountStatus.ACTIVE),
    (UserRole.TEACHER, "13800000003", "演示老师", AccountStatus.ACTIVE),
    (UserRole.EXPERT, "13800000004", "演示专家", AccountStatus.ACTIVE),
    (UserRole.ADMIN, "13800000005", "演示管理员", AccountStatus.ACTIVE),
    (UserRole.MAINTAINER, "13800000006", "演示维护员", AccountStatus.ACTIVE),
]

# 演示邀请码（固定码值便于内测分发；多次码）
_DEMO_INVITE_CODES: list[tuple[str, InviteChannel, int]] = [
    ("DEMAND26AA", InviteChannel.DEMAND, 10),
    ("DEMAND26AB", InviteChannel.DEMAND, 10),
    ("SUPPLY26AA", InviteChannel.SUPPLY, 5),
    ("SUPPLY26AB", InviteChannel.SUPPLY, 5),
]


async def seed_users(session) -> dict[str, User]:
    """注入六角色演示账号（幂等：按手机号查重）。

    Returns:
        phone → User 的映射（供邀请码 created_by 等关联使用）。
    """
    result = await session.execute(select(User))
    existing = {u.phone: u for u in result.scalars().all()}

    created = 0
    for role, phone, real_name, status in _DEMO_USERS:
        if phone in existing:
            continue
        user = User(phone=phone, real_name=real_name, role=role, status=status)
        session.add(user)
        await session.flush()

        credential = Credential(
            user_id=user.id,
            type=CredentialType.PASSWORD,
            identifier=phone,
            secret=hash_password(_DEMO_PASSWORD),
        )
        session.add(credential)
        existing[phone] = user
        created += 1

    await session.commit()
    logger.info(
        "seed",
        f"演示账号注入完成（新增 {created} / 共 {len(_DEMO_USERS)}）",
        op_type="seed",
    )
    return existing


async def seed_invite_codes(session, users_by_phone: dict[str, User]) -> None:
    """注入演示邀请码（幂等：按码值查重）。"""
    admin = users_by_phone.get("13800000005")
    if admin is None:
        raise RuntimeError("演示管理员账号缺失，无法关联邀请码 created_by")

    result = await session.execute(select(InviteCode))
    existing_codes = {c.code for c in result.scalars().all()}

    created = 0
    expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    for code, channel, max_uses in _DEMO_INVITE_CODES:
        if code in existing_codes:
            continue
        session.add(
            InviteCode(
                code=code,
                channel=channel,
                max_uses=max_uses,
                used_count=0,
                expires_at=expires_at,
                status=InviteCodeStatus.ACTIVE,
                created_by=admin.id,
            )
        )
        created += 1

    await session.commit()
    logger.info(
        "seed",
        f"演示邀请码注入完成（新增 {created} / 共 {len(_DEMO_INVITE_CODES)}）",
        op_type="seed",
    )


async def clean_auth_domain(session) -> None:
    """清空认证域数据（--clean 模式）。"""
    from sqlalchemy import text

    await session.execute(text("TRUNCATE users, credentials, invite_codes CASCADE"))
    await session.commit()
    logger.info("seed", "认证域数据已清空", op_type="seed")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Campfire-AI 种子注入")
    parser.add_argument("--clean", action="store_true", help="清空认证域数据后重新注入")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        if args.clean:
            await clean_auth_domain(session)
        users = await seed_users(session)
        await seed_invite_codes(session, users)

    await engine.dispose()
    print("种子注入完成。演示账号：13800000001~13800000006（family/volunteer/teacher/expert/admin/maintainer）")
    print("演示邀请码：DEMAND26AA/DEMAND26AB（需求侧），SUPPLY26AA/SUPPLY26AB（供给侧）")


if __name__ == "__main__":
    asyncio.run(main())
