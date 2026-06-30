# @contract
"""CSLT-02 RAG语义检索 — Pydantic Schema 定义。

提供全平台共享的检索输入/输出模型和枚举定义。

契约引用：
- SemanticSearchInput: docs/contracts/CSLT-02/SemanticSearchInput.json
- TagFilterDto: docs/contracts/CSLT-02/TagFilterDto.json
- CaseSliceDto: docs/contracts/CSLT-02/CaseSliceDto.json
- SemanticSearchResult: docs/contracts/CSLT-02/SemanticSearchResult.json
- EvidenceLevel: docs/contracts/CSLT-02/EvidenceLevel.json
- DegradationLevel: docs/contracts/CSLT-02/DegradationLevel.json
- RetrievalStatus: docs/contracts/CSLT-02/RetrievalStatus.json

字段名、类型、必填/可选状态与契约 JSON Schema 完全一致。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from py_schemas.base import CampfireBaseModel

# ===========================================================================
# 枚举定义
# ===========================================================================


class EvidenceLevel(StrEnum):
    """案例循证等级枚举。

    契约: EvidenceLevel.json
    标识案例所依据的证据强度，用于综合排序中的循证加权计算：
    NCAEP=1.0, INSTITUTIONAL_EXPERIENCE=0.8, CASE_OBSERVATION=0.6。
    """

    NCAEP = "NCAEP"
    INSTITUTIONAL_EXPERIENCE = "INSTITUTIONAL_EXPERIENCE"
    CASE_OBSERVATION = "CASE_OBSERVATION"


class DegradationLevel(StrEnum):
    """检索降级放宽层级枚举。

    契约: DegradationLevel.json
    当精确标签过滤结果不足期望数量时，按此枚举顺序逐层放宽过滤条件。
    """

    NONE = "NONE"
    EMOTION_RELAXED = "EMOTION_RELAXED"
    BEHAVIOR_RELAXED = "BEHAVIOR_RELAXED"
    ALL_TAGS_REMOVED = "ALL_TAGS_REMOVED"


class RetrievalStatus(StrEnum):
    """检索执行状态枚举。

    契约: RetrievalStatus.json
    标识一次检索操作的整体执行结果，供下游 CSLT-03 和 OBS-01 使用。
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"
    EMPTY = "EMPTY"


# ===========================================================================
# 请求模型
# ===========================================================================


class TagFilterDto(CampfireBaseModel):
    """档案标签过滤条件数据传输对象。

    契约: TagFilterDto.json
    由上游 PROF-02 从患者个性化档案中提取并标准化后传入。

    age_range: 患者年龄段（必填）。
    behavior_type: 主要行为类型（必填），枚举值引用 CSLT-01/BehaviorTypeCategory。
    emotion_level: 情绪等级（可选），为 null 时不应用此过滤条件。
    sensory_features: 感官特征标签（可选），为 null 时不应用此过滤条件。
    """

    age_range: str = Field(
        ...,
        min_length=1,
        description="患者年龄段。枚举值由 PROF-02 定义（如：学龄前(0-5岁)、学龄儿童(6-12岁)等）。",
        examples=["学龄儿童(6-12岁)"],
    )
    behavior_type: Literal[
        "SELF_INJURY",
        "AGGRESSION",
        "ELOPEMENT",
        "MEDICATION",
        "EMOTIONAL_MELTDOWN",
        "STEREOTYPY",
        "OTHER",
    ] = Field(
        ...,
        description="主要行为类型。枚举值引用 CSLT-01/BehaviorTypeCategory。",
        examples=["EMOTIONAL_MELTDOWN"],
    )
    emotion_level: Literal["轻", "中", "重"] | None = Field(
        default=None,
        description="情绪等级（可选）。枚举值：轻、中、重。为 null 时不应用此过滤条件。",
        examples=["重"],
    )
    sensory_features: str | None = Field(
        default=None,
        description="感官特征标签（可选）。如听觉敏感、触觉敏感、视觉敏感等。",
        examples=["听觉敏感"],
    )


