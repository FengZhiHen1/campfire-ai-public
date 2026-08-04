# @contract
"""红线安全门 — Pydantic 契约（ADR-008 二元安全门目标态）。

二元判定（redline/pass）取代旧三级危机分级；判定为纯规则、零 LLM 参与
（红线安全门与兜底策略 §一）。旧三级危机分级语义已废除。

模型清单：
    RedlineGateRequest   红线判定请求
    RedlineGateResult    判定输出契约（gate_result / gate_trigger）
    RedlineEventRecord   红线事件落库 DTO
"""

from __future__ import annotations

from pydantic import Field

from py_schemas.base import CampfireBaseModel
from py_schemas.enums import BehaviorBucket, GateResult


class RedlineGateRequest(CampfireBaseModel):
    """红线安全门判定请求。

    判定输入 = 家属点选的行为桶 + 可选文字描述 + 可选档案标识
    （档案叠加规则需要，红线安全门 §3.4）。
    """

    bucket: BehaviorBucket | None = Field(
        default=None,
        description="家属点选的行为桶；红线桶（自伤/攻击/走失/用药）直接命中红线",
    )
    text: str | None = Field(
        default=None,
        max_length=2000,
        description="可选文字描述（关键词硬拦截 + 否定过滤 + 档案叠加的输入）",
    )
    profile_id: str | None = Field(
        default=None,
        description="关联档案 ID（档案叠加规则需要；无档案时该规则自动跳过）",
    )


class RedlineGateResult(CampfireBaseModel):
    """红线安全门判定输出契约（红线安全门 §3.5）。

    gate_result: redline / pass（二元）
    gate_trigger: 触发规则 ID（如 KW_SELF_HARM_001 / BUCKET_ATTACK / PROFILE_RECURRENCE）
    """

    gate_result: GateResult = Field(..., description="判定结果：redline / pass")
    gate_trigger: str | None = Field(
        default=None,
        description="触发规则 ID；pass 时为 None",
        examples=["KW_SELF_HARM_001", "BUCKET_ATTACK", "PROFILE_RECURRENCE"],
    )
    detail: str | None = Field(
        default=None,
        description="判定详情（命中关键词/桶名等，供审计与词库迭代）",
    )


class RedlineEventRecord(CampfireBaseModel):
    """红线事件落库 DTO（红线安全门 §四：事件记录供词库迭代与 M4 冷启动）。"""

    session_id: str = Field(..., description="关联会话 ID")
    gate_trigger: str = Field(..., description="触发规则 ID")
    input_summary: str = Field(..., max_length=500, description="输入摘要（脱敏后）")
    bucket: BehaviorBucket | None = Field(default=None, description="关联行为桶")
    profile_id: str | None = Field(default=None, description="关联档案 ID")


__all__ = [
    "RedlineGateRequest",
    "RedlineGateResult",
    "RedlineEventRecord",
]
