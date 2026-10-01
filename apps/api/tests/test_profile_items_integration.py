"""集成测试：档案条目的落层分流、确认/纠正/删除、摘要与应急取数（真实 PostgreSQL）。

对应 `docs/技术设计/technical-details/个性化档案.md` 第 2、3、4、8 节与
`docs/技术设计/面/profile/档案面HTTP契约.md` 第 3、4、5 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_items_integration.py

本文件守住的核心判据：

1. 落层分流六用例（第 10 节验证方式）：四种非推断 `origin` 各提交一条进稳定层；
   两种推断 `origin` 只进候选层、摘要中不出现。
2. 推断不得自认已确认：`ai_inference` + `confirmed` 被拒绝且未落库。
3. 候选隔离：候选不混进 `items`（由返回结构保证，`AC-18`）。
4. 否定不回潮：`rejected` 不进摘要、不参与注入、不再作候选。
5. 降权（90 天）：不进摘要与默认读取、被检索到时标注陈旧、未被删除。
6. 纠正：新旧互指、旧条目转 `historical`、注入只含新条目；纠正推断来源的条目
   把生成方式重绑为 `user_statement`，不造出「推断被写成已确认」的行。
7. 删除不再被取数（`AC-08`），且行消失后重复删除报「不可访问」（裁决 1）。
8. 摘要覆盖性：十二字段都能生产；只有候选条目的对象返回「无档案」而非空对象。
9. 应急八组：只取稳定层；某组未预存返回显式 absent；`communication` 是具名结构。
10. 摘要 `possibly_stale`：有未完成待处理记录时为真。
11. 幂等键：`pending_id` 唯一，重复消费不产生第二条目。
12. 历史回看开关：`include_superseded` 只放开「已被取代」这一条轴
    ——`rejected` 与候选层都不受影响，注入路径不接它；历史条目的归组按它曾属哪一层
    （未确认的系统推断即便被取代也归 `candidates`）。
13. 历史条目只可回看：已被取代的条目不得被确认、也不得被否定（两处守卫；
    此前对「已取代 + 未确认」的行两者都会成功）；删除不受影响（`RQ-MEM-03` 的删）。
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


async def _superseded_unconfirmed_candidate(object_id: str) -> tuple[str, str]:
    """造一条「已被取代 + 未确认」的条目，返回 `(旧条目, 取代它的新条目)`。

    走的是一条合法路径而不是直接改库：提交一条 `ai_inference` 候选（未确认），
    再用 `correct_item` 纠正它——旧条目转 `historical` 并写上 `superseded_by`，
    而 `confirmation` 保持 `unconfirmed`（纠正不会顺带确认旧的推断）。
    正是这个状态组合让「确认/否定」两处的守卫成为必要条件：
    单看 `confirmation` 判据，它看起来仍是一条可确认的候选。
    """
    old_id = await _propose(object_id, origin="ai_inference", description="被取代的推断")
    async with session_scope(get_settings()) as session:
        new_item, _ = await service.correct_item(
            session, account_id=_ACCOUNT, item_id=old_id, description="使用者改写的描述"
        )
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=old_id)
    assert row is not None
    assert row.confirmation == "unconfirmed", "前提：这条被取代的条目仍停在未确认"
    assert row.superseded_by is not None and str(row.superseded_by) == str(new_item.item_id)
    return old_id, str(new_item.item_id)


# ---------------------------------------------------------------------------
# 1. 落层分流六用例（第 10 节验证方式全表照做）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_four_non_inferred_origins_land_in_the_stable_layer() -> None:
    """四种非推断 `origin` 各提交一条，全部直接进稳定层（第 3 节的落层表）。

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
    """两种推断 `origin` 各提交一条，只进候选层且摘要中不出现（`AC-18`）。

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
    """`include_candidates=False` 时不得混入候选（`read_profile_items` 契约第 4 节）。

    这是候选隔离的服务端侧保证：由返回结构保证，而不是靠前端自己分。
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
    """`ai_inference` + `confirmed` 被拒绝且未落库（`RQ-MEM-04`）。

    两件事都要断言：拒绝（请求被拒，不是降级改写），以及没有落库
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
    """正向对照：`user_statement` + `confirmed` 合法——陈述本身即确认。

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
    """确认只能作用于候选条目；对已确认或已否定的条目失败（契约第 4 节）。"""
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
    """否定不回潮：`rejected` 不进摘要、不参与注入、不再作候选（第 2 节）。

    三处一次断言：摘要不含、`resolve_for_context(include_candidates=True)` 不含、
    `read_items(include_candidates=True)` 不含。否定不物理删除行。
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
# 3.1 已被取代的条目不得被确认、也不得被否定（第 5 节第 5 条：历史条目只可回看）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_is_rejected_on_a_superseded_unconfirmed_item() -> None:
    """已被取代 + 未确认的条目 → 确认被拒，且状态没有落库。

    设计对历史条目的话是「可回看」（第 5 节第 5 条），回看即只读；`RQ-MEM-03`
    给使用者的条目能力是「查 / 纠 / 删」，没有「确认一条已被取代的条目」。
    只按 `confirmation = 'unconfirmed'` 判会放行——这条行看起来仍是一条候选。

    消融：去掉 `repository.confirm_item` 的 `superseded_by IS NULL` 判据，
    本用例必红（实测：探针会拿到成功回执，且该行按归组判据从 `candidates`
    移进 `items`——一次设计未认可、且结果可观察的状态转移）。
    """
    object_id = await _new_object()
    old_id, new_id = await _superseded_unconfirmed_candidate(object_id)

    with pytest.raises(ProfileItemNotFoundError, match="未被取代"):
        async with session_scope(get_settings()) as session:
            await service.confirm_item(session, account_id=_ACCOUNT, item_id=old_id)

    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=old_id)
        grouped = await service.read_items(
            session,
            account_id=_ACCOUNT,
            support_object_id=object_id,
            include_superseded=True,
            include_candidates=True,
        )

    assert row is not None and row.confirmation == "unconfirmed", "被拒绝的确认不得落库"
    assert row.freshness == "historical" and row.superseded_by is not None
    assert [item.item_id for item in grouped.candidates] == [old_id], "它仍只在候选组"
    assert [item.item_id for item in grouped.items] == [new_id], "未被取代的新条目不受影响"


@pytest.mark.asyncio
async def test_reject_is_rejected_on_a_superseded_unconfirmed_item() -> None:
    """已被取代 + 未确认的条目 → 否定被拒，且仍可回看。

    否定比确认更有破坏性：读路径一律排除 `rejected`，因此否定一条历史行会让它
    从所有读路径消失，连「可回看」这条被设计认可的能力也一并失去。

    消融：去掉 `repository.reject_item` 的 `superseded_by IS NULL` 判据，
    本用例必红（实测：探针会拿到成功回执，该行此后连
    `include_superseded=true` 也取不到）。
    """
    object_id = await _new_object()
    old_id, new_id = await _superseded_unconfirmed_candidate(object_id)

    with pytest.raises(ProfileItemNotFoundError, match="未被取代"):
        async with session_scope(get_settings()) as session:
            await service.reject_item(session, account_id=_ACCOUNT, item_id=old_id)

    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=old_id)
        grouped = await service.read_items(
            session,
            account_id=_ACCOUNT,
            support_object_id=object_id,
            include_superseded=True,
            include_candidates=True,
        )

    assert row is not None and row.confirmation == "unconfirmed", "被拒绝的否定不得落库"
    assert [item.item_id for item in grouped.candidates] == [old_id], "历史行仍可回看，不是消失"
    assert [item.item_id for item in grouped.items] == [new_id]


@pytest.mark.asyncio
async def test_unsubstituted_candidates_still_confirmable_and_rejectable() -> None:
    """防一刀切：未被取代的候选，确认与否定都照旧成功。

    没有这条，上面两条可能只是「一切都被拒」——而 `RQ-MEM-03` 的「纠」与
    第 3 节的「候选经使用者确认进稳定层」都依赖这两条路径可用。
    """
    object_id = await _new_object()
    to_confirm = await _propose(object_id, origin="ai_inference", description="待确认的推断")
    to_reject = await _propose(object_id, origin="ai_inference", description="待否定的推断")

    async with session_scope(get_settings()) as session:
        confirmed = await service.confirm_item(session, account_id=_ACCOUNT, item_id=to_confirm)
    async with session_scope(get_settings()) as session:
        rejected = await service.reject_item(session, account_id=_ACCOUNT, item_id=to_reject)

    assert confirmed.confirmation == "confirmed"
    assert rejected.confirmation == "rejected"


@pytest.mark.asyncio
async def test_delete_is_still_allowed_on_a_superseded_item() -> None:
    """新增的守卫不得误伤删除：已取代条目仍可删（`RQ-MEM-03` 的「删」）。

    确认与否定两处加的是 `superseded_by IS NULL`；`delete_item` 的判据只有归属，
    本轮不碰它。这条用例把「删除对历史条目仍允许」钉住，避免日后的守卫被
    顺手扩散成「历史条目只读」。
    """
    object_id = await _new_object()
    old_id, new_id = await _superseded_unconfirmed_candidate(object_id)

    async with session_scope(get_settings()) as session:
        await service.delete_item(session, account_id=_ACCOUNT, item_id=old_id)

    async with session_scope(get_settings()) as session:
        gone = await repo.get_item(session, item_id=old_id)
        kept = await repo.get_item(session, item_id=new_id)

    assert gone is None, "已取代条目必须仍可被物理删除"
    assert kept is not None, "取代它的新条目不受影响"


# ---------------------------------------------------------------------------
# 4. 降权（90 天，第 3 节与第 10 节验证项）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_downgraded_candidate_is_excluded_but_not_deleted() -> None:
    """把候选条目的 `last_confirmed_at` 置为 90 天前，验证：

    - 不进摘要与默认读取；
    - 被检索到时标注陈旧（`freshness = stale`，不是消失）；
    - 未被删除（第 3 节：不删除）。
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

    # 但显式检索候选时它仍在，且新鲜度标注为 stale（「被检索到时须标注其陈旧」）。
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
    """正向对照：已确认的条目即使很久没再确认，也不降权（第 3 节的用意）。"""
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
    """纠正 = 新增取代条目 + 旧条目转 `historical` 并互指，注入只含新条目。

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
    """纠正无变更被拒（契约第 1 节：422）。

    没有这条，一次空转的纠正会把一条有效认识白白变成历史态。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", description="一模一样的描述")
    with pytest.raises(ProfileDataError, match="无变更"):
        async with session_scope(get_settings()) as session:
            await service.correct_item(session, account_id=_ACCOUNT, item_id=item_id, description="一模一样的描述")


