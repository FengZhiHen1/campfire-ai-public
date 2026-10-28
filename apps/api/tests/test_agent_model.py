"""模型网关：唯一组装处、重试归属、重试预算与失败分类。

对应 docs/技术设计/technical-details/通用基座.md 第 6 节与第 9 节。
本组用例全部离线：不发起任何真实模型调用（`TECH-02` 未核实，且不得把使用者资料
发给外部处理方）。

测试环境自保：构造 httpx/openai 客户端时会读取宿主机的 `no_proxy`；实测本机
`no_proxy` 含 `[::1]` 时 httpx 0.28.1 在构造期抛 `InvalidURL`。归一化在
`tests/conftest.py` 里统一做，本文件不再重复（这条陷阱本身也有一条用例）。
"""

from __future__ import annotations

import asyncio

import httpx2
import pytest
from agents.exceptions import ModelTimeoutError
from agents.retry import (
    ModelRetryBackoffSettings,
    ModelRetryNormalizedError,
    RetryDecision,
    RetryPolicy,
    RetryPolicyContext,
)
from pydantic import SecretStr

from campfire.agent.limits import AGENT_RUN_TIMEOUT_SECONDS
from campfire.agent.model import (
    ModelConfigurationError,
    ModelGateway,
    build_retry_settings,
    classify_model_failure,
    resolve_model_name,
    worst_case_model_seconds,
)
from campfire.core.config import Settings

API_KEY = SecretStr("test-key")


def _settings(**overrides: object) -> Settings:
    """构造一份含凭据的配置；不读 .env 的字段用显式默认值固定下来。"""
    values: dict[str, object] = {
        "tokenhub_api_key": API_KEY,
        "tokenhub_base_url": "https://tokenhub.example/v1",
        "model_name": "deepseek-v4.1-flash",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]  # 夹具以 object 组合再交给 pydantic 收敛校验，静态类型看不出这层收敛


async def _retry_decision(policy: RetryPolicy, context: RetryPolicyContext) -> bool:
    """调用重试策略并取出「要不要重试」。

    策略返回 `bool | RetryDecision`，而 `RetryDecision` 是 dataclass——实例本身恒为
    真值，因此必须读它的 `retry` 字段而不是 `bool(...)`，否则「不重试」会被读成重试。
    """
    decision = policy(context)
    if asyncio.iscoroutine(decision):
        decision = await decision
    return decision.retry if isinstance(decision, RetryDecision) else bool(decision)


# --- 配置与组装 -------------------------------------------------------------


def test_gateway_requires_an_api_key() -> None:
    with pytest.raises(ModelConfigurationError, match="TOKENHUB_API_KEY"):
        ModelGateway(Settings(tokenhub_api_key=None))


def test_unknown_purpose_fails_instead_of_falling_back_to_the_default_model() -> None:
    with pytest.raises(ModelConfigurationError, match="未知的模型用途档"):
        resolve_model_name(_settings(), purpose="emergency")  # type: ignore[arg-type]  # 故意传词表外的用途档：本用例测的就是它在装载期失败


def test_gateway_uses_the_configured_model_name_and_base_url() -> None:
    gateway = ModelGateway(_settings())

    assert gateway.model_name == "deepseek-v4.1-flash"
    # Model 接口不暴露 model 属性，这里断言的是具体实现回填了配置的模型名
    assert gateway.model.model == "deepseek-v4.1-flash"  # type: ignore[attr-defined]  # `Model` 接口不暴露 model，断言的是具体实现回填的模型名
    assert str(gateway.client.base_url).startswith("https://tokenhub.example/v1")


def test_client_level_retries_are_disabled_so_the_runner_owns_the_bound() -> None:
    """重试只能有一个所有者：客户端与 SDK 同时重试会让尝试次数相乘。"""
    gateway = ModelGateway(_settings())

    assert gateway.client.max_retries == 0


def test_request_timeout_is_bounded_by_configuration() -> None:
    gateway = ModelGateway(_settings(model_request_timeout_seconds=12.5))

    assert gateway.client.timeout == 12.5


