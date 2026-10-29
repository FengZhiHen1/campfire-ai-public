"""引用可核对性：`status` / `applicable_scope` 随载荷走，`withdrawn` 读回时现查（DEMO-03）。

对应契约与设计：

- docs/技术设计/technical-details/资料与案例检索.md 第 3 节（来源与适用范围必须随结果
  传递）、第 4 节（历史引用保留，但呈现时必须标注「该来源已撤下」，不得再作为当前依据）；
- docs/design/pages/对话页.md 契约修订 5（状态徽章；撤下判定来自 citation 载荷刷新，
  不由前端猜测）；
- docs/技术设计/面/consult/HTTP与SSE契约.md 第 7 节（citation part 事件流与水合同形）。

本文件钉三件事：

1. **事件流与水合一致**：同一条凭据在线格式与水合出的 part 里逐字相同（含可核对性三项）；
   —— 判据是拿**写侧/事件侧**的真实函数与**读侧**的真实解析直接比对，不是两处各写一份期望。
2. **读回时按当前真源重判撤下**：在库 ⇒ `False`、已撤下 ⇒ `True`、
   找不到/解析不了/取数失败 ⇒ `None`（未知）。**「找不到」不得说成「已撤下」**。
3. **不编造**：任何一项缺数据都保持未知，不补「已发表」。

集成部分（真实 PostgreSQL）用 `pytest.mark.integration` 标记，未配置库时跳过。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import delete

from campfire.agent.context import CitationRecorder
from campfire.agent.runtime.events import CitationEvent
from campfire.agent.runtime.session_annotations import citation_annotation
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts.session_items import (
    PART_TYPE_CITATION,
    CitationPart,
    CitationRecordPart,
    HydratedMessage,
    StoredItem,
    build_messages,
)
from campfire.surfaces.consult import citations as consultation_citations
from campfire.surfaces.consult.citations import (
    parse_citation_reference,
    refresh_citation_freshness,
    resolve_citation_freshness,
)
from campfire.surfaces.consult.sse import event_payload

# ---------------------------------------------------------------------------
# 线格式与水合同形（DB-free）
# ---------------------------------------------------------------------------


class _MemoryIndex:
    """最小的引用索引替身：只为拿到 `CitationRecorder` 发出的凭据。"""

    def __init__(self) -> None:
        self.rows: list[object] = []

    async def add(self, record: object) -> None:
        self.rows.append(record)

    async def list_for_run(self, _run_id: str) -> Sequence[object]:
        return []


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant_with_annotation(annotation: Mapping[str, object], text: str = "建议尽早评估。") -> dict:
    return {
        "type": "message",
        "id": "__fake_id__",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": [dict(annotation)]}],
    }


def _stored(row_id: int, payload: dict) -> StoredItem:
    return StoredItem(row_id=row_id, data=payload)


@pytest.mark.asyncio
async def test_event_payload_and_hydrated_part_are_byte_identical() -> None:
    """★ 事件流与水合必须同形：同一条凭据在两个路径上逐字段相同。

    做法（判据的力量全在这里）：不另写一份期望值，而是

    1. 用**生产写入端**（`CitationRecorder`）发一条带可核对性三项的凭据；
    2. 用**生产事件编码**（`sse.event_payload(CitationEvent(...))`）得到线格式载荷；
    3. 用**生产写侧注解编码**（`session_annotations.citation_annotation`）把它挂进会话条目，
       再交给**生产读侧解析**（`session_items.build_messages`）水合；
    4. 断言两者逐字相同。

    判别性：把读侧对新三项的读取删掉（回到六个字段）⇒ 本用例红；
    把写侧注解里的三项删掉 ⇒ 同样红（水合出 `None` 而事件侧有值）。
    """
    record = await CitationRecorder(_MemoryIndex(), run_id="run-1").record(  # type: ignore[arg-type]
        source="knowledge",
        reference="knowledge:11111111-1111-4111-8111-111111111111",
        summary="视觉支持策略",
        status="published",
        applicable_scope="学龄前儿童",
        withdrawn=False,
    )

    wire = event_payload(CitationEvent(citation=record))["citation"]
    parts = build_messages(
        [_stored(1, _user("问")), _stored(2, _assistant_with_annotation(citation_annotation(record)))]
    )
    hydrated = next(part for part in parts[1]["parts"] if part["type"] == "citation")["citation"]

    assert hydrated == wire, "同一批引用在事件流与历史水合里必须逐字同形"
    # 三项都在，且值是写入时的真值（不是读侧补出来的）。
    assert hydrated["status"] == "published"
    assert hydrated["applicable_scope"] == "学龄前儿童"
    assert hydrated["withdrawn"] is False


# ---------------------------------------------------------------------------
# 回指解析
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "expected_library"),
    [
        ("knowledge:11111111-1111-4111-8111-111111111111", "knowledge"),
        ("case:11111111-1111-4111-8111-111111111111", "case"),
    ],
)
def test_parse_citation_reference_accepts_the_two_known_namespaces(reference: str, expected_library: str) -> None:
    """线格式的 `<库别>:<标识>` 是唯一认得的形状（与前端 `REFERENCE_NAMESPACE` 同源）。"""
    parsed = parse_citation_reference(reference)

    assert parsed is not None
    assert parsed[0] == expected_library
    assert parsed[1] == uuid.UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    "reference",
    [
        "11111111-1111-4111-8111-111111111111",  # 裸 uuid：不知道查哪个库
        "internal:11111111-1111-4111-8111-111111111111",  # 不认识的库别
        "knowledge:not-a-uuid",  # 标识不是 uuid
        "knowledge:a/b",  # 带分隔符：不是本仓写出来的形状
        "knowledge:",  # 空标识
        "",
    ],
)
def test_parse_citation_reference_returns_none_for_unparsable_shapes(reference: str) -> None:
    """解析不了就是解析不了（返回 `None`，不是抛异常、也不是猜一个库）。"""
    assert parse_citation_reference(reference) is None


# ---------------------------------------------------------------------------
# 读回时重判：只换 withdrawn，其余逐字不动（DB-free）
# ---------------------------------------------------------------------------


def _record_part(**overrides: object) -> CitationRecordPart:
    """一条引用载荷的默认形状；`overrides` 换掉本文件关心的字段。"""
    base: dict[str, object] = {
        "citation_id": "c1",
        "run_id": "r1",
        "source": "knowledge",
        "reference": "knowledge:11111111-1111-4111-8111-111111111111",
        "recorded_at": "2026-10-29T00:00:00+00:00",
        "summary": "视觉支持策略",
        "status": "published",
        "applicable_scope": "学龄前儿童",
        "withdrawn": False,
    }
    base.update(overrides)
    return cast(CitationRecordPart, base)


def _hydrated(payload: CitationRecordPart) -> HydratedMessage:
    return HydratedMessage(
        id="m1",
        role="assistant",
        parts=[
            {"type": "text", "text": "正文"},
            CitationPart(type=PART_TYPE_CITATION, citation=payload),
        ],
    )


@pytest.mark.asyncio
async def test_refresh_rewrites_only_withdrawn_and_keeps_the_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 只换 `withdrawn`：`status` / `applicable_scope` 是快照，**不**按当前真源改写。

    为什么这条要钉：状态与范围回答的是「当时我们依据的是什么」，把它按今天的数据刷新
    等于篡改历史依据；而 `withdrawn` 回答的是「现在还能不能引用」，不刷新就会把一条
    已撤下的来源继续呈成可用。两者取向相反，必须分开。
    """
    message = _hydrated(_record_part())

    async def _resolved(_settings: object, _references: Sequence[str]) -> dict[str, bool]:
        return {"knowledge:11111111-1111-4111-8111-111111111111": True}

    monkeypatch.setattr(consultation_citations, "resolve_citation_freshness", _resolved)

    refreshed = await refresh_citation_freshness(get_settings(), [message])

    payload = next(part for part in refreshed[0]["parts"] if part["type"] == "citation")["citation"]
    assert payload["withdrawn"] is True, "已撤下必须刷成 True"
    assert payload["status"] == "published", "快照状态不得被改写"
    assert payload["applicable_scope"] == "学龄前儿童"
    assert [part["type"] for part in refreshed[0]["parts"]] == ["text", "citation"], "part 顺序与数量不得变"
    # 输入不被就地修改（水合结果可能被上层持有）。
    original = next(part for part in message["parts"] if part["type"] == "citation")["citation"]
    assert original["withdrawn"] is False


