"""py-rag 语法契约 — 语义类型与数据结构定义。

模块: py_rag.types
职责: 定义 py-rag 包所有公开接口使用的语义类型（NewType）、枚举与数据模型。
      每个语义概念只在此处定义一次，禁止裸用原始类型。
数据来源:
  - 无外部数据来源（纯类型定义层）
边界:
  - 依赖: Python 标准库 typing、pydantic（与项目技术栈一致）
  - 被依赖: py_rag 内所有模块、py_schemas（检索相关类型由 py_schemas.consult 定义）
禁止行为:
  - 禁止在 types.py 中包含任何实现逻辑（无 HTTP 调用、无数据库连接）
  - 禁止裸用 str/int/float/list 表示已定义 NewType 的语义概念
  - 禁止在此文件定义与 py_schemas 重复的检索相关 Pydantic 模型
"""

from __future__ import annotations

from typing import NewType

# ============================================================================
# 嵌入相关语义类型
# ============================================================================


# === EmbeddingVector ===
# 前置: 从嵌入 API 返回的 list[float] 经维度校验（1024）后包装
# 后置: 仅用于向量检索（pgvector <=> 算子）和日志记录，不直接修改内部值
# 输入约束: 长度必须为 1024，元素为 float32 范围内的浮点数
# 输出约束: 通过 NewType 防止与普通 list[float] 混用
EmbeddingVector = NewType("EmbeddingVector", list[float])


# === EmbeddingModelName ===
# 前置: 无
# 后置: 标识当前使用的嵌入模型，写入 EmbeddingResponse.model 字段
EmbeddingModelName = NewType("EmbeddingModelName", str)


# ============================================================================
# 索引相关语义类型
# ============================================================================


# === CaseIdStr ===
# 前置: 外部传入的 case_id，格式为 UUID v4 字符串
# 后置: 用于日志记录、数据库查询和状态更新，非 UUID 格式应被前置校验拦截
CaseIdStr = NewType("CaseIdStr", str)


# === TraceIdStr ===
# 前置: secrets.token_hex(16) 生成，32 位十六进制小写
# 后置: 全链路追踪标识，贯穿索引管线各阶段日志
TraceIdStr = NewType("TraceIdStr", str)


# === ChunkIdStr ===
# 前置: uuid.uuid4() 生成
# 后置: 标识 case_chunks 表中的唯一切片行
ChunkIdStr = NewType("ChunkIdStr", str)


# ============================================================================
# 检索相关语义类型
# ============================================================================


# === QueryFingerprint ===
# 前置: hashlib.sha256(query_text.encode()).hexdigest() 计算
# 后置: 64 字符十六进制指纹，用于日志关联，不暴露原始查询文本
QueryFingerprint = NewType("QueryFingerprint", str)


# === SimilarityScore ===
# 前置: pgvector <=> 算子返回值经 1 - distance 转换
# 后置: 保留 4 位小数，范围 [0.0, 1.0]
SimilarityScore = NewType("SimilarityScore", float)


# === CompositeScore ===
# 前置: 由语义相似度、时效权重、循证权重加权计算
# 后置: 保留 4 位小数，范围 [0.0, 1.0]，用于结果排序
CompositeScore = NewType("CompositeScore", float)


# ============================================================================
# 类型别名
# ============================================================================

# TopK 合法范围常量
TOP_K_MIN: int = 1
TOP_K_MAX: int = 50

# 嵌入维度常量
EMBEDDING_DIMENSION: int = 1024

# 索引元数据 JSONB 键名集合
INDEX_METADATA_KEYS: frozenset[str] = frozenset(
    {"behavior_type", "age_range", "severity", "evidence_level", "case_title", "source"}
)
