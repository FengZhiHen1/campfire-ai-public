"""摄取：把处理好的 Markdown 切分、嵌入、写入条目表与节点表。

职责：把一份 Markdown 切成块、批量嵌入，并在一个事务里写入条目表与节点表。
边界：只做摄取，不暴露服务端点（入口是 CLI）；缺来源或缺适用范围的元数据一律拒绝入库。
参考：docs/技术设计/technical-details/RAG策略.md 第 1.1、1.2、2、7 节；细节见 `ingest_file`、`build_vector_store`、`_write_nodes` 的 docstring。
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

    整份文件失败即抛出——不留「一半进去了」的静默状态（RAG 策略第 7 节）。
    """


@dataclass
class IngestionResult:
    """一次摄取的结果，供 CLI 输出与导入记账使用。"""

    source_path: str
    item_id: str
    #: 未变而跳过的文件（幂等）：True 时没有写入任何行。
    skipped: bool = False
    chunks_written: int = 0
    #: 因超限且不可分而未嵌入的块数——它们进人工处理队列（不静默截断）。
    needs_manual_review: int = 0
    #: 逐块的定位信息，便于撤下时回溯。
    headers: list[str] = field(default_factory=list)


def compute_doc_hash(text: str) -> str:
    """文件内容哈希，用于幂等判断（未变跳过、变了重新 upsert）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: 语料文件的 YAML frontmatter 分隔符（首行 `---` 起、下一行 `---` 止）。
_FRONTMATTER_DELIMITER = "---"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """分离语料文件的可选 frontmatter 与正文。

    资料准备在链外完成（RAG 策略第 1.1 节），加工件因此可以自带出处元数据。
    这些字段是条目字段的来源（`RQ-KB-02` 要求每条必须有来源与适用范围），
    必须被解析出来——不能当正文嵌入（YAML 会污染检索内容），也不能丢弃
    （那会让许可与出处脱离语料）。

    支持的最小形态是「`---` 起、键值对、`---` 止」；键值都是字符串，不支持
    嵌套结构——语料的元数据不需要它，而完整 YAML 解析器会为一个薄需求引入依赖。

    Returns:
        `(元数据字典, 正文)`；没有 frontmatter 时返回 `({}, 原文)`。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return {}, text

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIMITER:
            end = index
            break
    if end is None:
        # 只有起始分隔符：不当作 frontmatter，
        # 按普通正文处理（宁可当正文也不错位截断）。
        return {}, text

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            continue
        metadata[key.strip()] = _unquote(value.strip())

    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return metadata, body


def _unquote(value: str) -> str:
    """去掉值两端的引号并还原转义（与 `html_extract._yaml_value` 对称）。

    为什么必须对称（2026-09-29 实测缺陷）：写侧把含引号的值转义成 `\\"`，
    而读侧若只 `strip('"')`，读回的值会带一个多余的反斜杠——语料里的
    出处或标题被静默改写。写法与读法必须成对。
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            # 只还原写侧产生的转义（反斜杠与双引号），不解释任意 YAML 转义。
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


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
        # 章节标题在节点粒度取值：超长 section 会被切成多块，只有首块带标题行，
        # 因此必须在切分前取好并传给每一块（否则后续块的 locator 会丢章节）。
        report = chunk_markdown_section(header_path, node.text, start_index=index)
        chunks.extend(report.chunks)
        index += len(report.chunks)
    return chunks


def build_vector_store(settings: Settings, *, engine: Engine, async_engine: AsyncEngine) -> PGVectorStore:
    """构造指向迁移建出的节点表的向量存储。

    两个引擎必须同时注入（框架要求二者同时给或同时不给），这样它读写的是我们
    自己的引擎与连接池，而不是另建一套。

    Raises:
        IngestionError: 未配置 `DATABASE_URL` 时——没有库可写，明确失败。

    框架耦合因此被限制在两处：`_table_class` 与 `from_params` 的构造参数；
    两者都由 `apps/api/tests/test_library_schema_integration.py` 的集成测试守护。
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


async def embed_texts(settings: Settings, texts: list[str]) -> list[list[float]]:
    """批量嵌入文本（资料与案例摄取共用）。

    与 `_embed_chunks` 分开的原因：案例摄取嵌的是整张卡片的拼接文本，
    没有 `Chunk` 对象（卡片是结构化 JSON，不走 Markdown 分块链）。两处各写一份
    批量嵌入就会漂移出「一处校验长度、一处不校验」这类差异，而漏掉的长度校验
    会让供应商拒绝或静默截断（截断即制造错误的检索依据）。

    条数上界不在此处实现：「单请求建议 ≤128 条」由 `build_embedding` 的
    `embed_batch_size=RECOMMENDED_BATCH_SIZE` 落实——框架在 `aget_text_embedding_batch`
    里按它切片后逐批调用，因此任意长度的入参都只会产生不超过该值的请求。
    本函数负责的是另一件事：返回顺序与入参一一对应（条数不符即报错，见下）。

    Raises:
        EmbeddingConfigurationError: 缺凭据（透传，调用方需区别于普通失败）。
        IngestionError: 供应商报错，或返回条数与请求不符（后者会静默错配向量与文本）。
    """
    for text in texts:
        assert_text_within_limit(text)

    try:
        embedder = build_embedding(settings)
        vectors = await embedder.aget_text_embedding_batch(texts)
    except EmbeddingConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 转译成领域错误并保留原因类型
        raise IngestionError(f"嵌入失败：{type(exc).__name__}") from exc

    if len(vectors) != len(texts):
        raise IngestionError(f"嵌入返回条数不符：期望 {len(texts)}，得到 {len(vectors)}")
    return vectors


