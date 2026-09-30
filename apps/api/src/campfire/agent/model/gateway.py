"""模型网关：模型名与客户端在本仓库的唯一组装处。

职责：按用途解析模型名（:func:`resolve_model_name`），构造并持有进程内复用的模型客户端与重试配置。
边界：业务代码不得硬编码模型名，只经本模块取值；基座不含领域术语，本模块同样不含。
参考：docs/技术设计/technical-details/通用基座.md 第 6 节「模型路由」、docs/技术栈设计.md 第 2 节。
重试归属、180 秒预算、客户端复用三处刻意的决定与宿主机环境陷阱，各自下沉到被引用的定义处。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agents import ModelSettings
from agents.models.interface import Model
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.retry import (
    ModelRetryBackoffSettings,
    ModelRetrySettings,
    RetryDecision,
    RetryPolicy,
    RetryPolicyContext,
    retry_policies,
)
from openai import AsyncOpenAI

from campfire.agent.limits import AGENT_RUN_TIMEOUT_SECONDS
from campfire.core.config import Settings

from .errors import ModelConfigurationError

ModelPurpose = Literal["default"]
"""用途分档。一期全应用单一模型，因此只有一个值——保留这个形参是为了不让调用点
把「只有一个」写死：等出现第二个档位时，分发逻辑加在 :func:`resolve_model_name` 里，
调用点不动（技术栈设计第 3 节）。"""

# 退避倍数固定为 2：它只是一个上界参数，没有第二个消费者要调它，
# 因此不做成配置项。
_BACKOFF_MULTIPLIER = 2.0

# SDK 的抖动上界。依据 `agents/run_internal/model_retry.py:204`：
#     min(max(base * (0.875 + random() * 0.25), 0.0), max_delay)
# 即每次延迟最多是 base 的 1.125 倍。预算必须按这个上界算：只按名义 base 算会低估
# （实测默认配置低估 0.375 秒，而一组合法配置低估 22.2 秒——足以让闸门放行一个真实最坏
# 200 秒的配置）。
_JITTER_UPPER_BOUND = 1.125

# 指数项的夹子。`max_delay` 一旦饱和，后续延迟都等于上界，所以夹住指数不改变上界；
# 而不夹会让 `2.0 ** attempt` 在 attempt 上千时抛 OverflowError（配置错误却得到浮点溢出，
# 恰是本该给可操作提示的场景）。
_MAX_BACKOFF_EXPONENT = 64

# 需要重试的供应商状态码：408 请求超时、409 冲突、429 限流，以及 5xx。
# 认证失败（401/403）与 400 类不在其中：重试不会让它们变好，只会消耗时间预算。
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


def resolve_model_name(settings: Settings, purpose: ModelPurpose = "default") -> str:
    """按用途取模型名。业务代码只经此函数取模型名（项目结构设计第 10 节）。

    依据 docs/技术设计/technical-details/通用基座.md 第 6 节「模型路由」：

    - 统一配置入口，业务代码不得硬编码模型名；接口保留用途分档（一期只有一个值）。

    以及 docs/技术栈设计.md 第 2 节与本仓库已核实的事实：TokenHub 提供 OpenAI 兼容接口，
    Base URL 固定 `https://tokenhub.tencentmaas.com/v1`，且按开通地域选择接口、不支持
    跨地域调用；SDK 侧走 Chat Completions 模型类（不是 Responses）。

    Raises:
        ModelConfigurationError: 传入了一期不存在的用途档。
    """
    if purpose != "default":
        raise ModelConfigurationError(f"未知的模型用途档 {purpose!r}：一期只有 'default'")
    return settings.model_name


def require_sane_retry_config(settings: Settings) -> None:
    """校验重试相关的四个数字本身合法（闸门与算术共用同一份判定）。

    必须在算术之前做：`model_max_retries = -1` 会让「尝试次数 = 0」、最坏耗时算成
    0 秒，于是「预算落在 180 秒内」这道闸门对任何超时值都放行；`timeout <= 0` 同理。
    pydantic 侧对 `.env` 来的值也会拦，但算术不能依赖「上一步拦住了」。

    Raises:
        ModelConfigurationError: 超时非正、退避延迟为负、或重试次数为负。
    """
    if settings.model_request_timeout_seconds <= 0:
        raise ModelConfigurationError(
            f"model_request_timeout_seconds 必须为正数（当前 {settings.model_request_timeout_seconds}）："
            "0 或负数会让单次模型请求没有时间上界"
        )
    if settings.model_max_retries < 0:
        raise ModelConfigurationError(
            f"model_max_retries 不能为负（当前 {settings.model_max_retries}）："
            "负数会被 SDK 当作 0，而重试预算算术会归零、闸门形同不存在"
        )
    if settings.model_retry_initial_delay_seconds < 0 or settings.model_retry_max_delay_seconds < 0:
        raise ModelConfigurationError("model_retry_initial_delay_seconds / model_retry_max_delay_seconds 不能为负")


# quality-floor: ignore docstring-promise 异常由 require_sane_retry_config 抛出，本函数体只做算术
def worst_case_model_seconds(settings: Settings) -> float:
    """模型调用链最坏情况占用的墙钟秒数：`超时 × 尝试次数 + 退避延迟之和`。

    三条口径，写清楚以免再次算错：

    1. 退避按 SDK 的抖动上界算（每次延迟再乘 :data:`_JITTER_UPPER_BOUND`），
       不是按名义值算——SDK 开着 `jitter=True`；
    2. 先校验再算（:func:`require_sane_retry_config`）：负数重试会把最坏耗时算成 0 秒；
    3. 指数项夹在 :data:`_MAX_BACKOFF_EXPONENT` 次方，保证对任意配置都不抛浮点溢出。

    供应商 `Retry-After` 那条路径已纳入同一上界：SDK 原生的 `retry_after()` 会把
    供应商给的秒数原样当 delay 睡掉、绕过这里的算术，因此 :func:`build_retry_settings`
    改用 :func:`_bounded_retry_after`，把该值夹到 `model_retry_max_delay_seconds`。
    本函数算的就是那个上界，两者因此一致。

    供构造期校验与测试使用，让「重试预算落在运行上限内」这条约束可被机械核对，
    而不是靠读注释相信它。

    Raises:
        ModelConfigurationError: 重试相关配置本身非法（见 :func:`require_sane_retry_config`）。
    """
    require_sane_retry_config(settings)

    retries = settings.model_max_retries
    delays = 0.0
    for attempt in range(retries):
        base = min(
            settings.model_retry_initial_delay_seconds * (_BACKOFF_MULTIPLIER ** min(attempt, _MAX_BACKOFF_EXPONENT)),
            settings.model_retry_max_delay_seconds,
        )
        delays += min(base * _JITTER_UPPER_BOUND, settings.model_retry_max_delay_seconds)
    return settings.model_request_timeout_seconds * (retries + 1) + delays


def build_retry_settings(settings: Settings) -> ModelRetrySettings:
    """构造 SDK 的 runner-managed 重试配置。

    1. 重试交给 SDK 的 runner-managed retry，客户端自身的重试关掉（`max_retries=0`）。
    SDK 提供 `ModelRetrySettings` 与 `retry_policies` 策略 DSL，它自己处理「响应是否已经
    开始流出」这类重放安全问题；而 OpenAI 客户端也有自己的重试。实测（按 500 响应计 HTTP
    请求数）：客户端不设 `max_retries` 时一次调用最多发 3 个请求，设为 0 后只发 1 个。
    两者都开时并非简单相乘——SDK 在第二次尝试起会禁用 provider 管理重试
    （`agents/run_internal/model_retry.py:516-549`），实测「客户端 2 + SDK 2」= 5 个请求、
    「客户端 2 + SDK 3」= 6 个，而不是 9。结论不变（客户端必须是 0），但理由要说准：
    首次尝试会额外带上客户端的请求，而那一部分不在我们的预算算术里。

    2. 重试预算必须落在 180 秒通用响应上限之内。 否则模型重试会被运行上限从中间砍断，
    失败原因从「模型不可用」变成「运行超时」——那是最难排查的一类误报。构造时即校验
    （:func:`worst_case_model_seconds`），不合法就抛 :class:`ModelConfigurationError`。

    失败语义：超时、限流与供应商错误按策略重试；重试耗尽则本次运行失败并给出原因。
    不得用缓存或旧结果冒充当前结果。

    Raises:
        ModelConfigurationError: 重试相关配置非法，或其预算达到/超过 180 秒通用响应上限。
    """
    worst_case = worst_case_model_seconds(settings)
    # 用 >= 而不是 >：最坏耗时恰好等于上限时，最后一次重试与运行上限同时到期，
    # 失败原因会在「模型不可用」与「运行超时」之间摇摆——那正是这条闸门要避免的误报。
    if worst_case >= AGENT_RUN_TIMEOUT_SECONDS:
        raise ModelConfigurationError(
            f"模型重试预算最坏 {worst_case:.1f} 秒，达到或超过通用响应上限 {AGENT_RUN_TIMEOUT_SECONDS:.0f} 秒："
            "重试会被运行上限从中间砍断，失败原因会变成「运行超时」。"
            "请下调 model_request_timeout_seconds 或 model_max_retries"
        )

    return ModelRetrySettings(
        max_retries=settings.model_max_retries,
        backoff=ModelRetryBackoffSettings(
            initial_delay=settings.model_retry_initial_delay_seconds,
            max_delay=settings.model_retry_max_delay_seconds,
            multiplier=_BACKOFF_MULTIPLIER,
            jitter=True,
        ),
        # 策略取并集：网络/超时类、供应商给的 Retry-After、以及可重试状态码。
        # 不用 provider_suggested()：它在供应商没有明示建议时返回「不重试」，
        # 而 TokenHub 属第三方兼容端点，是否给该信号未经核实（TECH-12 同类未知）。
        policy=retry_policies.any(
            retry_policies.network_error(),
            _bounded_retry_after(settings),
            retry_policies.http_status(_RETRYABLE_STATUS_CODES),
        ),
    )


def _bounded_retry_after(settings: Settings) -> RetryPolicy:
    """`retry_policies.retry_after()` 的有上界版本。

    为什么必须包一层：SDK 的 `retry_after()` 把供应商的 `Retry-After` 原样作为
    `RetryDecision.delay` 返回（`agents/retry.py:348-355`），而该 delay 优先于默认
    退避（`run_internal/model_retry.py:483-491`）且不经任何夹紧，最终被
    `_sleep_for_retry(decision.delay)` 直接睡掉（同文件 `:678`）。于是一个
    `Retry-After: 600` 会睡 600 秒，被运行编排的 180 秒预算从中间砍断——失败原因从
    「模型不可用」变成「运行超时」，正是本模块要消灭的那类误报。
    夹到 `model_retry_max_delay_seconds` 之后，该路径落回与其它退避同一个上界，
    :func:`worst_case_model_seconds` 的算术因此对它重新成立。

    另一处必须一并夹的是 SDK 的兜底分支（`model_retry.py:487`）：即便本策略返回
    `retry=True` 而不给 delay，SDK 也会回落到 `normalized.retry_after`。因此这里
    总是显式给出 夹紧后的 delay，而不是「有值才给」。
    """

    def policy(context: RetryPolicyContext) -> bool | RetryDecision:
        """按供应商给的 Retry-After 决定重试，延迟夹到配置的退避上界。"""
        delay = context.normalized.retry_after
        if delay is None and context.provider_advice is not None:
            delay = context.provider_advice.retry_after
        if delay is None:
            return False
        return RetryDecision(retry=True, delay=min(delay, settings.model_retry_max_delay_seconds))

    policy.__name__ = "_bounded_retry_after"
    return policy


# quality-floor: ignore docstring-promise 异常由 build_retry_settings 抛出，本函数体无 raise
def build_model_settings(settings: Settings) -> ModelSettings:
    """构造模型的调用设置（重试是其中唯一由基座裁决的部分）。

    Raises:
        ModelConfigurationError: 重试预算超出通用响应上限。
    """
    return ModelSettings(retry=build_retry_settings(settings))


@dataclass(frozen=True, slots=True)
class ModelBinding:
    """一次运行要用的模型三件套：名字、模型实例、调用设置。

    单独成形是为了让运行编排只依赖这三样，而不是依赖整个网关——测试可以给出替身模型，
    而不必伪造凭据与客户端。

    `frozen=True` 只冻结这个外壳，不冻结 `settings`：`ModelSettings` 与
    `ModelRetrySettings` 实测都不是 frozen dataclass，且同一个对象会在多次取用之间共享
    （`binding.settings is gateway.model_settings` 为真）。就地改它会影响后续所有运行。
    仓库内目前没有触发者：SDK 的 `ModelSettings.resolve()` 是 copy-on-write，压缩的摘要
    调用用 `dataclasses.replace`。因此这是已知的理论风险而非已发生的缺陷——真要在
    结构上消除，需要给这两个 SDK 类型加冻结语义（我们无法改 SDK，只能包一层）。
    """

    name: str
    model: Model
    settings: ModelSettings


class ModelGateway:
    """进程内复用的模型网关：一次构造，按次取用。

    3. 客户端由装配处构造一次并复用。 每次运行新建 `AsyncOpenAI` 会新建连接池与
    TLS 握手，代价直接落在应急路径的首字时延上（`RQ-EMG-03`）。因此这里是长生命周期
    对象：由装配处持有，运行编排按次取 `model`。

    装配处（`main.py` / `worker.py`）持有它，并在进程结束时 `aclose()`。
    """

    def __init__(self, settings: Settings) -> None:
        """校验配置并构造客户端。

        已核实的宿主机环境陷阱（会在这里以明确错误暴露）：

        构造任何开启 `trust_env` 的客户端时，若 `no_proxy` 含带方括号的 IPv6 字面量
        （例如 `no_proxy=127.0.0.1,localhost,::1,[::1]`），URL 解析会在构造期抛
        `InvalidURL: Invalid port: ':1]'`。实测复现：本机 `no_proxy` 值即含 `[::1]`，
        `httpx.AsyncClient()` 与 `openai.AsyncOpenAI(...)` 都在构造期失败；去掉 `[::1]` 即恢复。

        归因要说准：`openai` 客户端用的是 httpx2（`openai/_base_client.py:37`
        `import httpx2`），与探针自用的 httpx 0.28.1 是两个独立包，两者的 `InvalidURL`
        实测互不为子类、也不是同一个类。因此排查时不能只看 `httpx` 的版本。

        我们仍然保留 `trust_env`：TokenHub 是外部服务，企业网络下可能需要经代理访问
        （与健康探针同一取舍）。代价是这个环境问题会表现为构造失败，因此构造异常一律转成
        :class:`ModelConfigurationError` 并给出可操作的提示，而不是把裸 `InvalidURL` 抛出去。

        Raises:
            ModelConfigurationError: 未配置凭据、重试预算越界，或客户端无法构造
                （例如宿主机代理环境有问题，见模块 docstring）。
        """
        self._model_name = resolve_model_name(settings)
        api_key = settings.tokenhub_api_key
        if api_key is None:
            raise ModelConfigurationError("未配置 TOKENHUB_API_KEY：模型路由无法建立")

        self._settings = build_model_settings(settings)

        try:
            self._client = AsyncOpenAI(
                base_url=settings.tokenhub_base_url,
                api_key=api_key.get_secret_value(),
                timeout=settings.model_request_timeout_seconds,
                # 重试的唯一所有者是 SDK 的 runner-managed retry，
                # 见模块 docstring。
                max_retries=0,
            )
        except Exception as exc:  # noqa: BLE001 —— 构造期异常一律转成可操作的配置错误
            # 不带原始消息：底层异常文本可能包含代理 URL（其中可能含凭据）。
            raise ModelConfigurationError(
                f"模型客户端构造失败（{type(exc).__name__}）：请检查 TOKENHUB_BASE_URL 与宿主机代理配置"
                "（已知陷阱：no_proxy 里的 [::1] 会让 httpx2 在构造期失败，见模块 docstring）"
            ) from exc

        # 把「客户端必须自己不重试」这条契约在构造期核实，而不是只写在 docstring 里：
        # 客户端带上重试就有两个所有者，预算算术不成立。
        if self._client.max_retries != 0:
            raise ModelConfigurationError(
                f"模型客户端未按契约关闭自身重试（max_retries={self._client.max_retries}）："
                "重试只能有一个所有者（SDK 的 runner-managed retry）"
            )

        self._model = OpenAIChatCompletionsModel(model=self._model_name, openai_client=self._client)

    @property
    def client(self) -> AsyncOpenAI:
        """底层 HTTP 客户端。

        暴露它是为了让重试归属这条契约可被核对：客户端自身必须 `max_retries=0`
        （否则重试出现两个所有者），超时必须是有界值。构造期已核实一次；这条契约的
        运行时强度仍只由测试保证——就地改 `gateway.client.max_retries` 会真实抬高
        首次尝试的请求数，而那一部分不在预算算术里（已知的理论风险，无结构防护）。
        """
        return self._client

    @property
    def binding(self) -> ModelBinding:
        """把模型三件套打包给运行编排。

        `settings` 是共享对象（见 :class:`ModelBinding` 的说明）：取用方不得就地改它。
        """
        return ModelBinding(name=self._model_name, model=self._model, settings=self._settings)

    @property
    def model(self) -> Model:
        """本次运行使用的模型实例（长生命周期，可直接复用）。"""
        return self._model

    @property
    def model_name(self) -> str:
        """模型名，供运行记录使用。"""
        return self._model_name

    @property
    def model_settings(self) -> ModelSettings:
        """调用设置；运行编排把它放进 `RunConfig`。"""
        return self._settings

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端与连接池。"""
        await self._client.close()
