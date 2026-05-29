"""LLM API 客户端 —— 通过 OpenAI SDK 调用 DeepSeek API。

LLMClientContract 的具体实现，适配 DeepSeek 的 OpenAI 兼容端点。
重试逻辑和错误映射由契约 ABC 继承而来——本文件仅实现 API 调用钩子。
"""

from __future__ import annotations

from typing import AsyncGenerator

from openai import AsyncOpenAI

from py_llm.llm_contract import LLMClientContract, LLMClientError  # noqa: F401  由 __init__.py 重导出
from py_llm.types import ChatCompletionChunk, Choice, Delta, RetryConfig  # noqa: F401  由 __init__.py 重导出


# ============================================================================
# DeepSeekLLMClient —— LLMClientContract 的具体实现
# ============================================================================


class DeepSeekLLMClient(LLMClientContract):
    """DeepSeek API 流式/非流式聊天客户端。

    实现 LLMClientContract 定义的两个抽象钩子：_do_create_stream 和 _do_create_completion。
    所有重试循环、指数退避和错误映射逻辑由契约的 @final 公共入口（chat_stream / chat）处理。

    用法:
        client = DeepSeekLLMClient()
        async for chunk in client.async_chat_stream(messages=[...]):
            print(chunk.choices[0].delta.content)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        retry_config: RetryConfig | None = None,
    ) -> None:
        """初始化 DeepSeek 客户端。

        Args:
            api_key: DeepSeek API 密钥。为 None 时自动从 py_config 的
                     AppSettings 中读取（DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL）。
            base_url: DeepSeek API 基地址。当 api_key 为 None 且 py_config
                      可用时，会被 AppSettings 中的值覆盖。
            retry_config: 可选的重试行为配置。
        """
        if api_key is None:
            try:
                from py_config import get_settings

                settings = get_settings()
                resolved_api_key = settings.DEEPSEEK_API_KEY.get_secret_value()
                resolved_base_url = (
                    str(settings.DEEPSEEK_BASE_URL).rstrip("/v1").rstrip("/")
                )
            except (ImportError, AttributeError):
                resolved_api_key = ""  # 降级模式——测试中可 mock async_chat_stream
                resolved_base_url = base_url.rstrip("/")
        else:
            resolved_api_key = api_key
            resolved_base_url = base_url.rstrip("/")

        super().__init__(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            retry_config=retry_config,
        )
        self._client = AsyncOpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
        )

    # ========================================================================
    # 抽象钩子实现
    # ========================================================================

    async def _do_create_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        response_format: dict[str, str] | None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """执行流式 API 调用并 yield 转换后的 chunk。

        由契约的 @final chat_stream() 在其重试循环中调用。
        """
        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "timeout": timeout,
        }
        if response_format is not None:
            create_kwargs["response_format"] = response_format

        stream = await self._client.chat.completions.create(**create_kwargs)  # type: ignore[call-overload]
        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                choice = chunk.choices[0]
                yield ChatCompletionChunk(
                    id=chunk.id,
                    object=chunk.object or "chat.completion.chunk",
                    created=chunk.created,
                    model=chunk.model,
                    choices=[
                        Choice(
                            delta=Delta(
                                content=choice.delta.content or "",
                                role=choice.delta.role,
                            ),
                            index=choice.index,
                            finish_reason=choice.finish_reason,
                        )
                    ],
                )

    async def _do_create_completion(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        response_format: dict[str, str] | None,
    ) -> str:
        """执行非流式 API 调用并返回响应文本。

        由契约的 @final chat() 在其重试循环中调用。
        """
        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "timeout": timeout,
        }
        if response_format is not None:
            create_kwargs["response_format"] = response_format

        response = await self._client.chat.completions.create(**create_kwargs)  # type: ignore[call-overload]
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        return ""

    # ========================================================================
    # 向后兼容包装（旧 API: async_chat_stream / async_chat）
    # ========================================================================

    async def async_chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-v4-pro",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 310.0,
        max_retries: int = 3,
        response_format: dict[str, str] | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """chat_stream() 的向后兼容别名。

        委托给契约的 @final chat_stream()。max_retries 参数仅为调用端兼容而保留，
        实际重试行为由构造时传入的 RetryConfig 统一控制。
        """
        async for chunk in self.chat_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            response_format=response_format,
        ):
            yield chunk

    async def async_chat(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-v4-pro",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 5.0,
        max_retries: int = 3,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """chat() 的向后兼容别名。

        委托给契约的 @final chat()。max_retries 参数仅为调用端兼容而保留。
        """
        return await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            response_format=response_format,
        )


# 向后兼容别名
LLMClient = DeepSeekLLMClient
