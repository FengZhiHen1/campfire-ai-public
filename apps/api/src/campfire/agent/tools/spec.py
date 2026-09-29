"""工具注册形状与调用上下文。

依据 docs/技术设计/technical-details/通用基座.md 第 5 节：

```text
ToolSpec:
    name
    description
    parameters      # JSON Schema
    handler         # 由产品侧注册
    risk            # low | medium | high（一期全为 low）
    requires_approval: bool
```

三处刻意的收口：

1. **JSON Schema 与参数校验同源**：``parameters`` 由 ``args_model`` 的 Pydantic 模型
   导出，而不是手写一份 schema 再单独写一份校验。手写两份必然漂移，而漂移的方向恰好是
   最坏的方向——schema 说必填、校验说可选。
2. **工具名的形状契约定义在 ``skill_runtime.skill``**，本模块复用它（不另写一条正则）：
   ``allowed-tools`` 是作者写下工具名的地方，契约放那一侧可避免两个子包互相 import。
   校验用 ``fullmatch``——``$`` 会放过尾随换行，而带换行的工具名足以撑破
   ``<tool_availability>`` 信封。
3. **工具名字面量不含任何领域词**：基座不知道自己被用在哪件事上。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from agents.function_schema import ensure_strict_json_schema
from pydantic import BaseModel, ValidationError

from campfire.agent.context import CitationRecorder
from campfire.agent.skill_runtime import TOOL_NAME_PATTERN

from .activation_state import ActivationState
from .errors import ToolSpecError
from .results import ToolFailure, ToolOutcome

logger = logging.getLogger("campfire.agent.tools")

RiskLevel = Literal["low", "medium", "high"]
"""工具风险档。一期全部为 ``low``，因此不实现人工审批（基座第 5 节）。"""

# TOOL_NAME_PATTERN 从 skill_runtime 复用：``allowed-tools`` 与工具池注册必须是同一条
# 名字契约，两处各写一条正则会慢慢分叉。契约的落点与理由见 skill_runtime/skill.py。
__all__ = [
    "TOOL_NAME_PATTERN",
    "RiskLevel",
    "Tool",
    "ToolContext",
    "ToolHandler",
    "ToolSpec",
]

_NAME_MAX_LENGTH = 64
_DESCRIPTION_MAX_LENGTH = 1024

ArgsT = TypeVar("ArgsT", bound=BaseModel)

ToolHandler = Callable[["ToolContext", ArgsT], Awaitable[ToolOutcome]]
"""产品侧注册的工具实现：拿到解析后的参数，返回产出。

