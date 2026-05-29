"""py-rag 索引入库行为契约 — ABC 模板方法。

模块: py_rag.indexing_contract
职责: 定义案例向量化入库异步管线的契约骨架。
      包含两个 ABC：
      - BaseIndexService: 索引任务投递（同步返回，< 50ms）
      - BaseIndexPipeline: Worker 消费处理（文本组装 → 嵌入编码 → 索引写入）
数据来源:
  - Redis List: MUST — index:queue:case_chunks 异步任务队列
  - case_cards 表: MUST — 审核通过案例的四段式字段 + 元数据
  - EmbeddingEncoder: MUST — 调用嵌入服务生成文档向量
  - pgvector case_chunks 表: MUST — 向量索引写入目标
边界:
  - 依赖: py_cache（Redis 客户端）
  - 依赖: py_rag.embedding_contract（编码文档文本）
  - 依赖: py_rag.indexing.chunk_builder（文本组装 + PII 校验）
  - 依赖: py_rag.indexing.index_writer（pgvector 写入）
  - 被依赖: api-server（审核通过后触发索引入队）
禁止行为:
  - 禁止在 Service 层直接操作 Redis 之外的资源
  - 禁止 Worker 主循环中裸捕获 Exception 后静默吞掉
  - 禁止索引管线任一步骤失败时跳过状态更新（必须写 indexing_failed）
"""

from __future__ import annotations

import json
import secrets
import uuid as uuid_lib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, final

from sqlalchemy.ext.asyncio import AsyncSession

from py_rag.models import ChunkMetadata
from py_rag.protocols import ChunkBuilder, IndexWriter
from py_rag.types import CaseIdStr, TraceIdStr

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

INDEX_QUEUE_KEY: str = "index:queue:case_chunks"
REDIS_LPUSH_RETRY_COUNT: int = 1
REDIS_LPUSH_RETRY_INTERVAL: float = 0.5


# ============================================================================
# BaseIndexService — 索引任务投递
# ============================================================================


