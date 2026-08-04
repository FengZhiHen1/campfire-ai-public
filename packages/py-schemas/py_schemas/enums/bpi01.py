# @contract
"""BPI-01 行为形态词表（behavior_form 后台词表，数据模型 §1.2）。

按行为类型分组的具体形态勾选词表。家属无感（后台枚举）；
内容为占位示例，完整词表需专业翻译审校后入库（审校 TODO，不影响结构）。
"""

from __future__ import annotations

from py_schemas.enums.emergency_enums import BehaviorBucket

# 行为类型 → 形态词表（BPI-01 中文条目化，待专业审校）
BPI01_BEHAVIOR_FORMS: dict[BehaviorBucket, list[str]] = {
    BehaviorBucket.SELF_INJURY: ["撞头", "咬手", "抓挠皮肤", "打脸", "拔头发"],
    BehaviorBucket.AGGRESSION: ["推搡", "踢打", "咬人", "抓人", "摔物"],
    BehaviorBucket.STEREOTYPY: ["摇晃身体", "转圈", "重复语言", "排列物品"],
    BehaviorBucket.MELTDOWN: ["尖叫", "哭喊", "倒地", "拒绝移动"],
    BehaviorBucket.ELOPEMENT: ["突然跑离", "无回应离开", "藏匿"],
    BehaviorBucket.MEDICATION: ["拒药", "误服", "漏服"],
    BehaviorBucket.SOCIAL_WITHDRAWAL: ["回避眼神", "独处角落", "无回应"],
    BehaviorBucket.HYPERACTIVITY: ["持续跑动", "攀爬", "无法安坐"],
    BehaviorBucket.OTHER: ["其他形态"],
}


def is_valid_behavior_form(bucket: BehaviorBucket, form: str) -> bool:
    """校验形态是否属于该行为桶的词表。"""
    return form in BPI01_BEHAVIOR_FORMS.get(bucket, [])


__all__ = ["BPI01_BEHAVIOR_FORMS", "is_valid_behavior_form"]
