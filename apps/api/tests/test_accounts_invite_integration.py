"""邀请码状态机的存储层行为（真实 PostgreSQL）。

对应 `docs/技术设计/technical-details/认证与账号.md` 第 4 节。这里锁住的都是
数据库行为（条件更新的原子性、CHECK 约束、唯一约束），因此带 `integration` marker。

    docker compose up -d postgres
    uv run pytest -m integration apps/api/tests/test_accounts_invite_integration.py

逐条对应设计：

1. 一码只用一次（第 4 节可用性不变量）：并发占用只有一个成功——这是邀请码
   「一次性」的唯一依据，也是 `AC-15` 的核心。
2. 无效码绝不建号：占用失败时一切都未发生（第 1 步就拒绝，不触碰身份服务）。
3. 过期即不可占用，且判定在 `WHERE` 里（不先查后写）。
4. 补偿释放只释放未完成的占用：已绑定账号的码不可释放——否则同一个码能建两个账号。
5. 已绑定账号的码不可撤销：那是已完成的注册，改成 `revoked` 是篡改记录。
6. 词表与状态一致性落 CHECK：非法 `state`、状态与时间戳矛盾的行都被存储层拒绝。
7. 占用后 `used_by_account_id` 仍为 NULL（历史缺陷的回归测试）：第 4 节的顺序是
   「先占用、后建号」，因此占用那一刻账号尚不存在。这一条钉住下面这个真实缺陷：
   把该列纳入 `state = used` 的必填判据后，每一次注册都无法占用。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    INVITE_CODE_TTL_DAYS,
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
    """未配置 `DATABASE_URL` 时跳过——不假装通过（仓库既有集成测试的统一做法）。"""
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    yield


async def _clear() -> None:
    """清掉本文件写入的行。

    必须按签发者过滤，不能 `delete(InviteCode)` 全清（2026-09-30 实测的真实缺陷）：
    本文件与 `test_auth_registration_integration.py` 原先都做无过滤的全表删除，
    于是两个文件并发运行时互相删对方刚签发的码。
    症状是随机失败：实测一次五文件并发跑出现
    `InviteCodeNotFoundError: 邀请码不存在，无法执行 补偿释放`——而单跑该文件必然通过。
    这类「只在并发下偶发」的失败极难归因，所以这里用签发者标识把删除范围收窄到本文件。
    """
    async with session_scope(get_settings()) as session:
        await session.execute(delete(InviteCode).where(InviteCode.created_by == _OPERATOR))


async def _issue(*, now: datetime | None = None, ttl_days: int = INVITE_CODE_TTL_DAYS) -> str:
    """签发一张码并返回它（已提交）。"""
    async with session_scope(get_settings()) as session:
        record = await issue_invite_code(session, created_by=_OPERATOR, now=now, ttl_days=ttl_days)
        return record.code


# ---------------------------------------------------------------------------
# 形状校验（纯函数，但一并放在集成文件里以复用清理夹具）
# ---------------------------------------------------------------------------


def test_generated_code_matches_the_declared_shape() -> None:
    """生成的码必须符合声明的形状：长度、字符集、且不含形近字符。

    形近字符是真实失败来源——码由运营口述或手抄发给使用者（一期没有可主动触达
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
    """归一：大小写不敏感 + 剥首尾空白（口述/手抄噪声），但不剥中间。"""
    assert normalize_invite_code("  abcd2345  ") == "ABCD2345"

    # 中间空白是抄写错误，必须被拒绝而不是被猜测修补（CORE-07：无静默兜底）。
    with pytest.raises(InviteCodeFormatError):
        normalize_invite_code("ABCD 234")


def test_normalize_rejects_wrong_length_and_non_string() -> None:
    """长度不符与非字符串都在边界处变成领域异常（不是 TypeError / DBAPIError）。"""
    for bad in ("ABC", "ABCDEFGHI", ""):
        with pytest.raises(InviteCodeFormatError):
            normalize_invite_code(bad)
    for bad in (123, None, b"ABCD2345", ["ABCD2345"]):
        with pytest.raises(InviteCodeFormatError):
            normalize_invite_code(bad)


