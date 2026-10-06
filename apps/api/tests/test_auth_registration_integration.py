"""端到端：注册经 HTTP 走通邀请码校验，且无效码绝不建号。

    docker compose up -d postgres supertokens
    uv run pytest -m integration apps/api/tests/test_auth_registration_integration.py

这个文件钉住的是 `AC-15` 的核心断言：

`AC-15` 要求「无码或无效码拒绝注册；撤销后不可用；校验在自己的后端」。
仅断言「HTTP 返回了错误」是不够的——真正要证明的是「身份服务侧没有新建用户」，
因为「拒绝」与「建了号再报错」在响应上看起来可以一样，而后者已经消耗了邀请码
并留下了用户记录。因此本文件的每条拒绝用例都回查身份服务确认账号不存在。

为什么用 ASGI 直连而不是起一个真服务器：

`httpx.ASGITransport` 让请求穿过完整的 FastAPI 应用（含 SuperTokens 中间件、
cookie 处理、路由分派），但不占端口、不需要网络。这比「起 uvicorn 再打 localhost」
更可靠（没有端口冲突与启动竞态），且仍然覆盖中间件行为——中间件是这一步的实现本身。

覆盖边界（诚实声明）：

- CI 不执行本文件：它需要真实 postgres 与 supertokens，而 CI 的 backend 作业
  两者都没有（缺口已登记于 `docs/TODO.md`）。
- 本文件不校验 anti-CSRF 自定义头的真实生效——那是 signin/refresh 路径的行为，
  且需要从前端 SDK 的调用形态出发构造；注册路径的 CSRF 语义不在本文件范围内。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete
from supertokens_python.recipe.emailpassword.types import FormField

from campfire.core.config import Settings, get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts import (
    INVITE_CODE_FORM_FIELD,
    STATE_ISSUED,
    InviteCode,
    claim_invite_code,
    get_invite_code,
    issue_invite_code,
    normalize_invite_code,
    revoke_invite_code,
)

pytestmark = pytest.mark.integration

#: 本文件的账号名域（避免与开发库里的真实账号撞名）。
_EMAIL_DOMAIN = "registration-e2e.test"

#: 测试密码：满足官方默认校验器（≥8 字符 + 小写字母 + 数字）。
_PASSWORD = "probePass123"

#: 本文件签发邀请码时使用的运营者标识。它同时是清理的过滤条件——
#: 见 :func:`_clear`（不能全表删除，否则并发跑时会删掉别的测试文件刚签发的码）。
_OPERATOR = "it_registration"


@pytest.fixture(autouse=True)
def _normalise_env_for_sdk(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """清掉宿主机代理变量——SDK 的 httpx 客户端在构造期就会被它弄坏。

    实测：本机 `no_proxy` 含 `[::1]`，httpx 构造客户端即抛
    `InvalidURL: Invalid port: ':1]'`；SDK 的 querier 自己 new `AsyncClient`
    （未传 `trust_env=False`），因此必须清掉代理本身。属测试环境适配，
    生产由部署编排给出正确的 `no_proxy`。
    """
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    yield


def _settings_or_skip() -> Settings:
    """取配置；缺库或缺 API Key 时跳过——不假装通过。"""
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    if settings.supertokens_api_key is None:
        pytest.skip("未配置 SUPERTOKENS_API_KEY——集成测试需要 docker compose up -d supertokens")
    return settings


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """返回一个穿过完整应用（含 SuperTokens 中间件）的 ASGI 客户端。

    core 不可达时跳过：那时注册失败的原因是环境，不是被测代码。
    """
    from campfire.core.auth import check_auth_core
    from campfire.core.health import Status

    settings = _settings_or_skip()
    if (await check_auth_core(settings)).status is not Status.OK:
        pytest.skip("SuperTokens core 不可达——集成测试需要 docker compose up -d supertokens")

    # 应用装配（lifespan 不会在 ASGITransport 下自动运行，故显式初始化 SDK）。
    import campfire.main as main_module
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)

    transport = httpx.ASGITransport(app=main_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


async def _require_core_and_init() -> Settings:
    """校验环境并完成 SDK 装配；core 不可达即跳过。

    从 `client` 夹具里抽出来，供不用该夹具的用例复用（它们直接调复写函数，
    原因见 `test_non_ok_result_with_account_created_does_not_release_the_code` 的说明）。

    为什么必须抽出来而不是各写一遍：漏掉 `init_supertokens` 的后果是
    `GeneralError: Initialisation not done`——那看起来像代码缺陷，实际是装配缺失。
    实测在无 core 的 CI 环境里，漏掉它的那条用例是 failed 而不是 skipped。
    """
    from campfire.core.auth import check_auth_core
    from campfire.core.health import Status

    settings = _settings_or_skip()
    if (await check_auth_core(settings)).status is not Status.OK:
        pytest.skip("SuperTokens core 不可达——集成测试需要 docker compose up -d supertokens")

    # 应用装配（lifespan 不会在 ASGITransport 下自动运行，故显式初始化 SDK）。
    from campfire.core.auth.supertokens import init_supertokens
    from campfire.modules.accounts.registration import api_overrides, sign_up_form_fields

    init_supertokens(settings, api_overrides=api_overrides, sign_up_form_fields=sign_up_form_fields)
    return settings


async def _clear() -> None:
    """清掉本文件写入的邀请码行。

    必须按签发者过滤，不能全表删除（2026-09-30 实测的真实缺陷）：本文件与
    `test_accounts_invite_integration.py` 原先都做无过滤的 `delete(InviteCode)`，
    于是并发运行时互相删对方刚签发的码——实测一次并发跑出现
    `InviteCodeNotFoundError`（补偿释放找不到码），而单跑必然通过。
    签发者标识把删除范围收窄到本文件。

    账号不能清：它们在 SuperTokens core 的库里，而本文件不实现删除用户的用例
    （那是账号注销的功能，属另一次改动）。因此账号名必须每次唯一——
    见 :func:`_unique_email`；否则第二次跑同一用例会因「账号已存在」而失败，
    表现为「注册测试不稳定」而不是「环境有残留」。
    """
    async with session_scope(get_settings()) as session:
        await session.execute(delete(InviteCode).where(InviteCode.created_by == _OPERATOR))


def _unique_email(prefix: str = "acct") -> str:
    """生成唯一的账号名。

    必须唯一：SuperTokens core 会永久记住账号（本文件不清理它们），
    固定名字会让「第二次运行」变成「账号已存在」——而那是建号失败路径，
    于是拒绝类用例会以错误的原因通过（假通过）。
    """
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}@{_EMAIL_DOMAIN}"


async def _issue_code() -> str:
    """签发一张可用的邀请码。"""
    async with session_scope(get_settings()) as session:
        record = await issue_invite_code(session, created_by=_OPERATOR)
        return record.code


def _signup_payload(email: str, invite_code: str | None) -> dict[str, object]:
    """构造身份服务 signup 的表单体（SDK 的线格式）。

    实测格式：身份服务的 signup 端点是 `{"formFields": [{"id": ..., "value": ...}]}`，
    不是扁平的 JSON 对象。第一版按扁平对象构造，实测全部请求返回 200 +
    `FIELD_ERROR`「Field is not optional」——即请求压根没到达我们的复写。
    测试用错格式会制造「以为在测拒绝路径、实际在测字段缺失」的假象。

    邀请码作为自定义字段一并放进 `formFields`（字段名见
    `INVITE_CODE_FORM_FIELD`），这正是前端要照做的形状。
    """
    form_fields = [
        {"id": "email", "value": email},
        {"id": "password", "value": _PASSWORD},
    ]
    if invite_code is not None:
        form_fields.append({"id": INVITE_CODE_FORM_FIELD, "value": invite_code})
    return {"formFields": form_fields}


def _status_of(response: httpx.Response) -> str:
    """取响应体里的 `status`（身份服务的业务结果字段）。

    它不是 HTTP 状态码：实测拒绝也是 200，见模块说明。
    """
    body = response.json()
    assert isinstance(body, dict), f"身份服务返回了非对象响应体：{body!r}"
    status = body.get("status")
    assert isinstance(status, str), f"响应体里没有 status 字段：{body!r}"
    return status


def _is_ok(response: httpx.Response) -> bool:
    """注册是否成功（`status == "OK"`）。"""
    return _status_of(response) == "OK"


def _is_rejected(response: httpx.Response) -> bool:
    """注册是否被我们拒绝（`GENERAL_ERROR`）。

    刻意不接受 `FIELD_ERROR`：那是 SDK 的表单校验失败（字段缺失或格式错），
    意味着请求没有到达我们的复写。把它当成「拒绝生效」，会让用例在
    「复写压根没被调用」时通过——那正是第一版的实际情形。
    """
    return _status_of(response) == "GENERAL_ERROR"


async def _account_exists(email: str) -> bool:
    """回查身份服务：该账号名是否真的存在。

    这是本文件的核心判据——「拒绝」必须意味着「没有创建用户」，
    而不只是「响应看起来像失败」。

    为什么用 `GET /recipe/user?email=`：实测该端点可用（返回
    `{"status":"OK","user":{...}}`；无此用户时 status 非 OK）。第一版用的
    `/recipe/emailpassword/email/exists` 实测 `404`——那是 SDK 内部的常量路径，
    不是 core 的公开 Management API 路径。写错端点的后果是「探针永远失败」，
    而失败信息看起来像被测代码出了问题。
    """
    import httpx

    from campfire.core.auth.supertokens import _require_api_key

    settings = get_settings()
    url = f"{settings.supertokens_connection_uri.rstrip('/')}/recipe/user"
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as http:
            response = await http.get(
                url,
                params={"email": email},
                headers={"api-key": _require_api_key(settings)},
            )
        response.raise_for_status()
        return response.json().get("status") == "OK"
    except Exception as exc:  # noqa: BLE001 —— 探针：查不动就报错，不猜
        raise AssertionError(f"无法回查账号是否存在（{type(exc).__name__}）——本用例的判据失效") from exc


def _signup_path(settings: Settings) -> str:
    """signup 的实际路径（`api_base_path` + SDK 的 `/signup`）。"""
    return f"{settings.supertokens_api_base_path.rstrip('/')}/signup"


#: 本文件用的「不存在的租户」。刻意写死而不是随机：它必须确实不在 `tenants` 表里，
#: 且名字要一眼看出是测试产物（真 core 里只存在 `public`）。
_UNKNOWN_TENANT = "t40-unknown-tenant"


def _signup_path_for_tenant(settings: Settings, tenant_id: str) -> str:
    """带租户段的 signup 路径：`/api/auth/<tenant>/signup`。

    租户**由 URL 路径承载**，不是请求头或请求体：SDK 用正则
    `^{api_base_path}(?:/([a-zA-Z0-9-]+))?(/.*)$` 从路径上切出租户
    （实测 `.venv/.../supertokens_python/recipe_module.py:63-77`）。
    因此「换租户」这件事完全由调用方控制，这正是 C-3 的可探测性来源。
    """
    return f"{settings.supertokens_api_base_path.rstrip('/')}/{tenant_id}/signup"


# ---------------------------------------------------------------------------
# 无效码绝不建号（AC-15 的核心）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_code_creates_the_account(client: httpx.AsyncClient) -> None:
    """正向对照：有效码注册成功，且账号真的建出来了。

    没有这条，下面所有「拒绝」用例都可能是「注册根本不通」造成的假通过。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("ok")
        code = await _issue_code()

        response = await client.post(_signup_path(settings), json=_signup_payload(email, code))

        assert _is_ok(response), f"有效码注册应成功，实际 {_status_of(response)}: {response.text[:400]}"
        assert await _account_exists(email) is True, "注册返回成功但身份服务里没有该账号"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_missing_code_is_rejected_and_creates_no_user(client: httpx.AsyncClient) -> None:
    """不带邀请码 → 拒绝，且身份服务里没有该账号（`AC-15`）。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("nocode")

        response = await client.post(_signup_path(settings), json=_signup_payload(email, None))

        assert _is_rejected(response), f"缺少邀请码时必须被我们的复写拒绝，实际 {_status_of(response)}"
        assert await _account_exists(email) is False, "被拒绝的注册却建出了账号——AC-15 落空"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_unknown_code_is_rejected_and_creates_no_user(client: httpx.AsyncClient) -> None:
    """不存在的邀请码 → 拒绝，且不留下任何用户记录。

    判别性：若实现是「先建号再校验」，本用例的第二条断言失败——而响应看起来
    可能同样是错误码，所以只断言状态码是不足以发现该缺陷的。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("badcode")

        response = await client.post(_signup_path(settings), json=_signup_payload(email, "ZZZZZZZZ"))

        assert _is_rejected(response), f"无效邀请码必须拒绝，实际 {_status_of(response)}"
        assert await _account_exists(email) is False, "无效码的注册建出了账号——AC-15 落空"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_revoked_code_is_rejected_and_creates_no_user(client: httpx.AsyncClient) -> None:
    """已撤销的邀请码 → 拒绝，且不建号（`AC-15`「撤销后不可用」）。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        code = await _issue_code()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=code)

        email = _unique_email("revoked")
        response = await client.post(_signup_path(settings), json=_signup_payload(email, code))

        assert _is_rejected(response), f"已撤销的邀请码必须拒绝，实际 {_status_of(response)}"
        assert await _account_exists(email) is False, "已撤销码的注册建出了账号"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_used_code_is_rejected_the_second_time(client: httpx.AsyncClient) -> None:
    """一码只用一次：同一张码第二次注册被拒，且第二个账号不存在。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        code = await _issue_code()
        first = _unique_email("first")
        second = _unique_email("second")

        first_response = await client.post(_signup_path(settings), json=_signup_payload(first, code))
        assert _is_ok(first_response), f"首次注册应成功：{first_response.text[:300]}"

        second_response = await client.post(_signup_path(settings), json=_signup_payload(second, code))
        assert _is_rejected(second_response), f"同一张邀请码不得用第二次，实际 {_status_of(second_response)}"
        assert await _account_exists(second) is False, "第二次注册建出了账号——一码多用"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_duplicate_account_name_releases_the_code(client: httpx.AsyncClient) -> None:
    """建号失败 → 补偿释放：账号名重复时该码回到可用状态（第 4 节步骤 3）。

    判别性：若实现漏了补偿释放，该码会永久停在「已占用」，使用者拿到一个新码
    也救不回这张——本用例断言同一张码在失败后仍可成功注册。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("dup")
        first_code = await _issue_code()

        ok = await client.post(_signup_path(settings), json=_signup_payload(email, first_code))
        assert _is_ok(ok), f"首次注册应成功：{ok.text[:300]}"

        # 用新码 + 同一个账号名 → 建号失败（账号已存在），该新码应被释放。
        second_code = await _issue_code()
        conflict = await client.post(_signup_path(settings), json=_signup_payload(email, second_code))
        assert not _is_ok(conflict), f"重复账号名必须失败：{conflict.text[:300]}"

        # 关键断言：那张码已回到 issued，可再次使用（换一个账号名）。
        from campfire.modules.accounts import get_invite_code, normalize_invite_code

        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=normalize_invite_code(second_code))
        assert record is not None
        assert record.state == STATE_ISSUED, (
            f"建号失败后邀请码应被补偿释放回 issued，实际 {record.state}——该码会永久停在已占用，使用者必须重新索码"
        )

        another = _unique_email("dup2")
        reuse = await client.post(_signup_path(settings), json=_signup_payload(another, second_code))
        assert _is_ok(reuse), f"被释放的码应可再次使用：{reuse.text[:300]}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_non_ok_result_with_account_created_does_not_release_the_code() -> None:
    """账号已建但结果非 OK 时，不得释放邀请码（2026-09-30 审查发现的重要缺陷）。

    这条用例守的是什么：

    第 4 节的补偿释放依赖「建号失败」。但「原实现返回非 OK」≠「没有建号」：
    实测已装 SDK 的源码（`recipe/emailpassword/api/implementation.py`）顺序是
    `:738` 建号 → `:755` `post_auth_checks` → `:766` 不通过则返回
    `SignUpPostNotAllowedResponse`（非 OK）。即存在
    「账号已建、结果却不是 OK」的真实路径。

    修复前代码对此无条件释放，于是同一个码可以再建一个账号——
    「一码只用一次」（`AC-15`）被破坏，且第一张码的记录会被第二次绑定覆盖，
    运营看不出发生过两次注册。

    为什么这层用「直接调用复写函数」而不是 HTTP 端到端：

    实测 `Supertokens.reset()` 之后再次 `init` 会抛
    `GeneralError: Session recipe has already been initialised`——SDK 的 reset
    只重置 Supertokens 实例、不重置各 recipe，同一进程内换一套复写不可行。
    因此这里直接调用 :func:`make_sign_up_override` 返回的包装函数，传入一个
    假的 original：它真的建一个账号（走 SDK），然后返回非 OK。
    这精确复现了目标组合，且不依赖 `post_auth_checks` 的内部触发条件。

    顺带的好处：它同时绕开了 HTTP 层，因此不需要 core 之外的任何夹具。

    判别性：把 `registration.py` 里 `_account_exists` 那层判断去掉
    （恢复为无条件释放），本用例失败——码会回到 `issued`、可被再次占用。
    """
    # 前置检查用 `_settings_or_skip()`；但本用例不走 `client` 夹具（它直接调用复写
    # 函数，见上文理由），因此必须自己完成 SDK 装配——否则 `sign_up` 会抛
    # `GeneralError: Initialisation not done`。
    #
    # 这是实测踩到的缺陷（2026-10-01）：在没有真实 core 的环境（CI）里，本用例因为
    # 少了这一步而 failed，看起来像代码缺陷，实际是「夹具没被用到、初始化就漏了」。
    # 补上之后它在无 core 环境下会正确地 skip（`_core_reachable` 判定）。
    await _require_core_and_init()
    await _clear()
    try:
        from supertokens_python.recipe.emailpassword.asyncio import sign_up
        from supertokens_python.recipe.emailpassword.interfaces import SignUpPostNotAllowedResponse

        from campfire.modules.accounts import registration as reg

        email = _unique_email("nonok")
        code = await _issue_code()

        async def fake_original(  # noqa: ANN202 —— 模拟 SDK：先建号，再返回非 OK
            form_fields, tenant_id, session, linking, api_options, user_context
        ):
            """复现 SDK 的真实顺序：建号成功，但结果是非 OK。"""
            created = await sign_up(tenant_id, email, _PASSWORD)
            assert type(created).__name__.startswith("SignUpOk"), f"构造失败，账号没建出来：{created}"
            return SignUpPostNotAllowedResponse(reason="testing")

        override = reg.make_sign_up_override(fake_original)
        result = await override(
            [FormField("email", email), FormField("password", _PASSWORD), FormField(INVITE_CODE_FORM_FIELD, code)],
            "public",
            None,
            None,
            None,
            {},
        )

        assert type(result).__name__ == "SignUpPostNotAllowedResponse", "本用例要构造的是非 OK 结果"
        # 前置确认：账号确实建出来了（否则本用例没有判别力）。
        assert await _account_exists(email) is True, "构造失败：账号没建出来，本用例失去判别力"

        # 核心断言：该码不得回到 issued（它已被一次真实注册用掉）。
        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=normalize_invite_code(code))
        assert record is not None
        assert record.state != STATE_ISSUED, (
            "账号已建却被释放了邀请码——同一个码可以再建一个账号，"
            "「一码只用一次」（AC-15）被破坏；且原绑定会被覆盖，运营看不出发生过两次注册"
        )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_exception_after_account_created_does_not_release_the_code(client: httpx.AsyncClient) -> None:
    """建号成功后 original 抛异常时，不得释放邀请码（阻断级缺陷的回归测试）。

    这条守的是什么：

    SDK 的顺序是 `implementation.py:738` 建号 → `:755` `post_auth_checks`
    → 再 `create_new_session`——建号之后仍有会抛异常的步骤。
    修复前 `except Exception` 分支无条件释放邀请码，于是存在真实路径：
    「账号已建、随后抛异常」→ 码退回 `issued` → 同一张码再建第二个账号
    （`AC-15`「一码只用一次」被破坏）。

    评审实测复现方式：劫持 `create_new_session` 令其抛错，走完整 HTTP 注册，
    得到「账号已建但码回到 issued」。本用例用假的 original（真的建号、然后抛错）
    复现同一组合，无需劫持 SDK 内部函数。

    判别性：把 `except` 分支改回无条件 `_release_quietly(code)`，本用例失败
    （码会回到 `issued`）。
    """
    # client 夹具已负责「未配置即跳过」并初始化 SDK——本用例直接调复写函数，
    # 因此必须依赖它完成的 SDK 装配（第一版漏了这个参数，实测报
    # GeneralError: Initialisation not done）。
    await _clear()
    try:
        from supertokens_python.recipe.emailpassword.asyncio import sign_up

        from campfire.modules.accounts import registration as reg

        email = _unique_email("exc")
        code = await _issue_code()

        async def fake_original(  # noqa: ANN202 —— 模拟 SDK：先建号，再抛异常
            form_fields, tenant_id, session, linking, api_options, user_context
        ):
            created = await sign_up(tenant_id, email, _PASSWORD)
            assert type(created).__name__.startswith("SignUpOk"), f"构造失败，账号没建出来：{created}"
            raise RuntimeError("模拟 create_new_session 失败")

        override = reg.make_sign_up_override(fake_original)
        with pytest.raises(RuntimeError):
            await override(
                [
                    FormField("email", email),
                    FormField("password", _PASSWORD),
                    FormField(INVITE_CODE_FORM_FIELD, code),
                ],
                "public",
                None,
                None,
                None,
                {},
            )

        # 前置确认：账号确实建出来了（否则本用例没有判别力）。
        assert await _account_exists(email) is True, "构造失败：账号没建出来，本用例失去判别力"

        # 核心断言：码不得回到 issued。
        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=normalize_invite_code(code))
        assert record is not None
        assert record.state != STATE_ISSUED, "建号已发生却释放了邀请码——同一个码可以再建一个账号（AC-15 破坏）"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_session_credentials_go_to_cookies_not_headers(client: httpx.AsyncClient) -> None:
    """会话凭据必须走 cookie，不得出现在响应头（2026-09-30 评审抓出的重要级）。

    为什么这是设计冲突而不是风格问题：

    认证与账号第 5 节定的是「cookie 型会话，凭据不可被前端 JavaScript 读取」，
    项目结构设计第 9 节也写「前端不得读取或存储凭据」。而 SDK 的默认传输方式是
    「按 `st-auth-mode` 头决定，缺省落 `header`」——实测
    `session_request_functions.py:285-290`：`"any"` 且无该头时落成 `"header"`。
    于是注册会把 access/refresh token 放进响应头（JS 可读），与上述两条冲突。

    判别性：去掉 `session.init` 里的 `get_token_transfer_method` 固定，
    本用例失败（响应头会重新出现 `st-access-token`、`Set-Cookie` 数为 0）。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("cookie")
        code = await _issue_code()

        response = await client.post(_signup_path(settings), json=_signup_payload(email, code))

        assert _is_ok(response), f"有效码注册应成功：{response.text[:300]}"

        header_names = {name.lower() for name in response.headers}
        assert "st-access-token" not in header_names, (
            "access token 出现在响应头里——前端 JS 可读，与「凭据不可被前端读取」冲突"
        )
        assert "st-refresh-token" not in header_names, "refresh token 出现在响应头里"
        assert len(response.headers.get_list("set-cookie")) > 0, "注册未下发任何 Set-Cookie——凭据没有走 cookie 传输"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_anonymous_account_existence_endpoint_is_disabled(client: httpx.AsyncClient) -> None:
    """匿名的账号存在性端点必须关闭（2026-09-30 评审抓出）。

    SDK 默认挂载 `GET /auth/signup/email/exists`（`disable_email_exists_get`
    默认 `False`），无需会话即可回答「某账号名是否存在」。评审用真实 uvicorn
    实测：已存在 → `200 {"exists":true}`、不存在 → `exists:false`——可区分。
    这与第 5 节「不区分『账号不存在』与『密码错误』」（防账号枚举）是同一条纪律的反面。

    判别性：去掉 `api_overrides` 里的 `disable_email_exists_get = True`，
    本用例失败（该端点会返回 200 并泄露存在性）。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        # 先造一个确实存在的账号，让「可区分」有判别力。
        existing = _unique_email("exists")
        code = await _issue_code()
        created = await client.post(_signup_path(settings), json=_signup_payload(existing, code))
        assert _is_ok(created), f"前置账号创建失败：{created.text[:300]}"

        base = settings.supertokens_api_base_path.rstrip("/")
        for email in (existing, _unique_email("absent")):
            response = await client.get(f"{base}/signup/email/exists", params={"email": email})
            # 端点关闭后应不可用（404 或等价），绝不能返回存在性。
            assert response.status_code != 200, (
                f"匿名存在性端点仍可用（HTTP {response.status_code}，body={response.text[:160]}）"
                "——任何人都能查任意账号名是否存在"
            )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_rejection_message_does_not_distinguish_reasons(client: httpx.AsyncClient) -> None:
    """四种拒绝（缺失/不存在/已撤销/已用）的响应体一致——不可枚举。

    判别性：若实现把四种原因写成不同消息，调用方可逐字区分「码存在但过期」与
    「码不存在」——那就是账号枚举渠道（认证与账号第 5 节同一条纪律）。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        bodies: set[str] = set()

        # 1) 不存在
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("a1"), "ZZZZZZZZ"))
        bodies.add(response.text)

        # 2) 已撤销
        revoked = await _issue_code()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=revoked)
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("a2"), revoked))
        bodies.add(response.text)

        # 3) 已占用
        used = await _issue_code()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=used)
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("a3"), used))
        bodies.add(response.text)

        # 4) 形状不合法（长度不对）
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("a4"), "ABC"))
        bodies.add(response.text)

        assert len(bodies) == 1, (
            f"四种拒绝的响应体必须完全一致（否则构成账号枚举渠道），实测 {len(bodies)} 种：{sorted(bodies)}"
        )
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# 账号名不要求邮箱格式（PROD-01 / RQ-ACC-05）—— 端到端
# ---------------------------------------------------------------------------


