"""集成测试：`write_from_pending` 消费链路（待处理记录 → 档案条目）。

对应 `docs/技术设计/technical-details/写入路径.md` 第 4、5、6 节与
`docs/技术设计/technical-details/个性化档案.md` 第 7、8 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_consumer_integration.py

本文件守住的判据

1. 主链路：入队 → 消费 → 档案出现条目，`pending_id` 就是幂等键。
2. 授权在领取时重新判定（第 6 节）：对象在排队期间被归档 → 不写入。
3. 账号注销后不写入（墓碑的作用）：记录被删除且不产生条目。
4. 幂等：重复消费不产生第二条目（唯一约束 + 显式查重）。
5. 推断不得冒充事实：载荷声称 `confirmed` 但 `origin` 是推断 → 拒绝。
6. 载荷缺键：显式失败，不猜、不写。
7. kind 分派：`memory_episode` 被本消费者拒绝。
8. 可选字段的形状非法不得静默降级（D-41）：键缺失仍是「未提供」，但键在而形状
   不对时与必填字段同处置（显式失败、不写残缺条目）；否则条目会以不完整内容置 `done`，
   使用者与模型看到的是「已保存」。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from campfire.core.auth.tombstone_repository import record_deletion
from campfire.core.authz import set_authorizer
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.core.pending_write import (
    KIND_PROFILE_ITEM,
    STATE_DEAD,
    STATE_DONE,
    STATE_PENDING,
    PendingWrite,
    enqueue,
)
from campfire.modules.profile import repository as repo
from campfire.modules.profile import service
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.consumer import write_from_pending
from campfire.modules.profile.errors import InferredCannotBeConfirmedError, ProfileDataError
from campfire.modules.profile.models import ProfileItem, SupportObject

pytestmark = pytest.mark.integration

_ACCOUNT = "it_profile_consumer_account"
#: 注销用例专用账号（它会被写墓碑）。
_ACCOUNT_DELETED = "it_profile_consumer_deleted"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入授权实现（`write_from_pending` 在领取时要用它重新判定）。"""
    set_authorizer(OwnerAuthorizer(get_settings()))
    yield
    set_authorizer(None)


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件两个账号的数据与墓碑。"""
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    from campfire.core.auth.tombstone import AccountDeletionTombstone

    accounts = (_ACCOUNT, _ACCOUNT_DELETED)
    async with session_scope(get_settings()) as session:
        await session.execute(delete(PendingWrite).where(PendingWrite.account_id.in_(accounts)))
        await session.execute(delete(AccountDeletionTombstone).where(AccountDeletionTombstone.account_id.in_(accounts)))
        owned = select(SupportObject.id).where(SupportObject.account_id.in_(accounts))
        await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id.in_(accounts)))


async def _new_object(account: str = _ACCOUNT, name: str = "小宝") -> str:
    async with session_scope(get_settings()) as session:
        record = await service.create_object(session, account_id=account, display_name=name)
    return str(record.id)


async def _enqueue(
    object_id: str,
    *,
    origin: str = "user_statement",
    account: str = _ACCOUNT,
    payload: dict | None = None,
) -> str:
    """入队一条 `profile_item` 记录，返回其标识。"""
    body = (
        payload
        if payload is not None
        else {
            "domain": "communication",
            "topic": "表达方式",
            "description": "用图片卡表达需求",
        }
    )
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind=KIND_PROFILE_ITEM,
            account_id=account,
            origin=origin,
            payload=body,
            source={"session_id": "s1", "tool": "propose_profile_item"},
            support_object_id=object_id,
        )
    return str(record.id)


async def _item_count(object_id: str) -> int:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(ProfileItem)
                .where(ProfileItem.support_object_id == repo.to_object_uuid(object_id))
            )
        ).scalar_one()


async def _pending_state(pending_id: str) -> str:
    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(PendingWrite).where(PendingWrite.id == repo.to_item_uuid(pending_id)))
        ).scalar_one()
        return row.state


# ---------------------------------------------------------------------------
# 1. 主链路
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_record_becomes_a_profile_item() -> None:
    """入队 → 消费 → 档案出现条目，且记录置 `done` 并清租约。

    只有 `done` 算写入成功（写入路径第 2 节的不变量）：消费前必须是 `pending`。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    assert await _pending_state(pending_id) == STATE_PENDING
    assert await _item_count(object_id) == 0, "消费前不得有条目"

    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")

    assert result.written is True
    assert result.item_id is not None
    assert await _pending_state(pending_id) == STATE_DONE
    assert await _item_count(object_id) == 1

    # 条目应带上来源与生成方式（AC-07），且确认状态由 origin 推导。
    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(ProfileItem).where(ProfileItem.pending_id == repo.to_item_uuid(pending_id)))
        ).scalar_one()
    assert row.origin == "user_statement"
    assert row.confirmation == "confirmed"
    assert row.source["session_id"] == "s1"
    assert str(row.support_object_id) == object_id


