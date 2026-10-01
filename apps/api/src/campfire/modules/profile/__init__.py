"""个性化档案：支持对象生命周期、条目读写与分流、摘要、应急取数、注销清除。

职责：本模块拥有支持对象的建立/改名/归档/恢复、档案条目的自动写入、来源与生成方式
标注、纠正与删除、按对象归属读取、一页摘要与应急预取。
边界：不决定谁能访问（交 `core/authz`）；不把系统推断当既成事实返回。
参考：docs/项目结构设计.md 第 6 节；docs/技术设计/technical-details/个性化档案.md；
docs/技术设计/technical-details/支持对象.md。

不得承担：决定谁能访问（交 `core/authz`）；把系统推断当既成事实返回。

一期档案归属支持对象，只创建者可用（`RQ-MEM-05`）；授权经 `core/authz` 的
`require_owned` / `require_writable`，其实现在本模块（`authz.OwnerAuthorizer`）、
由装配处注入——`core/*` 不得依赖 `modules/*`（项目结构设计第 7 节）。

数据形状与状态机见 docs/技术设计/technical-details/个性化档案.md
（稳定层与候选层、一页摘要、纠错规则）。
"""

from campfire.modules.profile.authz import OwnerAuthorizer
from campfire.modules.profile.consumer import ProfileWriteResult, write_from_pending
from campfire.modules.profile.errors import (
    InferredCannotBeConfirmedError,
    ProfileDataError,
    ProfileError,
    ProfileItemNotFoundError,
)
from campfire.modules.profile.models import (
    CANDIDATE_ORIGINS,
    CONFIRMATION_CONFIRMED,
    CONFIRMATION_REJECTED,
    CONFIRMATION_UNCONFIRMED,
    CONFIRMATIONS,
    DOMAIN_OTHER,
    DOMAINS,
    EMERGENCY_GROUPS,
    FRESHNESS_CURRENT,
    FRESHNESS_HISTORICAL,
    FRESHNESS_STALE,
    FRESHNESSES,
    MANUAL_ENTRY_SOURCE,
    MAX_ACCOUNT_ID_LENGTH,
    MAX_DISPLAY_NAME_LENGTH,
    MAX_SESSION_ID_LENGTH,
    STABLE_ORIGINS,
    STALE_AFTER_DAYS,
    ProfileItem,
    SessionObjectBinding,
    SupportObject,
    confirmation_on_entry,
    effective_freshness,
    lands_in_stable_layer,
)
from campfire.modules.profile.purge import ProfileAccountPurger
from campfire.modules.profile.service import (
    SUMMARY_FIELD_DOMAINS,
    EmergencyContext,
    GroupedItems,
    ItemView,
    ProfileSummary,
    SummaryEntry,
    SummaryField,
    add_manual_item,
    archive_object,
    assert_summary_coverable,
    bind_first_object,
    confirm_item,
    correct_item,
    create_object,
    delete_item,
    discard_session_binding,
    emergency_context,
    list_objects,
    propose_item,
    read_items,
    read_session_bindings,
    reject_item,
    rename_object,
    resolve_default_object,
    resolve_for_context,
    restore_object,
    summary,
)

__all__ = [
    # 表
    "ProfileItem",
    "SessionObjectBinding",
    "SupportObject",
    # 词表与常量
    "CANDIDATE_ORIGINS",
    "CONFIRMATIONS",
    "CONFIRMATION_CONFIRMED",
    "CONFIRMATION_REJECTED",
    "CONFIRMATION_UNCONFIRMED",
    "DOMAINS",
    "DOMAIN_OTHER",
    "EMERGENCY_GROUPS",
    "FRESHNESSES",
    "FRESHNESS_CURRENT",
    "FRESHNESS_HISTORICAL",
    "FRESHNESS_STALE",
    "MANUAL_ENTRY_SOURCE",
    "MAX_ACCOUNT_ID_LENGTH",
    "MAX_DISPLAY_NAME_LENGTH",
    "MAX_SESSION_ID_LENGTH",
    "STABLE_ORIGINS",
    "STALE_AFTER_DAYS",
    "SUMMARY_FIELD_DOMAINS",
    # 判据
    "assert_summary_coverable",
    "confirmation_on_entry",
    "effective_freshness",
    "lands_in_stable_layer",
    # 结果类型
    "EmergencyContext",
    "GroupedItems",
    "ItemView",
    "ProfileSummary",
    "ProfileWriteResult",
    "SummaryEntry",
    "SummaryField",
    # 支持对象生命周期
    "archive_object",
    "bind_first_object",
    "create_object",
    "discard_session_binding",
    "list_objects",
    "rename_object",
    "resolve_default_object",
    "restore_object",
    # 条目写入
    "add_manual_item",
    "propose_item",
    "write_from_pending",
    # 条目读写与状态迁移
    "confirm_item",
    "correct_item",
    "delete_item",
    "read_items",
    "reject_item",
    # 取数
    "emergency_context",
    "read_session_bindings",
    "resolve_for_context",
    "summary",
    # 授权实现（装配处注入 core/authz）
    "OwnerAuthorizer",
    # 注销清除（装配处注入 core/auth 的编排）
    "ProfileAccountPurger",
    # 异常
    "InferredCannotBeConfirmedError",
    "ProfileDataError",
    "ProfileError",
    "ProfileItemNotFoundError",
]
