"""单元测试：记忆的身份与派生标识。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 1、3 节与
``docs/技术设计/decisions/通用记忆归属为账号.md``。

这里锁的是三个**实测得到的硬约束**（都不需要真实图库）：

1. 分区键要满足 Graphiti 的 `validate_group_id`——实测 `group_id` 在 FalkorDB 后端
   **就是图名**，不合法的键会变成「写入成功、读取为空」的静默失败，因此在入口拒绝。
   **注意**：FalkorDB 图名本身**没有**字符集限制（实测），约束的唯一来源是 Graphiti。
2. episode 的确定性标识必须**稳定**：同一 `pending_id` 永远派生出同一 uuid
   （幂等唯一依据），不同 `pending_id` 必须不同（否则两条记忆会撞成一条）。
3. 外部传入的 episode 标识（删除路径的入口参数）必须是合法 UUID——账本里的脏 key
   不会报错，只会让某条记忆永远删不掉、或误删不到（静默失效）。
"""

from __future__ import annotations

import uuid

import pytest

from campfire.modules.memory.errors import MemoryDataError
from campfire.modules.memory.identity import (
    AccountId,
    AccountIdError,
    PendingId,
    derive_episode_uuid,
    to_account_id,
)

# ---------------------------------------------------------------------------
# 账号标识（分区键）
# ---------------------------------------------------------------------------


def test_uuid_account_id_is_accepted() -> None:
    """UUID 形式是最常见的账号键——必须可用（连字符在合法字符集内）。"""
    raw = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    assert to_account_id(raw) == AccountId(raw)


def test_underscore_and_hyphen_account_ids_are_accepted() -> None:
    """下划线与连字符均在判据内（与 Graphiti 的 `validate_group_id` 一致）。

    这两类的**落库能力**由 `test_memory_ledger_integration` 用真实 PG 证明
    （账本列已放宽为 varchar；此前是 uuid 列，会拒绝 `acct_aaa`）。
    """
    for raw in ("acct_aaa", "acct-bbb", "Acct123"):
        assert to_account_id(raw) == AccountId(raw)


def test_account_id_must_match_graphiti_group_id_rule() -> None:
    """与 Graphiti 的判据保持一致：只允许 `[a-zA-Z0-9_-]`。

    含点、空格、中文等字符的账号键会让 Graphiti 在写入时抛
    `GroupIdValidationError`（`helpers.py` 的 `re.match`）；在入口拒绝比在图库
    写入时失败更易定位。

    **注意**：FalkorDB 图名本身**没有**字符集限制（实测这些值都能建图），
    所以约束的唯一来源是 Graphiti——此处不断言 FalkorDB 的行为。
    """
    for bad in ("acct.aaa", "acct aaa", "账号一号", "acct/aaa", "acct:aaa"):
        with pytest.raises(AccountIdError):
            to_account_id(bad)


def test_trailing_newline_is_rejected_even_though_graphiti_allows_it() -> None:
    """尾随换行被拒绝——我方比 Graphiti 更严（安全方向）。

    Graphiti 用 `re.match`，其 `$` 允许尾随换行（实测 `validate_group_id('acct\\n')`
    返回 True）；我们用 `fullmatch`。宁可少收一个畸形键，也不让换行进入图名。
    这条把「方向更严」写成可执行事实，而不是注释里的声明。
    """
    with pytest.raises(AccountIdError):
        to_account_id("acct\n")


def test_empty_account_id_is_rejected() -> None:
    """空账号被拒绝。

    **理由（2026-09-29 评审更正）**：此前写「空串在 Graphiti 里代表默认分区」——
    该说法**不成立**。Graphiti 的 `validate_group_id('')` 确实放行，但随后
    `clone(database='')` 会造出一个**空图名的坏驱动**，其建索引任务抛
    `TypeError: Expected a string parameter`。真正回落到默认分区的是
    `group_id=None`（属性为 `'_'`、图仍是配置库）。
    因此「拒绝空值」的正当理由是：它既不是合法图名，也不是框架的默认分区语义，
    放行只会得到一个写不进去的驱动。
    """
    with pytest.raises(AccountIdError, match="为空"):
        to_account_id("")


