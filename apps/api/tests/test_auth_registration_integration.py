"""端到端：注册经 HTTP 走通邀请码校验，且**无效码绝不建号**。

    docker compose up -d postgres supertokens
    uv run pytest -m integration apps/api/tests/test_auth_registration_integration.py

## 这个文件钉住的是 `AC-15` 的**核心断言**

`AC-15` 要求「无码或无效码拒绝注册；撤销后不可用；**校验在自己的后端**」。
仅断言「HTTP 返回了错误」是不够的——真正要证明的是「**身份服务侧没有新建用户**」，
因为「拒绝」与「建了号再报错」在响应上看起来可以一样，而后者已经消耗了邀请码
并留下了用户记录。因此本文件的每条拒绝用例都**回查身份服务**确认账号不存在。

## 为什么用 ASGI 直连而不是起一个真服务器

`httpx.ASGITransport` 让请求穿过**完整的 FastAPI 应用**（含 SuperTokens 中间件、
cookie 处理、路由分派），但不占端口、不需要网络。这比「起 uvicorn 再打 localhost」
更可靠（没有端口冲突与启动竞态），且仍然覆盖中间件行为——中间件是这一步的实现本身。

## 覆盖边界（诚实声明）

- **CI 不执行本文件**：它需要真实 postgres 与 supertokens，而 CI 的 backend 作业
  两者都没有（缺口已登记于 `docs/TODO.md`）。
- 本文件**不校验** anti-CSRF 自定义头的真实生效——那是 signin/refresh 路径的行为，
  且需要从前端 SDK 的调用形态出发构造；注册路径的 CSRF 语义不在本文件范围内。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import delete
from supertokens_python.recipe.emailpassword.types import FormField

from campfire.core.config import Settings, get_settings
from campfire.core.db import dispose_engine, session_scope
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

#: 本文件签发邀请码时使用的运营者标识。**它同时是清理的过滤条件**——
#: 见 :func:`_clear`（不能全表删除，否则并发跑时会删掉别的测试文件刚签发的码）。
_OPERATOR = "it_registration"


@pytest.fixture(autouse=True)
def _normalise_env_for_sdk(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """清掉宿主机代理变量——SDK 的 httpx 客户端在构造期就会被它弄坏。

    实测：本机 ``no_proxy`` 含 ``[::1]``，httpx 构造客户端即抛
    ``InvalidURL: Invalid port: ':1]'``；SDK 的 querier 自己 new ``AsyncClient``
    （未传 ``trust_env=False``），因此必须清掉代理本身。属**测试环境适配**，
    生产由部署编排给出正确的 ``no_proxy``。
    """
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    yield


@pytest_asyncio.fixture
async def _dispose_shared_engine() -> AsyncIterator[None]:
    """每个用例前后释放共享引擎（跨事件循环复用会 ``Event loop is closed``）。"""
    await dispose_engine()
    yield
    await dispose_engine()


def _settings_or_skip() -> Settings:
    """取配置；缺库或缺 API Key 时跳过——**不假装通过**。"""
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")
    if settings.supertokens_api_key is None:
        pytest.skip("未配置 SUPERTOKENS_API_KEY——集成测试需要 docker compose up -d supertokens")
    return settings


@pytest_asyncio.fixture
async def client(_dispose_shared_engine: None) -> AsyncIterator[object]:
    """返回一个穿过**完整应用**（含 SuperTokens 中间件）的 ASGI 客户端。

    core 不可达时跳过：那时注册失败的原因是环境，不是被测代码。
    """
    import httpx

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


async def _clear() -> None:
    """清掉本文件写入的邀请码行。

    **必须按签发者过滤，不能全表删除**（2026-09-30 实测的真实缺陷）：本文件与
    ``test_accounts_invite_integration.py`` 原先都做无过滤的 ``delete(InviteCode)``，
    于是并发运行时**互相删对方刚签发的码**——实测一次并发跑出现
    ``InviteCodeNotFoundError``（补偿释放找不到码），而单跑必然通过。
    签发者标识把删除范围收窄到本文件。

    **账号不能清**：它们在 SuperTokens core 的库里，而本文件不实现删除用户的用例
    （那是账号注销的功能，属另一次改动）。因此**账号名必须每次唯一**——
    见 :func:`_unique_email`；否则第二次跑同一用例会因「账号已存在」而失败，
    表现为「注册测试不稳定」而不是「环境有残留」。
    """
    async with session_scope(get_settings()) as session:
        await session.execute(delete(InviteCode).where(InviteCode.created_by == _OPERATOR))


def _unique_email(prefix: str = "acct") -> str:
    """生成唯一的账号名。

    **必须唯一**：SuperTokens core 会永久记住账号（本文件不清理它们），
    固定名字会让「第二次运行」变成「账号已存在」——而那是**建号失败**路径，
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
    """构造身份服务 signup 的表单体（**SDK 的线格式**）。

    **实测格式**：身份服务的 signup 端点是 ``{"formFields": [{"id": ..., "value": ...}]}``，
    **不是**扁平的 JSON 对象。第一版按扁平对象构造，实测全部请求返回 200 +
    ``FIELD_ERROR``「Field is not optional」——即请求压根没到达我们的复写。
    测试用错格式会制造「以为在测拒绝路径、实际在测字段缺失」的假象。

    邀请码作为**自定义字段**一并放进 ``formFields``（字段名见
    ``INVITE_CODE_FORM_FIELD``），这正是前端要照做的形状。
    """
    form_fields = [
        {"id": "email", "value": email},
        {"id": "password", "value": _PASSWORD},
    ]
    if invite_code is not None:
        form_fields.append({"id": INVITE_CODE_FORM_FIELD, "value": invite_code})
    return {"formFields": form_fields}


