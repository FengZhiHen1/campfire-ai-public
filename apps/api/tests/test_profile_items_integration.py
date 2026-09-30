"""集成测试：档案条目的落层分流、确认/纠正/删除、摘要与应急取数（真实 PostgreSQL）。

对应 ``docs/技术设计/technical-details/个性化档案.md`` 第 2、3、4、8 节与
``docs/技术设计/面/profile/档案面HTTP契约.md`` 第 3、4、5 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_items_integration.py

## 本文件守住的核心判据

1. **落层分流六用例**（第 10 节验证方式）：四种非推断 `origin` 各提交一条进稳定层；
   两种推断 `origin` 只进候选层、**摘要中不出现**。
2. **推断不得自认已确认**：`ai_inference` + `confirmed` 被**拒绝**且**未落库**。
3. **候选隔离**：候选不混进 `items`（由返回结构保证，`AC-18`）。
4. **否定不回潮**：`rejected` 不进摘要、不参与注入、不再作候选。
5. **降权（90 天）**：不进摘要与默认读取、被检索到时标注陈旧、**未被删除**。
6. **纠正**：新旧互指、旧条目转 `historical`、注入只含新条目。
7. **删除幂等**且不再被取数（`AC-08`）。
8. **摘要覆盖性**：十二字段都能生产；只有候选条目的对象返回「无档案」而非空对象。
9. **应急八组**：只取稳定层；某组未预存返回显式 absent；`communication` 是具名结构。
10. **摘要 `possibly_stale`**：有未完成待处理记录时为真。
11. **幂等键**：`pending_id` 唯一，重复消费不产生第二条目。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from campfire.core.authz import ObjectArchivedError, set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import PendingWrite, enqueue
from campfire.modules.profile import repository as repo
from campfire.modules.profile import service
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.errors import (
    InferredCannotBeConfirmedError,
    ProfileDataError,
    ProfileItemNotFoundError,
)
from campfire.modules.profile.models import (
    STALE_AFTER_DAYS,
    ProfileItem,
    SupportObject,
)

pytestmark = pytest.mark.integration

_ACCOUNT = "it_profile_items_account"
#: 另一个账号：用于越权断言。
_ACCOUNT_OTHER = "it_profile_items_other"

#: 六种 `origin`（契约第 2 节）。四种非推断直接进稳定层，两种推断只进候选层。
_STABLE_ORIGINS = ("user_statement", "guardian_observation", "third_party_report", "document")
_CANDIDATE_ORIGINS = ("system_observation", "ai_inference")

#: 参照时间固定，避免用例依赖真实时钟。
_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


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


async def _clear() -> None:
    accounts = (_ACCOUNT, _ACCOUNT_OTHER)
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id.in_(accounts)))
        owned = select(SupportObject.id).where(SupportObject.account_id.in_(accounts))
        await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id.in_(accounts)))


async def _new_object(account: str = _ACCOUNT, name: str = "小宝") -> str:
    """建一个对象并返回标识（提交后读，见 test_profile_objects 的说明）。"""
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
    confirmation: str | None = None,
    source: dict | None = None,
) -> str:
    """提交一条条目，返回其标识。"""
    async with session_scope(get_settings()) as session:
        item = await service.propose_item(
            session,
            account_id=account,
            support_object_id=object_id,
            domain=domain,
            topic=topic,
            description=description,
            origin=origin,
            source=source if source is not None else {"session_id": "s1"},
            confirmation=confirmation,
        )
    return str(item.item_id)


# ---------------------------------------------------------------------------
# 1. 落层分流六用例（第 10 节验证方式全表照做）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_four_non_inferred_origins_land_in_the_stable_layer() -> None:
    """四种非推断 `origin` **各提交一条**，全部直接进稳定层（第 3 节的落层表）。

    注意 `third_party_report` 与 `document`：它们进稳定层，但 `confirmation`
    仍是 `unconfirmed`——「直接稳定层」说的是参与取数，不是「已确认」。
    这条断言同时证明「稳定层」与「已确认」是两个维度，不是一个。
    """
    object_id = await _new_object()
    for origin in _STABLE_ORIGINS:
        await _propose(object_id, origin=origin, description=f"来自 {origin} 的观察")

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert len(grouped.items) == 4, "四种非推断来源都应进稳定层"
    assert grouped.candidates == [], "非推断来源不得出现在候选层"

    by_origin = {item.origin: item for item in grouped.items}
    # 陈述与监护人观察：入档即已确认。
    assert by_origin["user_statement"].confirmation == "confirmed"
    assert by_origin["guardian_observation"].confirmation == "confirmed"
    # 第三方转述与文档：进稳定层但未确认——两个维度分离的证据。
    assert by_origin["third_party_report"].confirmation == "unconfirmed"
    assert by_origin["document"].confirmation == "unconfirmed"


@pytest.mark.asyncio
async def test_the_two_inferred_origins_land_only_in_the_candidate_layer() -> None:
    """两种推断 `origin` 各提交一条，**只进候选层**且**摘要中不出现**（`AC-18`）。

    「不出现」是本条的关键：候选不得以事实语气进入摘要——这是 `RQ-MEM-04`
    的可观察面，也是 `AC-18` 的验收对象。
    """
    object_id = await _new_object()
    for origin in _CANDIDATE_ORIGINS:
        await _propose(object_id, origin=origin, description=f"{origin} 归纳出的一条")

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
    assert grouped.items == [], "推断来源不得进稳定层"
    assert len(grouped.candidates) == 2
    assert {item.origin for item in grouped.candidates} == set(_CANDIDATE_ORIGINS)
    # 候选必须自带标记，调用方与模型都不得当作事实。
    assert all(item.confirmation == "unconfirmed" for item in grouped.candidates)

    # 摘要里不得出现它们——只有候选条目的对象在摘要意义上就是「无档案」。
    async with session_scope(get_settings()) as session:
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert summary.has_profile is False, "只有候选条目时必须返回「无档案」而不是空对象"
    assert summary.item_count == 0
    assert summary.fields == []


@pytest.mark.asyncio
async def test_candidates_are_not_mixed_into_items_by_default() -> None:
    """`include_candidates=False` 时**不得混入候选**（`read_profile_items` 契约第 4 节）。

    这是候选隔离的服务端侧保证：由**返回结构**保证，而不是靠前端自己分。
    """
    object_id = await _new_object()
    await _propose(object_id, origin="user_statement", description="已确认的事实")
    await _propose(object_id, origin="ai_inference", description="待确认的推断")

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert len(grouped.items) == 1
    assert grouped.items[0].origin == "user_statement"
    assert grouped.candidates == [], "默认读取不得返回候选"


# ---------------------------------------------------------------------------
# 2. 推断不得自认已确认（第 10 节的硬约束验证）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inferred_with_confirmed_is_rejected_and_not_persisted() -> None:
    """`ai_inference` + `confirmed` 被**拒绝**且**未落库**（`RQ-MEM-04`）。

    两件事都要断言：拒绝（请求被拒，不是降级改写），以及**没有落库**
    ——只断言异常时，一个「先写后校验」的实现仍会通过。
    """
    object_id = await _new_object()

    with pytest.raises(InferredCannotBeConfirmedError):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="communication",
                topic="表达方式",
                description="断言这不是已确认的事实",
                origin="ai_inference",
                source={"session_id": "s1"},
                confirmation="confirmed",
            )

    # 未落库：库里一条都没有。
    async with session_scope(get_settings()) as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(ProfileItem)
                .where(ProfileItem.support_object_id == repo.to_object_uuid(object_id))
            )
        ).scalar_one()
    assert count == 0, "被拒绝的推断不得落库"

    # `system_observation` 同样受约束。
    with pytest.raises(InferredCannotBeConfirmedError):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="communication",
                topic="表达方式",
                description="系统观察也不得写成已确认",
                origin="system_observation",
                source={"session_id": "s1"},
                confirmation="confirmed",
            )


@pytest.mark.asyncio
async def test_user_statement_with_confirmed_is_accepted() -> None:
    """**正向对照**：`user_statement` + `confirmed` 合法——陈述本身即确认。

    没有这条，上面的「拒绝」可能只是「一切 confirmed 都被拒」。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", confirmation="confirmed")
    async with session_scope(get_settings()) as session:
        record = await repo.get_item(session, item_id=item_id)
    assert record.confirmation == "confirmed"


