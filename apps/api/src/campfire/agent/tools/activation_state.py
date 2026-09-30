"""运行时激活状态：一次运行内可增长的「已激活 skill」与其「预授权工具集」。

职责：维护一次运行内可增长的已激活 skill 名与预授权工具集，供运行中的可用性
判定与资源读取看到最新状态。
边界：不回写 `RunRequest` 或会话；不在运行中注入可用性告知消息（注入只发生在
运行边界，由运行编排负责）。
参考：docs/技术设计/technical-details/通用基座.md 第 5 节、第 2 节。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class ActivationState:
    """一次运行的激活状态：skill 名与预授权工具集，分两个命名空间维护。

    为什么需要它：基座第 5 节定的是「激活集合变化时扩大可用工具」，但 `ToolScope` 与
    `ToolContext` 都是运行开始时的冻结快照——模型在运行中调 `skill` 工具激活后，
    快照不更新，后果有两个：① 激活 skill 的 `allowed-tools` 并集不生效，模型侧激活的
    工具调用被「未被已激活的 skill 授权」拒绝；② `read_skill_resource` 这类依赖激活态的
    工具读到过期状态。

    两个命名空间必须分开维护（这是本模块存在的第二个理由）：已激活的是 skill 名，
    可放行的是 工具名；两者都以 `str` 表示，语义却不同。第一版只存一集合、把 skill 名
    当工具名判定，于是双向都错：模型侧激活的 `allowed-tools` 永不生效（fail-closed），
    而池里与 skill 同名的工具被无条件放行（fail-open，等价于「激活 skill 即授权同名工具」）。
    因此本类只在 :meth:`activate` 一处同时写入两个命名空间，且两个参数强制关键字传参：
    位置传参会把 skill 名喂进工具集合，类型检查器看不见这类错，只能由签名挡住。

    设计边界（刻意不做的事）：

    - 不回写 `RunRequest` 或会话：运行时激活只影响本次运行的工具可用性与资源
      读取；下一次运行仍由请求显式携带激活集合（应用侧注入）。模型侧激活的持久化是
      「下一轮请求怎么构造」的问题，属面的职责，不归基座运行编排。
    - 不在这里发可用性告知消息：消息注入发生在运行边界（基座第 2 节），运行中
      扩大的可用性靠 dispatcher 的实际放行表达——模型调用成功即知道可用，无需在
      运行中伪造一条注入消息（那正是第 2 节「注入都发生在运行边界」排除的形状）。
    """

    _skill_names: set[str] = field(default_factory=set)
    _allowed_tools: set[str] = field(default_factory=set)

    def seed(self, skill_names: Iterable[str]) -> None:
        """并入运行开始时的激活 skill 名。

        不并工具集：那批工具已由 `ToolScope` 放行（dispatcher 的判定本身就是
        「scope ∪ 本状态」的并集），重复并入只会多一份会漂移的真相。
        """
        self._skill_names.update(skill_names)

    def activate(self, *, skill_name: str, allowed_tools: Iterable[str]) -> None:
        """并入运行中激活的一个 skill：它的名字，以及它预授权的工具名。

        名字与工具集在同一处并入，因此「激活了 skill 却没并工具」这类半边状态不可表示。
        """
        self._skill_names.add(skill_name)
        self._allowed_tools.update(allowed_tools)

    def skill_names(self) -> frozenset[str]:
        """当前已激活的 skill 名快照（供按 skill 判定的工具使用，如资源读取）。"""
        return frozenset(self._skill_names)

    def allowed_tools(self) -> frozenset[str]:
        """运行中激活带来的 工具名 并集快照（供 dispatcher 的可用性判定使用）。

        只报本状态新增的部分；请求时的 `ToolScope.active` 由 scope 承担。
        """
        return frozenset(self._allowed_tools)