def test_gateway_injects_retry_settings() -> None:
    # 超时取 20 秒：4 次重试的最坏值（20×5 + 退避 ≈ 105.6 秒）乘 2 次调用仍在上限之内
    # （闸门是「两次最坏调用装得下」，见 gateway 类说明第 2 条；30 秒那组会越线）。
    gateway = ModelGateway(
        _settings(model_max_retries=4, model_request_timeout_seconds=20.0, model_retry_initial_delay_seconds=0.5)
    )

    retry = gateway.model_settings.retry

    assert retry is not None
    assert retry.max_retries == 4
    # `backoff` 的声明类型是 `ModelRetryBackoffSettings | dict[str, Any]`；这里连形状一起断死：
    # 网关必须产出 pydantic 数据类，而不是把字典原样透传给 SDK。
    assert isinstance(retry.backoff, ModelRetryBackoffSettings)
    assert retry.backoff.initial_delay == 0.5
    assert retry.backoff.jitter is True


@pytest.mark.asyncio
async def test_gateway_closes_its_client() -> None:
    """关闭后底层客户端必须真的关掉（只断言「不抛」的话，改成空实现也会通过）。"""
    gateway = ModelGateway(_settings())
    assert gateway.client.is_closed() is False

    await gateway.aclose()

    assert gateway.client.is_closed() is True


def test_gateway_rejects_a_client_that_keeps_its_own_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试只能有一个所有者：客户端若没接受 `max_retries=0`，构造期就要失败。"""

    class StubbornClient:
        """忽略我们传入的 max_retries。"""

        max_retries = 3

        def __init__(self, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr("campfire.agent.model.gateway.AsyncOpenAI", StubbornClient)

    with pytest.raises(ModelConfigurationError, match="关闭自身重试"):
        ModelGateway(_settings())


def test_client_construction_failure_becomes_an_actionable_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任何构造期异常都必须转成可操作的配置错误。

    用通用异常而不是某个具体传输异常：真实路径上 openai 用的是 `httpx2`，
    它的 `InvalidURL` 与 `httpx` 0.28.1 的 `InvalidURL` 是两个类（实测互不为子类），
    因此拿 `httpx.InvalidURL` 造夹具其实没覆盖真实陷阱，只是被 `except Exception` 兜住。
    """
    from openai import APIConnectionError

    def broken_client(**_kwargs: object) -> None:
        raise APIConnectionError(request=None)  # type: ignore[arg-type]  # 只为构造一个真实类型

    monkeypatch.setattr("campfire.agent.model.gateway.AsyncOpenAI", broken_client)

    with pytest.raises(ModelConfigurationError, match="客户端构造失败"):
        ModelGateway(_settings())


def test_no_proxy_trap_does_not_block_gateway_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """宿主机 `no_proxy` 含 `[::1]` 时网关仍必须能构造（2026-10-01 修）。

    ~~这条替换了原先的 `test_real_no_proxy_trap_is_translated_into_a_configuration_error`。~~

    **⇒ 已订正（2026-10-02）**：上面划掉的那句里点名的用例**是真实存在过的用例**——
    它**由 `6fe28ba` 引入本文件**（`6fe28ba^` 处尚无该 `def`），并在 **`0ecb786` 被删除**；
    核实方式是 `git log --all -S "def <上面划掉的那个名字>"`，**命中 `6fe28ba` 与
    `0ecb786` 两个提交**（按 `--reverse` 即「先引入、后删除」），
    且 `git show 6fe28ba:apps/api/tests/test_agent_model.py` 里能看到该 `def`。
    **当前 HEAD 已无此用例。**
    （⚠ 证据命令里的名字写成占位：把它逐字写在这里会制造一条新的悬挂引用，
    而那正是本条订正要避免的事；逐字的名字就在上面划掉的那句里，可照抄去跑。）
    **⇒ 那句记录的事实成立且要保留**：本条**替换了原先一条锁「陷阱存在、被翻译成配置错误」
    的用例**，而且那次替换**正是按那条旧用例自己写明的失效条件执行的**
    ——`0ecb786` 的提交信息里逐字写着「旧的 `<上面划掉的那个名字>` 按其自身写明的失效条件
    替换为新用例」（**名字同样以占位写法给出**：提交信息不在本守卫的扫描面内，
    但把它抄进本 docstring 就会制造一条新的悬挂引用，与本条订正的目的相反）。
    那条旧用例锁的是「陷阱存在、被翻译成配置错误」，并自带失效条件：

        若将来 httpx2 修好这个解析，构造会成功、本用例会失败——那时删掉它，
        并把「陷阱已消失」记进文档，而不是放宽断言。

    现在正是那个时刻，但成因不是 httpx2 修好了，而是我们在构造窗口内做了规范化
    （`agent/model/proxy_env`）。变化的意义比原用例大：原先网关在含 `[::1]` 的
    宿主机上根本建不起来，于是生产组合根装配失败、产品端点稳定 503——把「陷阱」
    翻成一个可操作的配置错误，只是让失败变得可读，并没有让系统能用。现在它是真的能用。

    判别性：去掉 `gateway.py` 里的 `with normalized_no_proxy_environment():`，
    本用例失败（抛 `ModelConfigurationError`）。
    """
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1,[::1]")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1,[::1]")

    gateway = ModelGateway(_settings())
    try:
        assert gateway.model_name
    finally:
        import asyncio

        asyncio.run(gateway.aclose())


