"""安全卡槽位填充（此刻安全层个性化，零 LLM）。

槽位体系（智能应急咨询 §3.1）：
- {称呼}      nickname（不得以「孩子」为默认称呼——无档案回退纯模板）
- {触发物}    triggers（已知情绪触发因素）
- {安抚物}    soothing_items（有效安抚物；空则推导最近 outcome=有效 事件——S4 接线）
- {禁忌}      avoid_list（禁忌/无效方式；空则推导最近 outcome=无效 事件——S4 接线）
- {话术适配}  communication_methods（语言水平 + AAC/视觉支持）
- {走失信息}  physical_description / familiar_places / water_risk（走失专项组）

数据源接口 ProfileSnapshotProvider 为 S4 衔接点：本期由现有 profiles 表
字段实现部分槽位；S4 档案四层落地后切换为危机预案层数据源。
无档案/字段缺失 → 该槽位所在模板回退纯模板（冷启动兼容）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProfileSnapshot:
    """档案快照（槽位填充数据源——S4 档案四层落地后由危机预案层供给）。

    全部字段可空：任一槽位数据源缺失时该槽位回退纯模板。
    """

    nickname: str | None = None
    triggers: list[str] = field(default_factory=list)
    soothing_items: list[str] = field(default_factory=list)
    avoid_list: list[str] = field(default_factory=list)
    communication_methods: list[str] = field(default_factory=list)
    physical_description: str | None = None
    familiar_places: list[str] = field(default_factory=list)
    water_risk: list[str] = field(default_factory=list)
    emergency_contacts: list[dict[str, str]] = field(default_factory=list)


class ProfileSnapshotProvider(Protocol):
    """档案快照供给接口（S4 档案四层落地后接线实现）。"""

    async def get_snapshot(self, profile_id: str) -> ProfileSnapshot | None: ...


# 槽位占位符 → 快照字段映射
_SLOT_TRIGGERS = "{触发物}"
_SLOT_SOOTHING = "{安抚物}"
_SLOT_AVOID = "{禁忌}"
_SLOT_NICKNAME = "{称呼}"
_SLOT_COMMUNICATION = "{话术适配}"
_SLOT_PHYSICAL = "{体貌特征}"
_SLOT_PLACES = "{常去地点}"
_SLOT_WATER = "{水体风险}"


def fill_slots(template: str, snapshot: ProfileSnapshot | None) -> tuple[str, bool]:
    """槽位填充（确定性文本替换，零 LLM）。

    Args:
        template: 含槽位占位符的卡体模板。
        snapshot: 档案快照（None = 无档案模式）。

    Returns:
        (填充后文本, 是否实际发生个性化填充)。
        无档案或快照字段全空 → 原样返回模板（纯模板回退，冷启动兼容）。
    """
    if snapshot is None:
        return template, False

    filled = template
    personalized = False

    def _replace(slot: str, value: str | None) -> None:
        nonlocal filled, personalized
        if value and slot in filled:
            filled = filled.replace(slot, value)
            personalized = True

    _replace(_SLOT_NICKNAME, snapshot.nickname)
    _replace(_SLOT_TRIGGERS, "、".join(snapshot.triggers) if snapshot.triggers else None)
    _replace(_SLOT_SOOTHING, "、".join(snapshot.soothing_items) if snapshot.soothing_items else None)
    _replace(_SLOT_AVOID, "、".join(snapshot.avoid_list) if snapshot.avoid_list else None)
    _replace(_SLOT_COMMUNICATION, "、".join(snapshot.communication_methods) if snapshot.communication_methods else None)
    _replace(_SLOT_PHYSICAL, snapshot.physical_description)
    _replace(_SLOT_PLACES, "、".join(snapshot.familiar_places) if snapshot.familiar_places else None)
    _replace(_SLOT_WATER, "、".join(snapshot.water_risk) if snapshot.water_risk else None)

    return filled, personalized


def fill_emergency_contacts(template: str, snapshot: ProfileSnapshot | None) -> str:
    """紧急联系人槽位（走失报警话术用）：{紧急联系人} → 姓名（关系）电话 列表。"""
    if snapshot is None or not snapshot.emergency_contacts:
        return template
    contacts = "；".join(
        f"{c.get('name', '')}（{c.get('relation', '')}）{c.get('phone', '')}"
        for c in snapshot.emergency_contacts
        if c.get("name")
    )
    if contacts and "{紧急联系人}" in template:
        return template.replace("{紧急联系人}", contacts)
    return template


__all__ = ["ProfileSnapshot", "ProfileSnapshotProvider", "fill_slots", "fill_emergency_contacts"]
