"""py-llm 数据模型与配置单元测试。

覆盖 Pydantic 模型默认值、序列化、RetryConfig 校验、LLMClientError。
"""

from __future__ import annotations

import pytest
from py_llm.llm_contract import LLMClientError
from py_llm.types import ChatCompletionChunk, Choice, Delta, RetryConfig


class TestDelta:
    """Delta 模型——流式增量内容。"""

    def test_default(self):
        d = Delta()
        assert d.content == ""
        assert d.role is None

    def test_with_content(self):
        d = Delta(content="hello", role="assistant")
        assert d.content == "hello"
        assert d.role == "assistant"


class TestChoice:
    """Choice 模型——单个流式选项。"""

    def test_default(self):
        c = Choice()
        assert c.delta == Delta()
        assert c.index == 0
        assert c.finish_reason is None

    def test_with_finish_reason(self):
        c = Choice(delta=Delta(content="done"), finish_reason="stop")
        assert c.finish_reason == "stop"


class TestChatCompletionChunk:
    """ChatCompletionChunk 模型——流式响应块。"""

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

    def test_round_trip_via_json(self):
        """ChatCompletionChunk 应正确序列化/反序列化。"""
        chunk = ChatCompletionChunk(
            id="test-001",
            model="test-model",
            choices=[Choice(delta=Delta(content="hi"), finish_reason="stop")],
        )
        data = chunk.model_dump()
        restored = ChatCompletionChunk(**data)
        assert restored.id == "test-001"
        assert restored.choices[0].delta.content == "hi"
        assert restored.choices[0].finish_reason == "stop"


class TestLLMClientError:
    """LLMClientError——LLM 客户端错误。"""

    def test_basic(self):
        e = LLMClientError("调用失败")
        assert e.message == "调用失败"
        assert e.status_code == 503
        assert e.original_error is None

    def test_with_original_error(self):
        cause = RuntimeError("网络超时")
        e = LLMClientError("重试耗尽", status_code=504, original_error=cause)
        assert e.original_error is cause
        assert "原因" in str(e)

    def test_str_without_original_error(self):
        err = LLMClientError(message="just fail")
        s = str(err)
        assert "just fail" in s
        assert "原因" not in s


class TestRetryConfig:
    """RetryConfig——指数退避重试配置（不可变）。"""

    def test_default_config_is_valid(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 3.0
        assert cfg.max_delay == 120.0

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            RetryConfig(max_retries=-1)

    def test_zero_max_retries_is_valid(self):
        """max_retries=0 表示不重试，只尝试一次。"""
        cfg = RetryConfig(max_retries=0)
        assert cfg.max_retries == 0

    def test_base_delay_zero_raises(self):
        with pytest.raises(ValueError, match="base_delay must be > 0"):
            RetryConfig(base_delay=0)

    def test_base_delay_negative_raises(self):
        with pytest.raises(ValueError, match="base_delay must be > 0"):
            RetryConfig(base_delay=-1.0)

    def test_max_delay_less_than_base_delay_raises(self):
        with pytest.raises(ValueError, match="max_delay.*must be >= base_delay"):
            RetryConfig(base_delay=10.0, max_delay=5.0)

    def test_max_delay_equal_base_delay_is_valid(self):
        cfg = RetryConfig(base_delay=10.0, max_delay=10.0)
        assert cfg.max_delay == cfg.base_delay

    def test_retry_config_is_immutable(self):
        """RetryConfig 是 frozen dataclass，修改必须失败。"""
        cfg = RetryConfig()
        with pytest.raises(Exception):
            cfg.max_retries = 5  # type: ignore[misc]
