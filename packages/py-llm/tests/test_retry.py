"""重试逻辑测试 —— _should_retry / _calculate_delay / _map_error / 重试循环集成。

覆盖:
- _should_retry: 可重试/不可重试异常分类、最后 attempt 边界
- _calculate_delay: 指数退避范围与上限
- _map_error: 异常 → LLMClientError 映射
- chat_stream / chat 重试循环行为
"""

from __future__ import annotations

import pytest

from py_llm.llm_contract import LLMClientContract, LLMClientError
from py_llm.types import RetryConfig
from helpers import (
    ErrorSequenceClient,
    NormalClient,
    make_4xx_error,
    make_5xx_error,
    make_rate_limit_error,
    make_timeout_error,
)

VALID_MESSAGES = [{"role": "user", "content": "Hi"}]


# ============================================================================
# _should_retry —— 可重试性判定
# ============================================================================


class TestShouldRetry:
    """直接测试 _should_retry 的分类逻辑。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self._client = NormalClient()
        self._max = 3

    # -- 可重试异常 --

    def test_rate_limit_error_is_retryable(self):
        """RateLimitError 应可重试。"""
        assert self._client._should_retry(make_rate_limit_error(429), 0, self._max) is True

    def test_timeout_error_is_retryable(self):
        """APITimeoutError 应可重试。"""
        assert self._client._should_retry(make_timeout_error(), 0, self._max) is True

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_5xx_errors_are_retryable(self, status):
        """5xx 错误应可重试。"""
        assert self._client._should_retry(make_5xx_error(status), 0, self._max) is True

    # -- 不可重试异常 --

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_4xx_errors_are_not_retryable(self, status):
        """4xx 错误不应重试。"""
        assert self._client._should_retry(make_4xx_error(status), 0, self._max) is False

    def test_generic_exception_is_not_retryable(self):
        """通用异常不应重试。"""
        assert self._client._should_retry(RuntimeError("broke"), 0, self._max) is False

    def test_value_error_is_not_retryable(self):
        """ValueError 不应重试。"""
        assert self._client._should_retry(ValueError("bad"), 0, self._max) is False

    # -- 最后一次 attempt 边界 --

    def test_rate_limit_on_last_attempt_is_not_retryable(self):
        """即使可重试异常，在最后一次 attempt 也不可重试。"""
        assert self._client._should_retry(make_rate_limit_error(429), 3, self._max) is False

    def test_timeout_on_last_attempt_is_not_retryable(self):
        assert self._client._should_retry(make_timeout_error(), 3, self._max) is False

    def test_500_on_last_attempt_is_not_retryable(self):
        assert self._client._should_retry(make_5xx_error(500), 3, self._max) is False

    def test_attempt_exceeds_max_retries(self):
        """attempt > max_retries 也应返回 False。"""
        assert self._client._should_retry(make_rate_limit_error(429), 5, self._max) is False

    def test_with_zero_max_retries_nothing_is_retryable(self):
        """max_retries=0 时任何异常都不可重试。"""
        assert self._client._should_retry(make_rate_limit_error(429), 0, 0) is False


# ============================================================================
# _calculate_delay —— 指数退避
# ============================================================================


class TestCalculateDelay:
    """测试 _calculate_delay 返回预期范围内的值。"""

    def test_first_attempt_delay_range(self):
        """第 0 次重试延迟应在 [base, base+1] 范围内。"""
        cfg = RetryConfig(base_delay=3.0, max_delay=120.0)
        for _ in range(20):
            delay = LLMClientContract._calculate_delay(0, cfg)
            assert 3.0 <= delay <= 4.0, f"delay={delay} 超出 [3.0, 4.0]"

    def test_second_attempt_delay_range(self):
        """第 1 次重试延迟应在 [base*2, base*2+1] 范围内。"""
        cfg = RetryConfig(base_delay=3.0, max_delay=120.0)
        for _ in range(20):
            delay = LLMClientContract._calculate_delay(1, cfg)
            assert 6.0 <= delay <= 7.0, f"delay={delay} 超出 [6.0, 7.0]"

    def test_capped_at_max_delay(self):
        """当 base*2^attempt 超过 max_delay 时，延迟应被截断。"""
        cfg = RetryConfig(base_delay=10.0, max_delay=15.0)
        for _ in range(20):
            delay = LLMClientContract._calculate_delay(5, cfg)  # 10*32=320, 应截断到 15
            assert delay <= 15.0, f"delay={delay} 超过 max_delay=15.0"

    def test_delay_increases_with_attempt(self):
        """更高 attempt 应产生严格更大的延迟（区间不重叠）。"""
        cfg = RetryConfig(base_delay=5.0, max_delay=200.0)
        # attempt=0: [5.0, 6.0], attempt=3: [40.0, 41.0] — 区间无交集
        delays_0 = [LLMClientContract._calculate_delay(0, cfg) for _ in range(100)]
        delays_3 = [LLMClientContract._calculate_delay(3, cfg) for _ in range(100)]
        assert min(delays_3) > max(delays_0)


# ============================================================================
# _map_error —— 异常映射
# ============================================================================


class TestMapError:
    """测试 _map_error 产生正确的 LLMClientError。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self._client = NormalClient()

    def test_rate_limit_error_maps_to_429(self):
        """RateLimitError 应映射为 status 429，含"速率限制"消息。"""
        exc = make_rate_limit_error(429)
        mapped = self._client._map_error(exc)
        assert isinstance(mapped, LLMClientError)
        assert mapped.status_code == 429
        assert "速率限制" in mapped.message
        assert mapped.original_error is exc

    def test_timeout_error_maps_to_504(self):
        """APITimeoutError 应映射为 status 504，含"超时"消息。"""
        exc = make_timeout_error()
        mapped = self._client._map_error(exc)
        assert mapped.status_code == 504
        assert "超时" in mapped.message

    def test_500_error_maps_to_original_status(self):
        """APIStatusError 应保留原始状态码。"""
        mapped = self._client._map_error(make_5xx_error(500))
        assert mapped.status_code == 500
        assert "HTTP 500" in mapped.message

    def test_400_error_maps_to_original_status(self):
        """不可重试异常的原始状态码也应保留。"""
        mapped = self._client._map_error(make_4xx_error(400))
        assert mapped.status_code == 400
        assert "HTTP 400" in mapped.message

    def test_generic_exception_gets_default_status(self):
        """未识别异常应使用默认 status 503 和默认消息。"""
        mapped = self._client._map_error(RuntimeError("broke"))
        assert mapped.status_code == 503
        assert "重试耗尽" in mapped.message
        assert mapped.original_error is not None

    def test_mapped_error_includes_original_error(self):
        """映射后的错误应保留原始异常引用。"""
        exc = make_timeout_error()
        mapped = self._client._map_error(exc)
        assert mapped.original_error is exc


