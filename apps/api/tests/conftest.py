"""测试会话级夹具。

为什么要有这个夹具（这不是「顺手加的」）：

实测：宿主机 `no_proxy` 含带方括号的 IPv6 字面量（本机为
`127.0.0.1,localhost,::1,[::1]`）时，URL 解析在构造客户端时就抛
`InvalidURL: Invalid port: ':1]'`——它把 `[::1]` 当成 `host:port` 去解析。
本机实测三个都失败：`httpx.AsyncClient()`、`httpx2.AsyncClient()`、
`openai.AsyncOpenAI(...)`（注意 `openai` 用的是 `httpx2`，与 httpx 0.28.1 是两个独立包、
`InvalidURL` 互不为子类）。这与被测代码无关，却会让任何构造客户端的测试整片失败
（实测 17 个用例同时报同一个错），并让「失败原因」看起来像被测代码的问题。

⚠️ 归因差异留档：另一位审查者在自己的环境里测得「裸 `httpx.AsyncClient` 构造成功、
只有 `AsyncOpenAI` 失败」。本机复测不成立（两者都失败），差异可能来自环境变量大小写或
版本；夹具的必要性在两种说法下都成立，故保留，措辞以本机实测为准。

因此这里把 `no_proxy` 归一到合法值，让测试结果不依赖宿主机的代理配置。
生产代码保留 `trust_env`（企业网络可能需代理），并把这个环境问题转成可操作的
配置错误——见 `campfire.agent.model.gateway` 的模块 docstring。

同类的第二处宿主机适配：本地服务地址归一（见 :func:`pytest_configure`）：

代理之外还有一个宿主机差异会让整套集成测试慢一个量级：`localhost` 的解析结果里
`::1` 排在前面，而 compose 只把 PostgreSQL 与 SuperTokens 绑在 IPv4，于是每次建连
先撞一次注定失败的 `::1`——本机实测这一次失败要花约 2.07 秒。修在测试侧的
理由、实测数字与「为什么不改生产默认值」都记在 :func:`pytest_configure` 与
:data:`_LOCAL_SERVICE_ENV_KEYS` 上。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import suppress
from typing import TYPE_CHECKING

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

if TYPE_CHECKING:
    from campfire.core.config import Settings

#: 真实模型用例的显式开关：环境变量名与 marker 名。
#:
#: 为什么必须有显式开关（而不是「有凭据就跑」）：本机 `.env` 里是否有有效
#: `TOKENHUB_API_KEY` 是**环境**属性，不是**代码**属性。按凭据决定跑不跑的写法会让
#: 同一份提交在两台机器上跑出两种范围：谁的 `.env` 恰好有真 key，`uv run pytest` 就
#: 突然开始真调供应商——花额度、受外部限流影响，还把「机制对不对」的判据混进
#: 「端点通不通」。默认跳过、显式开启，才让「这一轮跑的是什么」由命令行决定。
LIVE_MODEL_ENV = "CAMPFIRE_LIVE_MODEL"
LIVE_MODEL_MARKER = "live_model"

#: 仅用于「装配期需要凭据、但用例不调用任何模型」的**非秘密占位**。
#:
#: 为什么需要它：`build_memory_graph` / `ModelGateway` 的构造期要求凭据存在
#: （缺则显式抛配置错误），而一部分集成测试只用它们持有的**结构**，一次模型请求
#: 都不发（只跑驱动查询、只读端点，或把模型客户端整体替换成替身）。这类用例的真实
#: 依赖是 PostgreSQL/FalkorDB；按凭据把它们整批 skip，等于在没有 key 的环境里静默
#: 削掉确定性覆盖。用占位装配既保住覆盖，也不会产生任何外部请求。
PLACEHOLDER_MODEL_KEY = "test-placeholder-not-a-secret"

#: 「看起来像占位符」的凭据形状：`.env.example` 里的 `sk-xxxx…` 一类。
#:
#: 显式开启真实模型用例时用它提前失败：占位符不是「没配置」，它会把请求真发出去再
#: 拿 401，表现为一堆像代码缺陷的红——那是**环境未就绪**被伪装成代码问题。
_PLACEHOLDER_KEY_PATTERN = re.compile(r"^(?:sk-)?x{4,}", re.IGNORECASE)

#: 模型端点相关的环境变量：**值为空白时在测试进程内视为「没配」**。
#:
#: 为什么（2026-10-29 实测，全量 pytest 基线）：`TOKENHUB_API_KEY=""` 这类空值在
#: `pydantic-settings` 里会变成 `SecretStr("")`——它不是 `None`，于是
#: `Settings.resolved_*_api_key` 的「显式配置优先」把它当成了有效凭据，
#: `AsyncOpenAI(api_key="")` 随即抛 `OpenAIError: Missing credentials`。后果是
#: 一个**环境未就绪**被报成 500/失败：`test_memory_*`、`test_health` 的嵌入探针、
#: `test_consult_endpoints_integration` 的应急用例同时红，看起来像代码坏了。
#:
#: 空串在语义上就是「没写这一行」（`resolved_*_base_url` 已经用 `.strip() or` 这么
#: 处理了，凭据一侧尚无同样的归一——那条产品侧缺口已另行上报，不在这里改产品代码）。
#: 测试进程先归一，才能让「有凭据 / 没凭据」这两条分支由**用例自己写的配置**决定，
#: 而不是由某台机器 shell 里恰好导出的空变量决定。
_BLANK_MEANS_UNSET_ENV_KEYS: tuple[str, ...] = (
    "TOKENHUB_BASE_URL",
    "TOKENHUB_API_KEY",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "MEMORY_LLM_BASE_URL",
    "MEMORY_LLM_API_KEY",
)

#: 「本地数据服务」设置项：环境变量名 → Settings 字段名。
#:
#: 值里出现主机位 `localhost` 时，在测试进程内改写为 `127.0.0.1`。
#:
#: 为什么（2026-10-01 实测）：宿主机 `getaddrinfo("localhost")` 先返回 `::1`，
#: 而 compose 只把 PostgreSQL 与 SuperTokens 绑在 IPv4（`127.0.0.1:5432` /
#: `127.0.0.1:3567`）。于是每次建连都先撞一次注定失败的 `::1`，而这次失败连接
#: 在本机要花约 2.07 秒（对照：连一个没人监听的 `127.0.0.1:54321` 同样是 2049 ms，
#: 即这 2 秒是宿主机失败连接的固定代价，与网络质量无关）。实测单个连接：
#: `asyncpg` 走 `localhost` 2068.6 ms、走 `127.0.0.1` 21.6 ms；
#: `check_auth_core` 走 `localhost` 276.2 ms、走 `127.0.0.1` 12.5 ms。
#:
#: 为什么放在测试侧而不是改 `core/config` 的默认值：那是生产默认值，改成
#: `127.0.0.1` 会把「只监听 IPv6 的部署形态」挡在门外，且这属于宿主机网络缺陷、
#: 不是产品缺陷（Linux 上 `::1` 拒绝是瞬时的，很可能只有 Windows 会踩）。
#: 测试只需绕开宿主机这一项配置即可，不动产品行为。
_LOCAL_SERVICE_ENV_KEYS: dict[str, str] = {
    "DATABASE_URL": "database_url",
    "SUPERTOKENS_CONNECTION_URI": "supertokens_connection_uri",
    "FALKORDB_HOST": "falkordb_host",
    "REDIS_URL": "redis_url",
}


def _rewrite_loopback_host(value: str) -> str:
    """把值里的主机位 `localhost` 改写成 `127.0.0.1`；其余位置不动。

    只认两个主机位置：`://localhost`（URL 的主机紧随 scheme）与 `@localhost`
    （带凭据的 URL 里主机紧随 `@`）。这样 `user:localhost@db-host` 这种
    密码恰好叫 localhost 的串不会被误改——那里的 `localhost` 前面是冒号。
    大小写不敏感（主机名按 DNS 规则不区分大小写）。

    Args:
        value: 原始设置值（URL 或裸主机名）。

    Returns:
        改写后的值；不含主机位 `localhost` 时原样返回。
    """
    if value.strip().lower() == "localhost":
        # 裸主机名字段（如 FALKORDB_HOST）：整个值就是主机位。
        return "127.0.0.1"
    return re.sub(r"(://|@)localhost(?=[:\"/]|$)", r"\g<1>127.0.0.1", value, flags=re.IGNORECASE)


def pytest_addoption(parser: pytest.Parser) -> None:
    """注册真实模型用例的显式开关（与 marker `live_model` 配套）。

    等价环境变量：`CAMPFIRE_LIVE_MODEL=1`（CI 与不方便加参数的地方用）。
    """
    parser.addoption(
        "--live-model",
        action="store_true",
        default=False,
        help=(
            "运行真正调用外部模型供应商的用例（marker `live_model`）；默认跳过。"
            f"也可用环境变量 {LIVE_MODEL_ENV}=1 开启。缺凭据时直接失败，不静默跳过。"
        ),
    )


def live_model_enabled(config: pytest.Config) -> bool:
    """本轮是否显式开启了真实模型用例。

    Args:
        config: pytest 配置对象（读 `--live-model`）。

    Returns:
        `--live-model` 或 `CAMPFIRE_LIVE_MODEL=1` 任一成立时为真。
    """
    if config.getoption("--live-model"):
        return True
    return os.environ.get(LIVE_MODEL_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _live_model_environment_problem(settings: Settings | None = None) -> str | None:
    """检查显式开启真实模型用例所需的环境；返回问题描述，缺什么就说什么。

    `None` 表示环境看起来可用（**不验证凭据是否有效**：那要花一次真实请求，
    属于用例本身的事）。

    Args:
        settings: 待检查的配置；省略时读进程配置。可注入是为了让「缺凭据必须失败」
            这条判据本身能被测到（`test_live_model_gate.py`）——不能注入的闸门
            只能靠人肉观察，而那种闸门正是「永远不会失败」的那一类。

    Returns:
        问题描述；环境齐全时返回 `None`。
    """
    from campfire.core.config import Settings as SettingsType

    resolved = settings if settings is not None else SettingsType()

    key = resolved.tokenhub_api_key
    if key is None or not key.get_secret_value().strip():
        return (
            "未配置 TOKENHUB_API_KEY——显式开启了 --live-model，但本进程没有任何模型凭据；"
            "请在环境或 .env 里提供真实凭据后重跑（本用例必须真连供应商，不能跳过冒充通过）"
        )
    if _PLACEHOLDER_KEY_PATTERN.match(key.get_secret_value().strip()) or "…" in key.get_secret_value():
        return (
            "TOKENHUB_API_KEY 看起来是 .env.example 里的占位符（形如 sk-xxxx…）——"
            "占位符会让请求真的发出去再拿 401，那不是「用例通过/失败」而应归为环境未就绪；"
            "请换成有效凭据，或不加 --live-model 只跑确定性门禁"
        )
    return None


def _mark_expression_excludes_live_model(config: pytest.Config) -> bool:
    """本轮 `-m` 表达式是否**显式排除**了 `live_model`（形如 `not live_model`）。

    为什么需要这条判据（2026-10-29 修）：`scripts/checks.py` 的 `quick`/`full` 与 CI 都会
    带上 `-m "not live_model"`。而门禁此前只看「开关是否被显式打开」，不看「这一轮到底选
    了什么」——于是一个 shell 里恰好导出过 `CAMPFIRE_LIVE_MODEL=1` 的开发机，跑确定性门禁
    会在**收集期**因缺凭据直接失败。那不是代码缺陷，是门禁把「要求跑真模型」误读成
    「这一轮要跑真模型」，而命令行已经明确说了不跑。

    只认这一种写法（本仓 `checks.py`、`ci.yml` 用的就是它）。其它表达式（如
    `-m "not (live_model or slow)"`）保持「照常校验环境」——宁可多拦一次，也不猜语义。

    Args:
        config: pytest 配置对象（读 `-m`/`--markexpr`）。

    Returns:
        表达式里显式排除了 `live_model` 时为真。
    """
    option = getattr(config, "option", None)
    markexpr = str(getattr(option, "markexpr", "") or "")
    return bool(re.search(r"\bnot\s+live_model\b", markexpr))


def enforce_live_model_environment(config: pytest.Config) -> None:
    """显式开启真模型用例时，在收集之前确认环境真的具备；缺什么就直说什么。

    三条不成立的组合都**不**失败（它们是刻意的选择，不是漏配）：

    1. 未开启 `--live-model` / `CAMPFIRE_LIVE_MODEL=1`：默认门禁本来就逐条 skip；
    2. 开启了但 `-m` 显式排除 `live_model`：本轮不会跑任何真模型用例（见
       :func:`_mark_expression_excludes_live_model`）；
    3. 环境齐全：由用例自己去证明端点可用。

    其余情况（开启、没排除、缺凭据或占位符）抛 :class:`pytest.UsageError`——退出码非 0、
    消息点名缺什么。这是「显式选择真模型却什么都没跑」与「静默跳过冒充通过」之间唯一的分界。

    Args:
        config: pytest 配置对象。

    Raises:
        pytest.UsageError: 环境不具备且本轮确实会跑真模型用例。
    """
    if not live_model_enabled(config):
        return
    if _mark_expression_excludes_live_model(config):
        return
    problem = _live_model_environment_problem()
    if problem is not None:
        raise pytest.UsageError(problem)


def settings_with_placeholder_model_key(settings: Settings) -> Settings:
    """缺模型凭据时补一个**非秘密占位**，供「只用装配结构、不调模型」的用例使用。

    用法边界（别把它当万金油）：只允许用在**一次模型请求都不会发出**的用例上
    ——只跑图库驱动查询、只读端点、或模型客户端已被替身整体替换。真调模型的用例
    必须打 `live_model` marker 并由 `--live-model` 显式开启。

    Args:
        settings: 已解析的配置。

    Returns:
        原对象（已有凭据时原样返回）或补了占位凭据的副本。
    """
    if settings.tokenhub_api_key is not None:
        return settings
    from campfire.core.config import Settings

    payload = settings.model_dump()
    payload["tokenhub_api_key"] = PLACEHOLDER_MODEL_KEY
    return Settings(**payload)  # type: ignore[arg-type]  # model_dump 往返，键值形状与字段一致


@pytest.fixture
def placeholder_model_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """本机没有模型凭据时，给**读路径**用例注入非秘密占位（不产生任何模型请求）。

    用于穿过完整应用装配、由生产代码自己调 `get_settings()` 取凭据的用例：
    那里没有「传一个 settings」的缝，只能经环境变量注入。

    收尾把 `get_settings` 的缓存清一次，让后续用例重新按真实环境解析。
    """
    from campfire.core.config import Settings, get_settings

    if Settings().tokenhub_api_key is None:
        monkeypatch.setenv("TOKENHUB_API_KEY", PLACEHOLDER_MODEL_KEY)
        get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """未显式开启时，真实模型用例逐条跳过并写明原因（不静默）。

    跳过而不是失败：默认门禁不该因为「本机没有供应商凭据」变红——那不是代码问题。
    但**显式开启**时反过来：缺环境即失败（见 :func:`_live_model_environment_problem`），
    不允许「开启了却什么都没跑」这种假绿。
    """
    if live_model_enabled(config):
        return
    reason = f"真实模型用例默认不运行（marker `{LIVE_MODEL_MARKER}`）：需要显式 `--live-model` 或 {LIVE_MODEL_ENV}=1"
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if LIVE_MODEL_MARKER in item.keywords:
            item.add_marker(skip)


def pytest_configure(config: pytest.Config) -> None:
    """在任何测试模块导入之前把本地服务地址归一到 IPv4 回环。

    为什么读 `Settings` 而不是直接读 `os.environ`：

    实测踩坑（2026-10-01，本轮自己的第一版就这么错了）：这些值通常写在 `.env`
    里而不在进程环境变量里，于是按 `os.environ` 遍历改写的写法一个都没改到
    ——表面上「归一化已生效」，实际整轮耗时与改动前一致（467.8s → 469.5s，无收益），
    差一点把「没生效」当成「无效的优化」。因此这里先取解析后的配置值
    （`Settings` 会合并 `.env` 与环境变量），再写回 `os.environ`：
    `pydantic-settings` 的优先级里环境变量高于 `.env`，写回环境变量即可覆盖。

    时点：

    `pytest_configure` 早于测试模块导入（已验证）。`Settings` 经 `lru_cache`
    缓存，故写回后清一次缓存。`apps/api/src` 下无模块级 `get_settings()` 调用，
    因此此处改写对全部测试模块都有效。

    `SUPERTOKENS_API_DOMAIN` / `SUPERTOKENS_WEBSITE_DOMAIN` 刻意不改：
    它们是 cookie 域与 same-site 判定的输入，不承担建连职责，改写会改变 SDK 行为。

    本钩子还承担第二件事：显式开启真实模型用例（`--live-model`）时，先检查环境是否
    真的具备（见 :func:`_live_model_environment_problem`）。缺凭据就在收集之前失败——
    退出码非 0、消息直说缺什么。这是「显式选择真模型却什么都没跑」与「静默跳过冒充
    通过」之间唯一的分界：没有这道检查，缺 key 的机器上 `--live-model` 会安静地跑完
    一轮零用例。`-m "not live_model"` 显式排除时**不**校验——那一轮本来就不跑真模型
    用例（`checks.py quick/full` 与 CI 都用这个表达式），见
    :func:`enforce_live_model_environment`。

    Args:
        config: pytest 配置对象（读 `--live-model`）。
    """
    from campfire.core.config import Settings, get_settings

    resolved = Settings()
    for env_key, attribute in _LOCAL_SERVICE_ENV_KEYS.items():
        current = getattr(resolved, attribute, None)
        if not isinstance(current, str) or not current:
            continue  # 未配置（如 CI 无 DATABASE_URL）：保持原样，由各文件的跳过守卫处理
        rewritten = _rewrite_loopback_host(current)
        if rewritten != current:
            os.environ[env_key] = rewritten

    # 空白即未配置：见 `_BLANK_MEANS_UNSET_ENV_KEYS` 的说明。
    for env_key in _BLANK_MEANS_UNSET_ENV_KEYS:
        value = os.environ.get(env_key)
        if value is not None and not value.strip():
            del os.environ[env_key]

    # 清缓存：让后续 get_settings() 用写回后的环境变量重新解析。
    get_settings.cache_clear()

    enforce_live_model_environment(config)


#: 「连不上 FalkorDB 容器」这一类异常。
#:
#: 实测踩坑（2026-09-29）：`redis.exceptions.ConnectionError` 不是内建
#: `ConnectionError`/`OSError` 的子类——它继承 `RedisError` → `Exception`。
#: 只按内建类型捕获会匹配不到，容器不可用时用例会变成 ERROR 而不是安静跳过。
FALKOR_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    RedisConnectionError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    OSError,
)

#: 测试进程内一律清掉的代理变量（`no_proxy` 例外：它由下面的夹具归一成合法值）。
#:
#: 为什么连「看起来无害」的 `http_proxy` 也要清（2026-10-29 实测）：宿主机若把
#: `all_proxy`/`ALL_PROXY` 指向 SOCKS，`httpx.AsyncClient()` 在**构造期**就要为
#: `all://` 建代理挂载，而 httpx 的 SOCKS 支持需要可选的 `socksio` 包；本仓库不装它
#: （也不该为测试引入新依赖），于是构造直接抛
#: `ImportError: Using SOCKS proxy, but the 'socksio' package is not installed`。
#: 实测后果：`test_probes.py` 的两条「配置非法」用例从「不是合法 URL」变成
#: 「探针自身异常（ImportError）」——**宿主机环境被报成被测代码的缺陷**。
#:
#: 这违反了本文件存在的第一条理由（测试结果不依赖宿主机代理配置）。产品侧保留
#: `trust_env`（企业网络可能需要代理），测试侧只需要一个**确定**的网络视图：
#: 全部直连。需要验证代理行为的用例自己 `monkeypatch.setenv`。
PROXY_ENV_KEYS: tuple[str, ...] = (
    "all_proxy",
    "ALL_PROXY",
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
)


@pytest.fixture(autouse=True)
def _normalise_proxy_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把代理相关的环境变量归一到合法值，隔离宿主机配置对测试的影响。

    两件事：清掉所有代理变量（见 :data:`PROXY_ENV_KEYS` 的说明——SOCKS 代理会让
    httpx 构造期抛 ImportError），再把 `no_proxy` 钉成合法值（宿主机常写成含方括号的
    IPv6 字面量，那会让 URL 解析把 `[::1]` 当成 `host:port`）。
    """
    for key in PROXY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    yield


