"""模型层的错误类型与失败分类。

依据 docs/技术设计/technical-details/通用基座.md 第 6 节与第 9 节：

- 失败语义：超时、限流与供应商错误按策略重试；**重试耗尽则本次运行失败并给出原因**；
- **不得**用缓存或旧结果冒充当前结果。

分类器存在的意义是让「给出原因」这一步有稳定词汇：运行编排把异常换成基座自己的错误码，
落进 ``run_failed`` 事件与运行记录，而不是把供应商的异常原文抛给使用者。
"""

from __future__ import annotations

from typing import Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

ModelFailureReason = Literal[
    "timeout",
    "rate_limited",
    "authentication",
    "connection",
    "provider_error",
    "unknown",
]
"""模型失败的归类。

- ``timeout``：单次请求超时（已按策略重试后仍失败）；
- ``rate_limited``：被限流；
- ``authentication``：凭据被拒——**不重试**，重试解决不了，配置错误必须暴露；
- ``connection``：连不上（DNS、TCP、代理）；
- ``provider_error``：供应商返回了非 2xx 且不属于上面几类；
- ``unknown``：SDK 层的其他异常。
"""


class ModelError(Exception):
    """模型层的基类错误。"""


class ModelConfigurationError(ModelError):
    """模型路由配置不可用：缺凭据、用途档不认识，或客户端根本构造不出来。

    这是**启动期就该暴露**的错误，不是一次运行失败：它不可能靠重试解决。
    """


def classify_model_failure(error: BaseException) -> ModelFailureReason:
    """把一个异常归类成基座的模型失败原因。

    判定顺序有讲究：``APITimeoutError`` 是 ``APIConnectionError`` 的子类，
    先判连接就会把超时误报成网络问题——而这两者对使用者的含义完全不同
    （超时是「这次太慢」，连接失败是「根本连不上」）。
    """
    if isinstance(error, (TimeoutError, APITimeoutError)):
        return "timeout"
    if isinstance(error, RateLimitError):
        return "rate_limited"
    if isinstance(error, AuthenticationError):
        return "authentication"
    if isinstance(error, APIConnectionError):
        return "connection"
    if isinstance(error, APIStatusError):
        return "provider_error"
    return "unknown"