def test_proxy_normalisation_preserves_the_exemption_semantics() -> None:
    """规范化只改词法，不改「哪些主机豁免代理」。

    判据取自实测：`[::1]` 与 `::1` 两种写法经 httpx2 解析出的豁免模式完全相同
    （都是 `all://[::1]`），差别只在后者不会在解析期崩。因此规范化必须做到
    「去掉方括号」而「不动其它任何取值」。
    """
    from campfire.agent.model.proxy_env import normalize_no_proxy

    assert normalize_no_proxy("127.0.0.1,localhost,::1,[::1]") == "127.0.0.1,localhost,::1,::1"
    assert normalize_no_proxy("[::1]") == "::1"
    # 其它形态逐字不动：域名、IPv4、CIDR、通配、非 IPv6 的方括号写法
    assert normalize_no_proxy("example.com,10.0.0.0/8,*.internal") == "example.com,10.0.0.0/8,*.internal"
    assert normalize_no_proxy("[not-ipv6]") == "[not-ipv6]"
    # 空白与顺序保留（避免把「看起来一样」当成「字符串一样」）
    assert normalize_no_proxy(" a , [::1] ,b") == " a , ::1 ,b"


# --- 重试预算 ---------------------------------------------------------------


def test_default_retry_budget_fits_inside_the_run_cap() -> None:
    """重试预算必须落在通用响应上限内，否则重试会被运行上限砍断。

    退避按 SDK 的抖动上界算（每次延迟最多 1.125 倍，见
    `agents/run_internal/model_retry.py:204`）：只按名义值算会低估，第一版就是这么错的。
    """
    worst_case = worst_case_model_seconds(_settings())

    assert worst_case == pytest.approx(120.0 * 2 + 1.125)
    assert worst_case <= AGENT_RUN_TIMEOUT_SECONDS


def test_run_cap_covers_more_than_one_model_call() -> None:
    """运行上限必须装得下两次**典型**调用（这条判据原先不存在，180 秒才活了下来）。

    为什么需要它：`test_default_retry_budget_fits_inside_the_run_cap` 只证明「一次最坏调用
    装得下」。但一轮真实运行至少两次模型调用（思考 → 调工具 → 读结果 → 再思考 → 成文），
    常见三到四次。2026-10-28 实测：45 秒超时 + 2 次重试的预算下，一次调用就吃掉 138 秒，
    两次就是 276 秒——180 秒的上限让这类轮次**必然**被杀，使用者等满三分钟什么也拿不到。

    判据分两层，两层都要成立：
      - 「两次典型调用」：`2 × 单次超时 <= 上限`（正常节奏下两次调用装得下）；
      - 「一次最坏调用」：`最坏预算 < 上限`（由上一个用例守）。
    只守后者会重演 180 秒那次：最坏预算装得下，但正常一轮都跑不完。
    """
    settings = _settings()

    typical_pair = settings.model_request_timeout_seconds * 2
    assert typical_pair <= AGENT_RUN_TIMEOUT_SECONDS, (
        f"单次超时 {settings.model_request_timeout_seconds:.1f} 秒 × 2 次调用 = {typical_pair:.1f} 秒，"
        f"超过运行上限 {AGENT_RUN_TIMEOUT_SECONDS:.0f} 秒：一轮用到两次模型调用的运行会被上限砍断"
    )
    assert worst_case_model_seconds(settings) < AGENT_RUN_TIMEOUT_SECONDS