#: 测试进程内被拦下的投递记录：`(pending_id, kind)`，按发生顺序。
#:
#: 由 :func:`_isolate_queue_dispatch` 装的记录器写入。它让用例（以及看日志的人）
#: 能断言「投递这一步真的发生过」，而不必真的把任务送进 Redis。
_DROPPED_DELIVERIES: list[tuple[str, str]] = []


async def _drop_delivery(pending_id: str, kind: str) -> None:
    """只记录、不投递的投递钩子（契约与 `core/jobs` 的钩子同形）。

    见 :func:`_isolate_queue_dispatch`：它的存在是为了让测试进程**永远不把任务投进
    真实队列**，而不是让队列消费「更少见」。
    """
    _DROPPED_DELIVERIES.append((pending_id, kind))


@pytest.fixture(autouse=True)
def _isolate_queue_dispatch() -> Iterator[None]:
    """把投递钩子钉在「只记录、不投递」的实现上，隔离测试进程与真实队列。

    为什么必须有这一层（QA-04；2026-10-06 本机实测）

    **2026-10-28 起这条竞速的根因已修**：`worker.py` 的模块级 `set_dispatch_hook(...)` 挪到
    `WORKER_STARTUP` 事件里，import 不再有副作用（回归守卫：
    `test_worker_import_is_side_effect_free.py`）。下面的隔离仍保留——`TestClient(app)` 的
    lifespan 会**主动**装真钩子（`main.py` 的装配点），所以测试进程依然需要每例重设。

    以下是被修掉的那条因果链，保留作沿革：`import campfire.main` 会经 `main.py:75` 拉进
    `campfire.worker`，而当时 `worker.py` 的**模块级** `set_dispatch_hook(...)` —— **import
    即注入真钩子**。于是测试进程里 `propose_profile_item` 真的把任务投进 Redis，另一端有
    Worker（尤其孤儿 Worker）竞速消费并把记录置 `done`，测试自己的模拟消费就领不到。

    实测读数（同一组合 `test_consult_endpoints_integration.py` +
    `test_profile_tools_integration.py`，同进程先 import `campfire.main` 才点亮钩子）：

    - **无 Worker**：5 次全绿（每次 `74 passed`）；
    - **有真 Worker**：**5 次全失败**（`3 failed`/`4 failed` 交替），
      报错逐字为 `assert None is not None`
      （`test_profile_tools_integration.py:223` 与 `:408`）。

    两次读数之间只改了「有没有 Worker 在消费」这一个变量。

    这一层让那条竞速在结构上不可能发生：钩子在每个用例开始前被换成
    :func:`_drop_delivery`，任务永远不进队列，因此
    **「判某集成测试失败之前必须先确认没有孤儿 Worker 在消费」这条忠告不再必要**。

    ⚠ 这不是「让错误消失」：被隔离的只是**投递的目的地**。待处理记录照旧真实落库，
    消费路径照旧在用例里真实执行（`test_profile_tools_integration._consume` 直接调
    用例层的 `write_from_pending`），只是不再经队列绕一圈。
    因此「写入链真的走通了」这条判据**一点没被放松**——它下面的消融读数（把消费
    断掉后原断言立刻变红）就是这一点的人工证明。

    为什么每个用例都重设一次，而不是只在会话开始设一次：测试体里会有人自己调
    `set_dispatch_hook(...)`（`test_pending_write_dispatch.py`、`test_memory_tools.py`
    等），而 `TestClient(app)` 的 lifespan 也会**重新装上真钩子**
    （`main.py:118`）。逐用例重设才能保证「任何一个用例开始时钩子都是受控的」
    ——这正是「测试自己就隔离了竞速」的含义，而不是依赖用例各自记得还原。

    钩子动的是 `core/jobs` 的模块级私有装配位：该模块只提供 setter、没有 getter，
    因此这里直接读写它（`test_pending_write_dispatch.py` 出于同一理由也直接读它）。
    """
    from campfire.core import jobs as jobs_module

    previous = jobs_module._dispatch_hook
    jobs_module.set_dispatch_hook(_drop_delivery)
    try:
        yield
    finally:
        jobs_module.set_dispatch_hook(previous)


