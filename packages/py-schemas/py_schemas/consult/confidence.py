# @contract
"""CSLT-05 置信度后校验 — Pydantic Schema 定义。

提供置信度校验的输入/输出模型、判定枚举和 LLM 自评估结果模型。

契约引用：
- ConfidenceValidationInput: docs/contracts/CSLT-05/ConfidenceValidationInput.json
- ConfidenceValidationOutput: docs/contracts/CSLT-05/ConfidenceValidationOutput.json
- ValidationVerdict: docs/contracts/CSLT-05/ValidationVerdict.json

字段名、类型、必填/可选状态与契约 JSON Schema 完全一致。

LLMAssessmentResult 为内部类型，用于 Pydantic 强校验 LLM 返回的 JSON
结构化评估结果。校验失败时走降级纯规则评分路径。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from py_schemas.base import CampfireBaseModel

# ===========================================================================
# 判定结论枚举
# ===========================================================================


class ValidationVerdict(StrEnum):
    """置信度后校验的判定结论枚举。

    契约: ValidationVerdict.json
    用于下游 CSLT-08 编排层决定前端 UI 展示策略，
    以及 CSLT-06 持久化到咨询历史记录中。

    PASS: 置信度 >= 0.7，方案可信。方案全文不做修改，直接交付下游。
    APPEND_WARNING: 置信度 < 0.7 或整体超时兜底。在方案全文末尾追加强制
        免责提示文本，同时异步触发 TICK-01 工单创建。
    FORCE_BLOCK: 高危关键词命中（用户原文或方案全文）。整体替换方案为预设
        安全提示文本，同时异步触发 TICK-01 特急工单。
    """

    PASS = "PASS"
    APPEND_WARNING = "APPEND_WARNING"
    FORCE_BLOCK = "FORCE_BLOCK"


# ===========================================================================
# 内部类型：LLM 自评估结果
# ===========================================================================


class LLMAssessmentResult(CampfireBaseModel):
    """LLM 自评估返回的 JSON 结构化评估结果。

    用于 Pydantic 强校验，校验失败时走降级纯规则评分路径。

    citation_adequacy: 来源引用充分度评分（0-1）。评估 LLM 生成内容中对案例
        切片的引用是否充分和恰当。0=完全没有引用来源，1=所有论断都有来源支撑。
    logical_coherence: 逻辑连贯性评分（0-1）。评估四段式内容之间的逻辑关系
        是否自然、不矛盾。0=段落之间逻辑断裂或矛盾，1=逻辑完全连贯。
    unsourced_claim_risk: 无来源声明可感知风险（0-1）。评估生成内容中有多少
        论断可能缺乏来源支撑。0=无风险，1=高风险。越低越好。
    """

    citation_adequacy: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "来源引用充分度评分。评估 LLM 生成内容中对案例切片的引用"
            "是否充分和恰当。0=完全没有引用来源，1=所有论断都有来源支撑。"
        ),
    )
    logical_coherence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "逻辑连贯性评分。评估四段式内容之间的逻辑关系是否自然、不矛盾。0=段落之间逻辑断裂或矛盾，1=逻辑完全连贯。"
        ),
    )
    unsourced_claim_risk: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "无来源声明可感知风险。评估生成内容中有多少论断可能缺乏来源支撑。"
            "0=无风险（所有论断都可追溯到引用），1=高风险（大量不可验证的论断）。"
            "越低越好。"
        ),
    )


# ===========================================================================
# 输入模型
# ===========================================================================


class ConfidenceValidationInput(CampfireBaseModel):
    """置信度后校验的输入参数。

    契约: ConfidenceValidationInput.json
    由 CSLT-08 编排层在应急方案生成完成后组装，聚合 CSLT-03 的生成结果、
    CSLT-01 的危机判定结果和编排上下文。

    plan_text: CSLT-03 GenerationResult.text 的方案全文（必填，最小长度 1）。
    source_list: CSLT-03 GenerationResult.source_list 的来源引用清单（必填）。
    disclaimer: CSLT-03 GenerationResult.disclaimer 的免责声明文本（必填）。
    crisis_level: CSLT-01 CrisisJudgmentResult.final_level 的危机等级（必填）。
    block_deep_response: CSLT-01 的阻断深度回答标记（必填）。
    high_risk_keyword_hit: CSLT-01 的高危关键词命中标记（可选，默认 false）。
    behavior_description: 患者行为描述原文（必填，1-2000 字符）。
    request_id: 本次咨询的追踪标识（必填，UUID 格式）。
    """

    plan_text: str = Field(
        ...,
        min_length=1,
        description=(
            "CSLT-03 GenerationResult.text 的方案全文。四段式结构化文本"
            "（即时安全干预动作、情绪安抚话术、后续观察指标、就医判断标准），"
            "包含来源引用清单和 LLM 生成的正文内容。"
            "CSLT-05 不修改此字段的内容，仅读取评估。"
        ),
    )
    source_list: list[str] = Field(
        ...,
        description=(
            "CSLT-03 GenerationResult.source_list 的来源引用清单。"
            "list[string] 格式，每条为引用描述。"
            "用于规则校验中的来源引用覆盖率计算。"
        ),
    )
    disclaimer: str = Field(
        ...,
        description=(
            "CSLT-03 GenerationResult.disclaimer 的免责声明文本。"
            "CSLT-03 已强制注入的合规免责声明。CSLT-05 校验其存在性但不修改。"
        ),
    )
    crisis_level: Literal["mild", "moderate", "severe"] = Field(
        ...,
        description=(
            "CSLT-01 CrisisJudgmentResult.final_level 的危机等级枚举值"
            "（mild/moderate/severe）。用于判断是否需要追加特急优先级工单。"
        ),
    )
    block_deep_response: bool = Field(
        ...,
        description=(
            "CSLT-01 CrisisJudgmentResult.block_deep_response 的阻断深度回答标记。"
            "若为 true（upstream 已判定 severe），CSLT-05 跳过校验，直接返回 PASS。"
        ),
    )
    high_risk_keyword_hit: bool = Field(
        default=False,
        description=(
            "CSLT-01 规则引擎层在高危关键词匹配中是否命中。若为 true，"
            "CSLT-05 直接进入 FORCE_BLOCK 路径，不再执行置信度校验。"
            "注意：此字段当前在 CSLT-01/CrisisJudgmentResult 合约中缺失"
            "——为契约间隙（gap）。降级方案：从 judgment_sources 反推。"
        ),
    )
    behavior_description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description=("患者行为描述原文（已脱敏），用于 LLM 自评估时提供完整评估上下文。1-2000 个汉字。"),
    )
    request_id: str = Field(
        ...,
        description=("本次咨询的追踪标识。由 CSLT-08 编排层生成并传入，用于全链路日志关联和幂等性控制。"),
    )


# ===========================================================================
# 输出模型
# ===========================================================================


class ConfidenceValidationOutput(CampfireBaseModel):
    """置信度后校验的输出结果。

    契约: ConfidenceValidationOutput.json
    包含置信度分数、判定结论、处理后的方案全文、工单触发状态和降级信息。
    由 CSLT-08 编排层消费用于前端 UI 展示决策，
    由 CSLT-06 消费用于持久化到咨询历史。

    confidence_score: 综合置信度分数（0-1，两位小数精度）。
    verdict: 最终判定结论（PASS/APPEND_WARNING/FORCE_BLOCK）。
    modified_plan_text: 经 CSLT-05 处理后的完整方案文本。
    ticket_triggered: 是否应触发人工工单创建。
    ticket_creation_failed: TICK-01 工单创建是否失败（可选，默认 false）。
    degradation_note: 降级原因说明（可选，llm_unavailable/timeout_fallback/null）。
    validation_time_ms: 校验流程总耗时（毫秒）。
    """

    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "对方案内容可信度的综合评估结果。0.00-1.00 区间，两位小数精度。"
            "LLM 自评估 50% + 规则校验 50% 加权计算。"
            "LLM 自评估不可用时为纯规则评分（标注 degradation_note）。"
            "持久化到 consultations.confidence_score DECIMAL(3,2)。"
        ),
    )
    verdict: ValidationVerdict = Field(
        ...,
        description=(
            "置信度后校验的最终判定结论。"
            "PASS=方案可信直接交付；"
            "APPEND_WARNING=置信度不足追加提示并触发工单；"
            "FORCE_BLOCK=高危关键词命中强制阻断替换方案。"
        ),
    )
    modified_plan_text: str = Field(
        ...,
        description=(
            "经 CSLT-05 处理后的完整方案文本，可直接交付给前端展示。"
            "PASS 时与原 plan_text 完全一致；"
            "APPEND_WARNING 时在原文末尾追加一段加粗的警示文本；"
            "FORCE_BLOCK 时整体替换为预设的安全提示文本。"
        ),
    )
    ticket_triggered: bool = Field(
        ...,
        description=(
            "是否应触发人工工单创建。"
            "verdict 为 APPEND_WARNING 或 FORCE_BLOCK 时为 true；PASS 时为 false。"
            "CSLT-08 编排层据此决定是否展示工单入口。"
        ),
    )
    ticket_creation_failed: bool = Field(
        default=False,
        description=(
            "TICK-01 工单创建接口调用失败时为 true（正常为 false）。"
            "CSLT-08 编排层据此在前端展示"
            "'工单创建失败，请手动联系专家'提示。"
        ),
    )
    degradation_note: Literal["llm_unavailable", "timeout_fallback"] | None = Field(
        default=None,
        description=(
            "降级原因说明。"
            "LLM 自评估不可用时值为 'llm_unavailable'（纯规则评分）；"
            "整体超时兜底时值为 'timeout_fallback'（默认按置信度不足处理）。"
            "正常复合评分时为 null。"
        ),
    )
    validation_time_ms: float = Field(
        ge=0.0,
        description=(
            "校验流程总耗时，从接收完整输入到产出判定结果。"
            "以毫秒为单位，供下游模块了解校验性能和做业务决策。"
            "目标 P95 <= 3000ms。"
        ),
    )


__all__ = [
    "ValidationVerdict",
    "LLMAssessmentResult",
    "ConfidenceValidationInput",
    "ConfidenceValidationOutput",
]
