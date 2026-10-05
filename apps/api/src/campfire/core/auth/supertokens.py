"""SuperTokens SDK 的装配与会话校验入口。

职责与归属（见 docs/项目结构设计.md 第 6 节）：本模块是 `core/auth` 的一部分，拥有会话校验的
装配与唯一入口；注册、邀请码、重置、注销等用例归 `modules/accounts`。

边界：`check_database=True` 固定在内、core 不可达即拒；不 import `modules/*`，注册复写由装配处注入。
参考：[认证与账号] 第 6 节与决策记录。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from supertokens_python import InputAppInfo, SupertokensConfig, init
from supertokens_python.recipe import emailpassword, session
from supertokens_python.recipe.emailpassword import InputFormField, InputOverrideConfig, InputSignUpFeature
from supertokens_python.recipe.emailpassword.interfaces import APIInterface
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session

from campfire.core.config import Settings, apply_no_proxy_normalization
from campfire.core.health import ComponentHealth, Status

logger = logging.getLogger(__name__)

#: FastAPI 依赖函数的类型（即 SDK `verify_session` 的返回签名）。
#:
#: 这里的 `Any` 是复刻 SDK 自己的签名（`Callable[..., Coroutine[Any, Any, ...]]`，
#: 见 `recipe/session/framework/fastapi/__init__.py`）：协程的发送/投掷值类型由
#: 事件循环决定，SDK 未收窄，我们不发明比上游更窄的谎话。
#: `verify_session` 以 `session_required=True` 调用时函数恒返回 `SessionContainer`
#: （未登录即抛 `UnauthorisedError`），但类型上含 `None`——按 SDK 签名如实声明。
SessionDependency = Callable[..., "Coroutine[Any, Any, SessionContainer | None]"]

#: 健康检查里这一项的名字。与 `main.check_auth_core` 的项名一致，
#: 避免同一能力出现两个标签（`core/health` 的既有约定）。
AUTH_COMPONENT = "auth"


class SuperTokensConfigurationError(RuntimeError):
    """SDK 装配所需的配置缺失或非法。

    刻意在装配期显式抛错（而不是留到第一次请求）：配置问题若推迟到请求期暴露，
    表现会是一条 500 或「登录莫名失败」，而排查者会先去查网络与凭据本身。
    这条与 `core/db.create_engine` 对未配置 `DATABASE_URL` 的处置同源。
    """


def _require_api_key(settings: Settings) -> str:
    """取出 Management API 密钥，未配置即显式失败。

    实测必须有值：core 以 `API_KEYS` 启动时，不带该 key 的请求会被拒
    （实测 `GET /apiversion` → `401 Invalid API key`），SDK 因此在建号的第一步
    就失败。所以「没配也能跑」不成立，不如在装配期就说清楚。

    Raises:
        SuperTokensConfigurationError: 未配置 `SUPERTOKENS_API_KEY`。
    """
    if settings.supertokens_api_key is None:
        raise SuperTokensConfigurationError(
            "未配置 SUPERTOKENS_API_KEY——core 以 API_KEYS 启动时所有 Management API 请求都会被拒"
        )
    # SecretStr：取值本身是显式动作，且不进入日志或异常消息。
    return settings.supertokens_api_key.get_secret_value()


def init_supertokens(
    settings: Settings,
    *,
    api_overrides: Callable[[APIInterface], APIInterface] | None = None,
    sign_up_form_fields: Callable[[], list[InputFormField]] | None = None,
) -> None:
    """初始化 SuperTokens SDK（幂等，可重复调用）。

    幂等性由 SDK 保证（实测 `Supertokens.init` 只在 `__instance is None` 时构造），
    因此 Web 入口可在 lifespan 里调用、测试可多次调用而不必自己防重。

    配方（recipe）选择与理由：

    - `session.init(anti_csrf="VIA_CUSTOM_HEADER")`：认证与账号第 5 节定的 anti-CSRF
      方式。它要求前端随请求带自定义头，且在 `sameSite=lax` 且 API 与站点同顶级域
      时是 SDK 的默认值；一期正是同顶级域部署。
      实测注意：`VIA_CUSTOM_HEADER` 下若没有 HTTP 请求上下文而直接调
      `get_session`，SDK 会抛异常（「can't check the CSRF token」）——那是预期的
      设计行为，不是缺陷：走 FastAPI 依赖（本模块的 `require_session`）时请求上下文
      存在，CSRF 校验正常进行。
    - `emailpassword.init(...)`：账号名 + 密码（账号名存放在 `email` 字段，
      `TECH-08` 的已知偏差）。采用官方默认密码校验器（≥8 字符、含小写字母与数字），
      不自定规则（认证与账号第 4 节）。
    - 不启用 Account Linking：它会使主用户 ID 变更（官方《User Object》原文：
      *The primary user ID. It can change if the user links to another user*），
      而 `account_id` 是记忆分区键与图名（认证与账号第 3 节）——启用等于让全部记忆
      与账本失联。刻意不初始化该配方：不初始化即不可能被启用。

    注册复写为什么是注入而不是本模块 import：

    注册须校验邀请码（认证与账号第 4 节），而邀请码的存储与状态机在
    `modules/accounts`。`core/*` 不得依赖 `modules/*`（项目结构设计第 7 节），
    因此本模块不 import 那个模块，而是由装配处（`main.py`）把复写函数传进来——
    与「工具注册在装配处完成」同一种做法。

    为什么两个参数必须同时给出（否则显式拒绝）：

    评审实测（2026-09-30）两者单独给的效果不对称，而这个不对称是危险的：

    传了 → 结果
    - 只传 `api_overrides` → 未声明的表单字段让请求在复写之前被拒 → 「永远拒绝注册」（可用性问题，fail-closed）
    - 只传 `sign_up_form_fields` → 邀请码校验被彻底绕过：实测无码、空码、乱码码三种都注册成功（安全缺口，fail-open）

    后者会静默地把「须凭邀请码注册」（`RQ-ACC-04`）变成「任何人都能注册」。
    因此这里不接受单独给出二者之一：一旦给了其中一个，另一个也必须给，
    否则抛 :class:`SuperTokensConfigurationError`。
    让危险的组合无法被表达，比在文档里提醒可靠。

    Args:
        settings: 应用配置（唯一配置入口）。
        api_overrides: API 复写（注册时校验邀请码）。必须与
            `sign_up_form_fields` 同给同不给。
        sign_up_form_fields: signup 自定义表单字段声明。必须与
            `api_overrides` 同给同不给。

    Raises:
        SuperTokensConfigurationError: 缺少必需的配置项，或只给了两个注册相关参数之一。
    """
    # 进程级规范化 no_proxy（2026-10-05，T18 修）：这是本仓**唯一**的 SDK 装配入口，
    # 因此 **API 与 CLI** 的装配都经它——API 走 `main.py` 的 lifespan，
    # CLI 走 `cli/operator._init_supertokens_for_cli`。放在这里而不是各入口各调一次，
    # 与 `require_session` 固定 `check_database=True` 是同一种做法：**让正确的行为
    # 无法被遗忘**——「记得在启动器里设环境变量」正是此前失败的形态。
    #
    # ⚠ **Worker 不在此列**（2026-10-06 订正，T18 复查发现的 P2）：`worker.py` **不调**
    # `init_supertokens`（Worker 不需要 SDK 的 emailpassword recipe），它靠**自己模块导入期**
    # 那一句 `apply_no_proxy_normalization()`（`worker.py:47`）覆盖同一件事。
    # 订正这句话不是为了措辞准确而已：**原先的「三进程都经它」会让后来者以为 Worker
    # 的入口调用是多余的、从而删掉它**——而删掉之后 Worker 侧会重新暴露在同一个代理陷阱下。
    # 两个入口各自独立地做这件事是**刻意的**（见 `worker.py:41-46` 的「入口级保证」论证）。
    #
    # 为什么必须有它：SDK 的 querier 在**每次请求**里自己
    # `AsyncClient(timeout=30.0)`（`querier.py:110`，**未传 `trust_env=False`**），
    # 因此「构造窗口」式的临时规范化覆盖不到它——宿主机 `no_proxy` 含 `[::1]` 时，
    # 注册与登录的第一步就在 httpx 构造期抛 `InvalidURL: Invalid port: ':1]'` ⇒ 整体 500，
    # 而 `/readyz` 的 auth 探针（`trust_env=False`）与 `agent/model` 的网关
    # （构造窗口规范化）**两条路径都不覆盖它** ⇒ 探针绿而功能坏。
    #
    # 时序：本语句在 SDK `init(...)` 之前执行，而 querier 的 `AsyncClient` 在**请求期**
    # 才构造 ⇒ 规范化必然早于任何 querier 客户端构造。机械证据（含「撤掉本语句 ⇒ 用例红」）
    # 见 `apps/api/tests/test_proxy_env_normalization.py`。
    apply_no_proxy_normalization()

    api_key = _require_api_key(settings)

    # 成对校验：见 docstring 的实测表。
    # 方向安全——漏传 api_overrides 是 fail-open。
    if (api_overrides is None) != (sign_up_form_fields is None):
        raise SuperTokensConfigurationError(
            "api_overrides 与 sign_up_form_fields 必须同时给出："
            "只给 api_overrides 会让注册永远被拒（表单字段未声明）；"
            "只给 sign_up_form_fields 会**完全绕过邀请码校验**（任何人可注册）"
        )

    override_config = InputOverrideConfig(apis=api_overrides) if api_overrides is not None else None
    sign_up_feature = InputSignUpFeature(form_fields=sign_up_form_fields()) if sign_up_form_fields is not None else None

    init(
        app_info=InputAppInfo(
            app_name="篝火智答",
            api_domain=settings.supertokens_api_domain,
            website_domain=settings.supertokens_website_domain,
            api_base_path=settings.supertokens_api_base_path,
            # 前端与 API 同源部署（经同一 Nginx），website_base_path 与 api_base_path
            # 一致即可；两者不同会改变 SDK 生成的重定向地址。
            website_base_path=settings.supertokens_api_base_path,
        ),
        framework="fastapi",
        supertokens_config=SupertokensConfig(
            connection_uri=settings.supertokens_connection_uri,
            api_key=api_key,
        ),
        recipe_list=[
            session.init(
                anti_csrf="VIA_CUSTOM_HEADER",
                # 固定为 cookie 传输（2026-09-30 评审抓出，实测确认）。
                #
                # 不固定时 SDK 的默认是「按请求头决定，缺省落 header」：实测
                # `session_request_functions.py:285-290` —— `output_transfer_method`
                # 为 `"any"` 且无 `st-auth-mode` 头时落成 `"header"`。
                # 于是注册会把 access/refresh token 放进响应头
                # （实测响应头含 `st-access-token`、`Set-Cookie` 数为 0），
                # 而响应头对前端 JavaScript 是可读的——与认证与账号第 5 节
                # 「cookie 型会话，凭据不可被前端 JavaScript 读取」以及
                # 项目结构设计第 9 节「前端不得读取或存储凭据」直接冲突。
                #
                # 固定成 cookie 后：凭据只在 `Set-Cookie` 里（HttpOnly 由 SDK 设置），
                # 前端 JS 读不到；anti-CSRF 仍由 `VIA_CUSTOM_HEADER` 覆盖写操作。
                get_token_transfer_method=lambda _req, _for_create, _ctx: "cookie",
            ),
            emailpassword.init(sign_up_feature=sign_up_feature, override=override_config),
        ],
        mode="asgi",
    )


def require_session() -> SessionDependency:
    """唯一的会话校验依赖。FastAPI 依赖注入用。

    本模块存在的唯一理由：把「逐请求查证」变成不可遗忘的默认

    [认证与账号] 第 6 节与决策记录要求每个受限操作都开启数据库查证
    （`check_database=True`），否则撤销不即时（`AC-17`、`RQ-ACC-06` 落空）。

    实测（2026-09-30，真实 core + 真实库）——这个开关的性质决定了本模块的形状：

    撤销会话后，用同一个 access token 校验 → 结果
    - `check_database` 不传（SDK 默认） → 仍然通过：「撤销未即时生效」
    - `check_database=True` → 被拒：`Either the session has ended or has been blacklisted`

    关键事实：`check_database` 不是 `session.init` 的初始化选项，而是
    每一次调用都要传的参数（实测 `session.init` 的签名里没有它；
    `recipe/session/framework/fastapi/__init__.py` 的 `verify_session` 默认值是
    `check_database: bool = False`）。

    因此「忘了传」不会报错，只会静默失去撤销能力——这正是决策记录那条不变量
    （「不得只在部分端点开启」）在实现层最容易被违反的方式。本模块的应对是：
    不暴露任何能绕过它的调用形态——对外只提供 :func:`require_session`，
    它在内部固定传 `True`，调用方没有机会漏传。

        ❌ 不要在生产代码里直接 `from supertokens_python... import verify_session`
           再自己传参。那样本模块的保证就被绕过了（`test_auth_supertokens` 会盯着这点）。

    为什么必须经由这个函数（而不是直接用 SDK 的 `verify_session`）：

    SDK 的 `verify_session` 默认 `check_database=False`，且它是每次调用的参数
    而非初始化选项（实测，见模块说明）。直接使用它意味着每一处调用点都要记得传
    `True`——漏一处，那条路径的撤销就静默失效，而没有任何东西会报错。

    本函数把该参数固定在内部，调用方没有机会漏传：

        @app.get("/protected")
        async def protected(session: SessionContainer = Depends(require_session())):
            ...

    返回的是 SDK 的依赖函数（而不是我们自己包一层），这样 FastAPI 的依赖注入、
    以及 SDK 自身的 cookie/anti-CSRF 处理都保持原生行为——我们只固定那一个开关。

    `session_required=True` 是刻意的：全应用必须登录（`RQ-ACC-01`），
    不存在匿名可达的业务路径（唯一例外是运维探针 `GET /health`，它不经过本依赖）。

    fail-closed：

    core 不可达时拒绝，不回退到无状态校验——决策记录明文要求
    （「数据库查证失败一律拒绝……回退等于在故障时静默关闭撤销能力」）。
    这一点由 SDK 的行为保证（查证失败即抛 `UnauthorisedError`/异常），
    本模块不做任何兜底捕获后放行。
    """
    return verify_session(
        # 这两个默认值都由 SDK 决定，不在此处覆盖：
        # - anti_csrf_check=None：由请求上下文读取自定义头（走 HTTP 时才能真正校验，
        #   这正是我们要的）。
        # - session_required=True：显式写出，因为它是「全应用必须登录」的体现。
        session_required=True,
        # ==== 本模块存在的理由：固定为 True，不可由调用方覆盖 ====
        # 撤下它就等于撤下「撤销即时生效」（AC-17 / RQ-ACC-06）。
        check_database=True,
    )


def check_supertokens_configuration(settings: Settings) -> ComponentHealth:
    """装配期自检：报告 SDK 配置是否齐备（不发起网络请求）。

    与 :func:`campfire.core.auth.check_auth_core` 的分工：那个探 core 可达性，
    这个只回答「我们这边的配置能不能装配起来」。两者都是必要的——
    core 活着但没配 API Key 时，注册仍会失败，而可达性探针是绿的。

    不发起网络请求是刻意的：健康检查不该因为配置检查而多一次往返。
    """
    missing = []
    if settings.supertokens_api_key is None:
        missing.append("SUPERTOKENS_API_KEY")
    if not settings.supertokens_connection_uri:
        missing.append("SUPERTOKENS_CONNECTION_URI")

    if missing:
        return ComponentHealth(
            AUTH_COMPONENT,
            Status.NOT_CONFIGURED,
            f"缺少 {'、'.join(missing)}",
        )
    return ComponentHealth(AUTH_COMPONENT, Status.OK, "配置齐备")


__all__ = [
    "AUTH_COMPONENT",
    "SuperTokensConfigurationError",
    "check_supertokens_configuration",
    "init_supertokens",
    "require_session",
    "SessionContainer",
]