def connect_falkordb_or_skip():  # noqa: ANN202 —— 返回 FalkorDriver；避免在 conftest 顶部导入上游
    """连上本地 FalkorDB 并返回驱动；容器不可用时跳过。

    这个辅助函数存在的原因是一次实测踩坑：`FalkorDB(...)` 的构造函数本身就发网络 I/O
    （指向死端口时构造期即抛 `ConnectionError`），所以构造必须在 `try`
    内。此前三个测试文件都把构造写在 `try` 之外，容器不可用时它们全部变成
    ERROR（实测某个文件 22 个用例全 ERROR、耗时约 99 秒），而 docstring 却宣称
    「容器不可用则跳过」——宣称与行为不符。

    异常类型同样踩过坑：`redis.exceptions.ConnectionError` 不是内建
    `ConnectionError` 的子类，故用 :data:`FALKOR_UNAVAILABLE_ERRORS` 同时覆盖两者。

    Returns:
        `(driver, client)`：已连上的驱动与底层客户端（调用方负责关闭客户端）。

    Raises:
        pytest.skip.Exception: 容器不可用（通过 `pytest.skip` 抛出）。
    """
    # 上游无 py.typed：这个 ignore 与 `modules/memory/graph.py` 的同一处一致，
    # 运行时行为由集成测试锁定（本函数本身就是那层守卫）。
    from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed 标记，非本仓类型缺陷
    from graphiti_core.driver.falkordb_driver import FalkorDriver

    client = None
    try:
        client = FalkorDB(host="localhost", port=6380)
        driver = FalkorDriver(falkor_db=client, database="campfire")
        return driver, client
    except FALKOR_UNAVAILABLE_ERRORS as exc:
        if client is not None:
            with suppress(Exception):
                client.aclose()
        pytest.skip(f"FalkorDB 不可用（{type(exc).__name__}）——先 docker compose up -d falkordb")
    except Exception:
        if client is not None:
            with suppress(Exception):
                client.aclose()
        raise


