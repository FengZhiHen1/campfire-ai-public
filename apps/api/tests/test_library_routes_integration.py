"""集成测试：资料库面 HTTP 端点的形状、两库分流、展开与 deep-link 三态（真实 PostgreSQL）。

对应 ``docs/技术设计/面/profile/资料库面HTTP契约.md`` 第 2～6 节与
``docs/技术设计/technical-details/资料与案例检索.md`` 第 3、4、5 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_library_routes_integration.py

## 只用虚构样例数据

`EVID-B` 未关闭前不得录真实素材（项目红线）。本文件的案例包前缀是 `2098-`，
与 `test_library_case_integration` 的 `2099-` 分开，因此两个文件并发跑时互不
清对方的数据（该文件已实测踩过「无过滤清理互删」的坑）。

嵌入用确定性替身（`TOKENHUB_API_KEY` 是 `.env.example` 的占位符，登记于 `TECH-02`），
SQL、融合、聚合、撤下与聚合后的 HTTP 形状都是真实的。

## 本文件守住的判据

1. 两库分开取数：`library=case` 只回案例、`library=knowledge` 只回资料。
2. 撤下条目不进列表（`RQ-KB-04`），但 deep-link 仍可见三态中的「已撤下」。
3. deep-link 三态：在库（完整条目）/ 已撤下（`item: null, withdrawn: true, title`）/ 404。
4. 案例的六项必带字段 + `inferred_fields` 在列表里都在场（`AC-06` 的前提）。
5. 空与失败可区分：检索为空 → 200 空数组；两路都失败 → 503。
6. `expand` 一次一条、内容随列表返回；`expand` 指向另一个库的条目 → 422。
7. 未知 `library` → 422（不静默退回资料库）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from campfire.core.config import EMBEDDING_DIM, Settings, get_settings
from campfire.core.db import create_engine, create_sync_engine, session_scope
from campfire.modules.library import routes as library_routes
from campfire.modules.library.case_ingestion import NARRATIVE_SECTIONS, ingest_case_package
from campfire.modules.library.ingestion import build_vector_store
from campfire.modules.library.models import CaseItem, KnowledgeItem, RetrievedNode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: 本文件的虚构前缀，与其它测试文件的 2099- 分开（并发跑时互不清对方的数据）。
FICTIONAL_PREFIX = "2098-"

#: 账号：本面数据是公共语料，账号只承担「必须登录」，因此一个固定值即可。
_ACCOUNT = "it_library_routes_account"


def _fake_vector(text_value: str) -> list[float]:
    """确定性替身向量：同文本永远得到同一向量（因此排序稳定、用例可复现）。"""
    seed = sum(ord(ch) for ch in text_value) % 97
    return [0.001 * ((i + seed) % 97 + 1) for i in range(EMBEDDING_DIM)]


class _FakeEmbedder:
    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]

    async def aget_query_embedding(self, query: str) -> list[float]:
        return _fake_vector(query)


@pytest.fixture(autouse=True)
def _patched_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """把嵌入构造换成替身：`TOKENHUB_API_KEY` 无效，真实调用必然 401。

    打的是 `campfire.modules.library.embedding.build_embedding`——本面的
    非空查询路径在函数内 import 它并调用，因此这个补丁真的作用在生产路径上。
    """
    monkeypatch.setattr("campfire.modules.library.embedding.build_embedding", lambda _settings: _FakeEmbedder())
    monkeypatch.setattr("campfire.modules.library.ingestion.build_embedding", lambda _settings: _FakeEmbedder())


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


def _store():
    """构造本文件用的向量存储（同步引擎由调用方用完即关）。"""
    settings = get_settings()
    sync_engine = create_sync_engine(settings)
    async_engine = create_engine(settings)
    return (
        settings,
        sync_engine,
        async_engine,
        build_vector_store(settings, engine=sync_engine, async_engine=async_engine),
    )


async def _cleanup_case(source_path: str) -> None:
    """清掉本文件写入的案例条目与其节点（表结构保留）。"""
    async with session_scope(get_settings()) as session:
        items = (await session.execute(select(CaseItem).where(CaseItem.source_path == source_path))).scalars().all()
        for item in items:
            await session.execute(RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%")))
            await session.delete(item)


async def _cleanup_knowledge(title: str) -> None:
    """清掉本文件写入的资料条目与其节点。"""
    async with session_scope(get_settings()) as session:
        items = (
            (await session.execute(select(KnowledgeItem).where(KnowledgeItem.source == _KNOWLEDGE_SOURCE)))
            .scalars()
            .all()
        )
        for item in items:
            await session.execute(RetrievedNode.__table__.delete().where(RetrievedNode.node_id.like(f"{item.id}:%")))
            await session.delete(item)
    del title


#: 本文件写入的资料条目的来源串：按它清理，避免全表删除（并发下会删别人的行）。
_KNOWLEDGE_SOURCE = "2098 虚构资料（资料库面路由集成测试）"


def _write_knowledge_package(root: Path) -> Path:
    """造一个虚构的资料 Markdown 文件（带 frontmatter，含来源与适用范围）。"""
    path = root / "knowledge-2098.md"
    path.write_text(
        "---\n"
        "title: 虚构资料：结构化日程与视觉支持\n"
        f"source: {_KNOWLEDGE_SOURCE}\n"
        "applicable_scope: 学龄前儿童（3-6 岁）\n"
        "keywords: 视觉支持 日程\n"
        "---\n\n"
        "# 虚构资料：结构化日程与视觉支持\n\n"
        "## 一、基本要求\n\n"
        "虚构正文：结构化日程能降低活动转换时的困难，建议配合图片日程表使用。\n",
        encoding="utf-8",
    )
    return path


def _card(**overrides: object) -> dict[str, object]:
    """一张虚构 L2 卡片；默认值刻意让 `medical_criteria` 非空（高风险档）。"""
    card: dict[str, object] = {
        "card_id": "{AWAITING_SYSTEM}",
        "raw_id": "{AWAITING_SYSTEM}",
        "title": "虚构卡片：图片日程表",
        "scenario": "虚构场景：活动转换前给出图片日程表。",
        "behavior_type": "其他",
        "age_range": ["3", "6"],
        "severity_level": "轻",
        "setting": "家庭",
        "ebp_tags": ["视觉支持(VS)"],
        "parent_category": "环境调整",
        "immediate_action": "1. 展示图片日程表。",
        "comforting_phrase": "我们慢慢来。",
        "observation_metrics": "记录一周内主动查看的次数。",
        "medical_criteria": "出现自伤行为即就医。",
        "evidence_level": "INSTITUTIONAL",
        "caution_notes": "不要在情绪高峰时强行要求。",
        "contraindications": "无",
        "is_template": False,
        "_inferred": {"severity_level": "虚构推断理由"},
    }
    card.update(overrides)
    return card


def _build_case_package(root: Path, *, slug: str, title: str) -> Path:
    """造一个虚构案例包（manifest + L1 五节叙事 + 一张 L2 卡片）。"""
    package = root / slug
    package.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "external_key": f"{FICTIONAL_PREFIX}01-01_0000_{slug}",
        "title": title,
        "source_type": "专家访谈转写",
        "subject_type": "家长",
        "interview_at": "2098-01-01T00:00:00+08:00",
        "consent_scope": "ai_retrieval_and_advice",
        "consent_recorded_at": "2098-01-01",
        "evidence_level": "INSTITUTIONAL",
        "review_status": "owner",
        "reviewer": None,
        "authorization": "虚构样例（无真实来源）",
        "transcript_ref": "（虚构，无上游转写稿）",
        "keywords": "虚构关键词 结构化活动",
        "aliases": "",
        "status": "internal",
        "files": {"narrative": "L1_x.md", "cards": ["L2_x_01.json"]},
    }
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    sections = "\n\n".join(
        f"## {name}\n\n虚构的{name}段落，提到结构化活动与图片日程表。" for name in NARRATIVE_SECTIONS
    )
    (package / "L1_x.md").write_text(f"# {title}\n\n{sections}\n", encoding="utf-8")
    (package / "L2_x_01.json").write_text(json.dumps(_card(), ensure_ascii=False), encoding="utf-8")
    return package


@pytest_asyncio.fixture
async def seeded(tmp_path: Path) -> AsyncIterator[dict[str, str]]:
    """落一个案例与一份资料，返回它们的标识；收尾按来源串清理。

    包文件落在 pytest 的 `tmp_path` 里（不是仓库目录）：它们是测试输入，
    不该进版本控制，也不该在跑完测试后在仓库里留下目录。

    清理按来源串过滤而不是全表删除：并发跑时全表删除会删掉别的测试文件刚写入的行
    （`test_auth_registration_integration` 已实测踩过这一坑）。
    """
    case_title = "虚构案例：结构化活动参与"
    package = _build_case_package(tmp_path, slug="case-2098-01", title=case_title)
    knowledge_path = _write_knowledge_package(tmp_path)

    settings, sync_engine, _async_engine, store = _store()
    try:
        from campfire.modules.library.ingestion import ingest_file

        async with session_scope(settings) as session:
            case_result = await ingest_case_package(settings, session, vector_store=store, package_dir=package)
        async with session_scope(settings) as session:
            knowledge_result = await ingest_file(settings, session, vector_store=store, path=knowledge_path)
        yield {
            "case_source_path": str(package),
            "case_item_id": case_result.item_id,
            "case_title": case_title,
            "knowledge_item_id": knowledge_result.item_id,
            "knowledge_title": "虚构资料：结构化日程与视觉支持",
        }
    finally:
        await _cleanup_case(str(package))
        await _cleanup_knowledge(_KNOWLEDGE_SOURCE)
        sync_engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """穿过完整应用路由的 ASGI 客户端（SDK 必须先初始化，同档案面的说明）。"""
    import campfire.main as main_module
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(get_settings(), api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
    main_module.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _as_account() -> None:
    """把登录态固定成本文件的账号（本面数据是公共语料，账号只承担「必须登录」）。"""
    import campfire.main as main_module

    main_module.app.dependency_overrides[library_routes.current_account] = lambda: _ACCOUNT


# ---------------------------------------------------------------------------
# 浏览与两库分流（契约第 2、3 节）
# ---------------------------------------------------------------------------


async def test_browse_defaults_to_case_library(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """`library` 缺省为 `case`（页面默认落在案例分区，契约第 3 节）。"""
    response = await client.get("/library/items")

    assert response.status_code == 200
    body = response.json()
    assert body["library"] == "case"
    assert seeded["case_item_id"] in [item["item_id"] for item in body["items"]]


async def test_two_libraries_are_read_separately(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """两库分开取数（`RQ-KB-01`）：库别决定回哪些条目，不合并成一张表加类型标签。"""
    cases = await client.get("/library/items", params={"library": "case"})
    knowledge = await client.get("/library/items", params={"library": "knowledge"})

    case_ids = {item["item_id"] for item in cases.json()["items"]}
    knowledge_ids = {item["item_id"] for item in knowledge.json()["items"]}

    assert seeded["case_item_id"] in case_ids
    assert seeded["knowledge_item_id"] not in case_ids
    assert seeded["knowledge_item_id"] in knowledge_ids
    assert seeded["case_item_id"] not in knowledge_ids
    assert all(item["library"] == "knowledge" for item in knowledge.json()["items"])


async def test_case_items_carry_the_six_mandatory_fields_and_inferred(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """案例的六项必带字段 + `inferred_fields` 在列表里都在场（`AC-06` 的前提）。

    缺任一个，页面就无法如实回答「谁说的、多可信、什么时候」，列表退化为
    无法核对的读物（资料与案例检索第 3 节）。这里断言键在场而不只断言
    值非空：字段缺失与字段为空对呈现层是两件事。

    `inferred_fields` 在浏览路是空列表而非 `None` —— 这是检索链已文档化的
    决定（`retrieval._case_fields_for_browse`：浏览路是条目级列表，没有「命中的是
    哪张卡片」，因此为空清单，不拿案例级并集冒充）。本用例因此同时钉住那条决定
    与「资料侧是 `None`」的区分：若实现把空列表折叠成 `None`，「这条案例没有
    卡片级推断」就会与「这条不是案例」在响应里无法区分（实测曾如此）。
    """
    response = await client.get("/library/items", params={"library": "case"})

    item = next(entry for entry in response.json()["items"] if entry["item_id"] == seeded["case_item_id"])
    for key in (
        "authorization",
        "source_type",
        "evidence_level",
        "review_status",
        "interview_at",
        "makes_claims_high_risk",
        "inferred_fields",
    ):
        assert key in item, key
    assert item["review_status"] == "owner"
    assert item["authorization"]
    # 访谈时间按 UTC 归一后出参（2098-01-01T00:00+08:00 → 2097-12-31T16:00Z），
    # 因此断言「带着时区且可解析」而不是断言字面前缀。
    assert item["interview_at"].endswith("Z") or "+" in item["interview_at"]
    assert item["interview_at"].startswith("2097-12-31T16:00")
    assert item["inferred_fields"] == []


async def test_knowledge_items_do_not_carry_case_only_fields(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """资料条目不得带上案例专属字段（那会让前端把资料当案例呈现）。

    `inferred_fields` 的一侧是本用例的验收对象：案例侧是空列表、资料侧是
    `None`——两者必须可区分（实测曾因 `if x else None` 被折叠成同一个值）。
    """
    response = await client.get("/library/items", params={"library": "knowledge"})

    item = next(entry for entry in response.json()["items"] if entry["item_id"] == seeded["knowledge_item_id"])
    assert item["authorization"] is None
    assert item["inferred_fields"] is None
    assert item["applicable_scope"] == "学龄前儿童（3-6 岁）"
    assert item["source"] == _KNOWLEDGE_SOURCE


async def test_empty_inferred_list_is_distinguishable_from_absent(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """「案例但没有卡片级推断」与「不是案例」必须在响应里可区分。

    案例侧浏览路的 `inferred_fields` 是空列表、资料侧是 `None`（检索链已文档化的
    取值规则）。把空列表折叠成 `None` 会让前端无法判断该不该渲染推断标注。
    """
    cases = await client.get("/library/items", params={"library": "case"})
    knowledge = await client.get("/library/items", params={"library": "knowledge"})

    case_item = next(entry for entry in cases.json()["items"] if entry["item_id"] == seeded["case_item_id"])
    knowledge_item = next(
        entry for entry in knowledge.json()["items"] if entry["item_id"] == seeded["knowledge_item_id"]
    )

    assert case_item["inferred_fields"] == []
    assert knowledge_item["inferred_fields"] is None
    assert case_item["inferred_fields"] != knowledge_item["inferred_fields"]


async def test_search_returns_hits_with_degradation_field(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """非空查询走两路检索；响应带 `degraded_paths`（空表示两路都正常）。"""
    response = await client.get("/library/items", params={"library": "case", "query": "结构化活动"})

    assert response.status_code == 200
    body = response.json()
    assert body["degraded_paths"] == []
    assert seeded["case_item_id"] in [item["item_id"] for item in body["items"]]


async def test_empty_result_is_200_with_empty_array(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """检索为空不是失败：200 空数组，不标注降级（契约第 6 节）。

    为什么必须替身而不是真的搜一个不存在的词：向量路按 `similarity_top_k`
    取最近邻、没有相关度阈值（`retrieval.VECTOR_TOP_K = 30`），因此库里有
    任何节点时它总会返回若干条。也就是说「检索为空」在这条链上等价于
    「该库没有任何可检索节点」——那正是本用例要固定下来的语义：库为空
    返回 200 空数组，而不是 503。
    """
    from campfire.modules.library.retrieval import SearchOutcome

    async def _empty(*args, **kwargs):  # noqa: ANN002, ANN003
        return SearchOutcome(items=[], degraded_paths=())

    monkeypatch.setattr(library_routes, "search", _empty)

    response = await client.get("/library/items", params={"library": "case", "query": "结构化活动"})

    assert response.status_code == 200
    assert response.json()["items"] == []
    # 空结果不标注降级：两路都正常，只是没命中（契约第 6 节「单路失败才标注」）。
    assert response.json()["degraded_paths"] == []


async def test_rejects_unknown_library(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """未知 `library` → 422（不静默退回资料库，契约第 2 节）。

    消融：改成静默退回资料库，本断言必须失败——那会让案例检索拿到资料条目
    并当成案例呈现，比明确失败更危险。
    """
    response = await client.get("/library/items", params={"library": "nope"})

    assert response.status_code == 422


async def test_rejects_out_of_range_limit_and_foreign_cursor(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """`limit` 越界与非法游标各 422（契约第 2 节：载荷不合法）。"""
    too_big = await client.get("/library/items", params={"limit": 10_000})
    bad_cursor = await client.get("/library/items", params={"cursor": "abc"})

    assert too_big.status_code == 422
    assert bad_cursor.status_code == 422


async def test_rejects_cursor_the_parser_cannot_parse(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """游标的形状闸门必须与解析器同域：解析不了的游标一律 422，不得 500。

    三种取值钉住「闸门比解析器宽」的两个方向（修复前实测的状态）：

    - `²`（Unicode 上标数字）：`str.isdigit()` 为真而 `int()` 抛 `ValueError`
      ——未捕获的异常在生产上是 500，而契约第 2 节要 422；
    - `１２３`（全角数字）：两者都「成功」，于是面从未发出过的偏移量 123 被静默
      接受（200）——「只由本面产生」的游标形状没有被真正守住；
    - 5000 位数字串：`isdigit()` 为真，但 `int()` 撞上 CPython 的整数串转换上限
      （4300 位）又抛 `ValueError`——同一个洞的第二条 500 路径。

    消融：修复前这三种取值分别得到 500 / 200 / 500，三条断言全红。
    """
    for cursor in ("²", "１２３", "1" * 5000):
        response = await client.get("/library/items", params={"library": "case", "cursor": cursor})
        assert response.status_code == 422, f"cursor={cursor[:8]!r} 得到 {response.status_code}"


async def test_browse_pagination_walks_without_repeats(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """浏览路按游标翻页不重不漏；翻到尾部 `next_cursor` 为 null。

    本文件只落了少量条目，因此这里断言的是「跟随游标能走到 null 且见到目标条目」，
    不是「翻满 N 页」——后者依赖库里恰好有多少语料，而那是别处（主库历史语料）
    决定的，测试不应该依赖它。
    """
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # 上界防止游标不推进时无限循环（CORE-11）
        params: dict[str, object] = {"library": "case", "limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get("/library/items", params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["item_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None
    assert len(seen) == len(set(seen))


async def test_search_page_size_is_the_single_page_limit(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """检索路的单页条数就是 `limit`：不多探一条，也不多发一条。

    `window = offset + limit + 1` 是浏览路为判断「还有没有下一页」多探一条而设计的，
    而检索路没有对应的切片（只按 `is_browse` 切），于是这个值被原样当成单页条数
    传下去——`limit=1` 会回 2 条，与 docstring「`limit`：单页条数」相反。

    替身按收到的 `limit` 截断结果，因此「检索链收到多少」是可观察的。

    同时钉住检索路不可翻页这个已文档化的决定（见 `list_items` 内注释）：
    `cursor` 不参与取数，`next_cursor` 恒为 null——本用例只要求它「不假装能翻页」，
    不要求它翻页。

    消融：修复前替身收到 2（`offset 0 + limit 1 + 1`）、响应回 2 条，两条断言都红。
    """
    from campfire.modules.library.retrieval import RetrievedItem, SearchOutcome

    received: list[int] = []

    def _item(index: int) -> RetrievedItem:
        return RetrievedItem(
            item_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"library-page-{index}")),
            library="case",
            title=f"虚构条目 {index}",
            snippet="虚构片段",
            source="虚构来源",
            applicable_scope="不限",
            status="internal",
            locator="loc",
            ranking={"fused_score": 0.1},
        )

    async def _search(*args, **kwargs):  # noqa: ANN002, ANN003
        received.append(kwargs["limit"])
        return SearchOutcome(items=[_item(index) for index in range(3)][: kwargs["limit"]], degraded_paths=())

    monkeypatch.setattr(library_routes, "search", _search)

    response = await client.get("/library/items", params={"library": "case", "query": "结构化活动", "limit": 1})

    assert response.status_code == 200
    assert received == [1], "检索链收到的必须是单页条数，不是「多探一条」的窗口"
    assert len(response.json()["items"]) == 1, "单页条数就是 limit，不得多发一条"
    assert response.json()["next_cursor"] is None


async def test_search_ignores_cursor_visibly_rather_than_pretending_to_page(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """非空 `query` 下的 `cursor` 不参与取数，且响应明确 `next_cursor: null`。

    这是 `list_items` 内注释写下的决定（检索路是融合后的 top-K 名次列表，没有
    「第 K 名之后」的谓词，因此不假装能翻页），本用例把它固定成可观察行为：
    带 `cursor` 重取得到与首页相同的结果，调用方据 `next_cursor: null` 知道
    这里没有下一页——而不是把它读成「已到末页」的翻页结果。
    """
    from campfire.modules.library.retrieval import RetrievedItem, SearchOutcome

    def _item() -> RetrievedItem:
        return RetrievedItem(
            item_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "library-cursor-0")),
            library="case",
            title="虚构条目",
            snippet="虚构片段",
            source="虚构来源",
            applicable_scope="不限",
            status="internal",
            locator="loc",
            ranking={"fused_score": 0.1},
        )

    async def _search(*args, **kwargs):  # noqa: ANN002, ANN003
        return SearchOutcome(items=[_item()], degraded_paths=())

    monkeypatch.setattr(library_routes, "search", _search)

    first = await client.get("/library/items", params={"library": "case", "query": "结构化活动", "limit": 1})
    with_cursor = await client.get(
        "/library/items", params={"library": "case", "query": "结构化活动", "limit": 1, "cursor": "1"}
    )

    assert first.status_code == with_cursor.status_code == 200
    assert with_cursor.json()["items"] == first.json()["items"]
    assert with_cursor.json()["next_cursor"] is None


# ---------------------------------------------------------------------------
# 展开（契约第 4 节）
# ---------------------------------------------------------------------------


async def test_expand_attaches_narrative_and_cards_to_that_item(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """`expand` 命中的条目额外带 `narrative` 与 `cards`，其他条目不附带。"""
    response = await client.get(
        "/library/items",
        params={"library": "case", "expand": seeded["case_item_id"]},
    )

    assert response.status_code == 200
    item = next(entry for entry in response.json()["items"] if entry["item_id"] == seeded["case_item_id"])
    assert item["narrative"] is not None
    assert item["narrative"]["sections"]
    assert item["cards"] is not None
    assert item["cards"]

    # 其他条目不带展开内容（一次只展开一条）。
    others = [entry for entry in response.json()["items"] if entry["item_id"] != seeded["case_item_id"]]
    for entry in others:
        assert entry["narrative"] is None
        assert entry["cards"] is None


async def test_expanded_cards_expose_high_risk_fields_and_inference(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """卡片的高风险字段照旧返回（呈现纪律不在本面，契约第 4 节），
    且被推断字段清单随卡片给出（「被推断的字段必须标为推断」的载体）。"""
    response = await client.get(
        "/library/items",
        params={"library": "case", "expand": seeded["case_item_id"]},
    )

    card = response.json()["items"][0]["cards"][0]
    assert card["immediate_action"]
    assert card["medical_criteria"]
    assert card["caution_notes"]
    assert card["inferred_fields"] == ["severity_level"]
    assert card["risk_class"] == "high"
    assert card["card_id"].startswith(f"{FICTIONAL_PREFIX}01-01_0000_case-2098-01#")


async def test_expand_cards_do_not_mix_in_narrative_sections(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """展开的 `cards` 只含卡片节点、`narrative.sections` 只含叙事节点（不互相混入）。

    同一张节点表装两类节点，混进来会让展开区出现重复的「场景背景」。
    """
    response = await client.get(
        "/library/items",
        params={"library": "case", "expand": seeded["case_item_id"]},
    )

    body = response.json()["items"][0]
    headings = [section["heading"] for section in body["narrative"]["sections"]]
    assert set(headings) == set(NARRATIVE_SECTIONS)
    assert len(body["cards"]) == 1


async def test_expand_rejects_malformed_id(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """非法 `expand` 标识 → 422（载荷问题，不静默忽略）。"""
    response = await client.get("/library/items", params={"library": "case", "expand": "not-a-uuid"})

    assert response.status_code == 422


async def test_expand_rejects_id_from_the_other_library(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """`expand` 指向另一个库的条目 → 422（该库的列表里永远不会出现它）。

    对抗用例：静默忽略会让调用方以为「展开没生效」是渲染问题，排查方向全错。
    """
    response = await client.get(
        "/library/items",
        params={"library": "case", "expand": seeded["knowledge_item_id"]},
    )

    assert response.status_code == 422


async def test_expand_of_item_not_on_page_is_not_an_error(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """`expand` 指向本库但不在当前页的条目：200 且该条目不出现——不是错误。

    这是正常的翻页情形（调用方刷新列表时目标可能不在当前页），把它当失败会让
    前端在翻页时收到 4xx。游标取一个超出可翻页窗口的值，因此该页必为空。
    """
    response = await client.get(
        "/library/items",
        params={"library": "knowledge", "limit": 1, "cursor": "999", "expand": seeded["knowledge_item_id"]},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def _point_library_routes_at(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Callable[[], None]:
    """把本面读到的设置换成 `settings`；返回一个把 `core.db` 进程内缓存还原的函数。

    还原必须由用例在自己的体内显式调用：请求路径会把按 `settings` 建出的引擎与会话
    工厂写进 `core.db` 的模块级缓存，而 `monkeypatch` 要等夹具（含 `seeded`）收尾之后
    才撤销——那时 `seeded` 正要用真设置删掉自己写入的语料，读到坏缓存就会清理失败、
    在库里留下脏行（本次实测踩过，已手工清理）。
    """
    import campfire.core.db as core_db

    original = (core_db._engine, core_db._session_factory)
    monkeypatch.setattr(library_routes, "get_settings", lambda: settings)
    core_db._engine = None
    core_db._session_factory = None

    def _restore() -> None:
        core_db._engine, core_db._session_factory = original

    return _restore


async def test_expand_fetch_failure_is_503_with_and_without_expand(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """同一失败原因下，带不带 `expand` 同码 503（契约第 2 节的错误码表里没有 500）。

    失败是真实的驱动失败、不是替身异常：把本面读到的设置换成指向无人监听的端口，
    并清掉 `core.db` 进程内缓存的引擎与会话工厂，于是逃出来的是生产里「数据库不可用」
    的同一异常类型——探针实测：裸 `load_items` 抛 `ConnectionRefusedError`，而检索路
    把它转译成 `RetrievalError`。

    两次请求只差 `expand` 一个参数，因此两条断言是「同因同码」的对照。

    消融：修复前 `_check_expand_target` 的取数在 `try` 之外，带 `expand` 的那次让
    `ConnectionRefusedError` 原样冒出（生产里由 Starlette 的 ServerErrorMiddleware
    兜成 500），不带的那次走检索链的转译 → 503；本用例因异常未被接住而红。
    """
    dead = Settings(database_url="postgresql+asyncpg://campfire:campfire@127.0.0.1:1/campfire")
    restore = _point_library_routes_at(monkeypatch, dead)
    try:
        without_expand = await client.get("/library/items", params={"library": "case"})
        with_expand = await client.get("/library/items", params={"library": "case", "expand": seeded["case_item_id"]})
    finally:
        restore()

    assert without_expand.status_code == 503
    assert with_expand.status_code == 503
    assert with_expand.json()["code"] == "retrieval_unavailable"


async def test_expand_with_unconfigured_database_is_503_for_both_requests(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """未配置 `DATABASE_URL` 时同样同码 503（`RuntimeError` 这一类）。

    `core.db.create_engine` 在缺配置时抛 `RuntimeError`，它发生在取得会话之前：
    不带 `expand` 的请求由检索路的 `except RuntimeError` 接住，带 `expand` 的请求
    原先没有任何 `except` 接它。两次请求一起断，钉住「同因同码」。
    """
    unconfigured = Settings(database_url=None)
    restore = _point_library_routes_at(monkeypatch, unconfigured)
    try:
        without_expand = await client.get("/library/items", params={"library": "case"})
        with_expand = await client.get("/library/items", params={"library": "case", "expand": seeded["case_item_id"]})
    finally:
        restore()

    assert without_expand.status_code == 503
    assert with_expand.status_code == 503
    assert with_expand.json()["code"] == "retrieval_unavailable"


async def test_expand_maps_known_retrieval_failure_to_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """`expand` 校验里的已知取数失败（`RetrievalError`）→ 503，与列表路同形。"""
    from campfire.modules.library.retrieval import RetrievalError

    async def _fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RetrievalError("虚构取数失败：条目表不可达")

    monkeypatch.setattr(library_routes, "load_items", _fail)

    response = await client.get("/library/items", params={"library": "case", "expand": seeded["case_item_id"]})

    assert response.status_code == 503
    assert response.json()["code"] == "retrieval_unavailable"


async def test_expand_lets_unknown_errors_bubble_instead_of_reporting_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """`expand` 校验里的未知编程错误原样冒出，不冒充「检索暂时不可用」。

    与 `get_item` 同一条纪律：改名／契约漂移类的缺陷被报成 503 时，使用者会照提示
    重试、运维会按依赖故障排查，而真相是代码缺陷。ASGI 传输把未捕获异常原样抛回
    测试，因此这里断言异常类型——它等价于生产里的 500（由 ServerErrorMiddleware
    兜底），而不是 503。

    消融：把捕获放宽成 `except Exception`，本用例收不到异常、响应是 503，必红。
    """

    async def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AttributeError("虚构的编程错误：条目模型改名后取数处未同步")

    monkeypatch.setattr(library_routes, "load_items", _boom)

    with pytest.raises(AttributeError):
        await client.get("/library/items", params={"library": "case", "expand": seeded["case_item_id"]})


# ---------------------------------------------------------------------------
# 撤下与 deep-link 三态（契约第 5 节）
# ---------------------------------------------------------------------------


async def test_withdrawn_case_disappears_from_list_but_deep_link_shows_three_states(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """撤下条目不进列表（`RQ-KB-04`），但 deep-link 以克制形态可见。

    三态一次测齐：撤下前（在库，完整条目）、撤下后（`item: null` + `withdrawn` +
    仅标题）、不存在的合法标识（404）。
    """
    item_id = seeded["case_item_id"]

    before = await client.get(f"/library/items/{item_id}")
    assert before.status_code == 200
    assert before.json()["item"]["item_id"] == item_id
    assert before.json()["withdrawn"] is False

    from campfire.modules.library.withdrawal import withdraw_item

    async with session_scope(get_settings()) as session:
        await withdraw_item(session, library="case", item_id=item_id, reason="集成测试撤下")

    listing = await client.get("/library/items", params={"library": "case"})
    assert item_id not in [item["item_id"] for item in listing.json()["items"]]

    after = await client.get(f"/library/items/{item_id}")
    assert after.status_code == 200
    body = after.json()
    assert body["item"] is None
    assert body["withdrawn"] is True
    assert body["title"] == seeded["case_title"]
    # 只带标题：不带正文与其他字段（页面渲染单条撤下卡，不显示正文）。
    assert set(body) == {"item", "withdrawn", "title"}


async def test_deep_link_of_unknown_or_malformed_id_is_404(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """不存在的合法标识与非法标识都 404（页面按普通进入处理）。"""
    unknown = await client.get(f"/library/items/{uuid.uuid4()}")
    malformed = await client.get("/library/items/not-a-uuid")

    assert unknown.status_code == 404
    assert malformed.status_code == 404
    assert unknown.json()["code"] == malformed.json()["code"] == "not_found"


async def test_deep_link_maps_known_retrieval_failure_to_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """已知取数失败（`RetrievalError`）→ 503，与列表路同形（契约第 6 节）。"""
    from campfire.modules.library.retrieval import RetrievalError

    async def _fail(_item_uuid):  # noqa: ANN001
        raise RetrievalError("虚构取数失败：节点表不可达")

    monkeypatch.setattr(library_routes, "_find_item_any_library", _fail)

    response = await client.get(f"/library/items/{uuid.uuid4()}")

    assert response.status_code == 503
    assert response.json()["code"] == "retrieval_unavailable"


async def test_deep_link_lets_unknown_errors_bubble_instead_of_reporting_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """未知编程错误原样冒出，不冒充「检索暂时不可用」503。

    本端点自己的 docstring 写明「未归入上面两类的意外异常原样冒出：把未知缺陷报成
    『检索暂时不可用』会掩盖真实的程序错误」，同文件 `list_items` 也只把已知失败
    类型转 503。改名/契约漂移类的缺陷（`AttributeError`/`TypeError`）被报成 503 时，
    使用者会照提示重试、运维会按依赖故障排查，而真相是代码缺陷。

    ASGI 传输把未捕获异常原样抛回测试，因此这里断言异常类型——它等价于生产里的
    500（由 Starlette 的 ServerErrorMiddleware 兜底），而不是 503。

    消融：修复前这里是 `except Exception`，本用例收不到异常、响应是 503，必红。
    """

    async def _boom(_item_uuid):  # noqa: ANN001
        raise AttributeError("虚构的编程错误：条目字段改名后取值处未同步")

    monkeypatch.setattr(library_routes, "_find_item_any_library", _boom)

    with pytest.raises(AttributeError):
        await client.get(f"/library/items/{uuid.uuid4()}")


async def test_deep_link_works_across_both_libraries(client: httpx.AsyncClient, seeded: dict[str, str]) -> None:  # noqa: ANN001
    """deep-link 没有 `library` 参数，因此两库都查得到（`item_id` 是 UUID，跨库不撞）。"""
    case = await client.get(f"/library/items/{seeded['case_item_id']}")
    knowledge = await client.get(f"/library/items/{seeded['knowledge_item_id']}")

    assert case.status_code == knowledge.status_code == 200
    assert case.json()["item"]["library"] == "case"
    assert knowledge.json()["item"]["library"] == "knowledge"
    assert knowledge.json()["item"]["source"] == _KNOWLEDGE_SOURCE


async def test_withdrawn_knowledge_also_returns_200_with_title_only(
    client: httpx.AsyncClient, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """资料侧的撤下与案例侧同形（两库的撤下语义一致，不因库别而异）。"""
    item_id = seeded["knowledge_item_id"]

    from campfire.modules.library.withdrawal import withdraw_item

    async with session_scope(get_settings()) as session:
        await withdraw_item(session, library="knowledge", item_id=item_id, reason="集成测试撤下")

    response = await client.get(f"/library/items/{item_id}")

    assert response.status_code == 200
    assert response.json()["withdrawn"] is True
    assert response.json()["title"] == seeded["knowledge_title"]
    assert response.json()["item"] is None


# ---------------------------------------------------------------------------
# 空与失败可区分（契约第 6 节）
# ---------------------------------------------------------------------------


async def test_both_paths_failing_is_503_not_an_empty_list(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """两路检索都失败 → **503**，不得写成「没有找到相关内容」（契约第 6 节）。

    消融：把这条改成降级返回空数组，用例必须失败——那会让使用者以为库里
    没有依据，而真相是检索坏了。
    """
    from campfire.modules.library.retrieval import RetrievalError

    async def _fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RetrievalError("两路检索均失败：向量路 ConnectionError、字面路 ConnectionError")

    monkeypatch.setattr(library_routes, "search", _fail)
    monkeypatch.setattr(library_routes, "browse", _fail)

    response = await client.get("/library/items", params={"library": "case", "query": "结构化活动"})

    assert response.status_code == 503
    assert response.json()["code"] == "retrieval_unavailable"
    # 失败文案不得被写成空态那句话（安全与如实呈现的要求）。
    assert "没有找到" not in response.json()["detail"]


async def test_single_path_failure_still_returns_200_with_degraded_flag(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, str]
) -> None:  # noqa: ANN001
    """单路失败 → **200** 且在结果内标注降级（契约第 6 节：照常呈现）。

    没有 `degraded_paths` 时调用方拿到 200 就无从知道结果不完整——那是契约
    第 6 节「单路失败在结果内标注」在 HTTP 层的落点。
    """
    from campfire.modules.library.retrieval import RetrievedItem, SearchOutcome

    async def _degraded(*args, **kwargs):  # noqa: ANN002, ANN003
        return SearchOutcome(
            items=[
                RetrievedItem(
                    item_id="it-degraded",
                    library="case",
                    title="降级条目",
                    snippet="片段",
                    source="虚构来源",
                    applicable_scope="不限",
                    status="internal",
                    locator="loc",
                    ranking={"fused_score": 0.1},
                )
            ],
            degraded_paths=("vector",),
        )

    monkeypatch.setattr(library_routes, "search", _degraded)

    response = await client.get("/library/items", params={"library": "case", "query": "结构化活动"})

    assert response.status_code == 200
    body = response.json()
    assert body["degraded_paths"] == ["vector"]
    assert [item["item_id"] for item in body["items"]] == ["it-degraded"]


# ---------------------------------------------------------------------------
# 装配与鉴权
# ---------------------------------------------------------------------------


async def test_routes_are_mounted_under_the_library_prefix() -> None:
    """资料库面路由挂在应用上（装配点回归）。用 OpenAPI 而不是遍历 `app.routes`：
    FastAPI 0.141 把 `include_router` 的结果收成单个 `_IncludedRouter`（实测）。"""
    import campfire.main as main_module

    paths = set(main_module.app.openapi()["paths"])
    assert {"/library/items", "/library/items/{item_id}"} <= paths


async def test_the_face_has_no_write_endpoints() -> None:
    """本面只有读端点（契约第 1 节：`RQ-KB-03`/`AC-29` 已定录入与撤下只经 CLI）。

    这是一条「不存在」的断言，因此必须有对照：同一份 OpenAPI 里确实存在其它面的
    写端点（`POST /profile/objects`、`DELETE /memory/episodes/{key}`），
    证明「查不到写方法」不是因为解析路径写错了。
    """
    import campfire.main as main_module

    schema = main_module.app.openapi()["paths"]
    library_methods = {method for path, ops in schema.items() if path.startswith("/library") for method in ops}
    assert library_methods == {"get"}

    other_writes = {
        method
        for path, ops in schema.items()
        if not path.startswith("/library")
        for method in ops
        if method in {"post", "patch", "delete", "put"}
    }
    assert other_writes, "对照失败：整份 schema 里都没有写方法，说明取值方式有问题"


async def test_endpoints_require_a_session() -> None:
    """无会话请求资料库面端点 → 401（`RQ-ACC-01`）。

    走真实 SDK，因此需要 SuperTokens core 与 API Key；缺任一跳过而不是假装通过。
    """
    import campfire.main as main_module
    from campfire.core.auth import check_auth_core
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.core.health import Status
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    settings = get_settings()
    if settings.supertokens_api_key is None:
        pytest.skip("未配置 SUPERTOKENS_API_KEY——需要 docker compose up -d supertokens")
    if (await check_auth_core(settings)).status is not Status.OK:
        pytest.skip("SuperTokens core 不可达——需要 docker compose up -d supertokens")

    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    # 必须先撤掉本文件的账号替换：那次替换正是这条用例要验的东西（依赖本身）。
    # 留着它会让请求通到处理函数并返回 200，而失败原因看起来像「端点没要求登录」。
    main_module.app.dependency_overrides.clear()

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        for path in ("/library/items", f"/library/items/{uuid.uuid4()}"):
            response = await async_client.get(path)
            assert response.status_code == 401, path


# ---------------------------------------------------------------------------
# 卡片文本还原（纯函数，不依赖库）
# ---------------------------------------------------------------------------


async def test_parse_card_fields_keeps_multiline_values_intact() -> None:
    """卡片文本还原按已知字段名起新行，因此多行值不会被拆成两半。

    消融：把解析改成「按换行无条件切」，本用例必须失败——那会把一个字段的值
    拆开、并把后半段丢掉（静默丢内容）。
    """
    text = "title：虚构卡片\nscenario：第一行\n第二行\nimmediate_action：步骤一\n步骤二\nevidence_level：INSTITUTIONAL"

    fields = library_routes._parse_card_fields(text)  # noqa: SLF001 —— 直接测该纯函数

    assert fields["scenario"] == "第一行\n第二行"
    assert fields["immediate_action"] == "步骤一\n步骤二"
    assert fields["evidence_level"] == "INSTITUTIONAL"


async def test_risk_class_derivation_follows_the_ingestion_rule() -> None:
    """`risk_class` 的派生判据与 `case_ingestion._card_is_high_risk` 同源。

    判据（公共案例库第 5 节 + `case_ingestion` 的 docstring）：`medical_criteria`
    或 `contraindications` 非空即高风险；`caution_notes` 单独出现不抬高整卡等级。
    """
    assert library_routes._card_risk_class({"caution_notes": "注意"}) == "low"  # noqa: SLF001
    assert library_routes._card_risk_class({"medical_criteria": "出现自伤即就医"}) == "high"  # noqa: SLF001
    assert library_routes._card_risk_class({"contraindications": "禁止身体约束"}) == "high"  # noqa: SLF001
    # `无` 与空白不算「有内容」（与 `_card_is_high_risk` 同判据）。
    assert library_routes._card_risk_class({"medical_criteria": "无"}) == "low"  # noqa: SLF001


async def test_session_id_parsing_falls_back_to_the_whole_string() -> None:
    """取不到 `session=` 词元时原样返回整串，不返回空串。

    空串会被读成「这条记忆没有来源」，而 `write_episode` 拒绝写入无来源的记忆
    ——因此空串只可能表示解析失败，那会把一次解析缺陷伪装成缺失的来源。
    """
    from campfire.modules.memory.routes import _session_id_from

    assert _session_id_from("session=sess-1 message=2") == "sess-1"
    assert _session_id_from("correction_of=abc") == "correction_of=abc"
    assert _session_id_from("") == ""


async def test_paginated_created_at_ordering_is_stable() -> None:
    """两个同 `created_at` 的条目也不丢行：浏览路的 `ORDER BY created_at DESC, id`。

    本用例是一项回归观测，不依赖库：断言的是排序键里带了 `id` 这一事实
    （若无第二排序键，分页时同时间戳的行顺序不稳定，翻页会漏）。
    用真实库验证会依赖主库历史语料，因此这里只核对 SQL 文本的形状。
    """
    import inspect

    source = inspect.getsource(__import__("campfire.modules.library.retrieval", fromlist=["browse"]).browse)
    assert "ORDER BY created_at DESC, id" in source


async def test_iso_datetime_round_trip_in_payload() -> None:
    """响应里的时间是带时区的 ISO 串（前端按它排序与分组，不能丢时区）。"""
    from campfire.modules.library.routes import LibraryItemPayload

    payload = LibraryItemPayload(
        item_id="x",
        library="case",
        title="t",
        snippet="s",
        source="src",
        applicable_scope="scope",
        status="internal",
        locator="loc",
        ranking={},
        interview_at=datetime(2098, 1, 1, tzinfo=timezone.utc),
    )

    dumped = payload.model_dump(mode="json")
    assert dumped["interview_at"].startswith("2098-01-01T00:00:00")
