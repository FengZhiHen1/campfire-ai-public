"""LLM API client — DeepSeek API via OpenAI SDK with retry.

Uses openai.AsyncOpenAI for streaming chat completion over DeepSeek's
OpenAI-compatible endpoint.

Retry strategy on transient failures:
  - RateLimitError (429), APITimeoutError, APIStatusError (5xx) → retry
  - Max 3 retries, exponential backoff 3s→120s with jitter
  - Exhausted → LLMClientError
"""

from __future__ import annotations

import random
import time
from typing import AsyncGenerator

from openai import APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, Field


# ============================================================================
# Streaming models (OpenAI-compatible SSE chunk representation)
# ============================================================================


class Delta(BaseModel):
    """Streaming delta content — maps to choice.delta in OpenAI streaming format."""

    content: str = Field(default="", description="Text delta for this chunk")
    role: str | None = Field(default=None, description="Role indicator, only present on first chunk")


class Choice(BaseModel):
    """A single streaming choice — maps to choices[0] in OpenAI streaming format."""

    delta: Delta = Field(default_factory=Delta, description="Delta content for this choice")
    index: int = Field(default=0, description="Choice index")
    finish_reason: str | None = Field(default=None, description="Finish reason: stop|length|content_filter|null")


class ChatCompletionChunk(BaseModel):
    """Streaming chat completion chunk — maps to OpenAI streaming response chunk."""

    id: str = Field(default="", description="Chunk ID")
    object: str = Field(default="chat.completion.chunk", description="Object type")
    created: int = Field(default=0, description="Unix timestamp")
    model: str = Field(default="deepseek-v4-pro", description="Model name")
    choices: list[Choice] = Field(default_factory=list, description="Streaming choices")


# ============================================================================
# Exceptions
# ============================================================================


class LLMClientError(Exception):
    """LLM API client error after retries exhausted.

    Wraps underlying OpenAI SDK exceptions after all retry attempts fail.

    Attributes:
        status_code: HTTP status code (if available from APIStatusError).
        original_error: The last underlying exception that caused the failure.
    """

    status_code: int = 503

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
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


# ============================================================================
# LLMClient
# ============================================================================


class LLMClient:
    """DeepSeek API streaming chat client via OpenAI SDK.

    Unified interface for LLM streaming calls with retry, timeout control,
    and circuit breaker awareness.

    Usage:
        client = LLMClient()
        async for chunk in client.async_chat_stream(messages=[...]):
            print(chunk.choices[0].delta.content)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        """Initialize LLM client.

        Args:
            api_key: DeepSeek API key. If None, reads from AppSettings.
            base_url: DeepSeek API base URL, default https://api.deepseek.com.
        """
        if api_key is None:
            try:
                from py_config import config

                api_key = config.DEEPSEEK_API_KEY.get_secret_value()
            except (ImportError, AttributeError):
                api_key = ""  # Degraded mode — tests mock async_chat_stream

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def async_chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-v4-pro",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 90.0,
        max_retries: int = 3,
        response_format: dict | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Stream chat completion from DeepSeek API with retry.

        Uses POST /v1/chat/completions with stream=true via OpenAI SDK.
        Retries on transient failures (429, 5xx, timeout) with exponential backoff.

        Args:
            messages: Chat messages in OpenAI format.
            model: Model identifier, default "deepseek-v4-pro".
            temperature: Sampling temperature, default 0.3.
            max_tokens: Maximum tokens to generate, default 8192.
            timeout: HTTP-level timeout in seconds per chunk, default 90.0.
            max_retries: Maximum retry attempts on transient failures, default 3.
            response_format: Optional response format dict (e.g. {"type": "json_object"}).

        Yields:
            ChatCompletionChunk: Each streaming chunk from the API.

        Raises:
            LLMClientError: After all retries exhausted.
        """
        base_delay: float = 3.0
        max_delay: float = 120.0

        for attempt in range(max_retries + 1):
            try:
                create_kwargs: dict = {
                    "model": model,
                    "messages": messages,  # type: ignore[arg-type]
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                    "timeout": timeout,
                }
                if response_format is not None:
                    create_kwargs["response_format"] = response_format
                stream = await self._client.chat.completions.create(**create_kwargs)
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
                return

            except RateLimitError as exc:
                if attempt == max_retries:
                    raise LLMClientError(
                        message="LLM API 速率限制，已重试耗尽",
                        status_code=429,
                        original_error=exc,
                    ) from exc

            except APITimeoutError as exc:
                if attempt == max_retries:
                    raise LLMClientError(
                        message="LLM API 请求超时，已重试耗尽",
                        status_code=504,
                        original_error=exc,
                    ) from exc

            except APIStatusError as exc:
                if attempt == max_retries:
                    raise LLMClientError(
                        message=f"LLM API 返回错误 (HTTP {exc.status_code})",
                        status_code=exc.status_code,
                        original_error=exc,
                    ) from exc

            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            time.sleep(delay)

    async def async_chat(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-v4-pro",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: float = 5.0,
        max_retries: int = 3,
        response_format: dict | None = None,
    ) -> str:
        """Non-streaming chat completion from DeepSeek API with retry.

        Uses POST /v1/chat/completions with stream=false via OpenAI SDK.
        Retries on transient failures (429, 5xx, timeout) with exponential backoff.

        Args:
            messages: Chat messages in OpenAI format.
            model: Model identifier, default "deepseek-v4-pro".
            temperature: Sampling temperature, default 0.3.
            max_tokens: Maximum tokens to generate, default 8192.
            timeout: HTTP-level timeout in seconds, default 5.0.
            max_retries: Maximum retry attempts on transient failures, default 3.
            response_format: Optional response format dict (e.g. {"type": "json_object"}).

        Returns:
            str: The complete response text from the LLM.

        Raises:
            LLMClientError: After all retries exhausted.
        """
        base_delay: float = 3.0
        max_delay: float = 120.0

        for attempt in range(max_retries + 1):
            try:
                create_kwargs: dict = {
                    "model": model,
                    "messages": messages,  # type: ignore[arg-type]
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "timeout": timeout,
                }
                if response_format is not None:
                    create_kwargs["response_format"] = response_format
                response = await self._client.chat.completions.create(**create_kwargs)
                if response.choices and len(response.choices) > 0:
                    return response.choices[0].message.content or ""
                return ""

            except RateLimitError as exc:
                if attempt == max_retries:
                    raise LLMClientError(
                        message="LLM API 速率限制，已重试耗尽",
                        status_code=429,
                        original_error=exc,
                    ) from exc

            except APITimeoutError as exc:
                if attempt == max_retries:
                    raise LLMClientError(
                        message="LLM API 请求超时，已重试耗尽",
                        status_code=504,
                        original_error=exc,
                    ) from exc

            except APIStatusError as exc:
                if attempt == max_retries:
                    raise LLMClientError(
                        message=f"LLM API 返回错误 (HTTP {exc.status_code})",
                        status_code=exc.status_code,
                        original_error=exc,
                    ) from exc

            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            time.sleep(delay)

        # Should never reach here, but satisfy type checker
        raise LLMClientError(message="LLM API 调用失败，未知错误")
