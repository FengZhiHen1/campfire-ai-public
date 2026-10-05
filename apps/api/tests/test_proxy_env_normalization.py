"""`no_proxy` 规范化的进程级行为：产品侧路径（注册/登录）不再被宿主机环境崩掉。

对应缺陷（2026-10-01 登记，2026-10-05 由 T18 修）：宿主机 `no_proxy` 含**带方括号的
IPv6 字面量**（`127.0.0.1,localhost,::1,[::1]`）时，httpx 与 httpx2 都在**客户端构造期**
抛 `InvalidURL: Invalid port: ':1]'`。而 SuperTokens 的 querier 在每次请求里自己建客户端
（`querier.py:110` 的 `AsyncClient(timeout=30.0)`，**未传 `trust_env=False`**）⇒
**注册与登录的第一步就 500**，而 `/readyz` 的 `auth` 探针（`trust_env=False`）**仍报 ok**。

这个文件钉住的是**产品侧**那条路径，不是探针那条。为什么必须分开钉：

- `core/auth/__init__.py` 的探针传 `trust_env=False` ⇒ 它**读不到** `no_proxy`，
  因此「探针绿」在这条缺陷上是**零信息**——本次实测（受污染环境）探针 `status=ok`
  而 `POST /api/auth/signin` 回 500；
- `agent/model/gateway.py` 的构造窗口规范化只覆盖**网关构造的那一瞬间**，
  querier 的客户端在**请求期**才建 ⇒ 同样覆盖不到。

⇒ 判据必须是「产品路径能走通」，而不是「探针报 ok」。本文件按这个判据写。

判别性（**撤掉修复必须变红**，逐条对应）：

- 撤掉 `core/config.apply_no_proxy_normalization` 的函数体 ⇒
  `test_normalisation_makes_both_spellings_legal` 与
  `test_normalisation_fixes_the_real_httpx_trap` 红；
- 撤掉 `core/auth/supertokens.py` 里那次调用 ⇒
  `test_supertokens_assembly_applies_process_normalisation` 红；
- 撤掉 `main.py` / `worker.py` 导入期那次调用 ⇒ 两个子进程用例红。

子进程用例是**时序**的机械证据：在一个全新的 Python 进程里，先 `import campfire.main`
（或 `campfire.worker`），再构造 httpx / httpx2 客户端——构造成功即证明规范化确实发生在
消费者之前，且不依赖任何测试夹具的干预。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import httpx2
import pytest
from pydantic import SecretStr

from campfire.core.config import (
    PROXY_ENV_NAMES,
    Settings,
    apply_no_proxy_normalization,
    normalize_no_proxy,
)

#: 宿主机那种真实取值（本机现状即此形态）：带方括号的 IPv6 字面量与无方括号的并存。
_POLLUTED = "127.0.0.1,localhost,::1,[::1]"

#: 规范化后的期望取值（只去方括号，其余逐字不动）。
_EXPECTED = "127.0.0.1,localhost,::1,::1"

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: 探测两个 httpx 实现是否真的会因污染取值而崩——不成立时用例应显式失败，而不是空转通过。
_BOTH_HTTPX_PACKAGES = (httpx, httpx2)


def _pollute(monkeypatch: pytest.MonkeyPatch, value: str = _POLLUTED) -> None:
    """把两个大小写键都设成污染取值（宿主机真实形态就是这样并存的）。"""
    for name in PROXY_ENV_NAMES:
        monkeypatch.setenv(name, value)


def _assert_trap_is_real() -> None:
    """前置假设的机械核实：污染取值下，两个 httpx 实现的构造**确实**会崩。

    没有这一步，下面的「修好后不崩」有可能是在一个陷阱本就不存在的环境里通过的
    ——那种绿是假的。两个包都要核：`openai` 用的是 httpx2，而 querier 用的是 httpx，
    **两者的 `InvalidURL` 互不为子类**（upstream 是两个独立包）。
    """
    broken: list[str] = []
    for package in _BOTH_HTTPX_PACKAGES:
        try:
            package.AsyncClient()
        except Exception:  # noqa: BLE001 —— 只关心「崩不崩」，类型见下面断言
            continue
        broken.append(package.__name__)
    assert not broken, (
        f"前提不成立：{broken} 在污染取值 {_POLLUTED!r} 下仍能构造客户端"
        "——本环境的 httpx 已修好该解析，本文件的判据需要重新设计，不要放宽断言"
    )


# ---------------------------------------------------------------------------
# 一、规范化本身：两个键的值一致、合法，且幂等
# ---------------------------------------------------------------------------


def test_normalisation_makes_both_spellings_legal(monkeypatch: pytest.MonkeyPatch) -> None:
    """承重用例：规范化后**两个大小写键读到的值一致且合法**（无方括号）。

    为什么判据是「两个键都一致」而不是「小写键对了」：Windows 上 `os.environ` 按
    `key.upper()` 折叠，读哪个拼写都命中同一条——因此单看小写键**分辨不出**「只写了一个
    键」与「两个键都写了」。而消费者读哪个拼写不由我们决定（httpx 经
    `urllib.getproxies_environment` 两遍扫描，全小写优先；别的库可能只读大写）。
    两个键都写才是「与消费者拼写无关」的保证，故这里逐个拼写都断言。
    """
    _pollute(monkeypatch)
    _assert_trap_is_real()

    written = apply_no_proxy_normalization()

    assert written == _EXPECTED
    for name in PROXY_ENV_NAMES:
        value = os.environ.get(name)
        assert value == _EXPECTED, f"{name} 不是规范化后的值：{value!r}"
        # 「合法」的机械判据：没有任何方括号包住的 IPv6 残留。
        assert "[" not in value and "]" not in value
    # 幂等：再调一次不产生任何变化（装配处与 SDK 装配点都会调，这不是可选项）。
    assert apply_no_proxy_normalization() == _EXPECTED
    assert normalize_no_proxy(_EXPECTED) == _EXPECTED


def test_normalisation_fixes_the_real_httpx_trap(monkeypatch: pytest.MonkeyPatch) -> None:
    """承重的行为判据：规范化前构造崩、规范化后**两个 httpx 实现**都能构造。

    这条用例不看 `os.environ` 的字面值，只看「真实的客户端构造能不能过」——
    与缺陷的影响面同构（缺陷的表现就是构造期抛异常）。
    """
    _pollute(monkeypatch)
    _assert_trap_is_real()

    apply_no_proxy_normalization()

    for package in _BOTH_HTTPX_PACKAGES:
        client = package.AsyncClient(timeout=5.0)
        # 用毕即关：不开着的连接池（本用例不建连接，但仍然按契约收尾）。
        assert client is not None


def test_normalisation_does_not_invent_a_value_when_both_keys_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个键都没设置时**什么都不写**：返回 `None`，且不留下空串。

    「未设置」与「设置为空」在 httpx 里不是一回事（空串会让豁免列表解析出一条空项），
    因此这一档必须区分——写一个空串进去会把「本来不管代理」变成另一种行为。
    """
    for name in PROXY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    assert apply_no_proxy_normalization() is None
    for name in PROXY_ENV_NAMES:
        assert name not in os.environ


