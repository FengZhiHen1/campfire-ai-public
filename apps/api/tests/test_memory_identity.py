"""单元测试：记忆的身份与派生标识。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 1、3 节与
``docs/技术设计/decisions/通用记忆归属为账号.md``。

这里锁的是两个**实测得到的硬约束**（都不需要真实图库）：

1. 分区键要同时满足 Graphiti 的 `validate_group_id` 与 FalkorDB 的图名约束——
   实测 `group_id` 在 FalkorDB 后端**就是图名**，不合法的键会变成「写入成功、
   读取为空」的静默失败，因此在入口拒绝。
2. episode 的确定性标识必须**稳定**：同一 `pending_id` 永远派生出同一 uuid
   （幂等唯一依据），不同 `pending_id` 必须不同（否则两条记忆会撞成一条）。
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
    """下划线与连字符均在判据内（与 Graphiti 的 validate_group_id 一致）。"""
    for raw in ("acct_aaa", "acct-bbb", "Acct123"):
        assert to_account_id(raw) == AccountId(raw)


def test_account_id_must_match_graphiti_group_id_rule() -> None:
    """与 Graphiti 的判据保持一致：只允许 `[a-zA-Z0-9_-]`。

    含点、空格、中文等字符的账号键会让 Graphiti 在写入时抛
    `GroupIdValidationError`；在入口拒绝比在图库写入时失败更易定位。
    """
    for bad in ("acct.aaa", "acct aaa", "账号一号", "acct/aaa", "acct:aaa"):
        with pytest.raises(AccountIdError):
            to_account_id(bad)


def test_empty_account_id_is_rejected() -> None:
    """空账号被拒绝——空串在 Graphiti 里代表**默认分区**。

    放行空值等于允许所有人共用一张图，正是本次归属裁决要避免的事。
    """
    with pytest.raises(AccountIdError, match="为空"):
        to_account_id("")


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
    """派生结果不依赖进程状态（用固定命名空间，非随机）。

    这条防的是「把命名空间改成随机值」或「改用 uuid4」这类改动——那会让历史
    pending_id 漂移到不同 uuid，重复投递随之产生重复 episode。
    UUID 的版本号是判据：**5 = 基于名字的确定性派生**，4 = 随机。
    """
    derived = derive_episode_uuid(PendingId("fixed-pending-id"))
    assert uuid.UUID(derived).version == 5, "必须是 UUID5（名字派生），不能是 UUID4（随机）"


def test_empty_pending_id_is_rejected() -> None:
    """空 pending_id 被拒绝：它会让所有空记录撞成同一条记忆。"""
    with pytest.raises(MemoryDataError, match="pending_id"):
        derive_episode_uuid(PendingId(""))


def test_episode_uuid_namespace_is_pinned() -> None:
    """命名空间是固定常量。

    一旦改动，所有历史 pending_id 都会派生出不同的 uuid——已写入的记忆将无法再
    被同一条待处理记录认出，幂等与删除账本同时失效。此断言把该常量钉住。
    """
    from campfire.modules.memory.identity import EPISODE_UUID_NAMESPACE

    assert str(EPISODE_UUID_NAMESPACE) == "6f2a1c3e-9b74-4d51-8a0e-2c5f7b9d4e11"
