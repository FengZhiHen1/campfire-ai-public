"""py-rag 数据模型定义。

包含：
- 嵌入相关：无（embedding 模块直接返回 list[float]）
- 索引相关：IndexTaskEnvelope, ChunkMetadata, InternalIndexContext, EmbeddingResponse
- 检索相关：由 py_schemas.consult 定义（SemanticSearchResult, CaseSliceDto 等）
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import Literal

from pydantic import BaseModel, Field

# ============================================================================
# 索引相关模型（CASE-04）
# ============================================================================


class IndexTaskEnvelope(BaseModel):
    """Redis List 异步任务载荷。

    契约引用: docs/contracts/CASE-04/IndexTaskEnvelope.json
    """

    case_id: str = Field(description="案例唯一标识，格式为标准 UUID v4")
    trace_id: str = Field(
        pattern=r"^[a-f0-9]{32}$",
        description="全链路追踪标识，32 位十六进制小写",
    )
    enqueued_at: str = Field(description="任务投递的 ISO 8601 时间戳")


class ChunkMetadata(BaseModel):
    """case_chunks.metadata JSONB 字段的结构化定义。

    契约引用: docs/contracts/CASE-04/ChunkMetadata.json
    消费方: CSLT-02（RAG 语义检索）
    """

    behavior_type: str = Field(description="行为类型")
    age_range: str = Field(description="年龄区间，格式为 'min-max'")
    severity: str = Field(description="严重程度枚举值")
    evidence_level: str = Field(description="循证等级枚举值")
    case_title: str | None = Field(default=None, description="源案例标题")
    source: str | None = Field(default=None, description="案例来源类型（专家撰写/机构脱敏/工单沉淀）")


class InternalIndexContext(BaseModel):
    """Worker 内部处理上下文，不对外暴露。"""

    case_id: uuid_lib.UUID = Field(description="正在处理的案例标识")
    trace_id: str = Field(
        pattern=r"^[a-f0-9]{32}$",
        description="全链路追踪标识",
    )
    retry_count: int = Field(default=0, ge=0, le=2, description="当前重试次数")
    phase: str = Field(description="当前处理阶段: build_chunk_text | generate_embedding | write_index")


class EmbeddingResponse(BaseModel):
    """嵌入 API 返回的嵌入向量（内部模型）。"""

    embedding: list[float] = Field(min_length=1024, max_length=1024, description="1024 维 float32 向量")
    model: str = Field(default="text-embedding-v4", description="嵌入模型名称")


# ============================================================================
# 类型别名
# ============================================================================

EnqueueResult = dict[Literal["status"], Literal["enqueued", "already_queued", "already_indexed"]]
"""enqueue_index_task() 返回字典结构。"""

INDEX_METADATA_KEYS: frozenset[str] = frozenset(
    {"behavior_type", "age_range", "severity", "evidence_level", "case_title", "source"}
)
"""case_chunks.metadata JSONB 键名常量，供 CSLT-02 检索过滤时引用。"""
