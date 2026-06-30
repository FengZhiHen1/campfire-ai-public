"""边界条件与集成路径测试。

覆盖:
- 空内容 chunk、零 chunk 流
- 大输入（150 条消息）
- response_format 透传
- 默认参数验证
- 后置条件调用
- 并发访问
- base_url 尾部斜杠处理
"""

from __future__ import annotations

import asyncio

import pytest
from helpers import (
    NormalClient,
    SpyClient,
    make_chunk,
    make_rate_limit_error,
)
from py_llm.llm_contract import LLMClientError

VALID_MESSAGES = [{"role": "user", "content": "Hi"}]


# ============================================================================
# 空内容 / 零 chunk
# ============================================================================


@pytest.mark.asyncio
async def test_all_empty_content_chunks():
    """全部 chunk 内容为空的流不应崩溃。"""
    chunks = [
        make_chunk(chunk_id="e1", content=""),
        make_chunk(chunk_id="e2", content=""),
        make_chunk(chunk_id="e3", content="", finish_reason="stop"),
    ]
    client = NormalClient(stream_chunks=chunks)
    results = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(results) == 3
    for r in results:
        assert r.choices[0].delta.content == ""


@pytest.mark.asyncio
async def test_single_empty_chunk():
    """只 yield 一个空 chunk 的流应正常完成。"""
    chunks = [make_chunk(chunk_id="only", content="", finish_reason="stop")]
    client = NormalClient(stream_chunks=chunks)
    results = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(results) == 1


@pytest.mark.asyncio
async def test_stream_yields_zero_chunks():
    """流式钩子不 yield 任何内容应正常完成，不报错。"""
    client = NormalClient(stream_chunks=[])
    results = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(results) == 0


# ============================================================================
# 大输入
# ============================================================================


@pytest.mark.asyncio
async def test_many_messages():
    """100+ 条消息应被接受并正常处理。"""
    many = [{"role": "user", "content": f"msg {i}"} for i in range(150)]
    client = NormalClient()
    results = [c async for c in client.chat_stream(messages=many)]
    assert len(results) > 0


# ============================================================================
# response_format 透传
# ============================================================================


@pytest.mark.asyncio
async def test_response_format_passed_to_stream_hook():
    """response_format 参数应到达 _do_create_stream。"""
    client = NormalClient()
    fmt = {"type": "json_object"}
    async for _ in client.chat_stream(messages=VALID_MESSAGES, response_format=fmt):
        pass
    assert len(client.stream_kwargs) == 1
    assert client.stream_kwargs[0]["response_format"] == fmt


@pytest.mark.asyncio
async def test_response_format_passed_to_chat_hook():
    """response_format 参数应到达 _do_create_completion。"""
    client = NormalClient()
    fmt = {"type": "json_object"}
    await client.chat(messages=VALID_MESSAGES, response_format=fmt)
    assert len(client.completion_kwargs) == 1
    assert client.completion_kwargs[0]["response_format"] == fmt


@pytest.mark.asyncio
async def test_response_format_none_by_default_stream():
    """未提供 response_format 时应传递 None。"""
    client = NormalClient()
    async for _ in client.chat_stream(messages=VALID_MESSAGES):
        pass
    assert client.stream_kwargs[0]["response_format"] is None


@pytest.mark.asyncio
async def test_response_format_none_by_default_chat():
    """非流式路径未提供 response_format 时应传递 None。"""
    client = NormalClient()
    await client.chat(messages=VALID_MESSAGES)
    assert client.completion_kwargs[0]["response_format"] is None


# ============================================================================
# 默认参数验证
# ============================================================================


@pytest.mark.asyncio
async def test_default_parameters_passed_to_stream_hook():
    """验证所有默认参数正确传至 _do_create_stream。"""
    client = NormalClient()
    async for _ in client.chat_stream(messages=VALID_MESSAGES):
        pass
    kw = client.stream_kwargs[0]
    assert kw["model"] == "deepseek-v4-pro"
    assert kw["temperature"] == 0.3
    assert kw["max_tokens"] == 8192
    assert kw["timeout"] == 310.0


@pytest.mark.asyncio
async def test_default_parameters_passed_to_chat_hook():
    """验证所有默认参数正确传至 _do_create_completion。"""
    client = NormalClient()
    await client.chat(messages=VALID_MESSAGES)
    kw = client.completion_kwargs[0]
    assert kw["model"] == "deepseek-v4-pro"
    assert kw["temperature"] == 0.3
    assert kw["max_tokens"] == 8192
    assert kw["timeout"] == 5.0  # chat 默认 timeout 是 5.0，非 310.0


# ============================================================================
# stream 与 chat 的 timeout 默认值不同（回归检查）
# ============================================================================


