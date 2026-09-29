"""模型网关：**模型名与客户端在本仓库的唯一组装处**。

依据 docs/技术设计/technical-details/通用基座.md 第 6 节「模型路由」：

- 统一配置入口，**业务代码不得硬编码模型名**；接口保留用途分档（一期只有一个值）。
- 失败语义：超时、限流与供应商错误按策略重试；重试耗尽则本次运行失败并给出原因。
  **不得**用缓存或旧结果冒充当前结果。

以及 docs/技术栈设计.md 第 2 节与本仓库已核实的事实：TokenHub 提供 OpenAI 兼容接口，
Base URL 固定 ``https://tokenhub.tencentmaas.com/v1``，且**按开通地域选择接口、不支持
跨地域调用**；SDK 侧走** Chat Completions** 模型类（不是 Responses）。

## 三处刻意的决定

**1. 重试交给 SDK 的 runner-managed retry，客户端自身的重试关掉（``max_retries=0``）。**
SDK 提供 ``ModelRetrySettings`` 与 ``retry_policies`` 策略 DSL，它自己处理「响应是否已经
开始流出」这类重放安全问题；而 OpenAI 客户端也有自己的重试。两者同时开会让最坏尝试次数
相乘（客户端 3 次 × SDK 3 次 = 最多 16 次请求），且两套退避互相叠加、总时长不可预期。
因此：**重试只有一个所有者**，就是 SDK 的 runner-managed retry。

**2. 重试预算必须落在 180 秒通用响应上限之内。** 否则模型重试会被运行上限从中间砍断，
失败原因从「模型不可用」变成「运行超时」——那是最难排查的一类误报。构造时即校验
（:func:`worst_case_model_seconds`），不合法就抛 :class:`ModelConfigurationError`。

**3. 客户端由装配处构造一次并复用。** 每次运行新建 ``AsyncOpenAI`` 会新建连接池与
TLS 握手，代价直接落在应急路径的首字时延上（``RQ-EMG-03``）。因此这里是**长生命周期
对象**：由装配处持有，运行编排按次取 ``model``。

## 已核实的宿主机环境陷阱（会在这里以明确错误暴露）

构造任何开启 ``trust_env`` 的 httpx/openai 客户端时，若 ``no_proxy`` 含**带方括号的
IPv6 字面量**（例如 ``no_proxy=127.0.0.1,localhost,::1,[::1]``），httpx 0.28.1 会在解析
挂载规则时抛 ``InvalidURL: Invalid port: ':1]'``。实测复现：本机 ``no_proxy`` 值即含
``[::1]``，``httpx.AsyncClient()`` 与 ``openai.AsyncOpenAI(...)`` 都在**构造期**失败；
把 ``[::1]`` 去掉即恢复。

我们**仍然保留** ``trust_env``：TokenHub 是外部服务，企业网络下可能需要经代理访问
（与健康探针同一取舍）。代价是这个环境问题会表现为构造失败，因此构造异常一律转成
:class:`ModelConfigurationError` 并给出可操作的提示，而不是把裸 ``InvalidURL`` 抛出去。
"""

from __future__ import annotations

from typing import Literal

from agents import ModelSettings
from agents.models.interface import Model
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.retry import ModelRetryBackoffSettings, ModelRetrySettings, retry_policies
from openai import AsyncOpenAI

from campfire.agent.limits import AGENT_RUN_TIMEOUT_SECONDS
from campfire.core.config import Settings

from .errors import ModelConfigurationError

ModelPurpose = Literal["default"]
"""用途分档。一期全应用单一模型，因此**只有一个值**——保留这个形参是为了不让调用点
把「只有一个」写死：等出现第二个档位时，分发逻辑加在 :func:`resolve_model_name` 里，
调用点不动（技术栈设计第 3 节）。"""

# 退避倍数固定为 2：它只是一个上界参数，没有第二个消费者要调它，因此不做成配置项。
_BACKOFF_MULTIPLIER = 2.0

