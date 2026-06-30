"""py-rag 语义检索行为契约 — ABC 模板方法。

模块: py_rag.retrieval_contract
职责: 定义语义检索引擎的契约骨架。编码查询向量 → 检索相似切片 → 组装排序结果。
      调用者走 @final search 公共入口，实现者只能覆写 _do_ 前缀的钩子。
数据来源:
  - EmbeddingEncoder: MUST — 编码查询文本为向量
  - PostgreSQL + pgvector: MUST — case_chunks 表 HNSW 语义检索
  - ConsultRepository (py_db): MUST — search_similar_chunks() 封装数据库查询
边界:
  - 依赖: py_rag.embedding_contract（查询向量编码）
  - 依赖: py_db.repositories.consult_repository（数据库检索）
  - 依赖: py_schemas.consult（SemanticSearchResult, CaseSliceDto, EvidenceLevel, DegradationLevel）
  - 被依赖: api-server consult_service（CSLT-02 RAG 检索编排）
禁止行为:
  - 禁止在检索函数中执行 case_chunks 表的 INSERT/UPDATE/DELETE（纯只读）
  - 禁止在日志中记录完整的用户查询文本（仅记录 query_fingerprint）
  - 禁止同步阻塞调用（必须全链路异步）
  - 禁止绕过 _validate_input 前置校验直接调用 _do_search
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any, final

from sqlalchemy.ext.asyncio import AsyncSession

from py_rag.embedding_contract import BaseEmbeddingEncoder
from py_rag.types import (
    TOP_K_MAX,
    TOP_K_MIN,
    CompositeScore,
    EmbeddingVector,
    QueryFingerprint,
    SimilarityScore,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 检索全流程超时：包含查询编码、向量检索与结果组装。
# 考虑到 DashScope embedding 在高峰期可能接近 5~10s，预留充足余量。
_TOTAL_TIMEOUT_SECONDS: float = 30.0


class BaseSemanticSearch(ABC):
    """语义检索引擎契约。

    实现者只能覆写 _do_ 前缀的钩子。
    调用者只能使用 @final 标记的公共方法。
    """

    def __init__(self, embedding_encoder: BaseEmbeddingEncoder) -> None:
        """需要注入嵌入编码器实例。"""
        self._encoder = embedding_encoder

    @final
    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        request_id: str | None = None,
        db: AsyncSession | None = None,
    ) -> Any:  # SemanticSearchResult
        """对用户行为描述文本执行纯语义检索。

        输入校验 → 编码查询向量 → 检索相似切片 → 结果组装排序。
        此方法不可覆写（@final）。

        前置:
          - query_text 为非空字符串，长度 1-2000 字符
          - top_k 在 [1, 50] 范围内（超出自动钳位）
          - db 为有效的 AsyncSession（非 None）
        后置:
          - 返回 SemanticSearchResult（可能为空列表）
          - 超时时返回部分结果（is_complete=False）
          - 不抛异常（检索失败降级为空结果）
        输入约束:
          - query_text: 1-2000 字符，上游已脱敏 PII
          - top_k: 默认 10，合法范围 [1, 50]
          - request_id: 可选全链路追踪 ID
          - db: 调用方注入的异步数据库会话
        输出约束:
          - SemanticSearchResult: 排序后的案例切片列表及检索状态
          - 结果按 composite_score 降序排列
        异常:
          - EmbeddingUnavailableError: 编码服务不可用（重试耗尽）
          - RetrievalTimeoutError: 整体检索超时且无任何结果
          - DependencyCommunicationError: PostgreSQL 连接失败
        Side Effects:
          - 记录结构化日志（含 query_fingerprint，不含完整查询文本）
          - 不执行任何写操作（纯只读）
        """
        actual_top_k, query_fingerprint = self._validate_input(
            query_text, top_k, db
        )

        query_vector: EmbeddingVector | None = None
        embedding_successful: bool = False
        start_time: float = time.monotonic()

        async def _search_pipeline() -> list[dict[str, Any]]:
            nonlocal query_vector, embedding_successful

            query_vector = await self._encoder.encode(query_text, text_type="query")
            embedding_successful = True

            return await self._do_search(
                query_vector,
                actual_top_k,
                db,  # type: ignore[arg-type]
            )

        try:
            final_rows = await asyncio.wait_for(
                _search_pipeline(), timeout=_TOTAL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            elapsed_ms: float = (time.monotonic() - start_time) * 1000

            if not embedding_successful:
                from py_schemas.consult import DegradationLevel, SemanticSearchResult

                return SemanticSearchResult(
                    results=[],
                    total_count=0,
                    is_complete=False,
                    reason="embedding_unavailable",
                    query_fingerprint=query_fingerprint,
                    degradation_applied=False,
                    degradation_level=DegradationLevel.NONE,
                    elapsed_ms=round(elapsed_ms, 1),
                )

            from py_schemas.consult import DegradationLevel, SemanticSearchResult

            return SemanticSearchResult(
                results=[],
                total_count=0,
                is_complete=False,
                reason="timeout",
                query_fingerprint=query_fingerprint,
                degradation_applied=False,
                degradation_level=DegradationLevel.NONE,
                elapsed_ms=round(elapsed_ms, 1),
            )

        elapsed_total: float = (time.monotonic() - start_time) * 1000

        case_slices = []
        for row in final_rows:
            slice_dto = self._build_case_slice_dto(row)
            case_slices.append(slice_dto)

        case_slices.sort(
            key=lambda s: (s.composite_score, s.case_created_at or ""),
            reverse=True,
        )
        case_slices = case_slices[:actual_top_k]

        reason: str | None = None
        if len(case_slices) == 0 and embedding_successful:
            reason = "case_library_empty"

        from py_schemas.consult import DegradationLevel, SemanticSearchResult

        result = SemanticSearchResult(
            results=case_slices,
            total_count=len(case_slices),
            is_complete=True,
            reason=reason,
            query_fingerprint=query_fingerprint,
            degradation_applied=False,
            degradation_level=DegradationLevel.NONE,
            elapsed_ms=round(elapsed_total, 1),
        )

        self._validate_result(result)
        return result

    # === @abstractmethod 钩子：实现者必填 ===

    @abstractmethod
    async def _do_search(
        self,
        query_vector: EmbeddingVector,
        top_k: int,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """执行数据库语义检索（pgvector HNSW）。

        实现者在此填写数据库查询逻辑。
        不需要关心编码和校验——@final search 已处理。

        输入约束:
          - query_vector: 已通过维度校验的 1024 维向量
          - top_k: 已钳位到 [1, 50]
          - db: 有效异步会话
        输出约束:
          - 返回原始数据库行字典列表（由 search 组装为 SemanticSearchResult）
        异常:
          - sqlalchemy.exc.OperationalError: 数据库连接失败
        """
        ...

    # === 可覆写钩子：实现者可选定制 ===

    def _compute_query_fingerprint(self, query_text: str) -> QueryFingerprint:
        """计算查询文本 SHA256 指纹。

        基线实现使用 hashlib.sha256。
        子类可覆写以使用不同哈希算法。
        """
        return QueryFingerprint(
            hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        )

    def _build_case_slice_dto(self, row: dict[str, Any]) -> Any:
        """将数据库结果行组装为 CaseSliceDto。

        基线实现从 metadata JSONB 提取字段并计算综合排序分数。
        子类可覆写以调整组装逻辑或排序公式。
        """
        from py_schemas.consult import CaseSliceDto, EvidenceLevel

        metadata: dict[str, Any] = row.get("metadata", {})
        case_created_at: str = metadata.get("case_created_at", "2020-01-01")
        similarity: float = row.get("similarity", 0.0)
        composite_score = CompositeScore(round(similarity, 4))

        evidence_level_str: str | None = metadata.get("evidence_level")
        evidence_level: EvidenceLevel = EvidenceLevel.NCAEP
        if evidence_level_str:
            try:
                evidence_level = EvidenceLevel(evidence_level_str)
            except ValueError:
                evidence_level = EvidenceLevel.CASE_OBSERVATION

        return CaseSliceDto(
            slice_id=row.get("id", ""),
            card_id=row.get("card_id", ""),
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

    # === 校验器方法 ===

    def _validate_input(
        self,
        query_text: str,
        top_k: int,
        db: AsyncSession | None,
    ) -> tuple[int, QueryFingerprint]:
        """基线前置校验：参数合法性 + top_k 钳位 + 查询指纹计算。

        子类可通过 super() 叠加业务级校验。
        返回 (actual_top_k, query_fingerprint) 供后续步骤使用。
        """
        if not isinstance(query_text, str):
            raise ValueError(
                f"query_text 必须为字符串类型，实际为 {type(query_text).__name__}"
            )
        if not query_text:
            raise ValueError("query_text 不能为空")
        if len(query_text) > 2000:
            raise ValueError(f"query_text 超过最大长度限制（2000），实际 {len(query_text)}")
        if db is None:
            raise ValueError("db 不能为 None")

        actual_top_k = max(TOP_K_MIN, min(TOP_K_MAX, top_k))
        query_fingerprint = self._compute_query_fingerprint(query_text)
        return actual_top_k, query_fingerprint

    def _validate_result(self, result: Any) -> None:
        """基线后置校验：结果对象结构完整。

        子类可通过 super() 叠加业务级校验。
        """
        if result is None:
            raise RuntimeError("SemanticSearchResult 不能为 None")
