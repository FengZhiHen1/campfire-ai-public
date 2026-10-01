"""集成测试：档案面 HTTP 端点的形状、状态码与失败语义（真实 PostgreSQL）。

对应 ``docs/技术设计/面/profile/档案面HTTP契约.md`` 第 2～6 节与
``docs/技术设计/technical-details/个性化档案.md`` 第 2～5 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_routes_integration.py

## 为什么走 ASGI 直连而不是起服务器

`httpx.ASGITransport` 让请求穿过完整的 FastAPI 路由与依赖注入（含错误码映射），
但不占端口、不需要网络。会话依赖被显式替换（`app.dependency_overrides`）：
本文件测的是「拿到账号之后路由怎么组织」，而 `require_session` 的撤销语义有
自己的端到端用例（`test_auth_session_lifecycle_integration`）——在每条业务用例里
重复签署真会话只会让失败原因变得难查。401 那一条单独用真实 SDK 验证（见末节）。

## 本文件守住的判据

1. 越权与不存在逐字同文案（不泄露存在性）；归档上的新增文案区分（409）。
2. 空名 422、`limit` 越界 422、无字段的 PATCH 422、重复确认 422、纠正无变更 422、
   对已被取代的条目再次纠正 422、对已被取代的条目确认/否定 422。
3. 删除的越权与不存在一律 404 且响应体逐字相同（裁决 1）；删除成功的响应为
   `already: false`。
4. 删掉的条目不再出现在读取里（`AC-08`）。
5. 候选层单独成组、不进摘要（`AC-18`）；归档对象上 confirm 返回 200（可读可纠）。
6. 补充条目的 `origin` 由服务端定为 `user_statement`；纠正同样重绑生成方式
   ——纠正一条候选不会造出「推断被写成已确认」的条目。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.core.authz import OBJECT_ARCHIVED_MESSAGE, OBJECT_NOT_ACCESSIBLE_MESSAGE, set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import PendingWrite
from campfire.modules.profile import repository as repo
from campfire.modules.profile import routes as profile_routes
from campfire.modules.profile import service
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.models import ProfileItem, SupportObject

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ACCOUNT = "it_profile_routes_account"
_ACCOUNT_OTHER = "it_profile_routes_other"

#: 稳定的来源定位：`AC-07` 要求条目带来源，而 `source` 是 `propose_item` 的必填。
_SOURCE = {"session_id": "it-session", "message_ref": "1", "tool_name": "it-test", "recorded_at": "2026-09-30"}


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现；结束清除（端口默认 fail-closed，未注入即拒绝）。"""
    set_authorizer(OwnerAuthorizer(get_settings()))
    yield
    set_authorizer(None)


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件两个账号的数据（顺序：待处理记录 → 条目 → 对象，外键要求）。"""
    await _clear()
    yield
    await _clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """穿过完整应用路由的 ASGI 客户端；会话依赖替换成本文件的固定账号。

    SDK 必须显式初始化：`lifespan` 在 `ASGITransport` 下不会自动运行，而
    SuperTokens 的中间件在每个请求上先调 `Supertokens.get_instance()`
    （实测：未初始化即抛 `GeneralError: Initialisation not done`）——中间件在
    路由与依赖之前执行，因此这一步无法靠替换依赖绕开。

    `init_supertokens` 是幂等的（SDK 内部只在 `__instance is None` 时构造），
    且这不发起网络请求：真正的会话校验才需要 core，而本文件的会话依赖已被替换。
    """
    import campfire.main as main_module
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(get_settings(), api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
    main_module.app.dependency_overrides.clear()


@pytest.fixture
def as_account() -> Iterator[object]:
    """把「当前账号」切换成给定值，返回设置函数。

    用依赖覆盖而不是伪造 cookie：本文件关心的不是「怎么证明你是谁」，
    而是「证明之后路由是否只让你碰自己的东西」。
    """
    import campfire.main as main_module

    def _set(account: str) -> None:
        main_module.app.dependency_overrides[profile_routes.current_account] = lambda: account

    _set(_ACCOUNT)
    yield _set
    main_module.app.dependency_overrides.clear()


async def _clear() -> None:
    accounts = (_ACCOUNT, _ACCOUNT_OTHER)
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id.in_(accounts)))
        owned = select(SupportObject.id).where(SupportObject.account_id.in_(accounts))
        await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id.in_(accounts)))


async def _new_object(account: str = _ACCOUNT, name: str = "小宝") -> str:
    """建一个对象并返回标识。"""
    async with session_scope(get_settings()) as session:
        record = await service.create_object(session, account_id=account, display_name=name)
    return str(record.id)


async def _propose(
    object_id: str,
    *,
    origin: str,
    description: str = "可观察的描述",
    domain: str = "communication",
    topic: str = "表达方式",
    account: str = _ACCOUNT,
) -> str:
    """提交一条条目并返回标识。"""
    async with session_scope(get_settings()) as session:
        item = await service.propose_item(
            session,
            account_id=account,
            support_object_id=object_id,
            domain=domain,
            topic=topic,
            description=description,
            origin=origin,
            source=dict(_SOURCE),
        )
    return str(item.item_id)


async def _superseded_unconfirmed_candidate(client: httpx.AsyncClient, object_id: str) -> tuple[str, str]:
    """经 HTTP 造一条「已被取代 + 未确认」的条目，返回 `(旧条目, 新条目)`。

    提交 `ai_inference` 候选（未确认）后用纠正端点取代它：旧条目转 `historical`
    并写上 `superseded_by`，`confirmation` 仍是 `unconfirmed`。
    """
    candidate = await _propose(object_id, origin="ai_inference", description="被取代的推断")
    corrected = await client.post(f"/profile/items/{candidate}/correct", json={"description": "使用者改写的描述"})
    assert corrected.status_code == 201, corrected.text
    return candidate, corrected.json()["item_id"]


# ---------------------------------------------------------------------------
# 支持对象（契约第 2 节）
# ---------------------------------------------------------------------------


async def test_list_objects_includes_archived_ones(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """列表含已归档对象——前端据此在切换器里标「已归档」（契约第 2.1 节）。"""
    keep = await _new_object(name="在用")
    gone = await _new_object(name="已归档")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=gone)

    response = await client.get("/profile/objects")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[keep]["archived_at"] is None
    assert items[gone]["archived_at"] is not None


async def test_create_object_returns_201_with_login_owner(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """创建返回 201 与对象形状；属主取登录态（请求体里没有账号字段）。"""
    response = await client.post("/profile/objects", json={"display_name": "新建对象"})

    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "新建对象"
    assert body["archived_at"] is None
    assert isinstance(body["id"], str)

    response = await client.get("/profile/objects")
    assert [item["id"] for item in response.json()["items"]] == [body["id"]]


async def test_create_object_with_blank_name_is_422(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """空名（去空白后为空）→ 422（契约第 2.1 节）。"""
    response = await client.post("/profile/objects", json={"display_name": "   "})

    assert response.status_code == 422


async def test_patch_object_archive_and_restore_are_idempotent(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """归档与恢复幂等：重复归档不报错、重复恢复保持为空（契约第 2.2 节）。"""
    object_id = await _new_object()

    first = await client.patch(f"/profile/objects/{object_id}", json={"archived": True})
    second = await client.patch(f"/profile/objects/{object_id}", json={"archived": True})
    assert first.status_code == second.status_code == 200
    assert first.json()["archived_at"] is not None
    assert second.json()["archived_at"] is not None

    third = await client.patch(f"/profile/objects/{object_id}", json={"archived": False})
    fourth = await client.patch(f"/profile/objects/{object_id}", json={"archived": False})
    assert third.status_code == fourth.status_code == 200
    assert third.json()["archived_at"] is None
    assert fourth.json()["archived_at"] is None


async def test_patch_object_renames_active_object(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """改名返回新名字；改名不触碰档案（本条只钉对外形状）。"""
    object_id = await _new_object(name="旧名")

    response = await client.patch(f"/profile/objects/{object_id}", json={"display_name": "新名"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "新名"


async def test_patch_object_without_any_field_is_422(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """两个字段都不给 → 422：静默 200 会让调用方以为改名成功了。"""
    object_id = await _new_object()

    response = await client.patch(f"/profile/objects/{object_id}", json={})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 越权与不存在（契约第 1、6 节）
# ---------------------------------------------------------------------------


async def test_other_accounts_object_is_404_with_the_same_body_as_missing(
    client: httpx.AsyncClient, as_account
) -> None:  # noqa: ANN001
    """越权与不存在的响应体逐字相同（不泄露存在性）。

    消融：让两者文案或 code 区分开，本断言必须失败。
    """
    foreign = await _new_object(account=_ACCOUNT_OTHER)

    trespassing = await client.get(f"/profile/objects/{foreign}/summary")
    missing = await client.get("/profile/objects/3f2504e0-4f89-41d3-9a0c-0305e82c3300/summary")

    assert trespassing.status_code == missing.status_code == 404
    assert trespassing.json() == missing.json()
    assert trespassing.json()["detail"] == OBJECT_NOT_ACCESSIBLE_MESSAGE


async def test_archived_object_rejects_new_items_with_a_distinct_409(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """归档对象上新增 → 409 `object_archived`，且文案区分于越权（契约第 1 节）。

    归档文案不是「区分了不该区分的二者」：属主自己的对象，使用者需要知道
    原因才能去恢复。
    """
    object_id = await _new_object()
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={"domain": "communication", "topic": "补充", "description": "归档后补充"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "object_archived"
    assert response.json()["detail"] == OBJECT_ARCHIVED_MESSAGE
    assert response.json()["detail"] != OBJECT_NOT_ACCESSIBLE_MESSAGE


async def test_archived_object_still_readable_and_correctable(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """归档对象可读、条目可确认与纠正（支持对象第 4 节：归档对象可读可纠）。

    对抗用例：归档语义很容易被实现成「一概拒绝」，那会让使用者无法处理
    已归档对象里的错误内容。
    """
    object_id = await _new_object()
    candidate = await _propose(object_id, origin="ai_inference")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    summary = await client.get(f"/profile/objects/{object_id}/summary")
    confirmed = await client.post(f"/profile/items/{candidate}/confirm")

    assert summary.status_code == 200
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmation"] == "confirmed"


# ---------------------------------------------------------------------------
# 读取（契约第 3 节）
# ---------------------------------------------------------------------------


async def test_summary_contains_only_stable_layer_entries(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """摘要只取稳定层；只有候选条目的对象返回「无档案」（`AC-18`、个性化档案第 10 节）。"""
    object_id = await _new_object()
    await _propose(object_id, origin="user_statement", description="稳定层内容")
    await _propose(object_id, origin="ai_inference", description="候选层内容")

    response = await client.get(f"/profile/objects/{object_id}/summary")

    assert response.status_code == 200
    body = response.json()
    texts = [entry["text"] for field in body["fields"] for entry in field["items"]]
    assert "稳定层内容" in texts
    assert "候选层内容" not in texts
    assert body["has_profile"] is True

    candidate_only = await _new_object(name="只有候选")
    await _propose(candidate_only, origin="system_observation", description="只有候选内容")
    empty = await client.get(f"/profile/objects/{candidate_only}/summary")

    assert empty.status_code == 200
    assert empty.json() == {"fields": [], "has_profile": False}


async def test_summary_entries_carry_origin_and_confirmed_time(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """摘要每条带 `item_id`、`origin` 与 `last_confirmed_at`（契约第 3 节）。"""
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="guardian_observation", description="观察内容")

    response = await client.get(f"/profile/objects/{object_id}/summary")

    entries = [entry for field in response.json()["fields"] for entry in field["items"]]
    entry = next(item for item in entries if item["item_id"] == item_id)
    assert entry["origin"] == "guardian_observation"
    assert entry["last_confirmed_at"] is not None
    assert entry["freshness"] == "current"


async def test_items_returns_candidates_in_a_separate_group(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """候选层单独成组（`AC-18` 的服务端侧保证），且含三项状态字段。"""
    object_id = await _new_object()
    stable = await _propose(object_id, origin="user_statement")
    candidate = await _propose(object_id, origin="ai_inference")

    response = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})

    assert response.status_code == 200
    body = response.json()
    assert [item["item_id"] for item in body["items"]] == [stable]
    assert [item["item_id"] for item in body["candidates"]] == [candidate]
    for item in [*body["items"], *body["candidates"]]:
        assert {"origin", "confirmation", "freshness"} <= set(item)


async def test_items_without_include_candidates_omits_candidates(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """默认不返回候选，也不混进 `items`。"""
    object_id = await _new_object()
    await _propose(object_id, origin="ai_inference")

    response = await client.get(f"/profile/objects/{object_id}/items")

    body = response.json()
    assert body["items"] == []
    assert body["candidates"] == []


# ---------------------------------------------------------------------------
# 历史条目（已被取代）的 opt-in 读通道
# ---------------------------------------------------------------------------


async def _correct(client: httpx.AsyncClient, item_id: str, description: str) -> str:
    """走 HTTP 纠正一条条目并返回新条目标识。"""
    response = await client.post(f"/profile/items/{item_id}/correct", json={"description": description})
    assert response.status_code == 201, response.text
    return response.json()["item_id"]


async def test_items_without_include_superseded_omits_the_superseded_history(  # noqa: ANN001
    client: httpx.AsyncClient, as_account
) -> None:
    """默认（不传 `include_superseded`）历史条目不出现在任何一组——与改动前逐条相同。

    两种读法都断言：默认读法，以及只开候选层的读法——历史条目不是候选，
    不该被候选开关带出来。
    """
    object_id = await _new_object()
    old = await _propose(object_id, origin="user_statement", description="旧描述")
    new = await _correct(client, old, "新描述")

    default = (await client.get(f"/profile/objects/{object_id}/items")).json()
    candidates_only = (
        await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    ).json()

    for body in (default, candidates_only):
        assert [item["item_id"] for item in body["items"]] == [new]
        assert body["candidates"] == []
        assert old not in [item["item_id"] for item in [*body["items"], *body["candidates"]]]


async def test_include_superseded_returns_the_history_with_both_pointers(  # noqa: ANN001
    client: httpx.AsyncClient, as_account
) -> None:
    """`include_superseded=true` → 已被取代的旧条目随 `items` 返回，互指完整。

    四件事：① 旧条目出现且 `freshness = historical`；② 互指两侧都在
    （旧条目 `superseded_by` 指向新条目、新条目 `supersedes` 指回旧条目）；
    ③ 它进 `items` 而不进 `candidates`——档案页第 62 行的「已更正」标落在完整条目区，
    候选组是「待确认」，已被取代的条目不属于那里；
    ④ 排序照既有规则（首次记录时间倒序）：新条目后写，因此排在旧条目之前。
    """
    object_id = await _new_object()
    old = await _propose(object_id, origin="user_statement", description="旧描述")
    new = await _correct(client, old, "新描述")

    body = (await client.get(f"/profile/objects/{object_id}/items", params={"include_superseded": "true"})).json()

    assert [item["item_id"] for item in body["items"]] == [new, old], "同一排序规则下的插入位置"
    assert body["candidates"] == []
    history = body["items"][1]
    assert history["freshness"] == "historical"
    assert history["description"] == "旧描述"
    assert history["superseded_by"] == new
    assert body["items"][0]["supersedes"] == old


async def test_include_superseded_keeps_unconfirmed_history_in_candidates(  # noqa: ANN001
    client: httpx.AsyncClient, as_account
) -> None:
    """被取代的候选仍归 `candidates`（`AC-18` 的服务端侧保证，端到端断言）。

    纠正一条未确认的推断：新条目进 `items`，旧条目（历史 + 未确认）进 `candidates`
    ——它仍是未确认的系统推断，不得因为「已被取代」而被当成完整条目区的内容。
    同时断言只开历史回看（`include_candidates=false`）时它根本不出现：缺省路径不变，
    候选组也不会在没请求候选时凭空多出内容。
    """
    object_id = await _new_object()
    old = await _propose(object_id, origin="ai_inference", description="被取代的推断")
    new = await _correct(client, old, "使用者改写的描述")

    body = (
        await client.get(
            f"/profile/objects/{object_id}/items",
            params={"include_superseded": "true", "include_candidates": "true"},
        )
    ).json()
    assert [item["item_id"] for item in body["items"]] == [new]
    assert [item["item_id"] for item in body["candidates"]] == [old]
    assert body["candidates"][0]["freshness"] == "historical"
    assert body["candidates"][0]["confirmation"] == "unconfirmed"

    stable_only = (
        await client.get(f"/profile/objects/{object_id}/items", params={"include_superseded": "true"})
    ).json()
    assert [item["item_id"] for item in stable_only["items"]] == [new]
    assert stable_only["candidates"] == [], "没开候选开关时候选组必须为空"


async def test_include_superseded_still_excludes_rejected_items(  # noqa: ANN001
    client: httpx.AsyncClient, as_account
) -> None:
    """`include_superseded=true` 不放开 `rejected`——否定过的内容不得回看。

    用最强的形态：一条既被否定、又被取代的条目（先否定一条候选，再纠正它；
    纠正把它置 `historical` 并写 `superseded_by`）。它同时命中两个开关的放宽条件，
    因此「开闸开过头、连被否定的内容一起放」的实现在此变红。
    同时留一条对照（同一对象里被取代的稳定条目必须出现），证明本用例不是因为
    整个闸没开才通过。
    """
    object_id = await _new_object()
    rejected = await _propose(object_id, origin="ai_inference", description="被否定的推断")
    rejected_response = await client.post(f"/profile/items/{rejected}/reject")
    assert rejected_response.status_code == 200
    rewritten = await _correct(client, rejected, "使用者改写的描述")

    old_stable = await _propose(object_id, origin="user_statement", description="旧的稳定条目")
    corrected = await _correct(client, old_stable, "更正后的稳定条目")

    body = (
        await client.get(
            f"/profile/objects/{object_id}/items",
            params={"include_superseded": "true", "include_candidates": "true"},
        )
    ).json()

    returned = [item["item_id"] for item in [*body["items"], *body["candidates"]]]
    assert rejected not in returned, "被否定的条目不得因 include_superseded 而回看"
    assert old_stable in returned, "对照：被取代的稳定条目必须出现（闸确实开了）"
    assert rewritten in returned
    assert corrected in returned


async def test_items_rejects_a_non_boolean_include_superseded(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """`include_superseded` 非布尔 → 422（与本面既有的入参校验风格一致）。

    与 `include_candidates` 同形：由查询参数的 bool 解析把关，非法取值明确失败，
    不静默当成 `false`——静默降级会让「传错了」看起来像「没有历史条目」。
    """
    object_id = await _new_object()

    for raw in ("maybe", "", "2"):
        response = await client.get(f"/profile/objects/{object_id}/items", params={"include_superseded": raw})
        assert response.status_code == 422, f"include_superseded={raw!r} 得到 {response.status_code}"


async def test_items_rejects_out_of_range_limit(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """`limit` 越界 → 422（契约第 2 节错误码表：`limit` 越界归载荷不合法）。"""
    object_id = await _new_object()

    response = await client.get(f"/profile/objects/{object_id}/items", params={"limit": 10_000})

    assert response.status_code == 422


async def test_items_rejects_unknown_domain_filter(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """领域过滤含词表外取值 → 422（不静默返回空列表冒充「这个领域没有条目」）。"""
    object_id = await _new_object()

    response = await client.get(f"/profile/objects/{object_id}/items", params={"domain": "not_a_domain"})

    assert response.status_code == 422


async def test_items_pagination_walks_the_whole_list_without_repeats(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """cursor 分页能翻完整个列表且不重不漏；翻到尾部 `next_cursor` 为 null。

    造 25 条稳定条目、每页 10 条，逐页跟随游标——这是唯一能证明
    「游标真的推进而不是每次都返回第一页」的断言方式。
    """
    object_id = await _new_object()
    expected = {await _propose(object_id, origin="user_statement", description=f"条目 {index}") for index in range(25)}

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # 上界防止游标不推进时无限循环（CORE-11）
        params: dict[str, object] = {"limit": 10}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get(f"/profile/objects/{object_id}/items", params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["item_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None
    assert len(seen) == len(set(seen)) == len(expected)
    assert set(seen) == expected


async def test_items_rejects_foreign_cursor(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """非法游标 → 422（边界显式，不静默当成第一页）。"""
    object_id = await _new_object()

    response = await client.get(f"/profile/objects/{object_id}/items", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422


async def test_items_rejects_cursor_the_parser_cannot_parse(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """游标的形状闸门必须与解析器同域：解析不了的游标一律 422，不得 500。

    契约那张整面表里 422 = 载荷不合法，而「游标不是本面发出的」属于载荷不合法
    （`list_items` 的 docstring 已写明这一条）。三种取值钉住「闸门比解析器宽」
    的两个方向——修复前的实测状态：

    - `²`（Unicode 上标数字）：`str.isdigit()` 为真而 `int()` 抛 `ValueError`；
      未捕获的异常在生产上是 500，而本面要 422；
    - `１２３`（全角数字）：两者都「成功」，于是本面从未发出过的偏移量 123 被静默
      接受（200）——「游标只由本面产生、只被本面消费」这条声明没有被真的守住；
    - 5000 位数字串：`isdigit()` 为真，但 `int()` 撞上 CPython 的整数串转换上限
      （4300 位）又抛 `ValueError`——同一个洞的第二条 500 路径。

    消融：修复前这三种取值分别得到「异常冒出（生产 500）／200／异常冒出（生产 500）」，
    三条断言全红。
    """
    object_id = await _new_object()

    for cursor in ("²", "１２３", "1" * 5000):
        response = await client.get(f"/profile/objects/{object_id}/items", params={"cursor": cursor})
        assert response.status_code == 422, f"cursor={cursor[:8]!r} 得到 {response.status_code}"


# ---------------------------------------------------------------------------
# 确认 / 纠正 / 否定 / 删除（契约第 4 节）
# ---------------------------------------------------------------------------


async def test_confirm_twice_is_422(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """确认只能作用于候选；对已确认条目再确认 → 422（契约第 4 节）。"""
    object_id = await _new_object()
    candidate = await _propose(object_id, origin="ai_inference")

    first = await client.post(f"/profile/items/{candidate}/confirm")
    second = await client.post(f"/profile/items/{candidate}/confirm")

    assert first.status_code == 200
    assert first.json() == {"item_id": candidate, "confirmation": "confirmed"}
    assert second.status_code == 422


async def test_correct_replaces_old_item_and_keeps_both_pointers(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """纠正 = 新增取代条目，旧条目转 historical 并互指；旧条目不再出现在默认读取里。"""
    object_id = await _new_object()
    old = await _propose(object_id, origin="user_statement", description="旧描述")

    response = await client.post(
        f"/profile/items/{old}/correct",
        json={"description": "新描述", "topic": "新主题", "contexts": ["医院"], "manifestations": ["捂耳"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["supersedes"] == old
    new = body["item_id"]
    assert new != old

    listing = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    assert [item["item_id"] for item in listing.json()["items"]] == [new]
    item = listing.json()["items"][0]
    assert item["description"] == "新描述"
    assert item["supersedes"] == old
    assert item["confirmation"] == "confirmed"


async def test_correct_without_change_is_422(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """纠正无变更 → 422：空转会让一条有效认识白变成历史态。"""
    object_id = await _new_object()
    old = await _propose(object_id, origin="user_statement", description="同一句话")

    response = await client.post(f"/profile/items/{old}/correct", json={"description": "同一句话"})

    assert response.status_code == 422


async def test_correct_of_a_candidate_rebinds_it_to_the_user_statement(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """纠正一条候选：新条目以 `user_statement` 进稳定层，不再标成推断来源。

    这是纠正端点的零覆盖区。此前它把新条目写成 `ai_inference + confirmed` 并直接
    进稳定层——正是 `propose_item` 与 Worker 两处硬拒、第 7 节要求「请求被拒绝」
    的组合，同时把使用者亲手改的词标成「模型推断」。
    """
    object_id = await _new_object()
    candidate = await _propose(object_id, origin="ai_inference", description="模型推断的描述")

    response = await client.post(f"/profile/items/{candidate}/correct", json={"description": "使用者改写的描述"})

    assert response.status_code == 201, response.text
    new = response.json()["item_id"]

    listing = (await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})).json()
    assert listing["candidates"] == [], "被取代的候选不再作为候选呈现"
    assert [item["item_id"] for item in listing["items"]] == [new]
    assert listing["items"][0]["origin"] == "user_statement"
    assert listing["items"][0]["confirmation"] == "confirmed"
    assert listing["items"][0]["source"] == {"channel": "profile_page"}


async def test_correct_twice_is_422_and_keeps_the_first_pointer(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """对已被取代的条目再次纠正 → 422，且第一次的互指不被改写（第 3 节不变量 3）。

    双击或弱网重试同一个纠正请求即命中：第二次会覆写旧条目的 `superseded_by`，
    让第一次产生的取代者成为悬挂指针。
    """
    object_id = await _new_object()
    old = await _propose(object_id, origin="user_statement", description="第一版描述")

    first = await client.post(f"/profile/items/{old}/correct", json={"description": "第二版描述"})
    assert first.status_code == 201, first.text
    new = first.json()["item_id"]

    second = await client.post(f"/profile/items/{old}/correct", json={"description": "第三版描述"})

    assert second.status_code == 422
    listing = (await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})).json()
    assert [item["item_id"] for item in listing["items"]] == [new], "第二次纠正不得留下第三个条目"


async def test_reject_removes_candidate_from_reads(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """否定不物理删除，但此后不出现在条目读取里（个性化档案第 2 节）。"""
    object_id = await _new_object()
    candidate = await _propose(object_id, origin="ai_inference")

    response = await client.post(f"/profile/items/{candidate}/reject")

    assert response.status_code == 200
    assert response.json() == {"item_id": candidate, "confirmation": "rejected"}

    listing = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    assert listing.json()["items"] == []
    assert listing.json()["candidates"] == []


async def test_confirm_of_a_superseded_item_is_422(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """对已被取代的条目确认 → 422（历史条目只可回看，`RQ-MEM-03` 无此能力）。

    消融：去掉 `repository.confirm_item` 的 `superseded_by IS NULL` 判据，
    本用例必红——探针实测此前返回 200，且该行按归组判据从 `candidates` 移进 `items`。
    """
    object_id = await _new_object()
    old, new = await _superseded_unconfirmed_candidate(client, object_id)

    response = await client.post(f"/profile/items/{old}/confirm")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_payload"
    listing = (
        await client.get(
            f"/profile/objects/{object_id}/items",
            params={"include_superseded": "true", "include_candidates": "true"},
        )
    ).json()
    assert [item["item_id"] for item in listing["candidates"]] == [old], "被拒绝的确认不得改变归组"
    assert [item["item_id"] for item in listing["items"]] == [new]
    assert listing["candidates"][0]["confirmation"] == "unconfirmed"


async def test_reject_of_a_superseded_item_is_422(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """对已被取代的条目否定 → 422，且它仍可回看（否定会让它从所有读路径消失）。

    消融：去掉 `repository.reject_item` 的 `superseded_by IS NULL` 判据，
    本用例必红——探针实测此前返回 200，该行此后连
    `include_superseded=true` 也取不到。
    """
    object_id = await _new_object()
    old, new = await _superseded_unconfirmed_candidate(client, object_id)

    response = await client.post(f"/profile/items/{old}/reject")

    assert response.status_code == 422, response.text
    listing = (
        await client.get(
            f"/profile/objects/{object_id}/items",
            params={"include_superseded": "true", "include_candidates": "true"},
        )
    ).json()
    assert [item["item_id"] for item in listing["candidates"]] == [old], "历史行必须仍可回看"
    assert listing["candidates"][0]["confirmation"] == "unconfirmed"


async def test_delete_of_a_superseded_item_is_still_200(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """已取代条目仍可删除（`RQ-MEM-03` 的「删」）：新增守卫只落在确认与否定两处。

    没有这条，守卫可能被顺手扩散成「历史条目一概只读」，而删除对历史条目
    仍然合法——那是与纠正、确认都不同的一条路径。
    """
    object_id = await _new_object()
    old, new = await _superseded_unconfirmed_candidate(client, object_id)

    response = await client.delete(f"/profile/items/{old}")

    assert response.status_code == 200, response.text
    assert response.json() == {"item_id": old, "already": False}
    listing = (
        await client.get(
            f"/profile/objects/{object_id}/items",
            params={"include_superseded": "true", "include_candidates": "true"},
        )
    ).json()
    assert [item["item_id"] for item in listing["candidates"]] == [], "删掉的历史行不再出现"
    assert [item["item_id"] for item in listing["items"]] == [new]


async def test_delete_returns_404_for_foreign_and_absent_items(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """删除的越权与不存在：404 且响应体逐字相同（契约第 6 节、裁决 1）。

    两个场景都是真实 HTTP 实测，不是读代码推得：
    - 越权：删除他人条目；
    - 不存在：删除一个从未存在过的合法标识。

    第三次调用是「自己的条目删过之后再来一次」——条目是物理删除，服务端无法把
    「已被自己删掉」与「从未存在」区分开，因此同样 404、同样文案：删除的越权与
    不存在一律 404，不得返回 200（2026-09-30 编排器裁决 1）。

    另外断言越权删除没有删到任何行：只报 404 却真把行删了同样是缺陷。
    """
    foreign_object = await _new_object(account=_ACCOUNT_OTHER)
    foreign_item = await _propose(foreign_object, origin="ai_inference", account=_ACCOUNT_OTHER)
    mine = await _new_object(name="我的对象")
    my_item = await _propose(mine, origin="user_statement")
    missing = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    foreign = await client.delete(f"/profile/items/{foreign_item}")
    absent = await client.delete(f"/profile/items/{missing}")
    mine_first = await client.delete(f"/profile/items/{my_item}")
    mine_again = await client.delete(f"/profile/items/{my_item}")

    assert mine_first.status_code == 200
    assert mine_first.json() == {"item_id": my_item, "already": False}

    for response in (foreign, absent, mine_again):
        assert response.status_code == 404
        assert response.json() == {"detail": OBJECT_NOT_ACCESSIBLE_MESSAGE, "code": "not_found"}
    assert foreign.json() == absent.json() == mine_again.json(), "越权与不存在的响应必须逐字相同"

    # 越权删除不得删到行（他人条目完好）。
    async with session_scope(get_settings()) as session:
        survivor = await repo.get_item(session, item_id=foreign_item)
    assert survivor is not None and survivor.description == "可观察的描述"


async def test_deleted_item_is_gone_from_items_and_summary(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """删除后读取不再返回该条目（`AC-08` 的验收对象）。"""
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", description="待删除内容")

    await client.delete(f"/profile/items/{item_id}")

    listing = await client.get(f"/profile/objects/{object_id}/items", params={"include_candidates": "true"})
    summary = await client.get(f"/profile/objects/{object_id}/summary")

    ids = [item["item_id"] for item in [*listing.json()["items"], *listing.json()["candidates"]]]
    texts = [entry["text"] for field in summary.json()["fields"] for entry in field["items"]]
    assert item_id not in ids
    assert "待删除内容" not in texts


async def test_other_accounts_item_operations_are_404(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """条目级动作（纠正/否定/确认）对他人条目一律 404，且与不存在同文案。"""
    foreign_object = await _new_object(account=_ACCOUNT_OTHER)
    foreign_item = await _propose(foreign_object, origin="ai_inference", account=_ACCOUNT_OTHER)
    missing = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

    for path, body in (
        (f"/profile/items/{foreign_item}/confirm", None),
        (f"/profile/items/{foreign_item}/reject", None),
        (f"/profile/items/{foreign_item}/correct", {"description": "改写"}),
    ):
        foreign = await client.post(path, json=body) if body else await client.post(path)
        absent = (
            await client.post(path.replace(foreign_item, missing), json=body)
            if body
            else await client.post(path.replace(foreign_item, missing))
        )
        assert foreign.status_code == 404, path
        assert foreign.json() == absent.json(), path


# ---------------------------------------------------------------------------
# 补充条目（契约第 5 节）
# ---------------------------------------------------------------------------


async def test_create_item_uses_user_statement_origin(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """补充条目的 `origin` 由服务端定为 `user_statement`，不接受调用方传入（契约第 5 节）。

    请求体里塞 `origin: ai_inference` 也不得生效——否则生成方式就成了使用者
    可选的字段，而它决定了这条内容落在候选层还是稳定层。
    """
    object_id = await _new_object()

    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={
            "domain": "sensory_processing",
            "topic": "听觉",
            "description": "对吹风机声音敏感",
            "contexts": ["家里"],
            "manifestations": ["捂耳"],
            "origin": "ai_inference",
        },
    )

    assert response.status_code == 201
    item_id = response.json()["item_id"]

    listing = await client.get(f"/profile/objects/{object_id}/items")
    item = next(entry for entry in listing.json()["items"] if entry["item_id"] == item_id)
    assert item["origin"] == "user_statement"
    assert item["confirmation"] == "confirmed"
    assert item["contexts"] == ["家里"]
    assert item["source"]


async def test_create_item_rejects_unknown_domain(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """未知领域名 → 422（不静默归入「其他」）。"""
    object_id = await _new_object()

    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={"domain": "not_a_domain", "topic": "x", "description": "y"},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# topic 的长度上界（D-63）
# ---------------------------------------------------------------------------


async def test_topic_over_the_storage_width_is_422_not_500(as_account) -> None:  # noqa: ANN001
    """`topic` 超过存储列宽 → 422（不是 500）；恰好等于列宽 → 正常写入且不截断。

    列宽是 `String(200)`（`modules/profile/models.py` 的 `ProfileItem.topic`），
    工具入口同值有界（`tools/profile.py` 的 `max_length=200`），而两条 HTTP 写路径
    此前完全不收界：201 字的载荷一路走到 asyncpg 抛 `StringDataRightTruncationError`，
    未映射异常原样冒泡（`_map_error` 末尾的 `raise exc`）→ 500。契约第 1 节的 422
    表达的是「这次请求本身有问题」，而 500 会让调用方以为服务端故障、重试同一份载荷。

    两条写路径都要收界（补充条目的 `topic` 必填、纠正的 `topic` 可选）：同一字段的
    两条入口对同一约束有两种实现，正是本条要钉住的漂移，只修一半等于没修。
    用 201 与 200 这一对相邻长度做判别——上界大于 200 时 201 字会被接受，小于 200 时
    200 字会被拒绝，只有真正按 200 收界的实现能同时满足两端。

    这里自建 `raise_app_exceptions=False` 的客户端、并按末节 401 用例的写法自行
    初始化 SDK：ASGITransport 默认把未处理异常重新抛出，那样超长载荷只会表现为
    测试报错、看不到实际状态码——而本条要钉住的正是「错误码是 422 不是 500」。
    """
    import campfire.main as main_module
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(get_settings(), api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    object_id = await _new_object()
    at_limit = "主" * 200
    over_limit = "主" * 201

    transport = httpx.ASGITransport(app=main_module.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as raw:
        created = await raw.post(
            f"/profile/objects/{object_id}/items",
            json={"domain": "communication", "topic": at_limit, "description": "边界内的主题"},
        )
        assert created.status_code == 201, created.text
        listing = await raw.get(f"/profile/objects/{object_id}/items")
        stored = next(entry for entry in listing.json()["items"] if entry["item_id"] == created.json()["item_id"])
        assert stored["topic"] == at_limit, "恰好 200 字必须完整落库，不被截断"

        too_long = await raw.post(
            f"/profile/objects/{object_id}/items",
            json={"domain": "communication", "topic": over_limit, "description": "超宽主题"},
        )
        assert too_long.status_code == 422, too_long.text
        assert [error for error in too_long.json()["detail"] if error["loc"][-1] == "topic"], too_long.text

        # 纠正的先超长后边界内：反过来的顺序会让条目先被取代，第二次请求便因
        # D-64 的状态判据返回 422——那样这条断言就不再指向长度上界。
        old = await _propose(object_id, origin="user_statement", description="待纠正")
        over_correct = await raw.post(
            f"/profile/items/{old}/correct",
            json={"description": "改写", "topic": over_limit},
        )
        assert over_correct.status_code == 422, over_correct.text
        assert [error for error in over_correct.json()["detail"] if error["loc"][-1] == "topic"], over_correct.text

        at_limit_correct = await raw.post(
            f"/profile/items/{old}/correct",
            json={"description": "改写", "topic": at_limit},
        )
        assert at_limit_correct.status_code == 201, at_limit_correct.text


# ---------------------------------------------------------------------------
# 401：全端点须登录（真实 SDK，需 core）
# ---------------------------------------------------------------------------


async def test_endpoints_require_a_session() -> None:
    """无会话请求档案面每一个端点 → 401（`RQ-ACC-01`：全应用必须登录）。

    走真实 SDK（因此需要 SuperTokens core 与 API Key；缺任一跳过而不是假装通过）。
    不替换会话依赖——这条要验的正是依赖本身。

    清单不手写残缺版：期望集合与实际路由表（OpenAPI 是它的对外可观测形式）
    逐项比对，两端都必须相等——新增端点而忘了同步时这条会失败，而不是
    「只测了旧的一半」却显示通过。
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

    expected = {
        ("GET", "/profile/objects"),
        ("POST", "/profile/objects"),
        ("PATCH", "/profile/objects/{support_object_id}"),
        ("GET", "/profile/objects/{support_object_id}/summary"),
        ("GET", "/profile/objects/{support_object_id}/items"),
        ("POST", "/profile/objects/{support_object_id}/items"),
        ("POST", "/profile/items/{item_id}/confirm"),
        ("POST", "/profile/items/{item_id}/correct"),
        ("POST", "/profile/items/{item_id}/reject"),
        ("DELETE", "/profile/items/{item_id}"),
    }
    operations = {
        (method.upper(), template)
        for template, spec in main_module.app.openapi()["paths"].items()
        if template.startswith("/profile/")
        for method in spec
    }
    assert operations == expected, "401 覆盖清单与档案面路由表不一致——同步本条后再跑"

    item_id = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"
    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        for method, template in sorted(operations):
            path = template.replace("{support_object_id}", item_id).replace("{item_id}", item_id)
            response = await async_client.request(method, path, json={} if method in ("POST", "PATCH") else None)
            assert response.status_code == 401, f"{method} {template} 未要求登录"


