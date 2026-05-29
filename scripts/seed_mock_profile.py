#!/usr/bin/env python3
"""Mock 档案与用户种子脚本。

为开发/预览环境插入一条固定的 mock 用户 + mock 档案，
让前端使用固定 device_id 直接绑定此账户，无需注册流程。

用法:
    uv run scripts/seed_mock_profile.py
    uv run scripts/seed_mock_profile.py --clean   # 先删除旧 mock 数据再插入
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone

import asyncpg
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# Mock 数据定义
# ---------------------------------------------------------------------------

MOCK_DEVICE_ID: str = "campfire-mock-device"
MOCK_USERNAME: str = "campfire-mock-device"
MOCK_PHONE: str = "13800138000"

# 与 anonymous_user.py 中一致的占位 hash，避免 bcrypt 校验问题
_ANON_PASSWORD_HASH: str = (
    "$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
)

MOCK_PROFILE = {
    "nickname": "小明",
    "birth_date": date(2018, 6, 1),
    "diagnosis_type": "ASD",
    "primary_behavior": "情绪崩溃",
    "language_level": "短句",
    "sensory_features": ["听觉敏感", "触觉敏感"],
    "triggers": ["噪音", "环境变化"],
    "medication_notes": "利培酮每日 0.5mg",
    "is_default": True,
}

# ---------------------------------------------------------------------------
# 数据库操作
# ---------------------------------------------------------------------------

async def _ensure_user(conn: asyncpg.Connection) -> uuid.UUID:
    """查找或创建 mock 用户，返回 user_id。"""
    row = await conn.fetchrow(
        "SELECT id FROM users WHERE device_id = $1",
        MOCK_DEVICE_ID,
    )
    if row:
        user_id = row["id"]
        print(f"[mock] 用户已存在: {user_id}")
        return user_id

    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO users (id, username, password_hash, role, phone, device_id, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        user_id,
        MOCK_USERNAME,
        _ANON_PASSWORD_HASH,
        "family",
        MOCK_PHONE,
        MOCK_DEVICE_ID,
        now,
        now,
    )
    print(f"[mock] 用户已创建: {user_id}")
    return user_id


async def _ensure_profile(conn: asyncpg.Connection, caregiver_id: uuid.UUID) -> uuid.UUID:
    """查找或创建 mock 档案，返回 profile_id。"""
    row = await conn.fetchrow(
        "SELECT profile_id FROM profiles WHERE caregiver_id = $1 AND nickname = $2",
        caregiver_id,
        MOCK_PROFILE["nickname"],
    )
    if row:
        profile_id = row["profile_id"]
        print(f"[mock] 档案已存在: {profile_id}")
        return profile_id

    profile_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO profiles (
            profile_id, caregiver_id, nickname, birth_date, diagnosis_type,
            primary_behavior, language_level, sensory_features, triggers,
            medication_notes, is_default, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        profile_id,
        caregiver_id,
        MOCK_PROFILE["nickname"],
        MOCK_PROFILE["birth_date"],
        MOCK_PROFILE["diagnosis_type"],
        MOCK_PROFILE["primary_behavior"],
        MOCK_PROFILE["language_level"],
        json.dumps(MOCK_PROFILE["sensory_features"], ensure_ascii=False),
        json.dumps(MOCK_PROFILE["triggers"], ensure_ascii=False),
        MOCK_PROFILE["medication_notes"],
        MOCK_PROFILE["is_default"],
        now,
        now,
    )
    print(f"[mock] 档案已创建: {profile_id}")
    return profile_id


async def _clean_mock_data(conn: asyncpg.Connection) -> None:
    """清理旧 mock 数据。"""
    user_row = await conn.fetchrow(
        "SELECT id FROM users WHERE device_id = $1",
        MOCK_DEVICE_ID,
    )
    if user_row:
        caregiver_id = user_row["id"]
        deleted_profiles = await conn.execute(
            "DELETE FROM profiles WHERE caregiver_id = $1",
            caregiver_id,
        )
        deleted_user = await conn.execute(
            "DELETE FROM users WHERE id = $1",
            caregiver_id,
        )
        print(f"[mock] 已清理旧数据: {deleted_profiles} | {deleted_user}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Mock 档案与用户种子脚本")
    parser.add_argument("--clean", action="store_true", help="先删除旧 mock 数据")
    args = parser.parse_args()

    dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    if not dsn:
        print("错误: DATABASE_URL 环境变量未设置", file=sys.stderr)
        return 1

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(dsn)

        if args.clean:
            await _clean_mock_data(conn)

        async with conn.transaction():
            user_id = await _ensure_user(conn)
            profile_id = await _ensure_profile(conn, user_id)

        print(f"\n✅ Mock 数据就绪")
        print(f"   Device ID : {MOCK_DEVICE_ID}")
        print(f"   User ID   : {user_id}")
        print(f"   Profile ID: {profile_id}")
        print(f"   昵称      : {MOCK_PROFILE['nickname']}")
        return 0

    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn:
            await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