@pytest.mark.asyncio
async def test_correction_keeps_the_old_item_readable_as_history() -> None:
    """旧条目可回看（纠正不物理覆盖，第 5 节第 5 条）。"""
    object_id = await _new_object()
    old_id = await _propose(object_id, origin="user_statement", description="旧描述")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=old_id, description="新描述")
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=old_id)
    assert row is not None, "旧条目不得被物理删除"
    assert row.description == "旧描述"


@pytest.mark.asyncio
async def test_superseded_gate_is_independent_of_the_candidate_axis() -> None:
    """`include_superseded` 与 `include_candidates` 是两条独立的轴，互斥不成立。

    ① 稳定侧：只开 `include_superseded` 就能回看被取代的旧条目；
    ② 候选侧：同样只开 `include_superseded` 时，被取代的候选仍取不到
       ——历史回看不越过候选层（未确认内容不得混进稳定列表）；
    ③ 两个开关都开：被取代的候选也返回，且归 `candidates`——它仍是未确认的
       系统推断，`AC-18` 要求这类内容只能出现在「待确认」分组，归组不看它是否历史；
    ④ 注入路径不接这个开关：`resolve_for_context` 取不到任何历史条目
       （历史条目「此后不参与注入」）。
    """
    stable_object = await _new_object(name="稳定侧对象")
    stable_old = await _propose(stable_object, origin="user_statement", description="旧的稳定条目")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=stable_old, description="改写后的稳定条目")

    candidate_object = await _new_object(name="候选侧对象")
    candidate_old = await _propose(candidate_object, origin="ai_inference", description="旧的候选推断")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=candidate_old, description="改写后的候选推断")

    # ① + ④ 稳定侧。
    async with session_scope(get_settings()) as session:
        stable_view = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=stable_object, include_superseded=True
        )
        injected = await service.resolve_for_context(
            session, account_id=_ACCOUNT, support_object_id=stable_object, include_candidates=True
        )
    assert [item.description for item in stable_view.items] == ["改写后的稳定条目", "旧的稳定条目"]
    assert stable_view.candidates == []
    assert [item.description for item in injected] == ["改写后的稳定条目"], "注入路径不接历史回看开关"

    # ② 候选侧：候选轴关着，历史回看不放行。
    async with session_scope(get_settings()) as session:
        candidate_closed = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=candidate_object, include_superseded=True
        )
    assert [item.description for item in candidate_closed.items] == ["改写后的候选推断"]

    # ③ 两条轴都开：被取代的候选返回，且不改它「未确认」的标记与归组
    #    ——未确认的系统推断只能出现在「待确认」分组（`AC-18`）。
    async with session_scope(get_settings()) as session:
        candidate_open = await service.read_items(
            session,
            account_id=_ACCOUNT,
            support_object_id=candidate_object,
            include_candidates=True,
            include_superseded=True,
        )
    assert [item.description for item in candidate_open.items] == ["改写后的候选推断"]
    assert [item.description for item in candidate_open.candidates] == ["旧的候选推断"]
    assert candidate_open.candidates[0].confirmation == "unconfirmed", "历史回看不改写确认状态"
    assert candidate_open.candidates[0].freshness == "historical"


