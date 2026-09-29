"""摄取：把处理好的 Markdown 切分、嵌入、写入条目表与节点表。

设计依据（RAG 策略第 7 节）：

- **入口是 CLI**（``python -m campfire.cli ingest <路径>``），摄取不暴露成服务端点。
- **一份文件一个事务**：导入失败要么整份成功、要么明确失败并留下可见记录，
  **不留下「一半进去了」的静默状态**。
- **幂等与增量**：按 doc_hash 判断（未变跳过、变了重新 upsert），避免重复嵌入。
- **换嵌入模型必须整库重建**：维度固定 2560，混入不同维度会让检索静默失准。

**实现期实测得到的关键约束**（2026-09-29，决定本模块的事务写法）：

框架的 ``PGVectorStore.add()`` 内部自建并提交 session
（``with self._session() as session, session.begin()``），**无法参与我们的外部事务**。
但 ``__init__`` 接受 ``engine=``/``async_engine=``（两者必须同时给）注入我们自己的
引擎，且 ``store._table_class`` 暴露框架的表模型。因此本模块**不用 ``add()``**，
而是用我们自己的 session、经框架的表模型写节点行——这样条目表与节点表
**在同一个事务里落库**，撤下时才能「同时改条目状态与删节点」（RAG 策略第 2 节）。

框架耦合因此被限制在两处：``_table_class`` 与 ``from_params`` 的构造参数；
两者都由 ``apps/api/tests/test_library_schema_integration.py`` 的集成测试守护。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from campfire.core.config import Settings
from campfire.core.db import to_sync_url
from campfire.modules.library.chunking import Chunk, chunk_markdown_section
from campfire.modules.library.embedding import (
    EMBEDDING_DIM,
    EmbeddingConfigurationError,
    assert_text_within_limit,
    build_embedding,
)
from campfire.modules.library.models import (
    LIBRARY_KNOWLEDGE,
    KnowledgeItem,
    RetrievedNode,
)

#: `PGVectorStore` 的 table_name；框架会渲染成表 `data_campfire_node`（实测约束）。
NODE_TABLE_NAME = "campfire_node"


class IngestionError(Exception):
    """摄取失败：解析、嵌入或写入任一步出错。

    整份文件失败即抛出——**不留「一半进去了」的静默状态**（RAG 策略第 7 节）。
    """


@dataclass
class IngestionResult:
    """一次摄取的结果，供 CLI 输出与导入记账使用。"""

    source_path: str
    item_id: str
    #: 未变而跳过的文件（幂等）：True 时没有写入任何行。
    skipped: bool = False
    chunks_written: int = 0
    #: 因超限且不可分而**未嵌入**的块数——它们进人工处理队列（不静默截断）。
    needs_manual_review: int = 0
    #: 逐块的定位信息，便于撤下时回溯。
    headers: list[str] = field(default_factory=list)


def compute_doc_hash(text: str) -> str:
    """文件内容哈希，用于幂等判断（未变跳过、变了重新 upsert）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_markdown(text: str) -> list[Chunk]:
    """把 Markdown 切成块：框架按标题切 + 我们的两层后处理。

    框架负责按 `#` 层级切分并给出 `header_path`；超长二次切分与结构保护
    由 :mod:`campfire.modules.library.chunking` 负责（框架不做，实测 2248
    字符的 section 原样输出）。
    """
    parser = MarkdownNodeParser()
    nodes = parser.get_nodes_from_documents([Document(text=text)])

    chunks: list[Chunk] = []
    index = 0
    for node in nodes:
        header_path = str(node.metadata.get("header_path", "") or "")
        report = chunk_markdown_section(header_path, node.text, start_index=index)
        chunks.extend(report.chunks)
        index += len(report.chunks)
    return chunks


def build_vector_store(settings: Settings, *, engine: Engine, async_engine: AsyncEngine) -> PGVectorStore:
    """构造指向**迁移建出的**节点表的向量存储。

    两个引擎必须同时注入（框架要求二者同时给或同时不给），这样它读写的是我们
    自己的引擎与连接池，而不是另建一套。

    Raises:
        IngestionError: 未配置 ``DATABASE_URL`` 时——没有库可写，明确失败。
    """
    if not settings.database_url:
        raise IngestionError("未配置 DATABASE_URL，无法写入节点表")

    sync_dsn = to_sync_url(settings.database_url)
    return PGVectorStore(
        connection_string=sync_dsn,
        async_connection_string=settings.database_url,
        table_name=NODE_TABLE_NAME,
        embed_dim=EMBEDDING_DIM,
        perform_setup=False,  # DDL 归 Alembic 迁移所有
        use_jsonb=True,
        engine=engine,
        async_engine=async_engine,
    )


