"""邀请码状态机的存储层行为（真实 PostgreSQL）。

对应 ``docs/技术设计/technical-details/认证与账号.md`` 第 4 节。这里锁住的都是
**数据库行为**（条件更新的原子性、CHECK 约束、唯一约束），因此带 ``integration`` marker。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_accounts_invite_integration.py

## 逐条对应设计

1. **一码只用一次**（第 4 节可用性不变量）：并发占用只有一个成功——这是邀请码
   「一次性」的**唯一**依据，也是 `AC-15` 的核心。
2. **无效码绝不建号**：占用失败时**一切都未发生**（第 1 步就拒绝，不触碰身份服务）。
3. **过期即不可占用**，且判定在 `WHERE` 里（不先查后写）。
4. **补偿释放只释放未完成的占用**：已绑定账号的码不可释放——否则同一个码能建两个账号。
5. **已绑定账号的码不可撤销**：那是已完成的注册，改成 `revoked` 是篡改记录。
6. **词表与状态一致性落 CHECK**：非法 `state`、状态与时间戳矛盾的行都被**存储层**拒绝。
7. **占用后 `used_by_account_id` 仍为 NULL**（历史缺陷的回归测试）：第 4 节的顺序是
   「先占用、后建号」，因此占用那一刻账号**尚不存在**。这一条钉住下面这个真实缺陷：
   把该列纳入 `state = used` 的必填判据后，**每一次注册都无法占用**。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from campfire.core.config import get_settings
from campfire.core.db import dispose_engine, session_scope
from campfire.modules.accounts import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    InviteCode,
    InviteCodeFormatError,
    InviteCodeNotFoundError,
    InviteCodeRejectedError,
    InviteCodeStateError,
    bind_invite_code_account,
    claim_invite_code,
    count_invite_codes,
    generate_invite_code,
    get_invite_code,
    issue_invite_code,
    list_invite_codes,
    normalize_invite_code,
    release_invite_code,
    revoke_invite_code,
)
from campfire.modules.accounts.models import STATE_ISSUED, STATE_REVOKED, STATE_USED

pytestmark = pytest.mark.integration

#: 本文件的测试账号前缀。按它清理自己的行（不按 id 清，避免漏掉中途失败留下的记录）。
_ACCOUNT = "it_invite_account"

#: 测试用签发者标识。
_OPERATOR = "it_operator"


@pytest_asyncio.fixture(autouse=True)
async def _require_database() -> AsyncIterator[None]:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**（仓库既有集成测试的统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_shared_engine() -> AsyncIterator[None]:
    """每个用例前后释放共享引擎（跨事件循环复用会 ``Event loop is closed``）。"""
    await dispose_engine()
    yield
    await dispose_engine()


async def _clear() -> None:
    """清掉本文件写入的行（全部邀请码 + 本文件的账号绑定）。"""
    async with session_scope(get_settings()) as session:
        await session.execute(delete(InviteCode))


async def _issue(**kwargs: object) -> str:
    """签发一张码并返回它（已提交）。"""
    async with session_scope(get_settings()) as session:
        record = await issue_invite_code(session, created_by=_OPERATOR, **kwargs)  # type: ignore[arg-type]
        return record.code


# ---------------------------------------------------------------------------
# 形状校验（纯函数，但一并放在集成文件里以复用清理夹具）
# ---------------------------------------------------------------------------


def test_generated_code_matches_the_declared_shape() -> None:
    """生成的码必须符合声明的形状：长度、字符集、且**不含形近字符**。

    形近字符是真实失败来源——码由运营**口述或手抄**发给使用者（一期没有可主动触达
    的通道，见第 3 节）。若生成侧产出 `I`/`O`/`0`/`1`，口述歧义会直接变成注册失败。
    """
    codes = {generate_invite_code() for _ in range(200)}

    assert len(codes) == 200, "200 次生成不应出现重复（32^8 空间下碰撞概率可忽略）"
    for code in codes:
        assert len(code) == INVITE_CODE_LENGTH
        assert set(code) <= set(INVITE_CODE_ALPHABET)
    forbidden = set("IO01") & set(INVITE_CODE_ALPHABET)
    assert not forbidden, f"字母表不应含形近字符，实测含 {sorted(forbidden)}"


def test_normalize_accepts_case_and_surrounding_whitespace() -> None:
    """归一：大小写不敏感 + 剥首尾空白（口述/手抄噪声），但**不剥中间**。"""
    assert normalize_invite_code("  abcd2345  ") == "ABCD2345"

    # 中间空白是抄写错误，必须被拒绝而不是被猜测修补（CORE-07：无静默兜底）。
    with pytest.raises(InviteCodeFormatError):
        normalize_invite_code("ABCD 234")


def test_normalize_rejects_wrong_length_and_non_string() -> None:
    """长度不符与非字符串都在边界处变成**领域异常**（不是 TypeError / DBAPIError）。"""
    for bad in ("ABC", "ABCDEFGHI", ""):
        with pytest.raises(InviteCodeFormatError):
            normalize_invite_code(bad)
    for bad in (123, None, b"ABCD2345", ["ABCD2345"]):
        with pytest.raises(InviteCodeFormatError):
            normalize_invite_code(bad)


def test_format_error_does_not_leak_the_code() -> None:
    """**形状异常不得复述邀请码本身**——它是准入凭据，会随日志扩散。

    判别性：若实现把 `raw` 拼进消息，本用例失败。

    注意字符选择：字母表刻意剔除了 `I`/`O`/`0`/`1`（形近字符，见 `models` 的说明），
    所以这些正是天然的「字符集外」样本——用 `X` 之类**在**字母表内的字符构造不出
    非法输入（第一版就是这么写错的：`"ABCD234x"` 归一为大写后合法，于是压根不抛）。
    """
    for secret in ("ABCD234I", "abcd234o", "ABCD0234"):
        with pytest.raises(InviteCodeFormatError) as excinfo:
            normalize_invite_code(secret)
        assert secret not in str(excinfo.value), "异常消息复述了邀请码本身"
        assert secret.upper().strip() not in str(excinfo.value)


# ---------------------------------------------------------------------------
# 签发
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issued_code_is_usable_and_has_the_declared_ttl() -> None:
    """新签发的码是 `issued`，有效期是 30 天（第 4 节参数）。"""
    await _clear()
    try:
        base = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        code = await _issue(now=base)

        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=code)
        assert record is not None
        assert record.state == STATE_ISSUED
        assert record.used_at is None
        assert record.used_by_account_id is None
        assert record.revoked_at is None
        assert record.created_by == _OPERATOR
        assert record.expires_at == base + timedelta(days=30)
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_issue_rejects_empty_operator() -> None:
    """签发者标识为空 → 明确拒绝（`created_by` 是 `NOT NULL`，不给数据库报错的机会）。"""
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeFormatError, match="签发者"):
                await issue_invite_code(session, created_by="")
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 占用：原子性（本文件的核心）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_claim_succeeds_exactly_once() -> None:
    """**一码只用一次**：并发占用恰好一个成功（第 4 节可用性不变量的核心）。

    判别性：若实现是「先查 state 再更新」，两个并发事务都会查到自己可占用、都去改，
    于是**两个都返回记录**——同一个码建出两个账号（`AC-15` 被破坏）。本用例的
    「恰好一个成功」断言会失败。这里用两个独立会话来模拟两个并发注册请求。
    """
    await _clear()
    try:
        code = await _issue()

        async def claim() -> object:
            async with session_scope(get_settings()) as session:
                try:
                    return await claim_invite_code(session, code=code)
                except InviteCodeRejectedError as exc:
                    return exc

        results = await asyncio.gather(claim(), claim())
        winners = [r for r in results if isinstance(r, InviteCode)]
        losers = [r for r in results if isinstance(r, InviteCodeRejectedError)]

        assert len(winners) == 1, f"并发占用应恰好一个成功，实际 {len(winners)} 个成功"
        assert len(losers) == 1, "另一个必须收到明确的拒绝，而不是静默"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_claim_marks_used_but_leaves_account_null() -> None:
    """占用后 `state = used`、`used_at` 已填，但 **`used_by_account_id` 仍为 NULL**。

    **这是第 4 节顺序的必然结果，不是遗漏**：步骤 1（占用）发生在步骤 2（建号）之前，
    账号此刻尚不存在。该 NULL 同时是「码已占用但账号未建」这一中间态的**排查信号**。

    判别性：把 `used_by_account_id` 纳入 `state = used` 的必填判据（或写成 NOT NULL），
    本用例失败——而线上表现是**每一次注册都无法占用**。
    """
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            claimed = await claim_invite_code(session, code=code)

        assert claimed.state == STATE_USED
        assert claimed.used_at is not None
        assert claimed.used_by_account_id is None, "占用发生在建号之前，账号此刻必然不存在"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_claim_rejects_a_used_code() -> None:
    """已占用的码不可再占用（一次性）。"""
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError):
                await claim_invite_code(session, code=code)
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_claim_rejects_an_expired_code() -> None:
    """**过期即不可占用**，且判定在 `WHERE` 里（不先查后写）。

    判别性：若实现把过期判定写在应用层（先查出来再比时间），并发下两个请求会都读到
    「我没过期」；本用例用「签发时间早于 30 天」构造过期，仍能证明判定生效。
    """
    await _clear()
    try:
        base = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        code = await _issue(now=base)

        # 恰好过期前一秒仍可占用；过期后一秒不可占用。
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError):
                await claim_invite_code(session, code=code, now=base + timedelta(days=30, seconds=1))
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_claim_rejects_revoked_and_unknown_codes() -> None:
    """已撤销的码与不存在的码都被拒绝，且**拒绝类型相同**（不可枚举）。"""
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=code)

        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError):
                await claim_invite_code(session, code=code)
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError):
                await claim_invite_code(session, code="ZZZZZZZZ")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_rejection_does_not_distinguish_the_four_reasons() -> None:
    """**四种拒绝情形返回同一个异常类型与同一段消息**（`AC-15` 要求不泄露存在性）。

    这是**有意的**设计（见 `errors.InviteCodeRejectedError`）：可区分的错误会让调用方
    逐字判断出「这个码存在但过期」与「这个码不存在」——那就是账号枚举渠道。
    """
    await _clear()
    try:
        messages = set()

        # 1) 不存在
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError) as excinfo:
                await claim_invite_code(session, code="ZZZZZZZZ")
            messages.add(str(excinfo.value))

        # 2) 已过期
        base = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        expired = await _issue(now=base - timedelta(days=31))
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError) as excinfo:
                await claim_invite_code(session, code=expired, now=base)
            messages.add(str(excinfo.value))

        # 3) 已被占用
        used = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=used)
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError) as excinfo:
                await claim_invite_code(session, code=used)
            messages.add(str(excinfo.value))

        # 4) 已撤销
        revoked = await _issue()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=revoked)
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError) as excinfo:
                await claim_invite_code(session, code=revoked)
            messages.add(str(excinfo.value))

        assert len(messages) == 1, f"四种拒绝情形的消息必须完全一致（否则构成枚举渠道），实测 {messages}"
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 补偿释放与绑定（第 4 节步骤 3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_returns_an_unfinished_claim_to_issued() -> None:
    """**补偿释放**：建号失败时把未完成的占用退回 `issued`，该码可再次被占用。"""
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)

        async with session_scope(get_settings()) as session:
            released = await release_invite_code(session, code=code)
        assert released.state == STATE_ISSUED
        assert released.used_at is None
        assert released.used_by_account_id is None

        # 释放后可再次占用（这正是补偿的目的）。
        async with session_scope(get_settings()) as session:
            again = await claim_invite_code(session, code=code)
        assert again.state == STATE_USED
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_release_refuses_a_code_that_is_bound_to_an_account() -> None:
    """**已绑定账号的码不可释放**——否则同一个码能建出两个账号。

    判别性：去掉 `release_invite_code` 的 `used_by_account_id IS NULL` 条件，本用例
    失败（释放成功、码回到 issued、可再次占用）。
    """
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)
        async with session_scope(get_settings()) as session:
            await bind_invite_code_account(session, code=code, account_id=_ACCOUNT)

        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeStateError, match="不可释放"):
                await release_invite_code(session, code=code)

        # 码仍绑定在原账号上，未被改写。
        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=code)
        assert record is not None and record.state == STATE_USED
        assert record.used_by_account_id == _ACCOUNT
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_release_reports_missing_and_revoked_codes_distinctly() -> None:
    """释放失败时必须区分「不存在」与「状态不对」——两者对调用方含义完全不同。"""
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeNotFoundError):
                await release_invite_code(session, code="ZZZZZZZZ")

        revoked = await _issue()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=revoked)
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeStateError):
                await release_invite_code(session, code=revoked)
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_bind_records_the_account_once() -> None:
    """绑定把「已占用未建号」收敛为正常态；重复绑定显式失败（不静默覆盖）。"""
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)

        async with session_scope(get_settings()) as session:
            bound = await bind_invite_code_account(session, code=code, account_id=_ACCOUNT)
        assert bound.used_by_account_id == _ACCOUNT

        # 重复绑定（换一个账号）必须失败：静默覆盖会让「码被谁用了」失去唯一答案。
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeStateError):
                await bind_invite_code_account(session, code=code, account_id="other_account")
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 撤销
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_makes_an_issued_code_unusable() -> None:
    """撤销后**立即不可再用**（第 4 节）。"""
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            revoked = await revoke_invite_code(session, code=code)
        assert revoked.state == STATE_REVOKED
        assert revoked.revoked_at is not None

        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeRejectedError):
                await claim_invite_code(session, code=code)
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_revoke_refuses_a_code_bound_to_an_account() -> None:
    """**已绑定账号的码不可撤销**——那是已完成的注册。

    判别性：若允许撤销，历史会变成「这张码被撤销了」，而事实是「有个账号用它注册过」；
    两者对排查的含义相反，属**篡改记录**。去掉 `revoke_invite_code` 的第二个条件，
    本用例失败。
    """
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)
        async with session_scope(get_settings()) as session:
            await bind_invite_code_account(session, code=code, account_id=_ACCOUNT)

        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeStateError, match="不可撤销"):
                await revoke_invite_code(session, code=code)

        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=code)
        assert record is not None and record.state == STATE_USED, "已完成的注册不得被改成 revoked"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_revoke_accepts_an_unclaimed_occupation() -> None:
    """**可从「已占用未建号」撤销**：第 4 节说该中间态「由运营在撤销/重发时处理」。

    判别性：若撤销只允许 `issued`，运营就无法清理那些「码被占用了但建号失败」的残留
    ——本用例失败。
    """
    await _clear()
    try:
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)

        async with session_scope(get_settings()) as session:
            revoked = await revoke_invite_code(session, code=code)
        assert revoked.state == STATE_REVOKED
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_revoke_reports_missing_and_already_revoked() -> None:
    """撤销的失败分支：不存在 → `NotFound`；已撤销 → `State`（不静默成功）。"""
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeNotFoundError):
                await revoke_invite_code(session, code="ZZZZZZZZ")

        code = await _issue()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=code)
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeStateError):
                await revoke_invite_code(session, code=code)
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 存储层约束（CORE-05：不变量落最强通道）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_rejects_an_unknown_state() -> None:
    """非法 `state` 被**存储层**拒绝（词表是闭集）。"""
    await _clear()
    try:
        with pytest.raises(IntegrityError, match="ck_campfire_invite_code_state"):
            async with session_scope(get_settings()) as session:
                session.add(
                    InviteCode(
                        code="AAAA2345",
                        state="not_a_state",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                        created_by=_OPERATOR,
                    )
                )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_database_rejects_state_timestamp_contradictions() -> None:
    """**状态与时间戳矛盾的行被存储层拒绝**。

    判别性：去掉对应的 CHECK，矛盾行就能落库，变成静默脏数据。

    三条判据的**方向性由状态机决定**，不是随意选的（见 `models` 的说明）：
    `issued` 是「无历史」态，两个时间戳都必须为空；`revoked` 是吸收态，反向也成立；
    而 `used_at` **只能单向蕴含**——`used` 可迁到 `revoked`，届时 `used_at` 作为
    历史事实保留，等价断言会误杀该迁移（实测报 CheckViolationError）。
    """
    await _clear()
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=1)
    try:
        # 方向一：state = used 但 used_at 为空（「说占用了却没有时间」）。
        with pytest.raises(IntegrityError, match="ck_campfire_invite_code_used_requires_timestamp"):
            async with session_scope(get_settings()) as session:
                session.add(InviteCode(code="BBBB2345", state=STATE_USED, expires_at=future, created_by=_OPERATOR))

        # 方向二：issued 却已有 used_at（`issued` 必须无历史）。
        with pytest.raises(IntegrityError, match="ck_campfire_invite_code_issued_is_pristine"):
            async with session_scope(get_settings()) as session:
                session.add(
                    InviteCode(
                        code="CCCC2345",
                        state=STATE_ISSUED,
                        expires_at=future,
                        used_at=now,
                        created_by=_OPERATOR,
                    )
                )

        # 方向三：issued 却已有 revoked_at。
        with pytest.raises(IntegrityError, match="ck_campfire_invite_code_issued_is_pristine"):
            async with session_scope(get_settings()) as session:
                session.add(
                    InviteCode(
                        code="FFFF2345",
                        state=STATE_ISSUED,
                        expires_at=future,
                        revoked_at=now,
                        created_by=_OPERATOR,
                    )
                )

        # 方向四：state = revoked 但 revoked_at 为空。
        with pytest.raises(IntegrityError, match="ck_campfire_invite_code_revoked_at_by_state"):
            async with session_scope(get_settings()) as session:
                session.add(InviteCode(code="DDDD2345", state=STATE_REVOKED, expires_at=future, created_by=_OPERATOR))

        # 反向确认：**合法的 `used → revoked` 迁移不得被约束误杀**。
        # 这条把上面那处实测缺陷钉死——等价断言在这里会失败。
        code = await _issue()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=code)
        async with session_scope(get_settings()) as session:
            revoked = await revoke_invite_code(session, code=code)
        assert revoked.state == STATE_REVOKED
        assert revoked.used_at is not None, "撤销后 used_at 作为历史事实应保留"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_database_enforces_unique_codes() -> None:
    """`code` 是主键——同一码不可能落库两次（一次性的存储层依据）。"""
    await _clear()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    try:
        async with session_scope(get_settings()) as session:
            session.add(InviteCode(code="EEEE2345", expires_at=future, created_by=_OPERATOR))

        with pytest.raises(IntegrityError, match="pk_campfire_invite_code"):
            async with session_scope(get_settings()) as session:
                session.add(InviteCode(code="EEEE2345", expires_at=future, created_by=_OPERATOR))
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 列举与统计（运营命令的数据来源）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filters_by_state_and_is_bounded() -> None:
    """列举可按状态过滤，且 `limit` **收敛到服务端上界**（CORE-11）。"""
    await _clear()
    try:
        codes = [await _issue() for _ in range(3)]
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=codes[0])

        async with session_scope(get_settings()) as session:
            issued = await list_invite_codes(session, state=STATE_ISSUED)
            revoked = await list_invite_codes(session, state=STATE_REVOKED)
        assert {r.code for r in issued} == set(codes[1:])
        assert {r.code for r in revoked} == {codes[0]}

        # 上界收敛：给一个荒谬的 limit，不得无界取数。
        async with session_scope(get_settings()) as session:
            bounded = await list_invite_codes(session, limit=10**9)
        assert len(bounded) <= 500

        # 每次调用都必须是独立会话，避免复用同一会话导致两次查询互相影响。
        async with session_scope(get_settings()) as session:
            assert await count_invite_codes(session) == 3
            assert await count_invite_codes(session, state=STATE_ISSUED) == 2
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_list_rejects_an_unknown_state_instead_of_returning_empty() -> None:
    """状态打错字必须**显式拒绝**，不能静默返回空列表。

    判别性：静默返回空会让「这个状态下没有码」与「我把状态名打错了」无法区分——
    运营据此判断「邀请码用完了」是危险的。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeFormatError):
                await list_invite_codes(session, state="issed")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_cleanup_leaves_no_rows() -> None:
    """自检：清理后本表无残留（避免给其它测试留下脏数据）。"""
    await _clear()
    async with session_scope(get_settings()) as session:
        assert await count_invite_codes(session) == 0
