"""正常路径与集成测试 —— 验证流式和非流式流程的端到端正常行为。

对抗测试仅覆盖 P0-P3（边界/异常），本文件补充正常路径。
"""

from __future__ import annotations

import pytest

from py_llm.types import ChatCompletionChunk
from conftest import NormalClient, make_chunk, make_default_chunks

VALID_MESSAGES = [{"role": "user", "content": "Hello, how are you?"}]


# ============================================================================
# chat_stream —— 正常流式路径
# ============================================================================


@pytest.mark.asyncio
async def test_chat_stream_yields_all_chunks():
    """正常流式调用应 yield 全部预设 chunk。"""
    client = NormalClient()
    chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(chunks) == 3
    assert chunks[0].choices[0].delta.content == "Hello"
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[1].choices[0].delta.content == " World"
    assert chunks[2].choices[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_chat_stream_chunks_are_chat_completion_chunk_type():
    """每个 yield 的对象都是 ChatCompletionChunk 类型。"""
    client = NormalClient()
    async for chunk in client.chat_stream(messages=VALID_MESSAGES):
        assert isinstance(chunk, ChatCompletionChunk)


@pytest.mark.asyncio
async def test_chat_stream_custom_chunks():
    """使用自定义 chunk 列表验证内容传递正确。"""
    custom = [
        make_chunk(chunk_id="c1", content="Part1", role="assistant"),
        make_chunk(chunk_id="c2", content="Part2", finish_reason="stop"),
    ]
    client = NormalClient(stream_chunks=custom)
    results = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(results) == 2
    assert results[0].id == "c1"
    assert results[1].id == "c2"


@pytest.mark.asyncio
async def test_chat_stream_with_custom_parameters():
    """自定义参数应正确传递给钩子。"""
    client = NormalClient()
    msgs = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "你好"},
    ]
    async for _ in client.chat_stream(
        messages=msgs,
        model="deepseek-v4-flash",
        temperature=0.7,
        max_tokens=2048,
        timeout=60.0,
    ):
        pass
    kw = client.stream_kwargs[0]
    assert kw["messages"] == msgs
    assert kw["model"] == "deepseek-v4-flash"
    assert kw["temperature"] == 0.7
    assert kw["max_tokens"] == 2048
    assert kw["timeout"] == 60.0


# ============================================================================
# chat —— 正常非流式路径
# ============================================================================


@pytest.mark.asyncio
async def test_chat_returns_string():
    """正常非流式调用应返回字符串。"""
    client = NormalClient(completion_result="答案是 42。")
    result = await client.chat(messages=VALID_MESSAGES)
    assert result == "答案是 42。"
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_chat_with_system_message():
    """带 system 消息的正常调用。"""
    client = NormalClient()
    msgs = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "什么是 Python？"},
    ]
    result = await client.chat(messages=msgs)
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_chat_with_custom_parameters():
    """自定义参数应正确传递给钩子。"""
    client = NormalClient()
    msgs = [{"role": "user", "content": "请简要解释。"}]
    result = await client.chat(
        messages=msgs,
        model="deepseek-v4-flash",
        temperature=0.9,
        max_tokens=512,
        timeout=30.0,
    )
    assert isinstance(result, str)
    kw = client.completion_kwargs[0]
    assert kw["model"] == "deepseek-v4-flash"
    assert kw["temperature"] == 0.9
    assert kw["max_tokens"] == 512
    assert kw["timeout"] == 30.0


# ============================================================================
# RetryConfig 定制
# ============================================================================


@pytest.mark.asyncio
async def test_custom_retry_config_is_used():
    """自定义 RetryConfig 应在契约入口中生效。"""
    from py_llm.types import RetryConfig
    from conftest import ErrorSequenceClient, make_rate_limit_error

    msgs = [{"role": "user", "content": "Hi"}]
    # max_retries=1: 共 2 次尝试（0, 1），均抛异常 → 最终失败
    client = ErrorSequenceClient(
        errors={0: make_rate_limit_error(429), 1: make_rate_limit_error(429)},
        retry_config=RetryConfig(max_retries=1),
    )
    with pytest.raises(Exception):
        async for _ in client.chat_stream(messages=msgs):
            pass


# ============================================================================
# 流式与非流式独立运作
# ============================================================================


@pytest.mark.asyncio
async def test_stream_and_chat_have_independent_kwargs():
    """chat_stream 和 chat 的参数记录互不干扰。"""
    client = NormalClient()
    async for _ in client.chat_stream(messages=VALID_MESSAGES):
        pass
    await client.chat(messages=VALID_MESSAGES)
    assert len(client.stream_kwargs) == 1
    assert len(client.completion_kwargs) == 1


@pytest.mark.asyncio
async def test_stream_then_chat_yields_correct_content():
    """先流式后非流式，内容互不污染。"""
    chunks = [
        make_chunk(chunk_id="s1", content="流式内容"),
        make_chunk(chunk_id="s2", content="", finish_reason="stop"),
    ]
    client = NormalClient(stream_chunks=chunks, completion_result="非流式内容")
    s_results = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert s_results[0].choices[0].delta.content == "流式内容"
    ns_result = await client.chat(messages=VALID_MESSAGES)
    assert ns_result == "非流式内容"


# ============================================================================
# 多角色多轮对话
# ============================================================================


@pytest.mark.asyncio
async def test_multi_turn_conversation():
    """多轮对话消息应被完整传递。"""
    client = NormalClient()
    conversation = [
        {"role": "system", "content": "你是一个有帮助的助手。"},
        {"role": "user", "content": "什么是 ASD？"},
        {"role": "assistant", "content": "ASD 是一种神经发育状况。"},
        {"role": "user", "content": "早期表现有哪些？"},
    ]
    async for _ in client.chat_stream(messages=conversation):
        pass
    assert len(client.stream_kwargs[0]["messages"]) == 4


# ============================================================================
# 默认 chunk 内容验证
# ============================================================================


def test_default_chunks_have_expected_content():
    """make_default_chunks 生成的 chunk 应符合预期结构。"""
    chunks = make_default_chunks()
    assert len(chunks) == 3
    assert chunks[0].choices[0].delta.content == "Hello"
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[1].choices[0].delta.content == " World"
    assert chunks[2].choices[0].finish_reason == "stop"
