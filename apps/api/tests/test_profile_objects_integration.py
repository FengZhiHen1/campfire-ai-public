"""集成测试：支持对象生命周期、归属判定与越权文案纪律（真实 PostgreSQL）。

对应 `docs/技术设计/technical-details/支持对象.md` 第 3、4、5、6 节与
`docs/技术设计/面/profile/档案面HTTP契约.md` 第 1、2 节。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_profile_objects_integration.py

本文件守住的十条（逐条对应设计）：

1. 越权与不存在的文案逐字相同（5.3）——消融见 :func:`test_...` 的说明。
2. 归档对象可读、不可新增写入，且写路径文案区分于越权（第 4、5.3 节）。
3. 归档不删数据：归档前后档案条目数与内容一致（第 9 节验证项）。
4. 归档与恢复幂等（第 8 节）。
5. 改名不触碰档案（第 4 节）。
6. 空白 `display_name` 被存储层 CHECK 拒绝（第 9 节：直连库插入测试）。
7. 默认对象推导：绑定历史的最近一个 → 创建最早的在用对象 → 全部归档则无（第 6 节）。
8. 绑定不可变 + 首对象补绑只发生一次（第 6 节、`RQ-ACC-09`）。
9. 并发补绑：同会话两个对象先后补建，第二个无操作（对抗边界用例）。
10. 注销真删三张表（第 7 节、`AC-24`），含一个已归档对象。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from campfire.core.authz import (
    AuthorizationError,
    ObjectArchivedError,
    get_authorizer,
    require_owned,
    require_writable,
    set_authorizer,
)
from campfire.core.config import get_settings
from campfire.core.db import session_scope, to_sync_url
from campfire.modules.profile import repository as repo
from campfire.modules.profile import service
from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.models import ProfileItem, SessionObjectBinding, SupportObject
from campfire.modules.profile.purge import ProfileAccountPurger

pytestmark = pytest.mark.integration

#: 本文件的账号（避免与其它测试文件的行互相干扰）。
_ACCOUNT_A = "it_profile_account_a"
_ACCOUNT_B = "it_profile_account_b"
#: 注销用例专用账号（它会被真删，因此与其它用例隔离）。
_ACCOUNT_PURGE = "it_profile_account_purge"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——不假装通过（仓库既有集成测试的统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _authorizer() -> AsyncIterator[None]:
    """注入真实的授权实现（属主即允许），用例结束后清除。

    `autouse` 是必要的：端口的默认行为是未注入即拒绝（fail-closed），
    没有实现时每个判定都会抛异常，用例会以与业务无关的原因失败。
    """
    set_authorizer(OwnerAuthorizer(get_settings()))
    yield
    set_authorizer(None)


@pytest_asyncio.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    """清掉本文件账号的全部行（顺序：条目 → 绑定 → 对象，外键要求如此）。"""
    await _clear()
    yield
    await _clear()


async def _clear() -> None:
    """清掉本文件三个账号的全部数据。"""
    accounts = (_ACCOUNT_A, _ACCOUNT_B, _ACCOUNT_PURGE)
    async with session_scope(get_settings()) as session:
        owned = select(SupportObject.id).where(SupportObject.account_id.in_(accounts))
        await session.execute(delete(ProfileItem).where(ProfileItem.support_object_id.in_(owned)))
        await session.execute(delete(SessionObjectBinding).where(SessionObjectBinding.account_id.in_(accounts)))
        await session.execute(delete(SupportObject).where(SupportObject.account_id.in_(accounts)))


async def _make_object(account: str, name: str) -> str:
    """建一个对象，返回其标识字符串。

    标识必须在事务提交之后读：`id` 的默认值由 `core/db.new_uuid` 在 flush 时
    求值（它是 Python 侧默认值，不是数据库默认值），提交前读到的是 `None`。
    真实调用方（HTTP 层）同样在提交后才拿到标识。
    """
    async with session_scope(get_settings()) as session:
        record = await service.create_object(session, account_id=account, display_name=name)
    return str(record.id)


# ---------------------------------------------------------------------------
# 1. 越权与不存在的文案逐字相同（5.3 的判据）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foreign_object_and_missing_object_have_identical_messages() -> None:
    """越权与不存在必须给出逐字相同的文案（支持对象 5.3）。

    区分二者等于提供对象枚举通道——与登录限流「不区分账号不存在与密码错误」
    同一条纪律。本用例同时覆盖读与写两条路径（表里两行都要满足）。

    消融：把实现改成两种情形各给一句文案（例如把「不属于你」单独说出口），
    本用例立即失败——这就是它要防的回归。
    """
    object_x = await _make_object(_ACCOUNT_A, "小宝")

    # 用账号 B 的登录态请求对象 X（读路径）。
    read_foreign = None
    with pytest.raises(AuthorizationError) as foreign_reader:
        await require_owned(_ACCOUNT_B, object_x)
    read_foreign = foreign_reader.value

    # 请求一个根本不存在的对象（读路径）。
    missing = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(AuthorizationError) as missing_reader:
        await require_owned(_ACCOUNT_B, missing)

    # 写路径的两条同样必须相同。
    with pytest.raises(AuthorizationError) as foreign_writer:
        await require_writable(_ACCOUNT_B, object_x)
    with pytest.raises(AuthorizationError) as missing_writer:
        await require_writable(_ACCOUNT_B, missing)

    assert str(read_foreign) == str(missing_reader.value), "越权与不存在的读文案必须逐字相同"
    assert str(foreign_writer.value) == str(missing_writer.value), "越权与不存在的写文案必须逐字相同"
    assert str(read_foreign) == str(foreign_writer.value), "读与写路径的越权文案必须一致"

    # 反证：文案里不得出现对象标识（它会让两条消息可区分）。
    assert object_x not in str(read_foreign)
    assert missing not in str(read_foreign)


@pytest.mark.asyncio
async def test_owner_can_read_its_own_object() -> None:
    """属主自己的对象：读判定通过（对照组，证明上面的断言不是因为「一律拒绝」）。"""
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    await require_owned(_ACCOUNT_A, object_x)  # 不抛异常即通过
    await require_writable(_ACCOUNT_A, object_x)


@pytest.mark.asyncio
async def test_malformed_object_id_is_indistinguishable_from_unauthorized() -> None:
    """畸形对象标识同样归入「不可访问」，文案一致（不提供额外的区分维度）。"""
    with pytest.raises(AuthorizationError) as malformed:
        await require_owned(_ACCOUNT_A, "not-a-uuid")
    with pytest.raises(AuthorizationError) as missing:
        await require_owned(_ACCOUNT_A, "00000000-0000-4000-8000-000000000000")
    assert str(malformed.value) == str(missing.value)


# ---------------------------------------------------------------------------
# 2. 归档边界（第 4、5.3、8 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archived_object_is_readable_but_not_writable() -> None:
    """归档对象可读、不可新增写入，且写路径文案区分于越权（第 4、5.3 节）。

    三种情形一次覆盖：① 读仍成功；② 写失败且原因是「已归档」；
    ③ 归档文案 ≠ 越权文案（属主自己的对象，告知归档不泄露信息）。
    """
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    # ① 读判定仍通过（归档不等于删除）。
    await require_owned(_ACCOUNT_A, object_x)

    # ② 写判定失败，且类型是 ObjectArchivedError。
    with pytest.raises(ObjectArchivedError) as archived:
        await require_writable(_ACCOUNT_A, object_x)

    # ③ 文案与越权不同。
    with pytest.raises(AuthorizationError) as foreign:
        await require_writable(_ACCOUNT_B, object_x)

    assert str(archived.value) != str(foreign.value), "归档文案必须区分于越权"
    assert "已归档" in str(archived.value)


@pytest.mark.asyncio
async def test_archived_error_is_raised_before_any_authorization_leak() -> None:
    """别人的归档对象必须得到越权文案，而不是「已归档」（枚举通道）。

    顺序要求（5.3）：归档判定只在确认属主之后做。若先判归档，
    攻击者可以用「是否报已归档」来判定某个标识是否存在——那正是要堵的通道。
    """
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    with pytest.raises(AuthorizationError) as error:
        await require_writable(_ACCOUNT_B, object_x)

    # 不得是归档错误——必须与「对象不存在」无法区分。
    assert not isinstance(error.value, ObjectArchivedError), "别人的归档对象泄露了它的存在性"


@pytest.mark.asyncio
async def test_rename_on_archived_object_fails() -> None:
    """改名一个已归档对象明确失败（第 8 节：改名明确失败；归档才是幂等的那个）。"""
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    with pytest.raises(ObjectArchivedError):
        async with session_scope(get_settings()) as session:
            await service.rename_object(
                session, account_id=_ACCOUNT_A, support_object_id=object_x, display_name="新名字"
            )


@pytest.mark.asyncio
async def test_archive_and_restore_are_idempotent() -> None:
    """归档与恢复幂等：重复执行不报错（第 8 节）。

    实测重复执行两次（自检要求「幂等类要求必须实测重复执行」）：
    归档两次后 `archived_at` 有值；恢复两次后为空。
    """
    object_x = await _make_object(_ACCOUNT_A, "小宝")

    async with session_scope(get_settings()) as session:
        first = await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)
    assert first.archived_at is not None

    async with session_scope(get_settings()) as session:
        second = await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)
    assert second.archived_at is not None, "重复归档必须成功（幂等），不得报错"

    async with session_scope(get_settings()) as session:
        restored = await service.restore_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)
    assert restored.archived_at is None

    async with session_scope(get_settings()) as session:
        restored_again = await service.restore_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)
    assert restored_again.archived_at is None, "重复恢复必须成功（幂等）"


@pytest.mark.asyncio
async def test_archive_does_not_delete_items_and_content_is_unchanged() -> None:
    """归档不删数据：归档前后档案条目数与内容一致（第 9 节验证项）。"""
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.propose_item(
            session,
            account_id=_ACCOUNT_A,
            support_object_id=object_x,
            domain="communication",
            topic="表达方式",
            description="用图片卡表达需求",
            origin="user_statement",
            source={"session_id": "s1"},
        )

    async with session_scope(get_settings()) as session:
        before = await service.read_items(session, account_id=_ACCOUNT_A, support_object_id=object_x)
    assert len(before.items) == 1

    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    async with session_scope(get_settings()) as session:
        after = await service.read_items(session, account_id=_ACCOUNT_A, support_object_id=object_x)
    assert len(after.items) == 1, "归档不得删除档案条目"
    assert after.items[0].description == before.items[0].description, "归档不得改变条目内容"


@pytest.mark.asyncio
async def test_restore_allows_writes_again() -> None:
    """恢复后重新接受写入（第 9 节验证项）。"""
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    # 归档期间写入被拒。
    with pytest.raises(ObjectArchivedError):
        async with session_scope(get_settings()) as session:
            await service.propose_item(
                session,
                account_id=_ACCOUNT_A,
                support_object_id=object_x,
                domain="communication",
                topic="表达方式",
                description="归档期间不该写进去",
                origin="user_statement",
                source={"session_id": "s1"},
            )

    async with session_scope(get_settings()) as session:
        await service.restore_object(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    async with session_scope(get_settings()) as session:
        item = await service.propose_item(
            session,
            account_id=_ACCOUNT_A,
            support_object_id=object_x,
            domain="communication",
            topic="表达方式",
            description="恢复后可以写",
            origin="user_statement",
            source={"session_id": "s1"},
        )
    assert item.item_id is not None


# ---------------------------------------------------------------------------
# 3. 改名不触碰档案（第 4 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_does_not_touch_the_profile() -> None:
    """改名不触碰档案：历史条目的来源与内容不随改名变化（第 4 节）。"""
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.propose_item(
            session,
            account_id=_ACCOUNT_A,
            support_object_id=object_x,
            domain="communication",
            topic="表达方式",
            description="用图片卡表达需求",
            origin="user_statement",
            source={"session_id": "s1", "tool": "propose_profile_item"},
        )

    async with session_scope(get_settings()) as session:
        before = await service.read_items(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    async with session_scope(get_settings()) as session:
        await service.rename_object(session, account_id=_ACCOUNT_A, support_object_id=object_x, display_name="大宝")

    async with session_scope(get_settings()) as session:
        after = await service.read_items(session, account_id=_ACCOUNT_A, support_object_id=object_x)

    assert [item.description for item in after.items] == [item.description for item in before.items]
    # 来源（会话与工具）也不得因改名而变化。
    assert after.items[0].source == before.items[0].source


# ---------------------------------------------------------------------------
# 4. 空名拒收：不变量落在存储层（第 9 节的直连库插入测试）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blank_display_name_is_rejected_by_the_storage_layer() -> None:
    """直连数据库插入空白 `display_name`，验证 CHECK 拒绝。

    这条证明不变量落在存储层而不是只靠应用层：应用层的「先查后写」
    挡不住并发与运维直连写入，而空名会让切换器出现无法辨认的条目（第 3 节）。

    用裸 SQL 而不是 ORM，是为了绕过应用层的一切校验——被测的正是存储层。

    为什么每次尝试各自开一个连接：CHECK 违反会让当前事务进入 aborted 状态，
    该事务上的后续语句一律被拒（PostgreSQL 的语义）。用外层事务 + SAVEPOINT
    虽然也能恢复，但会掩盖「约束确实拦住了这条插入」这一判据（回滚掉就看不出
    是哪个约束报的）。每次开一条独立连接，失败彼此不干扰，判据最直接。
    """
    from sqlalchemy import create_engine

    url = get_settings().database_url
    assert url is not None
    engine = create_engine(to_sync_url(url))
    try:
        for blank in ("", "   ", "\t", "\n\t "):
            with pytest.raises(IntegrityError) as error:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO campfire_support_object (id, account_id, display_name) "
                            "VALUES (gen_random_uuid(), :account, :name)"
                        ),
                        {"account": _ACCOUNT_A, "name": blank},
                    )
            # 必须是我们那条 CHECK 拦下的，而不是别的约束（例如非空）——
            # 否则这条用例会在「非空约束」上通过，而真正的不变量未被验证。
            assert "display_name_not_blank" in str(error.value), f"空白名 {blank!r} 被别的约束拦下：{error.value}"

        # 正向对照：同样这条 SQL 用合法名字必须成功（证明失败来自名字而不是 SQL 本身）。
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO campfire_support_object (id, account_id, display_name) "
                    "VALUES (gen_random_uuid(), :account, :name)"
                ),
                {"account": _ACCOUNT_A, "name": "小宝"},
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 5. 默认对象推导（第 6 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_object_follows_the_latest_binding() -> None:
    """默认沿用最近一次绑定：同一账号建立 X、Y 并分别开过会话，取最近那次（第 6 节）。

    同时验证「没有历史时回退到创建最早的在用对象」这条第二段判据。
    """
    # 没有任何对象时：返回 None（不是错误，AC-02 同源）。
    assert await _default(_ACCOUNT_A) is None

    x = await _make_object(_ACCOUNT_A, "小宝")
    # 只有 X 时，回退路径给出 X。
    assert await _default(_ACCOUNT_A) == x

    y = await _make_object(_ACCOUNT_A, "大宝")
    assert await _default(_ACCOUNT_A) == x, "无绑定历史时应回退到创建最早的在用对象"

    # 先绑定 X，再绑定 Y：最近的绑定是 Y。
    async with session_scope(get_settings()) as session:
        await service.bind_first_object(session, session_id="s-x", account_id=_ACCOUNT_A, support_object_id=x)
    assert await _default(_ACCOUNT_A) == x

    async with session_scope(get_settings()) as session:
        await service.bind_first_object(session, session_id="s-y", account_id=_ACCOUNT_A, support_object_id=y)
    assert await _default(_ACCOUNT_A) == y, "应取 bound_at 最大的那条绑定的对象"


@pytest.mark.asyncio
async def test_no_default_object_when_every_object_is_archived() -> None:
    """全部对象归档后不再有默认对象——不回退到归档对象（第 6、9 节）。

    这不是错误：由入口引导新建（第 8 节末行）。
    """
    x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=x)

    assert await _default(_ACCOUNT_A) is None, "归档对象不得被选为默认对象"


@pytest.mark.asyncio
async def test_default_object_ignores_another_accounts_bindings() -> None:
    """默认对象推导只看当前账号的绑定（`AC-22`：两个账号互不可见）。"""
    x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.bind_first_object(session, session_id="s-a", account_id=_ACCOUNT_A, support_object_id=x)
    assert await _default(_ACCOUNT_A) == x
    assert await _default(_ACCOUNT_B) is None, "账号 B 不得看到账号 A 的绑定"


async def _default(account: str) -> str | None:
    """取某账号的默认对象（每次开新事务，模拟独立请求）。"""
    async with session_scope(get_settings()) as session:
        return await service.resolve_default_object(session, account_id=account)


# ---------------------------------------------------------------------------
# 6. 绑定不可变 + 首对象补绑只发生一次（第 6 节、RQ-ACC-09）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_object_binding_happens_once_then_never_changes() -> None:
    """首对象补绑只发生一次：会话已有绑定后再建新对象不改绑（第 6 节）。

    这是「绑定不可变」与「首对象补绑」两条规则的接缝——补绑是从无到有的首次绑定，
    不是改绑；该不变量禁止的是既有绑定的变更。
    """
    x = await _make_object(_ACCOUNT_A, "小宝")
    y = await _make_object(_ACCOUNT_A, "大宝")

    async with session_scope(get_settings()) as session:
        created = await service.bind_first_object(session, session_id="s-1", account_id=_ACCOUNT_A, support_object_id=x)
    assert created is True, "首个绑定应当真的建立"

    async with session_scope(get_settings()) as session:
        again = await service.bind_first_object(session, session_id="s-1", account_id=_ACCOUNT_A, support_object_id=y)
    assert again is False, "已有绑定的会话不得改绑"

    async with session_scope(get_settings()) as session:
        binding = await repo.get_session_binding(session, session_id="s-1")
    assert binding is not None
    assert str(binding.support_object_id) == x, "绑定必须仍是最初那个对象"


@pytest.mark.asyncio
async def test_concurrent_first_binding_second_is_a_noop() -> None:
    """对抗边界：同一会话两个对象先后补建，第二个无操作（第 6 节）。

    「判定已有绑定」用主键存在性（条件插入）而不是更新——这条用例钉住它：
    若实现改成「先查再插」或「无条件 upsert」，第二次会改绑成功，本用例失败。
    """
    x = await _make_object(_ACCOUNT_A, "小宝")
    y = await _make_object(_ACCOUNT_A, "大宝")

    async with session_scope(get_settings()) as session:
        first = await service.bind_first_object(
            session, session_id="s-race", account_id=_ACCOUNT_A, support_object_id=x
        )
    async with session_scope(get_settings()) as session:
        second = await service.bind_first_object(
            session, session_id="s-race", account_id=_ACCOUNT_A, support_object_id=y
        )

    assert (first, second) == (True, False), "两次补绑只能有一次生效"

    # 库里也只能有一行（主键保证），且指向第一个对象。
    async with session_scope(get_settings()) as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(SessionObjectBinding)
                .where(SessionObjectBinding.session_id == "s-race")
            )
        ).scalar_one()
        binding = await repo.get_session_binding(session, session_id="s-race")
    assert count == 1
    assert binding is not None and str(binding.support_object_id) == x


@pytest.mark.asyncio
async def test_binding_is_not_inferred_from_another_table() -> None:
    """绑定表不得用「有无行」回答「会话是否存在或属于谁」（第 6 节）。

    本用例的判据很直接：无绑定的会话合法存在——`get_session_binding` 返回 `None`
    而不是抛异常，且这不是「会话不存在」的表达。
    """
    async with session_scope(get_settings()) as session:
        binding = await repo.get_session_binding(session, session_id="s-never-bound")
    assert binding is None


@pytest.mark.asyncio
async def test_discarding_a_session_binding_touches_only_that_session_and_is_idempotent() -> None:
    """丢弃会话时的绑定删除：只删该会话那一行，删不存在的绑定不报错。

    唯一合法调用点是应急入口的运行起步失败补偿（那个会话的 `session_id` 从未回给
    调用方，永久不可达）。两条前提都在这里钉住：只删该会话（按账号全删会把账号下
    其它会话的绑定一起打掉），以及幂等（补偿路径可能重试，第二次是在删一个已经不存在
    的行）。

    消融：把实现换成按账号删除（`delete_session_bindings_for_account`），
    第二条断言（另一个会话的绑定还在）立即失败。
    """
    x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        await service.bind_first_object(session, session_id="s-discard", account_id=_ACCOUNT_A, support_object_id=x)
        await service.bind_first_object(session, session_id="s-keep", account_id=_ACCOUNT_A, support_object_id=x)

    async with session_scope(get_settings()) as session:
        deleted = await service.discard_session_binding(session, session_id="s-discard")
    assert deleted == 1

    async with session_scope(get_settings()) as session:
        gone = await repo.get_session_binding(session, session_id="s-discard")
        kept = await repo.get_session_binding(session, session_id="s-keep")
    assert gone is None, "被丢弃的会话不得留下绑定"
    assert kept is not None and str(kept.support_object_id) == x, "别的会话的绑定不得被牵连"

    async with session_scope(get_settings()) as session:
        again = await service.discard_session_binding(session, session_id="s-discard")
    assert again == 0, "删一个已经不存在的绑定不报错，返回 0"
    assert await _count_bindings(_ACCOUNT_A) == 1


# ---------------------------------------------------------------------------
# 7. 注销真删（第 7 节、AC-24）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_purge_removes_items_bindings_and_archived_objects() -> None:
    """注销清除：三张表都不再有该账号的行——含一个已归档对象（第 7 节、`AC-24`）。

    归档是生命周期状态，不是注销的豁免。

    消融（验证本用例有判别力）：把 purger 的 `delete_support_objects_for_account`
    去掉，本用例立即失败（对象仍在）；把删条目的那步去掉，外键会让删对象失败。
    """
    active = await _make_object(_ACCOUNT_PURGE, "在用对象")
    archived = await _make_object(_ACCOUNT_PURGE, "已归档对象")

    async with session_scope(get_settings()) as session:
        await service.propose_item(
            session,
            account_id=_ACCOUNT_PURGE,
            support_object_id=active,
            domain="communication",
            topic="表达方式",
            description="这条必须被注销删除",
            origin="user_statement",
            source={"session_id": "s1"},
        )
        await service.propose_item(
            session,
            account_id=_ACCOUNT_PURGE,
            support_object_id=archived,
            domain="communication",
            topic="表达方式",
            description="归档对象下的条目也必须被删除",
            origin="user_statement",
            source={"session_id": "s1"},
        )
        await service.bind_first_object(
            session, session_id="s-purge", account_id=_ACCOUNT_PURGE, support_object_id=active
        )
        await service.archive_object(session, account_id=_ACCOUNT_PURGE, support_object_id=archived)

    # 注销前的对照：数据确实在（否则下面的断言不成立）。
    assert await _count_objects(_ACCOUNT_PURGE) == 2
    assert await _count_items(_ACCOUNT_PURGE) == 2

    outcome = await ProfileAccountPurger(get_settings()).purge_account(_ACCOUNT_PURGE)
    assert outcome.name == "profile"

    assert await _count_objects(_ACCOUNT_PURGE) == 0, "支持对象（含已归档的）必须真删"
    assert await _count_items(_ACCOUNT_PURGE) == 0, "档案条目必须真删"
    assert await _count_bindings(_ACCOUNT_PURGE) == 0, "会话-对象绑定必须真删"


@pytest.mark.asyncio
async def test_account_purge_is_idempotent() -> None:
    """注销清除幂等：账号没有数据时正常返回，不报错（重试注销是正常路径）。"""
    purger = ProfileAccountPurger(get_settings())
    first = await purger.purge_account("it_profile_account_absent")
    second = await purger.purge_account("it_profile_account_absent")
    assert first.name == second.name == "profile"
    assert "0" in first.detail


@pytest.mark.asyncio
async def test_account_purge_does_not_touch_other_accounts() -> None:
    """注销清除只删该账号的数据：另一个账号的对象与条目必须完好。"""
    mine = await _make_object(_ACCOUNT_PURGE, "待注销")
    theirs = await _make_object(_ACCOUNT_A, "别人的对象")
    async with session_scope(get_settings()) as session:
        await service.propose_item(
            session,
            account_id=_ACCOUNT_A,
            support_object_id=theirs,
            domain="communication",
            topic="表达方式",
            description="别人的条目",
            origin="user_statement",
            source={"session_id": "s1"},
        )
    assert mine != theirs

    await ProfileAccountPurger(get_settings()).purge_account(_ACCOUNT_PURGE)

    assert await _count_objects(_ACCOUNT_A) == 1, "别的账号的对象不得被删除"
    assert await _count_items(_ACCOUNT_A) == 1, "别的账号的条目不得被删除"


async def _count_objects(account: str) -> int:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(
                select(func.count()).select_from(SupportObject).where(SupportObject.account_id == account)
            )
        ).scalar_one()


async def _count_items(account: str) -> int:
    async with session_scope(get_settings()) as session:
        owned = select(SupportObject.id).where(SupportObject.account_id == account)
        return (
            await session.execute(
                select(func.count()).select_from(ProfileItem).where(ProfileItem.support_object_id.in_(owned))
            )
        ).scalar_one()


async def _count_bindings(account: str) -> int:
    async with session_scope(get_settings()) as session:
        return (
            await session.execute(
                select(func.count()).select_from(SessionObjectBinding).where(SessionObjectBinding.account_id == account)
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# 8. 端口的 fail-closed（未注入即拒绝）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorizer_fails_closed_not_open() -> None:
    """端口未注入实现时拒绝受限操作，不降级为放行（5.3 末行）。

    这条独立于上面的 `_authorizer` 夹具：它主动清除实现，验证「装配遗漏」
    不会变成一次静默的越权——那是本项目最不能容忍的失败方向。
    """
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    set_authorizer(None)
    try:
        with pytest.raises(AuthorizationError):
            await require_owned(_ACCOUNT_A, object_x)
        assert get_authorizer() is None
    finally:
        set_authorizer(OwnerAuthorizer(get_settings()))


# ---------------------------------------------------------------------------
# 9. 列表含已归档对象（档案面契约第 2.1 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_object_list_includes_archived_with_timestamp() -> None:
    """列表含已归档对象且带 `archived_at`，前端据此标「已归档」（契约第 2.1 节）。"""
    active = await _make_object(_ACCOUNT_A, "在用")
    archived = await _make_object(_ACCOUNT_A, "已归档")
    async with session_scope(get_settings()) as session:
        await service.archive_object(session, account_id=_ACCOUNT_A, support_object_id=archived)

    async with session_scope(get_settings()) as session:
        objects = await service.list_objects(session, account_id=_ACCOUNT_A)

    by_id = {str(obj.id): obj for obj in objects}
    assert set(by_id) == {active, archived}, "列表必须含已归档对象"
    assert by_id[active].archived_at is None
    assert by_id[archived].archived_at is not None


@pytest.mark.asyncio
async def test_duplicate_display_names_are_allowed() -> None:
    """同名不拒：同一账号下两个对象可以同名（支持对象第 3 节）。"""
    first = await _make_object(_ACCOUNT_A, "小宝")
    second = await _make_object(_ACCOUNT_A, "小宝")
    assert first != second

    async with session_scope(get_settings()) as session:
        objects = await service.list_objects(session, account_id=_ACCOUNT_A)
    assert [obj.display_name for obj in objects] == ["小宝", "小宝"]


@pytest.mark.asyncio
async def test_object_timestamps_are_timezone_aware() -> None:
    """时间列必须带时区（第 3 节的列类型）——朴素时间会被解释成不同瞬间。"""
    object_x = await _make_object(_ACCOUNT_A, "小宝")
    async with session_scope(get_settings()) as session:
        record = await repo.get_support_object(session, support_object_id=object_x)
        # 数据库返回带时区的 datetime；`tzinfo` 不得为空。
        assert record is not None, "刚创建的对象必须读得回来"
        assert record.created_at.tzinfo is not None
        assert record.updated_at.tzinfo is not None
        assert isinstance(record.created_at, datetime)
        assert record.created_at <= datetime.now(timezone.utc)