# ---------------------------------------------------------------------------
# 3. 确认与否定（第 2、3 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_moves_a_candidate_into_the_stable_layer() -> None:
    """确认一条候选后它进稳定层——「推断要使用者确认才成事实」的落点（第 3 节）。"""
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="ai_inference", description="可能是感觉敏感")

    # 确认前：不进摘要。
    async with session_scope(get_settings()) as session:
        before = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert before.has_profile is False

    async with session_scope(get_settings()) as session:
        confirmed = await service.confirm_item(session, account_id=_ACCOUNT, item_id=item_id)
    assert confirmed.confirmation == "confirmed"

    # 确认后：进摘要。
    async with session_scope(get_settings()) as session:
        after = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert after.has_profile is True
    assert after.item_count == 1


@pytest.mark.asyncio
async def test_confirm_only_applies_to_unconfirmed_items() -> None:
    """确认**只能作用于候选条目**；对已确认或已否定的条目失败（契约第 4 节）。"""
    object_id = await _new_object()
    # 已确认的条目（user_statement 入档即 confirmed）。
    stable_id = await _propose(object_id, origin="user_statement")

    with pytest.raises(ProfileItemNotFoundError):
        async with session_scope(get_settings()) as session:
            await service.confirm_item(session, account_id=_ACCOUNT, item_id=stable_id)

    # 已否定的候选也不能再确认。
    candidate_id = await _propose(object_id, origin="ai_inference")
    async with session_scope(get_settings()) as session:
        await service.reject_item(session, account_id=_ACCOUNT, item_id=candidate_id)
    with pytest.raises(ProfileItemNotFoundError):
        async with session_scope(get_settings()) as session:
            await service.confirm_item(session, account_id=_ACCOUNT, item_id=candidate_id)


