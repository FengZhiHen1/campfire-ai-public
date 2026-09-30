"""集成测试：记忆面 HTTP 端点的形状、幂等与「空与失败可区分」（真实 FalkorDB + PostgreSQL）。

对应 ``docs/技术设计/面/profile/记忆面HTTP契约.md`` 第 3～6 节与
``docs/技术设计/technical-details/通用记忆.md`` 第 3、4、7 节。

    docker compose up -d postgres falkordb
    uv run pytest -m integration apps/api/tests/test_memory_routes_integration.py

## 为什么注入假模型客户端

实体抽取要调 TokenHub，而 `.env` 里的 `TOKENHUB_API_KEY` 是占位符（已登记
`TECH-02`）。本文件注入假 LLM 与假嵌入器，只验证 HTTP 形状、账本过滤与失败语义，
不验证抽取质量。因此本文件通过不代表真实抽取可用。

假客户端经 `get_shared_memory_graph` 的接缝注入：直接给
`campfire.modules.memory.graph._shared_graph` 赋值（模块级单例），收尾时清回
`None` 并关闭句柄——这与 `write_memory` / `read_memory` 工具走的是同一个句柄，
因此测的是生产路径上真正被用到的那一个。

## 本文件守住的判据

1. `episode_key` 暴露、`source_session_id` 从 `source_description` 解析出来。
2. 图库不可用 → **503**，不是 200 空数组（空与失败必须可区分，契约第 6 节）。
3. 删除幂等：实测重复执行两次（第一次 `newly_deleted=true`，第二次 `false`）。
4. 删除后两条读路径都不再返回（`AC-08`）：本面列表与 `read_timeline`。
5. 非法 `episode_key` → 422（形状校验在路由层，本包裁决 7）。
6. 纠正两步：正常路径返回 201 且 `superseded` / `new_episode_written` 都为真；
   写新失败时返回 **200** 与 `{superseded: true, new_episode_written: false}`
   （本包裁决 3 的中间态形状）——旧记忆已撤下、新记忆未写入。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from campfire.core.authz import set_authorizer
from campfire.core.config import EMBEDDING_DIM, get_settings
from campfire.core.db import session_scope
from campfire.modules.memory import routes as memory_routes
from campfire.modules.memory.graph import MemoryGraph, OrderedCrossEncoder
from campfire.modules.memory.identity import PendingId, derive_episode_uuid, to_account_id
from campfire.modules.memory.models import MemoryDeletionLedger
from campfire.modules.memory.store import read_timeline, write_episode
from campfire.modules.profile.authz import OwnerAuthorizer

from .conftest import connect_falkordb_or_skip

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ACCOUNT = "it_memory_routes_account"
_ACCOUNT_OTHER = "it_memory_routes_other"

#: 稳定的参照时间，避免用例依赖真实时钟。
_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """账本与删除过滤都要查本库；未配置时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现（本面不用端口，但同进程的其它面共享它，保持一致）。"""
    set_authorizer(OwnerAuthorizer(get_settings()))
    yield
    set_authorizer(None)


def _build_fake_graph() -> MemoryGraph:
    """装配一个使用假模型客户端的记忆图库句柄（不调真实供应商）。"""
    os.environ["no_proxy"] = "localhost,127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core.graphiti import Graphiti
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.llm_client.config import LLMConfig

    class _FakeEmbedder(EmbedderClient):
        async def create(self, input_data) -> list[float]:  # noqa: ANN001
            return [0.001] * EMBEDDING_DIM

    class _FakeLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(config=LLMConfig(api_key="test", model="fake"))

        async def _generate_response(
            self,
            messages=None,  # noqa: ANN001
            response_model=None,
            max_tokens=None,
            model_size=None,
            group_id=None,
            prompt_name=None,
            **kwargs,
        ):
            if response_model is not None:
                return {name: [] for name in response_model.model_fields}
            return {}

    driver, _client = connect_falkordb_or_skip()
    return MemoryGraph(
        graphiti=Graphiti(
            graph_driver=driver,
            llm_client=_FakeLLM(),
            embedder=_FakeEmbedder(),
            cross_encoder=OrderedCrossEncoder(),
            store_raw_episode_content=True,
        ),
        driver=driver,
    )


@pytest_asyncio.fixture
async def graph(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[MemoryGraph]:
    """把共享句柄换成假客户端的句柄，收尾清场并复位。

    清理两步都不可省：
    - 图库节点：`MATCH (n) DETACH DELETE n`（两个账号各自那张图）；
    - 删除账本：它的 `episode_key` 是全局唯一约束，与图库无关，
      不清会跨用例残留，让「刚写的两条」被上个用例记的删除挡掉。
    """
    import campfire.modules.memory.graph as graph_module

    handle = _build_fake_graph()
    monkeypatch.setattr(graph_module, "_shared_graph", handle)

    await _clear_ledger()
    try:
        yield handle
    finally:
        for account in (_ACCOUNT, _ACCOUNT_OTHER):
            scoped = handle.driver_for(account)
            await scoped.execute_query("MATCH (n) DETACH DELETE n")
        await _clear_ledger()
        await handle.aclose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """穿过完整应用路由的 ASGI 客户端（SDK 必须先初始化，见档案面同一说明）。"""
    import campfire.main as main_module
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(get_settings(), api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
    main_module.app.dependency_overrides.clear()


@pytest.fixture
def as_account() -> AsyncIterator[object]:
    """把登录态账号切换成给定值。"""
    import campfire.main as main_module

    def _set(account: str) -> None:
        main_module.app.dependency_overrides[memory_routes.current_account] = lambda: account

    _set(_ACCOUNT)
    yield _set
    main_module.app.dependency_overrides.clear()


async def _clear_ledger() -> None:
    async with session_scope(get_settings()) as session:
        await session.execute(
            delete(MemoryDeletionLedger).where(MemoryDeletionLedger.account_id.in_([_ACCOUNT, _ACCOUNT_OTHER]))
        )


async def _write(
    graph: MemoryGraph,
    *,
    content: str,
    occurred_at: datetime = _NOW,
    account: str = _ACCOUNT,
    pending: str | None = None,
    source: str | None = None,
) -> str:
    """写入一条片段并返回其 episode 标识。"""
    pending_id = pending or str(uuid.uuid4())
    episode_key = derive_episode_uuid(PendingId(pending_id))
    await write_episode(
        graph,
        to_account_id(account),
        episode_key,
        content=content,
        occurred_at=occurred_at,
        source_description=source or "session=it-session-1 message=1",
    )
    return str(episode_key)


# ---------------------------------------------------------------------------
# 查看（契约第 3 节）
# ---------------------------------------------------------------------------


async def test_list_returns_episode_key_and_source_session(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """列表暴露 `episode_key`，并把 `source_session_id` 从来源串里解析出来。

    `episode_key` 是本面的临界点：没有稳定标识就无法「列表 → 指认 → 删除」
    （契约第 3 节）。`source_session_id` 是契约的字段名，因此必须是一个标识
    而不是整条 `source_description`。
    """
    key = await _write(graph, content="我提过的事", source="session=sess-abc message=7 pending=x")

    response = await client.get("/memory/episodes")

    assert response.status_code == 200
    items = response.json()["items"]
    entry = next(item for item in items if item["episode_key"] == key)
    assert entry["content"] == "我提过的事"
    assert entry["source_session_id"] == "sess-abc"
    assert entry["occurred_at"].startswith("2026-09-30T12:00")


async def test_list_returns_newest_first(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """时间线按发生时间倒序（回看语义：「最近发生了什么」）。"""
    await _write(graph, content="旧的", occurred_at=_NOW - timedelta(days=2))
    await _write(graph, content="新的", occurred_at=_NOW)

    response = await client.get("/memory/episodes")

    contents = [item["content"] for item in response.json()["items"]]
    assert contents.index("新的") < contents.index("旧的")


async def test_list_filters_by_time_range_and_query(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """时间区间与关键词过滤真的生效（自建 Cypher，不是框架的「最近 N 条」）。"""
    await _write(graph, content="去超市的事", occurred_at=_NOW - timedelta(days=10))
    await _write(graph, content="去医院的事", occurred_at=_NOW)

    by_query = await client.get("/memory/episodes", params={"query": "超市"})
    by_time = await client.get("/memory/episodes", params={"since": (_NOW - timedelta(days=1)).isoformat()})

    assert [item["content"] for item in by_query.json()["items"]] == ["去超市的事"]
    assert [item["content"] for item in by_time.json()["items"]] == ["去医院的事"]


async def test_list_rejects_unparsable_time(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """时间无法解析或缺时区 → 422（不静默当成「没传」）。"""
    naive = await client.get("/memory/episodes", params={"since": "2026-09-30T12:00:00"})
    garbage = await client.get("/memory/episodes", params={"since": "not-a-time"})

    assert naive.status_code == 422
    assert garbage.status_code == 422


async def test_list_rejects_inverted_range(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """`since` 晚于 `until` → 422（区间非法，不静默忽略条件）。"""
    response = await client.get(
        "/memory/episodes",
        params={"since": _NOW.isoformat(), "until": (_NOW - timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 422


async def test_list_rejects_out_of_range_limit(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """`limit` 越界 → 422（记忆面上界 100，本包裁决 8）。"""
    assert (await client.get("/memory/episodes", params={"limit": 10_000})).status_code == 422
    assert (await client.get("/memory/episodes", params={"limit": 0})).status_code == 422


async def test_list_pagination_walks_the_whole_timeline(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """cursor 分页能翻完整个时间线且不重不漏。"""
    expected = {
        await _write(graph, content=f"片段 {index}", occurred_at=_NOW - timedelta(minutes=index)) for index in range(12)
    }

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # 上界防止游标不推进时无限循环（CORE-11）
        params: dict[str, object] = {"limit": 5}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get("/memory/episodes", params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["episode_key"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None
    assert len(seen) == len(set(seen)) == len(expected)
    assert set(seen) == expected


async def test_list_rejects_foreign_cursor(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """非法游标 → 422（边界显式，不静默当成第一页）。"""
    response = await client.get("/memory/episodes", params={"cursor": "nope"})

    assert response.status_code == 422


async def test_empty_timeline_is_200_with_empty_array(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """查询返回空不是失败：200 空数组，不标注降级（契约第 6 节）。"""
    response = await client.get("/memory/episodes")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_unavailable_graph_is_503_not_an_empty_list(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, as_account
) -> None:  # noqa: ANN001
    """图库不可用 → 503，不是 200 空数组（契约第 6 节「空与失败必须可区分」）。

    消融：把这条改成降级返回空数组，用例必须失败——那会把「读不到」呈现成
    「没有记忆」，使用者据此就会以为系统从未记住任何事。
    """
    import campfire.modules.memory.graph as graph_module
    from campfire.modules.memory.errors import MemoryUnavailableError

    class _BrokenGraph:
        def driver_for(self, account_id: str):  # noqa: ANN202
            raise MemoryUnavailableError("图库不可用", operation="test", cause="ConnectionError")

    monkeypatch.setattr(graph_module, "_shared_graph", _BrokenGraph())

    response = await client.get("/memory/episodes")

    assert response.status_code == 503
    assert response.json()["code"] == "memory_unavailable"
    # 复述连接串或凭据是被禁的；这里断言文案里没有出现异常类以外的内容无从机械验证，
    # 但至少要保证它不带 URL 形态（`://`）与凭据分隔符。
    assert "://" not in response.json()["detail"]


# ---------------------------------------------------------------------------
# 删除（契约第 4 节）
# ---------------------------------------------------------------------------


async def test_delete_is_idempotent_across_two_real_calls(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """删除幂等：实测重复执行两次，第二次 `newly_deleted` 为假且仍返回 200。"""
    key = await _write(graph, content="要删掉的")

    first = await client.delete(f"/memory/episodes/{key}")
    second = await client.delete(f"/memory/episodes/{key}")

    assert first.status_code == second.status_code == 200
    assert first.json() == {"episode_key": key, "newly_deleted": True, "reason": "user_request"}
    assert second.json() == {"episode_key": key, "newly_deleted": False, "reason": "user_request"}


async def test_delete_removes_the_episode_from_both_read_paths(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """删除后两条读路径都不再返回（`AC-08` 的验收对象）。

    「两条」= 本面的列表 + 用例层入口 `store.read_timeline`。后者是工具与应急
    预注入共用的入口，因此这一条同时覆盖了「工具侧也读不到」。
    """
    key = await _write(graph, content="删了就不该再看到")

    await client.delete(f"/memory/episodes/{key}")

    listing = await client.get("/memory/episodes")
    async with session_scope(get_settings()) as session:
        direct = await read_timeline(session, graph, to_account_id(_ACCOUNT))

    assert key not in [item["episode_key"] for item in listing.json()["items"]]
    assert key not in [str(episode.episode_uuid) for episode in direct]


async def test_delete_fails_on_malformed_key(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """非法 `episode_key` 形状 → 422（本包裁决 7：形状校验在路由层）。

    与「不存在」（200 幂等命中）分开：形状问题是载荷问题，重试同样的请求不会变好。
    用与记忆模块同源的校验函数（`identity.to_episode_key`），不另写一份规则。
    """
    for bad in ("not-a-uuid", "  3f2504e0-4f89-41d3-9a0c-0305e82c3300", "3f2504e0-4f89-41d3-9a0c-0305e82c330 0"):
        response = await client.delete(f"/memory/episodes/{bad}")
        assert response.status_code == 422, bad


async def test_delete_of_never_written_key_is_idempotent_200(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """删除一条从未写过的合法标识：账本照记且返回 200，不报错。

    这是契约第 4 节的语义落点：删除是「记入账本」，它的正确性不依赖图库里
    是否真有这条片段——因此对一条（可能已被物理清理的）历史标识重放删除请求
    同样成功，这正是重试安全所需要的。
    """
    never = str(uuid.uuid4())

    response = await client.delete(f"/memory/episodes/{never}")

    assert response.status_code == 200
    assert response.json() == {"episode_key": never, "newly_deleted": True, "reason": "user_request"}


# ---------------------------------------------------------------------------
# 纠正（契约第 5 节）
# ---------------------------------------------------------------------------


async def test_correct_supersedes_old_and_writes_new(client: httpx.AsyncClient, graph: MemoryGraph, as_account) -> None:  # noqa: ANN001
    """纠正正常路径：返回 201，旧记忆撤下、新记忆写入，两者都在响应里可见。"""
    old = await _write(graph, content="原来的说法")

    response = await client.post(
        f"/memory/episodes/{old}/correct",
        json={"occurred_at": _NOW.isoformat(), "content": "更正后的说法"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["superseded"] is True
    assert body["new_episode_written"] is True
    assert body["supersedes"] == old
    assert body["episode_key"] not in (None, old)

    listing = await client.get("/memory/episodes")
    keys = [item["episode_key"] for item in listing.json()["items"]]
    contents = {item["episode_key"]: item["content"] for item in listing.json()["items"]}
    assert old not in keys
    assert contents[body["episode_key"]] == "更正后的说法"


async def test_correct_reports_the_intermediate_state_when_writing_new_fails(
    client: httpx.AsyncClient, graph: MemoryGraph, monkeypatch: pytest.MonkeyPatch, as_account
) -> None:  # noqa: ANN001
    """撤下成功而写新失败 → **200** 与 `{superseded: true, new_episode_written: false}`。

    这是本包裁决 3 的对外承诺形状（契约第 5 节只写「明确的中间态」未定字段名）。
    消融：把它改成笼统 5xx 或笼统 201，用例必须失败——前者会让使用者以为纠正
    完全没生效（于是重复提交，而旧记忆早已撤下），后者会让他以为已经改好了。
    """
    old = await _write(graph, content="即将被撤下的旧说法")

    async def _fail_write(*args, **kwargs):  # noqa: ANN002, ANN003
        from campfire.modules.memory.errors import MemoryUnavailableError

        raise MemoryUnavailableError("图库写入失败", operation="write_episode", cause="ConnectionError")

    monkeypatch.setattr(memory_routes, "write_episode", _fail_write)

    response = await client.post(
        f"/memory/episodes/{old}/correct",
        json={"occurred_at": _NOW.isoformat(), "content": "写不进去的新说法"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"superseded": True, "new_episode_written": False, "episode_key": None, "supersedes": old}

    # 中间态必须真的是「旧记忆已撤下」——不是把两步都回滚了。
    listing = await client.get("/memory/episodes")
    assert old not in [item["episode_key"] for item in listing.json()["items"]]


async def test_correct_rejects_empty_content_before_superseding(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """空内容在入口就被拒（422），旧记忆不被撤下。

    顺序要求：若先撤下再校验内容，一次注定失败的请求会白撤掉一条有效记忆。
    """
    old = await _write(graph, content="不该被误撤下的旧说法")

    response = await client.post(
        f"/memory/episodes/{old}/correct",
        json={"occurred_at": _NOW.isoformat(), "content": "   "},
    )

    assert response.status_code == 422
    listing = await client.get("/memory/episodes")
    assert old in [item["episode_key"] for item in listing.json()["items"]]


async def test_correct_rejects_malformed_key_and_time(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """非法标识与非法时间各返回 422（载荷问题，不落到 404/500）。"""
    bad_key = await client.post(
        "/memory/episodes/not-a-uuid/correct",
        json={"occurred_at": _NOW.isoformat(), "content": "内容"},
    )
    bad_time = await client.post(
        f"/memory/episodes/{uuid.uuid4()}/correct",
        json={"occurred_at": "2026-09-30T12:00:00", "content": "内容"},
    )

    assert bad_key.status_code == 422
    assert bad_time.status_code == 422


async def test_correct_preserves_the_reason_recorded_by_correction(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """纠正撤下后，再收到删除请求时 `reason` 仍是账本里的 `correction`。

    契约第 4 节：`reason` 如实回报账本里的原原因——幂等命中不改变原记录。
    这是「审计读到的事实与账本一致」的断言。
    """
    old = await _write(graph, content="先纠正再删除")

    corrected = await client.post(
        f"/memory/episodes/{old}/correct",
        json={"occurred_at": _NOW.isoformat(), "content": "纠正后的内容"},
    )
    assert corrected.status_code == 201

    deleted = await client.delete(f"/memory/episodes/{old}")

    assert deleted.status_code == 200
    assert deleted.json()["newly_deleted"] is False
    assert deleted.json()["reason"] == "correction"


# ---------------------------------------------------------------------------
# 归属与装配
# ---------------------------------------------------------------------------


async def test_other_accounts_episode_is_not_visible_and_delete_is_404(
    client: httpx.AsyncClient, graph: MemoryGraph, as_account
) -> None:  # noqa: ANN001
    """记忆按账号分区：他人的片段不出现在列表里，删除他的 `episode_key` → 404。

    删除的 404 来自账本的跨账号守卫（`record_deletion` 的 fail-closed）：
    该 `episode_key` 已被别的账号记入账本时，本账号的删除不会生效，因此必须
    显式失败而不是静默幂等——静默幂等会让「删不掉」看起来像「删掉了」。
    """
    from campfire.modules.memory import deletion

    foreign = await _write(graph, content="别人的记忆", account=_ACCOUNT_OTHER)
    async with session_scope(get_settings()) as session:
        await deletion.delete_episode(session, account_id=to_account_id(_ACCOUNT_OTHER), episode_key=foreign)

    listing = await client.get("/memory/episodes")
    deleted = await client.delete(f"/memory/episodes/{foreign}")

    assert foreign not in [item["episode_key"] for item in listing.json()["items"]]
    assert deleted.status_code == 404
    assert deleted.json()["code"] == "not_found"


async def test_routes_are_mounted_under_the_memory_prefix() -> None:
    """记忆面路由挂在应用上（装配点回归）。用 OpenAPI 而不是遍历 `app.routes`：
    FastAPI 0.141 把 `include_router` 的结果收成单个 `_IncludedRouter`（实测）。"""
    import campfire.main as main_module

    paths = set(main_module.app.openapi()["paths"])
    assert {"/memory/episodes", "/memory/episodes/{episode_key}", "/memory/episodes/{episode_key}/correct"} <= paths


async def test_endpoints_require_a_session() -> None:
    """无会话请求记忆面端点 → 401（`RQ-ACC-01`；记忆面无一例外必须登录）。

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

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        for method, path in (
            ("GET", "/memory/episodes"),
            ("DELETE", "/memory/episodes/3f2504e0-4f89-41d3-9a0c-0305e82c3303"),
            ("POST", "/memory/episodes/3f2504e0-4f89-41d3-9a0c-0305e82c3303/correct"),
        ):
            response = await async_client.request(method, path, json={"occurred_at": "x", "content": "y"})
            assert response.status_code == 401, f"{method} {path} 未要求登录"