def test_normalisation_takes_the_polluted_value_from_either_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有大写键存在时（POSIX 上可能如此）也要规范化，且结果同样落进两个拼写。

    这是「与消费者拼写无关」的另一半：不能只在「小写键存在」时才动手。
    """
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", _POLLUTED)

    assert apply_no_proxy_normalization() == _EXPECTED
    for name in PROXY_ENV_NAMES:
        assert os.environ.get(name) == _EXPECTED


# ---------------------------------------------------------------------------
# 二、产品侧路径：SDK 装配处必须自己完成规范化（不可遗忘）
# ---------------------------------------------------------------------------


def _settings_for_assembly() -> Settings:
    """构造一份能通过装配前校验的设置（不连任何服务）。"""
    return Settings(
        supertokens_connection_uri="http://localhost:3567",
        supertokens_api_key=SecretStr("test-key-not-a-secret"),
    )


def test_supertokens_assembly_applies_process_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    """承重用例：`init_supertokens` 必须自己做进程级规范化。

    为什么判据挂在 SDK 装配上而不是某个入口文件上：`init_supertokens` 是本仓**唯一**的
    SDK 装配入口，三个进程都经它（API 的 lifespan、Worker 侧、`cli/operator`）。
    缺陷此前的形态正是「防护散落在不覆盖 querier 的路径上」——把判据挂在这个唯一入口上，
    才能让「谁忘了在启动器里设一次」不再让注册/登录整体 500。

    判别性：撤掉 `core/auth/supertokens.py` 里那次 `apply_no_proxy_normalization()`，
    本用例红。
    """
    _pollute(monkeypatch)

    from campfire.core.auth.supertokens import init_supertokens

    init_supertokens(_settings_for_assembly())

    for name in PROXY_ENV_NAMES:
        assert os.environ.get(name) == _EXPECTED, f"SDK 装配没有规范化 {name}"


def test_agent_model_proxy_env_reuses_the_core_implementation() -> None:
    """单一真源：`agent/model/proxy_env` 必须转出 `core/config` 的**同一批对象**。

    为什么需要这条：实现此前在 `agent/model`，而产品侧受害者 `core/auth` 不得 import
    `agent/*`（层白名单）——于是产品侧无法复用它，只能另写一份，那会制造第二真源。
    转入 `core/config` 后 `agent/*` 仍可复用（白名单里本就有 `campfire.core.config`），
    但「复用」必须是**真的同一个函数对象**，否则两份实现会各自漂移。
    """
    from campfire.agent.model import proxy_env as agent_side
    from campfire.core import config as core_side

    assert agent_side.normalize_no_proxy is core_side.normalize_no_proxy
    assert agent_side.normalized_no_proxy_environment is core_side.normalized_no_proxy_environment
    assert agent_side.PROXY_ENV_NAMES is core_side.PROXY_ENV_NAMES

    # 构造窗口版仍然精确还原（它是非装配路径上的纵深，不是被替换掉的旧实现）。
    original = os.environ.get("no_proxy")
    try:
        os.environ["no_proxy"] = _POLLUTED
        with agent_side.normalized_no_proxy_environment():
            assert os.environ["no_proxy"] == _EXPECTED
        assert os.environ["no_proxy"] == _POLLUTED
    finally:
        if original is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = original


# ---------------------------------------------------------------------------
# 三、时序：入口导入期就完成规范化（子进程里的机械证据）
# ---------------------------------------------------------------------------

#: 子进程脚本：导入入口 → 检查环境已是规范化取值 → 构造两个 httpx 实现的客户端。
#:
#: 为什么放子进程：主测试进程早已 import 过 `campfire.main`（收集期/别的用例），
#: 导入期语句不会再执行一次——那会让「入口确实在导入期规范化」永远测不出来（假绿）。
#: 全新进程才能真的重放「导入即规范化」这一步。
_ENTRY_PROBE = """
import json, os, sys
import httpx, httpx2

