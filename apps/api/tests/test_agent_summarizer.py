"""摘要调用：热前缀逐字回放、指令在最后、工具声明照旧但禁止调用、截断从严。

对应 docs/技术设计/technical-details/压缩策略.md 第 4 节。用假 Chat Completions 服务跑真实
链路（真实模型类 + 真实运行循环），只把 HTTP 出口换掉——与运行编排的测试同一手法。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from agents import ModelSettings
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from pydantic import BaseModel

from campfire.agent.context import SummaryRequest
from campfire.agent.model import ModelBinding
from campfire.agent.runtime import ModelSummarizer, ToolBridge
from campfire.agent.tools import ToolContext, ToolDispatcher, ToolPool, ToolResult, ToolSpec, resolve_scope

BASE_URL = "https://tokenhub.test/v1"
MODEL_NAME = "test-model"


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-summary",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


class ScriptedChat:
    """假服务：按请求的 ``stream`` 决定回 SSE 还是普通 JSON，并记录每次请求体。

    摘要调用是**非流式**的（``Runner.run`` 而非 ``run_streamed``），所以替身必须两种形状都会答；
    第一版只答 SSE，SDK 解析出来的东西没有 ``choices``，报出的是一句与真实原因无关的
    ``AttributeError``。
    """

    def __init__(
        self,
        text: str = "摘要正文",
        *,
        output_tokens: int = 0,
        status_code: int = 200,
        with_cache: bool = False,
    ) -> None:
        self._text = text
        self._output_tokens = output_tokens
        self._status = status_code
        self._with_cache = with_cache
        self.requests: list[dict[str, Any]] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if self._status != 200:
            return httpx.Response(self._status, json={"error": {"message": "boom"}})
        if body.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=self._stream_body())
        return httpx.Response(200, json=self._json_body())

    def _stream_body(self) -> bytes:
        """流式应答（主运行用得到，摘要调用不用）。"""
        return (
            _chunk({"role": "assistant", "content": ""})
            + _chunk({"content": self._text})
            + _chunk({}, "stop")
            + "data: [DONE]\n\n"
        ).encode()

    def _json_body(self) -> dict[str, Any]:
        """非流式应答：摘要调用走这条。"""
        return {
            "id": "chatcmpl-summary",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": self._text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": self._output_tokens,
                "total_tokens": 42 + self._output_tokens,
                # 缓存命中走 OpenAI 形状的 prompt_tokens_details.cached_tokens：实测
                # Chat Completions 路径下 raw_usage 为 None，只有 SDK 归一后的这个字段是真的。
                **({"prompt_tokens_details": {"cached_tokens": 40}} if self._with_cache else {}),
            },
        }

    @property
    def body(self) -> dict[str, Any]:
        """第一次请求的请求体。"""
        return self.requests[0]


def _binding(chat: ScriptedChat) -> ModelBinding:
    from openai import AsyncOpenAI

    client = httpx.AsyncClient(transport=httpx.MockTransport(chat.handler))
    return ModelBinding(
        name=MODEL_NAME,
        model=OpenAIChatCompletionsModel(
            model=MODEL_NAME,
            openai_client=AsyncOpenAI(api_key="k", base_url=BASE_URL, max_retries=0, http_client=client),
        ),
        settings=ModelSettings(),
    )


class _Args(BaseModel):
    """检索参数。"""

    query: str


def _search_tool() -> ToolSpec[_Args]:
    """一个工具：只为验证「声明照旧带上」。"""

    async def handler(_context: ToolContext, args: _Args) -> ToolResult:
        return ToolResult(text=f"读到 {args.query}")

    return ToolSpec(name="search_knowledge", description="检索", args_model=_Args, handler=handler)


SYSTEM_PROMPT = "主运行的静态系统提示"


def _request(
    *,
    prefix: Sequence[dict[str, object]] = (),
    max_tokens: int = 512,
    system_prompt: str = SYSTEM_PROMPT,
) -> SummaryRequest:
    return SummaryRequest(
        prefix=tuple(prefix),  # type: ignore[arg-type]
        system_prompt=system_prompt,
        instruction="把历史压成六节摘要。",
        previous_summary=None,
        max_tokens=max_tokens,
    )


@pytest.mark.asyncio
async def test_system_prompt_is_the_main_run_prompt_replayed_verbatim() -> None:
    """第 4 节 + 第 8 节：**主运行**的系统提示逐字回放。

    这条是缓存能否命中的前提：前缀缓存要求「完整匹配一个已持久化的前缀单元」，第 0 条消息
    就不同的话整个前缀都不命中。第一版把摘要器自己的提示放在系统位，接口**无法承载**主运行
    的系统提示——只能靠装配处碰巧传同一个字符串。
    """
    chat = ScriptedChat("摘要正文")
    summarizer = ModelSummarizer(binding=_binding(chat))

    await summarizer.summarize(_request(system_prompt="主运行的静态系统提示"))

    assert chat.body["messages"][0] == {"role": "system", "content": "主运行的静态系统提示"}


@pytest.mark.asyncio
async def test_instruction_comes_last_after_the_replayed_prefix() -> None:
    """第 4 节：热前缀逐字回放，压缩指令作为**最后一条 user 消息**追加。"""
    chat = ScriptedChat("摘要正文")
    summarizer = ModelSummarizer(binding=_binding(chat))
    prefix = [
        {"role": "user", "content": "第一段历史"},
        {"role": "assistant", "content": "第二段历史"},
    ]

    await summarizer.summarize(_request(prefix=prefix))

    messages = chat.body["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    # 被压缩范围的消息逐字回放
    assert messages[1]["content"] == "第一段历史"
    assert messages[2]["content"] == "第二段历史"
    # 指令在最末
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "把历史压成六节摘要。"
    assert len(messages) == 4


@pytest.mark.asyncio
async def test_replayed_items_are_copied_not_mutated() -> None:
    """「逐字回放」不只是措辞：原项不得被就地修改。"""
    chat = ScriptedChat("摘要")
    summarizer = ModelSummarizer(binding=_binding(chat))
    original = {"role": "user", "content": "历史"}

    await summarizer.summarize(_request(prefix=[original]))

    assert original == {"role": "user", "content": "历史"}
    assert chat.body["messages"][1] is not original


class _FakeIndex:
    """引用索引替身（本文件只关心工具声明是否照旧带上）。"""

    async def add(self, _record: object) -> None:
        """不落任何东西。"""
        return None

    async def list_for_run(self, _run_id: str) -> Sequence[object]:
        """空列表。"""
        return []


def _tool_context() -> ToolContext:
    """一个最小可用的工具上下文。"""
    from campfire.agent.context import CitationRecorder
    from campfire.agent.tools import ActivationState

    return ToolContext(
        run_id="r",
        session_id="s",
        surface=None,
        activation_state=ActivationState(),
        citations=CitationRecorder(_FakeIndex(), run_id="r"),
    )


@pytest.mark.asyncio
async def test_tools_are_declared_but_calls_are_forbidden() -> None:
    """声明照旧（前缀一致 → 缓存可复用），但 tool_choice=none 让「工具调用一律排除」由构造保证。"""
    chat = ScriptedChat("摘要")
    pool = ToolPool([_search_tool()])
    dispatcher = ToolDispatcher(pool, resolve_scope(pool), context=_tool_context())
    bridge = ToolBridge(dispatcher, sink=lambda _event: None)

    summarizer = ModelSummarizer(binding=_binding(chat), tools=bridge.function_tools())
    await summarizer.summarize(_request())

    declared = {tool["function"]["name"] for tool in chat.body["tools"]}
    assert declared == {"search_knowledge"}
    assert chat.body["tool_choice"] == "none"


@pytest.mark.asyncio
async def test_max_tokens_bounds_the_summary_call() -> None:
    """第 4 节：摘要输出受 maxTokens 限制。"""
    chat = ScriptedChat("摘要")

    await ModelSummarizer(binding=_binding(chat)).summarize(_request(max_tokens=1234))

    assert chat.body["max_tokens"] == 1234


@pytest.mark.asyncio
async def test_usage_and_elapsed_are_reported() -> None:
    """第 9 节：摘要调用的用量与耗时进记录。"""
    chat = ScriptedChat("摘要", output_tokens=37)

    result = await ModelSummarizer(binding=_binding(chat)).summarize(_request(max_tokens=512))

    assert result.text == "摘要"
    assert result.output_tokens == 37
    assert result.input_tokens == 42
    assert result.elapsed_seconds >= 0
    assert result.truncated is False


@pytest.mark.asyncio
async def test_summary_hitting_the_cap_is_flagged_as_truncated() -> None:
    """截断从严：``output_tokens >= maxTokens`` 即视为疑似截断，让机制拒绝落检查点。"""
    chat = ScriptedChat("半截摘要", output_tokens=512)

    result = await ModelSummarizer(binding=_binding(chat)).summarize(_request(max_tokens=512))

    assert result.truncated is True


@pytest.mark.asyncio
async def test_cache_tokens_are_taken_from_raw_usage() -> None:
    """第 9 节：压缩记录要带 ``prompt_cache_hit/miss_tokens``（第 12 节用它断言缓存仍有效）。

    SDK 的聚合 ``Usage`` 不带这两个字段，因此必须读 ``ModelResponse.raw_usage``。
    提供方不给时保持 0——不编造计量。
    """
    chat = ScriptedChat("摘要", output_tokens=7, with_cache=True)

    result = await ModelSummarizer(binding=_binding(chat)).summarize(_request(max_tokens=512))

    assert result.prompt_cache_hit_tokens == 40
    assert result.prompt_cache_miss_tokens == 2  # 42 − 40，推导口径见 _cache_tokens


@pytest.mark.asyncio
async def test_no_cache_details_means_no_observed_hits() -> None:
    """提供方不报缓存明细时：命中 0、未命中等于全部输入 token。

    这只表达「我们没看到命中」，**不区分**「确实没有缓存」与「提供方不报」——口径与边界写在
    ``_cache_tokens`` 的 docstring 里，不在这里编造一个 0。
    """
    chat = ScriptedChat("摘要", output_tokens=7)

    result = await ModelSummarizer(binding=_binding(chat)).summarize(_request(max_tokens=512))

    assert result.prompt_cache_hit_tokens == 0
    assert result.prompt_cache_miss_tokens == result.input_tokens == 42


@pytest.mark.asyncio
async def test_missing_usage_is_treated_as_suspect_not_as_complete() -> None:
    """提供方**没给用量**时必须按不安全方向处理。

    ``output_tokens`` 缺失时它是 0：第一版把它算成「完整」，等于把「没有数据」当成了
    「没截断」的正面证据——而判错代价是不对称的（误判为完整会把半截摘要写进检查点、
    丢掉没被摘要的历史）。
    """
    chat = ScriptedChat("摘要", output_tokens=0)

    result = await ModelSummarizer(binding=_binding(chat)).summarize(_request(max_tokens=512))

    assert result.output_tokens == 0
    assert result.truncated is True


@pytest.mark.asyncio
async def test_provider_failure_propagates_to_the_mechanism() -> None:
    """提供方失败原样冒泡：由压缩机制按第 7 节转成「摘要失败、窗口不动」。"""
    chat = ScriptedChat(status_code=500)
    summarizer = ModelSummarizer(binding=_binding(chat))

    with pytest.raises(Exception):  # noqa: B017 —— 这里只断言「没有被吞掉」
        await summarizer.summarize(_request())
