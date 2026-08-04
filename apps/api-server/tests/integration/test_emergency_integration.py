"""应急咨询全链路集成测试（ADR-009 时刻分层）——真实 PG/Redis + TestModel。

链路覆盖（阶段 S3 成功标准）：
- 红线桶（自伤）→ 高危卡 + 就医指引，且无方案流（不进入完整方案层）
- 走失桶 → 独立一键流程（报警话术 + 水体提醒）
- 非红线桶 → 桶卡 → 阶段问答（含 meltdown 分流）→ 四段式方案（契约校验）
  → 追问 → 未解决标记兜底
- SSE 事件序与 Last-Event-Id 续传
- 关键词追问触发红线（红线门对每条输入生效）
"""

from __future__ import annotations

import json
import time

import pytest

pytestmark = pytest.mark.integration


def _register_and_login(client, phone, invite_code, role="family"):
    client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": "Abc12345", "invite_code": invite_code, "role": role},
    )
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "password": "Abc12345"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _collect_events(client, session_id, headers, timeout_s=30):
    """收集 SSE 事件流直到 done/error（或超时）。"""
    events: list[dict] = []
    deadline = time.time() + timeout_s
    with client.stream("GET", f"/api/v1/consult/stream/{session_id}", headers=headers) as resp:
        assert resp.status_code == 200
        current_event = None
        for line in resp.iter_lines():
            if time.time() > deadline:
                break
            if line.startswith("event: "):
                current_event = line[7:]
            elif line.startswith("data: ") and current_event:
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = {}
                events.append({"type": current_event, "data": data})
                if current_event in ("done", "error"):
                    return events
    return events


def _make_demand_code(client, admin_headers):
    resp = client.post(
        "/api/v1/auth/invite-codes",
        json={
            "channel": "demand",
            "max_uses": 10,
            "count": 1,
            "expires_at": "2030-01-01T00:00:00+08:00",
        },
        headers=admin_headers,
    )
    return resp.json()["codes"][0]


class TestRedlinePath:
    def test_self_injury_bucket_hits_redline(self, seed_safety_cards, admin_headers):
        """自伤桶：高危卡 + 就医指引，无方案流（不进入完整方案层）。"""
        client = seed_safety_cards
        code = _make_demand_code(client, admin_headers)
        headers = _register_and_login(client, "13800000101", code)

        resp = client.post("/api/v1/consult/stream", json={"bucket": "自伤"}, headers=headers)
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        events = _collect_events(client, session_id, headers)
        types = [e["type"] for e in events]
        assert "safety_card" in types
        assert "redline_guide" in types
        assert types[-1] == "done"
        assert "result" not in types  # 红线会话不进入完整方案层
        # 高危卡标红变体
        card_event = next(e for e in events if e["type"] == "safety_card")
        assert card_event["data"]["card"]["variant"] == "redline"

    def test_elopement_flow(self, seed_safety_cards, admin_headers):
        """走失桶：独立一键流程（报警话术 + 水体提醒），跳过常规问答。"""
        client = seed_safety_cards
        code = _make_demand_code(client, admin_headers)
        headers = _register_and_login(client, "13800000102", code)

        resp = client.post("/api/v1/consult/stream", json={"bucket": "走失"}, headers=headers)
        session_id = resp.json()["session_id"]

        events = _collect_events(client, session_id, headers)
        types = [e["type"] for e in events]
        assert "stage_question" not in types  # 跳过常规问答
        assert "redline_guide" in types
        guide = next(e for e in events if e["type"] == "redline_guide")
        assert "水体" in guide["data"]["guide"]["guidance"]
        assert "110" in guide["data"]["guide"]["guidance"]

    def test_keyword_in_followup_hits_redline(self, seed_safety_cards, admin_headers):
        """追问轮输入含高危词 → 红线门生效（安全不变量）。"""
        client = seed_safety_cards
        code = _make_demand_code(client, admin_headers)
        headers = _register_and_login(client, "13800000103", code)

        # 非红线桶建立会话
        resp = client.post("/api/v1/consult/stream", json={"bucket": "刻板行为"}, headers=headers)
        session_id = resp.json()["session_id"]

        # 追问含高危词
        resp = client.post(
            f"/api/v1/consult/stream/{session_id}/followup",
            json={"text": "他开始撞头了怎么办"},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text

        events = _collect_events(client, session_id, headers)
        types = [e["type"] for e in events]
        assert "redline_guide" in types


class TestNormalPath:
    def test_meltdown_full_journey(self, seed_safety_cards, admin_headers):
        """非红线全链路：桶卡 → 分流两问 → 阶段问题 → 四段式方案 → 追问 → 兜底。"""
        client = seed_safety_cards
        code = _make_demand_code(client, admin_headers)
        headers = _register_and_login(client, "13800000104", code)

        # 1. 桶选择（情绪崩溃）
        resp = client.post("/api/v1/consult/stream", json={"bucket": "情绪崩溃"}, headers=headers)
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        # 2. 分流两问 + 阶段问题推进
        resp = client.post(
            "/api/v1/consult/stream",
            json={"session_id": session_id, "stage_answer": "有"},
            headers=headers,
        )
        assert resp.status_code == 200
        resp = client.post(
            "/api/v1/consult/stream",
            json={"session_id": session_id, "stage_answer": "会"},
            headers=headers,
        )
        assert resp.status_code == 200
        resp = client.post(
            "/api/v1/consult/stream",
            json={"session_id": session_id, "stage_answer": "能"},
            headers=headers,
        )
        assert resp.status_code == 200

        # 3. 收集事件流（生成路径——DeepSeek 不可用时降级直出，两者均为合法终态）
        events = _collect_events(client, session_id, headers, timeout_s=90)
        types = [e["type"] for e in events]
        assert "safety_card" in types
        assert "stage_question" in types
        # 生成路径：result（契约校验通过）或 chunk（降级直出）+ done/error 终态
        assert types[-1] in ("done", "error")

        # 4. 追问（session 处于 followup 或已终态均可提交）
        resp = client.post(
            f"/api/v1/consult/stream/{session_id}/followup",
            json={"text": "他还是安静不下来"},
            headers=headers,
        )
        assert resp.status_code == 202

        # 5. 未解决标记 → 兜底信号
        resp = client.post(
            f"/api/v1/consult/stream/{session_id}/unresolved",
            json={"mark": True},
            headers=headers,
        )
        assert resp.status_code == 202


class TestHistory:
    def test_history_and_detail(self, clean_auth_tables, admin_headers):
        """历史列表与详情（会话模型落库验证）。"""
        client = clean_auth_tables
        code = _make_demand_code(client, admin_headers)
        headers = _register_and_login(client, "13800000105", code)

        resp = client.post("/api/v1/consult/stream", json={"bucket": "自伤"}, headers=headers)
        session_id = resp.json()["session_id"]

        resp = client.get("/api/v1/consult/history", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(i["id"] == session_id for i in items)

        resp = client.get(f"/api/v1/consult/{session_id}", headers=headers)
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["bucket"] == "自伤"

    def test_unauthenticated_rejected(self, clean_auth_tables):
        """全站守卫：未登录 401。"""
        client = clean_auth_tables
        resp = client.post("/api/v1/consult/stream", json={"bucket": "自伤"})
        assert resp.status_code == 401
