"""端到端：会话的建立、撤销与即时失效（真实 SuperTokens core + 真实库）。

这条用例存在的理由：把「`check_database=True` 才即时失效」这一实测事实钉住。
静态检查（`test_auth_supertokens.py`）只能证明「我们传了 True」，证明不了
「传 True 之后撤销真的即时生效」——那需要真实 core。

    docker compose up -d postgres supertokens
    uv run pytest -m integration apps/api/tests/test_auth_session_lifecycle_integration.py

本文件同时是「为什么 `check_database` 不能忘传」的证据：

实测（2026-09-30，core 12.2.0 + supertokens-python 0.31.3）：

- 撤销会话后，用同一个 access token 校验，`check_database` 不传（SDK 默认 False）→ 仍然通过
- `check_database=True` → 被拒：`Either the session has ended or has been blacklisted`

`test_default_check_database_does_not_revoke_immediately` 把这个反例写成用例：
它故意断言「默认参数下撤销不即时」。这不是在测我们的代码有 bug，而是把
SDK 的默认行为固定成可复核的事实——一旦上游改了默认值（那对我们是好事），
这条用例会失败，提示我们去简化 `require_session` 的注释与理由。

覆盖边界（诚实声明）：

- CI 不执行本文件：它需要真实 core，而 CI 的 backend 作业没有 postgres/core
  service。因此它是本地集成测试，不是 CI 闸门（该缺口已登记于 `docs/TODO.md`）。
- 它验证的是 SDK 层的会话语义（建立 → 撤销 → 失效），不经过 HTTP，
  因此不覆盖 cookie 传输、anti-CSRF 自定义头与 `/auth/*` 路由挂载——
  那需要 ASGI 级别的端到端测试，属后续工作。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from campfire.core.config import Settings, get_settings

if TYPE_CHECKING:
    from supertokens_python.recipe.emailpassword.interfaces import SignUpOkResult
    from supertokens_python.recipe.session.interfaces import SessionContainer

pytestmark = pytest.mark.integration

#: 测试用的账号名后缀（避免与开发库里的真实账号撞名）。
_TEST_EMAIL_DOMAIN = "session-lifecycle.test"


@pytest.fixture(autouse=True)
def _normalise_env_for_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉宿主机代理变量——实测必须，否则 SDK 连构造客户端都失败。

    实测：本机 `no_proxy` 含带方括号的 IPv6 字面量（`[::1]`），httpx 在
    构造客户端时即抛 `InvalidURL: Invalid port: ':1]'`。仓库 `conftest.py`
    已把 `no_proxy`/`NO_PROXY` 归一到合法值，但宿主的 `HTTP_PROXY` 仍在，
    而 SDK 的 querier 自己 `new httpx.AsyncClient(timeout=30.0)`（未传
    `trust_env=False`）——所以这里额外清掉代理本身，让请求直连 localhost。

    这属测试环境适配，不是产品行为：生产里 core 是同机/内网服务，
    部署编排会给出正确的 `no_proxy`（见技术栈设计第 6 节的暴露面约束）。
    """
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")


def _settings_or_skip() -> Settings:
    """取配置；缺 API Key 或未配库时跳过——不假装通过。

    缺 API Key 时 core 会拒掉所有 Management API 请求（实测 `401 Invalid API key`），
    因此那是「环境未就绪」而不是「代码有问题」。
    """
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    if settings.supertokens_api_key is None:
        pytest.skip(
            "未配置 SUPERTOKENS_API_KEY——集成测试需要 docker compose up -d supertokens"
            "（且 .env 里的 SUPERTOKENS_API_KEY 要与容器 API_KEYS 一致）"
        )
    return settings


async def _core_reachable() -> bool:
    """core 是否可达（不可达则跳过，而不是报一个看起来像代码缺陷的错）。"""
    from campfire.core.auth import check_auth_core

    health = await check_auth_core(get_settings())
    from campfire.core.health import Status

    return health.status is Status.OK


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """装配 SDK 并返回配置；core 不可达时跳过。

    `init_supertokens` 是幂等的（SDK 内部只在 `__instance is None` 时构造），
    因此各用例重复调用没有问题；但测试之间共享同一实例意味着 app_info 等
    一经设定不再改变——所以本文件不尝试在同一进程里换配置。
    """
    settings = _settings_or_skip()

    import asyncio

    if not asyncio.run(_core_reachable()):
        pytest.skip("SuperTokens core 不可达——集成测试需要 docker compose up -d supertokens")

    from campfire.core.auth import supertokens as st

    st.init_supertokens(settings)
    return settings


async def _create_account(email: str, password: str) -> SignUpOkResult:
    """建一个账号（经 SDK 的公开 API，走真实 core）。

    `sign_up` 的返回是「成功 | 邮箱已存在 | 链接到会话用户失败」的联合；断言收窄成
    `SignUpOkResult` 而不是声明 `object`——后者会让调用方丢掉 `user`，而本文件后面
    要用 `signup.user.id` 撤销该用户的全部会话。收窄同时是一条真判据：建号失败即失败，
    不静默带着一个「不是成功结果」的东西继续跑。
    """
    from supertokens_python.recipe.emailpassword.asyncio import sign_up
    from supertokens_python.recipe.emailpassword.interfaces import SignUpOkResult

    result = await sign_up("public", email, password)
    assert isinstance(result, SignUpOkResult), f"建号未成功：{result}"
    return result


