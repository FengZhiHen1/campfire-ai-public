"""知识快照的节点级内容锁定（`EVAL-01`）；全部确定性，不连库、不联网、不调模型。

守三件事：① 快照 hash 覆盖真实节点的正文、节点标识、metadata、向量，以及条目的 `doc_hash`
与本次运行的嵌入身份；② **节点数相同而内容漂移**必须改变 hash，从而让
`manifest.identity_drift` 在续跑时拒绝；③ 规范排序与向量序列化稳定。

不断言「117 个节点」：那是旧环境读数，只存在于检查点文件里，写进用例会让「换环境」与
「快照坏了」无法区分。这里只断言结构性质，另用一条用例钉住摘要算法与旧检查点一致。
"""

from __future__ import annotations

import json
import struct
from types import SimpleNamespace
from typing import Any

import pytest

from evaluation.carebench.config import RunConfig
from evaluation.carebench.hashing import canonical_json, sha256_text
from evaluation.carebench.knowledge import (
    EMBEDDING_DIM,
    SNAPSHOT_FORMAT_VERSION,
    EmbeddingIdentity,
    KnowledgeItemRow,
    KnowledgeSnapshot,
    KnowledgeSnapshotError,
    NodeRecord,
    SnapshotFile,
    build_snapshot,
    canonical_vector,
    node_content_digest,
    read_database_state,
)
from evaluation.carebench.manifest import identity_drift, identity_fingerprint, runtime_identity

FILE_A = "autism-corpus/a.md"
FILE_B = "autism-md/b.md"
DOC_HASH_A = "a" * 64
DOC_HASH_B = "b" * 64
ITEM_A = "11111111-1111-4111-8111-111111111111"
ITEM_B = "22222222-2222-4222-8222-222222222222"

#: 「调用方没给向量」的哨兵——与「显式给 None（库里是 NULL）」区分。
_MISSING = object()


# ---------------------------------------------------------------------------
# 构造器（不读磁盘、不依赖包的 snapshot.json）
# ---------------------------------------------------------------------------


def _manifest(*paths: str) -> KnowledgeSnapshot:
    return KnowledgeSnapshot(
        snapshot_version="test",
        corpus_root="data/knowledge",
        files=tuple(
            SnapshotFile(path=p, sha256="0" * 64, license="测试许可", source_kind="institutional") for p in paths
        ),
    )


def _item(
    item_id: str = ITEM_A,
    *,
    source_path: str | None = f"data/knowledge/{FILE_A}",
    doc_hash: str | None = DOC_HASH_A,
    source: str = "测试出处",
    title: str = "测试条目",
    withdrawn: bool = False,
) -> KnowledgeItemRow:
    return KnowledgeItemRow(
        item_id=item_id,
        title=title,
        source_path=source_path,
        withdrawn=withdrawn,
        nodes=0,
        source=source,
        doc_hash=doc_hash,
    )


def _vector(seed: float = 0.1) -> list[float]:
    """维度正确的向量（维度不符会另记违规，干扰内容漂移的判据）。"""
    return [seed] + [0.0] * (EMBEDDING_DIM - 1)


def _node(
    index: int,
    *,
    item_id: str = ITEM_A,
    node_id: str | None = None,
    text: str | None = None,
    embedding: object = _MISSING,
    locator: str = "/总则/",
) -> NodeRecord:
    return NodeRecord(
        node_id=f"{item_id}:{index}" if node_id is None else node_id,
        item_id=item_id,
        text=f"第 {index} 段正文" if text is None else text,
        metadata={
            "item_id": item_id,
            "library": "knowledge",
            "status": "published",
            "withdrawn": "false",
            "locator": locator,
        },
        embedding=_vector() if embedding is _MISSING else embedding,
    )


def _identity(model: str = "kinfra-text-embedding-4b", endpoint: str = "gw.example/v1") -> EmbeddingIdentity:
    return EmbeddingIdentity(model=model, dimension=EMBEDDING_DIM, endpoint=endpoint)


def _items_default() -> list[KnowledgeItemRow]:
    return [_item(ITEM_A), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}", doc_hash=DOC_HASH_B)]


def _nodes_default() -> list[NodeRecord]:
    return [_node(0), _node(1), _node(0, item_id=ITEM_B)]