@pytest.mark.asyncio
async def test_history_is_grouped_by_the_layer_it_belonged_to() -> None:
    """历史条目的归组问「它曾属哪一层」，不问新鲜度（`AC-18` 的服务端侧保证）。

    三格逐格断言，第四格是缺省路径的回归（非历史的两格由上面两条落层分流用例钉住）：

    ① 既历史又未确认的系统推断 → `candidates`。修复前它被 `is_history` 短路进
       `items`，档案页会把一条未确认的推断当完整条目区的内容呈现；
    ② 历史且已确认（用户陈述纠正后旧条目仍是 confirmed）→ `items`：
       档案页第 62 行的「已更正」标路径；
    ③ 历史且未确认但属稳定来源（`document`）→ `items`：落层判据（第 3 节）把
       `third_party_report` 与 `document` 放进稳定层，「历史」只改新鲜度、
       不改它曾属哪一层；这一格同时钉住「未确认一律进候选组」这个过度改法；
    ④ 缺省路径（`include_superseded = false`）历史条目根本不出现，两组与改动前逐条相同。
    """
    # ① 历史 + 未确认 + 系统推断。
    inferred_object = await _new_object(name="历史候选对象")
    inferred_old = await _propose(inferred_object, origin="ai_inference", description="被取代的推断")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=inferred_old, description="改写后的推断")

    # ② 历史 + 已确认（用户陈述纠正后旧条目仍是 confirmed）。
    stated_object = await _new_object(name="历史陈述对象")
    stated_old = await _propose(stated_object, origin="user_statement", description="被取代的陈述")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=stated_old, description="改写后的陈述")

    # ③ 历史 + 未确认 + 稳定来源（document 入档即未确认，却属稳定层）。
    document_object = await _new_object(name="历史文档对象")
    document_old = await _propose(document_object, origin="document", description="被取代的文档条目")
    async with session_scope(get_settings()) as session:
        await service.correct_item(session, account_id=_ACCOUNT, item_id=document_old, description="改写后的文档条目")

    async with session_scope(get_settings()) as session:
        inferred = await service.read_items(
            session,
            account_id=_ACCOUNT,
            support_object_id=inferred_object,
            include_candidates=True,
            include_superseded=True,
        )
        stated = await service.read_items(
            session,
            account_id=_ACCOUNT,
            support_object_id=stated_object,
            include_candidates=True,
            include_superseded=True,
        )
        document = await service.read_items(
            session,
            account_id=_ACCOUNT,
            support_object_id=document_object,
            include_candidates=True,
            include_superseded=True,
        )
        # ④ 缺省路径：历史条目根本不出现（`include_superseded = false`），与改动前逐条相同。
        default = await service.read_items(session, account_id=_ACCOUNT, support_object_id=inferred_object)

    assert [item.description for item in inferred.items] == ["改写后的推断"]
    assert [item.description for item in inferred.candidates] == ["被取代的推断"]
    assert inferred.candidates[0].freshness == "historical"
    assert inferred.candidates[0].confirmation == "unconfirmed"

    assert [item.description for item in stated.items] == ["改写后的陈述", "被取代的陈述"]
    assert stated.candidates == []

    assert [item.description for item in document.items] == ["改写后的文档条目", "被取代的文档条目"]
    assert document.candidates == []

    assert [item.description for item in default.items] == ["改写后的推断"]
    assert default.candidates == []