def _status_of(response: object) -> str:
    """取响应体里的 ``status``（身份服务的**业务结果**字段）。

    **它不是 HTTP 状态码**：实测拒绝也是 200，见模块说明。
    """
    body = response.json()  # type: ignore[attr-defined]
    assert isinstance(body, dict), f"身份服务返回了非对象响应体：{body!r}"
    status = body.get("status")
    assert isinstance(status, str), f"响应体里没有 status 字段：{body!r}"
    return status


def _is_ok(response: object) -> bool:
    """注册是否成功（``status == "OK"``）。"""
    return _status_of(response) == "OK"


def _is_rejected(response: object) -> bool:
    """注册是否被**我们**拒绝（``GENERAL_ERROR``）。

    **刻意不接受 ``FIELD_ERROR``**：那是 SDK 的表单校验失败（字段缺失或格式错），
    意味着请求**没有到达我们的复写**。把它当成「拒绝生效」，会让用例在
    「复写压根没被调用」时通过——那正是第一版的实际情形。
    """
    return _status_of(response) == "GENERAL_ERROR"


async def _account_exists(email: str) -> bool:
    """**回查身份服务**：该账号名是否真的存在。

    这是本文件的核心判据——「拒绝」必须意味着「没有创建用户」，
    而不只是「响应看起来像失败」。

    **为什么用 ``GET /recipe/user?email=``**：实测该端点可用（返回
    ``{"status":"OK","user":{...}}``；无此用户时 status 非 OK）。第一版用的
    ``/recipe/emailpassword/email/exists`` 实测 **404**——那是 SDK 内部的常量路径，
    **不是** core 的公开 Management API 路径。写错端点的后果是「探针永远失败」，
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
    """signup 的实际路径（``api_base_path`` + SDK 的 ``/signup``）。"""
    return f"{settings.supertokens_api_base_path.rstrip('/')}/signup"


# ---------------------------------------------------------------------------
# 无效码绝不建号（AC-15 的核心）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_code_creates_the_account(client: object) -> None:
    """正向对照：**有效码**注册成功，且账号真的建出来了。

    没有这条，下面所有「拒绝」用例都可能是「注册根本不通」造成的假通过。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("ok")
        code = await _issue_code()

        response = await client.post(_signup_path(settings), json=_signup_payload(email, code))  # type: ignore[attr-defined]

        assert _is_ok(response), f"有效码注册应成功，实际 {_status_of(response)}: {response.text[:400]}"
        assert await _account_exists(email) is True, "注册返回成功但身份服务里没有该账号"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_missing_code_is_rejected_and_creates_no_user(client: object) -> None:
    """**不带邀请码** → 拒绝，且身份服务里**没有**该账号（``AC-15``）。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("nocode")

        response = await client.post(_signup_path(settings), json=_signup_payload(email, None))  # type: ignore[attr-defined]

        assert _is_rejected(response), f"缺少邀请码时必须被我们的复写拒绝，实际 {_status_of(response)}"
        assert await _account_exists(email) is False, "被拒绝的注册却建出了账号——AC-15 落空"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_unknown_code_is_rejected_and_creates_no_user(client: object) -> None:
    """**不存在的邀请码** → 拒绝，且**不留下任何用户记录**。

    判别性：若实现是「先建号再校验」，本用例的第二条断言失败——而响应看起来
    可能同样是错误码，所以只断言状态码是不足以发现该缺陷的。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("badcode")

        response = await client.post(_signup_path(settings), json=_signup_payload(email, "ZZZZZZZZ"))  # type: ignore[attr-defined]

        assert _is_rejected(response), f"无效邀请码必须拒绝，实际 {_status_of(response)}"
        assert await _account_exists(email) is False, "无效码的注册建出了账号——AC-15 落空"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_revoked_code_is_rejected_and_creates_no_user(client: object) -> None:
    """**已撤销的邀请码** → 拒绝，且不建号（``AC-15``「撤销后不可用」）。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        code = await _issue_code()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=code)

        email = _unique_email("revoked")
        response = await client.post(_signup_path(settings), json=_signup_payload(email, code))  # type: ignore[attr-defined]

        assert _is_rejected(response), f"已撤销的邀请码必须拒绝，实际 {_status_of(response)}"
        assert await _account_exists(email) is False, "已撤销码的注册建出了账号"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_used_code_is_rejected_the_second_time(client: object) -> None:
    """**一码只用一次**：同一张码第二次注册被拒，且第二个账号不存在。"""
    settings = _settings_or_skip()
    await _clear()
    try:
        code = await _issue_code()
        first = _unique_email("first")
        second = _unique_email("second")

        first_response = await client.post(_signup_path(settings), json=_signup_payload(first, code))  # type: ignore[attr-defined]
        assert _is_ok(first_response), f"首次注册应成功：{first_response.text[:300]}"

        second_response = await client.post(_signup_path(settings), json=_signup_payload(second, code))  # type: ignore[attr-defined]
        assert _is_rejected(second_response), f"同一张邀请码不得用第二次，实际 {_status_of(second_response)}"
        assert await _account_exists(second) is False, "第二次注册建出了账号——一码多用"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_duplicate_account_name_releases_the_code(client: object) -> None:
    """**建号失败 → 补偿释放**：账号名重复时该码回到可用状态（第 4 节步骤 3）。

    **判别性**：若实现漏了补偿释放，该码会永久停在「已占用」，使用者拿到一个新码
    也救不回这张——本用例断言**同一张码**在失败后仍可成功注册。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        email = _unique_email("dup")
        first_code = await _issue_code()

        ok = await client.post(_signup_path(settings), json=_signup_payload(email, first_code))  # type: ignore[attr-defined]
        assert _is_ok(ok), f"首次注册应成功：{ok.text[:300]}"

        # 用**新码** + 同一个账号名 → 建号失败（账号已存在），该新码应被释放。
        second_code = await _issue_code()
        conflict = await client.post(_signup_path(settings), json=_signup_payload(email, second_code))  # type: ignore[attr-defined]
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
        reuse = await client.post(_signup_path(settings), json=_signup_payload(another, second_code))  # type: ignore[attr-defined]
        assert _is_ok(reuse), f"被释放的码应可再次使用：{reuse.text[:300]}"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_non_ok_result_with_account_created_does_not_release_the_code() -> None:
    """**账号已建但结果非 OK 时，不得释放邀请码**（2026-09-30 审查发现的重要缺陷）。

    ## 这条用例守的是什么

    第 4 节的补偿释放依赖「建号失败」。但**「原实现返回非 OK」≠「没有建号」**：
    实测已装 SDK 的源码（``recipe/emailpassword/api/implementation.py``）顺序是
    ``:738`` 建号 → ``:755`` ``post_auth_checks`` → ``:766`` 不通过则返回
    ``SignUpPostNotAllowedResponse``（**非 OK**）。即存在
    「**账号已建、结果却不是 OK**」的真实路径。

    修复前代码对此**无条件**释放，于是同一个码可以再建一个账号——
    「一码只用一次」（``AC-15``）被破坏，且第一张码的记录会被第二次绑定覆盖，
    运营**看不出发生过两次注册**。

    ## 为什么这层用「直接调用复写函数」而不是 HTTP 端到端

    实测 ``Supertokens.reset()`` 之后再次 ``init`` 会抛
    ``GeneralError: Session recipe has already been initialised``——SDK 的 reset
    只重置 Supertokens 实例、不重置各 recipe，**同一进程内换一套复写不可行**。
    因此这里直接调用 :func:`make_sign_up_override` 返回的包装函数，传入一个
    **假的 original**：它真的建一个账号（走 SDK），然后返回非 OK。
    这精确复现了目标组合，且不依赖 ``post_auth_checks`` 的内部触发条件。

    顺带的好处：它同时**绕开了 HTTP 层**，因此不需要 core 之外的任何夹具。

    判别性：把 ``registration.py`` 里 ``_account_exists`` 那层判断去掉
    （恢复为无条件释放），本用例失败——码会回到 ``issued``、可被再次占用。
    """
    # 仅用于「未配置库/API Key 即跳过」的前置检查。
    _settings_or_skip()
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
            """复现 SDK 的真实顺序：**建号成功**，但结果是非 OK。"""
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
        # 前置确认：账号**确实**建出来了（否则本用例没有判别力）。
        assert await _account_exists(email) is True, "构造失败：账号没建出来，本用例失去判别力"

        # 核心断言：该码**不得**回到 issued（它已被一次真实注册用掉）。
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
async def test_rejection_message_does_not_distinguish_reasons(client: object) -> None:
    """四种拒绝（缺失/不存在/已撤销/已用）的**响应体一致**——不可枚举。

    判别性：若实现把四种原因写成不同消息，调用方可逐字区分「码存在但过期」与
    「码不存在」——那就是账号枚举渠道（认证与账号第 5 节同一条纪律）。
    """
    settings = _settings_or_skip()
    await _clear()
    try:
        bodies: set[str] = set()

        # 1) 不存在
        response = await client.post(  # type: ignore[attr-defined]
            _signup_path(settings), json=_signup_payload(_unique_email("a1"), "ZZZZZZZZ")
        )
        bodies.add(response.text)

        # 2) 已撤销
        revoked = await _issue_code()
        async with session_scope(get_settings()) as session:
            await revoke_invite_code(session, code=revoked)
        response = await client.post(  # type: ignore[attr-defined]
            _signup_path(settings), json=_signup_payload(_unique_email("a2"), revoked)
        )
        bodies.add(response.text)

        # 3) 已占用
        used = await _issue_code()
        async with session_scope(get_settings()) as session:
            await claim_invite_code(session, code=used)
        response = await client.post(  # type: ignore[attr-defined]
            _signup_path(settings), json=_signup_payload(_unique_email("a3"), used)
        )
        bodies.add(response.text)

        # 4) 形状不合法（长度不对）
        response = await client.post(  # type: ignore[attr-defined]
            _signup_path(settings), json=_signup_payload(_unique_email("a4"), "ABC")
        )
        bodies.add(response.text)

        assert len(bodies) == 1, (
            f"四种拒绝的响应体必须完全一致（否则构成账号枚举渠道），实测 {len(bodies)} 种：{sorted(bodies)}"
        )
    finally:
        await _clear()
