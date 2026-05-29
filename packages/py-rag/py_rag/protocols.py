"""py-rag 接口契约 — Protocol 定义。

模块: py_rag.protocols
职责: 定义可替换功能组件的结构性子类型（Protocol）。
      实现者不需要显式继承，只需满足接口签名即可。
      与 *_contract.py 的区别：Protocol 用于可替换的叶子组件，
      ABC 用于需要强制模板方法（前置→执行→后置）的核心流程。
数据来源:
  - 无外部数据来源（纯接口定义层）
边界:
  - 依赖: py_rag.models（ChunkMetadata）
  - 被依赖: py_rag.indexing_contract（BaseIndexPipeline 构造参数）
禁止行为:
  - 禁止在 Protocol 中包含实现逻辑
  - 禁止在 Protocol 中定义 @final 方法（那是 ABC 的职责）
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from py_rag.models import ChunkMetadata


class ChunkBuilder(Protocol):
    """文本组装 + PII 校验组件契约。

    任何满足此签名的可调用对象都可作为 ChunkBuilder 注入 BaseIndexPipeline。
    实现者：chunk_builder.build_chunk_text()。
    """

    def __call__(self, case_data: dict[str, Any]) -> tuple[str, ChunkMetadata]:
        """将案例数据库行拼接为向量化文本，执行 PII 防线校验。

        前置:
          - case_data 包含四段式字段（immediate_action, comforting_phrase,
            observation_metrics, medical_criteria）
        后置:
          - 返回 (chunk_text, metadata) 元组
          - chunk_text 不含 PII（手机号/身份证号/家庭住址已脱敏）
        异常:
          - ChunkBuildError: 四段式字段不完整或免责声明丢失
          - PIIRejectionError: 检测到未脱敏的个人信息
        """
        ...


class IndexWriter(Protocol):
    """pgvector 索引写入组件契约。

    任何满足此签名的可调用对象都可作为 IndexWriter 注入 BaseIndexPipeline。
    实现者：index_writer.write_index_to_pgvector()。
    """

    async def __call__(
        self,
        card_id: str,
        chunk_text: str,
        embedding: list[float],
        metadata: ChunkMetadata,
        db_session: AsyncSession,
    ) -> None:
        """将文本切片和向量写入 pgvector 的 case_chunks 表。

        前置:
          - chunk_text 非空
          - embedding 为 1024 维 float 列表
          - metadata 为 ChunkMetadata 实例
        后置:
          - case_chunks 表新增一行（含 id, card_id, chunk_text, embedding, metadata, created_at）
        异常:
          - sqlalchemy.exc.IntegrityError: 唯一约束或外键冲突
          - sqlalchemy.exc.OperationalError: 数据库连接或磁盘问题
        """
        ...
