"""档案四层集成测试（ADR-010）——真实 PG/Redis。

覆盖（阶段 S4 成功标准）：
- 档案四层 CRUD（身份基础 + 危机预案）
- 事件双模式（一键打点 → 事后补全）
- 专业评估权限（老师可挂载不可改家属内容）
- 关联管理（邀请 → 访问 → 解除后立即拒绝）
- 槽位填充衔接 S3（有档案/空档案/事件推导兜底）
- 隐私断言：档案/事件无向量索引写入路径
"""

from __future__ import annotations

import pytest
from app.modules.emergency.stream_hub import StreamEvent

pytestmark = pytest.mark.integration


def _make_code(client, admin_headers, channel="demand", max_uses=10):
    resp = client.post(
        "/api/v1/auth/invite-codes",
        json={
            "channel": channel,
            "max_uses": max_uses,
            "count": 1,
            "expires_at": "2030-01-01T00:00:00+08:00",
        },
        headers=admin_headers,
    )
    return resp.json()["codes"][0]


def _register_login(client, phone, code, role="family", real_name=None):
    payload = {"phone": phone, "password": "Abc12345", "invite_code": code, "role": role}
    if real_name:
        payload["real_name"] = real_name
    client.post("/api/v1/auth/register", json=payload)
    resp = client.post("/api/v1/auth/login", json={"phone": phone, "password": "Abc12345"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_profile(client, headers, **crisis_plan) -> str:
    payload = {
        "identity": {
            "nickname": "小阳",
            "birth_date": "2016-06-15",
            "diagnosis_type": "ASD",
            "primary_behavior": "情绪崩溃",
            "triggers": ["噪音"],
        },
        "crisis_plan": crisis_plan or None,
    }
    resp = client.post("/api/v1/profiles", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["profile_id"]


class TestProfileCrud:
    def test_create_and_get_four_layers(self, clean_auth_tables, admin_headers):
        """四层档案创建与读取（含危机预案层字段）。"""
        client = clean_auth_tables
        code = _make_code(client, admin_headers)
        headers = _register_login(client, "13800000201", code)

        profile_id = _create_profile(
            client,
            headers,
            soothing_items=["降噪耳机"],
            avoid_list=["强行拥抱"],
            communication_methods=["短句"],
            physical_description="身高120cm，短发",
            familiar_places=["小区花园"],
        )

        resp = client.get(f"/api/v1/profiles/{profile_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        assert detail["identity"]["nickname"] == "小阳"
        assert detail["identity"]["primary_behavior"] == "情绪崩溃"
        assert detail["age_range"] == "学龄儿童(6-12岁)"
        assert detail["crisis_plan"]["soothing_items"] == ["降噪耳机"]
        assert detail["crisis_plan"]["physical_description"] == "身高120cm，短发"

    def test_family_isolation(self, clean_auth_tables, admin_headers):
        """隐私：非关联用户访问他人档案 404（存在性隐藏）。"""
        client = clean_auth_tables
        code = _make_code(client, admin_headers)
        owner = _register_login(client, "13800000202", code)
        other = _register_login(client, "13800000203", code)
        profile_id = _create_profile(client, owner)

        resp = client.get(f"/api/v1/profiles/{profile_id}", headers=other)
        assert resp.status_code == 404


class TestEventDualMode:
    def test_quick_log_and_complete(self, clean_auth_tables, admin_headers):
        """一键打点（仅 behavior_type）→ 事后补全（ABC 字段）。"""
        client = clean_auth_tables
        code = _make_code(client, admin_headers)
        headers = _register_login(client, "13800000204", code)
        profile_id = _create_profile(client, headers)

        # 一键打点
        resp = client.post(
            f"/api/v1/profiles/{profile_id}/events",
            json={"behavior_type": "情绪崩溃"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        event = resp.json()
        assert event["is_quick_log"] is True
        assert event["behavior_type"] == "情绪崩溃"

        # 事后补全
        resp = client.post(
            f"/api/v1/profiles/{profile_id}/events/{event['event_id']}/complete",
            json={
                "behavior_form": "尖叫",
                "intensity": "高",
                "antecedent_category": "感觉刺激",
                "consequence": "带离现场",
                "reaction": "逐渐平静",
                "outcome": "有效",
                "tags": ["商场"],
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        completed = resp.json()
        assert completed["is_quick_log"] is False
        assert completed["intensity"] == "高"
        assert completed["outcome"] == "有效"


class TestProfessionalNotes:
    def test_teacher_note_flow(self, clean_auth_tables, admin_headers):
        """老师关联后可挂载专业评估；不可新增/修改家属事件。"""
        client = clean_auth_tables
        demand_code = _make_code(client, admin_headers, "demand")
        supply_code = _make_code(client, admin_headers, "supply")

        owner = _register_login(client, "13800000205", demand_code)
        teacher = _register_login(client, "13800000206", supply_code, role="teacher", real_name="张老师")
        profile_id = _create_profile(client, owner)

        # 家属邀请老师
        resp = client.post(
            f"/api/v1/profiles/{profile_id}/access",
            json={"invitee_phone": "13800000206", "role": "teacher"},
            headers=owner,
        )
        assert resp.status_code == 201, resp.text

        # 家属打点
        event = client.post(
            f"/api/v1/profiles/{profile_id}/events",
            json={"behavior_type": "刻板行为"},
            headers=owner,
        ).json()

        # 老师挂载专业评估
        resp = client.post(
            f"/api/v1/profiles/{profile_id}/notes",
            json={
                "event_id": event["event_id"],
                "assessment": "感觉寻求行为，前庭刺激需求",
                "recommended_action": "提供替代性感官活动",
                "evidence_basis": "个案观察",
            },
            headers=teacher,
        )
        assert resp.status_code == 201, resp.text

        # 老师不可新增事件（隐私矩阵：老师以 Note 表达）
        resp = client.post(
            f"/api/v1/profiles/{profile_id}/events",
            json={"behavior_type": "刻板行为"},
            headers=teacher,
        )
        assert resp.status_code == 403

        # 老师不可补全家属事件
        resp = client.post(
            f"/api/v1/profiles/{profile_id}/events/{event['event_id']}/complete",
            json={"note": "试图修改"},
            headers=teacher,
        )
        assert resp.status_code in (403, 404)


class TestAccessManagement:
    def test_revoke_immediately_denies(self, clean_auth_tables, admin_headers):
        """解除关联后立即失去访问入口。"""
        client = clean_auth_tables
        demand_code = _make_code(client, admin_headers, "demand")
        supply_code = _make_code(client, admin_headers, "supply")

        owner = _register_login(client, "13800000207", demand_code)
        expert = _register_login(client, "13800000208", supply_code, role="expert", real_name="王专家")
        profile_id = _create_profile(client, owner)

        resp = client.post(
            f"/api/v1/profiles/{profile_id}/access",
            json={"invitee_phone": "13800000208", "role": "expert"},
            headers=owner,
        )
        access_id = resp.json()["access_id"]

        # 关联后专家可见
        resp = client.get(f"/api/v1/profiles/{profile_id}", headers=expert)
        assert resp.status_code == 200

        # 解除
        resp = client.delete(f"/api/v1/profiles/{profile_id}/access/{access_id}", headers=owner)
        assert resp.status_code == 204

        # 解除后立即 404
        resp = client.get(f"/api/v1/profiles/{profile_id}", headers=expert)
        assert resp.status_code == 404


class TestSlotFillingIntegration:
    """S3↔S4 衔接验证：经应急链路断言安全卡槽位填充内容。

    断言方式：直读 ConsultStreamHub 缓冲（不走 SSE 流）——TestClient 的
    transport 会等整个 ASGI app 协程完成才返回，非终态会话（桶卡发布后
    停在阶段问答等待）的 SSE 流永不结束，`client.stream()` 会永久挂起；
    hub 缓冲在 POST /stream 返回时已包含全部已发布事件（同步发布），
    直读断言同步、零阻塞且语义等价。
    """

    @staticmethod
    def _card_events(session_id: str) -> list[StreamEvent]:
        """读取 hub 缓冲中的安全卡事件。"""
        from app.modules.emergency.stream_hub import get_stream_hub

        stream = get_stream_hub().get_or_create(session_id)
        return [e for e in stream.events if e.event_type == "safety_card"]

    def test_snapshot_from_crisis_plan_layer(self, seed_safety_cards, admin_headers):
        """危机预案层字段 → 桶卡槽位填充（有档案路径）。"""
        client = seed_safety_cards
        code = _make_code(client, admin_headers)
        headers = _register_login(client, "13800000209", code)
        profile_id = _create_profile(
            client,
            headers,
            soothing_items=["降噪耳机"],
            avoid_list=["强行拥抱"],
            physical_description="身高120cm",
        )

        # 发起应急咨询（非红线桶）→ 桶卡槽位填充
        resp = client.post(
            "/api/v1/consult/stream",
            json={"bucket": "情绪崩溃", "profile_id": profile_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        card_events = self._card_events(session_id)
        assert card_events, "应至少产出一张安全卡"
        card = card_events[0].data["card"]
        assert "降噪耳机" in card["content"]  # {安抚物} 槽位已填充
        assert card["personalized"] is True

    def test_event_derivation_fallback(self, seed_safety_cards, admin_headers):
        """soothing_items 空 → 最近 outcome=有效 事件推导兜底。"""
        client = seed_safety_cards
        code = _make_code(client, admin_headers)
        headers = _register_login(client, "13800000210", code)
        profile_id = _create_profile(client, headers)  # 无危机预案

        # 打点 + 补全（outcome=有效 + consequence）
        event = client.post(
            f"/api/v1/profiles/{profile_id}/events",
            json={"behavior_type": "情绪崩溃"},
            headers=headers,
        ).json()
        client.post(
            f"/api/v1/profiles/{profile_id}/events/{event['event_id']}/complete",
            json={"consequence": "播放白噪音", "outcome": "有效"},
            headers=headers,
        )

        resp = client.post(
            "/api/v1/consult/stream",
            json={"bucket": "情绪崩溃", "profile_id": profile_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        card_events = self._card_events(session_id)
        assert card_events
        assert "播放白噪音" in card_events[0].data["card"]["content"]

    def test_empty_profile_returns_pure_template_path(self, seed_safety_cards, admin_headers):
        """空档案（无预案无事件）→ 纯模板回退（占位符保留）。"""
        client = seed_safety_cards
        code = _make_code(client, admin_headers)
        headers = _register_login(client, "13800000211", code)
        profile_id = _create_profile(client, headers)

        resp = client.post(
            "/api/v1/consult/stream",
            json={"bucket": "情绪崩溃", "profile_id": profile_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        card_events = self._card_events(session_id)
        assert card_events
        card = card_events[0].data["card"]
        assert "{安抚物}" in card["content"]  # 未填充——纯模板回退
        assert card["personalized"] is False


class TestPrivacyAssertion:
    def test_profile_data_not_in_vector_index(self, clean_auth_tables, admin_headers):
        """隐私断言：档案/事件数据无向量索引写入路径（case_chunks 无 profile 引用）。"""
        import psycopg2

        client = clean_auth_tables
        code = _make_code(client, admin_headers)
        headers = _register_login(client, "13800000212", code)
        profile_id = _create_profile(client, headers)
        client.post(
            f"/api/v1/profiles/{profile_id}/events",
            json={"behavior_type": "情绪崩溃", "note": "尖叫内容不应入索引"},
            headers=headers,
        )

        import os

        conn = psycopg2.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
        cur = conn.cursor()
        # case_chunks 是向量索引唯一宿主；断言其内容不含档案/事件文本
        cur.execute("SELECT count(*) FROM case_chunks WHERE chunk_text LIKE '%尖叫内容不应入索引%'")
        assert cur.fetchone()[0] == 0
        conn.close()