@pytest.mark.asyncio
async def test_inferred_pending_record_lands_in_the_candidate_layer() -> None:
    """推断来源的待处理记录只进候选层——确认状态由 `origin` 推导，不取载荷。"""
    object_id = await _new_object()
    pending_id = await _enqueue(object_id, origin="ai_inference")

    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
    assert result.written is True

    async with session_scope(get_settings()) as session:
        grouped = await service.read_items(
            session, account_id=_ACCOUNT, support_object_id=object_id, include_candidates=True
        )
    assert grouped.items == [], "推断不得进稳定层"
    assert len(grouped.candidates) == 1


# ---------------------------------------------------------------------------
# 2. 授权在领取时重新判定（写入路径第 6 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_object_archived_while_queued_blocks_the_write() -> None:
    """消融：对象在排队期间被归档 → 领取时判定不成立，不写入（第 6 节末段）。

    这条把「授权不靠缓存判断」落到了异步路径上：记录里带着发起时的对象标识，
    但判定必须在领取时按当前态重做。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    # 排队期间归档对象。
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT, support_object_id=object_id)

    from campfire.core.authz import ObjectArchivedError

    with pytest.raises(ObjectArchivedError):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="w1")

    assert await _item_count(object_id) == 0, "归档对象不得写入条目"


@pytest.mark.asyncio
async def test_deleted_account_is_discarded_without_writing() -> None:
    """账号已注销（墓碑存在）→ 删除该记录、不写条目（墓碑的唯一运行时用途）。

    与记忆侧同一处置：用 `done` 会是谎话（什么都没写），用 `dead` 会污染
    「重试耗尽」的告警流（这不是失败，是预期内的丢弃）。
    """
    object_id = await _new_object(account=_ACCOUNT_DELETED)
    pending_id = await _enqueue(object_id, account=_ACCOUNT_DELETED)

    # 写墓碑（注销的第一步）。
    async with session_scope(get_settings()) as session:
        await record_deletion(session, account_id=_ACCOUNT_DELETED)

    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")

    assert result.written is False
    assert result.discarded is True, "必须与「没领到」区分开"
    assert await _item_count(object_id) == 0, "已注销账号不得写入条目"

    # 记录被删除（与注销第 2 步「删除该账号的待处理记录」是同一个动作）。
    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(PendingWrite).where(PendingWrite.id == repo.to_item_uuid(pending_id)))
        ).scalar_one_or_none()
    assert row is None, "已注销账号的待处理记录必须被删除"


@pytest.mark.asyncio
async def test_consume_without_authorizer_fails_closed() -> None:
    """端口未注入时消费失败（fail-closed），且不写入——最不能容忍的失败方向。"""
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)
    set_authorizer(None)
    try:
        from campfire.core.authz import AuthorizationError

        with pytest.raises(AuthorizationError):
            async with session_scope(get_settings()) as session:
                await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
        assert await _item_count(object_id) == 0
    finally:
        set_authorizer(OwnerAuthorizer(get_settings()))


# ---------------------------------------------------------------------------
# 3. 幂等（写入路径第 5 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_consumption_does_not_create_a_second_item() -> None:
    """重复消费不产生第二条目：第二次消费因记录已 `done` 而领取失败（`written=False`）。

    再模拟「记录被放回 pending 后重跑」（租约过期回收的场景）：第二次必须以
    幂等键命中并安静跳过，而不是再插一条。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    async with session_scope(get_settings()) as session:
        first = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
    assert first.written is True

    # 第二次：记录已 done，领取不到——这不是错误。
    async with session_scope(get_settings()) as session:
        second = await write_from_pending(session, pending_id=pending_id, lease_owner="w2")
    assert second.written is False
    assert await _item_count(object_id) == 1

    # 强行把记录放回 pending（模拟租约过期后的重新领取），再跑一次：
    # 必须靠幂等键跳过，仍只有一条。
    async with session_scope(get_settings()) as session:
        # 用 `update(模型)` 而不是 `PendingWrite.__table__.update()`：后者在静态上是
        # `FromClause`（`__table__` 的声明类型），没有 `update`。与 `repository.py` 同法。
        await session.execute(
            update(PendingWrite)
            .where(PendingWrite.id == repo.to_item_uuid(pending_id))
            .values(state=STATE_PENDING, lease_owner=None, lease_expires_at=None, finished_at=None)
        )
    async with session_scope(get_settings()) as session:
        third = await write_from_pending(session, pending_id=pending_id, lease_owner="w3")
    assert third.written is False, "幂等键命中时必须安静跳过"
    assert third.item_id == first.item_id, "应回报既有条目"
    assert await _item_count(object_id) == 1, "重复消费不得产生第二条目"