def _build(
    *,
    items: list[KnowledgeItemRow] | None = None,
    nodes: list[NodeRecord] | None = None,
    case_item_count: int = 0,
    embedding: EmbeddingIdentity | None = None,
    paths: tuple[str, ...] = (FILE_A, FILE_B),
) -> KnowledgeSnapshot:
    return build_snapshot(
        _manifest(*paths),
        database="campfire_carebench_test",
        items=_items_default() if items is None else items,
        nodes=_nodes_default() if nodes is None else nodes,
        case_item_count=case_item_count,
        embedding=_identity() if embedding is None else embedding,
    )


# ---------------------------------------------------------------------------
# 规范形：排序与向量序列化
# ---------------------------------------------------------------------------


def test_snapshot_hash_is_independent_of_row_order() -> None:
    """条目与节点的返回顺序不得影响 hash（判别性：去掉任一处 sorted 即失败）。"""
    forward = _build()
    backward = _build(items=[_items_default()[1], _items_default()[0]], nodes=list(reversed(_nodes_default())))

    assert [item.item_id for item in backward.items] == [ITEM_B, ITEM_A], "构造前提：顺序确实反了"
    assert forward.sha256 == _build().sha256
    assert forward.sha256 == backward.sha256
    assert forward.nodes_sha256 == backward.nodes_sha256


def test_canonical_vector_is_defined_only_over_the_database_text_form() -> None:
    """规范口径固定为 `embedding::text`：文本形稳定，float32 拓宽值**不同**。

    pgvector 的 `float4` 文本形是 `0.1`；由 `float32` 拓宽来的 `float64` 是
    `0.10000000149011612`，摘要因此不同——这不是缺陷，而是「口径只有一条」的证据：
    生产路径固定读 `::text`，不得与内存 float32 混用。
    """
    widened = struct.unpack("<f", struct.pack("<f", 0.1))[0]
    assert widened != 0.1

    assert canonical_vector("[0.1,0.2]") == canonical_vector("[0.1, 0.2]") == [0.1, 0.2]
    assert node_content_digest([_node(0, embedding="[0.1]")]) == node_content_digest([_node(0, embedding=[0.1])])
    assert node_content_digest([_node(0, embedding="[0.1]")]) != node_content_digest([_node(0, embedding=[widened])])
    assert canonical_vector(None) == []


@pytest.mark.parametrize(("broken", "reason"), [("[0.1,,x]", "不是合法数字序列"), (object(), "不支持的向量类型")])
def test_unparseable_vectors_are_domain_errors(broken: object, reason: str) -> None:
    with pytest.raises(KnowledgeSnapshotError, match=reason):
        canonical_vector(broken)


def test_node_digest_matches_the_committed_checkpoint_algorithm() -> None:
    """摘要算法 = 旧检查点 `nodes_sha256` 的算法（规范形在用例里独立重写一遍）。"""
    nodes = [_node(1, embedding="[0.25,0.5]"), _node(0, embedding=[0.125, 0.75])]
    expected = [
        {"node_id": f"{ITEM_A}:0", "text": "第 0 段正文", "metadata": nodes[1].metadata, "embedding": [0.125, 0.75]},
        {"node_id": f"{ITEM_A}:1", "text": "第 1 段正文", "metadata": nodes[0].metadata, "embedding": [0.25, 0.5]},
    ]

    assert node_content_digest(nodes) == sha256_text(canonical_json(expected))


# ---------------------------------------------------------------------------
# 节点数相同、内容漂移 → 快照必须变（续跑拒绝的数据面）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda nodes: [_node(0, text="改了正文"), *nodes[1:]], id="text"),
        pytest.param(lambda nodes: [_node(0, embedding=_vector(0.2)), *nodes[1:]], id="vector"),
        pytest.param(lambda nodes: [_node(0, locator="/另一节/"), *nodes[1:]], id="metadata"),
        pytest.param(lambda nodes: [_node(0, node_id=f"{ITEM_A}:9"), *nodes[1:]], id="node_id"),
    ],
)
def test_same_node_count_with_different_node_content_changes_the_snapshot(mutate: Any) -> None:
    baseline = _build()
    drifted = _build(nodes=mutate(_nodes_default()))

    assert sum(item.nodes for item in drifted.items) == 3
    assert sum(item.nodes for item in baseline.items) == 3
    assert drifted.nodes_sha256 != baseline.nodes_sha256
    assert drifted.sha256 != baseline.sha256


