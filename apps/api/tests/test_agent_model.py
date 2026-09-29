"""模型网关：唯一组装处、重试归属、重试预算与失败分类。

对应 docs/技术设计/technical-details/通用基座.md 第 6 节与第 9 节。
本组用例全部离线：不发起任何真实模型调用（``TECH-02`` 未核实，且不得把使用者资料
发给外部处理方）。

**测试环境自保**：构造 httpx/openai 客户端时会读取宿主机的 ``no_proxy``；实测本机
``no_proxy`` 含 ``[::1]`` 时 httpx 0.28.1 在构造期抛 ``InvalidURL``。归一化在
``tests/conftest.py`` 里统一做，本文件不再重复（这条陷阱本身也有一条用例）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from agents.retry import ModelRetryNormalizedError, RetryDecision, RetryPolicyContext
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
    return Settings(**values)  # type: ignore[arg-type]


async def _retry_decision(policy: object, context: RetryPolicyContext) -> bool:
    """调用重试策略并取出「要不要重试」。

    策略返回 ``bool | RetryDecision``，而 ``RetryDecision`` 是 dataclass——实例本身恒为
    真值，因此必须读它的 ``retry`` 字段而不是 ``bool(...)``，否则「不重试」会被读成重试。
    """
    decision = policy(context)  # type: ignore[operator]
    if asyncio.iscoroutine(decision):
        decision = await decision
    return decision.retry if isinstance(decision, RetryDecision) else bool(decision)


# --- 配置与组装 -------------------------------------------------------------


def test_gateway_requires_an_api_key() -> None:
    with pytest.raises(ModelConfigurationError, match="TOKENHUB_API_KEY"):
        ModelGateway(Settings(tokenhub_api_key=None))


def test_unknown_purpose_fails_instead_of_falling_back_to_the_default_model() -> None:
    with pytest.raises(ModelConfigurationError, match="未知的模型用途档"):
        resolve_model_name(_settings(), purpose="emergency")  # type: ignore[arg-type]


def test_gateway_uses_the_configured_model_name_and_base_url() -> None:
    gateway = ModelGateway(_settings())

    assert gateway.model_name == "deepseek-v4.1-flash"
    assert gateway.model.model == "deepseek-v4.1-flash"  # type: ignore[attr-defined]
    assert str(gateway.client.base_url).startswith("https://tokenhub.example/v1")


def test_client_level_retries_are_disabled_so_the_runner_owns_the_bound() -> None:
    """重试只能有一个所有者：客户端与 SDK 同时重试会让尝试次数相乘。"""
    gateway = ModelGateway(_settings())

    assert gateway.client.max_retries == 0


def test_request_timeout_is_bounded_by_configuration() -> None:
    gateway = ModelGateway(_settings(model_request_timeout_seconds=12.5))

    assert gateway.client.timeout == 12.5


def test_gateway_injects_retry_settings() -> None:
    # 超时取 30 秒，使 4 次重试的最坏值（30×5 + 退避）仍落在 180 秒上限内。
    gateway = ModelGateway(
        _settings(model_max_retries=4, model_request_timeout_seconds=30.0, model_retry_initial_delay_seconds=0.5)
    )

    retry = gateway.model_settings.retry

    assert retry is not None
    assert retry.max_retries == 4
    assert retry.backoff is not None
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
    """重试只能有一个所有者：客户端若没接受 ``max_retries=0``，构造期就要失败。"""

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

    用**通用**异常而不是某个具体传输异常：真实路径上 openai 用的是 **httpx2**，
    它的 ``InvalidURL`` 与 ``httpx`` 0.28.1 的 ``InvalidURL`` 是两个类（实测互不为子类），
    因此拿 ``httpx.InvalidURL`` 造夹具其实没覆盖真实陷阱，只是被 ``except Exception`` 兜住。
    """
    from openai import APIConnectionError

    def broken_client(**_kwargs: object) -> None:
        raise APIConnectionError(request=None)  # type: ignore[arg-type]  # 只为构造一个真实类型

    monkeypatch.setattr("campfire.agent.model.gateway.AsyncOpenAI", broken_client)

    with pytest.raises(ModelConfigurationError, match="客户端构造失败"):
        ModelGateway(_settings())


def test_real_no_proxy_trap_is_translated_into_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """宿主机 ``no_proxy`` 含 ``[::1]`` 这条真实陷阱必须被翻译成配置错误。

    **本用例自带失效条件**：它锁住的是 httpx2 当前对 ``no_proxy`` 里带方括号的 IPv6
    字面量的解析行为。若将来 httpx2 修好这个解析，构造会成功、本用例会失败——那时删掉它，
    并把「陷阱已消失」记进文档，而不是放宽断言。
    """
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1,[::1]")

    with pytest.raises(ModelConfigurationError, match="客户端构造失败"):
        ModelGateway(_settings())


# --- 重试预算 ---------------------------------------------------------------


def test_default_retry_budget_fits_inside_the_run_cap() -> None:
    """重试预算必须落在 180 秒通用响应上限内，否则重试会被运行上限砍断。

    退避按 **SDK 的抖动上界**算（每次延迟最多 1.125 倍，见
    ``agents/run_internal/model_retry.py:204``）：只按名义值算会低估，第一版就是这么错的。
    """
    worst_case = worst_case_model_seconds(_settings())

    assert worst_case == pytest.approx(45.0 * 3 + 1.125 + 2.25)
    assert worst_case <= AGENT_RUN_TIMEOUT_SECONDS


def test_retry_budget_counts_the_jitter_upper_bound() -> None:
    """一组合法配置：按名义退避算是 177.8 秒（会放行），按抖动上界是 200.0 秒（必须拒绝）。

    这是审查者用探针测出来的反例，锁住它才能防止「算术退回名义值」。
    """
    sneaky = _settings(
        model_request_timeout_seconds=0.001,
        model_max_retries=7,
        model_retry_initial_delay_seconds=1.4,
        model_retry_max_delay_seconds=1000.0,
    )

    assert worst_case_model_seconds(sneaky) >= AGENT_RUN_TIMEOUT_SECONDS
    with pytest.raises(ModelConfigurationError, match="达到或超过通用响应上限"):
        build_retry_settings(sneaky)


def test_retry_budget_is_allowed_to_reach_the_cap_exactly_is_rejected() -> None:
    """恰好等于上限也要拒绝：那时最后一次重试与运行上限同时到期，失败原因会摇摆。"""
    exact = _settings(model_request_timeout_seconds=59.0, model_max_retries=2)

    assert worst_case_model_seconds(exact) >= AGENT_RUN_TIMEOUT_SECONDS
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

    实测反例：``model_max_retries=-1`` 配 ``timeout=1000`` 曾能构造成功。
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


# --- 失败分类 ---------------------------------------------------------------


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://tokenhub.example/v1/chat/completions")


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_request())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("slow"), "timeout"),
        (httpx.ReadTimeout("slow"), "unknown"),
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
    """``APITimeoutError`` 是 ``APIConnectionError`` 的子类，判定顺序错了就会误报。"""
    import openai

    timeout_error = openai.APITimeoutError(request=_request())

    assert isinstance(timeout_error, openai.APIConnectionError)
    assert classify_model_failure(timeout_error) == "timeout"