def test_framework_sentinel_account_id_is_rejected() -> None:
    """框架哨兵 `'_'` 被拒绝（`FalkorDriver.default_group_id`）。

    理由：`clone(database='_')` 会走「等于 default_group_id」分支、**落到 `default_db`**
    （实测），与我方写 `'_'` 那张图不是同一个图。允许账号叫 `_` 会造成
    「我方写 A 图、框架写 B 图」的静默分叉。
    """
    with pytest.raises(AccountIdError, match="哨兵"):
        to_account_id("_")


def test_non_string_account_id_raises_domain_error_not_type_error() -> None:
    """非字符串输入抛领域错误，而不是与校验无关的 `TypeError`（CORE-04）。

    实测此前 `to_account_id(123)` 抛 `TypeError: expected string or bytes-like object`
    ——调用方无法按 `AccountIdError` 处理，且错误消息指向正则内部而非输入本身。
    """
    for bad in (123, None, b"acct", ["acct"], object()):
        with pytest.raises(AccountIdError):
            to_account_id(bad)


def test_overlong_account_id_is_rejected() -> None:
    """超长账号键被拒绝（CORE-11：外部输入必须有界）。

    实测此前 100000 字符的键被接受，而它会直接成为 Redis 的图名。
    """
    from campfire.modules.memory.identity import MAX_ACCOUNT_ID_LENGTH

    with pytest.raises(AccountIdError, match="上界"):
        to_account_id("a" * (MAX_ACCOUNT_ID_LENGTH + 1))
    # 恰好等于上界仍应接受（边界是闭区间，避免 off-by-one 把合法值挡掉）。
    assert to_account_id("a" * MAX_ACCOUNT_ID_LENGTH)


def test_account_id_error_is_a_memory_data_error() -> None:
    """账号键错误属于「数据不合法」，不是「图库不可用」——调用方据此决定是否重试。"""
    with pytest.raises(MemoryDataError):
        to_account_id("bad id")
    # 反向：它不是不可用类错误（不成立的断言会暴露继承关系写反）。
    from campfire.modules.memory.errors import MemoryUnavailableError

    assert not issubclass(AccountIdError, MemoryUnavailableError)


# ---------------------------------------------------------------------------
# episode uuid 派生（幂等的唯一依据）
# ---------------------------------------------------------------------------


def test_same_pending_id_derives_the_same_uuid() -> None:
    """**幂等的核心断言**：同一 pending_id 永远得到同一 uuid。

    若这条不成立，重复投递就会在图库里产生第二条 episode（图库的 MERGE 是覆盖
    语义，不会替我们去重）。
    """
    pending = PendingId("11111111-1111-4111-8111-111111111111")
    first = derive_episode_uuid(pending)
    second = derive_episode_uuid(pending)
    assert first == second


def test_different_pending_ids_derive_different_uuids() -> None:
    """不同 pending_id 必须得到不同 uuid，否则两条记忆会撞成一个 episode。"""
    a = derive_episode_uuid(PendingId("11111111-1111-4111-8111-111111111111"))
    b = derive_episode_uuid(PendingId("22222222-2222-4222-8222-222222222222"))
    assert a != b


def test_derived_uuid_is_a_parseable_uuid() -> None:
    """派生结果必须是**合法 uuid**：图库以 uuid 为身份，格式不对会写入失败。"""
    derived = derive_episode_uuid(PendingId("33333333-3333-4333-8333-333333333333"))
    parsed = uuid.UUID(derived)
    assert str(parsed) == derived


def test_derived_uuid_is_stable_across_calls_and_processes() -> None:
    """同一 pending_id 反复派生得到同一结果（确定性，不依赖进程状态）。

    UUID 版本号是判据之一：**5 = 基于名字的确定性派生**，4 = 随机。
    """
    first = derive_episode_uuid(PendingId("fixed-pending-id"))
    second = derive_episode_uuid(PendingId("fixed-pending-id"))
    assert first == second, "同一 pending_id 两次派生必须一致"
    assert uuid.UUID(first).version == 5, "必须是 UUID5（名字派生），不能是 UUID4（随机）"