@pytest.mark.parametrize("already_confirmed", [False, True])
@pytest.mark.asyncio
async def test_correction_rebinds_an_inferred_item_to_the_user_statement(already_confirmed: bool) -> None:
    """纠正一条推断来源的条目：新条目的生成方式重绑为 `user_statement`（零覆盖区）。

    两种起点都要走：未确认的候选，以及已被确认的候选——后者在档案页属
    「已确认条目」，是界面给出「纠正」入口的形态（档案页第 3.4 节）。
    断言四件事：

    ① 新条目 `origin = user_statement` 且 `confirmation = confirmed`（第 2、3 节）；
    ② 库中本次纠正新写入的那一条不是「候选来源 + `confirmed`」——`propose_item`
       与 Worker 对同一组合都是硬拒，第 7 节要求这种请求被拒绝而不是被写进库
       （起点是已确认候选时，旧条目本身处于该组合，那是 `confirm` 入口的合法结果，
       不属本次纠正写入的行）；
    ③ 新条目的 `source` 是档案页通道，不继承旧条目的会话来源（契约第 4 节：
       补丁式的继承会让新条目继承旧条目的来源）；
    ④ 旧条目转 `historical` 并互指，取数只含新条目。
    """
    object_id = await _new_object()
    old_id = await _propose(object_id, origin="ai_inference", description="模型推断的描述")
    if already_confirmed:
        async with session_scope(get_settings()) as session:
            await service.confirm_item(session, account_id=_ACCOUNT, item_id=old_id)

    async with session_scope(get_settings()) as session:
        new_item, superseded = await service.correct_item(
            session, account_id=_ACCOUNT, item_id=old_id, description="使用者改写的描述"
        )
    new_id = str(new_item.item_id)

    assert new_item.origin == "user_statement", "新描述是使用者写的，origin 不得沿用推断来源"
    assert new_item.confirmation == "confirmed"
    assert new_item.source == {"channel": "profile_page"}, "来源定位不得继承旧条目的会话来源"
    assert superseded.freshness == "historical"
    assert str(superseded.superseded_by) == new_id
    assert str(new_item.supersedes) == old_id

    async with session_scope(get_settings()) as session:
        rows = list(
            (
                await session.execute(
                    select(ProfileItem).where(ProfileItem.support_object_id == repo.to_object_uuid(object_id))
                )
            ).scalars()
        )
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )

    offenders = [
        row.origin
        for row in rows
        if str(row.item_id) != old_id and row.origin in _CANDIDATE_ORIGINS and row.confirmation == "confirmed"
    ]
    assert len(rows) == 2, "纠正只新增一条条目（不留下第三个半成品）"
    assert offenders == [], "纠正不得造出「推断被写成已确认」的行（第 7 节的硬约束）"
    assert grouped.candidates == [], "被取代的旧候选不再作为候选呈现"
    assert [item.description for item in grouped.items] == ["使用者改写的描述"]


