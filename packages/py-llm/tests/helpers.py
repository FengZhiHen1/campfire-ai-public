"""py-llm 测试共享类、工厂函数。"""

from __future__ import annotations

import httpx
from openai import APIStatusError, APITimeoutError, RateLimitError
from py_llm.llm_contract import LLMClientContract
from py_llm.types import ChatCompletionChunk, Choice, Delta, RetryConfig

# ============================================================================
# 异常工厂函数
# ============================================================================

_REQ = httpx.Request("POST", "http://test.local")


def make_rate_limit_error(status_code: int = 429) -> RateLimitError:
    r = httpx.Response(status_code=status_code, request=_REQ)
    return RateLimitError("rate limit", response=r, body=None)


def make_timeout_error() -> APITimeoutError:
    return APITimeoutError(request=_REQ)


def make_api_status_error(status_code: int) -> APIStatusError:
    r = httpx.Response(status_code=status_code, request=_REQ)
    return APIStatusError(f"error {status_code}", response=r, body=None)


def make_5xx_error(status_code: int = 500) -> APIStatusError:
    return make_api_status_error(status_code)


def make_4xx_error(status_code: int = 400) -> APIStatusError:
    return make_api_status_error(status_code)


# ============================================================================
# ChatCompletionChunk 工厂函数
# ============================================================================


def make_chunk(
    chunk_id: str = "test-1",
    content: str = "",
    role: str | None = None,
    finish_reason: str | None = None,
    model: str = "deepseek-v4-pro",
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[
            Choice(
                delta=Delta(content=content, role=role),
                index=0,
                finish_reason=finish_reason,
            )
        ],
    )


def make_default_chunks() -> list[ChatCompletionChunk]:
    return [
        make_chunk(chunk_id="chunk-1", content="Hello", role="assistant"),
        make_chunk(chunk_id="chunk-2", content=" World"),
        make_chunk(chunk_id="chunk-3", content="", finish_reason="stop"),
    ]


# ============================================================================
# Mock 客户端
# ============================================================================


class NormalClient(LLMClientContract):
    """返回预设 chunk / 文本的 mock 实现。"""

    def __init__(
        self,
        api_key: str = "test-key",
        base_url: str = "http://test",
        retry_config: RetryConfig | None = None,
        stream_chunks: list[ChatCompletionChunk] | None = None,
        completion_result: str = "Hello World",
    ) -> None:
        super().__init__(api_key, base_url, retry_config)
        self._stream_chunks: list[ChatCompletionChunk] = (
            stream_chunks if stream_chunks is not None else make_default_chunks()
        )
        self._completion_result: str = completion_result
        self._stream_error: Exception | None = None
        self._completion_error: Exception | None = None
        self.stream_kwargs: list[dict] = []
        self.completion_kwargs: list[dict] = []

    def inject_stream_error(self, exc: Exception) -> None:
        self._stream_error = exc

    def inject_completion_error(self, exc: Exception) -> None:
        self._completion_error = exc

    async def _do_create_stream(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        response_format: dict[str, str] | None,
    ):
        self.stream_kwargs.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
                "response_format": response_format,
            }
        )
        if self._stream_error:
            raise self._stream_error
        for chunk in self._stream_chunks:
            yield chunk

    async def _do_create_completion(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        response_format: dict[str, str] | None,
    ) -> str:
        self.completion_kwargs.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
                "response_format": response_format,
            }
        )
        if self._completion_error:
            raise self._completion_error
        return self._completion_result


class ErrorSequenceClient(LLMClientContract):
    """按指定次序在特定 attempt 抛出异常的 mock。"""

    def __init__(
        self,
        errors: dict[int, Exception] | None = None,
        stream_chunks: list[ChatCompletionChunk] | None = None,
        completion_result: str = "Hello World",
        retry_config: RetryConfig | None = None,
    ) -> None:
        super().__init__("test-key", "http://test", retry_config)
        self._errors: dict[int, Exception] = errors or {}
        self._stream_chunks: list[ChatCompletionChunk] = (
            stream_chunks if stream_chunks is not None else make_default_chunks()
        )
        self._completion_result: str = completion_result
        self._stream_attempt_count: int = -1
        self._completion_attempt_count: int = -1

    async def _do_create_stream(self, **kwargs):
        self._stream_attempt_count += 1
        exc = self._errors.get(self._stream_attempt_count)
        if exc is not None:
            raise exc
        for chunk in self._stream_chunks:
            yield chunk

    async def _do_create_completion(self, **kwargs):
        self._completion_attempt_count += 1
        exc = self._errors.get(self._completion_attempt_count)
        if exc is not None:
            raise exc
        return self._completion_result

    @property
    def _attempt_count(self) -> int:
        return max(self._stream_attempt_count, self._completion_attempt_count)


class SpyClient(NormalClient):
    """NormalClient 子类，记录后置条件调用。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stream_postcondition_called: bool = False
        self.chat_postcondition_called: bool = False
        self.chat_postcondition_result: str | None = None

    def _validate_stream_postconditions(self) -> None:
        super()._validate_stream_postconditions()
        self.stream_postcondition_called = True

    def _validate_chat_postconditions(self, result: str) -> None:
        super()._validate_chat_postconditions(result)
        self.chat_postcondition_called = True
        self.chat_postcondition_result = result
