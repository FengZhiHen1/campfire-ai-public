"""LLM API client — DeepSeek API streaming chat client base class.

Provides LLMClient class with async_chat_stream() method signature.
Implementation is a stub that must be filled with real httpx.AsyncClient-based
DeepSeek API calls before production use.

Current stub: yields a single empty chunk. Plug in real API call by
replacing the async_chat_stream method body with httpx.AsyncClient streaming.

The class structure follows the unified client pattern defined in
project-structure.md: single point for API key injection, connection pooling,
retry logic, and circuit breaker.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

from pydantic import BaseModel, Field


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
    model: str = Field(default="deepseek-chat", description="Model name")
    choices: list[Choice] = Field(default_factory=list, description="Streaming choices")


class LLMClient:
    """DeepSeek API streaming chat client.

    Unified interface for LLM streaming calls with timeout control,
    connection pooling, retry mechanism, and circuit breaker.

    Usage:
        client = LLMClient(api_key="sk-xxx")
        async for chunk in client.async_chat_stream(messages=[...]):
            print(chunk.choices[0].delta.content)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Initialize LLM client.

        Args:
            api_key: DeepSeek API key. If None, reads from AppSettings.
            base_url: DeepSeek API base URL. If None, reads from AppSettings.
        """
        self._api_key = api_key
        self._base_url = base_url

    async def async_chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-chat",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: float = 15.0,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Stream chat completion from DeepSeek API.

        Uses POST /v1/chat/completions with stream=true.
        Each yielded chunk corresponds to one SSE "data:" line from the API.

        Args:
            messages: Chat messages in OpenAI format.
                      Format: [{"role": "system"|"user"|"assistant", "content": "..."}].
            model: Model identifier, default "deepseek-chat".
            temperature: Sampling temperature. Constrained to <= 0.3 per intent doc.
            max_tokens: Maximum tokens to generate, default 4096.
            timeout: Overall request timeout in seconds, default 15.0.

        Yields:
            ChatCompletionChunk: Each streaming chunk from the API.

        Raises:
            LLMClientError: Wraps httpx.HTTPStatusError for non-200 responses,
                           httpx.ConnectTimeout for connection timeouts, and
                           JSON decode errors for malformed API responses.
        """
        # Stub: replace with httpx.AsyncClient streaming implementation
        # Real implementation pattern:
        #
        # async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        #     async with client.stream(
        #         "POST",
        #         f"{base_url}/v1/chat/completions",
        #         json={
        #             "model": model,
        #             "messages": messages,
        #             "temperature": temperature,
        #             "max_tokens": max_tokens,
        #             "stream": True,
        #         },
        #         headers={"Authorization": f"Bearer {api_key}"},
        #     ) as response:
        #         response.raise_for_status()
        #         async for line in response.aiter_lines():
        #             if line.startswith("data: "):
        #                 data = line[6:]
        #                 if data.strip() == "[DONE]":
        #                     return
        #                 chunk = ChatCompletionChunk.model_validate_json(data)
        #                 yield chunk
        #
        yield ChatCompletionChunk(choices=[Choice(delta=Delta(content=""))])
