"""运行时激活集合：一次运行内可增长的激活状态。

为什么需要它：基座第 5 节定的是「激活集合变化时扩大可用工具」，但 ``ToolScope`` 与
``ToolContext`` 都是运行开始时的**冻结快照**——模型在运行中调 ``skill`` 工具激活后，
快照不更新，后果有两个：① 激活 skill 的 ``allowed-tools`` 并集不生效，模型侧激活的
工具调用被「未被已激活的 skill 授权」拒绝；② ``read_skill_resource`` 这类依赖激活态的
工具读到过期状态。

解法是一个**共享的可变集合**：``resolve_scope`` 算出的初始激活集并入它，模型侧激活
回调（``build_skill_tool(on_activated=...)``）往里加名字；dispatcher 的范围判定与
``ToolContext.activated_skills`` 都改为读它的实时快照。冻结形状不变——对外仍然是
frozenset，只是取值时现算。

放在 ``tools`` 而不是 ``runtime``：它是工具范围机制的一部分（dispatcher 与
``ToolContext`` 都要读它），而 ``runtime`` 反过来要用 ``tools``——放 ``runtime``
会形成反向依赖。

设计边界（刻意不做的事）：

- **不回写 ``RunRequest`` 或会话**：运行时激活只影响**本次运行**的工具可用性与资源
  读取；下一次运行仍由请求显式携带激活集合（应用侧注入）。模型侧激活的持久化是
  「下一轮请求怎么构造」的问题，属面的职责，不归基座运行编排。
- **不在这里发可用性告知消息**：消息注入发生在运行边界（基座第 2 节），运行中
  扩大的可用性靠 dispatcher 的实际放行表达——模型调用成功即知道可用，无需在
  运行中伪造一条注入消息（那正是第 2 节「注入都发生在运行边界」排除的形状）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActivationState:
    """一次运行的激活名字集合（可增长）。"""

    _names: set[str] = field(default_factory=set)

    def add(self, name: str) -> None:
        """并入一个激活名（模型侧激活回调调用）。"""
        self._names.add(name)

    def update(self, names: frozenset[str]) -> None:
        """并入初始激活集合（运行开始时调用一次）。"""
        self._names.update(names)

    def snapshot(self) -> frozenset[str]:
        """当前激活名的实时快照。"""
        return frozenset(self._names)
