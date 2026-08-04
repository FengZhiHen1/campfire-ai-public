# @contract
"""应急域枚举定义（ADR-009 时刻分层目标态）。

行为桶枚举与档案行为类型枚举对齐（ADR-010 第 7 条统一枚举，
个性化档案库/数据模型 §1.1），检索过滤零映射成本。
事实源：docs/技术设计/机制/智能应急咨询.md、红线安全门与兜底策略.md。
"""

from __future__ import annotations

from enum import StrEnum


class BehaviorBucket(StrEnum):
    """行为桶枚举（应急链路输入方式 + 红线分流 + 检索过滤维度三职）。

    值为统一行为类型枚举的中文持久化值（与档案/案例检索对齐）。
    UI 标签经 ui_label 属性映射（情绪哭闹/刻板升级/用药 等口语化标签）。
    """

    MELTDOWN = "情绪崩溃"
    STEREOTYPY = "刻板行为"
    SELF_INJURY = "自伤"
    AGGRESSION = "攻击"
    ELOPEMENT = "走失"
    MEDICATION = "用药相关"
    SOCIAL_WITHDRAWAL = "社交退缩"
    HYPERACTIVITY = "多动"
    OTHER = "其他"

    @property
    def ui_label(self) -> str:
        """家属侧 UI 标签（危机中认知友好的口语化表达）。"""
        return _UI_LABEL_MAP[self]


_UI_LABEL_MAP: dict[BehaviorBucket, str] = {
    BehaviorBucket.MELTDOWN: "情绪哭闹",
    BehaviorBucket.STEREOTYPY: "刻板升级",
    BehaviorBucket.SELF_INJURY: "自伤",
    BehaviorBucket.AGGRESSION: "攻击",
    BehaviorBucket.ELOPEMENT: "走失",
    BehaviorBucket.MEDICATION: "用药",
    BehaviorBucket.SOCIAL_WITHDRAWAL: "社交退缩",
    BehaviorBucket.HYPERACTIVITY: "多动",
    BehaviorBucket.OTHER: "其他",
}

# 红线桶：点选即直接命中红线（红线安全门 §3.1）
REDLINE_BUCKETS: frozenset[BehaviorBucket] = frozenset(
    {
        BehaviorBucket.SELF_INJURY,
        BehaviorBucket.AGGRESSION,
        BehaviorBucket.ELOPEMENT,
        BehaviorBucket.MEDICATION,
    }
)

# 走失桶走独立一键应急流程（智能应急咨询 §四）
ELOPEMENT_BUCKET: BehaviorBucket = BehaviorBucket.ELOPEMENT


class CrisisStage(StrEnum):
    """危机阶段枚举（Colvin 危机升级模型骨架）。

    高峰期只输出安全指令，主动抑制教学性内容（智能应急咨询 §3.1）。
    """

    TRIGGER = "触发"
    AGITATION = "躁动"
    ACCELERATION = "加速"
    PEAK = "高峰"


class MeltdownType(StrEnum):
    """情绪哭闹桶内分流（meltdown/tantrum，智能应急咨询 §3.3）。

    meltdown 路径永不推荐「故意忽视」；tantrum 路径适用不同安抚策略。
    """

    MELTDOWN = "meltdown"
    TANTRUM = "tantrum"


class TurnType(StrEnum):
    """咨询轮次类型（consultations.turn_type）。"""

    INITIAL_PLAN = "initial_plan"  # 首份方案（四段式契约约束）
    FOLLOWUP = "followup"  # 追问轮（自由文本，不套契约）


class GateResult(StrEnum):
    """红线安全门判定结果（二元，红线安全门 §3.5）。"""

    REDLINE = "redline"
    PASS = "pass"


class FallbackSignal(StrEnum):
    """确定性兜底信号枚举（智能应急咨询 §七，取代置信度路由）。"""

    RETRIEVAL_INSUFFICIENT = "retrieval_insufficient"  # 检索质量不足
    USER_UNRESOLVED = "user_unresolved"  # 用户标记未解决
    FOLLOWUP_LIMIT = "followup_limit"  # 连续追问超阈值
    REDLINE_HIT = "redline_hit"  # 红线命中


__all__ = [
    "BehaviorBucket",
    "REDLINE_BUCKETS",
    "ELOPEMENT_BUCKET",
    "CrisisStage",
    "MeltdownType",
    "TurnType",
    "GateResult",
    "FallbackSignal",
]