# quality-floor: ignore docstring-promise 异常由 embed_texts 抛出并原样传播，本函数只做转发
async def _embed_chunks(settings: Settings, chunks: list[Chunk]) -> list[list[float]]:
    """批量嵌入块文本（资料侧入口，转发到 :func:`embed_texts`）。

    Raises:
        EmbeddingConfigurationError: 缺凭据（透传，调用方需区别于普通失败）。
        IngestionError: 供应商报错，或返回条数与请求不符（后者会静默错配向量与文本）。
    """
    return await embed_texts(settings, [chunk.text for chunk in chunks])


def _node_metadata(item: KnowledgeItem, chunk: Chunk) -> dict[str, str]:
    """节点 metadata：条目投影 + 结构的可过滤/可返回字段（RAG 策略第 2 节）。

    需要在 SQL 层过滤的字段必须同时在 metadata 里，否则过滤会掉到应用层。
    布尔用字符串存——`MetadataFilter` 的类型联合不含 `bool`（实测）。
    """
    return {
        "item_id": str(item.id),
        "library": LIBRARY_KNOWLEDGE,
        "status": item.status,
        "withdrawn": "true" if item.withdrawn else "false",
        "title": item.title,
        "source": item.source,
        "applicable_scope": item.applicable_scope,
        # locator 用补全章节名的路径（chunk.locator），而非框架的父级 header_path——
        # 后者不含当前标题，会让同章所有块的引用指向同一个位置。
        "locator": chunk.locator,
    }


