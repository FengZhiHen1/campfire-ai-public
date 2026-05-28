"""MVP 核心路径集成测试。

覆盖 3 条核心链路：
1. 案例完整生命周期（创建 → 提交审核 → 通过 → 状态验证）
2. 档案 CRUD（创建 → 更新 → 查询）
3. 案例列表筛选（按 behavior_type 筛选）

要求：本地 PostgreSQL + Redis 服务已启动（docker compose up -d）。
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# 测试用例 1：案例完整生命周期
# ---------------------------------------------------------------------------


def test_case_lifecycle(client, db_fetchval, db_fetch):
    """案例从创建到审核通过的完整链路。"""
    device_id = "test-device-seed"
    headers = {"X-Device-Id": device_id}

    # 1. 创建案例
    create_res = client.post(
        "/api/v1/cases",
        json={
            "title": "集成测试案例",
            "behavior_type": "自伤",
            "severity": "重度",
            "scene": "家庭",
            "immediate_action": "立即阻止自伤动作",
            "comforting_phrase": "没关系，我陪着你",
            "observation_metrics": "观察情绪恢复时间",
            "medical_criteria": "出现伤口立即就医",
            "evidence_level": "机构经验总结",
        },
        headers=headers,
    )
    assert create_res.status_code == 201, f"创建案例失败: {create_res.text}"
    case_id = create_res.json()["case_id"]
    assert case_id.startswith("CASE-")

    # 2. 提交审核（确认 PII 已处理，避免默认 narrative "待补充" 被误检为真实姓名）
    submit_res = client.post(
        f"/api/v1/cases/{case_id}/submit?pii_confirmed=true",
        headers=headers,
    )
    assert submit_res.status_code == 200, f"提交审核失败: {submit_res.text}"
    assert submit_res.json()["status"] == "pending_review"

    # 3. 审核通过（使用另一个 device_id 避免自审限制）
    reviewer_headers = {"X-Device-Id": "reviewer-abc-123"}
    review_res = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={"decision": "approved"},
        headers=reviewer_headers,
    )
    assert review_res.status_code == 200, f"审核通过失败: {review_res.text}"
    assert review_res.json()["new_status"] == "approved"

    # 4. 数据库验证：状态为 approved
    db_status = db_fetchval("SELECT status FROM cases WHERE case_id = $1", case_id)
    assert db_status == "approved"

    # 5. Redis 队列验证：存在索引任务
    import redis
    import os

    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        r = redis.from_url(redis_url, decode_responses=True)
        try:
            queue_len = r.llen("campfire:case_index")
            assert queue_len >= 1, "Redis 索引队列应至少有一条任务"
        finally:
            r.close()

    print(f"✅ 案例生命周期测试通过: {case_id}")


# ---------------------------------------------------------------------------
# 测试用例 2：档案 CRUD
# ---------------------------------------------------------------------------


def test_profile_crud(client):
    """档案创建、更新、查询链路。"""
    device_id = "test-device-profile"
    headers = {"X-Device-Id": device_id}

    # 1. 创建档案
    create_res = client.post(
        "/api/v1/profiles",
        json={
            "birth_date": "2019-03-15",
            "diagnosis_type": "ASD",
            "primary_behavior": "刻板行为",
            "sensory_features": ["听觉敏感"],
            "triggers": ["噪音"],
            "medication_notes": "对尖锐声音敏感",
        },
        headers=headers,
    )
    assert create_res.status_code in (200, 201), f"创建档案失败: {create_res.text}"
    profile_id = create_res.json().get("id") or create_res.json().get("profile_id")
    assert profile_id is not None

    # 2. 查询档案（/api/v1/profiles/me）
    me_res = client.get("/api/v1/profiles/me", headers=headers)
    assert me_res.status_code == 200, f"查询档案失败: {me_res.text}"
    me_data = me_res.json()
    # 可能是单条或多条，取包含 ASD 诊断的
    if isinstance(me_data, list):
        target = next((p for p in me_data if p.get("diagnosis_type") == "ASD"), None)
    else:
        target = me_data
    assert target is not None
    assert target["primary_behavior"] == "刻板行为"

    # 3. 更新档案
    update_res = client.post(
        "/api/v1/profiles",
        json={
            "birth_date": "2019-03-15",
            "diagnosis_type": "ASD",
            "primary_behavior": "攻击行为",
            "sensory_features": ["听觉敏感"],
            "triggers": ["噪音", "环境变化"],
            "medication_notes": "对尖锐声音敏感，新增攻击行为",
        },
        headers=headers,
    )
    assert update_res.status_code in (200, 201), f"更新档案失败: {update_res.text}"

    # 4. 再次查询验证更新
    me_res2 = client.get("/api/v1/profiles/me", headers=headers)
    assert me_res2.status_code == 200
    me_data2 = me_res2.json()
    if isinstance(me_data2, list):
        target2 = next((p for p in me_data2 if p.get("diagnosis_type") == "ASD"), None)
    else:
        target2 = me_data2
    assert target2 is not None
    assert target2["primary_behavior"] == "攻击行为"

    print(f"✅ 档案 CRUD 测试通过: {profile_id}")


# ---------------------------------------------------------------------------
# 测试用例 3：案例列表筛选
# ---------------------------------------------------------------------------


def test_case_filters(client, db_fetch):
    """按 behavior_type 筛选案例列表。"""
    device_id = "test-device-filter"
    headers = {"X-Device-Id": device_id}

    # 1. 创建两条不同行为类型的案例
    case_types = [
        ("筛选测试-攻击", "攻击"),
        ("筛选测试-逃跑", "逃跑"),
    ]
    created_ids = []
    for title, behavior_type in case_types:
        res = client.post(
            "/api/v1/cases",
            json={
                "title": title,
                "behavior_type": behavior_type,
                "severity": "中度",
                "scene": "公共场合",
                "immediate_action": "测试动作",
                "comforting_phrase": "测试话术",
                "observation_metrics": "测试指标",
                "medical_criteria": "测试标准",
                "evidence_level": "个案观察记录",
            },
            headers=headers,
        )
        assert res.status_code == 201
        created_ids.append(res.json()["case_id"])

    # 2. 按行为类型筛选：攻击
    filter_res = client.get(
        "/api/v1/cases?behavior_type=攻击",
        headers=headers,
    )
    assert filter_res.status_code == 200
    data = filter_res.json()
    items = data.get("items", [])
    assert len(items) >= 1
    for item in items:
        assert item["behavior_type"] == "攻击"

    # 3. 按行为类型筛选：逃跑
    filter_res2 = client.get(
        "/api/v1/cases?behavior_type=逃跑",
        headers=headers,
    )
    assert filter_res2.status_code == 200
    data2 = filter_res2.json()
    items2 = data2.get("items", [])
    assert len(items2) >= 1
    for item in items2:
        assert item["behavior_type"] == "逃跑"

    # 4. 按状态筛选：draft（刚创建的默认状态）
    filter_res3 = client.get(
        "/api/v1/cases?status=draft",
        headers=headers,
    )
    assert filter_res3.status_code == 200
    data3 = filter_res3.json()
    items3 = data3.get("items", [])
    assert len(items3) >= 2

    print(f"✅ 案例筛选测试通过: 攻击={len(items)}条, 逃跑={len(items2)}条")