@pytest.mark.asyncio
async def test_rejected_candidate_never_comes_back() -> None:
    """**否定不回潮**：`rejected` 不进摘要、不参与注入、不再作候选（第 2 节）。

    三处一次断言：摘要不含、`resolve_for_context(include_candidates=True)` 不含、
    `read_items(include_candidates=True)` 不含。否定**不物理删除**行。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="ai_inference", description="被否定的一条推断")

    async with session_scope(get_settings()) as session:
        rejected = await service.reject_item(session, account_id=_ACCOUNT, item_id=item_id)
    assert rejected.confirmation == "rejected"

    # 行仍在（否定不删数据：它是可追溯事实）。
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=item_id)
    assert row is not None, "rejected 不得物理删除"

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
        context = await service.resolve_for_context(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert grouped.items == [] and grouped.candidates == [], "被否定的条目不得再作为候选返回"
    assert context == [], "被否定的条目不得参与上下文注入"
    assert summary.has_profile is False, "被否定的条目不得进摘要"


@pytest.mark.asyncio
async def test_reject_only_applies_to_candidates() -> None:
    """否定只作用于候选（对已确认条目返回失败——不能靠否定抹掉一条已确认的事实）。"""
    object_id = await _new_object()
    stable_id = await _propose(object_id, origin="user_statement")
    with pytest.raises(ProfileItemNotFoundError):
        async with session_scope(get_settings()) as session:
            await service.reject_item(session, account_id=_ACCOUNT, item_id=stable_id)


# ---------------------------------------------------------------------------
# 4. 降权（90 天，第 3 节与第 10 节验证项）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_downgraded_candidate_is_excluded_but_not_deleted() -> None:
    """把候选条目的 `last_confirmed_at` 置为 90 天前，验证：

    - 不进摘要与默认读取；
    - **被检索到时标注陈旧**（`freshness = stale`，不是消失）；
    - **未被删除**（第 3 节：不删除）。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="ai_inference", description="很久没确认的推断")

    old = _NOW - timedelta(days=STALE_AFTER_DAYS + 1)
    async with session_scope(get_settings()) as session:
        await session.execute(
            ProfileItem.__table__.update()
            .where(ProfileItem.item_id == repo.to_item_uuid(item_id))
            .values(last_confirmed_at=old)
        )

    # 默认读取（include_candidates=False）不返回它。
    async with session_scope(get_settings()) as session:
        default_view = await service.read_items(session, account_id=_ACCOUNT, support_object_id=object_id, now=_NOW)
    assert default_view.items == [] and default_view.candidates == []

    # 摘要不返回它。
    async with session_scope(get_settings()) as session:
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id, now=_NOW)
    assert summary.has_profile is False

    # 但**显式检索候选时它仍在**，且新鲜度标注为 stale（「被检索到时须标注其陈旧」）。
    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True, now=_NOW
        )
    assert len(grouped.candidates) == 1, "降权不是删除：显式检索时它仍应可见"
    assert grouped.candidates[0].freshness == "stale", "被检索到时必须标注陈旧"

    # 行仍在库里，且存储值未被改写（降权是读期判定）。
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=item_id)
    assert row is not None, "降权不得删除数据"
    assert row.freshness == "current", "降权是读期标记，不得改写存储值"


