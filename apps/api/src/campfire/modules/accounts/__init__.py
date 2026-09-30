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
# 已实现（2026-09-30）：`errors.py`（异常层次）、`models.py`（邀请码表）、
# `repository.py`（邀请码状态机：签发、原子占用、补偿释放、绑定、撤销、列举）、
# `onboarding.py`（引导状态表的读取与触发判定，`RQ-ACC-09`）。
#
# 仍缺：注册复写（把邀请码校验注入身份服务的 sign-up API）、人工重置、
# 账号注销编排，以及注销墓碑（归 `core/auth`）。它们随 SDK 装配与 CLI 子命令落地。
#
# `onboarding.py` 的表模型与迁移尚未落地（表形状由认证与账号第 8 节拥有）。
# 该模块因此走带绑定参数的显式 SQL，而不是声明第二份模型——同名表的第二份定义会与
# `core/db.metadata` 的 `--autogenerate` 差异比较打架（项目结构设计第 10 节）。
# 模型与迁移随该表的所有者批次补上，本模块的接口形状不变。

from campfire.modules.accounts.errors import (
    AccountsError,
    InviteCodeError,
    InviteCodeFormatError,
    InviteCodeNotFoundError,
    InviteCodeRejectedError,
    InviteCodeStateError,
    OnboardingTriggerError,
)
from campfire.modules.accounts.models import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    INVITE_CODE_STATES,
    INVITE_CODE_TTL_DAYS,
    MAX_ACCOUNT_ID_LENGTH,
    MAX_OPERATOR_LENGTH,
    STATE_ISSUED,
    STATE_REVOKED,
    STATE_USED,
    InviteCode,
)
from campfire.modules.accounts.onboarding import (
    ONBOARDING_STATES,
    ONBOARDING_TABLE_NAME,
    STATE_COMPLETED,
    STATE_IN_PROGRESS,
    STATE_SKIPPED,
    TERMINAL_STATES,
    onboarding_pending,
    read_onboarding_state,
    should_inject_onboarding,
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

__all__ = [
    # 异常
    "AccountsError",
    "InviteCodeError",
    "InviteCodeFormatError",
    "InviteCodeNotFoundError",
    "InviteCodeRejectedError",
    "InviteCodeStateError",
    "OnboardingTriggerError",
    # 常量（词表与形状）
    "INVITE_CODE_ALPHABET",
    "INVITE_CODE_LENGTH",
    "INVITE_CODE_STATES",
    "INVITE_CODE_TTL_DAYS",
    "MAX_ACCOUNT_ID_LENGTH",
    "MAX_OPERATOR_LENGTH",
    "STATE_ISSUED",
    "STATE_REVOKED",
    "STATE_USED",
    # 表
    "InviteCode",
    # 引导状态（一次性引导的触发判定）
    "ONBOARDING_STATES",
    "ONBOARDING_TABLE_NAME",
    "STATE_COMPLETED",
    "STATE_IN_PROGRESS",
    "STATE_SKIPPED",
    "TERMINAL_STATES",
    "onboarding_pending",
    "read_onboarding_state",
    "should_inject_onboarding",
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
]