# ============================================================================
# chat_stream 重试循环集成测试
# ============================================================================


@pytest.mark.asyncio
async def test_chat_stream_retries_on_rate_limit_and_succeeds():
    """attempt 0 出 RateLimitError，attempt 1 成功——应 yield chunk。"""
    client = ErrorSequenceClient(
        errors={0: make_rate_limit_error(429)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(chunks) == 3
    assert client._attempt_count >= 1  # 至少发生了一次重试


@pytest.mark.asyncio
async def test_chat_stream_retries_on_timeout_and_succeeds():
    """attempt 0 出 APITimeoutError，attempt 1 成功。"""
    client = ErrorSequenceClient(
        errors={0: make_timeout_error()},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_chat_stream_retries_on_5xx_and_succeeds():
    """attempt 0 出 APIStatusError(500)，attempt 1 成功。"""
    client = ErrorSequenceClient(
        errors={0: make_5xx_error(500)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_chat_stream_multiple_retries_then_success():
    """attempt 0, 1 各出异常，attempt 2 成功。"""
    client = ErrorSequenceClient(
        errors={0: make_rate_limit_error(429), 1: make_timeout_error()},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(chunks) == 3
    assert client._attempt_count == 2  # 成功于 attempt 2


@pytest.mark.asyncio
async def test_chat_stream_non_retryable_error_raised_immediately():
    """4xx 错误不应重试，直接抛出 LLMClientError。"""
    client = ErrorSequenceClient(
        errors={0: make_4xx_error(400)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    with pytest.raises(LLMClientError) as exc_info:
        async for _ in client.chat_stream(messages=VALID_MESSAGES):
            pass
    assert exc_info.value.status_code == 400
    assert client._attempt_count == 0  # 只尝试一次，无重试


@pytest.mark.asyncio
async def test_chat_stream_all_retries_exhausted():
    """全部 4 次尝试均失败——最终抛出 LLMClientError。"""
    client = ErrorSequenceClient(
        errors={i: make_rate_limit_error(429) for i in range(4)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    with pytest.raises(LLMClientError) as exc_info:
        async for _ in client.chat_stream(messages=VALID_MESSAGES):
            pass
    assert exc_info.value.status_code == 429
    assert client._attempt_count == 3


# ============================================================================
# chat（非流式）重试循环集成测试
# ============================================================================


@pytest.mark.asyncio
async def test_chat_retries_on_rate_limit_and_succeeds():
    """attempt 0 出 RateLimitError，attempt 1 成功。"""
    client = ErrorSequenceClient(
        errors={0: make_rate_limit_error(429)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    result = await client.chat(messages=VALID_MESSAGES)
    assert result == "Hello World"
    assert client._attempt_count >= 1


@pytest.mark.asyncio
async def test_chat_retries_on_timeout_and_succeeds():
    """attempt 0 出 APITimeoutError，attempt 1 成功。"""
    client = ErrorSequenceClient(
        errors={0: make_timeout_error()},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    result = await client.chat(messages=VALID_MESSAGES)
    assert result == "Hello World"


@pytest.mark.asyncio
async def test_chat_retries_on_5xx_and_succeeds():
    """attempt 0 出 APIStatusError(500)，attempt 1 成功。"""
    client = ErrorSequenceClient(
        errors={0: make_5xx_error(500)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    result = await client.chat(messages=VALID_MESSAGES)
    assert result == "Hello World"


@pytest.mark.asyncio
async def test_chat_non_retryable_error_raised_immediately():
    """4xx 错误不应重试。"""
    client = ErrorSequenceClient(
        errors={0: make_4xx_error(401)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    with pytest.raises(LLMClientError) as exc_info:
        await client.chat(messages=VALID_MESSAGES)
    assert exc_info.value.status_code == 401
    assert client._attempt_count == 0


@pytest.mark.asyncio
async def test_chat_all_retries_exhausted():
    """全部尝试均失败——最终抛出 LLMClientError。"""
    client = ErrorSequenceClient(
        errors={i: make_5xx_error(503) for i in range(4)},
        retry_config=RetryConfig(max_retries=3, base_delay=0.001),
    )
    with pytest.raises(LLMClientError) as exc_info:
        await client.chat(messages=VALID_MESSAGES)
    assert exc_info.value.status_code == 503
    assert client._attempt_count == 3


# ============================================================================
# max_retries=0 —— 不重试
# ============================================================================


@pytest.mark.asyncio
async def test_max_retries_zero_chat_stream_immediate_failure():
    """max_retries=0 时首次失败应直接抛出。"""
    client = ErrorSequenceClient(
        errors={0: make_rate_limit_error(429)},
        retry_config=RetryConfig(max_retries=0, base_delay=0.001),
    )
    with pytest.raises(LLMClientError):
        async for _ in client.chat_stream(messages=VALID_MESSAGES):
            pass


@pytest.mark.asyncio
async def test_max_retries_zero_chat_immediate_failure():
    """非流式路径 max_retries=0 时首次失败应直接抛出。"""
    client = ErrorSequenceClient(
        errors={0: make_timeout_error()},
        retry_config=RetryConfig(max_retries=0, base_delay=0.001),
    )
    with pytest.raises(LLMClientError):
        await client.chat(messages=VALID_MESSAGES)


# ============================================================================
# 非 OpenAI 异常不重试
# ============================================================================


@pytest.mark.asyncio
async def test_chat_stream_value_error_not_retried():
    """钩子抛出的 ValueError 不应被重试——映射为 LLMClientError。"""
    client = NormalClient()
    client.inject_stream_error(ValueError("数据损坏"))
    with pytest.raises(LLMClientError):
        async for _ in client.chat_stream(messages=VALID_MESSAGES):
            pass


@pytest.mark.asyncio
async def test_chat_runtime_error_not_retried():
    """钩子抛出的 RuntimeError 不应被重试——映射为 LLMClientError。"""
    client = NormalClient()
    client.inject_completion_error(RuntimeError("非预期状态"))
    with pytest.raises(LLMClientError):
        await client.chat(messages=VALID_MESSAGES)