def test_normalize_rejects_non_ascii_case_folding_aliases() -> None:
    """非 ASCII 输入必须被拒——否则 4 个字符会伪装成合法的 8 位码。

    实测（2026-09-30 评审发现）：`str.upper()` 做的是 Unicode 大小写折叠，
    于是 `'ßßßß'`（4 字符）被归一成 `'SSSSSSSS'`（8 字符），恰好通过
    长度校验；`'ſſſſſſſſ'`（8 字符）同样被接受。

    这不是安全问题（生成侧只产出 ASCII 大写、碰撞概率不变），但它让
    「长度必须是 8 位」这条输入契约名不副实。修复是在 `upper()` 之前
    先按 ASCII 拒绝。

    判别性：去掉 `isascii()` 检查，本条失败（`'ßßßß'` 会被当成合法码接受）。
    """
    for alias in ("ßßßß", "ſſſſſſſſ", "ＡＢＣＤ２３４５"):
        with pytest.raises(InviteCodeFormatError, match="非 ASCII"):
            normalize_invite_code(alias)

    # 反向确认：ASCII 的等长输入仍然正常（避免把校验写成「一律拒绝」）。
    assert normalize_invite_code("abcd2345") == "ABCD2345"


def test_format_error_does_not_leak_the_code() -> None:
    """形状异常不得复述邀请码本身——它是准入凭据，会随日志扩散。

    判别性：若实现把 `raw` 拼进消息，本用例失败。

    注意字符选择：字母表刻意剔除了 `I`/`O`/`0`/`1`（形近字符，见 `models` 的说明），
    所以这些正是天然的「字符集外」样本——用 `X` 之类在字母表内的字符构造不出
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


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl_days", [0, -1, INVITE_CODE_TTL_DAYS + 1, 10**9])
async def test_issue_rejects_out_of_range_ttl(ttl_days: int) -> None:
    """有效期天数越界 → 领域异常，而不是「签发即失效」的码或 `OverflowError`。

    两个方向都是这条判定的真实失败来源：0 与负值让「签发成功」与「立即失效」
    同时成立（占用判据是 `expires_at > now()`，第 4 节），而 10**9 会让
    `datetime + timedelta` 抛 `OverflowError`——它不是 `AccountsError`，
    调用方（运营 CLI）的收口接不住，运营看到的是裸 traceback。
    `INVITE_CODE_TTL_DAYS + 1` 这一档钉住上界正好落在设计定值上，
    而不是「比它大很多才拒」。

    判别性：撤掉 `issue_invite_code` 里的区间判定，0/-1 照常写入（红在
    `pytest.raises` 未命中），另外两档以别的异常类型冒出去。
    """
    await _clear()
    try:
        async with session_scope(get_settings()) as session:
            with pytest.raises(InviteCodeFormatError, match="有效期天数"):
                await issue_invite_code(session, created_by=_OPERATOR, ttl_days=ttl_days)
    finally:
        await _clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl_days", [1, INVITE_CODE_TTL_DAYS])
async def test_issue_accepts_ttl_within_the_design_range(ttl_days: int) -> None:
    """区间内的取值必须被接受：下界 1 与设计定值 30 都合法。

    判别性：把上界判定写成 `<` 而漏掉等号，30 这一档失败；下界写成 `<= 0`
    之外的形状（例如 `< 0`）则 0 那档漏放。
    """
    await _clear()
    try:
        base = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        code = await _issue(now=base, ttl_days=ttl_days)

        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=code)
        assert record is not None
        assert record.expires_at == base + timedelta(days=ttl_days)
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 占用：原子性（本文件的核心）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_claim_succeeds_exactly_once() -> None:
    """一码只用一次：并发占用恰好一个成功（第 4 节可用性不变量的核心）。

    判别性：若实现是「先查 state 再更新」，两个并发事务都会查到自己可占用、都去改，
    于是两个都返回记录——同一个码建出两个账号（`AC-15` 被破坏）。
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
async def test_claim_is_atomic_under_a_held_lock() -> None:
    """持锁型测试：占用的条件更新必须在行锁等待结束后重新判定。

    为什么需要这一条（原并发用例证明不了原子性）：

    2026-09-30 评审实测：把 `claim_invite_code` 换成先查后写后，
    上面那条 `gather` 并发用例 5/5 通过、整个文件 26/26 通过。
    轨迹显示原因：A 的 `UPDATE` 先拿到行锁并先提交，B 的 `SELECT`
    在提交之前就已完成——`gather` 下的时序无法稳定制造「两边都完成
    `SELECT`、然后才依次 `UPDATE`」，所以那条用例只是碰巧通过。

    本用例做了什么、以及它保证什么、不保证什么（实测边界，务必读）：

    手动控制提交时机：会话 A 占用后不提交（持行锁）→ B 尝试占用 →
    确认 B 确实阻塞 → A 提交 → 断言最终只有一个成功。

    - 它能确定性抓住的：把 `WHERE` 的判定条件整体去掉（无条件 `UPDATE`）。
      实测该消融下本用例 `FAILED`（完整输出已核对）。
    - 它不能确定性抓住的：先查后写这一变体。实测两次运行结论相反
      （一次 B 占用成功 = 缺陷暴露，一次 B 在阻塞前已读到 `issued`、唤醒后
      被预检查拒绝）。原因是普通 `SELECT` 不阻塞，B 的预读发生在 A 提交之前
      还是之后取决于事件循环调度——这不是测试写得不好，而是该缺陷本身就带竞态：
      先查后写只在特定交错下出错，因此任何单次运行的用例都无法保证命中。

    所以本用例的价值是把判别力从「碰巧」提升到「覆盖无条件更新」，
    不是「保证能抓住任何非原子实现」。要彻底排除先查后写，靠的是代码评审
    与「条件必须写在 `WHERE` 里」这条纪律，而不是靠这条用例。
    把这个边界写清楚，是为了不让后来者以为「CI 绿 = 原子性已验证」。
    """
    import asyncio

    from sqlalchemy import select as sa_select

    from campfire.core.db import get_session_factory

    await _clear()
    try:
        code = await _issue()
        factory = get_session_factory(get_settings())

        session_a = factory()
        session_b = factory()
        try:
            # --- 1. A 占用但不提交（持锁）---
            claimed_a = await claim_invite_code(session_a, code=code)
            assert claimed_a.state == STATE_USED
            # 不 commit、不 rollback —— 行锁留在 A 的事务里。

            # --- 2. B 尝试占用，应阻塞在行锁上 ---
            b_task = asyncio.create_task(claim_invite_code(session_b, code=code))

            # --- 3. 确认 B 真的被阻塞（而不是已提前返回）---
            blocked = False
            for _ in range(50):
                await asyncio.sleep(0.02)
                if not b_task.done():
                    blocked = True
                    break
            assert blocked, "B 没有阻塞——本用例未能制造出锁等待，断言将失去判别力"

            # --- 4. A 提交，唤醒 B ---
            await session_a.commit()

            # --- 5. B 的结果：解锁后必须被拒 ---
            try:
                result_b = await asyncio.wait_for(b_task, timeout=10)
            except InviteCodeRejectedError:
                result_b = None
            except Exception as exc:  # noqa: BLE001 —— 任何其它异常都要报出来，不吞
                raise AssertionError(f"B 的占用以非预期方式失败：{type(exc).__name__}: {exc}") from exc

            await session_b.rollback()

            assert result_b is None, "A 已占用并提交后，B 仍然占用成功——说明判定条件没有落在 UPDATE 的 WHERE 里"

            # 库里最终只能有一次占用。
            async with session_scope(get_settings()) as session:
                row = (await session.execute(sa_select(InviteCode).where(InviteCode.code == code))).scalar_one()
            assert row.state == STATE_USED
        finally:
            await session_a.close()
            await session_b.close()
    finally:
        await _clear()
    import asyncio

    from sqlalchemy import select as sa_select

    from campfire.core.db import get_session_factory

    await _clear()
    try:
        code = await _issue()
        factory = get_session_factory(get_settings())

        session_a = factory()
        session_b = factory()
        try:
            # --- 1. A 占用但不提交（持锁）---
            claimed_a = await claim_invite_code(session_a, code=code)
            assert claimed_a.state == STATE_USED
            # 不 commit、不 rollback —— 行锁留在 A 的事务里。

            # --- 2. B 尝试占用，应阻塞在行锁上 ---
            b_task = asyncio.create_task(claim_invite_code(session_b, code=code))

            # --- 3. 确认 B 真的被阻塞（而不是已提前返回）---
            blocked = False
            for _ in range(50):
                await asyncio.sleep(0.02)
                if not b_task.done():
                    blocked = True
                    break
            assert blocked, "B 没有阻塞——本用例未能制造出锁等待，断言将失去判别力"

            # --- 4. A 提交，唤醒 B ---
            await session_a.commit()

            # --- 5. B 的结果：必须被拒（它唤醒后重新求值 WHERE）---
            try:
                result_b = await asyncio.wait_for(b_task, timeout=10)
            except InviteCodeRejectedError:
                result_b = None
            except Exception as exc:  # noqa: BLE001 —— 任何其它异常都要报出来，不吞
                raise AssertionError(f"B 的占用以非预期方式失败：{type(exc).__name__}: {exc}") from exc

            await session_b.rollback()

            assert result_b is None, (
                "A 已占用并提交后，B 仍然占用成功——说明占用不是原子的"
                "（先查后写的实现会走到这里：B 在阻塞前已读到 issued，唤醒后无条件 UPDATE）"
            )

            # 库里最终只能有一次占用。
            async with session_scope(get_settings()) as session:
                row = (await session.execute(sa_select(InviteCode).where(InviteCode.code == code))).scalar_one()
            assert row.state == STATE_USED
        finally:
            await session_a.close()
            await session_b.close()
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_claim_marks_used_but_leaves_account_null() -> None:
    """占用后 `state = used`、`used_at` 已填，但 `used_by_account_id` 仍为 NULL。

    这是第 4 节顺序的必然结果，不是遗漏：步骤 1（占用）发生在步骤 2（建号）之前，
    账号此刻尚不存在。该 NULL 同时是「码已占用但账号未建」这一中间态的排查信号。

    判别性：把 `used_by_account_id` 纳入 `state = used` 的必填判据（或写成 NOT NULL），
    本用例失败——而线上表现是每一次注册都无法占用。
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
    """过期即不可占用，且判定在 `WHERE` 里（不先查后写）。

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
    """已撤销的码与不存在的码都被拒绝，且拒绝类型相同（不可枚举）。"""
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
    """四种拒绝情形返回同一个异常类型与同一段消息（`AC-15` 要求不泄露存在性）。

    这是有意的设计（见 `errors.InviteCodeRejectedError`）：可区分的错误会让调用方
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
    """补偿释放：建号失败时把未完成的占用退回 `issued`，该码可再次被占用。"""
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
    """已绑定账号的码不可释放——否则同一个码能建出两个账号。

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
    """撤销后立即不可再用（第 4 节）。"""
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
    """已绑定账号的码不可撤销——那是已完成的注册。

    判别性：若允许撤销，历史会变成「这张码被撤销了」，而事实是「有个账号用它注册过」；
    两者对排查的含义相反，属篡改记录。去掉 `revoke_invite_code` 的第二个条件，
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
    """可从「已占用未建号」撤销：第 4 节说该中间态「由运营在撤销/重发时处理」。

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
    """非法 `state` 被存储层拒绝（词表是闭集）。"""
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
    """状态与时间戳矛盾的行被存储层拒绝。

    判别性：去掉对应的 CHECK，矛盾行就能落库，变成静默脏数据。

    三条判据的方向性由状态机决定，不是随意选的（见 `models` 的说明）：
    `issued` 是「无历史」态，两个时间戳都必须为空；`revoked` 是吸收态，反向也成立；
    而 `used_at` 只能单向蕴含——`used` 可迁到 `revoked`，届时 `used_at` 作为
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

        # 反向确认：合法的 `used → revoked` 迁移不得被约束误杀。
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
    """列举可按状态过滤，且 `limit` 收敛到服务端上界（CORE-11）。

    为什么断言要对 `created_by` 收窄：

    `list_invite_codes` / `count_invite_codes` 是全局查询（运营要看全部码，
    这是对的）。但本文件的清理按 `created_by` 收窄（并发安全的必要做法），
    因此别的测试文件或上一次运行的残留行可能同时可见。
    断言全局精确值会在那种情况下假失败——而这个测试的意图是「本文件造的那几张」。
    故：先按 `created_by` 筛出自己那几张再断言，同时仍调用真实的全局函数
    （收窄发生在断言侧，不影响被测代码）。
    """
    await _clear()
    try:
        codes = [await _issue() for _ in range(3)]
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=codes[0])

        def mine(records: list[InviteCode]) -> set[str]:
            """只取本文件签发的那些码（见 docstring 的说明）。"""
            return {r.code for r in records if r.created_by == _OPERATOR}

        async with session_scope(get_settings()) as session:
            issued = await list_invite_codes(session, state=STATE_ISSUED)
            revoked = await list_invite_codes(session, state=STATE_REVOKED)
        assert mine(issued) == set(codes[1:])
        assert mine(revoked) == {codes[0]}

        # 上界收敛：给一个荒谬的 limit，不得无界取数。
        async with session_scope(get_settings()) as session:
            bounded = await list_invite_codes(session, limit=10**9)
        assert len(bounded) <= 500

        # 全局计数包含本文件的 3 张（用 >= 而不是 ==：见 docstring）。
        async with session_scope(get_settings()) as session:
            assert await count_invite_codes(session) >= 3
            assert await count_invite_codes(session, state=STATE_ISSUED) >= 2
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_list_rejects_an_unknown_state_instead_of_returning_empty() -> None:
    """状态打错字必须显式拒绝，不能静默返回空列表。

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
    """自检：清理后本文件签发的行无残留（避免给其它测试留下脏数据）。

    断言范围是 `created_by == _OPERATOR` 而不是全表：清理本身就是按这个范围收窄的
    （并发安全的必要做法，见 `_clear`），而全表计数会看到别的测试文件的行，
    那种断言会在并发运行时假失败。
    """
    await _clear()
    async with session_scope(get_settings()) as session:
        leftover = list(
            (await session.execute(select(InviteCode.code).where(InviteCode.created_by == _OPERATOR))).scalars()
        )
    assert leftover == [], f"清理后仍残留本文件签发的邀请码：{leftover}"