@pytest.mark.parametrize(
    "items",
    [
        pytest.param(
            [_item(ITEM_A, doc_hash="c" * 64), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}")], id="doc_hash"
        ),
        pytest.param(
            [_item(ITEM_A, source="另一出处"), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}")], id="source"
        ),
        pytest.param(
            [_item(ITEM_A, title="另一个标题"), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}")], id="title"
        ),
    ],
)
def test_same_node_count_with_different_item_evidence_changes_the_snapshot(
    items: list[KnowledgeItemRow],
) -> None:
    """节点不动、条目的 doc_hash / source / title 变了 → 快照必须变。"""
    baseline = _build()
    drifted = _build(items=items)

    assert [item.nodes for item in drifted.items] == [item.nodes for item in baseline.items]
    assert drifted.nodes_sha256 == baseline.nodes_sha256, "本用例只动条目，不动节点"
    assert drifted.sha256 != baseline.sha256


@pytest.mark.parametrize(
    "embedding",
    [
        pytest.param(_identity(model="another-model"), id="model"),
        pytest.param(_identity(endpoint="x/v1"), id="endpoint"),
    ],
)
def test_embedding_identity_drift_changes_the_snapshot(embedding: EmbeddingIdentity) -> None:
    baseline = _build()
    drifted = _build(embedding=embedding)

    assert drifted.nodes_sha256 == baseline.nodes_sha256
    assert baseline.embedding is not None and drifted.embedding is not None
    assert drifted.embedding.sha256 != baseline.embedding.sha256
    assert drifted.sha256 != baseline.sha256


def test_doc_hash_is_carried_verbatim_not_recomputed() -> None:
    """`doc_hash` 原样进快照：它是摄取侧对解码文本的 SHA-256，不是清单的文件字节 hash。"""
    payload = _build(items=[_item(ITEM_A, doc_hash="0123456789abcdef" * 4)]).to_dict()

    assert payload["items"][0]["doc_hash"] == "0123456789abcdef" * 4
    assert payload["items"][0]["doc_hash"] != payload["files"][0]["sha256"]


def test_resume_identity_names_the_knowledge_drift_when_node_count_is_unchanged() -> None:
    """节点数相同、正文变了 → 运行身份不一致项点名 `knowledge.snapshot_sha256`。

    `runner` 续跑前用 `identity_drift` 逐项比对，不一致即 `ResumeRejected`
    （拒绝分支由 `test_identity.py` 钉住；这里钉住「漂移会被看见」）。
    """
    from campfire.core.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://tester:secret@127.0.0.1:5432/campfire_carebench_test",
        model_name="model-a",
        tokenhub_base_url="http://127.0.0.1:7863/v1",
    )
    nodes = _nodes_default()
    before = runtime_identity(settings, _build(nodes=nodes), RunConfig())
    after = runtime_identity(settings, _build(nodes=[_node(0, text="改了正文"), *nodes[1:]]), RunConfig())

    assert before["knowledge"]["nodes"] == after["knowledge"]["nodes"] == 3
    assert any("knowledge.snapshot_sha256" in diff for diff in identity_drift(before, after))
    assert identity_fingerprint(before) != identity_fingerprint(after)


# ---------------------------------------------------------------------------
# 违规清单：每条判据都要能被触发（不留「永远不会失败」的检查）
# ---------------------------------------------------------------------------