@pytest.mark.asyncio
async def test_confirmed_item_is_not_downgraded_even_when_old() -> None:
    """**正向对照**：已确认的条目即使很久没再确认，也不降权（第 3 节的用意）。"""
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", description="早已确认的事实")
    old = _NOW - timedelta(days=STALE_AFTER_DAYS * 5)
    async with session_scope(get_settings()) as session:
        await session.execute(
            ProfileItem.__table__.update()
            .where(ProfileItem.item_id == repo.to_item_uuid(item_id))
            .values(last_confirmed_at=old)
        )
    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(session, account_id=_ACCOUNT, support_object_id=object_id, now=_NOW)
    assert len(grouped.items) == 1, "已确认的事实不因时间推移而降权"
    assert grouped.items[0].freshness == "current"


# ---------------------------------------------------------------------------
# 5. 纠正（第 3 节不变量 3、第 10 节验证项）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correction_creates_a_new_item_and_points_both_ways() -> None:
    """纠正 = 新增取代条目 + 旧条目转 `historical` 并**互指**，注入只含新条目。

    三处断言：① 两个指针都在（`superseded_by` 与 `supersedes`）；
    ② 旧条目 `freshness = historical`；③ 取数只含新条目。
    """
    object_id = await _new_object()
    old_id = await _propose(object_id, origin="user_statement", description="原来的描述")

    async with session_scope(get_settings()) as session:
        new_item, superseded = await service.correct_item(
            session, account_id=_ACCOUNT, item_id=old_id, description="更正后的描述"
        )
    new_id = str(new_item.item_id)

    assert new_id != old_id
    assert superseded.freshness == "historical", "旧条目必须转 historical"
    assert str(superseded.superseded_by) == new_id, "旧条目必须指向新条目"
    assert str(new_item.supersedes) == old_id, "新条目必须反向指向旧条目（互指）"

    # 取数只含新条目（旧条目不参与默认读取）。
    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(session, account_id=_ACCOUNT, support_object_id=object_id)
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    descriptions = [item.description for item in grouped.items]
    assert descriptions == ["更正后的描述"], "注入只含新条目"
    assert summary.item_count == 1
    assert all(entry.description == "更正后的描述" for field in summary.fields for entry in field.items)