async def test_routes_are_mounted_under_the_profile_prefix() -> None:
    """三个面的路由挂在 main.py 的应用上（装配点回归）。

    断言路径集合而不是逐个手写：漏挂一个端点时这条会失败，而逐个断言容易
    在新增端点后忘记补。

    用 `app.openapi()["paths"]` 而不是遍历 `app.routes`：FastAPI 0.141 把
    `include_router` 的结果收成单个 `_IncludedRouter` 项（`path` 为 `None`），
    遍历 `app.routes` 看不到子路由（实测）。OpenAPI 是路由表的对外可观测形式，
    它同时覆盖「路由注册了」与「请求体模型可用」两件事。
    """
    import campfire.main as main_module

    paths = set(main_module.app.openapi()["paths"])
    assert {
        "/profile/objects",
        "/profile/objects/{support_object_id}",
        "/profile/objects/{support_object_id}/summary",
        "/profile/objects/{support_object_id}/items",
        "/profile/items/{item_id}/confirm",
        "/profile/items/{item_id}/correct",
        "/profile/items/{item_id}/reject",
        "/profile/items/{item_id}",
    } <= paths


async def test_repo_scope_helper_still_used_by_routes(client: httpx.AsyncClient, as_account) -> None:  # noqa: ANN001
    """路由不得绕过用例层直接写表：用一条真实请求钉住用例层的副作用。

    这是「面不得直接访问数据库表」的一个可执行证据——写入经用例层时，
    `profile_item` 上会出现 `MANUAL_ENTRY_SOURCE` 这个由用例层补的来源定位，
    而绕过用例层直接 INSERT 不会产生它。
    """
    object_id = await _new_object()

    response = await client.post(
        f"/profile/objects/{object_id}/items",
        json={"domain": "communication", "topic": "t", "description": "d"},
    )

    assert response.status_code == 201
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=response.json()["item_id"])
    assert row is not None
    assert row.source