@pytest.mark.asyncio
async def test_correcting_an_already_superseded_item_fails_without_rewriting_pointers() -> None:
    """对已被取代的条目再次纠正：明确失败，不静默改写 `superseded_by`（第 3 节不变量 3）。

    双击与弱网重试同一个纠正请求即命中这条路径：第二次纠正会覆写旧条目的
    `superseded_by`，让第一次产生的取代者成为悬挂指针——「谁取代了谁」只答一半。
    断言三件事：

    ① 第二次纠正抛 `ProfileItemNotFoundError`，而不是静默改写后返回 201；
    ② 旧条目的 `superseded_by` 仍指向第一次的新条目（互指未被破坏）；
    ③ 库里仍是两条条目——失败的那笔整笔回滚，不留下悬挂的新条目。
    """
    object_id = await _new_object()
    first_old = await _propose(object_id, origin="user_statement", description="第一版描述")
    async with session_scope(get_settings()) as session:
        first_new, _ = await service.correct_item(
            session, account_id=_ACCOUNT, item_id=first_old, description="第二版描述"
        )
    first_new_id = str(first_new.item_id)

    with pytest.raises(ProfileItemNotFoundError, match="已被取代"):
        async with session_scope(get_settings()) as session:
            await service.correct_item(session, account_id=_ACCOUNT, item_id=first_old, description="第三版描述")

    async with session_scope(get_settings()) as session:
        row_old = await repo.get_item(session, item_id=first_old)
        row_new = await repo.get_item(session, item_id=first_new_id)
        total = await session.scalar(
            select(func.count())
            .select_from(ProfileItem)
            .where(ProfileItem.support_object_id == repo.to_object_uuid(object_id))
        )

    assert row_old is not None and row_new is not None
    assert str(row_old.superseded_by) == first_new_id, "重复纠正不得改写 superseded_by"
    assert row_old.freshness == "historical"
    assert str(row_new.supersedes) == first_old, "反向指针不得被第二次纠正改写"
    assert total == 2, "失败的纠正必须整笔回滚，不得留下悬挂的新条目"


