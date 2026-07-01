"""前置条件校验测试 —— 验证 @final 公共方法正确拦截非法输入。

覆盖 chat_stream / chat 的:
- 空 messages、空 model、越界 temperature、越界 max_tokens
- 前置校验在钩子调用前执行
"""

from __future__ import annotations

import pytest
from helpers import NormalClient

VALID_MESSAGES: list[dict[str, str]] = [{"role": "user", "content": "Hi"}]


# ============================================================================
# messages 校验
# ============================================================================


@pytest.mark.asyncio
async def test_chat_stream_rejects_empty_messages():
    """空消息列表必须抛出 ValueError。"""
    client = NormalClient()
    with pytest.raises(ValueError, match="messages must not be empty"):
        async for _ in client.chat_stream(messages=[]):
            pass


@pytest.mark.asyncio
async def test_chat_rejects_empty_messages():
    """非流式路径中空消息列表必须抛出 ValueError。"""
    client = NormalClient()
    with pytest.raises(ValueError, match="messages must not be empty"):
        await client.chat(messages=[])


@pytest.mark.asyncio
async def test_chat_stream_accepts_non_empty_messages():
    """非空消息应通过前置校验。"""
    client = NormalClient()
    chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES)]
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_chat_accepts_non_empty_messages():
    """非流式路径中非空消息应通过前置校验。"""
    client = NormalClient()
    result = await client.chat(messages=VALID_MESSAGES)
    assert isinstance(result, str)


# ============================================================================
# model 校验
# ============================================================================


@pytest.mark.parametrize("invalid_model", ["", None])
@pytest.mark.asyncio
async def test_chat_stream_rejects_empty_model(invalid_model):
    """空 model 必须抛出 ValueError。"""
    client = NormalClient()
    with pytest.raises(ValueError, match="model must not be empty"):
        async for _ in client.chat_stream(messages=VALID_MESSAGES, model=invalid_model):
            pass


@pytest.mark.asyncio
async def test_chat_rejects_empty_model():
    """非流式路径中空 model 必须抛出 ValueError。"""
    client = NormalClient()
    with pytest.raises(ValueError, match="model must not be empty"):
        await client.chat(messages=VALID_MESSAGES, model="")


# ============================================================================
# temperature 校验
# ============================================================================


@pytest.mark.parametrize(
    "temp,should_reject",
    [
        (-0.1, True),
        (-100.0, True),
        (0.0, False),
        (2.0, False),
        (2.1, True),
        (100.0, True),
    ],
)
@pytest.mark.asyncio
async def test_chat_stream_temperature_validation(temp, should_reject):
    """temperature 必须在 [0.0, 2.0] 范围内。"""
    client = NormalClient()
    if should_reject:
        with pytest.raises(ValueError, match="temperature must be in"):
            async for _ in client.chat_stream(messages=VALID_MESSAGES, temperature=temp):
                pass
    else:
        chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES, temperature=temp)]
        assert len(chunks) > 0


@pytest.mark.parametrize(
    "temp,should_reject",
    [
        (-0.1, True),
        (0.0, False),
        (2.0, False),
        (2.1, True),
    ],
)
@pytest.mark.asyncio
async def test_chat_temperature_validation(temp, should_reject):
    """非流式路径中 temperature 必须在 [0.0, 2.0] 范围内。"""
    client = NormalClient()
    if should_reject:
        with pytest.raises(ValueError, match="temperature must be in"):
            await client.chat(messages=VALID_MESSAGES, temperature=temp)
    else:
        result = await client.chat(messages=VALID_MESSAGES, temperature=temp)
        assert isinstance(result, str)


# ============================================================================
# max_tokens 校验
# ============================================================================


@pytest.mark.parametrize(
    "tokens,should_reject",
    [
        (0, True),
        (-1, True),
        (-100, True),
        (1, False),
        (8192, False),
    ],
)
@pytest.mark.asyncio
async def test_chat_stream_max_tokens_validation(tokens, should_reject):
    """max_tokens 必须 >= 1。"""
    client = NormalClient()
    if should_reject:
        with pytest.raises(ValueError, match="max_tokens must be"):
            async for _ in client.chat_stream(messages=VALID_MESSAGES, max_tokens=tokens):
                pass
    else:
        chunks = [c async for c in client.chat_stream(messages=VALID_MESSAGES, max_tokens=tokens)]
        assert len(chunks) > 0


@pytest.mark.parametrize(
    "tokens,should_reject",
    [
        (0, True),
        (1, False),
        (-5, True),
    ],
)
@pytest.mark.asyncio
async def test_chat_max_tokens_validation(tokens, should_reject):
    """非流式路径中 max_tokens 必须 >= 1。"""
    client = NormalClient()
    if should_reject:
        with pytest.raises(ValueError, match="max_tokens must be"):
            await client.chat(messages=VALID_MESSAGES, max_tokens=tokens)
    else:
        result = await client.chat(messages=VALID_MESSAGES, max_tokens=tokens)
        assert isinstance(result, str)


# ============================================================================
# 前置校验在钩子调用前执行
# ============================================================================


@pytest.mark.asyncio
async def test_precondition_runs_before_stream_hook():
    """前置校验失败时钩子不应被调用。"""
    client = NormalClient()
    try:
        async for _ in client.chat_stream(messages=[], max_tokens=0):
            pass
    except ValueError:
        pass
    assert len(client.stream_kwargs) == 0, "前置校验失败后钩子不应被调用"


@pytest.mark.asyncio
async def test_precondition_runs_before_chat_hook():
    """非流式路径中前置校验失败时钩子不应被调用。"""
    client = NormalClient()
    try:
        await client.chat(messages=[], max_tokens=0)
    except ValueError:
        pass
    assert len(client.completion_kwargs) == 0, "前置校验失败后钩子不应被调用"


@pytest.mark.asyncio
async def test_multiple_precondition_violations_raises_once():
    """多个违规同时存在时只抛出一次 ValueError。"""
    client = NormalClient()
    with pytest.raises(ValueError):
        async for _ in client.chat_stream(messages=[], model="", temperature=3.0, max_tokens=0):
            pass
