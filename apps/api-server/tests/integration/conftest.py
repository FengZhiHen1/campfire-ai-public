"""认证集成测试 — 独立测试库与 Redis 隔离（ADR-013 全链路）。

环境策略（自主决策：环境缺失自愈）：
- 使用独立测试库 campfire_test（不污染开发库），session 级建库 + 迁移链全量执行
- Redis 使用 DB 1 隔离（开发面在 DB 0）
- PostgreSQL/Redis 不可达时整个集成套件标记 skip，绝不伪造通过
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# 环境变量必须在 import app 之前设置（py_config 有 lru_cache）
# ---------------------------------------------------------------------------


def _resolve_test_db_url() -> str | None:
    """从开发配置派生测试库连接串（库名替换为 campfire_test）。"""
    try:
        from py_config import get_settings

        url = str(get_settings().DATABASE_URL)
    except Exception:
        return None
    base = url.rsplit("/", 1)[0]
    return f"{base}/campfire_test"


def _resolve_test_redis_url() -> str | None:
    try:
        from py_config import get_settings

        url = str(get_settings().REDIS_URL)
    except Exception:
        return None
    base = url.rsplit("/", 1)[0]
    return f"{base}/1"


_TEST_DB_URL = _resolve_test_db_url()
_TEST_REDIS_URL = _resolve_test_redis_url()

if _TEST_DB_URL:
    os.environ["DATABASE_URL"] = _TEST_DB_URL
if _TEST_REDIS_URL:
    os.environ["REDIS_URL"] = _TEST_REDIS_URL

# get_settings 在上方探测时已触发 lru_cache 缓存——重载测试库配置前必须清缓存
from py_config import get_settings as _get_settings  # noqa: E402

_get_settings.cache_clear()


def _infra_available() -> bool:
    """探测 PostgreSQL / Redis 可达性。"""
    if not _TEST_DB_URL or not _TEST_REDIS_URL:
        return False
    try:
        import psycopg2

        conn = psycopg2.connect(_TEST_DB_URL.replace("+asyncpg", "").replace("campfire_test", "campfire"))
        conn.close()
    except Exception:
        return False
    try:
        import redis

        r = redis.from_url(_TEST_REDIS_URL, socket_timeout=2)
        r.ping()
        r.close()
    except Exception:
        return False
    return True


INFRA_AVAILABLE = _infra_available()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def integration_client():
    """session 级 TestClient：建测试库 → 迁移链全量执行 → TestClient。

    PostgreSQL/Redis 不可达时 skip（环境缺失自愈，不伪造通过）。
    """
    if not INFRA_AVAILABLE:
        pytest.skip("集成测试依赖 PostgreSQL/Redis（docker compose up -d）")

    import psycopg2

    # 建测试库（幂等）
    admin_url = _TEST_DB_URL.replace("+asyncpg", "").replace("/campfire_test", "/campfire")
    conn = psycopg2.connect(admin_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'campfire_test'")
        if cur.fetchone() is None:
            cur.execute("CREATE DATABASE campfire_test")
    conn.close()

    # 迁移链全量执行（全新迁移链从头干净通过的运行时验证）
    import alembic.command
    import alembic.config

    alembic_cfg = alembic.config.Config(str(_alembic_ini_path()))
    alembic_cfg.set_main_option("sqlalchemy.url", _TEST_DB_URL.replace("+asyncpg", ""))
    # script_location 相对 ini 目录，显式转为绝对路径（pytest 运行目录不确定）
    alembic_cfg.set_main_option(
        "script_location",
        str(_alembic_ini_path().parent / "py_db" / "migrations"),
    )
    alembic.command.upgrade(alembic_cfg, "head")

    from app.main import app
    from fastapi.testclient import TestClient

    # 集成测试注入 TestModel（不依赖外部 LLM；真实 DeepSeek 路径已由冒烟验证）
    from pydantic_ai.models.test import TestModel

    app.state.emergency_model_factory = TestModel

    with TestClient(app) as client:
        yield client

    # session 结束清理测试库
    conn = psycopg2.connect(admin_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'campfire_test' AND pid <> pg_backend_pid()"
        )
        cur.execute("DROP DATABASE IF EXISTS campfire_test")
    conn.close()


def _alembic_ini_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[4] / "packages" / "py-db" / "alembic.ini"


@pytest.fixture
def clean_auth_tables(integration_client):
    """function 级：清空认证三表 + 测试 Redis DB，保证用例隔离。"""
    import psycopg2
    import redis

    url = _TEST_DB_URL.replace("+asyncpg", "")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE users, credentials, invite_codes CASCADE")
    conn.close()

    r = redis.from_url(_TEST_REDIS_URL)
    r.flushdb()
    r.close()

    return integration_client


@pytest.fixture
def seed_safety_cards(clean_auth_tables):
    """应急测试前置：清空应急四表并注入安全卡模板。"""
    import psycopg2

    conn = psycopg2.connect(_TEST_DB_URL.replace("+asyncpg", ""))
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE consultation_sessions, consultations, safety_cards, consultation_logs CASCADE")
        cur.execute(
            """
            INSERT INTO safety_cards (id, bucket, crisis_stage, title, card_template, review_status, version, created_at, updated_at)
            VALUES
              (gen_random_uuid(), NULL, NULL, '通用安全卡', '移走危险物品。保持冷静。', 'approved', 1, now(), now()),
              (gen_random_uuid(), '情绪崩溃', NULL, '情绪哭闹·通用卡', '保持安静陪伴。递上 {安抚物}。', 'approved', 1, now(), now()),
              (gen_random_uuid(), '情绪崩溃', '触发', '情绪哭闹·触发期', '移走 {触发物}。', 'approved', 1, now(), now()),
              (gen_random_uuid(), '刻板行为', NULL, '刻板升级·通用卡', '不打断，先观察。', 'approved', 1, now(), now()),
              (gen_random_uuid(), '自伤', NULL, '自伤高危桶卡', '用软垫挡住撞击部位。', 'approved', 1, now(), now()),
              (gen_random_uuid(), '走失', NULL, '走失应急卡', '立即报警：我的孩子{称呼}走失了。', 'approved', 1, now(), now())
            ON CONFLICT DO NOTHING
            """
        )
    conn.close()
    return clean_auth_tables


@pytest.fixture
def admin_headers(clean_auth_tables):
    """直写 DB 创建 admin 账号并登录，返回认证头。"""
    return _seed_admin_and_login(clean_auth_tables)


def _seed_admin_and_login(client):
    """直写 DB 创建 admin（admin 不开放注册，机制 §3.2）并登录。"""
    import psycopg2
    from py_auth.hashing import hash_password

    url = _TEST_DB_URL.replace("+asyncpg", "")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    admin_id = "00000000-0000-4000-8000-0000000000ad"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (id, phone, real_name, role, status, created_at, updated_at)
            VALUES (%s, '19900000001', '管理员', 'admin', 'active', now(), now())
            ON CONFLICT (phone) DO NOTHING
            """,
            (admin_id,),
        )
        cur.execute(
            """
            INSERT INTO credentials (id, user_id, type, identifier, secret, created_at)
            VALUES (gen_random_uuid(), %s, 'password', '19900000001', %s, now())
            ON CONFLICT (type, identifier) DO NOTHING
            """,
            (admin_id, hash_password("Admin12345")),
        )
    conn.close()

    resp = client.post("/api/v1/auth/login", json={"phone": "19900000001", "password": "Admin12345"})
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}
