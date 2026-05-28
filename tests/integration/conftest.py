"""MVP 核心路径集成测试 — 共享 fixture。

提供 FastAPI TestClient 和数据库连接，支持 sync 测试函数直接调用 API。
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import asyncpg
import pytest
from dotenv import load_dotenv

# 将 api-server 和 packages 加入 Python 路径
_project_root = os.path.join(os.path.dirname(__file__), "../..")
sys.path.insert(0, os.path.join(_project_root, "apps/api-server"))

# 加载环境变量（SecurityConfig 依赖 .env 中的 JWT 密钥）
load_dotenv(os.path.join(_project_root, ".env"))

for pkg in [
    "packages/py-config",
    "packages/py-db",
    "packages/py-schemas",
    "packages/py-rag",
    "packages/py-llm",
    "packages/py-cache",
    "packages/py-storage",
    "packages/py-auth",
    "packages/py-logger",
    "packages/py-security",
    "packages/py-infra",
    "packages/py-health",
]:
    sys.path.insert(0, os.path.join(_project_root, pkg))


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient（sync）。

    内部自动管理事件循环，调用 async 路由。
    必须使用上下文管理器 yield，确保 blocking portal 生命周期正确。
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def database_url() -> str:
    """从环境变量读取数据库连接串。"""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL 未设置，跳过集成测试")
    return url


def _raw_pg_url(url: str) -> str:
    """将 SQLAlchemy asyncpg DSN 转换为裸 asyncpg DSN。"""
    return str(url).replace("postgresql+asyncpg://", "postgresql://")


async def _db_fetchval(database_url: str, sql: str, *args: Any) -> Any:
    """执行单条 SQL 并返回标量结果。"""
    conn = await asyncpg.connect(_raw_pg_url(database_url))
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


async def _db_fetch(database_url: str, sql: str, *args: Any) -> list[asyncpg.Record]:
    """执行 SQL 并返回记录列表。"""
    conn = await asyncpg.connect(_raw_pg_url(database_url))
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture
def db_fetchval(database_url: str):
    """提供 sync 包装的数据库单值查询函数。"""

    def _wrapper(sql: str, *args: Any) -> Any:
        return asyncio.run(_db_fetchval(database_url, sql, *args))

    return _wrapper


@pytest.fixture
def db_fetch(database_url: str):
    """提供 sync 包装的数据库列表查询函数。"""

    def _wrapper(sql: str, *args: Any) -> list[asyncpg.Record]:
        return asyncio.run(_db_fetch(database_url, sql, *args))

    return _wrapper


@pytest.fixture(autouse=True)
def clear_tables(database_url: str):
    """每个测试前清理测试数据并重置序列。"""

    async def _clear() -> None:
        conn = await asyncpg.connect(_raw_pg_url(database_url))
        try:
            # 删除测试创建的案例、档案和用户
            await conn.execute("DELETE FROM cases WHERE case_id LIKE 'CASE-2026-%'")
            await conn.execute("DELETE FROM profiles WHERE caregiver_id IN (SELECT id FROM users WHERE device_id LIKE 'test-device-%')")
            await conn.execute("DELETE FROM users WHERE device_id LIKE 'test-device-%' OR device_id LIKE 'reviewer-%'")
            # 重置序列到已用最大值之后
            max_seq = await conn.fetchval(
                "SELECT COALESCE(MAX(NULLIF(regexp_replace(case_id, '.*-', '', 'g'), '')::int), 0) FROM cases WHERE case_id ~ 'CASE-[0-9]{4}-[0-9]+$'"
            )
            await conn.execute(f"SELECT setval('case_id_seq', GREATEST({max_seq}, 1), true)")
        finally:
            await conn.close()

    asyncio.run(_clear())
