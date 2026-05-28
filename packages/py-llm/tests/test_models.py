"""LLM API Client — 模型与异常单元测试。
"""

from __future__ import annotations

from py_llm.client import (
    ChatCompletionChunk,
    Choice,
    Delta,
    LLMClientError,
)


class TestDelta:
    def test_default(self):
        d = Delta()
        assert d.content == ""
        assert d.role is None

    def test_with_content(self):
        d = Delta(content="hello", role="assistant")
        assert d.content == "hello"


class TestChoice:
    def test_default(self):
        c = Choice()
        assert c.index == 0
        assert c.finish_reason is None

    def test_with_finish_reason(self):
        c = Choice(delta=Delta(content="done"), finish_reason="stop")
        assert c.finish_reason == "stop"


class TestChatCompletionChunk:
    def test_default(self):
        chunk = ChatCompletionChunk()
        assert chunk.object == "chat.completion.chunk"
        assert chunk.model == "deepseek-v4-pro"
        assert chunk.choices == []

    def test_with_choices(self):
        chunk = ChatCompletionChunk(
            id="chunk-1",
            created=1234567890,
            choices=[Choice(delta=Delta(content="hello"))],
        )
        assert chunk.id == "chunk-1"
        assert len(chunk.choices) == 1


class TestLLMClientError:
    def test_basic(self):
        e = LLMClientError("调用失败")
        assert e.message == "调用失败"
        assert e.status_code == 503
        assert e.original_error is None

    def test_with_original_error(self):
        cause = RuntimeError("网络超时")
        e = LLMClientError("重试耗尽", status_code=504, original_error=cause)
        assert e.original_error is cause
        assert "caused by" in str(e)