def test_derived_uuid_matches_a_pinned_golden_vector() -> None:
    """**黄金向量**：把命名空间常量真正接到派生输出上。

    为什么必须有这条（2026-09-29 评审发现的真实漏洞）：原有断言只查「版本 == 5」
    与「常量字面值」，而把 `EPISODE_UUID_NAMESPACE` 换成 `uuid.NAMESPACE_DNS` 时
    **两条都仍然通过**（实测消融）——派生值已漂移、测试却全绿。后果是所有历史
    `pending_id` 派生出不同的 uuid：重复投递不再幂等、删除账本对不上旧记录。

    这条把「常量 → 输出」的接线钉住：改常量或改派生方式都会让它失败。
    """
    assert derive_episode_uuid(PendingId("fixed-pending-id")) == "490eabc3-f4d2-55ca-a837-edf78e84ede3"


def test_derived_uuid_does_not_use_a_standard_namespace() -> None:
    """反向断言：换成标准命名空间会得到**不同**结果。

    与黄金向量互补——黄金向量防「实现被改」，这条防「常量被换成标准命名空间却
    看起来仍然合理」（例如有人顺手改用 `NAMESPACE_URL`）。
    """
    our_value = derive_episode_uuid(PendingId("fixed-pending-id"))
    for foreign in (uuid.NAMESPACE_DNS, uuid.NAMESPACE_URL, uuid.NAMESPACE_OID, uuid.NAMESPACE_X500):
        assert our_value != str(uuid.uuid5(foreign, "fixed-pending-id"))


def test_empty_pending_id_is_rejected() -> None:
    """空 pending_id 被拒绝：它会让所有空记录撞成同一条记忆。"""
    with pytest.raises(MemoryDataError, match="pending_id"):
        derive_episode_uuid(PendingId(""))


def test_episode_uuid_namespace_is_pinned() -> None:
    """命名空间是固定常量。

    一旦改动，所有历史 pending_id 都会派生出不同的 uuid——已写入的记忆将无法再
    被同一条待处理记录认出，幂等与删除账本同时失效。此断言把该常量钉住。

    Note:
        这条只钉**常量值**；「常量被真正接到派生输出上」由黄金向量
        `test_derived_uuid_matches_a_pinned_golden_vector` 负责（2026-09-29 评审
        发现只有这条时，换命名空间不会让任何测试失败）。
    """
    from campfire.modules.memory.identity import EPISODE_UUID_NAMESPACE

    assert str(EPISODE_UUID_NAMESPACE) == "6f2a1c3e-9b74-4d51-8a0e-2c5f7b9d4e11"


# ---------------------------------------------------------------------------
# episode 标识的入口校验（删除路径的参数）
# ---------------------------------------------------------------------------


def test_episode_key_accepts_a_canonical_uuid() -> None:
    """规范 UUID 文本通过，并原样返回。"""
    from campfire.modules.memory.identity import to_episode_key

    raw = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    assert to_episode_key(raw) == raw


def test_episode_key_normalizes_non_canonical_uuid_forms() -> None:
    """非规范形式被归一为小写连字符形式。

    为什么重要：账本按 `episode_key` **等值**过滤。若大小写或花括号形式不一致，
    「同一条记忆」在写入与读取两侧会被当成两个 key——删除记了却过滤不到。
    """
    from campfire.modules.memory.identity import to_episode_key

    canonical = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    for variant in (canonical.upper(), "{" + canonical + "}", canonical.replace("-", "")):
        assert to_episode_key(variant) == canonical, f"{variant!r} 应归一为规范形式"


def test_episode_key_rejects_malformed_values() -> None:
    """畸形 episode 标识在入口被拒——账本里的脏 key 只会让删除静默失效。"""
    from campfire.modules.memory.identity import to_episode_key

    for bad in ("", "not-a-uuid", "cd000000-0000-4000-8000-00000000idem", "x" * 100):
        with pytest.raises(MemoryDataError):
            to_episode_key(bad)
    # 非字符串同样转成领域错误，而不是泄漏 TypeError（CORE-04）。
    for bad_type in (123, None, b"3f2504e0-4f89-41d3-9a0c-0305e82c3301"):
        with pytest.raises(MemoryDataError):
            to_episode_key(bad_type)