def test_a_clean_library_has_no_violations() -> None:
    snapshot = _build()

    assert snapshot.violations == ()
    assert snapshot.ok is True
    assert [item.nodes for item in sorted(snapshot.items, key=lambda item: item.item_id)] == [2, 1]
    assert snapshot.node_count == 3


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("unlicensed", "不在许可清单内"),
        ("withdrawn", "已被撤下"),
        ("no_doc_hash", "没有 doc_hash"),
        ("no_source_path", "source_path"),
        ("no_nodes", "没有检索节点"),
        ("missing_corpus", "不在库内"),
    ],
)
def test_item_level_problems_are_violations(case: str, expected: str) -> None:
    items, nodes = {
        "unlicensed": (
            [_item(ITEM_A), _item(ITEM_B, source_path="data/knowledge/autism-md/05_WHO_事实清单.md")],
            _nodes_default(),
        ),
        "withdrawn": (
            [_item(ITEM_A, withdrawn=True), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}")],
            _nodes_default(),
        ),
        "no_doc_hash": (
            [_item(ITEM_A, doc_hash=None), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}")],
            _nodes_default(),
        ),
        "no_source_path": (
            [_item(ITEM_A, source_path=None), _item(ITEM_B, source_path=f"data/knowledge/{FILE_B}")],
            _nodes_default(),
        ),
        "no_nodes": (_items_default(), [_node(0)]),
        "missing_corpus": ([_item(ITEM_A)], [_node(0)]),
    }[case]
    snapshot = _build(items=items, nodes=nodes)

    assert any(expected in violation for violation in snapshot.violations), snapshot.violations
    assert snapshot.ok is False


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("no_item_id", "没有 item_id"),
        ("unknown_item", "未知条目"),
        ("empty_id", "没有 node_id"),
        ("duplicate_id", "节点标识重复"),
        ("null_vector", "没有向量"),
        ("empty_vector", "没有向量"),
        ("nan", "非有限值"),
        ("inf", "非有限值"),
        ("zero_vector", "零向量"),
        ("wrong_dimension", "向量维度是 2"),
        ("unparsable", "向量无法解析"),
    ],
)
def test_node_level_problems_are_violations(case: str, expected: str) -> None:
    base = _nodes_default()
    orphan = NodeRecord(node_id="orphan:0", item_id=None, text="游离正文", metadata={}, embedding=_vector())
    nodes = {
        "no_item_id": [*base, orphan],
        "unknown_item": [*base, _node(0, item_id="99999999-9999-4999-8999-999999999999")],
        "empty_id": [_node(0, node_id="  "), *base[1:]],
        "duplicate_id": [_node(0), _node(0), *base[2:]],
        "null_vector": [_node(0, embedding=None), *base[1:]],
        "empty_vector": [_node(0, embedding=[]), *base[1:]],
        "nan": [_node(0, embedding=[float("nan")] * EMBEDDING_DIM), *base[1:]],
        "inf": [_node(0, embedding=[float("inf")] * EMBEDDING_DIM), *base[1:]],
        "zero_vector": [_node(0, embedding=[0.0] * EMBEDDING_DIM), *base[1:]],
        "wrong_dimension": [_node(0, embedding=[0.1, 0.2]), *base[1:]],
        "unparsable": [_node(0, embedding="[0.1,,x]"), *base[1:]],
    }[case]
    snapshot = _build(nodes=nodes)

    assert any(expected in violation for violation in snapshot.violations), snapshot.violations


def test_case_items_block_the_snapshot() -> None:
    snapshot = _build(case_item_count=2)

    assert any("案例条目" in violation for violation in snapshot.violations)
    assert snapshot.ok is False


@pytest.mark.parametrize(
    ("embedding", "expected"),
    [
        pytest.param(None, "缺嵌入身份", id="absent"),
        pytest.param(EmbeddingIdentity(model="", dimension=EMBEDDING_DIM), "嵌入身份不完整", id="no_model"),
        pytest.param(EmbeddingIdentity(model="m", dimension=1024), "与绑死常量", id="wrong_dimension"),
    ],
)
def test_broken_embedding_identity_is_a_violation(embedding: EmbeddingIdentity | None, expected: str) -> None:
    snapshot = build_snapshot(
        _manifest(FILE_A, FILE_B),
        database="campfire_carebench_test",
        items=_items_default(),
        nodes=_nodes_default(),
        embedding=embedding,
    )

    assert any(expected in violation for violation in snapshot.violations), snapshot.violations


# ---------------------------------------------------------------------------
# 快照内容：node 级证据进 to_dict
# ---------------------------------------------------------------------------


def test_to_dict_carries_node_level_evidence() -> None:
    nodes = _nodes_default()
    payload = _build(nodes=nodes).to_dict()

    assert payload["format_version"] == SNAPSHOT_FORMAT_VERSION
    assert payload["nodes"] == {"count": 3, "sha256": node_content_digest(nodes)}
    by_id = {item["item_id"]: item for item in payload["items"]}
    assert by_id[ITEM_A]["doc_hash"] == DOC_HASH_A
    assert by_id[ITEM_A]["nodes"] == 2
    assert by_id[ITEM_A]["nodes_sha256"] == node_content_digest([_node(0), _node(1)])
    assert by_id[ITEM_B]["nodes_sha256"] == node_content_digest([_node(0, item_id=ITEM_B)])
    assert payload["embedding"] is not None and payload["embedding"]["dimension"] == EMBEDDING_DIM
    assert json.loads(json.dumps(payload, ensure_ascii=False))["nodes"]["count"] == 3
    assert "secret" not in json.dumps(payload).lower()


