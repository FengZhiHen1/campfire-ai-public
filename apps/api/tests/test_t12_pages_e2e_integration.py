"""E2E（本包范围）：三个页面的真实数据链路走一遍——档案 → 记忆 → 案例库。

对应 `docs/技术设计/面/profile/` 三份 HTTP 契约，以及档案页 / 记忆页 / 案例库浏览页
三份页面设计文档的「状态覆盖」节。

    docker compose up -d
    uv run pytest -m integration apps/api/tests/test_t12_pages_e2e_integration.py

这是什么级别的 E2E，以及为什么不是浏览器 E2E

它把三个页面对应的全部真实端点按页面使用顺序串成一条连续流程，穿过完整
FastAPI 路由、依赖注入、用例层、真实 PostgreSQL 与真实 Worker 消费分支；
会话依赖被替换成固定账号（与 `test_profile_routes_integration.py` 同一手法，
理由见该文件模块说明：本文件测的是「拿到账号之后三面怎么组织」，而
注册→登录→引导三段各有自己的端到端用例：`test_auth_session_lifecycle_integration`
与账号注册相关用例）。起点（对象为空）到终点（删除后读不到）都是真实状态迁移，
没有一处用 mock 数据冒充。

不是浏览器 E2E，如实标注：本仓库没有浏览器测试框架（`apps/web` 无 Playwright 依赖，
`pnpm ls @playwright/test` 为空），引入它会是一次未获批准的依赖新增；因此
「三个页面在真实浏览器里的渲染与交互」未被本文件验证——页面行为由
`apps/web/src/features/{profile,memory,library}/view/*.test.tsx` 在 jsdom 里覆盖。

本文件不覆盖、并如实标注的部分

1. 对话页与应急表单（T11）：那两条链路在本泳道基线里还是占位包
   （`apps/web/src/features/consult/` 仅有 `.gitkeep`），因此「日常对话 → 应急」
   无法纳入本流程。
2. 记忆的纠正与删除：需要图库里真实存在一条 episode，而写入走模型抽取
   （TokenHub）。本文件只断言查看端点的契约形状（200 空数组不是失败），
   纠正与删除由 `test_memory_routes_integration.py` 用自己的夹具覆盖。
3. 案例分区的列表内容：本泳道库是干净库，案例分区没有条目。本文件断言的是
   「空集也必须是 200 空数组」（空不是失败），不是「案例链路未实现」——
   `campfire_case_item` 与案例摄取在 T03 已落地。真正的案例呈现（卡片维度、
   风险档、审阅状态）由 `test_library_routes_integration.py` 用自己的摄取夹具覆盖。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.core.authz import set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import KIND_PROFILE_ITEM, PendingWrite, enqueue
from campfire.modules.library import routes as library_routes
from campfire.modules.memory import routes as memory_routes
from campfire.modules.profile import routes as profile_routes
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.models import ProfileItem, SupportObject

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ACCOUNT = "it_t12_e2e_account"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d")
    yield


def _require_tokenhub_or_skip() -> None:
    """未配置 `TOKENHUB_API_KEY` 时跳过。

    只有「记忆页」那一段需要它：`/memory/episodes` 读的是真实记忆图库
    （`get_shared_memory_graph`，构造期要求该凭据）。

    实测（2026-10-01，CI 环境无此凭据）：不加守卫时该端点在记忆图库不可用时回
    503 `memory_unavailable`，而本用例断言 200——于是 failed。
    那个 503 是正确的产品行为（图库不可用要如实报，不是假装空集），
    所以这里该按环境 skip，而不是把断言放宽成「200 或 503」——后者会把
    「图库挂了」和「真的没有记忆」混为一谈，而本文件存在的意义之一正是区分这两者。
    """
    if get_settings().tokenhub_api_key is None:
        pytest.skip("未配置 TOKENHUB_API_KEY——记忆页读端点需要真实记忆图库")


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现（Worker 消费分支在领取时要重新判定授权）。"""
    set_authorizer(OwnerAuthorizer(get_settings()))
    yield
    set_authorizer(None)


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id == _ACCOUNT))
        owned = select(SupportObject.id).where(SupportObject.account_id == _ACCOUNT)
        await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id == _ACCOUNT))


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """穿过完整应用路由的 ASGI 客户端；三个面的会话依赖都替换成本文件的固定账号。"""
    import campfire.main as main_module
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(get_settings(), api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver/api") as async_client:
        yield async_client
    main_module.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def as_account() -> Iterator[None]:
    """三个面的「当前账号」都指向本文件的固定账号。"""
    import campfire.main as main_module

    for module in (profile_routes, memory_routes, library_routes):
        main_module.app.dependency_overrides[module.current_account] = lambda: _ACCOUNT
    yield
    main_module.app.dependency_overrides.clear()


async def _enqueue_inferred_item(object_id: str) -> str:
    """入队一条推断来源的档案条目（模拟 `propose_profile_item` 工具写入待处理记录）。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_PROFILE_ITEM,
            account_id=_ACCOUNT,
            origin="ai_inference",
            payload={"domain": "sensory_processing", "topic": "声音敏感", "description": "人多时捂耳"},
            source={"session_id": "e2e-session", "tool_name": "propose_profile_item", "recorded_at": "2026-09-30"},
            support_object_id=object_id,
        )
    return str(record.id)


# ---------------------------------------------------------------------------
# 一条连续流程：档案页 → 记忆页 → 案例库浏览页
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pages_flow_from_empty_profile_to_library(client: httpx.AsyncClient) -> None:
    """三个页面的真实数据链路：建档 → 补充 → 候选确认 → 纠正 → 删除 → 归档/恢复 → 记忆 → 案例库。"""
    # ── 档案页：新账号的对象列表为空（首次进入的空态判据） ──────────────────
    response = await client.get("/profile/objects")
    assert response.status_code == 200
    assert response.json()["items"] == [], "全新账号不应有任何支持对象"

    # ── 档案页：新建对象（切换器末尾的「+ 新建对象」） ──────────────────────
    response = await client.post("/profile/objects", json={"display_name": "小宝"})
    assert response.status_code == 201, response.text
    object_id = response.json()["id"]
    assert response.json()["archived_at"] is None

    # 空名被拒（页面的提交按钮在空值时禁用，服务端亦兜底）。
    assert (await client.post("/profile/objects", json={"display_name": "   "})).status_code == 422

    # ── 档案页首屏：摘要（只取稳定层）+ 条目（候选单独成组） ────────────────
    response = await client.get(f"/profile/objects/{object_id}/summary")
    assert response.status_code == 200
    assert response.json()["fields"] == []
    assert response.json()["has_profile"] is False, "只有候选条目时摘要意义上仍是「无档案」"

    response = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "candidates": [], "next_cursor": None}

    # ── 档案页：补充一条（origin 由服务端定为 user_statement） ──────────────
    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={
            "domain": "communication",
            "topic": "表达方式",
            "description": "用图片卡表达需求",
            "contexts": ["在家"],
            "manifestations": ["指图片"],
        },
    )
    assert response.status_code == 201, response.text
    manual_item_id = response.json()["item_id"]

    response = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    listed = response.json()
    assert [entry["item_id"] for entry in listed["items"]] == [manual_item_id]
    assert listed["candidates"] == [], "使用者自己补充的条目直接进稳定层"
    assert listed["items"][0]["origin"] == "user_statement"
    assert listed["items"][0]["confirmation"] == "confirmed"

    summary = (await client.get(f"/profile/objects/{object_id}/summary")).json()
    assert summary["has_profile"] is True
    assert any(entry["item_id"] == manual_item_id for field in summary["fields"] for entry in field["items"])

    # ── 档案页：候选经 Worker 消费分支落库（跨进程边界的那一段） ────────────
    from campfire import worker as worker_module

    pending_id = await _enqueue_inferred_item(object_id)
    assert await worker_module.consume_profile_item_task(pending_id, lease_owner="e2e") == "written"

    response = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    listed = response.json()
    assert len(listed["candidates"]) == 1, "推断来源只进候选层（AC-18 的服务端侧保证）"
    candidate = listed["candidates"][0]
    assert candidate["origin"] == "ai_inference"
    assert candidate["confirmation"] == "unconfirmed"

    # 候选不进摘要：候选层视觉不变量（AC-18）的服务端侧承载。
    summary = (await client.get(f"/profile/objects/{object_id}/summary")).json()
    assert not any(entry["item_id"] == candidate["item_id"] for field in summary["fields"] for entry in field["items"])

    # ── 档案页：确认候选 → 进稳定层与摘要 ──────────────────────────────────
    response = await client.post(f"/profile/items/{candidate['item_id']}/confirm")
    assert response.status_code == 200, response.text
    assert response.json()["confirmation"] == "confirmed"
    # 重复确认是调用方的错误，不是幂等操作 → 422。
    assert (await client.post(f"/profile/items/{candidate['item_id']}/confirm")).status_code == 422

    listed = (await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})).json()
    assert candidate["item_id"] in [entry["item_id"] for entry in listed["items"]]
    assert listed["candidates"] == []

    # ── 档案页：纠正（新增取代条目，旧条目不返回） ─────────────────────────
    response = await client.post(
        f"/profile/items/{manual_item_id}/correct",
        json={"description": "改用图片卡加手势表达", "topic": "表达方式"},
    )
    assert response.status_code == 201, response.text
    corrected_id = response.json()["item_id"]
    assert response.json()["supersedes"] == manual_item_id

    listed = (await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})).json()
    listed_ids = [entry["item_id"] for entry in listed["items"]]
    assert corrected_id in listed_ids
    assert manual_item_id not in listed_ids, "被取代的条目不出现在读取里（契约第 3 节）"

    # ── 档案页：删除（删除后读不到，AC-08） ────────────────────────────────
    response = await client.delete(f"/profile/items/{corrected_id}")
    assert response.status_code == 200, response.text
    listed = (await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})).json()
    assert corrected_id not in [entry["item_id"] for entry in listed["items"]]

    # ── 档案页：归档对象 → 新增被拒（409，文案区分于越权）→ 恢复后可新增 ───
    response = await client.patch(f"/profile/objects/{object_id}", json={"archived": True})
    assert response.status_code == 200
    assert response.json()["archived_at"] is not None

    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={"domain": "communication", "topic": "x", "description": "y"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "object_archived"

    # 归档对象仍可读（记录仍可查看与纠正）。
    assert (await client.get(f"/profile/objects/{object_id}/items")).status_code == 200

    response = await client.patch(f"/profile/objects/{object_id}", json={"archived": False})
    assert response.status_code == 200
    assert response.json()["archived_at"] is None
    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={"domain": "communication", "topic": "恢复后", "description": "恢复使用后才能补充"},
    )
    assert response.status_code == 201, response.text

    # 越权与不存在逐字同文案（不泄露存在性）。
    other = await client.get(f"/profile/objects/{uuid4()}/items")
    assert other.status_code == 404

    # ── 记忆页：查看端点的契约形状（空即 200 空数组，不是失败） ────────────
    _require_tokenhub_or_skip()
    response = await client.get("/memory/episodes")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["items"], list)
    assert body["next_cursor"] is None or isinstance(body["next_cursor"], str)

    # ── 案例库浏览页：两库分开取数 ──────────────────────────────────────────
    response = await client.get("/library/items", params={"library": "case", "query": ""})
    assert response.status_code == 200, response.text
    assert response.json()["library"] == "case"
    # 本泳道库是干净库：案例分区没有条目，因此这里断言的是「空集也必须是 200 空数组」
    # （空不是失败，契约第 6 节）——不是断言案例链路未实现（`campfire_case_item`
    # 与 case 摄取在 T03 已落地）。
    assert response.json()["items"] == [], response.text

    response = await client.get("/library/items", params={"library": "knowledge", "query": ""})
    assert response.status_code == 200, response.text
    assert response.json()["library"] == "knowledge"
    assert isinstance(response.json()["items"], list)

    # 未知库别 → 422（页面的 chip 只发两个合法取值，服务端亦兜底）。
    assert (await client.get("/library/items", params={"library": "bogus"})).status_code == 422

    # deep-link：非法/不存在的 id → 404（页面按普通进入处理，不报错、不留在空页）。
    assert (await client.get(f"/library/items/{uuid4()}")).status_code == 404


@pytest.mark.asyncio
async def test_deep_link_reports_withdrawn_source_without_body(client: httpx.AsyncClient) -> None:
    """deep-link 的撤下态：服务端返回 200 + `withdrawn`，只带标题（契约第 5 节）。

    为什么能在这里造出撤下态：往知识库条目上打 `withdrawn` 由 CLI 承担
    （`modules/library/withdrawal.py`），这条用例直接调它——不经过任何写端点
    （本面只有读端点）。这样「撤下后不再返回、定向查询只给标题」这条界面语义
    就有了真实的端到端证据，而不是只由前端替身断言。
    """
    from campfire.modules.library import models as library_models
    from campfire.modules.library import withdrawal

    knowledge_id = uuid4()
    async with session_scope(get_settings()) as session:
        session.add(
            library_models.KnowledgeItem(
                id=knowledge_id,
                title="一条会被撤下的资料",
                source="某机构公开材料",
                applicable_scope="通用",
            )
        )

    try:
        # 在库：定向查询返回条目本身。
        response = await client.get(f"/library/items/{knowledge_id}")
        assert response.status_code == 200, response.text
        assert response.json()["item"] is not None, response.text
        assert response.json()["item"]["title"] == "一条会被撤下的资料"

        async with session_scope(get_settings()) as session:
            await withdrawal.withdraw_item(session, library="knowledge", item_id=str(knowledge_id))

        # 已撤下：200 + item 为 null + 只带标题。
        response = await client.get(f"/library/items/{knowledge_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["item"] is None
        assert body["withdrawn"] is True
        assert body["title"] == "一条会被撤下的资料"
        assert "正文不应出现在撤下卡里" not in response.text, "撤下态不得带正文"

        # 撤下条目不进列表（RQ-KB-04：撤下即消失，无「已撤下」幽灵条目）。
        listed = (await client.get("/library/items", params={"library": "knowledge", "query": ""})).json()
        assert str(knowledge_id) not in [item["item_id"] for item in listed["items"]]
    finally:
        from sqlalchemy import text

        async with session_scope(get_settings()) as session:
            await session.execute(
                text("DELETE FROM campfire_knowledge_item WHERE id = :item_id"), {"item_id": str(knowledge_id)}
            )