# ---------------------------------------------------------------------------
# 6. 删除（`AC-08`）与幂等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_the_item_from_every_read_path() -> None:
    """删除后该内容不再被取数（`AC-08`：删除须覆盖检索与衍生中的使用）。

    三条读路径都要断言：列表、摘要、上下文注入。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement", description="这条会被删除")

    async with session_scope(get_settings()) as session:
        await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)

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
async def test_delete_is_not_repeatable_after_the_row_is_gone() -> None:
    """删除不可重复：行已被物理删除后，再删报「不可访问」（404 的用例层判据）。

    条目表里没有留痕，因此第二次删除与「从未存在」在服务端不可区分——
    2026-09-30 编排器裁决 1：删除的越权与不存在一律 404，不得返回 200。
    实测重复执行三次（自检要求幂等类要求必须实测）。
    """
    object_id = await _new_object()
    item_id = await _propose(object_id, origin="user_statement")

    async with session_scope(get_settings()) as session:
        await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)

    from campfire.core.authz import AuthorizationError

    for _ in range(2):
        with pytest.raises(AuthorizationError):
            async with session_scope(get_settings()) as session:
                await service.delete_item(session, account_id=_ACCOUNT, item_id=item_id)


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
    # 删除先做归属判定（`_load_owned_item`），越权时报「不可访问」且不删任何行。
    with pytest.raises(AuthorizationError):
        async with session_scope(get_settings()) as session:
            await service.delete_item(session, account_id=_ACCOUNT_OTHER, item_id=item_id)

    # 原条目完好。
    async with session_scope(get_settings()) as session:
        row = await repo.get_item(session, item_id=item_id)
    assert row is not None and row.description == "可观察的描述"


@pytest.mark.asyncio
async def test_items_of_two_objects_are_mutually_invisible() -> None:
    """同一账号的两个对象：档案互不可见（`AC-22`）。"""
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
    """摘要只从稳定层取数，且每条带来源与时间（第 4 节）。"""
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
    """全新对象：返回「无档案」标记而不是空对象（`AC-02`、第 10 节验证项）。

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
    """摘要覆盖性：十二个字段都能从领域取值生产出来（第 10 节验证项）。

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
    """缺项不被当作否定（第 10 节验证项）：某领域无条目时，输出不声称「该情况不存在」。

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
    """八组键总是存在；未预存的组显式返回 absent（None），不为空列表（第 8 节）。

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
    """`proven_strategies` 与 `unhelpful_strategies` 取的是条目里成对相反的字段。

    这两组与 `known_triggers` 同属「触发因素与支持策略」领域，但语义是
    `helpful_support` 与 `unhelpful_support` 两个字段。若按领域取数，
    同一条条目会同时落进三组——「有效支持」与「无效支持」本是相反的两类内容，
    三者重复会让应急注入变成噪声。

    本用例的判据：一条同时带两个字段的条目，必须只出现在它对应的那一组里；
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

    # 有效支持组：字段级清单（两条），且不含无效支持。
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
    """应急预取只取稳定层：候选条目不得出现在任何一组里（第 8 节）。"""
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
    """同一条待处理记录不得产生第二条目（写入路径第 5 节：幂等键就是 `pending_id`）。

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
    """手动补充条目不经待处理记录（`pending_id` 为空），因此可以有多条。

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
    """未知领域名明确失败，不静默返回空列表（`read_profile_items` 契约第 5 节）。

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
    """写入时未知领域名明确失败，不静默归入「其他」（`propose_profile_item` 第 4 节）。"""
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
    """归档对象上的写入失败，且原因是已归档而不是越权（第 5.3 节，`AC-22` 的邻居）。"""
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

    # 但归档对象仍可纠正与删除条目（第 4 节：归档对象可读，RQ-MEM-03 不因归档失效）。
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
        await service.delete_item(session, account_id=_ACCOUNT, item_id=str(corrected.item_id))
    async with session_scope(get_settings()) as session:
        assert await repo.get_item(session, item_id=str(corrected.item_id)) is None, "归档对象下仍可删除条目"