# ---------------------------------------------------------------------------
# 4. 载荷与硬约束
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inferred_payload_claiming_confirmed_is_rejected() -> None:
    """载荷声称 `confirmed` 但 `origin` 是推断 → 拒绝，且不写库。

    载荷是 Worker 的唯一输入，因此它不可信：确认状态必须由 `origin` 推导，
    不能采信载荷里的任何确认状态（那会让一条被构造的载荷把推断写成事实）。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(
        object_id,
        origin="ai_inference",
        payload={
            "domain": "communication",
            "topic": "表达方式",
            "description": "被构造成已确认的推断",
            "confirmation": "confirmed",
        },
    )

    with pytest.raises(InferredCannotBeConfirmedError):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
    assert await _item_count(object_id) == 0


@pytest.mark.asyncio
async def test_payload_missing_required_keys_fails_without_writing() -> None:
    """载荷缺必填键 → 显式失败且不写入（不猜、不用默认值）。"""
    object_id = await _new_object()
    pending_id = await _enqueue(object_id, payload={"domain": "communication"})

    with pytest.raises(ProfileDataError, match="description"):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
    assert await _item_count(object_id) == 0


@pytest.mark.asyncio
async def test_unknown_domain_in_payload_fails() -> None:
    """载荷里的未知领域名 → 显式失败（不静默归入「其他」）。"""
    object_id = await _new_object()
    pending_id = await _enqueue(
        object_id,
        payload={"domain": "not_a_domain", "topic": "主题", "description": "描述"},
    )
    with pytest.raises(ProfileDataError, match="领域"):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="w1")


@pytest.mark.asyncio
async def test_memory_episode_kind_is_rejected_by_the_profile_consumer() -> None:
    """`memory_episode` 被本消费者拒绝——按 kind 分派不得串台。"""
    async with session_scope(get_settings()) as session:
        record = await enqueue(
            session,
            kind="memory_episode",
            account_id=_ACCOUNT,
            origin="user_statement",
            payload={"content": "一条记忆"},
            source={"session_id": "s1"},
            support_object_id=None,
        )
        pending_id = str(record.id)

    with pytest.raises(ProfileDataError, match="memory_episode"):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="w1")


@pytest.mark.asyncio
async def test_unknown_pending_id_is_skipped_not_an_error() -> None:
    """消费不存在的 `pending_id` 返回 `written=False`，不抛异常。

    「没领到」是并发下的正常结果（已被他人领取、已终结、或记录不存在）；
    把它当异常会让兜底扫描把每次竞争都记成失败。
    """
    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id="00000000-0000-4000-8000-000000000000", lease_owner="w")
    assert result.written is False
    assert result.discarded is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["not-a-uuid", "", "  ", None, 123])
async def test_malformed_pending_id_is_a_data_error_not_a_raw_driver_error(bad_id: object) -> None:
    """畸形 `pending_id` 在入口被解析成 `ProfileDataError`（CORE-04 边界解析）。

    为什么必须有这条：`to_pending_uuid` 此前零调用点，投递方的未知值被原样透传给
    `take_for_processing`，畸形标识以裸驱动错误穿透（实测消融：`123` 得到
    `sqlalchemy.exc.ProgrammingError`，asyncpg 报
    `operator does not exist: uuid = integer`）。worker 只把 `ProfileDataError` /
    `AuthorizationError` 转 `dead`，其余走可重试登记——而登记又拿同一个畸形标识去
    查库、抛错被吞成日志，于是这条记录既不 `dead` 也永不成功。本函数 docstring
    早已承诺「形状不合法 → `ProfileDataError`」，本用例把这条承诺钉住。

    判别性：去掉 `write_from_pending` 入口的 `to_pending_uuid` 调用（或把它换回裸
    `pending_id`），本用例收到的会是驱动异常/`StatementError`，不是
    `ProfileDataError`，因此失败。
    """
    async with session_scope(get_settings()) as session:
        with pytest.raises(ProfileDataError):
            await write_from_pending(session, pending_id=bad_id, lease_owner="w1")


@pytest.mark.asyncio
async def test_optional_payload_fields_are_persisted() -> None:
    """载荷里的可选字段（情境、表现、有效支持）被如实落到条目上。"""
    object_id = await _new_object()
    pending_id = await _enqueue(
        object_id,
        payload={
            "domain": "triggers_and_support",
            "topic": "嘈杂环境",
            "description": "嘈杂时捂耳",
            "contexts": ["商场", "教室"],
            "manifestations": ["捂耳"],
            "helpful_support": ["降噪耳机"],
            "unhelpful_support": ["多人围堵"],
            "person_report": "太吵了",
            "probable_need": "需要安静",
        },
    )

    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
    assert result.written is True

    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(ProfileItem).where(ProfileItem.pending_id == repo.to_item_uuid(pending_id)))
        ).scalar_one()
    assert row.contexts == ["商场", "教室"]
    assert row.manifestations == ["捂耳"]
    assert row.helpful_support == ["降噪耳机"]
    assert row.unhelpful_support == ["多人围堵"]
    assert row.person_report == "太吵了"
    assert row.probable_need == "需要安静"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("contexts", "商场"),
        ("manifestations", 7),
        ("person_report", ["太吵了"]),
        ("probable_need", 12),
    ],
)
async def test_misshaped_optional_payload_field_fails_instead_of_being_dropped(field: str, bad_value: object) -> None:
    """可选字段形状非法时显式失败，不得静默按「未提供」处理（D-41）。

    为什么必须有这条：可选字段被无声丢弃后记录仍被置 `done`，而 `done` 是「写入成功」
    的唯一表示（写入路径第 2 节）——下游读到的是「已完成但内容缺失」的条目。
    同一份载荷里，必填字段形状不对会抛错（第 145-155 行），可选字段因此必须同一处置。

    判别性：修复前这四条都会「成功」写入（该列留空）并置 `done`，本用例红。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(
        object_id,
        payload={
            "domain": "communication",
            "topic": "表达方式",
            "description": "可选字段形状非法",
            field: bad_value,
        },
    )

    with pytest.raises(ProfileDataError, match=field):
        async with session_scope(get_settings()) as session:
            await write_from_pending(session, pending_id=pending_id, lease_owner="w1")

    assert await _item_count(object_id) == 0, "形状非法的载荷不得写出残缺条目"
    assert await _pending_state(pending_id) != STATE_DONE, "条目没写成，记录不得置 done"


