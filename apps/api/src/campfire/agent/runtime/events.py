"""流式事件：一次运行对外的唯一输出形状。

依据 docs/技术设计/technical-details/通用基座.md 第 7 节：事件类型一期经 SSE 传输，
名称与语义对齐 AG-UI 以便升级。因此这里的 `type` 取值就是线上契约，改名等于改契约。

第一次看到这个模块的人常问三件事，答案都写在这里：

1. 为什么事件类型不直接暴露 SDK 的类型？ 这些事件要过 SSE 到前端、要进运行记录，
   两处都不该跟着 SDK 的版本漂移。所以 `RunUsage`、`CitationRecord` 等是基座自己的
   形状，SDK 类型在 `runner` 里被翻译一次。
2. `run_finished` 与 `run_failed` 怎么分？ 第 9 节把「触顶（步数/token/时间）」与
   「运行被取消」都归为以明确原因结束并保留已产生的引用，所以它们是 `run_finished`
   的 `reason`（`completed` / `timeout` / `cancelled`）；模型不可用、会话写入失败
   这类「本次运行明确失败」才是 `run_failed`。
3. 为什么有 `progress`？ 第 7 节要求长等待（例如检索中）有进度提示；它由装配处
   在等待期间发出，不承载业务语义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

from campfire.agent.context import CitationRecord
from campfire.agent.model import ModelFailureReason
from campfire.agent.tools import Candidate, ToolErrorCode

RunEndReason = Literal["completed", "timeout", "cancelled"]
"""结束后原因（`run_finished`）。三者都会保留已产生的引用（第 9 节）。"""

RunFailureCode = Literal[
    "model_unavailable",
    "injection_failed",
    "session_write_failed",
    "context_overflow",
    "internal",
]
"""失败码（`run_failed`）。

- `model_unavailable`：模型调用重试耗尽（`model_reason` 给出细分原因）；
- `injection_failed`：注入项渲染/索引写入失败——不得当作「没有注入」继续；
- `session_write_failed`：对话未能落库（第 9 节：不得把未落库的对话当作已保存继续下一轮）；
- `context_overflow`：提供方明确报上下文溢出，而压缩无法把窗口再降下来（压缩策略第 7 节：
  不可分单元超预算时明确失败并提示，不静默截断）；
- `internal`：其余未归类异常。
"""

# 工具结果摘要的长度上限。事件的用途是让使用者看到「发生了什么」，完整结果已经回给模型；
# 不做长度限制会让一次检索把整篇文档灌进 SSE。
SUMMARY_LIMIT = 200


@dataclass(frozen=True, slots=True)
class RunUsage:
    """一次运行的 token 计量。

    用提供方返回的 usage（见压缩策略第 9 节：不用字符数折算），SDK 的响应事件里带。
    多次模型调用在同一运行内累加。
    """

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: RunUsage) -> RunUsage:
        """累加两次模型调用的计量。"""
        return RunUsage(
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True, slots=True)
class RunStartedEvent:
    """运行开始：含本次激活的 skill 与注入项清单（第 7 节）。"""

    run_id: str
    session_id: str
    surface: str | None
    model: str
    activated_skills: tuple[str, ...]
    injection_sources: tuple[str, ...]
    appended_messages: int
    type: Literal["run_started"] = field(default="run_started", init=False)


@dataclass(frozen=True, slots=True)
class TextDeltaEvent:
    """文本增量。"""

    delta: str
    type: Literal["text_delta"] = field(default="text_delta", init=False)


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """进度提示，用于长等待。"""

    message: str
    type: Literal["progress"] = field(default="progress", init=False)


@dataclass(frozen=True, slots=True)
class ToolCallStartedEvent:
    """模型发起了一次工具调用。"""

    tool_name: str
    call_id: str
    type: Literal["tool_call_started"] = field(default="tool_call_started", init=False)


@dataclass(frozen=True, slots=True)
class ToolCallFinishedEvent:
    """一次工具调用结束（成功或被拒绝），带结果摘要。"""

    tool_name: str
    call_id: str
    ok: bool
    error_code: ToolErrorCode | None
    summary: str
    type: Literal["tool_call_finished"] = field(default="tool_call_finished", init=False)


@dataclass(frozen=True, slots=True)
class CitationEvent:
    """一条可引用依据；对应引用索引里的一条记录（第 4 节不变量）。"""

    citation: CitationRecord
    type: Literal["citation"] = field(default="citation", init=False)


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    """一条未确认的候选产出，供面呈现为「待确认」。"""

    candidate: Candidate
    type: Literal["candidate"] = field(default="candidate", init=False)


@dataclass(frozen=True, slots=True)
class CompactionFacts:
    """一次压缩的计量（压缩策略第 9 节），只带计数与用量、不带摘要正文。

    为什么挂在 `run_finished` / `run_failed` 上而不是新开一种事件：第 7 节的事件表是与
    AG-UI 对齐的对外契约，加一种类型等于改契约；而第 9 节要的是记录里的计量，终端事件
    已经带着引用清单与用量，把压缩计量一并带上最省事，也不给面增加新的分支。溢出恢复发生在
    运行开始之后，因此只有终端事件能收全所有压缩。
    """

    performed: bool
    window_tokens_before: int
    window_tokens_after: int
    released_tokens: int
    compacted_items: int
    retained_items: int
    attempts: int
    failed_attempts: int
    previous_summary_merged: bool
    summary_input_tokens: int
    summary_output_tokens: int
    summary_elapsed_seconds: float
    prompt_cache_hit_tokens: int = 0
    """摘要调用的缓存命中 token（压缩策略第 9 节要求记录、第 12 节要求用它断言）。

    来源是提供方 usage 里的 `prompt_cache_hit_tokens`；键名与是否返回均未核实
    （`TECH-02`），取不到时保持 0——不编造。
    """

    prompt_cache_miss_tokens: int = 0
    """摘要调用的缓存未命中 token（同上）。"""

    reason: str | None = None
    """没有压缩时的原因（压缩策略第 3、7 节：不留假成功，没做就要说清为什么）。"""

    detail: str = ""
    """给排障看的说明，只带类型级信息。"""


@dataclass(frozen=True, slots=True)
class RunFinishedEvent:
    """运行结束（正常或触顶），含结束原因与引用清单。"""

    reason: RunEndReason
    citations: tuple[CitationRecord, ...]
    usage: RunUsage
    elapsed_seconds: float
    compactions: tuple[CompactionFacts, ...] = ()
    """本次运行做过的压缩（第 9 节的计量）；没压缩时为空。"""

    type: Literal["run_finished"] = field(default="run_finished", init=False)


@dataclass(frozen=True, slots=True)
class RunFailedEvent:
    """运行失败，含错误码。"""

    code: RunFailureCode
    detail: str
    """面向排障的说明，只带类型级信息，不含凭据与使用者内容。"""

    citations: tuple[CitationRecord, ...]
    usage: RunUsage
    elapsed_seconds: float
    model_reason: ModelFailureReason | None = None
    """`code` 为 `model_unavailable` 时的细分原因。"""

    compactions: tuple[CompactionFacts, ...] = ()
    """本次运行做过的压缩（第 9 节的计量）；没压缩时为空。"""

    type: Literal["run_failed"] = field(default="run_failed", init=False)


RunEvent = Union[
    RunStartedEvent,
    TextDeltaEvent,
    ProgressEvent,
    ToolCallStartedEvent,
    ToolCallFinishedEvent,
    CitationEvent,
    CandidateEvent,
    RunFinishedEvent,
    RunFailedEvent,
]
"""一次运行可能发出的事件全集（判别联合，按 `type` 区分）。"""
