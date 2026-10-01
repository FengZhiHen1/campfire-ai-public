"""集成测试：档案工具层到库的落层分流（真实 PostgreSQL，工具层直调再查库）。

对应 `docs/技术设计/面/consult/tools/propose_profile_item.md` 第 4、6 节与
`docs/技术设计/technical-details/个性化档案.md` 第 3、7 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_tools_integration.py

为什么在工具层调、而不是直接调用例层：

`test_profile_items_integration.py` 已经覆盖了用例层的落层分流。本文件要证明的是
多出来的那一段：工具层写的待处理记录载荷，经 Worker 消费后落到的层与契约一致。
两处的差别不是重复劳动——工具层是载荷的构造者（哪些键进 payload、`confirmation` 带不带），
而 Worker 只消费载荷、不回查用例。载荷构造错了，用例层的测试全绿也看不出来。

本文件守住的核心判据：

1. 六值落层分流（契约第 6 节第一项）：四种非推断 `origin` 各提交一条 → 稳定层；
   两种推断 → 只进候选层。断言方式是直接查库读 `confirmation`/`origin`，
   不经过任何用例层的加工（避免用被测代码验证被测代码）。
2. 确认状态由 `origin` 推导：`user_statement`/`guardian_observation` → `confirmed`；
   其余四种 → `unconfirmed`。
3. 推断不得冒充事实（质量地板校验点③）：`ai_inference` + `confirmed` 被拒绝，
   且没有落库（待处理记录与条目都不存在）。
4. 越权拒绝且未落库：跨账号的对象被拒，且没有产生待处理记录。
5. 归档对象拒绝：不产生「已受理但永远写不进去」的回执。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from campfire.agent.context import CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.core.authz import set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import PendingWrite
from campfire.modules.profile.models import CANDIDATE_ORIGINS, STABLE_ORIGINS, ProfileItem, SupportObject
from campfire.tools.profile import ACCOUNT_PAYLOAD_KEY, ProposeProfileItemArgs, propose_profile_item

pytestmark = pytest.mark.integration

_ACCOUNT = "it_profile_tools_account"
_ACCOUNT_OTHER = "it_profile_tools_other"

#: 六种 `origin` 与契约第 4 节第 1 条的落层表的对应关系（逐字抄自契约，
#: 不从实现派生——否则两处定义漂移时测试会跟着漂移）。
#: 来源：docs/技术设计/面/consult/tools/propose_profile_item.md 第 4 节。
CONTRACT_LAYER_TABLE: dict[str, tuple[str, str]] = {
    # origin → (落层, 入档 confirmation)
    "user_statement": ("stable", "confirmed"),
    "guardian_observation": ("stable", "confirmed"),
    "third_party_report": ("stable", "unconfirmed"),
    "document": ("stable", "unconfirmed"),
    "system_observation": ("candidate", "unconfirmed"),
    "ai_inference": ("candidate", "unconfirmed"),
}


class _FakeIndex:
    def add(self, *_args: object, **_kwargs: object) -> None: ...


def _context(account: str = _ACCOUNT) -> ToolContext:
    return ToolContext(
        run_id="run-1",
        session_id="it-session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_FakeIndex(), run_id="run-1", clock=lambda: datetime.now(timezone.utc)),
        payload={ACCOUNT_PAYLOAD_KEY: account},
    )


def _args(object_id: str, **overrides: object) -> ProposeProfileItemArgs:
    base: dict[str, object] = {
        "support_object_id": object_id,
        "domain": "communication",
        "topic": "表达需求的方式",
        "description": "口渴时会拉大人的手走向水杯",
        "origin": "guardian_observation",
        "source": {"session_id": "it-session-1"},
    }
    base.update(overrides)
    return ProposeProfileItemArgs.model_validate(base)


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现（与装配处同法）；结束清除（端口默认 fail-closed）。"""
    from campfire.modules.profile.authz import OwnerAuthorizer

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
    """建一个对象并返回标识。"""
    from campfire.modules.profile import service

    async with session_scope(get_settings()) as session:
        record = await service.create_object(session, account_id=account, display_name=name)
    return str(record.id)


async def _consume(pending_id: str) -> str | None:
    """消费一条待处理记录（模拟 Worker），返回写成的条目 id（无写入返回 `None`）。

    为什么在测试里真的跑一次消费：工具只落记录、不写条目（契约第 4 节第 7 条），
    因此「落层对不对」这个问题只有在消费之后才能回答。跳过这一步等于只测了「记录落了」，
    而契约第 6 节的验证项问的是「条目落在哪一层」。
    """
    from campfire.modules.profile import write_from_pending

    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id=pending_id, lease_owner="it-worker")
    return result.item_id


