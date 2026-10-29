"""三组适配器的共同形状：一次「轮」的输入输出契约与状态词表。

职责：定义 :class:`TurnInput` / :class:`TurnOutcome` / :class:`SystemAdapter`，以及
状态归一（`completed` / `no_output` / `timeout` / `error`）。

边界：不做 I/O、不构造模型或工具——各适配器自己装配（`direct.py` / `rag.py` / `agent.py`）。

状态词表只有四种，且**只描述工程事实**：

- `completed`：运行正常结束且有可见正文；
- `no_output`：运行正常结束但没有任何正文（模型空回复）；
- `timeout`：超过评测工具的墙钟上限；
- `error`：运行明确失败（模型不可用、会话写入失败、工具/检索装配失败等）。

「明确拒答」不在这里判定：它是评审者的判断（协议 03 第 3 节把 `completion_status`
的取值与合理性都交给人工）。自动层面只给 :func:`campfire.prompts.refusal_suspected`
那类**线索**，且不参与分母计算的状态归一。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..cases import Case

#: 状态：正常结束且有正文。
STATUS_COMPLETED = "completed"
#: 状态：正常结束但无正文。
STATUS_NO_OUTPUT = "no_output"
#: 状态：超过评测工具的单轮墙钟上限。
STATUS_TIMEOUT = "timeout"
#: 状态：明确失败。
STATUS_ERROR = "error"

#: 合法的状态取值（落盘前校验，避免拼错的状态静默进入统计）。
ALL_STATUSES = (STATUS_COMPLETED, STATUS_NO_OUTPUT, STATUS_TIMEOUT, STATUS_ERROR)


@dataclass(frozen=True)
class TurnInput:
    """一次（案例 × 组别 × 轮次）的输入。"""

    case: Case
    system_id: str
    turn: int
    session_id: str
    account_id: str
    attempt: int = 1

    @property
    def group_key(self) -> str:
        """case-group 的稳定键（案例 × 组别）：分母与续跑都以它为单位。"""
        return f"{self.case.id}::{self.system_id}"


@dataclass
class TurnOutcome:
    """一次轮次的产出：原始正文、工程事实与轨迹。

    `trace` 是给 `traces/<...>.json` 的整份证据（工具事件、检索材料、消息体等），
    `raw_output` 不因任何原因改写：失败时它就是空串，原因写在 `error_*`。
    """

    status: str
    raw_output: str = ""
    latency_ms: int = 0
    usage: dict[str, int] | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error_type: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验状态词表（拼错的状态会让统计静默偏离）。"""
        if self.status not in ALL_STATUSES:
            raise ValueError(f"未知状态 {self.status!r}：只允许 {ALL_STATUSES}")


@dataclass(frozen=True)
class SystemMeta:
    """组别的装配事实（进 manifest 的 `systems[]`）。"""

    system_id: str
    label: str
    assembly: str
    model_id: str
    prompt_sha256: str
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """规范字典。"""
        return {
            "system_id": self.system_id,
            "label": self.label,
            "assembly": self.assembly,
            "model_id": self.model_id,
            "prompt_sha256": self.prompt_sha256,
            "notes": dict(self.notes),
        }


@runtime_checkable
class SystemAdapter(Protocol):
    """一个组别的适配器。

    生命周期由 runner 驱动：`prepare()` 一次 → 每个 case-group `open_case()` →
    每轮 `run_turn()` → 批次结束 `aclose()`。
    """

    system_id: str

    async def prepare(self) -> SystemMeta:
        """装配并返回本组的装配事实（失败即抛：装配失败不得当成「模型不行」）。"""
        ...

    async def open_case(
        self,
        *,
        case: Case,
        session_id: str,
        account_id: str,
        prior_turns: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """为一个 case-group 建立隔离会话（新会话、无历史、无关记忆清空）。

        `prior_turns` 只在续跑时非空：进程重启后 A/B 的内存历史要从已落盘的
        （使用者文本, 助手正文）重建，否则「第二轮」会变成一段全新对话的第一轮。
        C 组不用它——对话真源在库里。
        """
        ...

    async def run_turn(self, request: TurnInput) -> TurnOutcome:
        """跑一轮并返回原始产出。"""
        ...

    async def aclose(self) -> None:
        """释放本组持有的资源。"""
        ...


__all__ = [
    "ALL_STATUSES",
    "STATUS_COMPLETED",
    "STATUS_ERROR",
    "STATUS_NO_OUTPUT",
    "STATUS_TIMEOUT",
    "SystemAdapter",
    "SystemMeta",
    "TurnInput",
    "TurnOutcome",
]
