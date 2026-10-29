"""知识快照：许可裁定表 + 库内一致性核对 + 评测库隔离守卫。

职责：读 `knowledge/snapshot.json`（哪些语料允许进评测库、许可依据、文件 hash），
核对磁盘文件 hash，读取评测库里实际的条目清单，并把结果做成一个可 hash 的快照对象。

边界：**不改库、不摄取**——摄取仍走产品自己的 `python -m campfire.cli ingest`；
本模块只回答「这个库里现在有什么、是不是都在许可清单内」。

三条来自主 agent 的硬约束（2026-10-29）落在这里：

1. 评测知识必须落在**独立数据库**，不能继承开发库里的 internal 真实访谈输出；
2. 只用**许可较清晰**的子集（NHC / Hume CC BY / CDC）；
3. B 与 C 必须用**同一快照**，且 manifest 记下来源与快照 hash。

第 2、3 条由 `snapshot.json` + 运行时核对实现；第 1 条由
:func:`require_isolated_database` 的库名前缀守卫实现——它拒绝在名字不像评测库的库上运行，
因为「拿开发库跑一遍」与「拿评测库跑一遍」在输出格式上完全看不出区别。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

#: 包目录（`evaluation/carebench`）。
#: 嵌入维度（真源在产品 `core/config.EMBEDDING_DIM`）：模型与维度绑死，换模型要整库重建。
from campfire.core.config import EMBEDDING_DIM  # noqa: E402 —— 单一真源，不在评测侧另立常量

from .hashing import sha256_file, sha256_value

PACKAGE_ROOT = Path(__file__).resolve().parent

#: 仓库根（`evaluation/carebench` 往上两级）。
REPO_ROOT = PACKAGE_ROOT.parents[1]

#: 评测库名允许的前缀。任何运行都必须在这样的库上跑（见 `require_isolated_database`）。
DEFAULT_DB_PREFIX = "campfire_carebench"

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
class KnowledgeItemRow:
    """库内一个知识条目（只取与评测可复现性相关的列）。"""

    item_id: str
    title: str
    source_path: str | None
    withdrawn: bool
    nodes: int

    def canonical(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            # 只留基名：绝对路径会在换机器后变化，却与「用的是哪些语料」无关。
            "source_file": Path(self.source_path).name if self.source_path else None,
            "withdrawn": self.withdrawn,
            "nodes": self.nodes,
        }


@dataclass(frozen=True)
class KnowledgeSnapshot:
    """一次评测所依据的知识快照（含库内实际条目与隔离核对结论）。"""

    snapshot_version: str
    corpus_root: str
    files: tuple[SnapshotFile, ...]
    blocked: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    excluded_corpora: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    items: tuple[KnowledgeItemRow, ...] = field(default_factory=tuple)
    case_item_count: int = 0
    database: str = ""
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """快照是否可用于正式运行（文件齐、库内条目全部在许可清单内、无案例条目）。"""
        return not self.violations

    @property
    def sha256(self) -> str:
        """快照 hash：语料清单 + 库内条目（含节点数）+ 库名。

        含库名是有意的：两份「看起来一样」的条目来自不同库时，快照应当不同——
        否则 manifest 声称的快照与真正跑的那一份可能不是同一份。
        """
        return sha256_value(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """规范字典（进 manifest）。"""
        return {
            "snapshot_version": self.snapshot_version,
            "corpus_root": self.corpus_root,
            "database": self.database,
            "files": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "license": item.license,
                    "source_kind": item.source_kind,
                }
                for item in self.files
            ],
            "blocked": list(self.blocked),
            "excluded_corpora": list(self.excluded_corpora),
            "items": [item.canonical() for item in self.items],
            "case_item_count": self.case_item_count,
            "violations": list(self.violations),
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


async def read_database_state(
    session: AsyncSession,
    *,
    snapshot: KnowledgeSnapshot,
    database: str,
) -> KnowledgeSnapshot:
    """读库内条目并与许可清单核对，返回带 `items` / `violations` 的快照。

    核对四件事（缺一条就不允许正式运行）：

    1. 每个条目的 `source_path` 基名在 `included` 清单里；
    2. 没有 `status=internal` 的案例条目（真实访谈一律不得进评测库）；
    3. 没有已撤下条目（撤下的条目检索不到，留着只会让快照声明与实际能力不符）；
    4. 每个条目至少有一个检索节点（有条目没节点 = 检索永远命中不到，属静默失效）。
    """
    from campfire.modules.library.models import CaseItem, KnowledgeItem

    rows = (
        await session.execute(
            select(KnowledgeItem.id, KnowledgeItem.title, KnowledgeItem.source_path, KnowledgeItem.withdrawn).order_by(
                KnowledgeItem.created_at
            )
        )
    ).all()

    node_counts = {
        str(item_id): int(count)
        for item_id, count in (
            await session.execute(
                text(
                    "SELECT metadata_->>'item_id' AS item_id, count(*) FROM data_campfire_node "
                    "WHERE metadata_->>'item_id' IS NOT NULL GROUP BY 1"
                )
            )
        ).all()
    }

    case_count = int((await session.execute(select(func.count()).select_from(CaseItem))).scalar_one())

    allowed = {item.basename for item in snapshot.files}
    items: list[KnowledgeItemRow] = []
    violations: list[str] = []
    for item_id, title, source_path, withdrawn in rows:
        name = Path(source_path).name if source_path else None
        nodes = node_counts.get(str(item_id), 0)
        items.append(
            KnowledgeItemRow(
                item_id=str(item_id),
                title=str(title),
                source_path=source_path,
                withdrawn=bool(withdrawn),
                nodes=nodes,
            )
        )
        if name is None:
            violations.append(f"条目 {item_id} 没有 source_path，无法声明来源")
        elif name not in allowed:
            violations.append(f"条目 {source_path} 不在许可清单内（{UNLICENSED_NOTE}）")
        if withdrawn:
            violations.append(f"条目 {source_path} 已被撤下，不应出现在评测库")
        if nodes <= 0:
            violations.append(f"条目 {source_path} 没有检索节点（检索永远命中不到）")

    if case_count:
        violations.append(f"评测库含 {case_count} 条案例条目（含 internal 真实访谈时不得运行）：{UNLICENSED_NOTE}")

    return KnowledgeSnapshot(
        snapshot_version=snapshot.snapshot_version,
        corpus_root=snapshot.corpus_root,
        files=snapshot.files,
        blocked=snapshot.blocked,
        excluded_corpora=snapshot.excluded_corpora,
        items=tuple(items),
        case_item_count=case_count,
        database=database,
        violations=tuple(violations),
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
    "KnowledgeItemRow",
    "KnowledgeSnapshot",
    "KnowledgeSnapshotError",
    "PACKAGE_ROOT",
    "REPO_ROOT",
    "SnapshotFile",
    "UNLICENSED_NOTE",
    "database_name",
    "endpoint_host",
    "is_loopback",
    "load_snapshot_manifest",
    "read_database_state",
    "require_isolated_database",
]