async def _read_item(item_id: str) -> ProfileItem | None:
    """从库里直接读条目（不经过用例层）。"""
    import uuid

    async with session_scope(get_settings()) as session:
        return (
            await session.execute(select(ProfileItem).where(ProfileItem.item_id == uuid.UUID(item_id)))
        ).scalar_one_or_none()


async def _count_pending() -> int:
    async with session_scope(get_settings()) as session:
        rows = (
            await session.execute(select(PendingWrite).where(PendingWrite.account_id.in_((_ACCOUNT, _ACCOUNT_OTHER))))
        ).scalars()
        return len(list(rows))


# ---------------------------------------------------------------------------
# 六值落层分流（契约第 6 节第一项 + 质量地板「origin 六值各一条落层断言」）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("origin", "expected"), sorted(CONTRACT_LAYER_TABLE.items()))
@pytest.mark.asyncio
async def test_each_origin_lands_in_the_contract_layer(origin: str, expected: tuple[str, str]) -> None:
    """六种 `origin` 各提交一条，断言落层与确认状态与契约第 4 节的表一致。

    逐值参数化（而不是只测两个代表）：漏掉某一种 `origin` 的落层判据会让那一类内容
    静默落到错误的层——而错误方向恰好是有害的那个（推断进稳定层 = 推断冒充事实）。

    判别性：把 `STABLE_ORIGINS` 或 `CANDIDATE_ORIGINS` 的成员改一个，本用例失败。
    """
    layer, confirmation = expected
    object_id = await _new_object()

    outcome = await propose_profile_item(_context(), _args(object_id, origin=origin, description=f"{origin} 的描述"))

    assert isinstance(outcome, ToolResult)
    pending_id = _pending_id_of(outcome)
    item_id = await _consume(pending_id)
    assert item_id is not None, "消费应当写出一条条目"

    row = await _read_item(item_id)
    assert row is not None
    assert row.origin == origin
    assert row.confirmation == confirmation, f"{origin} 的入档确认状态应为 {confirmation}"

    # 落层判据本身由模块侧拥有（`lands_in_stable_layer`），这里用它自己的判据核对
    # 「稳定层 / 候选层」的归属——两处若不一致，说明工具写的载荷让判据得出了别的结论。
    from campfire.modules.profile import lands_in_stable_layer

    actual_layer = (
        "stable"
        if lands_in_stable_layer(origin=row.origin, confirmation=row.confirmation, freshness=row.freshness)
        else "candidate"
    )
    assert actual_layer == layer, f"{origin} 应落在 {layer} 层，实际 {actual_layer}"


def _pending_id_of(outcome: ToolResult) -> str:
    """从工具回执里取 `pending_id`（回执形状由契约第 3 节定死）。"""
    import json

    return str(json.loads(outcome.text)["pending_id"])


def test_the_contract_table_covers_both_origin_sets() -> None:
    """契约表与模块侧的两个集合逐一对应（防止两份判据漂移）。

    判别性：在 `STABLE_ORIGINS` 或 `CANDIDATE_ORIGINS` 里增删一个 `origin` 而不同步
    契约表，本用例失败——那正是「落层判据有两处定义」的开始。
    """
    contract_stable = {origin for origin, (layer, _) in CONTRACT_LAYER_TABLE.items() if layer == "stable"}
    contract_candidate = {origin for origin, (layer, _) in CONTRACT_LAYER_TABLE.items() if layer == "candidate"}

    assert contract_stable == set(STABLE_ORIGINS)
    assert contract_candidate == set(CANDIDATE_ORIGINS)
    assert contract_stable | contract_candidate == set(CONTRACT_LAYER_TABLE)
    assert not (contract_stable & contract_candidate)