async def _sign_in_and_open_session(email: str, password: str) -> SessionContainer:
    """登录并建立一个会话，返回 `SessionContainer`。

    注意：本 SDK 版本的 `sign_in` 不返回会话对象（实测 `SignInOkResult`
    只有 `user` 与 `recipe_user_id`），会话须另经
    `create_new_session_without_request_response` 建立。
    """
    from supertokens_python.recipe.emailpassword.asyncio import sign_in
    from supertokens_python.recipe.emailpassword.interfaces import SignInOkResult
    from supertokens_python.recipe.session.asyncio import create_new_session_without_request_response

    signin = await sign_in("public", email, password)
    assert isinstance(signin, SignInOkResult), f"登录未成功：{signin}"
    return await create_new_session_without_request_response("public", signin.recipe_user_id)


async def _verify(access_token: str, *, check_database: bool) -> bool:
    """校验令牌，返回是否被接受。

    `anti_csrf_check=False`：本文件不经过 HTTP，没有请求上下文可供读取
    自定义头，而 `VIA_CUSTOM_HEADER` 下 SDK 在无上下文时会直接抛异常（实测）。
    这一处显式传参不会削弱被测性质——被测的是 `check_database`。
    """
    from supertokens_python.recipe.session.asyncio import get_session_without_request_response
    from supertokens_python.recipe.session.exceptions import UnauthorisedError

    try:
        session = await get_session_without_request_response(
            access_token, anti_csrf_check=False, check_database=check_database
        )
    except UnauthorisedError:
        return False
    return session is not None


async def _unique_email() -> str:
    """生成一个未用过的账号名（真实 core 会记住账号，重复注册会失败）。"""
    import uuid

    return f"probe-{uuid.uuid4().hex[:12]}@{_TEST_EMAIL_DOMAIN}"


# ---------------------------------------------------------------------------
# 核心：撤销的即时性（AC-17 / RQ-ACC-06 的机制依据）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_session_is_rejected_immediately_with_check_database(sdk: Settings) -> None:
    """撤销后，同一个 access token 立即被拒（`check_database=True`）。

    这是 `AC-17`（重置后旧会话立即失效）与 `RQ-ACC-06` 的机制依据——
    `require_session` 固定传 True，正是为了这条成立。
    """
    email = await _unique_email()
    await _create_account(email, "probePass123")
    session = await _sign_in_and_open_session(email, "probePass123")
    token = session.get_access_token()
    handle = session.get_handle()

    # 撤销前：被接受（先证明令牌本身有效，否则下面的断言没有判别力）。
    assert await _verify(token, check_database=True) is True, "撤销前的有效令牌必须被接受"

    # 撤销（登出 / 人工重置时撤销全部会话走的就是这条）。
    from supertokens_python.recipe.session.asyncio import revoke_session

    await revoke_session(handle)

    assert await _verify(token, check_database=True) is False, (
        "撤销后同一个 access token 仍被接受——check_database=True 没有生效，AC-17 与 RQ-ACC-06 落空"
    )


@pytest.mark.asyncio
async def test_default_check_database_does_not_revoke_immediately(sdk: Settings) -> None:
    """反例（固定 SDK 的默认行为）：不传 `check_database` 时，撤销不即时生效。

    为什么把「缺陷行为」写成用例：

    这不是在断言我们的代码有问题，而是把 SDK 的默认值固定成可复核的事实：

    - 它是 `require_session` 存在的全部理由——若默认值就是 True，
      我们不需要那个包装层。
    - 一旦上游把默认改为 True（那对我们是好事），本用例会失败，
      提示我们回来简化注释与理由，而不是让一段「因为实测如此」的说明永远留着却已过期。

    判别性：若这条用例失败（默认已即时失效），说明 SDK 升级改变了语义，
    必须重新评估 `require_session` 是否仍必要。
    """
    email = await _unique_email()
    await _create_account(email, "probePass123")
    session = await _sign_in_and_open_session(email, "probePass123")
    token = session.get_access_token()
    handle = session.get_handle()

    from supertokens_python.recipe.session.asyncio import revoke_session

    await revoke_session(handle)

    accepted_by_default = await _verify(token, check_database=False)
    assert accepted_by_default is True, (
        "SDK 的默认行为变了：不传 check_database 时撤销**已经**即时生效。"
        "这是好消息，但意味着 require_session 的包装与认证文档的理由需要重新审视——"
        "不要把这条用例改成断言 False 就完事。"
    )


@pytest.mark.asyncio
async def test_revoking_all_sessions_invalidates_every_token(sdk: Settings) -> None:
    """撤销该用户全部会话：两个会话的令牌都立即失效。

    人工重置走的是这一步（`revoke_all_sessions_for_user`）——重置要撤掉的是
    「重置前签发的所有会话」，而不只是当前那一个（`AC-17` 原文）。
    """
    email = await _unique_email()
    signup = await _create_account(email, "probePass123")

    first = await _sign_in_and_open_session(email, "probePass123")
    second = await _sign_in_and_open_session(email, "probePass123")
    first_token = first.get_access_token()
    second_token = second.get_access_token()

    assert await _verify(first_token, check_database=True) is True
    assert await _verify(second_token, check_database=True) is True

    from supertokens_python.recipe.session.asyncio import revoke_all_sessions_for_user

    await revoke_all_sessions_for_user(signup.user.id)

    assert await _verify(first_token, check_database=True) is False, "第一个会话未被撤销"
    assert await _verify(second_token, check_database=True) is False, "第二个会话未被撤销"
