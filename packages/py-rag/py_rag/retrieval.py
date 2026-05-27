"""CSLT-02 RAG语义检索 — 混合检索引擎。

提供 hybrid_search() 函数，对用户行为描述文本执行混合检索——
先按档案标签精确过滤候选集（SQL WHERE），再按语义相似度 + 时效衰减 +
循证加权的综合分数排序。

核心设计（对应落地规范 §1.5）：
1. 输入校验与预处理 — Top-K 边界钳位、查询指纹计算
2. 编码查询向量 — 调用 DashScope text-embedding-v4
3. 混合检索（精确过滤 + 向量排序）— pgvector HNSW
4. 结果不足时触发降级放宽 — 逐层放宽标签条件
5. 超时保护包装 — asyncio.wait_for 500ms
6. 结果组装与排序 — 综合排序分数计算
7. 输出包装与日志记录 — SemanticSearchResult 组装
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from py_db.repositories.base_repository import DependencyCommunicationError
from py_db.repositories.consult_repository import ConsultRepository
from py_infra.exceptions import EmbeddingUnavailableError, RetrievalTimeoutError
from py_rag.embedding import encode_text
from py_schemas.consult import (
    CaseSliceDto,
    DegradationLevel,
    EvidenceLevel,
    SemanticSearchResult,
    TagFilterDto,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Top-K 边界
_TOP_K_MIN: int = 1
_TOP_K_MAX: int = 50

# 超时阈值（秒）
_TOTAL_TIMEOUT_SECONDS: float = 0.5

# 综合排序权重
_SIMILARITY_WEIGHT: float = 0.5
_TIME_DECAY_WEIGHT: float = 0.25
_EVIDENCE_WEIGHT: float = 0.25

# 时效衰减阶梯（基于案例审核通过距今的年数）
_TIME_DECAY_MAP: list[tuple[float, float]] = [
    (0.0, 1.0),    # < 1 年 → 权重 1.0
    (1.0, 0.7),    # 1-3 年 → 权重 0.7
    (3.0, 0.5),    # > 3 年 → 权重 0.5
]

# 循证等级加权映射
_EVIDENCE_WEIGHT_MAP: dict[str, float] = {
    "NCAEP": 1.0,
    "INSTITUTIONAL_EXPERIENCE": 0.8,
    "CASE_OBSERVATION": 0.6,
}

# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _compute_query_fingerprint(query_text: str) -> str:
    """计算查询文本的 SHA256 指纹。

    使用 SHA256 算法计算查询文本的十六进制哈希值，
    用于日志记录和问题排查，不暴露原始查询内容。

    Args:
        query_text: 用户查询文本。

    Returns:
        64 字符的 SHA256 十六进制指纹字符串。
    """
    return hashlib.sha256(query_text.encode("utf-8")).hexdigest()


def _clamp_top_k(top_k: int) -> int:
    """将 Top-K 钳位到合法范围 [1, 50]。

    Args:
        top_k: 原始期望返回数量。

    Returns:
        钳位后的值（1-50 之间）。
    """
    original = top_k
    clamped = max(_TOP_K_MIN, min(_TOP_K_MAX, top_k))
    if clamped != original:
        _logger.info(
            "top_k_clamped",
            extra={"original": original, "clamped": clamped},
        )
    return clamped


def _compute_time_decay(case_created_at_str: str) -> float:
    """根据案例录入时间计算时效衰减权重。

    采用阶梯函数（triple-step），而非连续衰减函数：
    - 距今 < 1 年 → 权重 1.0
    - 距今 1-3 年 → 权重 0.7
    - 距今 > 3 年 → 权重 0.5

    Args:
        case_created_at_str: 案例审核通过日期字符串（YYYY-MM-DD）。

    Returns:
        时效衰减权重（1.0 / 0.7 / 0.5）。
    """
    try:
        created_at = datetime.strptime(case_created_at_str, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        now = datetime.now(timezone.utc)
        years_since = (now - created_at).total_seconds() / (365.25 * 24 * 3600)

        for threshold, weight in _TIME_DECAY_MAP:
            if threshold == _TIME_DECAY_MAP[-1][0]:
                # 最后一项是兜底（> 3 年）
                return weight
            next_threshold = _TIME_DECAY_MAP[_TIME_DECAY_MAP.index((threshold, weight)) + 1][0]
            if years_since < next_threshold:
                return weight
        return _TIME_DECAY_MAP[-1][1]  # 0.5
    except (ValueError, IndexError):
        # 日期解析失败时取保守值（最高衰减）
        _logger.warning(
            "time_decay_parse_failed",
            extra={"case_created_at": case_created_at_str},
        )
        return 0.5


def _compute_evidence_weight(evidence_level: str | None) -> float:
    """根据循证等级计算加权权重。

    Args:
        evidence_level: 循证等级字符串（NCAEP / INSTITUTIONAL_EXPERIENCE / CASE_OBSERVATION）。

    Returns:
        循证加权权重（1.0 / 0.8 / 0.6），未知等级返回 0.6。
    """
    if evidence_level is None:
        return 0.6
    return _EVIDENCE_WEIGHT_MAP.get(evidence_level, 0.6)


def _compute_composite_score(
    similarity: float,
    case_created_at: str,
    evidence_level: str | None,
) -> float:
    """计算综合排序分数。

    公式：composite = similarity * 0.5 + time_decay * 0.25 + evidence_weight * 0.25

    所有分数保留 4 位小数，防止浮点累加误差导致排序不稳定。

    Args:
        similarity: 余弦语义相似度（0.0-1.0）。
        case_created_at: 案例审核通过日期（YYYY-MM-DD）。
        evidence_level: 循证等级。

    Returns:
        综合排序分数（0.0-1.0），保留 4 位小数。
    """
    time_decay = _compute_time_decay(case_created_at)
    ev_weight = _compute_evidence_weight(evidence_level)

    composite = (
        similarity * _SIMILARITY_WEIGHT
        + time_decay * _TIME_DECAY_WEIGHT
        + ev_weight * _EVIDENCE_WEIGHT
    )
    return round(composite, 4)


def _build_case_slice_dto(row: dict[str, Any]) -> CaseSliceDto:
    """将数据库结果行组装为 CaseSliceDto。

    从行数据和 metadata JSONB 中提取字段，
    计算综合排序分数。

    Args:
        row: search_similar_chunks 返回的结果字典。

    Returns:
        CaseSliceDto 实例。
    """
    metadata: dict[str, Any] = row.get("metadata", {})
    case_created_at: str = metadata.get("case_created_at", "2020-01-01")
    evidence_level_str: str | None = metadata.get("evidence_level")
    similarity: float = row.get("similarity", 0.0)
    composite_score: float = _compute_composite_score(
        similarity=similarity,
        case_created_at=case_created_at,
        evidence_level=evidence_level_str,
    )

    # 解析证据等级枚举
    evidence_level: EvidenceLevel = EvidenceLevel.NCAEP
    if evidence_level_str:
        try:
            evidence_level = EvidenceLevel(evidence_level_str)
        except ValueError:
            evidence_level = EvidenceLevel.CASE_OBSERVATION

    return CaseSliceDto(
        slice_id=row.get("id", ""),
        case_id=row.get("case_id", ""),
        slice_text=row.get("chunk_text", ""),
        chunk_type=row.get("chunk_type"),
        similarity_score=round(similarity, 4),
        composite_score=composite_score,
        evidence_level=evidence_level,
        case_title=metadata.get("case_title"),
        source=metadata.get("source"),
        case_created_at=case_created_at,
        applicable_tags=metadata.get("applicable_tags"),
    )


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------


async def hybrid_search(
    query_text: str,
    tag_filters: TagFilterDto,
    top_k: int = 10,
    request_id: str | None = None,
    db: AsyncSession = None,  # type: ignore[assignment]
) -> SemanticSearchResult:
    """对用户行为描述文本执行混合检索。

    先按档案标签精确过滤候选集（SQL WHERE），再按语义相似度 + 时效衰减 +
    循证加权的综合分数排序。支持降级放宽和超时保护。

    Args:
        query_text: 用户行为描述文本（1-2000 字符，上游已脱敏 PII）。
        tag_filters: 档案标签过滤条件（年龄段、行为类型、情绪等级等）。
        top_k: 期望返回的结果数量（默认 10，范围 1-50）。
        request_id: 全链路追踪 ID（可选，由上游生成）。
        db: 异步数据库会话（由调用方注入）。

    Returns:
        SemanticSearchResult: 排序后的案例切片列表及检索状态。

    Raises:
        EmbeddingUnavailableError: DashScope 编码服务不可用（重试耗尽）。
        RetrievalTimeoutError: 整体检索超过 500ms 且无任何结果。
        DependencyCommunicationError: PostgreSQL 连接失败（重试耗尽）。

    Side Effects:
        - 记录结构化日志（含 query_fingerprint，不含完整查询文本）。
        - 不执行任何写操作（纯只读）。
    """
    # --- 入口参数校验 ---
    if not isinstance(query_text, str):
        raise ValueError(
            f"query_text must be a string, got {type(query_text).__name__}"
        )

    # --- 步骤 1：输入预处理（top_k clamping 必须在 query_text 长度校验之前执行）---
    query_fingerprint: str = _compute_query_fingerprint(query_text)
    actual_top_k: int = _clamp_top_k(top_k)

    if not query_text:
        raise ValueError("query_text must not be empty")
    if len(query_text) > 2000:
        raise ValueError("query_text must not exceed 2000 characters")
    if tag_filters is None:
        raise ValueError("tag_filters must not be None")
    if db is None:
        raise ValueError("db must not be None")

    # 降级层级执行顺序（从严格到宽松）
    degradation_levels: list[DegradationLevel] = [
        DegradationLevel.NONE,
        DegradationLevel.EMOTION_RELAXED,
        DegradationLevel.BEHAVIOR_RELAXED,
        DegradationLevel.ALL_TAGS_REMOVED,
    ]

    # 可变容器，用于在超时时捕获部分结果
    partial_results: list[dict[str, Any]] = []
    query_vector: list[float] | None = None
    embedding_successful: bool = False
    final_degradation: DegradationLevel = DegradationLevel.NONE

    start_time: float = time.monotonic()

    # --- 内部搜索管道（包装在 asyncio.wait_for 中） ---
    async def _search_pipeline() -> list[dict[str, Any]]:
        """内部搜索管道协程。

        依次执行：向量编码 → 逐层检索 → 降级放宽。
        结果逐步追加到 partial_results 列表，超时时可返回部分结果。
        """
        nonlocal query_vector, embedding_successful, final_degradation

        # 步骤 2：编码查询向量
        query_vector = await encode_text(query_text, text_type="query")
        embedding_successful = True

        # 步骤 3+4：执行混合检索（精确过滤 + 向量排序），结果不足时触发降级放宽
        repo = ConsultRepository()

        for level in degradation_levels:
            # 根据当前降级层级执行查询
            emotion_level_param: str | None = (
                tag_filters.emotion_level
                if level == DegradationLevel.NONE
                else None
            )
            behavior_type_param: str = (
                tag_filters.behavior_type
                if level in (DegradationLevel.NONE, DegradationLevel.EMOTION_RELAXED)
                else ""
            )
            age_range_param: str = (
                tag_filters.age_range
                if level
                in (
                    DegradationLevel.NONE,
                    DegradationLevel.EMOTION_RELAXED,
                    DegradationLevel.BEHAVIOR_RELAXED,
                )
                else ""
            )

            rows = await repo.search_similar_chunks(
                session=db,
                query_vector=query_vector,
                age_range=age_range_param,
                behavior_type=behavior_type_param,
                emotion_level=emotion_level_param,
                top_k=actual_top_k,
                degradation_level=level,
            )

            partial_results.extend(rows)
            final_degradation = level

            # 达到目标数量即停止降级
            if len(partial_results) >= actual_top_k:
                # 截断到 top_k
                del partial_results[actual_top_k:]
                break

        return partial_results[:actual_top_k]

    # --- 步骤 5：超时保护包装 ---
    try:
        final_rows: list[dict[str, Any]] = await asyncio.wait_for(
            _search_pipeline(), timeout=_TOTAL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        # 超时触发：返回已有部分结果
        elapsed_ms: float = (time.monotonic() - start_time) * 1000
        final_rows = list(partial_results)  # 复制当前部分结果

        if not embedding_successful:
            # 编码阶段本身超时（无任何数据库结果）
            _logger.warning(
                "search_timeout_embedding_unavailable",
                extra={
                    "request_id": request_id,
                    "query_fingerprint": query_fingerprint,
                    "elapsed_ms": round(elapsed_ms, 1),
                },
            )
            return SemanticSearchResult(
                results=[],
                total_count=0,
                is_complete=False,
                reason="embedding_unavailable",
                query_fingerprint=query_fingerprint,
                degradation_applied=True,
                degradation_level=final_degradation,
                elapsed_ms=round(elapsed_ms, 1),
            )

        if len(final_rows) == 0:
            # 超时且无任何结果
            _logger.warning(
                "search_timeout_no_results",
                extra={
                    "request_id": request_id,
                    "query_fingerprint": query_fingerprint,
                    "elapsed_ms": round(elapsed_ms, 1),
                },
            )
            return SemanticSearchResult(
                results=[],
                total_count=0,
                is_complete=False,
                reason="timeout",
                query_fingerprint=query_fingerprint,
                degradation_applied=True,
                degradation_level=final_degradation,
                elapsed_ms=round(elapsed_ms, 1),
            )

        # 超时但有部分结果
        _logger.warning(
            "search_timeout_partial",
            extra={
                "request_id": request_id,
                "partial_count": len(final_rows),
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
        # 继续到步骤 6（组装排序），标记 is_complete=False, degradation_applied=True
        elapsed_total: float = elapsed_ms
        _timeout_partial: bool = True  # 标记供后续步骤使用
    else:
        # 正常完成（未超时）
        elapsed_total: float = (time.monotonic() - start_time) * 1000
        _timeout_partial = False

    # --- 步骤 6：结果组装与排序 ---
    # 计算综合排序分数
    case_slices: list[CaseSliceDto] = []
    for row in final_rows:
        slice_dto = _build_case_slice_dto(row)
        case_slices.append(slice_dto)

    # 按 composite_score 降序排序（分数相同时按 case_created_at 降序）
    case_slices.sort(
        key=lambda s: (s.composite_score, s.case_created_at or ""),
        reverse=True,
    )

    # 再次截断确保不超过 top_k
    case_slices = case_slices[:actual_top_k]

    # 判断是否触发降级
    degradation_applied: bool = (
        final_degradation != DegradationLevel.NONE or _timeout_partial
    )
    is_complete: bool = not _timeout_partial
    reason: str | None = None

    # 空库检测（如果三层降级后仍为 0 条）
    if len(case_slices) == 0 and embedding_successful:
        is_complete = True
        reason = "case_library_empty"
        _logger.info(
            "case_library_empty",
            extra={
                "request_id": request_id,
                "query_fingerprint": query_fingerprint,
            },
        )

    # --- 步骤 7：输出包装与日志记录 ---
    result = SemanticSearchResult(
        results=case_slices,
        total_count=len(case_slices),
        is_complete=is_complete,
        reason=reason,
        query_fingerprint=query_fingerprint,
        degradation_applied=degradation_applied,
        degradation_level=final_degradation,
        elapsed_ms=round(elapsed_total, 1),
    )

    # 结构化日志记录（不包含完整查询文本）
    _logger.info(
        "semantic_search_completed",
        extra={
            "trace_id": request_id,
            "query_len": len(query_text),
            "filters": {
                "age_range": tag_filters.age_range,
                "behavior_type": tag_filters.behavior_type,
                "emotion_level": tag_filters.emotion_level,
            },
            "result_count": result.total_count,
            "elapsed_ms": result.elapsed_ms,
            "degradation_level": result.degradation_level.value,
            "degradation_applied": result.degradation_applied,
            "is_complete": result.is_complete,
            "query_fingerprint": result.query_fingerprint,
        },
    )

    return result


__all__ = ["hybrid_search"]
