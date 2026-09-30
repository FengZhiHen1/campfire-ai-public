"""个性化档案的纯逻辑：落层判据、降权时限、词表闭集与授权文案纪律。

这些用例**不需要数据库**：它们钉住的是纯函数判据，因此可以在任何环境跑
（含 CI，那里的集成测试会被 skip）。

对应 ``docs/技术设计/technical-details/个性化档案.md`` 第 3 节与
``docs/技术设计/technical-details/支持对象.md`` 第 5.3 节。

为什么纯逻辑值得单独测：落层判据是**唯一判据**（第 3 节），而它有两个表达
（Python 谓词与 SQL 过滤）。集成测试覆盖 SQL 侧，本文件覆盖谓词侧——
两者不一致时必有一个失败。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from campfire.core.authz import (
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
)
from campfire.core.pending_write import ORIGINS
from campfire.modules.profile.errors import InferredCannotBeConfirmedError, ProfileDataError
from campfire.modules.profile.models import (
    CANDIDATE_ORIGINS,
    CONFIRMATION_CONFIRMED,
    CONFIRMATION_UNCONFIRMED,
    DOMAINS,
    EMERGENCY_GROUPS,
    FRESHNESS_CURRENT,
    FRESHNESS_HISTORICAL,
    FRESHNESS_STALE,
    STABLE_ORIGINS,
    STALE_AFTER_DAYS,
    confirmation_on_entry,
    effective_freshness,
    lands_in_stable_layer,
)
from campfire.modules.profile.repository import normalize_display_name, to_item_uuid, to_object_uuid
from campfire.modules.profile.service import SUMMARY_FIELD_DOMAINS, assert_summary_coverable

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------


def test_origin_vocabulary_is_six_values() -> None:
    """`origin` 必须是**六值**。

    契约（`propose_profile_item` 第 2 节）取六值，而 `5e27503214c3` 建的存储约束
    此前只有四值——「契约能传、存储拒收」。本用例钉住应用侧集合是六值，
    存储侧由迁移与集成测试钉住。
    """
    assert ORIGINS == {
        "user_statement",
        "guardian_observation",
        "third_party_report",
        "document",
        "system_observation",
        "ai_inference",
    }


def test_stable_and_candidate_origins_partition_all_origins() -> None:
    """四种稳定来源 + 两种候选来源 = 六值，且两边不重叠。

    这是第 3 节落层表的穷尽性：新增一个 `origin` 而漏了归类，会被本用例拦下。
    """
    assert STABLE_ORIGINS | CANDIDATE_ORIGINS == ORIGINS
    assert not (STABLE_ORIGINS & CANDIDATE_ORIGINS)


def test_domain_vocabulary_has_fourteen_modules_plus_fallback() -> None:
    """领域取十四个一级模块，另设「其他」兜底（第 6 节：保证不丢失）。"""
    assert len(DOMAINS) == 15
    assert "other" in DOMAINS


def test_emergency_groups_are_eight() -> None:
    """应急预取八组（第 8 节；框架七组 + 与有效策略成对的无效策略）。"""
    assert len(EMERGENCY_GROUPS) == 8
    assert "unhelpful_strategies" in EMERGENCY_GROUPS


# ---------------------------------------------------------------------------
# 落层判据（第 3 节）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        # 陈述与监护人观察：陈述本身即确认（RQ-MEM-02「直接陈述零确认入档」）。
        ("user_statement", CONFIRMATION_CONFIRMED),
        ("guardian_observation", CONFIRMATION_CONFIRMED),
        # 明确提供但未经本人确认：进稳定层，仍是 unconfirmed。
        ("third_party_report", CONFIRMATION_UNCONFIRMED),
        ("document", CONFIRMATION_UNCONFIRMED),
        # 系统观察与推断：只进候选层。
        ("system_observation", CONFIRMATION_UNCONFIRMED),
        ("ai_inference", CONFIRMATION_UNCONFIRMED),
    ],
)
def test_confirmation_on_entry_follows_the_layer_table(origin: str, expected: str) -> None:
    """入档时的确认状态由 `origin` 决定（第 3 节的落层表逐行）。"""
    assert confirmation_on_entry(origin) == expected


@pytest.mark.parametrize("origin", sorted(STABLE_ORIGINS))
def test_non_inferred_origins_land_in_the_stable_layer(origin: str) -> None:
    """四种非推断来源直接进稳定层——**包括**仍是 `unconfirmed` 的两种。

    「直接稳定层」说的是它参与取数，不是「已确认」：`third_party_report` 与
    `document` 进稳定层却仍是 `unconfirmed`（第 3 节）。
    """
    assert lands_in_stable_layer(
        origin=origin,
        confirmation=confirmation_on_entry(origin),
        freshness=FRESHNESS_CURRENT,
    )


@pytest.mark.parametrize("origin", sorted(CANDIDATE_ORIGINS))
def test_inferred_origins_do_not_land_in_the_stable_layer(origin: str) -> None:
    """系统观察与推断在未确认时**不进**稳定层（`AC-18` 的判据）。"""
    assert not lands_in_stable_layer(
        origin=origin,
        confirmation=CONFIRMATION_UNCONFIRMED,
        freshness=FRESHNESS_CURRENT,
    )


@pytest.mark.parametrize("origin", sorted(CANDIDATE_ORIGINS))
def test_inferred_becomes_stable_after_the_user_confirms_it(origin: str) -> None:
    """使用者确认后，推断进稳定层——这是「确认才成事实」的落点（第 3 节）。

    它同时说明为什么「推断不得写成 confirmed」这条硬约束必须在**写入路径**上卡，
    而不能做成存储层 CHECK：确认入口正是要把 `ai_inference` 的行置为 `confirmed`，
    存储层若禁止这个组合，确认功能就无法实现。
    """
    assert lands_in_stable_layer(
        origin=origin,
        confirmation=CONFIRMATION_CONFIRMED,
        freshness=FRESHNESS_CURRENT,
    )


@pytest.mark.parametrize("freshness", [FRESHNESS_HISTORICAL, FRESHNESS_STALE])
def test_non_current_items_never_land_in_the_stable_layer(freshness: str) -> None:
    """已取代与已降权的条目不参与稳定层取数（第 3 节末段）。"""
    assert not lands_in_stable_layer(
        origin="user_statement",
        confirmation=CONFIRMATION_CONFIRMED,
        freshness=freshness,
    )


# ---------------------------------------------------------------------------
# 降权时限（第 3 节：90 天）
# ---------------------------------------------------------------------------


def test_candidate_is_downgraded_after_ninety_days() -> None:
    """长期未确认的候选条目 90 天后降权（第 3 节）。"""
    stale_at = _NOW - timedelta(days=STALE_AFTER_DAYS)
    assert (
        effective_freshness(
            origin="ai_inference",
            confirmation=CONFIRMATION_UNCONFIRMED,
            freshness=FRESHNESS_CURRENT,
            last_confirmed_at=stale_at,
            now=_NOW,
        )
        == FRESHNESS_STALE
    )


def test_candidate_just_under_the_limit_is_not_downgraded() -> None:
    """**边界**：差一点点到 90 天不降权（判据是 `>=`，不是 `>`）。

    没有这条，一个 `>` 与 `>=` 的笔误不会被任何用例发现。
    """
    almost = _NOW - timedelta(days=STALE_AFTER_DAYS) + timedelta(seconds=1)
    assert (
        effective_freshness(
            origin="ai_inference",
            confirmation=CONFIRMATION_UNCONFIRMED,
            freshness=FRESHNESS_CURRENT,
            last_confirmed_at=almost,
            now=_NOW,
        )
        == FRESHNESS_CURRENT
    )


def test_downgraded_candidate_is_marked_not_deleted() -> None:
    """降权只是**标记**，不改存储值、更不删数据（第 3 节：不删除）。

    本用例断言的是函数的返回值语义：它返回 `stale` 而不修改输入，
    因此「降权」在存储上是一次读期判定，行仍在库里、`freshness` 仍是被传入的那个值。
    """
    stale_at = _NOW - timedelta(days=STALE_AFTER_DAYS + 1)
    stored = FRESHNESS_CURRENT
    effective = effective_freshness(
        origin="ai_inference",
        confirmation=CONFIRMATION_UNCONFIRMED,
        freshness=stored,
        last_confirmed_at=stale_at,
        now=_NOW,
    )
    assert effective == FRESHNESS_STALE
    # 存储值不是返回值本身——函数是纯的，没有副作用。
    assert stored == FRESHNESS_CURRENT


def test_confirmed_item_is_never_downgraded_by_time() -> None:
    """已确认的事实**不因时间推移降权**：没人再点一次确认不等于它失效。

    这条区分了两个容易混淆的概念——「长期未确认的推断」与「早已确认的事实」。
    """
    ancient = _NOW - timedelta(days=STALE_AFTER_DAYS * 10)
    assert (
        effective_freshness(
            origin="ai_inference",
            confirmation=CONFIRMATION_CONFIRMED,
            freshness=FRESHNESS_CURRENT,
            last_confirmed_at=ancient,
            now=_NOW,
        )
        == FRESHNESS_CURRENT
    )


def test_third_party_report_is_not_downgraded() -> None:
    """`third_party_report` 虽 `unconfirmed`，但不属「未经确认的推断」，不降权。

    它是**明确提供的信息**（第 3 节），只是没经本人确认——与 `ai_inference`
    的「系统归纳」是两类东西。这条钉住 `effective_freshness` 里那个易错的例外分支。
    """
    ancient = _NOW - timedelta(days=STALE_AFTER_DAYS * 10)
    assert (
        effective_freshness(
            origin="third_party_report",
            confirmation=CONFIRMATION_UNCONFIRMED,
            freshness=FRESHNESS_CURRENT,
            last_confirmed_at=ancient,
            now=_NOW,
        )
        == FRESHNESS_CURRENT
    )


# ---------------------------------------------------------------------------
# 摘要字段覆盖性（第 4、10 节）
# ---------------------------------------------------------------------------


def test_summary_has_twelve_fields_all_covered_by_domains() -> None:
    """摘要十二个字段，且每个字段的取数领域都在词表内（第 10 节的覆盖性验证项）。"""
    assert_summary_coverable()
    assert len(SUMMARY_FIELD_DOMAINS) == 12
    domains_used = {domain for _, domains in SUMMARY_FIELD_DOMAINS.values() for domain in domains}
    assert domains_used <= DOMAINS


def test_summary_coverability_check_is_discriminating(monkeypatch: pytest.MonkeyPatch) -> None:
    """**判别性**：把映射改成 11 个字段，检查必须失败。

    没有这条，「覆盖性检查」可能是一只永远通过的闸门。
    """
    from campfire.modules.profile import service

    trimmed = dict(list(SUMMARY_FIELD_DOMAINS.items())[:11])
    monkeypatch.setattr(service, "SUMMARY_FIELD_DOMAINS", trimmed)
    with pytest.raises(AssertionError, match="12"):
        service.assert_summary_coverable()


# ---------------------------------------------------------------------------
# 越权文案纪律（支持对象第 5.3 节）
# ---------------------------------------------------------------------------


def test_archived_error_is_a_subclass_of_authorization_error() -> None:
    """归档错误仍是授权错误的子类：调用方一句 `except AuthorizationError` 收口。

    同时它必须**可以**被单独分辨（对外状态码不同：409 与 404）。
    """
    assert issubclass(ObjectArchivedError, AuthorizationError)


def test_archived_message_differs_from_the_unauthorized_message() -> None:
    """归档文案与越权文案**必须不同**（第 5.3 节）。"""
    assert OBJECT_ARCHIVED_MESSAGE != OBJECT_NOT_ACCESSIBLE_MESSAGE
    assert "已归档" in OBJECT_ARCHIVED_MESSAGE


def test_unauthorized_message_is_a_single_constant() -> None:
    """「不存在」与「不属于你」共用**一个常量**——因此两者不可能漂移。

    逐字相同的文案纪律（第 5.3 节）靠「只有一份字面量」落实；
    若哪天有人为两种情形各写一句，本用例会失败（常量被拆开后
    `authz` 里就不再只有一个来源）。
    """
    from campfire.modules.profile import authz as authz_impl

    # 实现侧必须引用同一个常量，不能自己再写一份字面量。
    source = authz_impl.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "OBJECT_NOT_ACCESSIBLE_MESSAGE" in text
    # 断言实现里没有硬写这句文案（写了就会有两份来源）。
    assert OBJECT_NOT_ACCESSIBLE_MESSAGE not in text.replace("OBJECT_NOT_ACCESSIBLE_MESSAGE", ""), (
        "实现里硬写了越权文案，而不是引用常量——两份字面量必然漂移"
    )


# ---------------------------------------------------------------------------
# 输入边界（CORE-04）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "   ", "\t\n", None, 123])
def test_blank_display_name_is_rejected_by_the_use_case_layer(value: object) -> None:
    """空名与全空白名在用例层被拒（存储层 CHECK 亦兜底，第 8 节）。"""
    with pytest.raises(ProfileDataError):
        normalize_display_name(value)


def test_display_name_is_stripped_not_guessed() -> None:
    """对象名只剥首尾空白，不做其它猜测。"""
    assert normalize_display_name("  小宝  ") == "小宝"


def test_display_name_with_control_characters_is_rejected() -> None:
    """含控制字符的名字被拒——它会破坏切换器与列表的单行呈现。"""
    with pytest.raises(ProfileDataError, match="控制字符"):
        normalize_display_name("小\n宝")


def test_unicode_display_name_is_accepted() -> None:
    """中文与 emoji 是真实的称呼用法，不得被字符集校验误伤。"""
    assert normalize_display_name("小宝🌱") == "小宝🌱"


@pytest.mark.parametrize("value", ["not-a-uuid", "", None, "  "])
def test_malformed_object_id_is_rejected_as_a_domain_error(value: object) -> None:
    """畸形标识转成领域错误——不是让裸驱动异常穿透（CORE-04）。

    可读性与可处理性：调用方要能据此返回 404，而不是处理
    `invalid input syntax for type uuid`。
    """
    with pytest.raises(ProfileDataError):
        to_object_uuid(value)


def test_valid_uuid_is_parsed_and_normalized() -> None:
    """合法 UUID 被解析（大小写与花括号形式归一到同一个值）。"""
    parsed = to_object_uuid("3F2504E0-4F89-41D3-9A0C-0305E82C3301")
    assert str(parsed) == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    assert to_item_uuid(str(parsed)) == parsed


# ---------------------------------------------------------------------------
# 「推断不得冒充事实」这条硬约束的错误类型
# ---------------------------------------------------------------------------


def test_inferred_cannot_be_confirmed_is_a_data_error() -> None:
    """该拒绝属「调用方给错了」（不该重试），因此是 `ProfileDataError` 的子类。"""
    error = InferredCannotBeConfirmedError(
        "拒绝",
        operation="propose_item",
        detail="origin=ai_inference confirmation=confirmed",
    )
    assert isinstance(error, ProfileDataError)
    assert error.operation == "propose_item"
