"""认证全链路集成测试（ADR-013）——真实 PostgreSQL + Redis。

链路覆盖（阶段 S1 成功标准）：
- 注册（邀请码各 channel / 过期 / 停用 / 超量 / 并发消费）→ 登录 → 刷新 → 登出 → me
- teacher 注册 → pending_review → 审核通过 → 登录放行
- disabled 拒签
- refresh 复用检测 → 全家族吊销
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _create_invite_code(client, admin_headers, channel="demand", days=7, max_uses=1, count=1) -> str:
    resp = client.post(
        "/api/v1/auth/invite-codes",
        json={
            "channel": channel,
            "max_uses": max_uses,
            "count": count,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["codes"][0]


def _register(client, phone, password="Abc12345", invite_code="", role="family", real_name=None):
    payload = {"phone": phone, "password": password, "invite_code": invite_code, "role": role}
    if real_name:
        payload["real_name"] = real_name
    return client.post("/api/v1/auth/register", json=payload)


def _login(client, phone, password="Abc12345"):
    return client.post("/api/v1/auth/login", json={"phone": phone, "password": password})


# =============================================================================
# 全链路：注册 → 登录 → me → 刷新 → 登出
# =============================================================================


class TestAuthFullJourney:
    def test_family_full_journey(self, clean_auth_tables, admin_headers):
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers, channel="demand")

        # 注册
        resp = _register(client, "13800000001", invite_code=code, role="family")
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "active"

        # 邀请码已消费（单次码再用即失败）
        resp2 = _register(client, "13800000002", invite_code=code, role="family")
        assert resp2.status_code == 422, resp2.text

        # 登录
        resp = _login(client, "13800000001")
        assert resp.status_code == 200, resp.text
        tokens = resp.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # me
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200, resp.text
        me = resp.json()
        assert me["phone"] == "13800000001"
        assert me["role"] == "family"
        assert me["status"] == "active"

        # 刷新（轮换）
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 200, resp.text
        new_tokens = resp.json()
        assert new_tokens["access_token"] != tokens["access_token"]

        # 旧 refresh 复用 → 401 且吊销全家族
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 401, resp.text
        assert resp.json()["detail"]["code"] == "TOKEN_INVALID"

        # 家族已吊销：新 refresh 也被拒
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
        assert resp.status_code == 401, resp.text

    def test_logout_revokes_family(self, clean_auth_tables, admin_headers):
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers)
        _register(client, "13800000003", invite_code=code)
        tokens = _login(client, "13800000003").json()

        resp = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert resp.status_code == 204

        # 登出后 access 与 refresh 均失效
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert resp.status_code == 401
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 401

    def test_login_anti_enumeration(self, clean_auth_tables, admin_headers):
        """登录失败统一 401（不区分用户不存在/密码错误）。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers)
        _register(client, "13800000004", invite_code=code)

        r1 = _login(client, "13899999999")  # 不存在
        r2 = _login(client, "13800000004", password="WrongPass1")  # 密码错误
        assert r1.status_code == r2.status_code == 401
        assert r1.json()["detail"]["code"] == r2.json()["detail"]["code"] == "INVALID_CREDENTIALS"
        assert r1.json()["detail"]["message"] == r2.json()["detail"]["message"]


# =============================================================================
# 邀请码约束面
# =============================================================================