async def _write_nodes(
    session: AsyncSession,
    vector_store: PGVectorStore,
    item: KnowledgeItem,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> None:
    """写入该条目的节点（调用方先删旧节点，见 `ingest_file` 的顺序与撤下闸门）。

    删旧节点不在这里：删除必须对「内容变更重写」与「已撤下条目清残留」两条路径
    都发生，而且要在嵌入之前发生。留在调用方，两条路径共用同一句删除，不留
    「某条分支忘了删」的余地。

    实现期实测得到的关键约束（2026-09-29，决定本模块的事务写法）：

    框架的 `PGVectorStore.add()` 内部自建并提交 session
    （`with self._session() as session, session.begin()`），无法参与我们的外部事务。
    但 `__init__` 接受 `engine=`/`async_engine=`（两者必须同时给）注入我们自己的
    引擎，且 `store._table_class` 暴露框架的表模型。因此本模块不用 `add()`，
    而是用我们自己的 session、经框架的表模型写节点行——这样条目表与节点表
    在同一个事务里落库，撤下时才能「同时改条目状态与删节点」（RAG 策略第 2 节）。
    """
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
    source: str | None = None,
    applicable_scope: str | None = None,
    keywords: str = "",
    aliases: str = "",
) -> IngestionResult:
    """摄取一个 Markdown 文件（调用方负责事务与会话）。

    元数据来源有两条，显式参数优先于文件 frontmatter：

    1. 文件自带的 YAML frontmatter（`source`/`applicable_scope`/`title`/
       `keywords`/`aliases`）——语料加工件的常规形态，出处与正文同文件，
       不会错配；
    2. 调用方传的参数——用于没有 frontmatter 的裸 Markdown。

    两者都缺 `source` 或 `applicable_scope` 时拒绝入库：缺来源的条目不
    进入检索、缺适用范围的输出无法说明局限（`RQ-KB-02`、`RQ-CON-03`），
    这是不变量，不能在入口放行。

    幂等：同 `source_path` + 同 `doc_hash` 的条目已存在则跳过，不重复嵌入。
    变了的文件：删除其旧节点后重新写入（保证「撤下/更新即刻生效」的同一套机制）。

    已撤下条目的重新摄取（与案例摄取同一处置）：

    - 内容哈希再变也不重建节点：先清掉该条目名下的任何残留节点即返回，不做嵌入。
      哈希未变的重复摄取（幂等跳过）对已撤下条目做同一次清理——清理不依赖哈希变化，
      因为「同一份内容再交付一次」正是最常见的重交付形态。
      `withdrawal.py` 用「条目状态 + 删节点」在同一事务里表达撤下，节点表是条目表
      的投影（RAG 策略第 2 节）——为已撤下条目写回节点，等于让撤下内容的正文重新
      落回检索存储，并把「取不到已撤下正文」重新押在每条取数路径都记得过滤
      `withdrawn` 上；同时还会为永远不会被检索的内容付一次嵌入往返。
    - 条目行仍随最新文件更新（含 `doc_hash`），因此重复摄取同一份文件照常按幂等
      跳过；但写入计数为 0（本次确实没有写入节点），`headers` 为空。
    - 一期没有「重新摄取即恢复」的语义：恢复必须是运维的显式动作，不能被文件的一次
      重新交付悄悄完成（若将来要恢复，需要单独设计并写清语义）。

    设计依据（RAG 策略第 7 节）：

    - 入口是 CLI（`python -m campfire.cli ingest <路径>`），摄取不暴露成服务端点。
    - 一份文件一个事务：导入失败要么整份成功、要么明确失败并留下可见记录，
      不留下「一半进去了」的静默状态。
    - 幂等与增量：按 doc_hash 判断（未变跳过、变了重新 upsert），避免重复嵌入。
    - 换嵌入模型必须整库重建：维度固定 2560，混入不同维度会让检索静默失准。

    Raises:
        IngestionError: 读文件、缺必填元数据、嵌入或写库任一步失败——由调用方回滚整个事务。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IngestionError(f"读取文件失败：{type(exc).__name__}") from exc

    # frontmatter 是元数据来源，不参与分块——它进正文会污染检索内容。
    frontmatter, body = parse_frontmatter(raw)

    resolved_source = source or frontmatter.get("source", "")
    resolved_scope = applicable_scope or frontmatter.get("applicable_scope", "")
    if not resolved_source:
        raise IngestionError("缺少来源（source）：可用文件 frontmatter 或 --source 提供")
    if not resolved_scope:
        raise IngestionError("缺少适用范围（applicable_scope）：可用文件 frontmatter 或 --scope 提供")

    doc_hash = compute_doc_hash(raw)
    source_path = str(path)

    existing = (
        await session.execute(select(KnowledgeItem).where(KnowledgeItem.source_path == source_path))
    ).scalar_one_or_none()

    if existing is not None and existing.doc_hash == doc_hash:
        if existing.withdrawn:
            # 已撤下条目的残留清理不因哈希未变而跳过：节点不存在是撤下在向量路上唯一
            # 生效的机制（`withdrawal.py` 同事务删节点），而「上游重新交付同一份内容」
            # 是最常见的重交付形态。在此直接返回会把历史脏数据或旁路写入的残留节点
            # 一直留在库里，等某条取数路径读到；清理本身仍在跳过语义内——不嵌入、不写节点。
            await session.execute(delete(RetrievedNode).where(RetrievedNode.node_id.like(f"{existing.id}:%")))
        return IngestionResult(source_path=source_path, item_id=str(existing.id), skipped=True)

    chunks = split_markdown(body)
    if not chunks:
        raise IngestionError("文件未产生任何块（空文件或不含可检索内容）")

    # 只嵌入可嵌入的块；不可分单元进人工处理队列，不截断。
    embeddable = [c for c in chunks if not c.needs_manual_review]
    manual = [c for c in chunks if c.needs_manual_review]

    item = existing if existing is not None else KnowledgeItem(source_path=source_path)
    item.title = title or frontmatter.get("title") or path.stem
    item.source = resolved_source
    item.applicable_scope = resolved_scope
    item.keywords = keywords or frontmatter.get("keywords", "")
    item.aliases = aliases or frontmatter.get("aliases", "")
    item.doc_hash = doc_hash
    if existing is None:
        session.add(item)
    await session.flush()  # 取到 item.id

    # 先删该条目的旧节点再写新节点：更新与撤下走同一套机制，且与条目表状态变更同事务
    # （RAG 策略第 2 节：撤下要能同时改状态与删节点）。
    # 这一步对已撤下条目同样执行：撤下的承诺是「该条目没有检索节点」，重跑顺手清掉
    # 任何残留（历史脏数据或旁路写入），而不是把它们留在库里等某条取数路径读到。
    await session.execute(delete(RetrievedNode).where(RetrievedNode.node_id.like(f"{item.id}:%")))

    if item.withdrawn:
        # 已撤下的条目不重建节点：撤下的承诺是「该条目没有检索节点」，内容变了就写回
        # 节点会推翻它，并把已撤下的正文重新放进检索存储（取数是否读得到就只剩
        # 「每条路径都记得过滤 withdrawn」这一层）。一次嵌入调用都不做——为不会被
        # 检索的内容付供应商往返是纯浪费。计数保持缺省 0：本次确实没有写入任何节点。
        await session.flush()
        return IngestionResult(source_path=source_path, item_id=str(item.id))

    vectors = await _embed_chunks(settings, embeddable)

    await _write_nodes(session, vector_store, item, embeddable, vectors)

    return IngestionResult(
        source_path=source_path,
        item_id=str(item.id),
        chunks_written=len(embeddable),
        needs_manual_review=len(manual),
        headers=[c.header_path for c in embeddable],
    )
