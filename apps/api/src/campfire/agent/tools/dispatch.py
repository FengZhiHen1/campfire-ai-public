"""工具派发：**执行前的权限门**。

依据 docs/技术设计/technical-details/通用基座.md 第 5 节：

- **权限在执行前校验，不靠隐藏 schema**；工具不可见不是安全边界；
- 越界调用由服务端拒绝——这是硬边界，与 SDK 和模型供应商都无关；
- 拒绝返回**明确错误码**，不静默降级为其他工具。

四道门的顺序是刻意的，且每道门都返回带码失败而不是抛异常（除了取消）：

1. 名字是否注册；
2. 是否在当前可用集合内（越界拒绝）；
3. 是否落在需要人工审批的档位（一期不实现 HITL，故显式拒绝而不是放行）;
4. 交给工具自己解析参数并执行。

顺序理由：先判「有没有」再判「能不能」，最后才是「参数对不对」——把不存在的工具与
越界的工具分开报码，模型才能正确决定是放弃还是换参数重试。

**运行中激活**：``activation_state`` 非空时，可用性判定 = 请求时 scope ∪ 运行中激活
（模型侧 ``skill`` 工具成功后由回调并入）。没有它，模型侧激活的 ``allowed-tools``
并集永远不生效——那是第 5 节「激活集合变化时扩大可用工具」已定而快照实现漏掉的语义。
"""

from __future__ import annotations

from .activation_state import ActivationState
from .pool import ToolPool
from .results import ToolFailure, ToolOutcome
from .scope import ToolScope
from .spec import Tool, ToolContext


class ToolDispatcher:
    """把一次模型发起的工具调用落到权限门与实现上。"""

    def __init__(
        self,
        pool: ToolPool,
        scope: ToolScope,
        *,
        context: ToolContext,
        activation_state: ActivationState | None = None,
    ) -> None:
        """绑定工具池、本次运行的范围与上下文。

        ``activation_state`` 是运行中激活的可增长集合（见模块头）；``None`` 表示
        本次运行没有运行中激活通道（未注册模型侧激活工具），行为与原先一致。
        """
        self._pool = pool
        self._scope = scope
        self._context = context
        self._activation_state = activation_state

    @property
    def declared(self) -> tuple[Tool, ...]:
        """交给模型的稳定声明（超集，按名字排序）。"""
        return self._pool.declared()

    @property
    def scope(self) -> ToolScope:
        """本次运行的工具范围。"""
        return self._scope

    def _is_active(self, name: str) -> bool:
        """可用性判定：请求时 scope ∪ 运行中激活（若有通道）。"""
        if self._activation_state is not None and name in self._activation_state.snapshot():
            return True
        return self._scope.is_active(name)

    async def dispatch(self, name: str, arguments_json: str) -> ToolOutcome:
        """执行一次工具调用；任何拒绝都以带码失败返回。

        不在这里发流式事件：``tool_call_started`` / ``tool_call_finished`` 由运行编排
        统一发出，避免同一件事有两个发出点。
        """
        tool = self._pool.tools.get(name)
        if tool is None:
            return ToolFailure(
                code="tool_not_registered",
                message=f"没有名为 {name} 的工具；可用工具见最近一条 <tool_availability>",
            )

        if not self._is_active(name):
            return ToolFailure(
                code="tool_not_available",
                message=f"工具 {name} 此刻不可用：它未被已激活的 skill 授权",
            )

        if tool.requires_approval or tool.risk != "low":
            return ToolFailure(
                code="tool_requires_approval",
                message=f"工具 {name} 需要人工审批（风险 {tool.risk}），本次运行无法执行",
            )

        return await tool.invoke(self._context, arguments_json)