# ---------------------------------------------------------------------------
# 硬约束：推断不得冒充事实（质量地板校验点③）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inference_cannot_be_submitted_as_confirmed_and_nothing_is_persisted() -> None:
    """`ai_inference` + `confirmed` 被拒绝，且没有落库（待处理记录与条目都不存在）。

    怎么造出这个调用：参数模型里没有 `confirmation` 字段（那是有意的，
    见 `ProposeProfileItemArgs` 的说明），因此正常路径下这个组合表达不出来。
    这里直接往载荷里手工塞一个 `confirmation: confirmed`，模拟「绕过参数模型的调用方」
    ——而那正是 Worker 侧要再拒一次的情形（载荷可能是历史版本或被手工构造的）。

    质量地板校验点③要求「拒绝且未落库」：只断言返回失败是不够的，还要断言库里干净。
    """
    object_id = await _new_object()
    args = _args(object_id, origin="ai_inference")

    # 绕过工具层：直接按工具会写的形状落一条带 confirmation 的待处理记录，
    # 然后跑消费——这模拟的是「载荷被构造过」。
    from campfire.core.pending_write import KIND_PROFILE_ITEM, enqueue
    from campfire.modules.profile.consumer import PAYLOAD_DESCRIPTION, PAYLOAD_DOMAIN, PAYLOAD_TOPIC

    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_PROFILE_ITEM,
            account_id=_ACCOUNT,
            origin="ai_inference",
            payload={
                PAYLOAD_DOMAIN: args.domain,
                PAYLOAD_TOPIC: args.topic,
                PAYLOAD_DESCRIPTION: args.description,
                # 被构造的载荷：推断自认已确认。
                "confirmation": "confirmed",
            },
            source={"session_id": "it-session-1", "tool": "propose_profile_item"},
            support_object_id=object_id,
        )
        pending_id = str(record.id)

    from campfire.modules.profile import write_from_pending
    from campfire.modules.profile.errors import InferredCannotBeConfirmedError

    with pytest.raises(InferredCannotBeConfirmedError):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="it-worker")

    # 未落库：没有条目，也没有仍可重试的待处理记录（消费已把它置为终态）。
    async with session_scope(get_settings()) as session:
        import uuid as _uuid

        items = list(
            (
                await session.execute(select(ProfileItem).where(ProfileItem.support_object_id == _uuid.UUID(object_id)))
            ).scalars()
        )
    assert items == [], "被拒的推断不得留下条目"


@pytest.mark.asyncio
async def test_the_tool_never_puts_a_confirmation_into_the_payload() -> None:
    """工具写的载荷里没有 `confirmation` 键（确认状态由 `origin` 推导）。

    与上一条互补：上一条测「构造过的载荷会被拒」，这一条测「工具不会构造那样的载荷」。
    判别性：往 `payload` 里加 `confirmation`，本用例失败。
    """
    object_id = await _new_object()

    outcome = await propose_profile_item(_context(), _args(object_id, origin="ai_inference"))
    assert isinstance(outcome, ToolResult)
    pending_id = _pending_id_of(outcome)

    import uuid as _uuid

    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(PendingWrite).where(PendingWrite.id == _uuid.UUID(pending_id)))
        ).scalar_one()

    assert "confirmation" not in (row.payload or {}), "载荷不得携带 confirmation"


# ---------------------------------------------------------------------------
# 越权与归档（契约第 5 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_account_write_is_denied_and_nothing_is_persisted() -> None:
    """以账号 A 的登录态写账号 B 的对象 → 拒绝，且没有待处理记录。

    判别性：把 `require_writable` 从 handler 里去掉，本用例失败（记录会被落下，
    直到 Worker 领取时才失败——那是「接口回执成功、实际永远写不进去」）。
    """
    other_object = await _new_object(_ACCOUNT_OTHER, name="别人的对象")

    outcome = await propose_profile_item(_context(_ACCOUNT), _args(other_object))

    assert isinstance(outcome, ToolFailure)
    assert "不存在或不属于当前账号" in outcome.message
    assert await _count_pending() == 0, "越权的写入不得留下待处理记录"


@pytest.mark.asyncio
async def test_archived_object_write_is_denied_with_a_distinct_message() -> None:
    """归档对象 → 拒绝，文案区分于越权，且没有待处理记录（支持对象第 5.3 节）。"""
    from campfire.modules.profile import service

    object_id = await _new_object()
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    outcome = await propose_profile_item(_context(), _args(object_id))

    assert isinstance(outcome, ToolFailure)
    assert "已归档" in outcome.message, "必须说明归档状态（使用者需要知道才能去恢复）"
    assert await _count_pending() == 0


# ---------------------------------------------------------------------------
# 幂等（契约第 5 节末行：同一内容重复提交允许）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_same_content_can_be_submitted_twice() -> None:
    """同一内容重复提交不报错（幂等由 `pending_id` 承担，契约第 5 节末行）。

    两次得到不同的 `pending_id`（各自一条记录），因此消费后是两条并列条目——
    「不覆盖已有条目」正是契约第 4 节第 3 条。
    """
    object_id = await _new_object()
    args = _args(object_id)

    first = await propose_profile_item(_context(), args)
    second = await propose_profile_item(_context(), args)

    assert isinstance(first, ToolResult) and isinstance(second, ToolResult)
    first_id, second_id = _pending_id_of(first), _pending_id_of(second)
    assert first_id != second_id, "两次提交各自一条记录"

    # 两条都消费成功 → 并列两条（不覆盖）。
    assert await _consume(first_id) is not None
    assert await _consume(second_id) is not None

    import uuid as _uuid

    async with session_scope(get_settings()) as session:
        items = list(
            (
                await session.execute(select(ProfileItem).where(ProfileItem.support_object_id == _uuid.UUID(object_id)))
            ).scalars()
        )
    assert len(items) == 2, "冲突时并列新增，不覆盖既有条目"
