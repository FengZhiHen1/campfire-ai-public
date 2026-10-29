"""知识快照：许可裁定表 + 库内**节点级**一致性核对 + 评测库隔离守卫。

读 `knowledge/snapshot.json` 与磁盘文件 hash，读评测库里实际的条目与节点（正文、节点标识、
metadata、向量），做成可 hash 的快照。**不改库、不摄取**（摄取走 `python -m campfire.cli ingest`）。

三条硬约束：① 评测知识必须落在独立库（`require_isolated_database` 的库名前缀守卫）；
② 只用语许可较清晰的子集；③ B 与 C 用**同一快照**，manifest 记来源与快照 hash。

`nodes_sha256` 覆盖节点正文/标识/metadata/向量，`doc_hash` 记录条目与源文件版本的绑定，
嵌入身份单独记；三者都进 `to_dict()` / `sha256`，`.sha256` 又进 manifest 运行身份，
因此**续跑时内容漂移会被 `manifest.identity_drift` 点名拒绝**。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

#: 包目录（`evaluation/carebench`）。
#: 嵌入维度（真源在产品 `core/config.EMBEDDING_DIM`）：模型与维度绑死，换模型要整库重建。
from campfire.core.config import EMBEDDING_DIM  # noqa: E402 —— 单一真源，不在评测侧另立常量

from .hashing import canonical_json, sha256_file, sha256_text, sha256_value

PACKAGE_ROOT = Path(__file__).resolve().parent

#: 仓库根（`evaluation/carebench` 往上两级）。
REPO_ROOT = PACKAGE_ROOT.parents[1]

#: 评测库名允许的前缀。任何运行都必须在这样的库上跑（见 `require_isolated_database`）。
DEFAULT_DB_PREFIX = "campfire_carebench"

#: 快照 hash 的格式版本。节点级摘要、嵌入身份与条目 `doc_hash` 进 hash 后格式已变，
#: 因此与「任何更早算出的整体快照 hash」不可比（旧环境只留了逐条目 `nodes_sha256`，
#: 没有整体 hash，见 `docs/development/checkpoints/`）。改 `to_dict()` 形状必须递增它。
SNAPSHOT_FORMAT_VERSION = "2"

#: 措辞：库内出现了不在许可清单里的条目时给出的结论。
UNLICENSED_NOTE = "评测库含有许可清单之外的条目：必须先撤下或换到干净库，否则 B/C 的知识来源无法声明"


class KnowledgeSnapshotError(RuntimeError):
    """快照不可用：文件 hash 不符、清单结构不合法，或库内出现未许可条目。"""


@dataclass(frozen=True)
class SnapshotFile:
    """一份被允许进评测库的语料。"""

    path: str
    sha256: str
    license: str
    source_kind: str

    @property
    def basename(self) -> str:
        """文件名（库内 `source_path` 只按 basename 核对，见模块说明）。"""
        return Path(self.path).name


@dataclass(frozen=True)
class EmbeddingIdentity:
    """本次运行声明的嵌入身份（模型名 / 维度 / 端点结构），**不含凭据**。

    证据边界：只证明「这次检索用的嵌入器是哪一套」，**不证明**库内既有节点当初由它算出。
    """

    model: str
    dimension: int
    endpoint: str = ""

    @property
    def configured(self) -> bool:
        """身份是否完整到可以绑定（模型名与维度都给了）。"""
        return bool(self.model.strip()) and int(self.dimension) > 0

    def canonical(self) -> dict[str, Any]:
        """规范字典：只含三个可比较字段。"""
        return {"model": self.model, "dimension": int(self.dimension), "endpoint": self.endpoint}

    @property
    def sha256(self) -> str:
        return sha256_value(self.canonical())

    @classmethod
    def from_settings(cls, settings: Any) -> EmbeddingIdentity:
        """从应用配置取身份（与真实嵌入调用同一来源，不另立第二份配置）。

        维度取 `EMBEDDING_DIM` 而不是配置项：它与模型绑定，可配置的维度就是混库入口。
        """
        return cls(
            model=str(getattr(settings, "embedding_model_name", "") or ""),
            dimension=int(EMBEDDING_DIM),
            endpoint=_endpoint_identity(str(getattr(settings, "resolved_embedding_base_url", "") or "")),
        )


def current_embedding_identity() -> EmbeddingIdentity:
    """当前进程配置的嵌入身份（`read_database_state` 的缺省值）。"""
    from campfire.core.config import get_settings

    return EmbeddingIdentity.from_settings(get_settings())


def _endpoint_identity(url: str) -> str:
    """端点身份：`scheme://host[:port][/path]`（剔凭据、query 与末尾斜杠；取不到主机时为空）。

    保留 scheme：http↔https 是端点身份的实质变化，抹掉它会让两类端点算作同一身份。
    """
    parsed = urlparse((url or "").strip())
    if not parsed.hostname:
        return ""
    host = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
    origin = f"{parsed.scheme}://{host}" if parsed.scheme else host
    return f"{origin}{(parsed.path or '').rstrip('/')}"


@dataclass(frozen=True)
class NodeRecord:
    """库内一个真实检索节点，按读出时的原样保存（不做业务判断）。

    `embedding` 保留驱动给的原样值；规范化只发生在 :func:`canonical_vector` 一处。
    """

    node_id: str
    item_id: str | None
    text: str
    metadata: dict[str, Any]
    embedding: object = None


def canonical_vector(value: object) -> list[float]:
    """把**数据库文本形**的向量规范成 `list[float]`。

    规范口径为 `embedding::text`：固定解析该文本形后参与规范 JSON 哈希，不与其他读出表示
    混用（同一向量若以内存 float32 拓宽来的 float64 传入，会得到另一个摘要）。

    `None` / 空列表返回 `[]`（由调用方记为违规），不在这里抛错。
    """
    if value is None:
        return []
    if isinstance(value, str):
        body = value.strip()
        if body.startswith("[") and body.endswith("]"):
            body = body[1:-1]
        tokens = [token for token in body.split(",") if token.strip()]
        try:
            return [float(token) for token in tokens]
        except ValueError as exc:
            raise KnowledgeSnapshotError(f"向量不是合法数字序列：{value[:48]!r}") from exc
    if isinstance(value, (list, tuple)):
        return [_vector_element(item) for item in value]
    try:
        return [_vector_element(item) for item in value]  # type: ignore[union-attr]  # numpy 等序列
    except TypeError as exc:
        raise KnowledgeSnapshotError(f"不支持的向量类型：{type(value).__name__}") from exc


def _vector_element(value: object) -> float:
    """单个向量元素转 float。"""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise KnowledgeSnapshotError(f"向量元素不是数字：{value!r}") from exc


def node_content_digest(nodes: Sequence[NodeRecord]) -> str:
    """一组节点的内容摘要：正文 + 节点标识 + metadata + 向量（按 `node_id` 升序）。

    规范形（唯一实现）：`[{node_id, text, metadata, embedding}, ...]` 的 `canonical_json`
    的 SHA-256。排序让返回顺序不影响 hash；规范 JSON 避免拼接字符串造成跨字段撞车。
    与旧检查点 `nodes_sha256` 同算法（已只读复算旧库 6 条对上）；整体 hash 是格式 2。
    """
    payload = [
        {
            "node_id": node.node_id,
            "text": node.text,
            "metadata": node.metadata,
            "embedding": canonical_vector(node.embedding),
        }
        for node in sorted(nodes, key=lambda node: node.node_id)
    ]
    return sha256_text(canonical_json(payload))


@dataclass(frozen=True)
class KnowledgeItemRow:
    """库内一个知识条目（只取与评测可复现性相关的列）。"""

    item_id: str
    title: str
    source_path: str | None
    withdrawn: bool
    nodes: int
    #: 出处（`campfire_knowledge_item.source`）：缺来源的条目不进检索。
    source: str = ""
    #: 摄取侧对**解码后文本**做 SHA-256（`ingestion.compute_doc_hash`）得到的内容 hash；
    #: 与 `SnapshotFile.sha256`（清单对**磁盘文件字节**的 hash）是两套口径，不可互换。
    #: 快照只记录并进 hash，不与源文件重算比对（证据边界见 `build_snapshot`）。
    doc_hash: str | None = None
    #: 该条目全部节点的内容摘要（见 :func:`node_content_digest`）。
    nodes_sha256: str = ""

    def canonical(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            # 只留基名：绝对路径会在换机器后变化，却与「用的是哪些语料」无关。
            "source_file": Path(self.source_path).name if self.source_path else None,
            "source": self.source,
            "withdrawn": self.withdrawn,
            "nodes": self.nodes,
            "doc_hash": self.doc_hash,
            "nodes_sha256": self.nodes_sha256,
        }


@dataclass(frozen=True)
class KnowledgeSnapshot:
    """一次评测所依据的知识快照（含库内实际条目、节点摘要与隔离核对结论）。"""

    snapshot_version: str
    corpus_root: str
    files: tuple[SnapshotFile, ...]
    blocked: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    excluded_corpora: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    items: tuple[KnowledgeItemRow, ...] = field(default_factory=tuple)
    case_item_count: int = 0
    database: str = ""
    violations: tuple[str, ...] = field(default_factory=tuple)
    #: 本次运行声明的嵌入身份；`None` 表示未知（**违规**，见 `build_snapshot`）。
    embedding: EmbeddingIdentity | None = None
    #: 全部节点的内容摘要（正文 + 节点标识 + metadata + 向量）。
    nodes_sha256: str = ""
    #: 节点总数（与 `sum(item.nodes)` 同源，单独存一份让「节点被整体删掉」也进 hash）。
    node_count: int = 0

    @property
    def ok(self) -> bool:
        """快照是否可用于正式运行（许可齐、条目与节点可核对、无案例条目、身份已知）。"""
        return not self.violations

    @property
    def sha256(self) -> str:
        """快照 hash：格式版本 + 语料清单 + 条目与节点摘要 + 嵌入身份 + 库名。

        含库名是有意的：来自不同库的同形条目不得互相冒充。
        """
        return sha256_value(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """规范字典（进 manifest 的 `knowledge_snapshot` 段）。

        排序是规范的一部分（条目按 `item_id`、语料按 `path`）；`nodes` 只放摘要，
        它与逐节点展开对「内容是否漂移」的判别力相同。
        """
        return {
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "snapshot_version": self.snapshot_version,
            "corpus_root": self.corpus_root,
            "database": self.database,
            "embedding": (
                None if self.embedding is None else {**self.embedding.canonical(), "sha256": self.embedding.sha256}
            ),
            "files": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "license": item.license,
                    "source_kind": item.source_kind,
                }
                for item in sorted(self.files, key=lambda entry: entry.path)
            ],
            "blocked": list(self.blocked),
            "excluded_corpora": list(self.excluded_corpora),
            "items": [item.canonical() for item in sorted(self.items, key=lambda item: item.item_id)],
            "nodes": {"count": self.node_count, "sha256": self.nodes_sha256},
            "case_item_count": self.case_item_count,
            "violations": sorted(self.violations),
        }


def load_snapshot_manifest(path: Path | None = None) -> tuple[KnowledgeSnapshot, list[Path]]:
    """读许可裁定表并核对磁盘文件 hash。

    Args:
        path: 清单路径；缺省用包内的 `knowledge/snapshot.json`。

    Returns:
        （不含库内条目的快照, 待核对的语料文件路径列表）。

    Raises:
        KnowledgeSnapshotError: 清单结构不合法、文件缺失，或 hash 与清单不符。
    """
    manifest_path = path or PACKAGE_ROOT / "knowledge" / "snapshot.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KnowledgeSnapshotError(f"知识快照清单不存在：{manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise KnowledgeSnapshotError(f"知识快照清单不是合法 JSON：{manifest_path}（{exc.msg}）") from exc

    corpus_root = str(raw.get("corpus_root") or "data/knowledge")
    files: list[SnapshotFile] = []
    paths: list[Path] = []
    problems: list[str] = []
    for entry in raw.get("included") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            raise KnowledgeSnapshotError("快照清单 included 项缺少 path")
        relative = Path(corpus_root) / str(entry["path"])
        absolute = REPO_ROOT / relative
        if not absolute.exists():
            problems.append(f"语料文件缺失：{relative}")
            continue
        actual = sha256_file(absolute)
        declared = str(entry.get("sha256") or "")
        if declared and declared != actual:
            problems.append(f"语料文件 hash 与清单不符：{relative}（清单 {declared[:12]}… 实际 {actual[:12]}…）")
            continue
        files.append(
            SnapshotFile(
                path=str(entry["path"]),
                sha256=actual,
                license=str(entry.get("license") or ""),
                source_kind=str(entry.get("source_kind") or ""),
            )
        )
        paths.append(absolute)

    if problems:
        raise KnowledgeSnapshotError("；".join(problems))
    if not files:
        raise KnowledgeSnapshotError("快照清单没有任何 included 语料：评测库无法建立可声明的知识来源")

    snapshot = KnowledgeSnapshot(
        snapshot_version=str(raw.get("snapshot_version") or ""),
        corpus_root=corpus_root,
        files=tuple(files),
        blocked=tuple(raw.get("blocked") or ()),
        excluded_corpora=tuple(raw.get("excluded_corpora") or ()),
    )
    return snapshot, paths


def build_snapshot(
    manifest: KnowledgeSnapshot,
    *,
    database: str,
    items: Sequence[KnowledgeItemRow],
    nodes: Sequence[NodeRecord],
    case_item_count: int = 0,
    embedding: EmbeddingIdentity | None = None,
) -> KnowledgeSnapshot:
    """把读出的条目与节点做成带摘要与违规清单的快照（**纯函数**，不触库，便于测负例）。

    核对项（缺一条就不允许正式运行）：① 条目基名在清单内，且**清单里每份语料都在库内**；
    ② 无案例条目、无已撤下条目、条目有 `doc_hash`、条目至少一个节点；③ 节点有非空
    `item_id`、属于库内条目、标识非空且不重复、有向量且维度与身份一致、有限值且非零向量。

    证据边界：`doc_hash`/`source` 只被记录并进 hash，不与源文件重算比对——能发现两次运行
    之间的来源漂移（→ 续跑拒绝），但**不证明**库内 `doc_hash` 就是许可清单里那份文件；
    那一步要在读 `paths` 的阶段用 `ingestion.compute_doc_hash` 与库内值逐条比对（未接入）。
    """
    allowed = {entry.basename for entry in manifest.files}
    by_item: dict[str, list[NodeRecord]] = {}
    violations: list[str] = []
    unowned_nodes = 0
    unknown_owner_ids: set[str] = set()

    known_item_ids = {item.item_id for item in items}
    expected_dimension = embedding.dimension if embedding is not None and embedding.configured else EMBEDDING_DIM
    # 向量先规范化一次再分组：解析失败记成违规而不是让整份快照抛栈回溯（一条坏行不该
    # 把 preflight 变成异常，但它必须被看见）。
    normalized: list[NodeRecord] = []
    seen_node_ids: set[str] = set()
    duplicate_node_ids: set[str] = set()
    for node in nodes:
        try:
            vector = canonical_vector(node.embedding)
        except KnowledgeSnapshotError as exc:
            violations.append(f"节点 {node.node_id} 的向量无法解析：{exc}")
            vector = []
        normalized_node = replace(node, embedding=vector)
        normalized.append(normalized_node)
        node_id = node.node_id.strip()
        if not node_id:
            violations.append("存在没有 node_id 的节点：节点标识是引用回指与去重的唯一依据")
        elif node_id in seen_node_ids:
            duplicate_node_ids.add(node_id)
        else:
            seen_node_ids.add(node_id)
        if not node.item_id:
            unowned_nodes += 1
            continue
        by_item.setdefault(node.item_id, []).append(normalized_node)
        if node.item_id not in known_item_ids:
            unknown_owner_ids.add(node.item_id)
        if not vector:
            violations.append(f"节点 {node.node_id} 没有向量：向量路永远召回不到它")
            continue
        if not all(math.isfinite(value) for value in vector):
            violations.append(f"节点 {node.node_id} 的向量含非有限值（NaN/Inf），不能作为检索依据")
        if len(vector) != int(expected_dimension):
            violations.append(
                f"节点 {node.node_id} 的向量维度是 {len(vector)}，期望 {int(expected_dimension)}"
                "（维度绑死，混维即静默失准）"
            )
        if not any(value != 0.0 for value in vector):
            violations.append(f"节点 {node.node_id} 的向量是零向量：余弦相似度对小恒等，不是可用依据")
    if duplicate_node_ids:
        examples = "、".join(sorted(duplicate_node_ids)[:3])
        violations.append(f"节点标识重复：{examples}（共 {len(duplicate_node_ids)} 个），节点无法唯一定位")

    rows: list[KnowledgeItemRow] = []
    covered: set[str] = set()
    for item in items:
        name = Path(item.source_path).name if item.source_path else None
        owned = by_item.get(item.item_id, [])
        rows.append(replace(item, nodes=len(owned), nodes_sha256=node_content_digest(owned)))
        if name is None:
            violations.append(f"条目 {item.item_id} 没有 source_path，无法声明来源")
        elif name not in allowed:
            violations.append(f"条目 {item.source_path} 不在许可清单内（{UNLICENSED_NOTE}）")
        else:
            covered.add(name)
        if not item.doc_hash:
            violations.append(f"条目 {item.source_path or item.item_id} 没有 doc_hash：无法核对它来自哪一版源文件")
        if item.withdrawn:
            violations.append(f"条目 {item.source_path or item.item_id} 已被撤下，不应出现在评测库")
        if not owned:
            violations.append(f"条目 {item.source_path or item.item_id} 没有检索节点（检索永远命中不到）")

    for entry in manifest.files:
        if entry.basename not in covered:
            violations.append(f"许可清单内的语料不在库内：{entry.path}（实际知识少于声明的知识）")

    if unowned_nodes:
        violations.append(f"库内有 {unowned_nodes} 个节点没有 item_id（游离节点不在任何过滤路径上）")
    if unknown_owner_ids:
        examples = "、".join(sorted(unknown_owner_ids)[:3])
        violations.append(
            f"库内有节点属于未知条目（可能是案例或已删条目）：{examples}（共 {len(unknown_owner_ids)} 个）"
        )
    if case_item_count:
        violations.append(
            f"评测库含 {case_item_count} 条案例条目（真实访谈与虚构样例都不得进评测库）：{UNLICENSED_NOTE}"
        )

    if embedding is None:
        violations.append("缺嵌入身份（模型名/维度）：无法声明本次运行使用哪套嵌入器")
    elif not embedding.configured:
        violations.append(f"嵌入身份不完整：model={embedding.model!r} dimension={int(embedding.dimension)}")
    elif int(embedding.dimension) != int(EMBEDDING_DIM):
        violations.append(f"嵌入身份维度 {int(embedding.dimension)} 与绑死常量 {EMBEDDING_DIM} 不一致")

    return replace(
        manifest,
        items=tuple(rows),
        case_item_count=case_item_count,
        database=database,
        violations=tuple(sorted(violations)),
        embedding=embedding,
        nodes_sha256=node_content_digest(normalized),
        node_count=len(normalized),
    )


async def read_database_state(
    session: AsyncSession,
    *,
    snapshot: KnowledgeSnapshot,
    database: str,
    embedding: EmbeddingIdentity | None = None,
) -> KnowledgeSnapshot:
    """读库内条目与**整表**节点后交给 :func:`build_snapshot`（判据全在那里）。

    节点取整表：只取条目名下的会让游离节点与案例节点从快照里消失。向量固定按
    `embedding::text` 读（口径见 :func:`canonical_vector`）。`embedding` 缺省取当前配置
    （与真实嵌入调用同一来源）。
    """
    from campfire.modules.library.models import CaseItem, KnowledgeItem

    rows = (
        await session.execute(
            select(
                KnowledgeItem.id,
                KnowledgeItem.title,
                KnowledgeItem.source_path,
                KnowledgeItem.withdrawn,
                KnowledgeItem.source,
                KnowledgeItem.doc_hash,
            ).order_by(KnowledgeItem.created_at)
        )
    ).all()

    node_rows = (
        await session.execute(
            text(
                """
                SELECT node_id,
                       metadata_->>'item_id' AS item_id,
                       text,
                       metadata_ AS metadata,
                       embedding::text AS embedding
                FROM data_campfire_node
                ORDER BY node_id
                """
            )
        )
    ).all()

    case_count = int((await session.execute(select(func.count()).select_from(CaseItem))).scalar_one())

    items = [
        KnowledgeItemRow(
            item_id=str(item_id),
            title=str(title),
            source_path=source_path,
            withdrawn=bool(withdrawn),
            nodes=0,
            source=str(source or ""),
            doc_hash=doc_hash,
        )
        for item_id, title, source_path, withdrawn, source, doc_hash in rows
    ]
    nodes = [
        NodeRecord(
            node_id=str(row.node_id or ""),
            item_id=str(row.item_id) if row.item_id else None,
            text=str(row.text or ""),
            metadata=dict(row.metadata or {}),
            embedding=row.embedding,
        )
        for row in node_rows
    ]

    return build_snapshot(
        snapshot,
        database=database,
        items=items,
        nodes=nodes,
        case_item_count=case_count,
        embedding=embedding or current_embedding_identity(),
    )


def database_name(url: str | None) -> str:
    """从连接串取库名（空串表示取不到）。不返回用户名/口令/主机。"""
    if not url:
        return ""
    parsed = urlparse(url)
    return (parsed.path or "").lstrip("/")


def require_isolated_database(url: str | None, *, prefix: str = DEFAULT_DB_PREFIX) -> str:
    """核对当前数据库是评测库，返回库名。

    Raises:
        KnowledgeSnapshotError: 未配置数据库，或库名不以评测前缀开头。

    为什么用「库名前缀」这条机械判据：评测与开发用的是同一个 PostgreSQL 实例，
    两者只差一个库名。人在命令行里手滑一次就会把合成账号、会话与引用写进开发库；
    而输出格式与运行成功与否完全看不出这件事。因此这里宁可直接拒绝，也不「提醒一下就继续」。
    """
    name = database_name(url)
    if not name:
        raise KnowledgeSnapshotError("未配置 DATABASE_URL：评测需要独立数据库（campfire_carebench_*）")
    if not name.startswith(prefix):
        raise KnowledgeSnapshotError(
            f"当前数据库 {name!r} 不是评测库（要求库名以 {prefix} 开头）："
            "评测写入合成账号、会话与引用，不得落在开发/生产库上"
        )
    return name


def endpoint_host(url: str | None) -> str:
    """取端点主机（含端口），用于 manifest 与「嵌入是否误回落对话端点」的检查。"""
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.hostname:
        return ""
    return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname


def is_loopback(host: str) -> bool:
    """主机位是否是本机回环（本机网关的判据）。"""
    name = host.split(":")[0].strip("[]").lower()
    return name in {"127.0.0.1", "localhost", "::1"}


__all__ = [
    "EMBEDDING_DIM",
    "DEFAULT_DB_PREFIX",
    "EmbeddingIdentity",
    "KnowledgeItemRow",
    "KnowledgeSnapshot",
    "KnowledgeSnapshotError",
    "NodeRecord",
    "SNAPSHOT_FORMAT_VERSION",
    "PACKAGE_ROOT",
    "REPO_ROOT",
    "SnapshotFile",
    "UNLICENSED_NOTE",
    "build_snapshot",
    "canonical_vector",
    "current_embedding_identity",
    "database_name",
    "endpoint_host",
    "is_loopback",
    "load_snapshot_manifest",
    "node_content_digest",
    "read_database_state",
    "require_isolated_database",
]
