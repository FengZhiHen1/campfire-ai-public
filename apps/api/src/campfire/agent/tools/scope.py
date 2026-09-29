"""工具范围：**声明保持稳定，可用性用消息告知，越界调用服务端拒绝**。

依据 docs/技术设计/technical-details/通用基座.md 第 5 节「工具范围随激活集合变化」：

- 声明是超集且在一条对话内不变（缓存纪律）；
- 可用性（active 子集）随激活集合变化，变化时**追加一条消息**告知模型；
- 服务端按请求与参数校验权限——**暴露范围不是安全边界**。

两条解读写清楚，免得后来者以为是随手定的：

1. **有激活集合时，active = 各激活 skill 的 ``allowed-tools`` 并集**，不再叠加面配置的
   默认可用集。依据是第 5 节不变量：「未激活任何 skill 时只有面配置的默认可用集」——
   默认集是「无激活」时的兜底，不是常驻底集。技能设计第 3 节也据此把应急工具集写成
   只读资料与案例，与默认集并不相同。
2. **``allowed-tools`` 指向未注册工具时直接失败**，不静默收窄。静默收窄会把 skill 作者
   的笔误藏起来，让「以为能用这个工具」的 skill 静默地少一件工具。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from campfire.agent.context import InjectionItem, InjectionPriority
from campfire.agent.skill_runtime import Skill

from .pool import ToolPool

AVAILABILITY_SOURCE = "tool-availability"
"""可用性告知消息的来源标识（同时出现在引用索引与运行记录里）。"""


@dataclass(frozen=True, slots=True)
class ToolScope:
    """一次运行的工具可见范围。"""

    declared: tuple[str, ...]
    """已声明的工具（超集，字典序）。"""

    active: frozenset[str]
    """此刻可用的工具。"""

    activated_skills: frozenset[str]
    """产出这个范围的激活集合。"""

    def is_active(self, name: str) -> bool:
        """该工具此刻是否可用。"""
        return name in self.active

    def unavailable(self) -> tuple[str, ...]:
        """已声明但此刻不可用的工具（字典序）。"""
        return tuple(name for name in self.declared if name not in self.active)

    def availability_item(self) -> InjectionItem:
        """把「此刻可用/不可用」渲染成一条注入消息。

        不可用的部分也要写出来：第 5 节的不变量要求「激活前，该 skill 的工具虽已声明，
        但模型被明确告知不可用」。只报可用项达不到这条要求——模型会把「没提到」读成
        「可以用」。
        """
        lines = ["<tool_availability>", "  <available_tools>"]
        lines.extend(f'    <tool name="{name}" />' for name in sorted(self.active))
        lines.append("  </available_tools>")

        unavailable = self.unavailable()
        if unavailable:
            lines.append("  <unavailable_tools>")
            lines.extend(f'    <tool name="{name}" />' for name in unavailable)
            lines.append("  </unavailable_tools>")
        lines.append("</tool_availability>")

        return InjectionItem(
            source=AVAILABILITY_SOURCE,
            content="\n".join(lines),
            priority=InjectionPriority.TOOL_AVAILABILITY,
        )


# quality-floor: ignore docstring-promise 异常由 pool.ensure_names_are_registered 抛出，本函数体无 raise
def resolve_scope(
    pool: ToolPool,
    *,
    activated: Sequence[Skill] = (),
    default_active: Iterable[str] = (),
) -> ToolScope:
    """按激活集合解析出本次运行的工具范围。

    Raises:
        ToolNotRegisteredError: 激活 skill 的 ``allowed-tools`` 或 ``default_active``
            里出现了未注册的工具名。
    """
    names = pool.names()

    if activated:
        active = frozenset(name for skill in activated for name in skill.metadata.allowed_tools)
    else:
        active = frozenset(default_active)

    pool.ensure_names_are_registered(active)

    return ToolScope(
        declared=names,
        active=active,
        activated_skills=frozenset(skill.name for skill in activated),
    )