def test_retry_budget_counts_the_jitter_upper_bound() -> None:
    """按名义退避算会放行、按抖动上界必须拒绝——锁住它才能防止「算术退回名义值」。

    这是审查者用探针测出来的反例；数字随通用响应上限走（上限一半的判据见
    `test_run_cap_covers_more_than_one_model_call`），不在这里写死秒数。
    """
    # 13 秒 × 8 次尝试 + 名义退避 177.8 = 281.8 秒（按名义值算会放行），
    # 加上抖动上界（每次最多 1.125 倍）就是 304.0 秒（必须拒绝）。上限 300 秒。
    sneaky = _settings(
        model_request_timeout_seconds=13.0,
        model_max_retries=7,
        model_retry_initial_delay_seconds=1.4,
        model_retry_max_delay_seconds=1000.0,
    )

    # 这组配置的单次最坏预算已越过上限（名义值算会放行，抖动上界算必须拒绝）。
    assert worst_case_model_seconds(sneaky) >= AGENT_RUN_TIMEOUT_SECONDS
    with pytest.raises(ModelConfigurationError, match="达到或超过通用响应上限"):
        build_retry_settings(sneaky)


def test_retry_budget_equal_to_the_cap_exactly_is_rejected() -> None:
    """最坏预算恰好等于上限也要拒绝：那时最后一次重试与运行上限同时到期，失败原因会摇摆。

    秒数由常量推出而不是写死：1 次重试下最坏是 `2 × 超时 + 1.125`（抖动上界），
    于是令它等于上限即可。边界用例一旦写死数字就会退化成同义反复。
    """
    cap = AGENT_RUN_TIMEOUT_SECONDS
    exact = _settings(model_request_timeout_seconds=(cap - 1.125) / 2, model_max_retries=1)

    assert worst_case_model_seconds(exact) == pytest.approx(cap)
    with pytest.raises(ModelConfigurationError):
        build_retry_settings(exact)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_request_timeout_seconds", 0.0),
        ("model_request_timeout_seconds", -5.0),
        ("model_max_retries", -1),
        ("model_retry_initial_delay_seconds", -1.0),
        ("model_retry_max_delay_seconds", -1.0),
    ],
)
def test_illegal_retry_numbers_are_rejected_at_config_load(field: str, value: float) -> None:
    """负数重试会把「最坏耗时」算成 0 秒、让闸门对任何超时值放行——加载期就要失败。

    实测反例：`model_max_retries=-1` 配 `timeout=1000` 曾能构造成功。
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _settings(**{field: value})


def test_retry_budget_that_exceeds_the_run_cap_is_rejected() -> None:
    burst = _settings(model_request_timeout_seconds=100.0, model_max_retries=3)

    with pytest.raises(ModelConfigurationError, match="达到或超过通用响应上限"):
        build_retry_settings(burst)


def test_huge_retry_count_is_reported_not_overflowed() -> None:
    """极大重试次数必须给可操作的配置错误，而不是浮点溢出（第一版抛 OverflowError）。"""
    base = _settings()
    huge = Settings.model_construct(**{**base.model_dump(), "model_max_retries": 2000})

    with pytest.raises(ModelConfigurationError, match="达到或超过通用响应上限"):
        build_retry_settings(huge)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retry_after", "expected_retry"),
    [
        (429, None, True),  # 限流：重试
        (503, None, True),  # 供应商 5xx：重试
        (408, None, True),  # 请求超时：重试
        (None, 5.0, True),  # 供应商给了 Retry-After：按它重试
        (400, None, False),  # 参数错误：重试无用
        (401, None, False),  # 认证失败：重试无用，必须暴露配置问题
        (403, None, False),
    ],
)
async def test_retry_policy_retries_only_the_transient_failures(
    status_code: int | None,
    retry_after: float | None,
    expected_retry: bool,
) -> None:
    policy = build_retry_settings(_settings()).policy
    assert policy is not None

    context = RetryPolicyContext(
        error=RuntimeError("stub"),
        attempt=1,
        max_retries=2,
        stream=True,
        normalized=ModelRetryNormalizedError(status_code=status_code, retry_after=retry_after),
    )

    assert await _retry_decision(policy, context) is expected_retry


@pytest.mark.asyncio
async def test_retry_policy_retries_network_and_timeout_failures() -> None:
    policy = build_retry_settings(_settings()).policy
    assert policy is not None

    for normalized in (
        ModelRetryNormalizedError(is_timeout=True),
        ModelRetryNormalizedError(is_network_error=True),
    ):
        context = RetryPolicyContext(
            error=RuntimeError("stub"),
            attempt=1,
            max_retries=2,
            stream=True,
            normalized=normalized,
        )
        assert await _retry_decision(policy, context) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", [600.0, 3600.0])
async def test_supplier_retry_after_is_clamped_to_the_configured_max_delay(retry_after: float) -> None:
    """供应商给的 `Retry-After` 必须被夹到退避上界内——否则预算闸门对它形同不存在。

    SDK 原生的 `retry_after()` 把该值原样当 delay 睡掉（`agents/retry.py:348-355` →
    `run_internal/model_retry.py:483-491` → `:678`），于是 `Retry-After: 600` 会让一次
    重试睡 600 秒，被 180 秒运行预算砍断，失败原因从「模型不可用」变成「运行超时」。
    这里断言延迟本身有界（只断言「会重试」会漏掉这个缺陷——上面那条参数化用例正是如此）。
    """
    settings = _settings(model_retry_max_delay_seconds=8.0)
    policy = build_retry_settings(settings).policy
    assert policy is not None

    context = RetryPolicyContext(
        error=RuntimeError("stub"),
        attempt=1,
        max_retries=settings.model_max_retries,
        stream=True,
        normalized=ModelRetryNormalizedError(status_code=429, retry_after=retry_after),
    )

    decision = policy(context)
    if asyncio.iscoroutine(decision):
        decision = await decision
    assert isinstance(decision, RetryDecision)
    assert decision.retry is True
    assert decision.delay is not None, "必须显式给出夹紧后的 delay，否则 SDK 会回落到未夹紧的原值"
    assert decision.delay <= 8.0, f"Retry-After {retry_after} 未被夹到退避上界：{decision.delay}"


@pytest.mark.asyncio
async def test_supplier_retry_after_smaller_than_the_cap_is_kept_verbatim() -> None:
    """夹紧只压上界：供应商给的较小延迟应原样保留（它有真实语义，不该被抬高）。"""
    settings = _settings(model_retry_max_delay_seconds=8.0)
    policy = build_retry_settings(settings).policy
    assert policy is not None

    context = RetryPolicyContext(
        error=RuntimeError("stub"),
        attempt=1,
        max_retries=settings.model_max_retries,
        stream=True,
        normalized=ModelRetryNormalizedError(status_code=429, retry_after=3.0),
    )

    decision = policy(context)
    if asyncio.iscoroutine(decision):
        decision = await decision
    assert isinstance(decision, RetryDecision)
    assert decision.delay == 3.0


# --- 失败分类 ---------------------------------------------------------------


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://tokenhub.example/v1/chat/completions")


def _response(status_code: int) -> httpx2.Response:
    return httpx2.Response(status_code, request=_request())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("slow"), "timeout"),
        (ModelTimeoutError(30.0), "timeout"),
        # httpx2 的 `ReadTimeout` 不是内建 `TimeoutError` 的子类（实测 MRO 不含它）：提供方
        # 之外的传输超时无法归因，只能落 `unknown`。
        (httpx2.ReadTimeout("slow"), "unknown"),
        (ValueError("boom"), "unknown"),
    ],
)
def test_classify_non_openai_failures(error: BaseException, expected: str) -> None:
    assert classify_model_failure(error) == expected


def test_classify_openai_failures() -> None:
    import openai

    assert classify_model_failure(openai.APITimeoutError(request=_request())) == "timeout"
    assert classify_model_failure(openai.APIConnectionError(request=_request())) == "connection"
    assert classify_model_failure(openai.RateLimitError("rl", response=_response(429), body=None)) == "rate_limited"
    assert (
        classify_model_failure(openai.AuthenticationError("auth", response=_response(401), body=None))
        == "authentication"
    )
    assert classify_model_failure(openai.APIStatusError("boom", response=_response(500), body=None)) == "provider_error"


def test_timeout_is_not_misclassified_as_a_connection_problem() -> None:
    """`APITimeoutError` 是 `APIConnectionError` 的子类，判定顺序错了就会误报。"""
    import openai

    timeout_error = openai.APITimeoutError(request=_request())

    assert isinstance(timeout_error, openai.APIConnectionError)
    assert classify_model_failure(timeout_error) == "timeout"