@pytest.mark.asyncio
async def test_stream_timeout_is_310_default():
    """流式默认 timeout 应为 310.0。"""
    client = NormalClient()
    async for _ in client.chat_stream(messages=VALID_MESSAGES):
        pass
    assert client.stream_kwargs[0]["timeout"] == 310.0


@pytest.mark.asyncio
async def test_chat_timeout_is_5_default():
    """非流式默认 timeout 应为 5.0。"""
    client = NormalClient()
    await client.chat(messages=VALID_MESSAGES)
    assert client.completion_kwargs[0]["timeout"] == 5.0


# ============================================================================
# 后置条件验证
# ============================================================================


@pytest.mark.asyncio
async def test_stream_postcondition_is_called():
    """流式完成后应调用 _validate_stream_postconditions。"""
    client = SpyClient()
    async for _ in client.chat_stream(messages=VALID_MESSAGES):
        pass
    assert client.stream_postcondition_called is True


@pytest.mark.asyncio
async def test_chat_postcondition_is_called():
    """非流式完成后应调用 _validate_chat_postconditions。"""
    client = SpyClient()
    await client.chat(messages=VALID_MESSAGES)
    assert client.chat_postcondition_called is True


@pytest.mark.asyncio
async def test_chat_postcondition_receives_result():
    """_validate_chat_postconditions 应收到返回结果。"""
    client = SpyClient(completion_result="测试输出")
    await client.chat(messages=VALID_MESSAGES)
    assert client.chat_postcondition_result == "测试输出"


@pytest.mark.asyncio
async def test_postcondition_not_called_on_precondition_failure():
    """前置校验失败时不应调用后置条件。"""
    client = SpyClient()
    try:
        await client.chat(messages=[])
    except ValueError:
        pass
    assert client.chat_postcondition_called is False


@pytest.mark.asyncio
async def test_postcondition_not_called_on_hook_error():
    """钩子抛出异常时不应调用后置条件。"""
    client = SpyClient()
    client.inject_stream_error(make_rate_limit_error(429))
    try:
        async for _ in client.chat_stream(messages=VALID_MESSAGES):
            pass
    except LLMClientError:
        pass
    assert client.stream_postcondition_called is False


# ============================================================================
# chat 返回空字符串
# ============================================================================


@pytest.mark.asyncio
async def test_chat_returns_empty_string():
    """_do_create_completion 返回空字符串是合法的（非 None）。"""
    client = NormalClient(completion_result="")
    result = await client.chat(messages=VALID_MESSAGES)
    assert result == ""


# ============================================================================
# None 返回值触发后置条件 RuntimeError
# ============================================================================


class _NoneReturningClient(NormalClient):
    """恶意实现——_do_create_completion 返回 None。"""

    async def _do_create_completion(self, **kwargs) -> str:
        return None  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_none_completion_result_triggers_postcondition_error():
    """有缺陷的实现返回 None 时后置条件必须捕获。"""
    client = _NoneReturningClient()
    with pytest.raises(LLMClientError):
        await client.chat(messages=VALID_MESSAGES)


# ============================================================================
# 并发访问
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_chat_calls():
    """同一实例上多个并发 chat() 调用应各自正常工作。"""
    client = NormalClient()
    messages_list = [[{"role": "user", "content": f"msg {i}"}] for i in range(10)]
    results = await asyncio.gather(*(client.chat(messages=m) for m in messages_list))
    assert all(r == "Hello World" for r in results)
    assert len(results) == 10


@pytest.mark.asyncio
async def test_concurrent_stream_calls():
    """同一实例上多个并发 chat_stream() 调用应各自独立工作。"""

    async def collect(client, messages):
        return [c async for c in client.chat_stream(messages=messages)]

    client = NormalClient()
    messages_list = [[{"role": "user", "content": f"msg {i}"}] for i in range(5)]
    results = await asyncio.gather(*(collect(client, m) for m in messages_list))
    for chunks in results:
        assert len(chunks) == 3


@pytest.mark.asyncio
async def test_interleaved_stream_and_chat():
    """同一实例上先调 chat_stream 再调 chat 应正常工作。"""
    client = NormalClient()
    s_chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(s_chunks) == 3
    result = await client.chat(messages=VALID_MESSAGES)
    assert result == "Hello World"


# ============================================================================
# base_url 尾部斜杠处理
# ============================================================================


def test_base_url_trailing_slash_stripped():
    """base_url 尾部斜杠应被去除。"""
    client = NormalClient(base_url="http://test/")
    assert client._base_url == "http://test"


def test_base_url_no_trailing_slash_preserved():
    """无尾部斜杠的 base_url 应保持不变。"""
    client = NormalClient(base_url="http://test")
    assert client._base_url == "http://test"