@pytest.mark.asyncio
async def test_correction_rejects_a_no_change_patch() -> None:
    """纠正**无变更**被拒（契约第 1 节：422）。

    没有这条，一次空转的纠正会把一条有效认识白白变成历史态。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", description="一模一样的描述")
    with pytest.raises(ProfileDataError, match="无变更"):
        async with session_scope(get_settings()) as session:
            await service.correct_item(session, account_id=_ACCOUNT, item_id=item_id, description="一模一样的描述")


@pytest.mark.asyncio
async def test_correction_keeps_the_old_item_readable_as_history() -> None:
    """旧条目**可回看**（纠正不物理覆盖，第 5 节第 5 条）。"""
    object_id = await _new_object()
    old_id = await _propose(object_id, origin="user_statement", description="旧描述")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=old_id, description="新描述")
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=old_id)
    assert row is not None, "旧条目不得被物理删除"
    assert row.description == "旧描述"


# ---------------------------------------------------------------------------
# 6. 删除（`AC-08`）与幂等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_the_item_from_every_read_path() -> None:
    """删除后该内容**不再被取数**（`AC-08`：删除须覆盖检索与衍生中的使用）。

    三条读路径都要断言：列表、摘要、上下文注入。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", description="这条会被删除")

    async with session_scope(get_settings()) as session:
        deleted = await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)
    assert deleted is True

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
        context = await service.resolve_for_context(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
    assert grouped.items == [] and grouped.candidates == []
    assert summary.has_profile is False
    assert context == []


@pytest.mark.asyncio
async def test_delete_is_idempotent() -> None:
    """**删除幂等**：重复删除返回 False（调用方据此回报 `already: true`），不报错。

    实测重复执行两次（自检要求幂等类要求必须实测）。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement")

    async with session_scope(get_settings()) as session:
        first = await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)
    async with session_scope(get_settings()) as session:
        second = await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)
    async with session_scope(get_settings()) as session:
        third = await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)

    assert (first, second, third) == (True, False, False), "只有第一次删到了行"


# ---------------------------------------------------------------------------
# 7. 越权（`AC-22`：两个对象的档案互不可见）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_account_cannot_read_or_write_items() -> None:
    """跨账号访问条目：读与写两条路径都必须失败（`AC-22`）。"""
    mine = await _new_object(_ACCOUNT, "我的对象")
    item_id = await _propose(mine, origin="user_statement")

    # 账号 B 读我的对象条目。
    from campfire.core.authz import AuthorizationError

    with pytest.raises(AuthorizationError):
        async with session_scope(get_settings()) as session:
            await service.read_items(session, account_id=_ACCOUNT_OTHER, support_object_id=mine)

    # 账号 B 对我的条目做确认/纠正/删除：都经对象归属判定，全部失败。
    with pytest.raises(AuthorizationError):
        async with session_scope(get_settings()) as session:
            await service.confirm_item(session, account_id=_ACCOUNT_OTHER, item_id=item_id)
    with pytest.raises(AuthorizationError):
        async with session_scope(get_settings()) as session:
            await service.correct_item(session, account_id=_ACCOUNT_OTHER, item_id=item_id, description="他人修改")
    # 删除的归属判定在一条 SQL 内完成，越权时不删任何行。
    async with session_scope(get_settings()) as session:
        deleted = await service.delete_item(session, account_id=_ACCOUNT_OTHER, item_id=item_id)
    assert deleted is False, "越权删除不得删到任何行"

    # 原条目完好。
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=item_id)
    assert row is not None and row.description == "可观察的描述"


@pytest.mark.asyncio
async def test_items_of_two_objects_are_mutually_invisible() -> None:
    """同一账号的两个对象：档案**互不可见**（`AC-22`）。"""
    first = await _new_object(_ACCOUNT, "对象一")
    second = await _new_object(_ACCOUNT, "对象二")
    await _propose(first, origin="user_statement", description="属于对象一的条目")

    async with session_scope(get_settings()) as session:
        first_view = await service.read_items(session, account_id=_ACCOUNT, support_object_id=first)
        second_view = await service.read_items(session, account_id=_ACCOUNT, support_object_id=second)

    assert len(first_view.items) == 1
    assert second_view.items == [], "对象二的档案不得看到对象一的条目"


# ---------------------------------------------------------------------------
# 8. 摘要（第 4 节）与 possibly_stale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_only_includes_stable_layer_items() -> None:
    """摘要**只从稳定层取数**，且每条带来源与时间（第 4 节）。"""
    object_id = await _new_object()
    await _propose(object_id, origin="user_statement", domain="communication", description="稳定的一条")
    await _propose(object_id, origin="ai_inference", domain="communication", description="候选的一条")

    async with session_scope(get_settings()) as session:
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert summary.has_profile is True
    assert summary.item_count == 1
    entries = [entry for field in summary.fields for entry in field.items]
    assert [entry.description for entry in entries] == ["稳定的一条"]
    # 每条可追溯到具体条目，并带生成方式与最近确认时间。
    assert entries[0].item_id
    assert entries[0].origin == "user_statement"
    assert entries[0].last_confirmed_at is not None
    assert summary.generated_at is not None


@pytest.mark.asyncio
async def test_summary_marks_possibly_stale_when_writes_are_pending() -> None:
    """有待处理记录在途时 `possibly_stale` 必须为真（`read_profile_summary` 契约第 4 节）。

    写入是异步的：摘要可能未含最新内容，必须如实标注而不是假装已是最新。
    """
    object_id = await _new_object()

    async with session_scope(get_settings()) as session:
        before = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert before.possibly_stale is False, "无在途写入时不应报滞后"

    async with session_scope(get_settings()) as session:
        await enqueue(
            session,
            kind="profile_item",
            account_id=_ACCOUNT,
            origin="user_statement",
            payload={"domain": "communication", "topic": "表达方式", "description": "在途的一条"},
            source={"session_id": "s1"},
            support_object_id=object_id,
        )

    async with session_scope(get_settings()) as session:
        after = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert after.possibly_stale is True, "有未完成写入时必须标注可能滞后"


@pytest.mark.asyncio
async def test_summary_of_a_fresh_object_reports_no_profile() -> None:
    """全新对象：返回「无档案」标记而**不是空对象**（`AC-02`、第 10 节验证项）。

    调用方据此在输出里标注「本次未使用个性化档案」——空对象无法表达这个区别。
    """
    object_id = await _new_object()
    async with session_scope(get_settings()) as session:
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert summary.has_profile is False
    assert summary.fields == []
    assert summary.item_count == 0
    assert summary.support_object_id == object_id


@pytest.mark.asyncio
async def test_summary_field_domains_produce_their_fields() -> None:
    """**摘要覆盖性**：十二个字段都能从领域取值生产出来（第 10 节验证项）。

    本用例为每个摘要字段的取数领域各写一条，然后断言字段确实被填上
    ——「字段有映射」与「映射真能生产出内容」是两件事。
    """
    object_id = await _new_object()
    # 为每个被引用的领域各写一条稳定条目。
    domains_needed = {domain for _, domains in service.SUMMARY_FIELD_DOMAINS.values() for domain in domains}
    for domain in sorted(domains_needed):
        await _propose(object_id, origin="user_statement", domain=domain, description=f"{domain} 的事实")

    async with session_scope(get_settings()) as session:
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)

    produced = {field.key for field in summary.fields}
    expected = set(service.SUMMARY_FIELD_DOMAINS)
    assert produced == expected, f"未能生产出的摘要字段：{sorted(expected - produced)}"
    assert len(summary.fields) == 12


@pytest.mark.asyncio
async def test_missing_domain_is_not_reported_as_absent_fact() -> None:
    """**缺项不被当作否定**（第 10 节验证项）：某领域无条目时，输出不声称「该情况不存在」。

    本实现的可观察面：该字段根本不出现在摘要里——没有字段就无从表达「没有这种情况」，
    而不是给出一个空的 `items: []`（那读起来像「确实没有」）。
    """
    object_id = await _new_object()
    # 只写「沟通」领域，其余领域为空。
    await _propose(object_id, origin="user_statement", domain="communication", description="说话简短")

    async with session_scope(get_settings()) as session:
        summary = await service.summary(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert [field.key for field in summary.fields] == ["how_i_communicate"]
    for field in summary.fields:
        assert field.items, "字段一旦出现就必须有内容（空字段会被误读为「确实没有」）"


# ---------------------------------------------------------------------------
# 9. 应急上下文八组（第 8 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_context_returns_all_eight_groups_with_absent_marked() -> None:
    """八组键总是存在；**未预存的组显式返回 absent（None）**，不为空列表（第 8 节）。

    `None` 与 `[]` 的区别正是本用例的判据：调用方据此写「未预存」，
    而不是让模型顺着空列表推断「没有这种情况」。

    `communication` 单独断言：它是具名结构，只认三个具名 `topic`
    （第 8 节的 `{baseline, best_mode, processing_time_seconds}`），
    因此「沟通领域里的一条普通条目」不会出现在它里面——这是设计，
    不是遗漏（该组的键是固定的三个，不是「沟通领域的全部条目」）。
    """
    object_id = await _new_object()
    # 预存「沟通」领域的一个具名键，以及另一个领域的普通条目。
    await _propose(
        object_id, origin="user_statement", domain="communication", topic="baseline", description="可正常对话"
    )
    await _propose(object_id, origin="user_statement", domain="triggers_and_support", description="嘈杂环境会捂耳")

    async with session_scope(get_settings()) as session:
        context = await service.emergency_context(session, account_id=_ACCOUNT, support_object_id=object_id)

    # 七组（除 communication，它单独承载）键都在。
    assert "communication" not in context.groups, "communication 是具名结构，不走 groups"
    assert set(context.groups) == {
        "baseline",
        "known_triggers",
        "sensory_profile",
        "medical_risks",
        "proven_strategies",
        "unhelpful_strategies",
        "safety_history",
    }
    # 已预存的组有内容，未预存的组是显式 None（不是空列表）。
    assert context.groups["known_triggers"] is not None, "触发因素组已预存，应有内容"
    for group in ("baseline", "sensory_profile", "medical_risks", "proven_strategies", "unhelpful_strategies"):
        assert context.groups[group] is None, f"未预存的组 {group} 必须是显式 absent，而不是空列表"
    # communication 是具名结构：只认三个具名 topic。
    assert set(context.communication) == {"baseline"}
    assert context.communication["baseline"].description == "可正常对话"
    assert context.has_profile is True


@pytest.mark.asyncio
async def test_emergency_strategy_groups_are_taken_from_the_paired_fields() -> None:
    """`proven_strategies` 与 `unhelpful_strategies` 取的是条目里**成对相反的字段**。

    这两组与 `known_triggers` 同属「触发因素与支持策略」领域，但语义是
    `helpful_support` 与 `unhelpful_support` 两个字段。若按领域取数，
    同一条条目会同时落进三组——「有效支持」与「无效支持」本是相反的两类内容，
    三者重复会让应急注入变成噪声。

    本用例的判据：一条同时带两个字段的条目，**必须只出现在它对应的那一组**里；
    `known_triggers` 收条目级内容，两个策略组收字段级清单。
    """
    object_id = await _new_object()
    async with session_scope(get_settings()) as session:
        await service.propose_item(
            session,
            account_id=_ACCOUNT,
            support_object_id=object_id,
            domain="triggers_and_support",
            topic="嘈杂环境",
            description="嘈杂时捂耳",
            origin="user_statement",
            source={"session_id": "s1"},
            helpful_support=["降噪耳机", "提前离开"],
            unhelpful_support=["多人围堵"],
        )

    async with session_scope(get_settings()) as session:
        context = await service.emergency_context(session, account_id=_ACCOUNT, support_object_id=object_id)

    # 触发因素组：条目级（一条）。
    triggers = context.groups["known_triggers"]
    assert triggers is not None and len(triggers) == 1
    assert triggers[0].description == "嘈杂时捂耳"

    # 有效支持组：字段级清单（两条），且**不含**无效支持。
    proven = context.groups["proven_strategies"]
    assert proven is not None
    assert [entry.description for entry in proven] == ["降噪耳机", "提前离开"]
    assert "多人围堵" not in [entry.description for entry in proven]

    # 无效支持组：只含无效支持。
    unhelpful = context.groups["unhelpful_strategies"]
    assert unhelpful is not None
    assert [entry.description for entry in unhelpful] == ["多人围堵"]

    # 三组不得互相重复同一条内容（这是本用例的核心判据）。
    trigger_texts = {entry.description for entry in triggers}
    proven_texts = {entry.description for entry in proven}
    unhelpful_texts = {entry.description for entry in unhelpful}
    assert not (trigger_texts & proven_texts), "触发因素与有效支持不得重复同一条内容"
    assert not (proven_texts & unhelpful_texts), "有效支持与无效支持必须严格互斥"

    # 摊平后的条目仍可追溯到来源条目（第 4 节的可追溯性）。
    assert all(entry.item_id == triggers[0].item_id for entry in proven)


@pytest.mark.asyncio
async def test_emergency_strategy_group_is_absent_when_the_field_is_empty() -> None:
    """条目存在但没有有效支持字段时，`proven_strategies` 显式 absent（第 8 节）。

    「有触发因素但没有记录过有效支持」是真实情形，它必须与「预存了但为空」
    可区分：前者 absent，后者不可能出现（空列表不产生内容）。
    """
    object_id = await _new_object()
    await _propose(object_id, origin="user_statement", domain="triggers_and_support", description="嘈杂时捂耳")

    async with session_scope(get_settings()) as session:
        context = await service.emergency_context(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert context.groups["known_triggers"] is not None
    assert context.groups["proven_strategies"] is None, "未记录有效支持时必须 absent"
    assert context.groups["unhelpful_strategies"] is None


@pytest.mark.asyncio
async def test_emergency_context_communication_is_a_named_structure() -> None:
    """`communication` 是具名结构：三个键各自独立判定 absent（第 8 节）。"""
    object_id = await _new_object()
    await _propose(
        object_id, origin="user_statement", domain="communication", topic="baseline", description="可正常对话"
    )
    await _propose(
        object_id, origin="user_statement", domain="communication", topic="best_mode", description="文字优先"
    )
    # 刻意不写 processing_time_seconds。

    async with session_scope(get_settings()) as session:
        context = await service.emergency_context(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert set(context.communication) == {"baseline", "best_mode"}
    assert "processing_time_seconds" not in context.communication, "未预存的键不得出现"
    assert context.communication["baseline"].description == "可正常对话"


@pytest.mark.asyncio
async def test_emergency_context_only_takes_the_stable_layer() -> None:
    """应急预取**只取稳定层**：候选条目不得出现在任何一组里（第 8 节）。"""
    object_id = await _new_object()
    await _propose(object_id, origin="ai_inference", domain="communication", topic="baseline", description="推断")

    async with session_scope(get_settings()) as session:
        context = await service.emergency_context(session, account_id=_ACCOUNT, support_object_id=object_id)

    assert context.communication == {}, "候选不得进应急上下文"
    assert context.has_profile is False
    assert all(value is None for value in context.groups.values())


@pytest.mark.asyncio
async def test_emergency_context_ignores_rejected_items() -> None:
    """被否定的条目不进应急上下文（第 2 节：不参与注入）。"""
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="ai_inference", domain="communication", topic="baseline")
    async with session_scope(get_settings()) as session:
        await service.reject_item(session, account_id=_ACCOUNT, item_id=item_id)
    async with session_scope(get_settings()) as session:
        context = await service.emergency_context(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert context.communication == {}
    assert context.has_profile is False


@pytest.mark.asyncio
async def test_emergency_context_requires_ownership() -> None:
    """应急取数同样要过归属判定（支持对象 5.2 的调用点表）。"""
    from campfire.core.authz import AuthorizationError

    object_id = await _new_object(_ACCOUNT, "我的对象")
    with pytest.raises(AuthorizationError):
        async with session_scope(get_settings()) as session:
            await service.emergency_context(session, account_id=_ACCOUNT_OTHER, support_object_id=object_id)


# ---------------------------------------------------------------------------
# 10. 幂等键（pending_id）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_id_unique_constraint_blocks_duplicate_items() -> None:
    """同一条待处理记录**不得产生第二条目**（写入路径第 5 节：幂等键就是 `pending_id`）。

    用真实唯一约束验证：两次带同一个 `pending_id` 的插入，第二次必须被存储层拒绝。
    """
    import uuid

    from sqlalchemy.exc import IntegrityError

    object_id = await _new_object()
    pending = uuid.uuid4()

    async with session_scope(get_settings()) as session:
        await service.propose_item(
            session,
            account_id=_ACCOUNT,
            support_object_id=object_id,
            domain="communication",
            topic="表达方式",
            description="第一次写入",
            origin="user_statement",
            source={"session_id": "s1"},
            pending_id=pending,
        )

    with pytest.raises(IntegrityError):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="communication",
                topic="表达方式",
                description="重复写入",
                origin="user_statement",
                source={"session_id": "s1"},
                pending_id=pending,
            )


@pytest.mark.asyncio
async def test_manual_items_have_no_pending_id_and_are_not_blocked() -> None:
    """手动补充条目**不经待处理记录**（`pending_id` 为空），因此可以有多条。

    这验证了「唯一约束 + 可空」这两个要求能同时成立：PostgreSQL 的唯一约束
    允许多个 NULL。
    """
    object_id = await _new_object()
    for index in range(3):
        async with session_scope(get_settings()) as session:
            await service.add_manual_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="communication",
                topic="表达方式",
                description=f"手动补充的第 {index} 条",
            )
    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(session, account_id=_ACCOUNT, support_object_id=object_id)
    assert len(grouped.items) == 3
    # 手动补充的 origin 由服务端定为 user_statement，不接受调用方传入。
    assert {item.origin for item in grouped.items} == {"user_statement"}
    assert all(item.source == {"channel": "profile_page"} for item in grouped.items)


# ---------------------------------------------------------------------------
# 11. 领域过滤与非法取值
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_domain_filter_fails_instead_of_returning_empty() -> None:
    """未知领域名**明确失败**，不静默返回空列表（`read_profile_items` 契约第 5 节）。

    静默返回空会让打错字的过滤看起来像「这个领域没有条目」。
    """
    object_id = await _new_object()
    with pytest.raises(ProfileDataError, match="领域过滤"):
        async with session_scope(get_settings()) as session:
            await service.read_items(
                session, account_id=_ACCOUNT, support_object_id=object_id, domains=["not_a_domain"]
            )


@pytest.mark.asyncio
async def test_unknown_domain_on_write_fails() -> None:
    """写入时未知领域名明确失败，**不静默归入「其他」**（`propose_profile_item` 第 4 节）。"""
    object_id = await _new_object()
    with pytest.raises(ProfileDataError, match="领域"):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="not_a_domain",
                topic="主题",
                description="描述",
                origin="user_statement",
                source={"session_id": "s1"},
            )


@pytest.mark.asyncio
async def test_missing_source_is_rejected() -> None:
    """`source` 缺失明确失败——`AC-07` 要求条目带来源（`propose_profile_item` 第 5 节）。"""
    object_id = await _new_object()
    with pytest.raises(ProfileDataError, match="source"):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="communication",
                topic="表达方式",
                description="没有来源的条目",
                origin="user_statement",
                source={},
            )


@pytest.mark.asyncio
async def test_write_to_archived_object_fails_with_archived_reason() -> None:
    """归档对象上的写入失败，且原因是**已归档**而不是越权（第 5.3 节，`AC-22` 的邻居）。"""
    object_id = await _new_object()
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    with pytest.raises(ObjectArchivedError):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT,
                support_object_id=object_id,
                domain="communication",
                topic="表达方式",
                description="归档后不该写进去",
                origin="user_statement",
                source={"session_id": "s1"},
            )

    # 但**归档对象仍可纠正与删除条目**（第 4 节：归档对象可读，RQ-MEM-03 不因归档失效）。
    async with session_scope(get_settings()) as session:
        await service.restore_object(session, account_id=_ACCOUNT, support_object_id=object_id)
    item_id = await _propose(object_id, origin="user_statement", description="归档前写入的条目")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    # 归档状态下纠正与删除都必须可用。
    async with session_scope(get_settings()) as session:
        corrected, _ = await service.correct_item(
            session, account_id=_ACCOUNT, item_id=item_id, description="归档后仍可纠正"
        )
    assert corrected.description == "归档后仍可纠正"
    async with session_scope(get_settings()) as session:
        deleted = await service.delete_item(session, account_id=_ACCOUNT, item_id=str(corrected.item_id))
    assert deleted is True, "归档对象下仍可删除条目"
