"""账号：注册（邀请码）、登录会话、人工重置、账号注销编排。

职责：拥有邀请码校验与注册、登录会话建立与撤销、人工重置、账号注销编排的用例服务。
边界：不承担对任何支持对象档案的访问判定——那归 `core/authz`。
参考：docs/项目结构设计.md 第 6 节、docs/技术栈设计.md 第 4 节；完整论证见下方
「模块说明」注释块。
"""

# 模块说明：本包只做再导出、没有自己的定义，故原始论证整体保留在此处。
#
# 拥有的用例（见 docs/项目结构设计.md 第 6 节）：邀请码校验与注册、登录会话的
# 建立与撤销、人工重置、账号注销编排。
#
# 不得承担：对任何支持对象档案的访问判定——那归 `core/authz`。
# 「身份本身不构成对任何支持对象的访问授权」（docs/技术栈设计.md 第 4 节）。
#
# 一期约束（`RQ-ACC-01`～`RQ-ACC-08`）：全应用必须登录，不存在匿名内容页、
# 匿名接口或未登录可达的业务路径（唯一例外是运维探针 `GET /health`）；账号为
# 账号名与密码，不要求邮箱；注册须凭邀请码（`RQ-ACC-04`）；忘记密码由运营者
# 人工重置，重置后旧会话必须立即失效（`RQ-ACC-06`）。
#
# 已核实的偏差（docs/技术栈设计.md 第 2 节）：SuperTokens 无原生 username，
# 账号名仍存放于 `email` 字段（`TECH-08`）；运营操作走 SDK 或 Management API，
# 不依赖 Dashboard（超过 3 个用户属付费）。
#
# 会话校验经过 core（2026-09-29 裁决，见
# docs/技术设计/decisions/会话校验逐请求查证数据库.md）：SDK 以
# `check_database=True` 逐请求查证，而该查证由 core 执行——core 因此在鉴权
# 关键路径上，不存在「已登录用户不受影响」的路径。此前本文件写「会话校验在 Python
# SDK 内完成、不经过 core」，该表述已被推翻（该漂移登记于 docs/TODO.md）。
#
# 一期只做个人账号（`RQ-ACC-03`，2026-09-29 收窄）：不存在组织字段或组织标识，
# 组织与机构协作整体推迟到二期（见 docs/技术设计/decisions/一期只做个人账号.md）。
# 此前本文件写「组织标识」属该裁决之前的表述，已移除。
#
# 已实现（2026-09-30）：`errors.py`（异常层次）、`models.py`（邀请码表、会话归属表
# `campfire_session`、引导状态表 `campfire_onboarding`）、
# `repository.py`（邀请码状态机：签发、原子占用、补偿释放、绑定、撤销、列举）、
# `onboarding.py`（引导状态表的读取与触发判定，`RQ-ACC-09`）、
# `session_items.py`（SDK 会话条目 → parts/标题/预览的解析）、
# `session_repository.py`（会话归属行的读写与 SDK 两表的只读查询）、
# `sessions.py`（会话归属四个用例与注销清除）、
# `onboarding_completion.py`（引导收束写入：置 `completed`，`finish_onboarding` 的用例层）。
#
# 会话归属的数据链（2026-09-30，T06）：`campfire_session` 只存归属与登记，不存消息
# ——存消息就构成第二份对话真源（基座第 2 节）。会话列表的标题与末条预览都从 SDK 的
# 会话存储算出来（`session_items`），不落库：派生值落库会造出第二个可写真源。
# 对象名经注入回调取（`sessions.ObjectNameReader`），因为对象归 `modules/profile`，
# 而模块之间禁止互相 import（项目结构设计第 7 节）。
#
# 仍缺：注册复写（把邀请码校验注入身份服务的 sign-up API）、人工重置、账号注销编排，
# 以及注销墓碑（归 `core/auth`）。它们随 SDK 装配与 CLI 子命令落地。
#
# 引导状态表的模型与迁移已落地（2026-09-30）：`models.CampfireOnboarding` 已在
# `core/db.metadata` 里，迁移随该批生成。`onboarding.py` 因此不再需要「走显式 SQL
# 以避免第二份模型定义」——那条说明的前置已满足（该改动不在 T04 范围内，
# 在该文件里原样保留，已作为未决问题上报；读写语义与接口形状不受影响）。
#
# `onboarding_completion.py` 走模型而非显式 SQL：它只做写入，没有「先于模型存在」的
# 历史包袱，直接建在 `CampfireOnboarding` 上。