class BaseIndexService(ABC):
    """索引任务投递服务契约。

    实现者只能覆写 _do_ 前缀的钩子。
    调用者只能使用 @final 标记的公共方法。
    """

    @final
    async def enqueue(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """将审核通过的案例投递到索引入库异步队列。

        前置校验 → 状态查询 → 幂等判断 → 投递 Redis List。
        此方法不可覆写（@final）。同步返回，耗时 < 50ms。

        前置:
          - case_id 为有效的 UUID v4 字符串
          - db_session 为有效异步会话
          - 案例存在于 case_cards 表且 review_status = 'approved'
        后置:
          - 案例 index_status 更新为 'pending'
          - 任务载荷 JSON LPUSH 到 Redis List
          - 状态 CAS 冲突时返回 'already_queued'
        输入约束:
          - case_id: UUID v4 格式字符串
          - db_session: SQLAlchemy 异步会话
        输出约束:
          - {"status": "enqueued" | "already_queued" | "already_indexed"}
        异常:
          - ValueError: case_id 格式无效、案例不存在或未审核通过
          - RedisConnectionError: Redis LPUSH 重试耗尽
        """
        self._validate_case_id(case_id)

        status = await self._check_case_status(case_id, db_session)
        if status is None:
            raise ValueError(f"案例 {case_id} 不存在")
        if status == "already_indexed":
            return {"status": "already_indexed"}
        if status == "already_queued":
            return {"status": "already_queued"}
        if status != "approved_pending":
            raise ValueError(f"案例 {case_id} 未审核通过，当前状态不允许入队")

        result = await self._do_enqueue(case_id, db_session)
        self._validate_enqueue_result(result)
        return result

    @final
    async def manual_retry(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """对索引入库失败的案例执行手动重新索引。

        仅当案例 index_status = 'indexing_failed' 时允许调用。
        """
        self._validate_case_id(case_id)

        status = await self._check_case_status(case_id, db_session)
        if status is None:
            raise ValueError(f"案例 {case_id} 不存在")
        if status != "failed":
            raise ValueError(
                f"案例当前索引状态非异常，不允许手动重试（当前状态不允许）"
            )

        result = await self._do_enqueue(case_id, db_session)
        self._validate_enqueue_result(result)
        return result

    def _validate_enqueue_result(self, result: dict[str, str]) -> None:
        """基线后置校验：返回字典包含 status 键。"""
        if not isinstance(result, dict) or "status" not in result:
            raise RuntimeError("入队结果必须包含 status 键")

    @abstractmethod
    async def _do_enqueue(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """执行实际的 Redis LPUSH 投递操作 + 状态更新。

        实现者在此填写：生成 trace_id → 构建 IndexTaskEnvelope →
        LPUSH 到 Redis → CAS UPDATE case_cards SET index_status='pending'

        输入约束:
          - case_id 已通过前置校验
          - 案例状态已确认为可入队
        输出约束:
          - 返回 {"status": "enqueued"} 或 {"status": "already_queued"}（CAS 冲突）
        异常:
          - RedisConnectionError: LPUSH 操作失败
        """
        ...

    def _validate_case_id(self, case_id: CaseIdStr) -> None:
        """基线前置校验：case_id 格式有效。"""
        try:
            uuid_lib.UUID(str(case_id))
        except (ValueError, AttributeError):
            raise ValueError(f"无效的 case_id 格式：{case_id}")

    @abstractmethod
    async def _check_case_status(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> str | None:
        """查询案例审核与索引状态。

        Returns:
            'approved_pending' — 可入队
            'already_indexed' — 已索引，幂等跳过
            'already_queued' — 已在队列中，幂等跳过
            'failed' — 索引失败，可手动重试
            None — 案例不存在
        """
        ...


# ============================================================================
# BaseIndexPipeline — 索引管线 Worker
# ============================================================================


class BaseIndexPipeline(ABC):
    """索引管线 Worker 契约。

    定义索引处理的完整管线：文本组装 → 嵌入编码 → 索引写入。
    实现者只能覆写 _do_ 前缀的钩子。
    """

    def __init__(
        self,
        embedding_encoder: object,
        chunk_builder: ChunkBuilder,
        index_writer: IndexWriter,
    ) -> None:
        """注入可替换组件。

        embedding_encoder: BaseEmbeddingEncoder 实例
        chunk_builder: 满足 ChunkBuilder Protocol 的可调用对象
        index_writer: 满足 IndexWriter Protocol 的可调用对象
        """
        self._encoder = embedding_encoder
        self._chunk_builder = chunk_builder
        self._index_writer = index_writer

    @final
    async def process_task(
        self,
        case_id: CaseIdStr,
        trace_id: str,
        db_session: AsyncSession,
    ) -> None:
        """处理单个索引任务（完整管线）。

        步骤：状态更新 → 读取案例数据 → 文本组装 → 嵌入编码 → 索引写入 → 状态标记。
        此方法不可覆写（@final）。

        前置:
          - case_id 对应的案例 index_status = 'pending'
          - trace_id 为 32 位十六进制字符串
          - db_session 为有效异步会话
        后置:
          - 成功：index_status = 'indexed'，case_chunks 新增一行
          - 失败：index_status = 'indexing_failed'，记录错误详情
        异常:
          - 任一步骤失败均通过 _do_mark_failed 标记后静默返回
        """
        self._validate_task_preconditions(case_id, trace_id, db_session)

        # 步骤 1：CAS 更新状态为 processing
        if not await self._do_update_status_to_processing(case_id, db_session):
            return  # CAS 冲突，跳过

        # 步骤 2：读取案例数据
        case_data = await self._do_read_case_data(case_id, db_session)
        if case_data is None:
            await self._do_mark_failed(
                case_id, "案例数据读取失败：行不存在", "read_case", db_session
            )
            return

        # 步骤 3：文本组装与 PII 校验
        try:
            chunk_text, metadata = await self._do_build_chunk(case_data)
        except Exception as exc:
            await self._do_mark_failed(
                case_id, str(exc), "build_chunk_text", db_session
            )
            return

        # 步骤 4：调用嵌入服务生成文档向量
        try:
            embedding_list = await self._do_generate_embedding(chunk_text)
        except Exception as exc:
            await self._do_mark_failed(
                case_id, f"嵌入服务调用失败: {exc}", "generate_embedding", db_session
            )
            return

        # 步骤 5：写入 pgvector 索引
        try:
            await self._do_write_index(
                case_id, chunk_text, embedding_list, metadata, db_session
            )
        except Exception as exc:
            await self._do_mark_failed(
                case_id, f"pgvector 索引写入失败: {exc}", "write_index", db_session
            )
            return

        # 步骤 6：标记为 indexed
        await self._do_mark_indexed(case_id, db_session)
        self._validate_task_postconditions(case_id)

    # === 校验器方法 ===

    def _validate_task_preconditions(
        self,
        case_id: CaseIdStr,
        trace_id: str,
        db_session: AsyncSession,
    ) -> None:
        """基线前置校验：参数非空。"""
        if not case_id:
            raise ValueError("case_id 不能为空")
        if not trace_id:
            raise ValueError("trace_id 不能为空")
        if db_session is None:
            raise ValueError("db_session 不能为 None")

    def _validate_task_postconditions(self, case_id: CaseIdStr) -> None:
        """基线后置校验：标记 indexed 后验证。子类可叠加。"""

    # === @abstractmethod 钩子：实现者必填 ===

    @abstractmethod
    async def _do_update_status_to_processing(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> bool:
        """CAS 更新 index_status 为 'processing'。

        UPDATE case_cards SET index_status='processing'
        WHERE card_id=:id AND index_status='pending'

        Returns:
            True 表示更新成功，False 表示 CAS 冲突应跳过。
        """
        ...

    @abstractmethod
    async def _do_read_case_data(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> dict[str, Any] | None:
        """读取 case_cards JOIN case_narratives 完整数据。

        Returns:
            案例数据字典，不存在时返回 None。
        """
        ...

    async def _do_build_chunk(
        self,
        case_data: dict[str, Any],
    ) -> tuple[str, ChunkMetadata]:
        """文本组装 + PII 校验。

        委托注入的 ChunkBuilder Protocol 实例。
        子类可覆写以改变组装行为（默认不需要）。

        Returns:
            (chunk_text, ChunkMetadata) 元组。
        Raises:
            ChunkBuildError, PIIRejectionError
        """
        return self._chunk_builder(case_data)

    @abstractmethod
    async def _do_generate_embedding(
        self,
        chunk_text: str,
    ) -> list[float]:
        """调用嵌入服务生成文档向量。

        委托 embedding_contract.BaseEmbeddingEncoder.encode()。
        """
        ...

    async def _do_write_index(
        self,
        case_id: CaseIdStr,
        chunk_text: str,
        embedding: list[float],
        metadata: ChunkMetadata,
        db_session: AsyncSession,
    ) -> None:
        """写入 pgvector case_chunks 表。

        委托注入的 IndexWriter Protocol 实例。
        子类可覆写以改变写入行为（默认不需要）。
        """
        await self._index_writer(
            card_id=str(case_id),
            chunk_text=chunk_text,
            embedding=embedding,
            metadata=metadata,
            db_session=db_session,
        )

    @abstractmethod
    async def _do_mark_indexed(
        self,
        case_id: CaseIdStr,
        db_session: AsyncSession,
    ) -> None:
        """CAS 更新 index_status 为 'indexed'。

        UPDATE case_cards SET index_status='indexed', indexed_at=:now
        WHERE card_id=:id AND index_status='processing'
        """
        ...

    @abstractmethod
    async def _do_mark_failed(
        self,
        case_id: CaseIdStr,
        error: str,
        phase: str,
        db_session: AsyncSession,
    ) -> None:
        """更新 index_status 为 'indexing_failed' 并记录错误日志。"""
        ...