@pytest.mark.asyncio
async def test_refresh_leaves_unresolvable_references_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 核对不出来的回指 ⇒ `withdrawn` 是 `None`（未知），**不是** `True`。

    判别性：把 `_refreshed_message` 里的 `resolved.get(reference)` 换成
    `resolved.get(reference, True)`（「核不出来就当撤下」）⇒ 本用例红。
    方向为什么重要：把在库/不存在的来源标成「已撤下」是对使用者的错误陈述。
    """

    async def _resolved(_settings: object, _references: Sequence[str]) -> dict[str, bool]:
        return {}

    monkeypatch.setattr(consultation_citations, "resolve_citation_freshness", _resolved)

    refreshed = await refresh_citation_freshness(
        get_settings(),
        [_hydrated(_record_part(reference="knowledge:missing"))],
    )

    payload = next(part for part in refreshed[0]["parts"] if part["type"] == "citation")["citation"]
    assert payload["withdrawn"] is None


@pytest.mark.asyncio
async def test_refresh_skips_the_lookup_when_there_is_no_citation(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 citation part 的历史不查库（水合路径不该为无关消息多付一次查询）。"""

    async def _boom(_settings: object, _references: Sequence[str]) -> dict[str, bool]:
        raise AssertionError("没有引用时不该发起核对")

    monkeypatch.setattr(consultation_citations, "resolve_citation_freshness", _boom)

    messages: list[HydratedMessage] = [{"id": "m1", "role": "assistant", "parts": [{"type": "text", "text": "正文"}]}]

    assert [message["id"] for message in await refresh_citation_freshness(get_settings(), messages)] == ["m1"]


