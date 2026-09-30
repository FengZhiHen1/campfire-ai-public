"""摘要调用的实现：用与主调用同一模型同一路由的一次独立调用写摘要。

职责：回放热前缀、发起一次独立模型调用、把摘要正文与用量交给压缩机制。
边界：不写会话、不执行工具，也不判定是否该压缩（合并要求由压缩机制追加）；失败原样冒泡。
参考：docs/技术设计/technical-details/压缩策略.md 第 4 节。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import replace

from agents import Agent, FunctionTool, RunConfig, Runner
from agents.items import TResponseInputItem

from campfire.agent.context import SummaryRequest, SummaryResult
from campfire.agent.model import ModelBinding

DEFAULT_AGENT_NAME = "campfire-compaction"

_TRACE_WORKFLOW = "campfire-compaction"
"""追踪工作流名：与主运行分开，便于在追踪里区分「写摘要」与「答使用者」。"""


class ModelSummarizer:
    """用一次独立模型调用写摘要（不写会话、不执行工具）。

    两处必须写明的实现取舍：

    取舍 1：工具声明照旧带上，但 `tool_choice="none"`。带上是为了让前缀与主调用逐字一致
    （第 4 节的缓存要求）；禁止调用工具是为了让「工具调用一律排除」由构造保证，而不是靠
    事后过滤——顺带也避免压缩时真的去执行一次工具调用。这是对提供方的假设：OpenAI 兼容端点
    支持 `tool_choice="none"`（未在 TokenHub 上核实，登记为待验证项）。
    """

    def __init__(
        self,
        *,
        binding: ModelBinding,
        tools: Sequence[FunctionTool] = (),
        agent_name: str = DEFAULT_AGENT_NAME,
    ) -> None:
        """绑定模型与声明。

        依据压缩策略第 4 节：由模型写，且必须与主调用同一模型与路由——否则不共享前缀缓存；
        逐字回放热前缀：系统提示、上次路由请求的工具声明、被遮蔽范围的消息逐字回放，
        压缩指令作为最后一条 user 消息追加；摘要输出受 `maxTokens` 限制；只有返回文本进入
        检查点，推理与工具调用一律排除。

        系统提示不在这里：它由 :class:`~campfire.agent.context.SummaryRequest` 承载
        （主运行的静态系统提示）。第一版把摘要器自己的提示当系统消息，于是接口根本无法保证
        「系统提示逐字回放」——前缀缓存从第一条消息起就不可能命中（第 8 节：违反缓存纪律
        视为缺陷）。摘要指令走请求里的最后一条 user 消息，不占系统位。

        `tools` 必须与主调用使用的声明同一份（同顺序、同 schema），否则前缀不一致、
        缓存复用不成立。
        """
        self._binding = binding
        self._tools = list(tools)
        self._agent_name = agent_name

    # quality-floor: ignore docstring-promise 异常由 SDK/提供方抛出并原样冒泡，函数体无 raise
    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        """写一次摘要。

        Raises:
            Exception: 提供方或 SDK 的异常原样冒泡——调用方（压缩机制）按第 7 节把它转成
                「摘要失败、窗口不动」，而不是在这里吞掉。
        """
        agent = Agent(
            name=self._agent_name,
            instructions=request.system_prompt,  # 逐字回放主运行的系统提示（第 4 节）
            model=self._binding.model,
            tools=list(self._tools),
        )
        settings = replace(
            self._binding.settings,
            tool_choice="none",  # 声明照旧、调用禁止：见模块 docstring 第 1 条
            max_tokens=request.max_tokens,
        )
        run_config = RunConfig(
            model=self._binding.model,
            model_settings=settings,
            trace_include_sensitive_data=False,
            workflow_name=_TRACE_WORKFLOW,
        )
        instructions = _replay(request)

        started = time.monotonic()
        result = await Runner.run(agent, input=instructions, max_turns=1, run_config=run_config)
        elapsed = time.monotonic() - started

        usage = result.context_wrapper.usage
        cache_hit, cache_miss = _cache_tokens(usage)
        return SummaryResult(
            text=_final_text(result.final_output),
            truncated=_looks_truncated(usage.output_tokens, request.max_tokens),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            elapsed_seconds=elapsed,
            prompt_cache_hit_tokens=cache_hit,
            prompt_cache_miss_tokens=cache_miss,
        )


def _replay(request: SummaryRequest) -> list[TResponseInputItem]:
    """把热前缀逐字回放，并把压缩指令作为最后一条 user 消息追加（第 4 节）。

    依据 docs/技术设计/technical-details/压缩策略.md 第 4 节：

    - 由模型写，且必须与主调用同一模型与路由——否则不共享前缀缓存；
    - 逐字回放热前缀：系统提示、上次路由请求的工具声明、被遮蔽范围的消息逐字回放，
      压缩指令作为最后一条 user 消息追加；
    - 摘要输出受 `maxTokens` 限制；只有返回文本进入检查点，推理与工具调用一律排除；
    - 已有检查点时要求合并（合并要求由 :mod:`campfire.agent.context.compaction` 追加，不在这里）。
    """
    replayed: list[TResponseInputItem] = []
    for item in request.prefix:
        replayed.append(dict(item))  # type: ignore[arg-type]  # 逐字回放：只复制，不改写
    replayed.append({"role": "user", "content": request.instruction})
    return replayed


def _looks_truncated(output_tokens: int, max_tokens: int) -> bool:
    """摘要是否疑似被 `max_tokens` 截断。

    取舍 2：截断用 `output_tokens >= maxTokens` 判定，是启发式。SDK 的 `ModelResponse` 不暴露
    `finish_reason`（实测字段只有 output/usage/response_id/request_id/raw_usage），因此拿不到
    「因长度而停」的官方信号。判错的代价是不对称的：把完整摘要误判为截断只是不改窗口
    （第 7 节的安全方向），把截断摘要误判为完整则会把半截摘要写进检查点、丢掉没被摘要的
    历史。所以这里从严。

    两种情形都算疑似：

    - `output_tokens >= max_tokens`：用满了上限；
    - `output_tokens <= 0`：提供方没给用量。此时无法判断是否写满，必须按不安全方向处理
      （第一版直接算「完整」，等于把「没数据」当成了「没截断」的正面证据）。

    判错代价不对称（第 7 节）：误判为截断只是不改窗口（安全方向），误判为完整会把半截摘要
    写进检查点、丢掉没被摘要的历史。代价是「提供方不给用量」时压缩会一直不生效——
    那是一个会显式暴露的降级（`summary_truncated`），比静默丢历史好。
    """
    return output_tokens <= 0 or output_tokens >= max_tokens


def _cache_tokens(usage: object) -> tuple[int, int]:
    """从 SDK 归一后的 usage 里取缓存命中/未命中 token。

    实测（探针 `.tmp/probe_raw_usage.py`）：Chat Completions 路径下
    `ModelResponse.raw_usage` 是 `None`，而 `Usage.input_tokens_details.cached_tokens`
    是 SDK 归一后的真实字段。第一版去读 `raw_usage["prompt_cache_hit_tokens"]`，恒为 0
    且无法验证——那等于记了两个永远为零的字段。

    命中取 `cached_tokens`；未命中按 `input_tokens - cached_tokens` 推导（提供方在
    OpenAI 形状里只给命中数）。推导口径写在这里，供第 12 节的断言复核。

    证据边界：提供方不报缓存明细时，读到的命中必然是 0、未命中等于全部输入 token——
    它表达的是「我们没看到命中」，不区分「确实没有缓存」与「提供方不报」。
    """
    details = getattr(usage, "input_tokens_details", None)
    hit = int(getattr(details, "cached_tokens", 0) or 0)
    total = int(getattr(usage, "input_tokens", 0) or 0)
    return hit, max(0, total - hit)


def _final_text(output: object) -> str:
    """取模型输出里的文本；非文本（例如 None）返回空串。

    空串会让压缩机制按「摘要为空 → 不落检查点」处理（第 7 节），因此不需要在这里编造内容。
    """
    return output if isinstance(output, str) else ""
