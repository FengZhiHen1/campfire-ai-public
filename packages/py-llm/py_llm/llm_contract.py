"""py-llm 行为契约：LLM API 客户端 ABC 模板方法。

本文件是 py-llm 包的"代码骨架"——定义 LLM 客户端的：
- @final 公共入口（重试循环封装，不可覆写）
- @abstractmethod 钩子（实现者必填的 API 调用逻辑）
- 可扩展的校验器与决策点（基线实现 + super() 叠加）

实现者只能覆写 _do_ 前缀的钩子方法。
调用者只能使用 @final 标记的公共方法。
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import AsyncGenerator, final

from openai import APIStatusError, APITimeoutError, RateLimitError
from py_logger import logger

from py_llm.types import ChatCompletionChunk, RetryConfig


# ============================================================================
# 异常
# ============================================================================


class LLMClientError(Exception):
    """LLM API 客户端错误——重试耗尽后抛出。

    包装底层 OpenAI SDK 异常，提供统一的外部错误界面。

    Attributes:
        message: 错误描述。
        status_code: HTTP 状态码（如有）。
        original_error: 导致失败的最后一个底层异常。
    """

    def __init__(
        self,
        message: str = "LLM API 调用失败，已重试 3 次仍未恢复",
        status_code: int = 503,
        original_error: Exception | None = None,
    ) -> None:
        self.message: str = message
        self.status_code: int = status_code
        self.original_error: Exception | None = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message}（原因: {self.original_error}）"
        return self.message


# ============================================================================
# 契约 ABC
# ============================================================================


class LLMClientContract(ABC):
    """LLM API 客户端契约。

    模板方法模式：封装重试循环与错误映射，
    实现者只需填写 _do_create_stream 和 _do_create_completion 两个钩子。

    用法示例:
        class DeepSeekClient(LLMClientContract):
            async def _do_create_stream(self, **kwargs):
                stream = await self._client.chat.completions.create(**kwargs, stream=True)
                async for chunk in stream:
                    yield self._transform(chunk)

            async def _do_create_completion(self, **kwargs):
                response = await self._client.chat.completions.create(**kwargs, stream=False)
                return response.choices[0].message.content or ""
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._retry_config = retry_config or RetryConfig()

    # ========================================================================
    # @final 公共入口 —— 唯一外部调用接口
    # ========================================================================

    @final
    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-v4-pro",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 310.0,
        response_format: dict[str, str] | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """流式聊天补全——带指数退避重试。

        前置校验 → 重试循环（调用钩子 → 错误判定） → yield chunks。

        Args:
            messages: OpenAI 格式的对话消息列表。
            model: 模型标识，默认 "deepseek-v4-pro"。
            temperature: 采样温度 [0.0, 2.0]，默认 0.3。
            max_tokens: 最大生成 token 数，默认 8192。
            timeout: HTTP 超时秒数，默认 310.0。
            response_format: 可选的响应格式约束。

        Yields:
            ChatCompletionChunk: 流式响应的每个 chunk。

        Raises:
            LLMClientError: 重试耗尽后抛出。
            ValueError: 前置校验失败。
        """
        self._validate_preconditions(messages, model, temperature, max_tokens)
        cfg = self._retry_config
        for attempt in range(cfg.max_retries + 1):
            try:
                async for chunk in self._do_create_stream(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    response_format=response_format,
                ):
                    yield chunk
                self._validate_stream_postconditions()
                return
            except Exception as exc:
                if not self._should_retry(exc, attempt, cfg.max_retries):
                    self._log_exhausted(exc, cfg.max_retries)
                    raise self._map_error(exc) from exc
                delay = self._calculate_delay(attempt, cfg)
                self._log_retry(attempt, exc, delay, cfg.max_retries)
                await asyncio.sleep(delay)
        # 理论上不可达——最后一次 attempt 必定触发 _should_retry=False
        raise self._map_error(RuntimeError("重试循环异常退出"))

    @final
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-v4-pro",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 5.0,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """非流式聊天补全——带指数退避重试。

        前置校验 → 重试循环（调用钩子 → 错误判定） → 返回完整文本。

        Args:
            messages: OpenAI 格式的对话消息列表。
            model: 模型标识，默认 "deepseek-v4-pro"。
            temperature: 采样温度 [0.0, 2.0]，默认 0.3。
            max_tokens: 最大生成 token 数，默认 8192。
            timeout: HTTP 超时秒数，默认 5.0。
            response_format: 可选的响应格式约束。

        Returns:
            str: LLM 返回的完整文本。

        Raises:
            LLMClientError: 重试耗尽后抛出。
            ValueError: 前置校验失败。
        """
        self._validate_preconditions(messages, model, temperature, max_tokens)
        cfg = self._retry_config
        for attempt in range(cfg.max_retries + 1):
            try:
                result = await self._do_create_completion(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    response_format=response_format,
                )
                self._validate_chat_postconditions(result)
                return result
            except Exception as exc:
                if not self._should_retry(exc, attempt, cfg.max_retries):
                    self._log_exhausted(exc, cfg.max_retries)
                    raise self._map_error(exc) from exc
                delay = self._calculate_delay(attempt, cfg)
                self._log_retry(attempt, exc, delay, cfg.max_retries)
                await asyncio.sleep(delay)
        raise self._map_error(RuntimeError("重试循环异常退出"))

    # ========================================================================
    # @abstractmethod 钩子 —— 实现者必填
    # ========================================================================

    @abstractmethod
    async def _do_create_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        response_format: dict[str, str] | None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """实现者：执行实际的流式 API 调用并 yield 转换后的 chunk。

        不需要关心重试——公共入口已封装。只需：
        1. 调用底层 API（如 OpenAI SDK stream=True）
        2. 将每个原始 chunk 转换为 ChatCompletionChunk 并 yield
        """
        if False:  # 帮助 mypy 识别为异步生成器
            yield ChatCompletionChunk()

    @abstractmethod
    async def _do_create_completion(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        response_format: dict[str, str] | None,
    ) -> str:
        """实现者：执行实际的非流式 API 调用并返回文本。

        不需要关心重试——公共入口已封装。只需：
        1. 调用底层 API（如 OpenAI SDK stream=False）
        2. 从响应中提取文本内容并返回
        """
        ...

    # ========================================================================
    # 校验器 —— 模板提供基线校验，子类通过 super() 叠加业务级校验
    # ========================================================================

    def _validate_preconditions(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        """基线前置校验：消息非空、参数范围合法。

        子类可覆写并通过 super() 叠加业务级校验（如消息长度限制、特定模型约束等）。
        """
        if not messages:
            raise ValueError("messages must not be empty")
        if not model:
            raise ValueError("model must not be empty")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError(
                f"temperature must be in [0.0, 2.0], got {temperature}"
            )
        if max_tokens < 1:
            raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")

    # ========================================================================
    # 后置校验器 —— 模板提供基线校验，子类通过 super() 叠加
    # ========================================================================

    def _validate_stream_postconditions(self) -> None:
        """流式后置校验：流正常结束，无异常中断。

        子类可覆写并通过 super() 叠加（如校验至少 yield 了若干 chunk）。
        """

    def _validate_chat_postconditions(self, result: str) -> None:
        """非流式后置校验：返回值非 None、类型正确。

        子类可覆写并通过 super() 叠加业务级校验（如最小长度、格式约束等）。
        """
        if result is None:  # 防御性检查——str 类型保证不应为 None
            raise RuntimeError(f"{self.__class__.__name__}._do_create_completion 返回了 None")

    # ========================================================================
    # 日志 —— 可选依赖 py-logger，不可用时静默降级
    # ========================================================================

    @staticmethod
    def _log_retry(attempt: int, exc: Exception, delay: float, max_retries: int) -> None:
        """记录重试事件。"""
        logger.warning(
            service="py-llm",
            message=f"LLM API 调用失败，第 {attempt + 1}/{max_retries + 1} 次重试",
            op_type="retry",
            extra={
                "attempt": attempt + 1,
                "max_attempts": max_retries + 1,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:200],
                "delay_seconds": round(delay, 3),
            },
        )

    @staticmethod
    def _log_exhausted(exc: Exception, max_retries: int) -> None:
        """记录重试耗尽事件。"""
        logger.error(
            service="py-llm",
            message=f"LLM API 调用失败，{max_retries + 1} 次尝试全部失败",
            op_type="retry_exhausted",
            extra={
                "max_attempts": max_retries + 1,
                "final_error_type": type(exc).__name__,
                "final_error_message": str(exc)[:200],
            },
        )

    # ========================================================================
    # 决策扩展点 —— 模板提供基线实现，子类可覆写
    # ========================================================================

    def _should_retry(self, exc: Exception, attempt: int, max_retries: int) -> bool:
        """判定异常是否可重试。

        基线策略：RateLimitError(429)、APITimeoutError、APIStatusError(5xx)
        可重试；其余异常直接抛出。最后一次 attempt 不可重试。

        子类可覆写以添加/移除可重试类型。
        """
        if attempt >= max_retries:
            return False
        if isinstance(exc, RateLimitError):
            return True
        if isinstance(exc, APITimeoutError):
            return True
        if isinstance(exc, APIStatusError):
            return exc.status_code >= 500
        return False

    @staticmethod
    def _calculate_delay(attempt: int, cfg: RetryConfig) -> float:
        """计算第 attempt 次重试的等待延迟（指数退避 + 随机抖动）。"""
        delay: float = cfg.base_delay * (2 ** attempt) + random.uniform(0, 1)
        return min(delay, cfg.max_delay)

    def _map_error(self, exc: Exception) -> LLMClientError:
        """将底层异常映射为 LLMClientError。

        基线实现：按异常类型生成对应的中文错误消息与 HTTP 状态码。
        子类可覆写以自定义错误消息或添加额外上下文。
        """
        if isinstance(exc, RateLimitError):
            return LLMClientError(
                message="LLM API 速率限制，已重试耗尽",
                status_code=429,
                original_error=exc,
            )
        if isinstance(exc, APITimeoutError):
            return LLMClientError(
                message="LLM API 请求超时，已重试耗尽",
                status_code=504,
                original_error=exc,
            )
        if isinstance(exc, APIStatusError):
            return LLMClientError(
                message=f"LLM API 返回错误 (HTTP {exc.status_code})",
                status_code=exc.status_code,
                original_error=exc,
            )
        return LLMClientError(
            message="LLM API 调用失败，已重试耗尽",
            original_error=exc,
        )
