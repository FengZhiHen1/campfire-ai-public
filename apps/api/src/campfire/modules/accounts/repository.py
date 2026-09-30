"""邀请码的发放、原子占用、补偿释放与撤销。

本模块是**邀请码状态机的唯一实现**：其它地方（注册复写、运营 CLI）只调用这里，
不自己写 ``UPDATE ... SET state=...``——否则状态判据会散落成多份，也就没有
「唯一所有者」了（与 `core/pending_write/repository.py` 同一种纪律）。

形状由[认证与账号](../../../../../../docs/技术设计/technical-details/认证与账号.md)
第 4 节拥有。命名与锁法对齐 `core/pending_write/repository.py`。

## 为什么占用必须是「条件更新 + RETURNING」

第 4 节明文要求「以条件更新判定成败，**不先查后写**」。先查后写会让两个并发请求
都读到自己可占、都去改，于是**同一个码建出两个账号**——邀请码的「一次性」正是靠
这一步的原子性成立的（`AC-15`）。

    UPDATE ... SET state='used', used_at=now()
    WHERE code = ? AND state = 'issued' AND expires_at > now()
    RETURNING ...

数据库的行锁保证只有一个事务能把它从 `issued` 改成 `used`；另一个的 ``WHERE`` 不再
匹配、``RETURNING`` 为空 → 调用方**明确知道没占到**，而不是猜。

## 占用的提交时机（这一点不能省）

**占用必须在调用身份服务之前独立提交**，不能挂在外层请求事务上。理由是一个真实的
崩溃窗口：若占用与建号同属一个未提交事务，则在「core 已建号」与「事务提交」之间崩溃
时，占用**从未落库**——同一个码可以再次被使用，建出第二个账号（`AC-15` 被静默破坏）。
因此本模块的占用函数**要求调用方传入已提交的会话**，并在 docstring 里写明该契约。

## 「补偿释放」为什么不破坏一次性

第 4 节第 3 步允许建号失败时把码退回 `issued`。释放**不是**放宽不变量：它撤销的是一次
**未完成的**占用，因此释放带硬条件——``state = 'used' AND used_by_account_id IS NULL``。
已绑定账号的码（真正用掉的）**不可能**被释放，已撤销的码也不会被复活。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.accounts.errors import (
    InviteCodeFormatError,
    InviteCodeNotFoundError,
    InviteCodeRejectedError,
    InviteCodeStateError,
)
from campfire.modules.accounts.models import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    INVITE_CODE_TTL_DAYS,
    MAX_ACCOUNT_ID_LENGTH,
    MAX_OPERATOR_LENGTH,
    STATE_ISSUED,
    STATE_REVOKED,
    STATE_USED,
    InviteCode,
)

#: 生成邀请码时的重试上界（CORE-11：循环必有显式上界）。
#:
#: 取值理由：码空间是 32^8 ≈ 1.1e12，即使已有 100 万张码，单次碰撞概率也约 1e-6，
#: 连续 5 次碰撞的概率可忽略。上界存在的意义不是「可能撞满」，而是**不让一个理论上的
#: 死循环存在**——若码空间因配置变化被收窄（例如改短长度），必须有明确失败而不是转圈。
MAX_CODE_GENERATION_ATTEMPTS = 5

#: 单次列举的条数上界（CORE-11）。``invite list`` 是运营命令，积压时不该拖住终端。
LIST_MAX_LIMIT = 500

#: 列举的默认条数。
LIST_DEFAULT_LIMIT = 50

#: 邀请码字符集的正则判据长度（与 `INVITE_CODE_LENGTH` 一致）。
_ALPHABET_SET = frozenset(INVITE_CODE_ALPHABET)


def _utc_now() -> datetime:
    """当前 UTC 时间。集中一处，便于测试替换时只有一个改动点。"""
    return datetime.now(timezone.utc)


def normalize_invite_code(raw: object) -> str:
    """把外部传入的邀请码归一并校验**形状**（CORE-04：数据边界运行时解析）。

    **为什么归一而不是原样比较**：码由运营**口述或手抄**交给使用者（一期账号没有
    可主动触达的联系通道，见第 3 节），大小写与首尾空白是真实的输入噪声。生成侧
    **只产出大写**，因此把输入统一成大写在语义上是安全的——不存在「两个不同的码
    因归一而变成同一个」（那需要生成侧产出小写或大小写混合）。

    只剥**首尾**空白，不剥中间：``"ABCD 1234"`` 是抄写错误，应当被拒绝而不是被猜测
    修补（``CORE-07``：无静默兜底——猜错了会占用到另一个码）。

    Args:
        raw: 使用者或调用方给出的邀请码，**类型未知**（运行时边界）。

    Returns:
        可用于等值比较的规范化邀请码。

    Raises:
        InviteCodeFormatError: 非字符串、长度不符或含字符集外的字符。
            **异常不携带被拒的值**（见 `errors` 模块说明）。
    """
    if not isinstance(raw, str):
        raise InviteCodeFormatError(f"必须是字符串，收到 {type(raw).__name__}")
    normalized = raw.strip().upper()
    if len(normalized) != INVITE_CODE_LENGTH:
        raise InviteCodeFormatError(f"长度必须是 {INVITE_CODE_LENGTH} 位（收到 {len(normalized)} 位）")
    invalid = sorted({character for character in normalized if character not in _ALPHABET_SET})
    if invalid:
        # 不复述完整邀请码（它是准入凭据）；只报出非法字符，足够排查输入问题。
        raise InviteCodeFormatError(f"含字符集外的字符：{' '.join(invalid)}")
    return normalized


def generate_invite_code() -> str:
    """生成一个随机邀请码（**不做查重**，查重由插入时的主键约束承担）。

    用 :func:`secrets.choice` 而不是 ``random``：前者是密码学安全的随机源，
    后者的输出可被预测——可预测的邀请码等于没有邀请码（``AC-15``）。

    **每个字符独立取 5 bit**（字母表 32 个字符），8 字符共 **40 bit**。
    """
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


async def issue_invite_code(
    session: AsyncSession,
    *,
    created_by: str,
    now: datetime | None = None,
    ttl_days: int = INVITE_CODE_TTL_DAYS,
    max_attempts: int = MAX_CODE_GENERATION_ATTEMPTS,
) -> InviteCode:
    """签发一张邀请码（运营操作，经 CLI 调用）。

    **碰撞处理**：随机码可能撞上已有的码（主键冲突）。这里用「生成 → 插入 → 冲突则
    重试」而不是「先查重再插入」——后者在并发下仍有窗口，而主键约束是**存储层**的
    唯一真源（``CORE-05``：不变量落最强通道）。为避免把整个会话置于失败状态，
    每次尝试前用 ``savepoint`` 隔离冲突。

    Args:
        session: 关系库会话（**调用方负责提交**）。
        created_by: 签发者标识（运营者）。见 `models.MAX_OPERATOR_LENGTH` 的说明：
            **这不是审计身份**，只是「哪台机器的哪个 OS 用户签发的」。
        now: 参照时间，默认当前 UTC。签发时间即此值。
        ttl_days: 有效期天数（默认 `INVITE_CODE_TTL_DAYS`）。
        max_attempts: 生成重试上界。

    Returns:
        已加入会话的邀请码记录（**尚未提交**）。

    Raises:
        InviteCodeFormatError: `created_by` 为空或超宽——属配置/调用方错误。
        InviteCodeStateError: 连续 `max_attempts` 次都碰撞（码空间或被配置收窄）。
    """
    if not created_by:
        raise InviteCodeFormatError("签发者标识（created_by）不得为空")
    if len(created_by) > MAX_OPERATOR_LENGTH:
        raise InviteCodeFormatError(f"签发者标识超过 {MAX_OPERATOR_LENGTH} 字符上界")

    reference = now if now is not None else _utc_now()
    expires_at = reference + timedelta(days=ttl_days)

    for _ in range(max(1, max_attempts)):
        record = InviteCode(
            code=generate_invite_code(),
            state=STATE_ISSUED,
            expires_at=expires_at,
            created_by=created_by,
            created_at=reference,
        )
        # savepoint：主键冲突只回滚这一次尝试，不连带毁掉调用方在同一会话里
        # 已经做过的其它工作（`session.begin_nested()` 在 SQLAlchemy 2 里即 SAVEPOINT）。
        try:
            async with session.begin_nested():
                session.add(record)
        except Exception:  # noqa: BLE001 —— 只可能是唯一冲突，重试；耗尽后如实报错
            continue
        return record

    raise InviteCodeStateError(
        STATE_ISSUED,
        f"连续 {max_attempts} 次生成的邀请码都与既有码冲突（码空间是否被收窄？）",
    )


async def claim_invite_code(
    session: AsyncSession,
    *,
    code: object,
    now: datetime | None = None,
) -> InviteCode:
    """**原子占用**一张邀请码（第 4 节步骤 1）。注册路径的第一道、也是唯一一道准入判据。

    **调用契约（不能省）**：调用方必须在调用**身份服务建号之前**把本事务提交。
    占用是个**独立的**存储事实——见模块说明「占用的提交时机」。

    Args:
        session: 关系库会话（**调用方负责提交**）。
        code: 邀请码（运行时边界，先经 :func:`normalize_invite_code` 校验形状）。
        now: 参照时间，默认当前 UTC。同时用于过期判定与 `used_at`。

    Returns:
        占用成功的邀请码记录（`state = used`、`used_at` 已填、
        **`used_by_account_id` 仍为 NULL**——账号此刻尚不存在）。

    Raises:
        InviteCodeFormatError: 形状不合法。
        InviteCodeRejectedError: **未占用成功**——不存在、已过期、已被占用或已被撤销。
            四者合并见 `errors.InviteCodeRejectedError` 的说明（不可枚举）。
    """
    normalized = normalize_invite_code(code)
    reference = now if now is not None else _utc_now()

    statement = (
        update(InviteCode)
        .where(
            InviteCode.code == normalized,
            # 可占用的全部条件都进 `WHERE`：判定与占用在**一条 SQL** 内完成。
            # 过期判定也在此处（而不是先查出来再比时间）——先查后写会让两个并发
            # 请求都读到「我没过期」。
            InviteCode.state == STATE_ISSUED,
            InviteCode.expires_at > reference,
        )
        .values(state=STATE_USED, used_at=reference)
        .returning(InviteCode)
    )
    claimed = (await session.execute(statement)).scalar_one_or_none()
    if claimed is None:
        # 四种情形在此合并。**刻意不区分**：区分即账号枚举渠道（第 5 节）。
        raise InviteCodeRejectedError("邀请码无效、已过期、已被使用或已被撤销")
    return claimed


async def release_invite_code(
    session: AsyncSession,
    *,
    code: object,
    now: datetime | None = None,
) -> InviteCode:
    """**补偿释放**：把一次未完成的占用退回 `issued`（第 4 节步骤 3）。

    只在建号失败时调用。**硬条件**（`WHERE` 里）保证它不破坏一次性：

    - ``state = 'used'``：只释放「已占用」的码；
    - ``used_by_account_id IS NULL``：**已绑定账号的码不可释放**——那是真正用掉的码，
      释放它等于让同一个码再建一个账号；
    - **查不到就报错，不静默成功**：并发下若运营已撤销该码，本次释放应当被调用方知道
      （它意味着「建号失败」与「码被撤销」两件事同时发生，需要人工判断）。

    Args:
        session: 关系库会话（**调用方负责提交**）。
        code: 邀请码。
        now: 参照时间（仅用于诊断，不写入——释放要清空 `used_at`）。

    Returns:
        释放后的记录（`state = issued`，`used_at` / `used_by_account_id` 已清空）。

    Raises:
        InviteCodeFormatError: 形状不合法。
        InviteCodeNotFoundError: 该码不存在。
        InviteCodeStateError: 该码不处于「可释放」的状态（已绑定账号，或已被撤销）。
    """
    normalized = normalize_invite_code(code)
    statement = (
        update(InviteCode)
        .where(
            InviteCode.code == normalized,
            InviteCode.state == STATE_USED,
            InviteCode.used_by_account_id.is_(None),
        )
        .values(state=STATE_ISSUED, used_at=None, used_by_account_id=None)
        .returning(InviteCode)
    )
    released = (await session.execute(statement)).scalar_one_or_none()
    if released is not None:
        return released

    # 没释放成功：必须区分「不存在」与「状态不对」——两者对调用方的含义完全不同。
    current = await get_invite_code(session, code=normalized)
    if current is None:
        raise InviteCodeNotFoundError("补偿释放")
    raise InviteCodeStateError(current.state, "补偿释放（已绑定账号的占用不可释放）")


async def bind_invite_code_account(
    session: AsyncSession,
    *,
    code: object,
    account_id: str,
    now: datetime | None = None,
) -> InviteCode:
    """把已占用的邀请码绑定到建好的账号（第 4 节步骤 2 成功后的回填）。

    **为什么必须回填**：不回填就只能回答「这张码被用掉了」，回答不了「被谁用掉了」——
    而运营排查「某人说码用不了」时正需要这条链路（见 `errors.InviteCodeRejectedError`
    里那句「代价如实写明」）。它是本表**唯一**的账号关联，也是把
    「已占用未建号」这一中间态收敛为正常态的终点。

    Args:
        session: 关系库会话（**调用方负责提交**）。
        code: 邀请码。
        account_id: 建号成功得到的账号标识（即身份服务的用户标识，第 3 节）。
        now: 参照时间（仅用于诊断，不写入——绑定不改变时间戳）。

    Returns:
        绑定后的记录。

    Raises:
        InviteCodeFormatError: 邀请码形状不合法，或 `account_id` 为空/超宽。
        InviteCodeNotFoundError: 该码不存在。
        InviteCodeStateError: 该码不是「已占用且尚未绑定」的状态。
    """
    normalized = normalize_invite_code(code)
    if not account_id:
        raise InviteCodeFormatError("账号标识不得为空")
    if len(account_id) > MAX_ACCOUNT_ID_LENGTH:
        raise InviteCodeFormatError(f"账号标识超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界")

    statement = (
        update(InviteCode)
        .where(
            InviteCode.code == normalized,
            InviteCode.state == STATE_USED,
            InviteCode.used_by_account_id.is_(None),
        )
        .values(used_by_account_id=account_id)
        .returning(InviteCode)
    )
    bound = (await session.execute(statement)).scalar_one_or_none()
    if bound is not None:
        return bound

    current = await get_invite_code(session, code=normalized)
    if current is None:
        raise InviteCodeNotFoundError("绑定账号")
    raise InviteCodeStateError(current.state, "绑定账号")


async def revoke_invite_code(
    session: AsyncSession,
    *,
    code: object,
    now: datetime | None = None,
) -> InviteCode:
    """撤销一张邀请码（运营操作）。撤销后**立即不可再用**（第 4 节）。

    **可从哪两种状态撤销**（判据取自第 4 节的两句话）：

    - ``issued``——正常情形：撤销一张还没被用的码；
    - ``used`` 且 ``used_by_account_id IS NULL``——第 4 节明确「码已占用但账号未建」
      这一中间态「由运营在撤销/重发时处理」，撤销正是该处理动作之一。

    **不可从「已绑定账号」的 ``used`` 撤销**：那是已完成的注册。把它改成 `revoked`
    会让历史看起来像「这张码被撤销了」，而事实是「有个账号用它注册过」——两者对排查的
    含义相反，属**篡改记录**而非撤销。

    Args:
        session: 关系库会话（**调用方负责提交**）。
        code: 邀请码。
        now: 参照时间，默认当前 UTC。写入 `revoked_at`。

    Returns:
        撤销后的记录（`state = revoked`）。

    Raises:
        InviteCodeFormatError: 形状不合法。
        InviteCodeNotFoundError: 该码不存在。
        InviteCodeStateError: 该码已绑定账号（不可撤销），或已是 `revoked`。
    """
    normalized = normalize_invite_code(code)
    reference = now if now is not None else _utc_now()

    statement = (
        update(InviteCode)
        .where(
            InviteCode.code == normalized,
            InviteCode.state != STATE_REVOKED,
            # 已绑定账号的码不可撤销：见 docstring。
            (InviteCode.state == STATE_ISSUED) | (InviteCode.used_by_account_id.is_(None)),
        )
        .values(state=STATE_REVOKED, revoked_at=reference)
        .returning(InviteCode)
    )
    revoked = (await session.execute(statement)).scalar_one_or_none()
    if revoked is not None:
        return revoked

    current = await get_invite_code(session, code=normalized)
    if current is None:
        raise InviteCodeNotFoundError("撤销")
    raise InviteCodeStateError(current.state, "撤销（已绑定账号的邀请码不可撤销）")


async def get_invite_code(session: AsyncSession, *, code: object) -> InviteCode | None:
    """按码取一条记录（**运营排查用**）。不存在返回 ``None``。

    与 :func:`claim_invite_code` 的分工：这个**不改变状态**，因此可以用在
    「码用不了，帮我看看」这类只读排查上，也是 `release` / `bind` / `revoke`
    在条件更新未命中时用来区分「不存在」与「状态不对」的依据。

    Raises:
        InviteCodeFormatError: 形状不合法。
    """
    normalized = normalize_invite_code(code)
    return (await session.execute(select(InviteCode).where(InviteCode.code == normalized))).scalar_one_or_none()


async def list_invite_codes(
    session: AsyncSession,
    *,
    state: str | None = None,
    limit: int = LIST_DEFAULT_LIMIT,
) -> list[InviteCode]:
    """列出邀请码（运营命令 ``invite list``），按签发时间**倒序**（最新在前）。

    Args:
        session: 关系库会话。
        state: 可选的状态过滤（取值见 `models.INVITE_CODE_STATES`）。
        limit: 条数上界。**收敛到 `LIST_MAX_LIMIT`**（CORE-11）：调用方给多大都
            收敛到该上界，避免积压时一次查询耗时不可控。

    Returns:
        匹配的记录列表（可能为空）。

    Raises:
        InviteCodeFormatError: `state` 不在词表内——**显式拒绝而不是静默返回空列表**：
            后者会让打错字的状态查询看起来像「这个状态下没有码」。
    """
    if state is not None and state not in {STATE_ISSUED, STATE_USED, STATE_REVOKED}:
        raise InviteCodeFormatError(f"状态不在词表内：{state!r}")

    effective_limit = max(1, min(limit, LIST_MAX_LIMIT))
    statement = select(InviteCode).order_by(InviteCode.created_at.desc(), InviteCode.code).limit(effective_limit)
    if state is not None:
        statement = statement.where(InviteCode.state == state)
    return list((await session.execute(statement)).scalars())


async def count_invite_codes(session: AsyncSession, *, state: str | None = None) -> int:
    """统计邀请码条数（运营排查「还剩多少张有效码」）。

    Raises:
        InviteCodeFormatError: `state` 不在词表内。
    """
    if state is not None and state not in {STATE_ISSUED, STATE_USED, STATE_REVOKED}:
        raise InviteCodeFormatError(f"状态不在词表内：{state!r}")
    statement = select(func.count()).select_from(InviteCode)
    if state is not None:
        statement = statement.where(InviteCode.state == state)
    return (await session.execute(statement)).scalar_one()


__all__ = [
    # 常量
    "LIST_DEFAULT_LIMIT",
    "LIST_MAX_LIMIT",
    "MAX_CODE_GENERATION_ATTEMPTS",
    # 纯函数
    "generate_invite_code",
    "normalize_invite_code",
    # 状态机
    "bind_invite_code_account",
    "claim_invite_code",
    "count_invite_codes",
    "get_invite_code",
    "issue_invite_code",
    "list_invite_codes",
    "release_invite_code",
    "revoke_invite_code",
]