# 需要重试的供应商状态码：408 请求超时、409 冲突、429 限流，以及 5xx。
# 认证失败（401/403）与 400 类**不在其中**：重试不会让它们变好，只会消耗时间预算。
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


def resolve_model_name(settings: Settings, purpose: ModelPurpose = "default") -> str:
    """按用途取模型名。业务代码只经此函数取模型名（项目结构设计第 10 节）。

    Raises:
        ModelConfigurationError: 传入了一期不存在的用途档。
    """
    if purpose != "default":
        raise ModelConfigurationError(f"未知的模型用途档 {purpose!r}：一期只有 'default'")
    return settings.model_name


def worst_case_model_seconds(settings: Settings) -> float:
    """模型调用链最坏情况占用的墙钟秒数：``超时 × 尝试次数 + 退避延迟之和``。

    供构造期校验与测试使用，让「重试预算落在运行上限内」这条约束可被机械核对，
    而不是靠读注释相信它。
    """
    attempts = settings.model_max_retries + 1
    delays = sum(
        min(
            settings.model_retry_initial_delay_seconds * (_BACKOFF_MULTIPLIER**attempt),
            settings.model_retry_max_delay_seconds,
        )
        for attempt in range(settings.model_max_retries)
    )
    return settings.model_request_timeout_seconds * attempts + delays


def build_retry_settings(settings: Settings) -> ModelRetrySettings:
    """构造 SDK 的 runner-managed 重试配置。

    Raises:
        ModelConfigurationError: 配置的重试预算超出 180 秒通用响应上限。
    """
    worst_case = worst_case_model_seconds(settings)
    if worst_case > AGENT_RUN_TIMEOUT_SECONDS:
        raise ModelConfigurationError(
            f"模型重试预算最坏 {worst_case:.1f} 秒，超过通用响应上限 {AGENT_RUN_TIMEOUT_SECONDS:.0f} 秒："
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
            retry_policies.retry_after(),
            retry_policies.http_status(_RETRYABLE_STATUS_CODES),
        ),
    )


# quality-floor: ignore docstring-promise 异常由 build_retry_settings 抛出，本函数体无 raise
def build_model_settings(settings: Settings) -> ModelSettings:
    """构造模型的调用设置（重试是其中唯一由基座裁决的部分）。

    Raises:
        ModelConfigurationError: 重试预算超出通用响应上限。
    """
    return ModelSettings(retry=build_retry_settings(settings))


class ModelGateway:
    """进程内复用的模型网关：一次构造，按次取用。

    装配处（``main.py`` / ``worker.py``）持有它，并在进程结束时 ``aclose()``。
    """

    def __init__(self, settings: Settings) -> None:
        """校验配置并构造客户端。

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
                # 重试的唯一所有者是 SDK 的 runner-managed retry，见模块 docstring。
                max_retries=0,
            )
        except Exception as exc:  # noqa: BLE001 —— 构造期异常一律转成可操作的配置错误
            # 不带原始消息：httpx 的异常文本可能包含代理 URL（其中可能含凭据）。
            raise ModelConfigurationError(
                f"模型客户端构造失败（{type(exc).__name__}）：请检查 TOKENHUB_BASE_URL 与宿主机代理配置"
                "（已知陷阱：no_proxy 里的 [::1] 会让 httpx 在构造期失败）"
            ) from exc

        self._model = OpenAIChatCompletionsModel(model=self._model_name, openai_client=self._client)

    @property
    def client(self) -> AsyncOpenAI:
        """底层 HTTP 客户端。

        暴露它是为了让**重试归属**这条契约可被核对：客户端自身必须 ``max_retries=0``
        （否则与 SDK 的 runner-managed retry 相乘），超时必须是有界值。这条契约写在
        docstring 里无法防止有人改掉它，暴露出来才能被测到。
        """
        return self._client

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
        """调用设置；运行编排把它放进 ``RunConfig``。"""
        return self._settings

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端与连接池。"""
        await self._client.close()