class SemanticSearchInput(CampfireBaseModel):
    """RAG 语义检索的输入参数。

    契约: SemanticSearchInput.json
    包含用户行为描述文本、档案标签过滤条件和检索期望数量。

    query_text: 用户行为描述（1-2000 字符，上游已脱敏 PII）。
    tag_filters: 档案标签过滤条件。
    top_k: 检索期望返回数量（默认 10，范围 1-50）。
    request_id: 全链路追踪 ID（可选 UUID v4 格式）。
    """

    query_text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="家属描述的当前患者行为与情绪表现，作为语义检索的查询文本。上游已脱敏PII。",
        examples=["儿子在商场突然捂耳朵蹲下，拒绝移动，持续尖叫，之前在家也出现过类似情况"],
    )
    tag_filters: TagFilterDto = Field(
        ...,
        description="从患者个性化档案提取的结构化过滤维度，用于限定检索范围",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="检索期望返回的案例切片条目数量。默认10条，范围1-50。超出范围时自动修正为边界值。",
        examples=[10, 20],
    )
    request_id: str | None = Field(
        default=None,
        description="全链路追踪ID。上游调用方生成UUID v4格式字符串。可选，缺失时检索引擎自动生成。",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


# ===========================================================================
# 响应模型
# ===========================================================================


class CaseSliceDto(CampfireBaseModel):
    """案例切片的数据传输对象。

    契约: CaseSliceDto.json
    包含切片的文本内容、语义相似度分数、综合排序分数和来源案例元数据。
    下游 CSLT-03 将此注入 Prompt 模板作为参考案例上下文。
    """

    slice_id: str = Field(
        ...,
        description="案例切片的唯一标识，对应 case_chunks 表的主键 UUID",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    card_id: str = Field(
        ...,
        description="切片所属 L2 卡片的唯一标识，对应 case_cards 表主键 UUID",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    slice_text: str = Field(
        ...,
        max_length=8000,
        description="案例中某个要素的原文片段。已在上游 CASE-04 入库时脱敏 PII。",
        examples=["在嘈杂商场环境中，ASD儿童出现听觉感官过载反应，捂耳朵蹲下拒绝移动"],
    )
    chunk_type: str | None = Field(
        default=None,
        description="该切片所属的案例四要素类型",
        examples=["scene"],
    )
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="切片与用户行为描述之间的余弦语义相似度。取值范围 0.00-1.00，保留4位小数。",
        examples=[0.92],
    )
    composite_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="综合排序分数，公式：similarity*0.5 + time_decay*0.25 + evidence_weight*0.25。取值0.00-1.00，保留4位小数。",
        examples=[0.88],
    )
    evidence_level: EvidenceLevel = Field(
        ...,
        description="该案例所依据的证据强度等级",
    )
    case_title: str | None = Field(
        default=None,
        max_length=200,
        description="源案例的标题，供下游在 Prompt 中引用时展示",
        examples=["ASD商场感官过载干预案例"],
    )
    source: str | None = Field(
        default=None,
        description="案例来源类型",
        examples=["expert"],
    )
    case_created_at: str = Field(
        ...,
        description="案例首次审核通过的日期，用于时效权重计算",
        examples=["2025-11-03"],
    )
    applicable_tags: dict[str, str] | None = Field(
        default=None,
        description="该案例适用的人群标签维度，包含年龄段区间、诊断类型、行为类型等",
        examples=[
            {
                "age_range": "学龄儿童(6-12岁)",
                "diagnosis_type": "ASD",
                "behavior_type": "情绪崩溃",
            }
        ],
    )


class SemanticSearchResult(CampfireBaseModel):
    """RAG 语义检索的输出结果。

    契约: SemanticSearchResult.json
    包含排序后的案例切片列表、检索状态标记和查询指纹。
    """

    results: list[CaseSliceDto] = Field(
        ...,
        description="按综合排序分数从高到低排列的案例切片列表。长度不超过 top_k。",
    )
    total_count: int = Field(
        ...,
        ge=0,
        description="实际返回的结果数量。范围 0 至 top_k。",
        examples=[8],
    )
    is_complete: bool = Field(
        ...,
        description="标记本次检索是否完整完成。true=检索完整完成（未触发超时或空库）。false=检索被截断（超时或部分完成）。",
    )
    reason: str | None = Field(
        default=None,
        description="当 is_complete=false 时的原因标记。枚举值：case_library_empty, timeout, embedding_unavailable。is_complete=true 时此字段为 null。",
        examples=["timeout"],
    )
    query_fingerprint: str = Field(
        ...,
        pattern=r"^[a-f0-9]{64}$",
        description="查询文本的 SHA256 十六进制指纹，用于问题排查和去重。",
        examples=["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    )
    degradation_applied: bool = Field(
        ...,
        description="是否触发了降级放宽策略。true=至少触发了一层标签条件放宽。",
    )
    degradation_level: DegradationLevel = Field(
        ...,
        description="触发的降级放宽层级。degradation_applied=false 时恒为 NONE。",
    )
    elapsed_ms: float = Field(
        ...,
        ge=0,
        description="检索耗时，从接受到返回的总时长，以毫秒为单位。",
        examples=[320.5],
    )


__all__ = [
    "EvidenceLevel",
    "DegradationLevel",
    "RetrievalStatus",
    "TagFilterDto",
    "SemanticSearchInput",
    "CaseSliceDto",
    "SemanticSearchResult",
]