@pytest.mark.asyncio
async def test_absent_optional_payload_fields_stay_optional() -> None:
    """可选字段真的可选：整键缺失仍写入成功，列取默认值——与「形状非法」分开。

    这条是上一条的正向对照：把「形状非法」改成显式失败不得顺手把可选性也取消。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(
        object_id,
        payload={"domain": "communication", "topic": "表达方式", "description": "只有必填字段"},
    )

    async with session_scope(get_settings()) as session:
        result = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
    assert result.written is True

    async with session_scope(get_settings()) as session:
        row = (
            await session.execute(select(ProfileItem).where(ProfileItem.pending_id == repo.to_item_uuid(pending_id)))
        ).scalar_one()
    assert row.contexts == []
    assert row.manifestations == []
    assert row.helpful_support == []
    assert row.unhelpful_support == []
    assert row.person_report is None
    assert row.probable_need is None


@pytest.mark.asyncio
async def test_worker_task_is_registered_for_profile_items() -> None:
    """T12 收口：worker 的 `kind = profile_item` 消费分支已接上。

    本用例是本包早期那条「范围声明」用例的到期反转：那一条解析 `worker.py` 的
    语法树、断言其中没有 import 或调用 `write_from_pending`（当时那是 T12 的范围）；
    T12 落地后它必须反过来断言「接上了」，否则它防的就不是缺口而是修复本身。

    为什么仍然用 AST 而不是子串搜索：注释里提到这个函数名是正常的（说明边界在哪），
    子串搜索会把「注释里的说明」误判成「已经接上」。只有真实的 import 与调用才是证据。
    """
    import ast
    from pathlib import Path

    worker_source = Path(__file__).resolve().parents[1] / "src" / "campfire" / "worker.py"
    tree = ast.parse(worker_source.read_text(encoding="utf-8"), filename=str(worker_source))

    # 1) 必须 import profile 的消费链路。
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "profile" in node.module:
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names if "profile" in alias.name)
    assert "write_from_pending" in imported, "worker 必须接上 profile 的消费用例（T12 的范围）"

    # 2) 必须在代码里调用它（注释里的提及不算）。
    called = {
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "write_from_pending" in called, "worker 必须真的调用 write_from_pending，而不只是 import 它"

    # 正向对照：同一份解析逻辑必须能从样本里提取出名字，
    # 否则上面的断言可能只是「解析没工作」（提取恒为空集，两个断言都会通过）。
    sample = ast.parse("from x import something_else\nsomething_else(1)\n")
    sample_names = {alias.name for node in ast.walk(sample) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "something_else" in sample_names, "解析逻辑没有工作——上面的断言无效"


@pytest.mark.asyncio
async def test_consumer_does_not_write_when_lease_is_held_by_another_worker() -> None:
    """租约未过期时另一个 Worker 领不到记录（并发的正常结果，不是错误）。

    这条钉住「`written=False` 不是失败」：兜底扫描据此不会把每次竞争记成失败。
    """
    object_id = await _new_object()
    pending_id = await _enqueue(object_id)

    async with session_scope(get_settings()) as session:
        first = await write_from_pending(session, pending_id=pending_id, lease_owner="w1")
        # 同事务内第二条记录：先把状态放回 processing 且租约未过期，模拟另一 Worker 持租约。
        await session.execute(
            update(PendingWrite)
            .where(PendingWrite.id == repo.to_item_uuid(pending_id))
            .values(
                state="processing",
                lease_owner="w-other",
                lease_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
                finished_at=None,
            )
        )
    assert first.written is True

    async with session_scope(get_settings()) as session:
        second = await write_from_pending(session, pending_id=pending_id, lease_owner="w2")
    assert second.written is False, "租约未过期时不得领取"
    assert await _item_count(object_id) == 1
    assert STATE_DEAD != await _pending_state(pending_id)
