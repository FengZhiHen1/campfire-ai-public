# @contract
"""CSLT-01 危机分级判定 — Pydantic 数据模型定义。

所有模型使用 ConfigDict(extra="forbid") 严格校验，
与 docs/contracts/CSLT-01/ 下 JSON Schema 契约保持字段名、类型、必填性一致。

模型清单：
    CrisisJudgmentRequest  外部输入请求
    CrisisJudgmentResult   最终判定结果
    JudgmentLayerResult    单层判定记录
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_schemas.enums.crisis_enums import (
    BehaviorTypeCategory,
    CrisisLevel,
)


# ============================================================================
# CrisisJudgmentRequest（外部输入契约）
# ============================================================================


class CrisisJudgmentRequest(BaseModel):
    """危机分级判定请求。

    由 CSLT-08（咨询编排逻辑）组装，包含患者档案快照、
    前置行为类型选择和自然语言行为描述。
    """

    model_config = ConfigDict(extra="forbid")

    patient_profile: Any | None = Field(
        default=None,
        description="当前咨询关联的患者档案快照。由 PROF-02 在咨询编排阶段获取并注入。"
        "若 PROF-02 返回 None（患者未创建档案），本字段为 None，档案叠加规则自动跳过。",
    )
    behavior_type_selection: list[BehaviorTypeCategory] = Field(
        min_length=1,
        description="前置行为类型勾选（必填，支持多选）。"
        "家属在 CSLT-07 应急咨询界面勾选后传入。可多选任意 7 类预设选项的组合。",
        examples=[["SELF_INJURY", "EMOTIONAL_MELTDOWN"]],
    )

    @field_validator("behavior_type_selection")
    @classmethod
    def check_unique_items(
        cls,
        v: list[BehaviorTypeCategory],
    ) -> list[BehaviorTypeCategory]:
        """校验 behavior_type_selection 无重复元素。

        与契约 `uniqueItems: true` 保持一致。
        """
        if len(v) != len(set(v)):
            raise ValueError("behavior_type_selection must not contain duplicate items")
        return v

    behavior_description: str = Field(
        max_length=2000,
        description="家属自由输入的患者当前行为表现文本描述",
        examples=[
            "患者从下午3点开始持续撞头，已经撞了十几次，劝阻无效",
            "孩子在商场突然捂住耳朵蹲在地上，怎么拉都不走",
        ],
    )


# ============================================================================
# JudgmentLayerResult（单层判定记录）
# ============================================================================


class JudgmentLayerResult(BaseModel):
    """单层判定层的结果记录。

    每个判定层（PreSelectionLayer / RuleEngineLayer / LLMReviewLayer）
    执行后输出该结构，汇集到 CrisisJudgmentResult.judgment_sources 列表中供审计追溯。
    """

    model_config = ConfigDict(extra="forbid")

    layer_name: str = Field(
        description="判定层标识：'PreSelectionLayer' | 'RuleEngineLayer' | 'LLMReviewLayer'",
        examples=["PreSelectionLayer", "RuleEngineLayer", "LLMReviewLayer"],
    )
    level: CrisisLevel | None = Field(
        default=None,
        description="该判定层输出的危机等级。未命中时为 null",
        examples=["mild", "severe"],
    )
    trigger_rule_id: str | None = Field(
        default=None,
        description="触发的规则编号（如 'KW_SELF_HARM_001'），RuleEngineLayer 命中时必填",
        examples=["KW_SELF_HARM_001", "PROFILE_OVERLAP_001"],
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="判定详情，key-value 格式。内容因层而异",
        examples=[
            {"matched_keywords": ["撞墙", "撞头"], "negation_filtered": False},
            {"checked_types": ["SELF_INJURY", "AGGRESSION"]},
        ],
    )


# ============================================================================
# CrisisJudgmentResult（最终输出契约）
# ============================================================================


class CrisisJudgmentResult(BaseModel):
    """危机分级判定服务的最终输出结果。

    由 CrisisJudgmentPipeline._do_merge() 合并各判定层结果后输出。
    """

    model_config = ConfigDict(extra="forbid")

    final_level: CrisisLevel = Field(
        description="最终危机等级。由 merge() 按'宁升勿降'策略合并各判定层结果"
        "——任一层判 severe 即为 severe。",
    )
    block_deep_response: bool = Field(
        description="阻断深度回答标记。final_level=severe 时为 true，"
        "AI 仅输出安全提示模板，不生成深度应急建议。mild/moderate 时为 false。",
    )
    manual_review_flag: bool = Field(
        default=False,
        description="是否需要人工复核标记。仅档案叠加规则命中时为 true"
        "（患者历史行为标签含自伤/攻击且文本含触发词'又'/'再次'/'还是'），"
        "建议下游触发人工审核。",
    )
    review_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="LLM 复审置信度分数（0~1 区间）。"
        "当前 CSLT-01 已移除 LLM 复审，此字段保留仅为兼容性，恒为 null。",
    )
    judgment_sources: list[JudgmentLayerResult] = Field(
        min_length=1,
        description="各判定层的裁决结论，记录决策依据供审计追溯。"
        "当前包含 PreSelectionLayer 与 RuleEngineLayer 两层结果。",
    )
    degradation_note: str | None = Field(
        default=None,
        description="降级标注。rule_engine_degraded=关键词词库加载失败，"
        "仅前置选择层可用；profile_missing=患者档案缺失，档案叠加规则跳过。"
        "正常运行时为 null。",
    )