async def drop_falkordb_graph(client_or_driver: object, *graph_names: str) -> None:
    """彻底删除一张或多张图（`GRAPH.DELETE`），供测试夹具的清理使用。

    为什么不用 `MATCH (n) DETACH DELETE n`（2026-10-01 实测，FalkorDB v4.20.7）：
    清空节点后同图重新写入，带字符串范围条件（`>=` / `<=`）的查询会返回过期
    结果——「写入 → 清图 → 重写 → 窗查询」稳定复现（until 过滤失效，窗外记录
    出现在结果里），而 `GRAPH.DELETE` 删除图键后重建不复现。该缺陷只影响
    测试夹具的「清图重写」形状；生产路径无此形状（纯增量写入），不受影响。

    删除不存在的图键会报错，这里统一吞掉（幂等清理）。

    Args:
        client_or_driver: `falkordb.asyncio.FalkorDB` 客户端或持有 `.client` 的
            `FalkorDriver`（夹具与用例手里往往是后者）。
        graph_names: 要删除的图名（通常是测试账号名）。
    """
    client = client_or_driver
    # FalkorDriver 的 `.client` 是属性（持有底层客户端）；FalkorDB 客户端自己没有
    # `.client` 属性。两种入参都收，让夹具与用例各用手里最顺手的那个。
    inner = getattr(client_or_driver, "client", None)
    if inner is not None:
        client = inner
    execute = getattr(client, "execute_command", None)
    if not callable(execute):
        return
    for name in graph_names:
        try:
            await execute("GRAPH.DELETE", name)
        except Exception:  # noqa: BLE001 —— 图不存在或已删除：幂等清理，删空图无业务后果
            continue