# ---------------------------------------------------------------------------
# 真实库：在库 / 已撤下 / 不存在 三态（集成）
# ---------------------------------------------------------------------------


def _require_db() -> None:
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_withdrawn_is_resolved_against_the_current_source_of_truth() -> None:
    """★ 三态必须来自当前真源：在库 ⇒ False、已撤下 ⇒ True、不存在 ⇒ 未知（None）。

    为什么必须连真库：判据就是「按当前真源查」——替身只能证明代码调了某个函数，
    证明不了它查的是条目表的 `withdrawn`。撤下用真实的
    `modules/library/withdrawal.withdraw_item`（CLI 走的同一条路），不直接 UPDATE。
    """
    _require_db()
    from campfire.modules.library import models as library_models
    from campfire.modules.library import withdrawal

    live_id = uuid.uuid4()
    withdrawn_id = uuid.uuid4()
    missing_id = uuid.uuid4()

    async with session_scope(get_settings()) as session:
        session.add(
            library_models.KnowledgeItem(
                id=live_id,
                title="在库的资料",
                source="某机构公开材料",
                applicable_scope="学龄前儿童",
            )
        )
        session.add(
            library_models.KnowledgeItem(
                id=withdrawn_id,
                title="会被撤下的资料",
                source="某机构公开材料",
                applicable_scope="学龄前儿童",
            )
        )

    try:
        async with session_scope(get_settings()) as session:
            await withdrawal.withdraw_item(session, library="knowledge", item_id=str(withdrawn_id))

        references = [
            f"knowledge:{live_id}",
            f"knowledge:{withdrawn_id}",
            f"knowledge:{missing_id}",
            "internal:whatever",  # 解析不了：不该让整批失败
        ]
        resolved = await resolve_citation_freshness(get_settings(), references)

        assert resolved[f"knowledge:{live_id}"] is False, "在库的条目标记为未撤下"
        assert resolved[f"knowledge:{withdrawn_id}"] is True, "撤下由当前真源给出，不靠快照"
        assert f"knowledge:{missing_id}" not in resolved, "找不到的条目不得出现在核对结果里（= 未知）"
        assert "internal:whatever" not in resolved, "解析不了的回指不得被猜成某个库"

        # 端到端：水合载荷里三态各自落成 True / False / None。
        message = HydratedMessage(
            id="m1",
            role="assistant",
            parts=[
                CitationPart(
                    type=PART_TYPE_CITATION, citation=_record_part(citation_id=f"c{index}", reference=reference)
                )
                for index, reference in enumerate(references)
            ],
        )

        refreshed = await refresh_citation_freshness(get_settings(), [message])
        flags = [
            part["citation"]["withdrawn"]  # type: ignore[typeddict-item]
            for part in refreshed[0]["parts"]
            if part["type"] == "citation"
        ]

        assert flags == [False, True, None, None], "在库 / 已撤下 / 不存在 / 解析不了 四态投影"
    finally:
        async with session_scope(get_settings()) as session:
            for item_id in (live_id, withdrawn_id):
                row = await session.get(library_models.KnowledgeItem, item_id)
                if row is not None:
                    await session.delete(row)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_case_library_withdrawals_resolve_through_the_case_namespace() -> None:
    """`case:<id>` 走案例表：张冠李戴（用资料表查案例回指）会让撤下判定永远查不到。

    判别性：把 `_REFERENCE_MODELS` 里 `case` 映射到 `KnowledgeItem` ⇒ 本用例红
    （案例条目永远查不到 ⇒ `withdrawn` 恒为未知）。
    """
    _require_db()
    from campfire.modules.library import models as library_models

    case_id = uuid.uuid4()
    async with session_scope(get_settings()) as session:
        session.add(
            library_models.CaseItem(
                id=case_id,
                external_key=f"test-{case_id}",
                title="一条虚构样例",
                source="某次访谈",
                applicable_scope="学龄前",
                authorization="已授权（虚构样例）",
                source_type="专家访谈转写",
                evidence_level="OBSERVATIONAL",
                review_status="owner",
                interview_at=datetime(2026, 5, 25, tzinfo=UTC),
                subject_type="家长",
                consent_scope="ai_retrieval_and_advice",
                status="fictional",
                withdrawn=True,
            )
        )

    try:
        resolved = await resolve_citation_freshness(get_settings(), [f"case:{case_id}"])

        assert resolved[f"case:{case_id}"] is True, "案例侧的撤下标记必须能查到"
    finally:
        async with session_scope(get_settings()) as session:
            await session.execute(delete(library_models.CaseItem).where(library_models.CaseItem.id == case_id))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lookup_failure_keeps_everything_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """取数失败 ⇒ 整批未知（不是「都在库」）：说「在库」等于给没核对过的来源背书。"""
    _require_db()

    async def _broken_session(_settings: object):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover —— 只为让它成为异步生成器

    monkeypatch.setattr(consultation_citations, "session_scope", _broken_session)

    resolved = await resolve_citation_freshness(get_settings(), ["knowledge:11111111-1111-4111-8111-111111111111"])

    assert resolved == {}, "取数失败时不得返回任何「已核对」的结论"
