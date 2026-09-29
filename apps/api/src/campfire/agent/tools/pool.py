"""工具池：注册、稳定声明与启动期校验。

依据 docs/技术设计/technical-details/通用基座.md 第 5 节与 docs/项目结构设计.md 第 7 节：

- **工具注册在装配处完成**（``main.py`` / ``worker.py``），因此 ``agent/*`` 不需要
  import ``tools/*``（产品侧工具包）。
- **声明保持稳定**：请求里的 ``tools`` 数组在一条对话内不变（超集）。这是缓存纪律的
  要求——声明一变前缀就变，缓存从变化处失效。因此 :meth:`ToolPool.declared` 按名字
  排序返回固定顺序，而不是跟随注册顺序。
- 工具池是**超集**：``allowed-tools`` 不限制池子，它只选出「此刻可用」的子集。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType

from campfire.agent.skill_runtime import Skill

from .errors import ToolNotRegisteredError, ToolRegistrationError
from .spec import Tool

RESERVED_TOOL_NAMES: frozenset[str] = frozenset({"skill"})
"""基座保留的工具名。

``skill`` 是**模型侧激活**用的工具名（基座文档第 3 节：模型调用 ``skill({ name })``）。
产品侧工具不得占用它——否则模型侧的激活工具要么被顶掉、要么与产品工具同名，而
``allowed-tools`` 与实际派发都以名字为键，重名会让权限判定面对一个含义不明的名字。
保留名的注册走 :meth:`ToolPool.register_base`。
"""


class ToolPool:
    """已注册工具的集合。"""

    def __init__(self, tools: Sequence[Tool] = ()) -> None:
        """按顺序注册初始工具；重名立即失败。"""
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        """注册一个**产品侧**工具。

        Raises:
            ToolRegistrationError: 同名工具已注册，或用了基座保留名
                （见 :data:`RESERVED_TOOL_NAMES`）。不覆盖、不忽略——重名会让权限判定
                面对一个含义不明的名字。
        """
        if tool.name in RESERVED_TOOL_NAMES:
            raise ToolRegistrationError(f"工具名 {tool.name} 是基座保留名（模型侧激活工具）：产品侧工具不得占用")
        self._register(tool)

    def register_base(self, tool: Tool) -> None:
        """注册一个**基座自有**工具，允许使用保留名。

        与 :meth:`register` 分开是为了让「这个工具属于基座还是产品侧」在调用点就可见；
        两者的重名规则不同，混在一个方法里就只能靠注释说明。
        """
        self._register(tool)

    def _register(self, tool: Tool) -> None:
        """实际写入；重名一律拒绝。"""
        if tool.name in self._tools:
            raise ToolRegistrationError(f"工具 {tool.name} 重复注册")
        self._tools[tool.name] = tool

    @property
    def tools(self) -> Mapping[str, Tool]:
        """已注册工具，按名字索引的只读视图。"""
        return MappingProxyType(self._tools)

    def names(self) -> tuple[str, ...]:
        """已注册工具名（字典序，稳定）。"""
        return tuple(sorted(self._tools))

    def declared(self) -> tuple[Tool, ...]:
        """请求里交给模型的**稳定声明**（超集，按名字排序）。"""
        return tuple(self._tools[name] for name in self.names())

    def get(self, name: str) -> Tool:
        """按名字取工具。

        Raises:
            ToolNotRegisteredError: 名字未注册。
        """
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotRegisteredError((name,), self.names()) from exc

    def ensure_names_are_registered(self, names: Iterable[str]) -> None:
        """校验一组名字都存在（用于 ``allowed-tools`` 与面配置的默认可用集）。

        Raises:
            ToolNotRegisteredError: 存在未注册的名字；``names`` 属性带全部缺失项。
        """
        missing = tuple(sorted({name for name in names if name not in self._tools}))
        if missing:
            raise ToolNotRegisteredError(missing, self.names())

    def ensure_skills_are_resolvable(self, skills: Sequence[Skill]) -> None:
        """启动期校验：每个 skill 的 ``allowed-tools`` 都必须指向已注册工具。

        在启动时跑一次，是为了让 skill 作者的名字笔误在**启动**就暴露，而不是等到
        某个 skill 第一次被激活时的那次运行。一次报出全部问题。

        Raises:
            ToolNotRegisteredError: 存在指向未注册工具的 ``allowed-tools``。
        """
        missing: set[str] = set()
        for skill in skills:
            missing.update(name for name in skill.metadata.allowed_tools if name not in self._tools)
        if missing:
            raise ToolNotRegisteredError(tuple(sorted(missing)), self.names())