def test_snapshot_makes_no_assumption_about_corpus_size() -> None:
    """不假定固定条目数/节点数：一份语料一条节点同样成立。"""
    one = build_snapshot(
        _manifest(FILE_A),
        database="campfire_carebench_test",
        items=[_item(ITEM_A)],
        nodes=[_node(0)],
        embedding=_identity(),
    )
    ids = [f"{index:08d}-0000-4000-8000-000000000000" for index in range(3)]
    many_items = [
        KnowledgeItemRow(
            item_id=item_id,
            title=f"标题 {index}",
            source_path=f"data/knowledge/{FILE_B if index == 1 else FILE_A}",
            withdrawn=False,
            nodes=0,
            source="出处",
            doc_hash=DOC_HASH_B if index == 1 else DOC_HASH_A,
        )
        for index, item_id in enumerate(ids)
    ]
    many = build_snapshot(
        _manifest(FILE_A, FILE_B),
        database="campfire_carebench_test",
        items=many_items,
        nodes=[_node(index, item_id=item_id) for item_id in ids for index in range(3)],
        embedding=_identity(),
    )

    assert one.ok is True and one.node_count == 1
    assert many.ok is True and many.node_count == 9
    assert one.sha256 != many.sha256


# ---------------------------------------------------------------------------
# 读库路径：桩会话（不连库），钉住取数口径与缺省身份
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, rows: Any) -> None:
        self._rows = rows

    def all(self) -> Any:
        return self._rows

    def scalar_one(self) -> Any:
        return self._rows


class _StubSession:
    """按 SQL 里的表名分发条目 / 节点 / 案例计数；判据全部走真实实现。"""

    def __init__(self, *, items: list[tuple[Any, ...]], nodes: list[Any], case_count: int) -> None:
        self._items, self._nodes, self._case_count = items, nodes, case_count
        self.statements: list[str] = []

    async def execute(self, statement: Any, _params: Any = None) -> _StubResult:
        sql = str(statement)
        self.statements.append(sql)
        if "campfire_knowledge_item" in sql:
            return _StubResult(self._items)
        if "data_campfire_node" in sql:
            return _StubResult(self._nodes)
        if "campfire_case_item" in sql:
            return _StubResult(self._case_count)
        raise AssertionError(f"未预期的查询：{sql[:120]}")


def _node_row(node: NodeRecord) -> SimpleNamespace:
    """模拟一行节点查询结果（向量以 pgvector 文本形返回）。"""
    return SimpleNamespace(
        node_id=node.node_id,
        item_id=node.item_id,
        text=node.text,
        metadata=dict(node.metadata),
        embedding="[" + ",".join(repr(value) for value in canonical_vector(node.embedding)) + "]",
    )


@pytest.mark.asyncio
async def test_read_database_state_wires_rows_and_defaults_to_the_configured_identity() -> None:
    """真实行 → 摘要与纯函数一致；不传 `embedding` 时取当前配置（与真实嵌入调用同源）。"""
    nodes = _nodes_default()
    session = _StubSession(
        items=[
            (ITEM_A, "测试条目", f"data/knowledge/{FILE_A}", False, "测试出处", DOC_HASH_A),
            (ITEM_B, "测试条目", f"data/knowledge/{FILE_B}", False, "测试出处", DOC_HASH_B),
        ],
        nodes=[_node_row(node) for node in nodes],
        case_count=0,
    )

    snapshot = await read_database_state(
        session,  # type: ignore[arg-type]  # 桩只实现 execute
        snapshot=_manifest(FILE_A, FILE_B),
        database="campfire_carebench_test",
    )

    assert snapshot.ok is True
    assert snapshot.embedding is not None and snapshot.embedding.configured is True
    assert snapshot.embedding.dimension == EMBEDDING_DIM
    assert snapshot.nodes_sha256 == _build(nodes=nodes).nodes_sha256
    assert any("embedding::text" in sql for sql in session.statements), "向量必须按文本读（口径唯一）"