async def _embed_chunks(settings: Settings, chunks: list[Chunk]) -> list[list[float]]:
    """批量嵌入块文本。

    Raises:
        EmbeddingConfigurationError: 缺凭据（透传，调用方需区别于普通失败）。
        IngestionError: 供应商报错，或返回条数与请求不符（后者会静默错配向量与文本）。
    """
    for chunk in chunks:
        assert_text_within_limit(chunk.text)

    try:
        embedder = build_embedding(settings)
        vectors = await embedder.aget_text_embedding_batch([c.text for c in chunks])
    except EmbeddingConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误并保留原因类型
        raise IngestionError(f"嵌入失败：{type(exc).__name__}") from exc

    if len(vectors) != len(chunks):
        raise IngestionError(f"嵌入返回条数不符：期望 {len(chunks)}，得到 {len(vectors)}")
    return vectors


def _node_metadata(item: KnowledgeItem, chunk: Chunk) -> dict[str, str]:
    """节点 metadata：条目投影 + 结构的可过滤/可返回字段（RAG 策略第 2 节）。

    需要在 SQL 层过滤的字段必须同时在 metadata 里，否则过滤会掉到应用层。
    布尔用字符串存——``MetadataFilter`` 的类型联合不含 ``bool``（实测）。
    """
    return {
        "item_id": str(item.id),
        "library": LIBRARY_KNOWLEDGE,
        "status": item.status,
        "withdrawn": "true" if item.withdrawn else "false",
        "title": item.title,
        "source": item.source,
        "applicable_scope": item.applicable_scope,
        "locator": chunk.header_path,
    }


async def _write_nodes(
    session: AsyncSession,
    vector_store: PGVectorStore,
    item: KnowledgeItem,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> None:
    """在同一事务里替换该条目的全部节点。

    先删旧节点再写新节点——更新与撤下走同一套机制，且与条目表状态变更同事务
    （RAG 策略第 2 节：撤下要能同时改状态与删节点）。
    """
    await session.execute(delete(RetrievedNode).where(RetrievedNode.node_id.like(f"{item.id}:%")))

    table = vector_store._table_class  # noqa: SLF001 —— 框架耦合点，由集成测试守护
    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            table(
                node_id=f"{item.id}:{chunk.chunk_index}",
                text=chunk.text,
                embedding=vector,
                metadata_=_node_metadata(item, chunk),
            )
        )
    await session.flush()


async def ingest_file(
    settings: Settings,
    session: AsyncSession,
    *,
    vector_store: PGVectorStore,
    path: Path,
    title: str | None = None,
    source: str,
    applicable_scope: str,
    keywords: str = "",
    aliases: str = "",
) -> IngestionResult:
    """摄取一个 Markdown 文件（调用方负责事务与会话）。

    幂等：同 `source_path` + 同 `doc_hash` 的条目已存在则跳过，不重复嵌入。
    变了的文件：删除其旧节点后重新写入（保证「撤下/更新即刻生效」的同一套机制）。

    Raises:
        IngestionError: 读文件、嵌入或写库任一步失败——由调用方回滚整个事务。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IngestionError(f"读取文件失败：{type(exc).__name__}") from exc

    doc_hash = compute_doc_hash(raw)
    source_path = str(path)

    existing = (
        await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == source_path))
    ).scalar_one_or_none()

    if existing is not None and existing.doc_hash == doc_hash:
        return IngestionResult(source_path=source_path, item_id=str(existing.id), skipped=True)

    chunks = split_markdown(raw)
    if not chunks:
        raise IngestionError("文件未产生任何块（空文件或不含可检索内容）")

    # 只嵌入可嵌入的块；不可分单元进人工处理队列，**不截断**。
    embeddable = [c for c in chunks if not c.needs_manual_review]
    manual = [c for c in chunks if c.needs_manual_review]
    vectors = await _embed_chunks(settings, embeddable)

    item = existing if existing is not None else KnowledgeItem(source_path=source_path)
    item.title = title or path.stem
    item.source = source
    item.applicable_scope = applicable_scope
    item.keywords = keywords
    item.aliases = aliases
    item.doc_hash = doc_hash
    if existing is None:
        session.add(item)
    await session.flush()  # 取到 item.id

    await _write_nodes(session, vector_store, item, embeddable, vectors)

    return IngestionResult(
        source_path=source_path,
        item_id=str(item.id),
        chunks_written=len(embeddable),
        needs_manual_review=len(manual),
        headers=[c.header_path for c in embeddable],
    )