def _unique_name(prefix: str = "acct") -> str:
    """生成唯一的**非邮箱**账号名（无 `@`、含中文）。

    与 `_unique_email` 同样是「每次唯一」：身份服务 core 永久记住账号，
    固定名字会让第二次运行变成「账号已存在」。
    """
    import uuid

    return f"{prefix}小安{uuid.uuid4().hex[:10]}"


async def _signin(client: httpx.AsyncClient, account_name: str) -> httpx.Response:
    """用账号名 + 密码登录（signin 的表单体与 signup 同形）。"""
    settings = get_settings()
    path = f"{settings.supertokens_api_base_path.rstrip('/')}/signin"
    return await client.post(
        path,
        json={
            "formFields": [
                {"id": "email", "value": account_name},
                {"id": "password", "value": _PASSWORD},
            ]
        },
    )


@pytest.mark.asyncio
async def test_non_email_account_name_can_register_and_sign_in(client: httpx.AsyncClient) -> None:
    """★ 本缺陷最关键的端到端判据：非邮箱账号名**能注册、且能用它登录**。

    为什么必须验登录侧：修复方式是给 sign-up 的 `email` 字段声明一个校验器，
    而身份服务的 sign-in 字段表由 sign-up 派生、对 `email` 取同一个 `validate`
    （实测 `utils.py:160-175`）。因此「只改了注册、登录仍被默认邮箱正则拦下」
    是一个真实可能出现的错误修法（会表现成「能注册但登录不了」）。

    判别性：把 `sign_up_form_fields()` 里新增的 email 字段删掉 ⇒ 注册这一步就被
    默认邮箱校验器拒绝（`FIELD_ERROR: Email is not valid`），本用例失败。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        account_name = _unique_name("e2e")
        code = await _issue_code()

        signup = await client.post(_signup_path(settings), json=_signup_payload(account_name, code))
        assert _is_ok(signup), (
            f"非邮箱账号名 {account_name!r} 应可注册（RQ-ACC-05），实际 {_status_of(signup)}：{signup.text[:300]}"
        )
        assert await _account_exists(account_name) is True, "注册返回成功但身份服务里没有该账号"

        signin = await _signin(client, account_name)
        assert _is_ok(signin), (
            f"用刚注册的非邮箱账号名 {account_name!r} 登录必须成功——"
            f"若这里失败，说明只改了注册而登录仍被默认邮箱校验器拦下（能注册但登录不了）：{signin.text[:300]}"
        )
        assert len(signin.headers.get_list("set-cookie")) > 0, "登录成功却没有下发会话 cookie"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_ascii_account_name_without_at_sign_can_register_and_sign_in(
    client: httpx.AsyncClient,
) -> None:
    """同样验无 `@` 的纯 ASCII 账号名（`xiaoshi` 形态）。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        import uuid

        account_name = f"xiaoshi{uuid.uuid4().hex[:10]}"
        code = await _issue_code()

        signup = await client.post(_signup_path(settings), json=_signup_payload(account_name, code))
        assert _is_ok(signup), f"无 @ 的账号名应可注册，实际 {_status_of(signup)}：{signup.text[:300]}"

        signin = await _signin(client, account_name)
        assert _is_ok(signin), f"无 @ 的账号名应可登录：{signin.text[:300]}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_email_shaped_account_name_still_works(client: httpx.AsyncClient) -> None:
    """兼容性：邮箱形态的账号名修后仍可注册与登录（不影响已有账号）。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        account_name = _unique_email("compat")
        code = await _issue_code()

        signup = await client.post(_signup_path(settings), json=_signup_payload(account_name, code))
        assert _is_ok(signup), f"邮箱形态的账号名必须仍可注册，实际 {_status_of(signup)}：{signup.text[:300]}"

        signin = await _signin(client, account_name)
        assert _is_ok(signin), f"邮箱形态的账号名必须仍可登录：{signin.text[:300]}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_blank_account_name_is_rejected_on_sign_up(client: httpx.AsyncClient) -> None:
    """空与纯空白账号名必须被拒，且不给出会话（不得建出「空账号名」）。

    带**有效邀请码**：这样拒绝就必定来自账号名这一侧，而不是「缺码」那一条路径。
    拒绝形状是 SDK 的表单错误（`FIELD_ERROR`、`email` 字段、`Field is not optional`），
    与邀请码类拒绝（`GENERAL_ERROR` + 统一消息）不同——两者不会互相混淆。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        for blank in ("", "   ", "\t\n"):
            code = await _issue_code()
            response = await client.post(_signup_path(settings), json=_signup_payload(blank, code))

            assert _is_ok(response) is False, f"空/纯空白账号名 {blank!r} 不得注册成功"
            body = response.json()
            errors = [field.get("error") for field in body.get("formFields", [])]
            assert errors, f"空/空白账号名 {blank!r} 应返回表单错误，实际：{response.text[:300]}"
            assert len(response.headers.get_list("set-cookie")) == 0, f"空/空白账号名 {blank!r} 被拒却下发了会话 cookie"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_invite_code_rejections_stay_identical_after_account_name_change(
    client: httpx.AsyncClient,
) -> None:
    """账号名改动不得破坏「四种邀请码拒绝响应完全一致」这条既约。

    与 `test_rejection_message_does_not_distinguish_reasons` 同判据，但**账号名改用
    非邮箱形态**：新增的账号名字段若不慎把表单层拒绝引入邀请码路径，
    这里会看到多种响应体。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        bodies: set[str] = set()

        # 1) 不存在
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_name("b1"), "ZZZZZZZZ"))
        bodies.add(response.text)

        # 2) 已撤销
        revoked = await _issue_code()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=revoked)
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_name("b2"), revoked))
        bodies.add(response.text)

        # 3) 已占用
        used = await _issue_code()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=used)
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_name("b3"), used))
        bodies.add(response.text)

        # 4) 形状不合法（长度不对）
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_name("b4"), "ABC"))
        bodies.add(response.text)

        # 5) 缺码（账号名为非邮箱形态）——共五种拒绝，仍须同形
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_name("b5"), None))
        bodies.add(response.text)

        assert len(bodies) == 1, (
            f"五种邀请码类拒绝的响应体必须完全一致（否则构成账号枚举渠道），实测 {len(bodies)} 种：{sorted(bodies)}"
        )
    finally:
        await _clear()


# ---------------------------------------------------------------------------
# C-3（未知租户 + 有效码）与 C-4（账号名冲突）与其余拒绝同形
#     —— 2026-10-07 用户裁决的两条，见 results/T40.md
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tenant_with_valid_code_is_a_shaped_rejection_not_a_500(
    client: httpx.AsyncClient,
) -> None:
    """★ C-3：未知租户 + **有效**邀请码不得裸 500，且响应与邀请码拒绝逐字同形。

    这条守的是什么：

    租户由 URL 路径承载（见 `_signup_path_for_tenant`），因此「租户是否存在」这件事
    被调用方完全控制。修复前：SDK 在租户不存在时抛**裸 `Exception`**
    （实测 `auth_utils.py:865-869`），我们的 `except` 只用它做「要不要释放」的判定、
    然后原样 `raise` ⇒ 冒泡成 **HTTP 500**。500 本身就是「该租户不存在」的信号，
    且匿名可达（不需要已存在的账号）。

    实测（真 uvicorn + 真 core，改动前，`tmp/t40/probe-before.json`）：
        POST /api/auth/t40-unknown-tenant/signup + 有效码 → HTTP 500 `Internal Server Error`

    本用例断言的是**两件事**，缺一不可：
      (a) 不再是 500（用户裁决「补 4xx」）；
      (b) 形状与四类邀请码拒绝**逐字相同**——只满足 (a) 是不够的：给一个可区分的
          4xx 等于把裸 500 换成**更明显**的租户存在性预言机。

    判别性：把 `registration.py` 里 `_tenant_exists(...) is False` 那一支删掉
    （恢复原样 `raise`），本用例失败（HTTP 500）。
    把该支改成返回别的形状（如另造一个 4xx），(b) 部分失败。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        # --- 未知租户 + 有效码 ---
        unknown_code = await _issue_code()
        unknown_response = await client.post(
            _signup_path_for_tenant(settings, _UNKNOWN_TENANT),
            json=_signup_payload(_unique_email("c3unknown"), unknown_code),
        )

        assert unknown_response.status_code != 500, (
            f"未知租户 + 有效码不得裸 500（匿名可达的租户存在性信号），"
            f"实际 HTTP {unknown_response.status_code}：{unknown_response.text[:300]}"
        )

        # --- 已知租户（public，即 `_signup_path` 走的缺省路径）+ 无效码 ---
        known_response = await client.post(
            _signup_path(settings), json=_signup_payload(_unique_email("c3known"), "ZZZZZZZZ")
        )

        assert unknown_response.text == known_response.text, (
            "未知租户的响应必须与邀请码拒绝**逐字相同**——否则调用方仍能区分"
            f"「租户不存在」与「码无效」，可探测性只是从 500 换成了另一个形状：\n"
            f"  未知租户：HTTP {unknown_response.status_code} {unknown_response.text[:200]}\n"
            f"  码无效：  HTTP {known_response.status_code} {known_response.text[:200]}"
        )

        # --- 该码必须被释放：本次不可能建出账号（租户不存在），码未被真实使用 ---
        # 不释放的话，「探测未知租户」就成了烧掉邀请码的手段。
        async with session_scope(get_settings()) as session:
            record = await get_invite_code(session, code=normalize_invite_code(unknown_code))
        assert record is not None
        assert record.state == STATE_ISSUED, (
            f"未知租户下账号不可能建出，该码应被释放回 issued，实际 {record.state}——否则探测未知租户会白白烧掉邀请码"
        )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_duplicate_account_name_is_rejected_in_the_same_shape(client: httpx.AsyncClient) -> None:
    """★ C-4：账号名冲突的响应必须与四类邀请码拒绝**逐字同形**。

    为什么这是「改实现」而不是「改文档」：用户 2026-10-07 裁决「改实现，让第五条也同形」。

    偏差在哪一层（实测逐条核过，不是转述）：

    - 我们的四类拒绝走 `_reject(...)` → `GeneralErrorResponse` ⇒
      `200 {"status":"GENERAL_ERROR","message":…}`；
    - `EmailAlreadyExistsError` 原先在 `sign_up_post` 复写里**原样 `return result`**，
      于是继续走 SDK 的渲染：`recipe/emailpassword/api/signup.py:99-108` 把它转成
      `raise_form_field_exception("EMAIL_ALREADY_EXISTS_ERROR", …)` ⇒
      `200 {"status":"FIELD_ERROR","formFields":[…]}`。
    ⇒ **同一次请求的两个分支，线格式不同**，而调用方可逐字区分。

    它为什么可被匿名利用（SDK 的测试邮箱域 + 不消耗码）：
    `is_fake_email`（`auth_utils.py:971-974`）对 `@stfakeemail.supertokens.com` 为真，
    `implementation.py:734-736` 在该域且为首因子时**直接**返回 `EmailAlreadyExistsError()`
    ——不查库、不建号。而第 1 步（占用邀请码）先于它 ⇒ 本分支只在**码有效**时可达
    ⇒ 「拿到 FIELD_ERROR」本身就证明了候选码有效，且全过程不建号、不消耗码。

    实测（真 uvicorn + 真 core，改动前，`tmp/t40/probe-before.json`）：
        POST /api/auth/signup {email: c4-before@stfakeemail.supertokens.com, inviteCode: <有效码>}
        → 200 {"status":"FIELD_ERROR","formFields":[{"id":"email",…}]}
    改动后（`tmp/t40/probe-after.json`）→ 200 `GENERAL_ERROR` + 统一消息。

    ⚠️ 用户可见代价（如实记下）：重名注册**这条正常路径**的文案随之改变——
    前端按 `FIELD_ERROR` + `email` 字段分派到 `account-unusable`
    （「该账号名无法使用，请换一个」），改成 `GENERAL_ERROR` 后落进
    `invite-rejected`（「邀请码无效或已被使用」）——**不准确**。判定与理由见
    `registration.py` 对应注释与 `results/T40.md` 的 C-4 节。

    判别性：把 `registration.py` 里 `return _reject(_REJECTION_MESSAGE)` 改回
    `return result`，本用例失败（会看到 `FIELD_ERROR`）。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        # 用 SDK 的测试邮箱域触发 `EmailAlreadyExistsError`：不建号、不消耗码。
        fake_email = f"c4-{uuid.uuid4().hex[:10]}@stfakeemail.supertokens.com"
        code = await _issue_code()
        conflict = await client.post(_signup_path(settings), json=_signup_payload(fake_email, code))

        # 参照物：四类邀请码拒绝之一（码不存在）。
        baseline = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("c4base"), "ZZZZZZZZ"))

        assert conflict.text == baseline.text, (
            "账号名冲突的响应必须与四类邀请码拒绝**逐字相同**——否则「账号名冲突」"
            "这条分支与邀请码拒绝形状不同，配合 SDK 测试邮箱域可被用来判定候选码是否有效"
            f"（不建号、不消耗码）：\n"
            f"  账号名冲突：HTTP {conflict.status_code} {conflict.text[:200]}\n"
            f"  码无效：    HTTP {baseline.status_code} {baseline.text[:200]}"
        )
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_five_rejection_shapes_are_indistinguishable(client: httpx.AsyncClient) -> None:
    """★ C-3 + C-4 的合并守卫：**五类**拒绝的响应体逐字相同。

    这五种是：① 码不存在；② 码已撤销；③ 码已占用；④ 码形状不合法；
    ⑤ **账号名冲突**（C-4 的第五条）；另加 C-3 的 ⑥ **未知租户**。

    与既有 `test_rejection_message_does_not_distinguish_reasons`（只覆盖四类邀请码）
    和 `test_invite_code_rejections_stay_identical_after_account_name_change`（五类，
    但第五类是「缺码」而非「账号名冲突」）都不同：**本用例是把 C-3/C-4 两条裁决
    钉在一起的那一条**，任何一条被改回去都会在这里变红。

    判别性：把 C-3 或 C-4 任一处改回原实现，则响应体集合出现 >1 种，本用例失败。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        bodies: dict[str, str] = {}

        # ① 码不存在
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("f1"), "ZZZZZZZZ"))
        bodies["① 码不存在"] = response.text

        # ② 码已撤销
        revoked = await _issue_code()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=revoked)
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("f2"), revoked))
        bodies["② 码已撤销"] = response.text

        # ③ 码已占用
        used = await _issue_code()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=used)
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("f3"), used))
        bodies["③ 码已占用"] = response.text

        # ④ 码形状不合法
        response = await client.post(_signup_path(settings), json=_signup_payload(_unique_email("f4"), "ABC"))
        bodies["④ 码形状不合法"] = response.text

        # ⑤ 账号名冲突（C-4）——SDK 测试邮箱域，不建号、不消耗码
        response = await client.post(
            _signup_path(settings),
            json=_signup_payload(f"f5-{uuid.uuid4().hex[:10]}@stfakeemail.supertokens.com", await _issue_code()),
        )
        bodies["⑤ 账号名冲突"] = response.text

        # ⑥ 未知租户 + 有效码（C-3）
        response = await client.post(
            _signup_path_for_tenant(settings, _UNKNOWN_TENANT),
            json=_signup_payload(_unique_email("f6"), await _issue_code()),
        )
        bodies["⑥ 未知租户"] = response.text

        distinct = set(bodies.values())
        assert len(distinct) == 1, (
            "六类拒绝的响应体必须完全一致（任何差异都是可区分渠道：租户存在性 / 账号枚举 / "
            f"邀请码有效性预言机），实测 {len(distinct)} 种：" + json.dumps(bodies, ensure_ascii=False, indent=2)
        )
    finally:
        await _clear()
