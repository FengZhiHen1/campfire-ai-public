"""SDK 装配的契约：会话校验必须逐请求查证数据库，且没有旁路。

对应 `docs/技术设计/decisions/会话校验逐请求查证数据库.md` 的不变量
（「每个受限操作都必须开启数据库查证，不得只在部分端点开启」）。

为什么需要这些用例（它们防的是一类静默失效）：

实测（2026-09-30，真实 core + 真实库）：`check_database` 不是
`session.init` 的初始化选项，而是每次调用都要传的参数——
`session.init` 的签名里没有它，`recipe/session/framework/fastapi/__init__.py`
的 `verify_session` 默认值是 `check_database: bool = False`。

后果：撤销会话后，默认参数下同一个 access token 仍然通过校验；
只有显式传 `True` 才被拒。因此「忘传」不会报错，只会静默失去撤销能力
（`AC-17`、`RQ-ACC-06` 落空）——这是最危险的一类缺陷。

断言用 AST 解析代码，不是搜源码字符串：

这是本文件第一版的实测教训：最初用 `"check_database=True" in source` 之类的
子串匹配，结果第一条断言因为 docstring 里的一句说明文字（它写了
`check_database=False` 来描述 SDK 的默认值）而失败；反过来，
`anti_csrf="VIA_CUSTOM_HEADER"` 那条又因为 docstring 里举了同一个例子而
「通过」——即它根本没看真实的调用。

子串匹配把「注释」与「代码」混为一谈，两个方向都会出错：假失败与假通过。
改用 AST 后，断言只作用于真正的调用与关键字实参。

覆盖边界（诚实声明）：

这些是静态/装配级检查，不是端到端验证。 它们保证：
① SDK 装配真的是我们写的那样（`check_database` 被固定为 True）；
② 生产代码里没有绕过 `require_session` 直接用 SDK 的 `verify_session`。

它们不证明「撤销后旧令牌真的不能用了」——那需要真实 core 与真实库的端到端用例
（见 `test_auth_session_lifecycle_integration.py`，需 `docker compose up -d supertokens`）。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from campfire.core.auth import supertokens as st
from campfire.core.config import Settings

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "campfire"

#: 允许直接使用 SDK `verify_session` 的文件（即本模块自身）。
_VERIFY_SESSION_ALLOWLIST = {_SRC_ROOT / "core" / "auth" / "supertokens.py"}


# ---------------------------------------------------------------------------
# AST 小工具：只取代码里的调用，忽略注释与字符串字面量
# ---------------------------------------------------------------------------


def _call_keywords(source: str, function_name: str, callee_suffix: str) -> list[dict[str, ast.expr]]:
    """在 `function_name` 的函数体里找出调用 `callee_suffix` 的关键字实参。

    返回关键字名 → 实参 AST 节点的列表（同名多次调用会返回多条）。

    Args:
        source: 函数的源码（通常由 `inspect.getsource` 取得）。
        function_name: 目标函数名，用于定位其函数体。
        callee_suffix: 被调用者的名字后缀（如 `"verify_session"`、
            `"session.init"`），按 `ast.unparse` 后的文本做后缀匹配。

    Returns:
        每个匹配调用的 `{关键字名: 实参节点}`。

    Raises:
        AssertionError: 找不到目标函数，或一次都没匹配到调用——这本身就是失败，
            否则断言会在「压根没找到调用」时空转通过（假通过）。
    """
    tree = ast.parse(source)
    target = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function_name),
        None,
    )
    assert target is not None, f"源码里找不到函数 {function_name}——本用例没有真的检查到目标"

    found: list[dict[str, ast.expr]] = []
    for node in ast.walk(target):
        if not isinstance(node, ast.Call):
            continue
        if ast.unparse(node.func).endswith(callee_suffix):
            found.append({keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None})

    assert found, (
        f"{function_name} 里没有找到对 {callee_suffix} 的调用——"
        "若实现改成了别名或间接调用，本用例必须同步更新，不能静默空转"
    )
    return found


def _literal(node: ast.expr) -> object:
    """取常量实参的值；非字面量返回一个可读的占位符（避免用例因不可解析而空转）。"""
    try:
        return ast.literal_eval(node)
    except ValueError:
        return f"<非字面量：{ast.unparse(node)}>"


# ---------------------------------------------------------------------------
# require_session：唯一入口，且开关固定
# ---------------------------------------------------------------------------


def test_require_session_pins_check_database_to_true() -> None:
    """`require_session()` 必须把 `check_database` 固定为 `True`。

    判别性：把 `check_database=True` 改成 `False` 或删掉，本用例失败。
    用 AST 而非子串，因此 docstring 里写什么都不影响判定。
    """
    keywords = _call_keywords(inspect.getsource(st.require_session), "require_session", "verify_session")
    for call in keywords:
        assert "check_database" in call, (
            "require_session 调用 verify_session 时没有传 check_database（SDK 默认 False！）"
        )
        assert _literal(call["check_database"]) is True, (
            f"check_database 必须是 True（实际 {_literal(call['check_database'])!r}）——"
            "撤下它就等于撤下「撤销即时生效」（AC-17 / RQ-ACC-06），且不会有任何报错"
        )


def test_require_session_requires_a_session() -> None:
    """`session_required=True`：全应用必须登录（`RQ-ACC-01`）。

    判别性：改成 `False` 会让未登录请求静默通过（拿到 `None` 而不是被拒），
    这正是「不存在匿名可达路径」最容易被破坏的方式。
    """
    keywords = _call_keywords(inspect.getsource(st.require_session), "require_session", "verify_session")
    for call in keywords:
        assert _literal(call.get("session_required")) is True, (
            "session_required 必须是 True——全应用必须登录，未登录请求要被拒而不是放行"
        )


def test_verify_session_is_not_used_directly_outside_this_module() -> None:
    """生产代码里不得绕过 `require_session` 直接用 SDK 的 `verify_session`。

    这是把决策记录那条不变量变成机械检查：只要有一处直接调用 SDK，那一处的
    `check_database` 就可能不再固定，而不会有任何报错。

    只识别 `ImportFrom`（顶层导入），不识别函数内 import——这是一处已知的覆盖缺口，
    如实写明而不是假装完备：函数内 `from ... import verify_session` 不会被本用例拦下。
    """
    violations: list[str] = []

    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path in _VERIFY_SESSION_ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.endswith("framework.fastapi") and any(
                alias.name == "verify_session" for alias in node.names
            ):
                violations.append(f"{path.relative_to(_SRC_ROOT).as_posix()}:{node.lineno} 直接导入 verify_session")

    assert not violations, (
        "生产代码绕过 require_session 直接使用 SDK 的 verify_session——"
        "该处不再保证 check_database=True，撤销可能静默失效：\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# init_supertokens：配方集合与 anti-CSRF 方式
# ---------------------------------------------------------------------------


def _init_recipe_names() -> list[str]:
    """取 `init(...)` 的 `recipe_list` 里每个 `<name>.init(...)` 的配方名。

    Raises:
        AssertionError: 未找到 `recipe_list`（用例宁可失败，也不要空转通过）。
    """
    keywords = _call_keywords(inspect.getsource(st.init_supertokens), "init_supertokens", "init")
    # 取带 recipe_list 的那次调用（函数体内的 `init(...)`）。
    recipe_lists = [call["recipe_list"] for call in keywords if "recipe_list" in call]
    assert recipe_lists, "init_supertokens 里的 init(...) 没有传 recipe_list——本用例没有检查到目标"

    node = recipe_lists[-1]
    assert isinstance(node, ast.List), f"recipe_list 应是字面量列表（实际 {type(node).__name__}）"
    names: list[str] = []
    for element in node.elts:
        if isinstance(element, ast.Call):
            names.append(ast.unparse(element.func).split(".")[0])
    return names


def test_init_registers_exactly_the_two_intended_recipes() -> None:
    """装配恰好启用 `session` 与 `emailpassword` 两个配方。

    用「精确等于」而不是「包含」，因为多启用一个配方是本用例要防的事——
    判别性最强，且不会因为将来新增配方而静默放行。

    这是防止 Account Linking 被悄悄启用的机器化防线：账号链接会使主用户 ID 变更
    （官方《User Object》原文：*The primary user ID. It can change if the user links to
    another user*），而 `account_id` 是记忆分区键与 FalkorDB 图名
    （认证与账号第 3 节）——启用它等于让全部记忆与删除账本失联。
    """
    names = _init_recipe_names()

    assert sorted(names) == ["emailpassword", "session"], (
        f"装配的配方集合变成了 {sorted(names)}。启用新配方前必须确认它不会改写 account_id"
        "（accountlinking 会！）并同步认证与账号的设计文档"
    )


def test_anti_csrf_is_custom_header() -> None:
    """anti-CSRF 方式必须是 `VIA_CUSTOM_HEADER`（认证与账号第 5 节定的契约）。

    判别性：改成 `NONE` 会关闭 CSRF 防护；改成 `VIA_TOKEN` 则要求前端
    用另一种传参方式，与前端 SDK 的既定接法不符。
    """
    keywords = _call_keywords(inspect.getsource(st.init_supertokens), "init_supertokens", "session.init")
    assert keywords, "没有找到 session.init 调用"
    for call in keywords:
        assert _literal(call.get("anti_csrf")) == "VIA_CUSTOM_HEADER", (
            f"anti_csrf 应为 VIA_CUSTOM_HEADER（实际 {_literal(call.get('anti_csrf'))!r}）——改成 NONE 会关闭 CSRF 防护"
        )


# ---------------------------------------------------------------------------
# 配置：装配期显式失败，不留到请求期
# ---------------------------------------------------------------------------


def test_init_rejects_missing_api_key() -> None:
    """未配置 `SUPERTOKENS_API_KEY` 时装配期显式报错，不留到请求期。

    实测依据：core 以 `API_KEYS` 启动时，不带该 key 的请求被拒
    （`GET /apiversion` → `401 Invalid API key`）。因此「没配也能跑」不成立；
    把失败推迟到请求期只会让排查者先去查网络。
    """
    import pytest

    settings = Settings(supertokens_api_key=None)
    with pytest.raises(st.SuperTokensConfigurationError, match="SUPERTOKENS_API_KEY"):
        st.init_supertokens(settings)


def test_sign_up_parameters_must_be_provided_together() -> None:
    """`api_overrides` 与 `sign_up_form_fields` 必须成对，单独给即拒绝。

    为什么要有这条（评审实测的不对称危险）：

    - 只传 `api_overrides` → 未声明的表单字段让请求在复写之前被拒 → 永远无法注册（fail-closed）
    - 只传 `sign_up_form_fields` → 邀请码校验被彻底绕过：实测无码、空码、乱码码三种都注册成功（`fail-open`）

    后者会静默把「须凭邀请码注册」（`RQ-ACC-04`）变成「任何人可注册」。
    因此让危险组合无法被表达，比在文档里提醒可靠。

    判别性：去掉 `init_supertokens` 里的成对校验，本用例失败（不抛异常）。
    """
    import pytest
    from supertokens_python.recipe.emailpassword.interfaces import APIInterface

    settings = Settings(supertokens_api_key="x")

    def _noop_overrides(original: APIInterface) -> APIInterface:
        return original

    def _noop_fields() -> list[object]:
        return []

    # 只给 api_overrides
    with pytest.raises(st.SuperTokensConfigurationError, match="必须同时给出"):
        st.init_supertokens(settings, api_overrides=_noop_overrides)

    # 只给 sign_up_form_fields —— 这是安全缺口那一侧
    with pytest.raises(st.SuperTokensConfigurationError, match="必须同时给出"):
        st.init_supertokens(settings, sign_up_form_fields=_noop_fields)


def test_configuration_check_reports_missing_key() -> None:
    """配置自检不发起网络请求，且如实报告缺失项（not_configured 而不是伪装可用）。"""
    from campfire.core.health import Status

    missing = st.check_supertokens_configuration(Settings(supertokens_api_key=None))
    assert missing.status is Status.NOT_CONFIGURED
    assert "SUPERTOKENS_API_KEY" in missing.detail

    # 配齐时报告 OK（注意：这不代表 core 真的可达——那是 check_auth_core 的职责）。
    ok = st.check_supertokens_configuration(Settings(supertokens_api_key="x"))
    assert ok.status is Status.OK
