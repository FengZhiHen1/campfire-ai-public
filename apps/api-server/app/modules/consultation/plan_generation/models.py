"""CSLT-03 应急方案生成 — Pydantic 数据模型定义。

所有对外接口模型使用 ConfigDict(extra="forbid") 严格校验，
字段名、类型、必填性与 docs/contracts/CSLT-03/ 下 JSON Schema 契约完全一致。

模型清单：
    EmergencyPlanInput    对外输入（由 CSLT-08 编排层组装传入）
    GenerationResult      最终输出（传递给 CSLT-05/06/08）
    GenerationChunk       流式增量块（传递给 CSLT-04）
    PromptBuildContext    内部上下文（仅在 prompt_builder.py 内使用）
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from py_schemas.crisis import CrisisJudgmentResult
from py_schemas.consult import SemanticSearchResult

from .enums import BlockVariant, GenerationStatus


# ============================================================================
# EmergencyPlanInput（对外输入契约）
# ============================================================================


class EmergencyPlanInput(BaseModel):
    """应急方案生成服务的完整输入数据。

    由 CSLT-08 编排层组装上游 CSLT-01 危机分级结果、CSLT-02 RAG检索结果
    和患者档案摘要后传入。

    Contract: docs/contracts/CSLT-03/EmergencyPlanInput.json
    """

    model_config = ConfigDict(extra="forbid")

    crisis_result: CrisisJudgmentResult = Field(
        ...,
        description="上游 CSLT-01 危机分级判定结果。"
        "本模块消费 final_level（决定正常生成或短路返回）和"
        "block_deep_response（决定是否跳过 LLM 调用）两个字段。",
    )
    search_result: SemanticSearchResult = Field(
        ...,
        description="上游 CSLT-02 RAG语义检索结果。"
        "本模块消费 results（作为 Prompt 参考案例）、"
        "degradation_applied 和 degradation_level（检索引擎降级标记）字段。",
    )
    profile_summary: str = Field(
        ...,
        min_length=1,
        max_length=3000,
        description="Markdown 格式的患者档案摘要，由 CSLT-08 编排层从 PROF-02 获取并格式化。"
        "包含 diagnosis_type、behavior_tags、recent_events（最近5条事件摘要）等字段。",
        examples=[
            "- **诊断类型**：ASD\n"
            "- **主要行为类型**：情绪崩溃\n"
            "- **最近事件**：\n"
            "  1. 2026-05-25：因噪音触发情绪崩溃，干预方式为提供降噪耳机，效果部分缓解"
        ],
    )
    behavior_description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="家属输入的当前患者行为与情绪表现文字。文本已通过上游 SEC-03 PII 脱敏。",
        examples=["儿子在商场突然捂耳朵蹲下，拒绝移动，持续尖叫，之前在家也出现过类似情况"],
    )
    request_id: str = Field(
        ...,
        description="全链路请求追踪 ID（UUID v4），关联整个应急咨询链路的所有日志和指标。"
        "由 CSLT-08 编排层在咨询开始时生成。",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    block_variant: BlockVariant | None = Field(
        default=None,
        description="阻断场景下的高危行为类型变体。由 CSLT-08 编排层根据 CSLT-01 的判定结果选择对应变体传入。"
        "非阻断场景时为 null，本模块根据 crisis_result 自动推断。",
    )


# ============================================================================
# GenerationResult（对外输出契约）
# ============================================================================


class GenerationResult(BaseModel):
    """应急方案生成服务的最终输出结果。

    在流式输出完成后由 Service 层组装，传递给下游 CSLT-05 进行置信度后校验，
    同时由 CSLT-06 持久化存储供历史回溯。

    Contract: docs/contracts/CSLT-03/GenerationResult.json
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        description="LLM 生成的完整应急方案全文，为 JSON 格式文本。"
        "包含即时安全干预动作、情绪安抚话术、后续观察指标、就医判断标准四个字段，"
        "以及预编号的来源引用标记如 [1][2]。阻断场景下为空字符串。",
        max_length=65536,
        examples=[
            '{"即时安全干预动作":["将孩子带离嘈杂环境[1]"],"情绪安抚话术":["没关系，妈妈在这里"]}'
        ],
    )
    sections: dict[str, list[str]] = Field(
        default_factory=dict,
        description="从 JSON 文本解析出的四段式结构化数据。"
        "key 为段落标题，value 为该段落的建议列表。JSON 解析失败时各段落为空列表。",
    )
    source_list: list[str] = Field(
        default_factory=list,
        description="被引用案例的来源信息列表。每项格式为 '[N] CASE-XXX 案例标题（录入日期）'。"
        "无引用案例时为空列表。阻断场景下为空列表。",
        examples=[["[1] CASE-042 ASD商场感官过载干预案例（2025-11-03）"]],
    )
    disclaimer: str = Field(
        ...,
        description="法律合规免责声明，每次生成必须包含。"
        "意图文档 §1.11 约束的固定文本，由本模块硬注入至 LLM 输出末尾，不可被 LLM 生成内容覆盖。",
    )
    generation_time_ms: float = Field(
        ...,
        ge=0.0,
        description="从接收输入（校验通过）到完整方案生成完毕的总耗时，单位毫秒。",
        examples=[2850.5],
    )
    is_partial: bool = Field(
        ...,
        description="是否为部分生成结果。LLM 调用超时但已生成至少一个完整段落时为 true，"
        "正常完成时为 false，阻断场景下为 false。",
    )
    referenced_slice_ids: list[str] = Field(
        default_factory=list,
        description="LLM 输出中实际引用的案例切片 ID 列表。"
        "从 LLM 文本中提取 [N] 序号后反查预编号映射表获取。",
        examples=[["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]],
    )
    finish_reason: GenerationStatus = Field(
        ...,
        description="生成结束原因。COMPLETE=正常完成，PARTIAL=超时部分生成，"
        "BLOCKED=危机阻断直接输出安全提示，TIMEOUT=完全超时无任何文本产出，"
        "ERROR=LLM API 不可用或 Prompt 构建异常。",
    )
    ttft_ms: float = Field(
        ...,
        ge=0.0,
        description="首字延迟（Time to First Token），从 LLM API 调用发起到收到第一个 text chunk 的耗时，"
        "单位毫秒。满足意图文档 §1.9 AC-02 的 ≤3000ms 要求。阻断场景下为 0。",
        examples=[1850.0],
    )


# ============================================================================
# GenerationChunk（对外输出契约 — 流式增量块）
# ============================================================================


class GenerationChunk(BaseModel):
    """应急方案流式生成过程中的单个 Token 增量块。

    由 LLM API 的流式响应逐 chunk 拆包后通过 AsyncGenerator 产出，
    下游 CSLT-04 用 async for 消费后封装为 SSE 事件推送给前端。

    Contract: docs/contracts/CSLT-03/GenerationChunk.json
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        description="当前 chunk 的文本增量（delta），即 DeepSeek API 流式响应 choice.delta.content 的值。"
        "仅包含 section 内容文本，JSON 语法字符已被剥离。最后一个 chunk 可能为空字符串。",
        max_length=4096,
        examples=["引导孩子离开嘈杂环境，寻找安静角落"],
    )
    section: str | None = Field(
        default=None,
        description="当前 chunk 所属的四段式段落标题。"
        "值为 即时安全干预动作/情绪安抚话术/后续观察指标/就医判断标准 之一，"
        "或 None 表示 JSON 语法字符（花括号、引号等）或尚未进入任何段落。"
        "前端据此增量追加到对应的 planSections 卡片。",
    )
    is_final: bool = Field(
        ...,
        description="是否为流式输出的最后一个 chunk。true 表示流式输出结束，"
        "下游 CSLT-04 应发送 SSE done 事件并关闭连接。",
    )
    finish_reason: str | None = Field(
        default=None,
        description="流式输出结束原因。仅在 is_final=true 时有值。"
        "stop=正常结束，length=达到 max_tokens 上限，timeout=本模块全流程超时触发强制截断。",
    )
    raw_full_text: str | None = Field(
        default=None,
        description="LLM 返回的原始完整 JSON 文本（含 JSON 语法字符）。"
        "仅在 is_final=True 时填充，供下游 SSE 服务解析四段式 sections 使用。",
    )


# ============================================================================
# PromptBuildContext（内部上下文，不对外暴露）
# ============================================================================


class PromptBuildContext(BaseModel):
    """Prompt 构建的内部上下文 —— 仅在 prompt_builder.py 内使用。

    不对外暴露，不属于任何外部契约。
    用于在 Prompt 构建阶段和流式完成收尾阶段之间传递状态。
    """

    model_config = ConfigDict(extra="forbid")

    prenumbered_slices: list[tuple[str, str]] = Field(
        default_factory=list,
        description="预编号后的切片列表。每项为 (编号文本如'[1]', 切片ID_UUID字符串) 的元组。"
        "用于步骤 6 的反查：从 LLM 输出中提取 [N] 后查找对应的 slice_id。",
    )
    slice_text_block: str = Field(
        default="",
        description="组装完成的「参考案例」区域 Markdown 文本块，"
        "包含全量切片的预编号和循证等级标注。",
    )
    profile_markdown: str = Field(
        default="",
        description="Markdown 格式的患者档案摘要，由上游传入的 profile_summary 字段直接注入。",
    )
    has_cases: bool = Field(
        default=False,
        description="上游是否提供了至少一条案例切片。用于决定 Prompt 中是否包含参考案例区域。",
    )


__all__ = [
    "EmergencyPlanInput",
    "GenerationResult",
    "GenerationChunk",
    "PromptBuildContext",
]