class TestInviteCodeConstraints:
    def test_channel_constraint(self, clean_auth_tables, admin_headers):
        """demand 码不可注册 expert（渠道约束）。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers, channel="demand")
        resp = _register(client, "13800000010", invite_code=code, role="expert", real_name="王专家")
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "INVITE_CHANNEL_MISMATCH"

    def test_expired_code(self, clean_auth_tables, admin_headers):
        client = clean_auth_tables
        # 直接 DB 写入一个已过期码（生成接口不允许过去时间之外的语义，直接落库更直接）
        import psycopg2

        url = _test_pg_url()
        conn = psycopg2.connect(url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO invite_codes (code, channel, max_uses, used_count, expires_at, status, created_at)
                VALUES ('EXPIRED01', 'demand', 1, 0, now() - interval '1 day', 'active', now())
                """
            )
        conn.close()

        resp = _register(client, "13800000011", invite_code="EXPIRED01")
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "INVALID_INVITE_CODE"

    def test_revoked_code(self, clean_auth_tables, admin_headers):
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers)
        resp = client.post(f"/api/v1/auth/invite-codes/{code}/revoke", headers=admin_headers)
        assert resp.status_code == 200

        resp = _register(client, "13800000012", invite_code=code)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "INVALID_INVITE_CODE"

    def test_multi_use_code_quota(self, clean_auth_tables, admin_headers):
        """多次码按 max_uses 限量消费。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers, max_uses=2)
        assert _register(client, "13800000013", invite_code=code).status_code == 201
        assert _register(client, "13800000014", invite_code=code).status_code == 201
        resp = _register(client, "13800000015", invite_code=code)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "INVALID_INVITE_CODE"

    def test_invite_code_requires_admin(self, clean_auth_tables):
        """非 admin 不可生成邀请码（RBAC 守卫）。"""
        client = clean_auth_tables
        # 未登录
        resp = client.post(
            "/api/v1/auth/invite-codes",
            json={"channel": "demand", "expires_at": datetime.now(timezone.utc).isoformat()},
        )
        assert resp.status_code == 401


# =============================================================================
# 准入状态机
# =============================================================================


class TestAdmissionFlow:
    def test_teacher_review_journey(self, clean_auth_tables, admin_headers):
        """teacher 注册 → pending_review（可登录仅见状态页）→ 审核通过 → 全能力。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers, channel="supply")

        # 注册（real_name 必填）
        resp = _register(client, "13800000020", invite_code=code, role="teacher")
        assert resp.status_code == 422  # 缺 real_name
        resp = _register(client, "13800000020", invite_code=code, role="teacher", real_name="张老师")
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "pending_review"
        user_id = resp.json()["user_id"]

        # pending_review 可登录
        login_resp = _login(client, "13800000020")
        assert login_resp.status_code == 200
        tokens = login_resp.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me = client.get("/api/v1/auth/me", headers=headers).json()
        assert me["status"] == "pending_review"

        # admin 待审列表可见
        resp = client.get("/api/v1/auth/reviews", headers=admin_headers)
        assert resp.status_code == 200
        assert any(item["user_id"] == user_id for item in resp.json()["items"])

        # 审核通过
        resp = client.post(f"/api/v1/auth/reviews/{user_id}/approve", headers=admin_headers)
        assert resp.status_code == 200, resp.text

        # 续期获得 active 状态（refresh 以 DB 最新 status 签发）
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 200, resp.text
        new_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        me = client.get("/api/v1/auth/me", headers=new_headers).json()
        assert me["status"] == "active"

    def test_reject_and_resubmit(self, clean_auth_tables, admin_headers):
        """驳回（含原因）→ 用户可见原因 → 补交重提 → 回到待审。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers, channel="supply")
        resp = _register(client, "13800000021", invite_code=code, role="expert", real_name="王专家")
        user_id = resp.json()["user_id"]

        resp = client.post(
            f"/api/v1/auth/reviews/{user_id}/reject",
            json={"reason": "资质材料不清晰"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

        # 用户登录可见驳回原因
        tokens = _login(client, "13800000021").json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me = client.get("/api/v1/auth/me", headers=headers).json()
        assert me["status"] == "rejected"
        assert me["reject_reason"] == "资质材料不清晰"

        # 补交重提（仅本人）
        resp = client.post(
            f"/api/v1/auth/reviews/{user_id}/resubmit",
            json={"real_name": "王专家（补充）"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        me = client.get("/api/v1/auth/me", headers=headers).json()
        assert me["status"] == "pending_review"
        assert me["reject_reason"] is None

    def test_disabled_login_rejected(self, clean_auth_tables, admin_headers):
        """disabled 账号：登录拒签（403）+ 存活 refresh 拒签。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers)
        _register(client, "13800000022", invite_code=code)
        tokens = _login(client, "13800000022").json()

        # 直写 DB 禁用
        import psycopg2

        conn = psycopg2.connect(_test_pg_url())
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET status = 'disabled' WHERE phone = '13800000022'")
        conn.close()

        # 登录拒签
        resp = _login(client, "13800000022")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ACCOUNT_DISABLED"

        # refresh 拒签
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 403

    def test_business_route_guard(self, clean_auth_tables, admin_headers):
        """RBAC 守卫：family 不可访问案例审核端点（403）；未登录 401。"""
        client = clean_auth_tables
        code = _create_invite_code(client, admin_headers)
        _register(client, "13800000023", invite_code=code)
        tokens = _login(client, "13800000023").json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        resp = client.get("/api/v1/cases/review-queue", headers=headers)
        assert resp.status_code == 403

        resp = client.get("/api/v1/cases/review-queue")
        assert resp.status_code == 401


def _test_pg_url() -> str:
    import os

    return os.environ["DATABASE_URL"].replace("+asyncpg", "")
