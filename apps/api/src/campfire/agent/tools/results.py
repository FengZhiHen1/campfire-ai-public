"""一次工具调用的结果形状。

职责：定义工具调用的判别联合结果（:data:`ToolOutcome`）与其错误码。
边界：没有「成功但为空」「失败但像成功」的中间态；失败消息不得包含连接串或凭据。
参考：docs/技术设计/technical-details/通用基座.md 第 5 节失败语义。
"""

# 依据 docs/技术设计/technical-details/通用基座.md 第 5 节失败语义：
#
# - 工具自身错误作为结果回给模型（可恢复），不是抛异常中断运行；
# - 权限拒绝返回明确错误码，不静默降级为其他工具。
#
# 因此结果是一个判别联合（:data:`ToolOutcome`）：成功带产出，失败带错误码。没有
# 「成功但为空」「失败但像成功」的中间态。

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from campfire.agent.context import CitationRecord

from .payloads import ActionCard, Question

ToolErrorCode = Literal[
    "tool_not_registered",
    "tool_not_available",
    "tool_requires_approval",
    "tool_invalid_arguments",
    "tool_failed",
    "tool_interrupted",
]
"""工具失败的错误码。

- `tool_not_registered`：模型调用了一个不存在的工具名；
- `tool_not_available`：工具已声明但此刻未激活，服务端拒绝（硬边界）；
- `tool_requires_approval`：需要人工审批，而一期不实现 HITL，故显式拒绝；
- `tool_invalid_arguments`：参数不是合法 JSON 或不符合该工具的 JSON Schema；
- `tool_failed`：工具实现自己报错，错误类型回给模型，它可据此换个方式再试；
- `tool_interrupted`：调用没有结果就结束了（运行触顶、运行失败或取消打断）。
  它不是工具自身报错，因此与 `tool_failed` 分开——消费方据此知道「工具可能还在跑」
  而不是「工具说它坏了」。这个码由运行编排合成（工具没机会返回结果），
  见 :class:`~campfire.agent.runtime.runner._ToolCallTracker`。
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    """一条未确认的候选产出，供面呈现为「待确认」。

    基座只承载形状（业务回指 + 摘要），不承载语义：为什么待确认、确认后写到哪，
    都由产品侧与面决定（基座不得出现领域术语）。
    """

    reference: str
    """指向的业务标识。"""

    summary: str
    """给使用者看的一句话说明。"""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具成功执行后的产出。

    `citations` 只能来自 :class:`~campfire.agent.context.CitationRecorder`：引用
    凭据与索引写入是同一个动作，工具无法伪造一条「查不到出处」的依据。
    """

    text: str
    """回给模型的内容。"""

    citations: tuple[CitationRecord, ...] = ()
    """本次产出涉及的引用；每条都已在引用索引里有记录。"""

    candidates: tuple[Candidate, ...] = ()
    """本次产出产生的未确认候选。"""

    cards: tuple[ActionCard, ...] = ()
    """本次产出发出的结构化卡片（基座第 7.3 节的通用信封）。

    为什么走这条通道（与 `question` 走工具即结束运行不对称，判据在基座 7.3 节）：
    卡片不需要「结束本次运行」这一只有基座能给的编排行为——工具返回后运行自然继续，
    因此复用既有的工具结果通道即可（与 `citations`、`candidates` 同一种做法），
    基座把它翻成 `action_card` 事件。这样新增一种卡片是新增一个产品侧工具，基座不动。
    """

    question: Question | None = None
    """本次工具调用要向使用者发起的一组提问（基座第 7.2 节）；`None` 表示这次调用不提问。

    只有 `ask_user` 会填它，且填了就意味着**本次运行就此结束**：运行编排在工具边界把它翻成
    `question` 事件，并让 SDK 停下（不再回到模型）——提问是运行的中止方式（基座 7.2 节），
    所以这一条通道与 `cards` 那条（运行继续）在语义上不同，不能合并成一个字段。
    """


@dataclass(frozen=True, slots=True)
class ToolFailure:
    """一次被拒绝或失败的工具调用。"""

    code: ToolErrorCode
    """明确错误码；调用方按它区分「越界」与「工具自身出错」。"""

    message: str
    """给模型看的说明。不得包含连接串、凭据或堆栈。"""

    def as_model_text(self) -> str:
        """渲染成回给模型的工具结果文本。

        带错误码是刻意的：模型能据此区分「我没有这个工具」与「工具执行出错」，
        前者不该重试，后者可以换个参数再试。
        """
        return f'<tool_error code="{self.code}">{self.message}</tool_error>'


ToolOutcome = ToolResult | ToolFailure
"""一次工具调用的完整可能空间：要么成功产出，要么带码失败。"""
