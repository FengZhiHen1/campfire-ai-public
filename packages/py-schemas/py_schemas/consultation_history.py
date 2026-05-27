"""CSLT-06 咨询历史管理 — Pydantic Schema 定义。

提供咨询历史归档写入和查询输出的输入/输出模型。
所有模型设置 model_config = {"extra": "forbid"} 以防止未声明字段。

契约引用：
- ConsultationHistoryCreate: docs/contracts/CSLT-06/ConsultationHistoryCreate.json
- ConsultationHistoryListItem: docs/contracts/CSLT-06/ConsultationHistoryListItem.json
- ConsultationHistoryDetail: docs/contracts/CSLT-06/ConsultationHistoryDetail.json

字段名、类型、必填/可选状态与契约 JSON Schema 完全一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field


# ===========================================================================
# 常量定义
# ===========================================================================

GENERATION_DISCLAIMER_CONST: str = (
    "以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。"
    "如情况紧急，请立即联系专业医疗机构。"
)


def _validate_disclaimer(v: str) -> str:
    """Pydantic AfterValidator：强调 disclaimer 必须与标准声明文本完全一致。

    与 Service 层 disclaimer 等值校验形成双重防护——Pydantic 模型层先拦截非法输入，
    Service 层在入库前做最终等值校验。
    """
    if v != GENERATION_DISCLAIMER_CONST:
        raise ValueError("disclaimer 内容与标准声明不一致")
    return v


# ===========================================================================
# 输入模型
# ===========================================================================


class ConsultationHistoryCreate(BaseModel):
    """咨询历史归档写入的输入模型。

    由 CSLT-08 编排层在每次咨询流程完成后组装并传入。
    包含本次咨询的完整上下文数据。

    consultation_time 虽然在契约中为必填，但实际归档时以服务端
    PostgreSQL NOW() 为准，忽略请求体中的传入值。
    """

    request_id: UUID = Field(
        ...,
        description="幂等键，由 CSLT-08 编排层在咨询开始前生成 UUID v4 并全链路携带。"
        "本模块通过 PostgreSQL UNIQUE 约束 + INSERT ... ON CONFLICT DO NOTHING 实现幂等写入。",
    )
    user_id: UUID = Field(
        ...,
        description="本次咨询的发起家属用户标识，对应 JWT Token 的 sub 字段。",
    )
    crisis_level: Literal["mild", "moderate", "severe"] = Field(
        ...,
        description="本次咨询的危机分级判定结果。枚举值：mild/moderate/severe。透传 CSLT-01 判定结果。",
    )
    behavior_description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="家属在本次咨询中输入的患者行为表现文字。已通过上游 PII 脱敏。1-2000 汉字字符。",
    )
    consultation_time: datetime = Field(
        ...,
        description="本次应急咨询发生的时间点。归档时以服务端 PostgreSQL NOW() 函数自动填充为准，忽略请求体中的传入值。",
    )
    generated_plan: str = Field(
        ...,
        min_length=1,
        max_length=65536,
        description="AI 生成的完整四段式应急方案全文（Markdown 格式）。is_partial=true 时可为非完整四段式文本。",
    )
    source_list: list[str] = Field(
        ...,
        description="被引用案例的来源信息列表。每项格式为 '[N] CASE-XXX 案例标题（录入日期）'。无引用案例时为空列表。",
    )
    disclaimer: Annotated[str, AfterValidator(_validate_disclaimer)] = Field(
        ...,
        description="法律合规免责声明。入库前执行等值校验——必须与固定文本完全一致。",
    )
    generation_time_ms: float = Field(
        ...,
        ge=0.0,
        description="从接收输入到完整方案生成完毕的总耗时，单位毫秒。",
    )
    is_partial: bool = Field(
        ...,
        description="是否为部分生成结果。is_partial=true 的记录仍需在列表中正常展示。",
    )
    referenced_slice_ids: list[UUID] = Field(
        ...,
        description="LLM 输出中实际引用的案例切片 ID 列表。",
    )
    finish_reason: Literal["COMPLETE", "PARTIAL", "BLOCKED", "TIMEOUT", "ERROR"] = Field(
        ...,
        description="生成结束原因。COMPLETE=正常完成，PARTIAL=超时部分生成，BLOCKED=危机阻断，TIMEOUT=完全超时，ERROR=不可恢复错误。",
    )
    ttft_ms: float = Field(
        ...,
        ge=0.0,
        description="首字延迟（Time to First Token），单位毫秒。阻断场景下为 0。",
    )
    has_feedback: bool = Field(
        default=False,
        description="反馈标记。默认 false。由 QUAL-03 在用户提交反馈后通过 PATCH 回调更新为 true。",
    )
    token_input: Optional[int] = Field(
        default=None,
        ge=0,
        description="LLM 输入 Token 数量。阻断场景下为 null。",
    )
    token_output: Optional[int] = Field(
        default=None,
        ge=0,
        description="LLM 输出 Token 数量。阻断场景下为 null。",
    )
    device_info: Optional[dict] = Field(
        default=None,
        description="设备与平台信息。全字段 nullable。用于运维排查。",
    )

    model_config = {"extra": "forbid"}


# ===========================================================================
# 输出模型
# ===========================================================================


class ConsultationHistoryListItem(BaseModel):
    """咨询历史列表摘要条目。

    仅包含列表展示所需的 5 个字段，禁止携带 generated_plan 等大字段。
    按 consultation_time 降序排列。前端自行截取 behavior_description 前 50 字展示。
    """

    id: UUID = Field(
        ...,
        description="咨询记录的唯一标识，系统生成的 UUID v4。",
    )
    consultation_time: datetime = Field(
        ...,
        description="本次应急咨询发生的时间点（服务端时间）。列表按此字段降序排列。",
    )
    behavior_description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="家属在本次咨询中输入的患者行为表现文字（完整原文）。前端负责截取前 50 字展示。",
    )
    crisis_level: Literal["mild", "moderate", "severe"] = Field(
        ...,
        description="本次咨询的危机分级判定结果。枚举值：mild / moderate / severe。",
    )
    has_feedback: bool = Field(
        ...,
        description="反馈标记。true 表示用户已为此咨询提交反馈。",
    )

    model_config = {"extra": "forbid"}


class ConsultationHistoryDetail(BaseModel):
    """单次咨询的完整详情。

    包含归档时的全部字段。generated_plan 原样返回完整 Markdown 全文（禁止截断或二次加工）。
    供前端详情页面和 TICK-01（工单自动生成）消费。
    """

    id: UUID = Field(
        ...,
        description="咨询记录的唯一标识，系统生成的 UUID v4。",
    )
    request_id: UUID = Field(
        ...,
        description="幂等键，由 CSLT-08 编排层生成。用于去重检测和全链路追踪关联。",
    )
    user_id: UUID = Field(
        ...,
        description="本次咨询的发起家属用户标识。",
    )
    crisis_level: Literal["mild", "moderate", "severe"] = Field(
        ...,
        description="本次咨询的危机分级判定结果。",
    )
    behavior_description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="家属在本次咨询中输入的患者行为表现文字（完整原文）。",
    )
    consultation_time: datetime = Field(
        ...,
        description="本次应急咨询发生的时间点（服务端时间）。",
    )
    generated_plan: str = Field(
        ...,
        min_length=1,
        max_length=65536,
        description="AI 生成的完整四段式应急方案全文（Markdown 格式）。必须原样返回归档时的完整文本，禁止截断、压缩或格式化。",
    )
    source_list: list[str] = Field(
        ...,
        description="被引用案例的来源信息列表。",
    )
    disclaimer: Annotated[str, AfterValidator(_validate_disclaimer)] = Field(
        ...,
        description="法律合规免责声明固定文本。",
    )
    generation_time_ms: float = Field(
        ...,
        ge=0.0,
        description="从接收输入到完整方案生成完毕的总耗时，单位毫秒。",
    )
    is_partial: bool = Field(
        ...,
        description="是否为部分生成结果。true 时前端应展示「部分生成」提示。",
    )
    referenced_slice_ids: list[UUID] = Field(
        ...,
        description="LLM 输出中实际引用的案例切片 ID 列表。",
    )
    finish_reason: Literal["COMPLETE", "PARTIAL", "BLOCKED", "TIMEOUT", "ERROR"] = Field(
        ...,
        description="生成结束原因。COMPLETE / PARTIAL / BLOCKED / TIMEOUT / ERROR。",
    )
    ttft_ms: float = Field(
        ...,
        ge=0.0,
        description="首字延迟（Time to First Token），单位毫秒。",
    )
    has_feedback: bool = Field(
        ...,
        description="反馈标记。true 表示用户已为此咨询提交反馈。",
    )
    token_input: Optional[int] = Field(
        default=None,
        description="LLM 输入 Token 数量。阻断场景下为 null。",
    )
    token_output: Optional[int] = Field(
        default=None,
        description="LLM 输出 Token 数量。阻断场景下为 null。",
    )
    device_info: Optional[dict] = Field(
        default=None,
        description="设备与平台信息。用于运维排查。",
    )

    model_config = {"extra": "forbid"}


__all__ = [
    "GENERATION_DISCLAIMER_CONST",
    "ConsultationHistoryCreate",
    "ConsultationHistoryListItem",
    "ConsultationHistoryDetail",
]