from campfire.modules.accounts.errors import (
    AccountsError,
    InviteCodeError,
    InviteCodeFormatError,
    InviteCodeNotFoundError,
    InviteCodeRejectedError,
    InviteCodeStateError,
    OnboardingTriggerError,
    OnboardingWriteError,
    SessionError,
    SessionNotFoundError,
    SessionQueryError,
    SessionRegistrationError,
)
from campfire.modules.accounts.models import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    INVITE_CODE_STATES,
    INVITE_CODE_TTL_DAYS,
    MAX_ACCOUNT_ID_LENGTH,
    MAX_OPERATOR_LENGTH,
    MAX_SESSION_ID_LENGTH,
    STATE_ISSUED,
    STATE_REVOKED,
    STATE_USED,
    CampfireOnboarding,
    CampfireSession,
    InviteCode,
)
from campfire.modules.accounts.onboarding import (
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_SKIPPED,
    ONBOARDING_STATES,
    ONBOARDING_TABLE_NAME,
    TERMINAL_STATES,
    onboarding_pending,
    read_onboarding_state,
    should_inject_onboarding,
)
from campfire.modules.accounts.onboarding_completion import (
    SKIPPED_SECTIONS,
    complete_onboarding,
)
from campfire.modules.accounts.registration import (
    EMAIL_FORM_FIELD,
    INVITE_CODE_FORM_FIELD,
    InviteCodeRequired,
    api_overrides,
    make_sign_up_override,
)
from campfire.modules.accounts.repository import (
    LIST_DEFAULT_LIMIT,
    LIST_MAX_LIMIT,
    MAX_CODE_GENERATION_ATTEMPTS,
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
from campfire.modules.accounts.session_items import (
    INJECTED_MESSAGE_PREFIXES,
    TITLE_FALLBACK,
    TITLE_MAX_CHARS,
    HydratedMessage,
    MessagePart,
    StoredItem,
    build_messages,
    build_preview,
    build_title,
)
from campfire.modules.accounts.session_repository import (
    LIST_SCAN_MAX_ITEMS,
    SessionListRow,
    delete_session_owners_for_account,
    get_session_owner,
    insert_session_owner,
    is_session_owned_by,
    list_session_owners,
    read_all_items,
    read_first_items,
    read_last_items,
)
from campfire.modules.accounts.sessions import (
    ObjectNameReader,
    SessionAccountPurger,
    SessionHistory,
    SessionOwner,
    SessionPage,
    SessionSummaryView,
    decode_cursor,
    encode_cursor,
    list_sessions,
    load_history,
    register_session,
    require_session_owner,
    validate_limit,
)

__all__ = [
    # 异常
    "AccountsError",
    "InviteCodeError",
    "InviteCodeFormatError",
    "InviteCodeNotFoundError",
    "InviteCodeRejectedError",
    "InviteCodeStateError",
    "OnboardingTriggerError",
    "OnboardingWriteError",
    "SessionError",
    "SessionNotFoundError",
    "SessionQueryError",
    "SessionRegistrationError",
    # 常量（词表与形状）
    "INVITE_CODE_ALPHABET",
    "INVITE_CODE_LENGTH",
    "INVITE_CODE_STATES",
    "INVITE_CODE_TTL_DAYS",
    "MAX_ACCOUNT_ID_LENGTH",
    "MAX_OPERATOR_LENGTH",
    "MAX_SESSION_ID_LENGTH",
    "STATE_ISSUED",
    "STATE_REVOKED",
    "STATE_USED",
    # 表
    "CampfireOnboarding",
    "CampfireSession",
    "InviteCode",
    # 引导状态（一次性引导的触发判定）
    "ONBOARDING_STATES",
    "ONBOARDING_TABLE_NAME",
    "ONBOARDING_COMPLETED",
    "ONBOARDING_IN_PROGRESS",
    "ONBOARDING_SKIPPED",
    "TERMINAL_STATES",
    "onboarding_pending",
    "read_onboarding_state",
    "should_inject_onboarding",
    # 引导收束（唯一写 `completed` 的用例；`skipped` 归 UI 跳过入口）
    "SKIPPED_SECTIONS",
    "complete_onboarding",
    # 邀请码状态机
    "LIST_DEFAULT_LIMIT",
    "LIST_MAX_LIMIT",
    "MAX_CODE_GENERATION_ATTEMPTS",
    "bind_invite_code_account",
    "claim_invite_code",
    "count_invite_codes",
    "get_invite_code",
    "issue_invite_code",
    "list_invite_codes",
    "release_invite_code",
    "revoke_invite_code",
    # 纯函数
    "generate_invite_code",
    "normalize_invite_code",
    # 注册复写（注入身份服务的 sign-up API）
    "EMAIL_FORM_FIELD",
    "INVITE_CODE_FORM_FIELD",
    "InviteCodeRequired",
    "api_overrides",
    "make_sign_up_override",
    # 会话条目解析（SDK 持久化格式 → parts/标题/预览）
    "INJECTED_MESSAGE_PREFIXES",
    "TITLE_FALLBACK",
    "TITLE_MAX_CHARS",
    "HydratedMessage",
    "MessagePart",
    "StoredItem",
    "build_messages",
    "build_preview",
    "build_title",
    # 会话归属的存储层（归属行读写 + SDK 两表只读）
    "LIST_SCAN_MAX_ITEMS",
    "SessionListRow",
    "delete_session_owners_for_account",
    "get_session_owner",
    "insert_session_owner",
    "is_session_owned_by",
    "list_session_owners",
    "read_all_items",
    "read_first_items",
    "read_last_items",
    # 会话归属的用例层
    "ObjectNameReader",
    "SessionAccountPurger",
    "SessionHistory",
    "SessionOwner",
    "SessionPage",
    "SessionSummaryView",
    "decode_cursor",
    "encode_cursor",
    "list_sessions",
    "load_history",
    "register_session",
    "require_session_owner",
    "validate_limit",
]