target = sys.argv[1]
__import__(target)

report = {
    "no_proxy": os.environ.get("no_proxy"),
    "NO_PROXY": os.environ.get("NO_PROXY"),
    "httpx_ok": False,
    "httpx2_ok": False,
    "errors": [],
}
for package, key in ((httpx, "httpx_ok"), (httpx2, "httpx2_ok")):
    try:
        package.AsyncClient(timeout=5.0)
        report[key] = True
    except Exception as exc:
        report["errors"].append(f"{package.__name__}:{type(exc).__name__}:{exc}")

sys.stdout.write("__REPORT__" + json.dumps(report))
"""


def _run_entry_probe(module: str) -> dict[str, object]:
    """在全新进程里导入入口模块，返回环境与客户端构造结果。"""
    env = dict(os.environ)
    # 污染取值：两个拼写都给。Windows 会把同名（忽略大小写）的键折叠成一条，
    # 但取值仍是污染的——复现所需的就是「子进程读到污染值」。
    for name in PROXY_ENV_NAMES:
        env[name] = _POLLUTED
    completed = subprocess.run(
        [sys.executable, "-c", _ENTRY_PROBE, module],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        f"子进程导入 {module} 失败（退出码 {completed.returncode}）：\n"
        f"stdout={completed.stdout[-2000:]}\nstderr={completed.stderr[-2000:]}"
    )
    marker = completed.stdout.rfind("__REPORT__")
    assert marker != -1, f"子进程没有输出报告：stdout={completed.stdout[-2000:]!r} stderr={completed.stderr[-2000:]!r}"
    return json.loads(completed.stdout[marker + len("__REPORT__") :])


@pytest.mark.parametrize("module", ["campfire.main", "campfire.worker"])
def test_entry_modules_normalise_at_import_time(module: str) -> None:
    """承重用例：入口模块**在导入期**就完成规范化，且此后构造客户端不再崩。

    为什么这条是「时序」的机械证据：子进程只做两件事——导入入口、构造客户端。
    导入返回时规范化已经生效（两个拼写都读到合法值），而构造客户端在**之后**发生且成功
    ⇒ 规范化确实早于消费者。反过来，若把入口那次调用撤掉，子进程读到的仍是污染取值、
    构造也仍会抛 `InvalidURL`（同一条用例变红）。

    为什么入口必须是「导入期」而不是 lifespan：客户端构造可以发生在导入期或 `app`
    构造期，那时 lifespan 还没跑——把规范化放在 lifespan 会留下一个真实的窗口。
    """
    report = _run_entry_probe(module)

    assert report["no_proxy"] == _EXPECTED, f"导入后 no_proxy 仍非法：{report['no_proxy']!r}"
    assert report["NO_PROXY"] == _EXPECTED, f"导入后 NO_PROXY 仍非法：{report['NO_PROXY']!r}"
    assert report["errors"] == [], f"导入入口后客户端构造仍失败：{report['errors']}"
    assert report["httpx_ok"] is True and report["httpx2_ok"] is True


# ---------------------------------------------------------------------------
# 四、静态守门：入口的调用必须排在其它 import 之前（防止被顺手挪到 lifespan）
# ---------------------------------------------------------------------------

#: 允许排在规范化调用之前的 import：标准库与配置模块自身。
#:
#: 标准库放行的理由：它们不构造 httpx 客户端（`urllib.request` 只提供代理**读取**，
#: 而 `getproxies` 本身不构造客户端），且不先导入就无法写这个模块。
#: `campfire.core.config` 是规范化的实现处，必须先导入才能调用。
#: 除此以外**任何** import 落到调用之前都判红——那是「消费者可能先于规范化」的形态。
_ALLOWED_IMPORT_ROOTS_BEFORE_NORMALISATION = frozenset({"campfire.core.config"})


def _imported_module_names(node: ast.stmt) -> list[str]:
    """一条 import 语句的目标模块名（`from X import Y` 取 X，`import X` 取 X）。"""
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.module else []
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return []


def _is_allowed_before_normalisation(name: str) -> bool:
    """该 import 目标是否允许排在规范化调用之前。"""
    if name in _ALLOWED_IMPORT_ROOTS_BEFORE_NORMALISATION:
        return True
    return name.split(".")[0] in sys.stdlib_module_names


@pytest.mark.parametrize("entry", ["main.py", "worker.py"])
def test_entry_calls_normalisation_before_other_imports(entry: str) -> None:
    """入口里的规范化调用必须是**模块级**语句，且排在其它 import 之前。

    为什么用 AST 而不是搜字符串：docstring 与注释里也写着这个函数名（理由说明就在
    旁边），子串匹配会把「说明」当成「调用」——两个方向都会错（假通过、假失败）。
    本项目已有同一教训的留档，见 `test_auth_supertokens.py` 的模块 docstring。

    判别性：把调用挪进 `lifespan`（或挪到 import 块之后），本用例红。
    """
    source = (_REPO_ROOT / "apps" / "api" / "src" / "campfire" / entry).read_text(encoding="utf-8")
    body = ast.parse(source).body

    call_index = None
    for index, node in enumerate(body):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "apply_no_proxy_normalization"
        ):
            call_index = index
            break

    assert call_index is not None, (
        f"{entry} 的模块级没有调用 apply_no_proxy_normalization——入口级时序保证不存在（客户端构造可能发生在规范化之前）"
    )

    offenders = [
        name
        for node in body[:call_index]
        for name in _imported_module_names(node)
        if not _is_allowed_before_normalisation(name)
    ]
    assert not offenders, f"{entry} 在规范化调用之前就导入了：{offenders}——时序保证不成立"


def test_supertokens_assembly_calls_normalisation_before_sdk_init() -> None:
    """SDK 装配点：规范化必须排在 `init(...)` 之前。

    判据同样是 AST：只认真正的调用与调用顺序，注释里的说明不算。
    """
    source = (_REPO_ROOT / "apps" / "api" / "src" / "campfire" / "core" / "auth" / "supertokens.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    function = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "init_supertokens"),
        None,
    )
    assert function is not None, "找不到 init_supertokens——本用例会空跑"

    normalise_line = None
    init_line = None
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "apply_no_proxy_normalization":
            normalise_line = node.lineno if normalise_line is None else min(normalise_line, node.lineno)
        if isinstance(node.func, ast.Name) and node.func.id == "init":
            init_line = node.lineno if init_line is None else min(init_line, node.lineno)

    assert normalise_line is not None, "init_supertokens 里没有调用 apply_no_proxy_normalization"
    assert init_line is not None, "init_supertokens 里没有调用 SDK 的 init——本用例会空跑"
    assert normalise_line < init_line, f"规范化（第 {normalise_line} 行）没有排在 SDK init（第 {init_line} 行）之前"