返回类型允许是 :class:`~campfire.agent.tools.ToolFailure`——工具可以**显式声明一次可恢复
失败并带上错误码**（例如「你要激活的 skill 不存在」），而不是只能靠抛异常把细节丢掉。
"""


@dataclass(frozen=True, slots=True)
class ToolContext:
    """一次工具调用的上下文。

    基座能说的只有运行层面的事实。产品侧的领域事实（支持对象标识之类）经 ``payload``
    透传：**基座不解读它，也不保证形状**——产品侧 handler 必须自己显式解析，
    把「以为拿到的是 X」变成一次明确的失败，而不是一次隐性的错算。

    ``activated_skills`` 是**属性**而非冻结字段：它读 ``activation_state`` 的实时快照，
    模型侧激活（运行中调 ``skill`` 工具）并入后，后续工具调用立即看到新状态——
    ``read_skill_resource`` 的授权判定依赖这一点。这里取的是 **skill 名**命名空间；
    工具名的并集由 dispatcher 取（见 ``activation_state`` 模块头）。
    """

    run_id: str
    """本次运行标识。"""

    session_id: str
    """本次对话标识。"""

    surface: str | None
    """当前面；``None`` 表示未指定。"""

    activation_state: "ActivationState"
    """运行时激活状态（共享、可增长）；skill 名与预授权工具集的唯一事实来源。"""

    citations: CitationRecorder
    """引用写入端。工具要产出引用**只能**经它，因此引用与索引记录不会脱钩。"""

    payload: object | None = None
    """装配处放入的每次运行的领域事实；基座不解读。"""

    @property
    def activated_skills(self) -> frozenset[str]:
        """本次运行已激活的 skill 名（含运行中模型侧激活）。"""
        return self.activation_state.skill_names()


class Tool(Protocol):
    """工具池里的一个工具（结构类型）。

    存在的理由是类型而不是抽象：:class:`ToolSpec` 对参数模型是泛型的，而工具池要装
    不同参数模型的工具。有了这个不含泛型参数的结构类型，工具池不必退化成 ``Any``。
    """

    name: str
    """工具名。"""

    description: str
    """给模型看的说明。"""

    risk: RiskLevel
    """风险档。"""

    requires_approval: bool
    """是否需要人工审批。"""

    @property
    def parameters(self) -> dict[str, object]:
        """参数的 JSON Schema。"""
        ...

    async def invoke(self, context: ToolContext, arguments_json: str) -> ToolOutcome:
        """解析参数并调用实现；参数不合法时返回 ``tool_invalid_arguments``。"""
        ...


@dataclass(frozen=True, slots=True)
class ToolSpec(Generic[ArgsT]):
    """一个工具的注册形状。"""

    name: str
    description: str
    args_model: type[ArgsT]
    handler: ToolHandler[ArgsT]
    risk: RiskLevel = "low"
    requires_approval: bool = False

    def __post_init__(self) -> None:
        """校验名字、描述与**参数 schema 能否通过严格模式**。

        Raises:
            ToolSpecError: 名字不符合 :data:`TOOL_NAME_PATTERN`（或超长）、描述为空或超长，
                或参数 schema 无法被 SDK 的严格模式接受。
        """
        if not TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ToolSpecError(f"工具名 {self.name!r} 不合法：只允许小写字母、数字与下划线，且以字母开头")
        if len(self.name) > _NAME_MAX_LENGTH:
            raise ToolSpecError(f"工具名 {self.name!r} 超过 {_NAME_MAX_LENGTH} 字符")
        if not self.description.strip():
            raise ToolSpecError(f"工具 {self.name} 的描述不能为空：描述是模型选择工具的唯一依据")
        if len(self.description) > _DESCRIPTION_MAX_LENGTH:
            raise ToolSpecError(f"工具 {self.name} 的描述超过 {_DESCRIPTION_MAX_LENGTH} 字符")
        self._require_strict_schema()

    def _require_strict_schema(self) -> None:
        """在**注册期**确认参数 schema 能被 SDK 的严格模式接受。

        为什么必须提前：``ensure_strict_json_schema`` 由 SDK 在**构造工具时**调用，而那一刻
        运行已经发出 ``run_started`` 了——实测参数模型含开放对象（``dict[str, int]``、
        ``extra="allow"``）时抛裸 ``UserError``，事件流只到 ``run_started`` 就断，调用方拿不到
        任何 ``run_failed``。注册期就失败，问题是配置错误，而不是一次半截的运行。

        Raises:
            ToolSpecError: schema 含开放对象等严格模式不支持的结构。
        """
        try:
            ensure_strict_json_schema(self.parameters)
        except Exception as exc:  # noqa: BLE001 —— SDK 的 UserError 也要变成我们的配置错误
            raise ToolSpecError(
                f"工具 {self.name} 的参数 schema 无法通过严格模式（{type(exc).__name__}）："
                "参数模型不要使用开放对象（例如 dict[str, X]）或 extra='allow'"
            ) from exc

    @property
    def parameters(self) -> dict[str, object]:
        """参数的 JSON Schema，由 ``args_model`` 导出（按需生成）。"""
        return dict(self.args_model.model_json_schema())

    async def invoke(self, context: ToolContext, arguments_json: str) -> ToolOutcome:
        """解析参数并调用实现。

        解析失败是**显式状态**（``tool_invalid_arguments``），不是异常；实现自身抛出的
        异常转成 ``tool_failed`` 回给模型，只带异常类型名——异常消息里可能带连接串或
        凭据，不得进入对话与日志（见 AGENTS.md 安全条款）。实现若显式返回
        :class:`~campfire.agent.tools.ToolFailure`，则原样透传（它自己选了错误码）。

        ``asyncio.CancelledError`` 继承自 ``BaseException``，因此不会被下面的
        ``except Exception`` 吞掉：取消必须优先于工具自身的失败处置。
        """
        parsed = self._parse(arguments_json)
        if isinstance(parsed, ToolFailure):
            return parsed

        try:
            return await self.handler(context, parsed)
        except Exception as exc:  # noqa: BLE001 —— 失败语义要求把工具错误作为结果回给模型
            logger.warning("工具执行失败 tool=%s error=%s", self.name, type(exc).__name__)
            return ToolFailure(code="tool_failed", message=f"工具 {self.name} 执行失败（{type(exc).__name__}）")

    def _parse(self, arguments_json: str) -> ArgsT | ToolFailure:
        """把模型给的 JSON 字符串解析成参数模型。"""
        # 无参工具的调用可能给空串；把它当作空对象，而不是一次「参数不合法」的误报。
        text = arguments_json.strip() or "{}"
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return ToolFailure(code="tool_invalid_arguments", message=f"工具 {self.name} 的参数不是合法 JSON")

        if not isinstance(raw, dict):
            return ToolFailure(code="tool_invalid_arguments", message=f"工具 {self.name} 的参数必须是对象")

        try:
            return self.args_model.model_validate(raw)
        except ValidationError as exc:
            return ToolFailure(code="tool_invalid_arguments", message=self._summarize(exc))

    def _summarize(self, error: ValidationError) -> str:
        """把校验错误压成一行可读说明；**不回显输入值**（可能含使用者资料）。"""
        problems = "；".join(
            f"{'.'.join(str(part) for part in item['loc']) or '(根)'}: {item['type']}" for item in error.errors()
        )
        return f"工具 {self.name} 的参数不符合 schema：{problems}"
