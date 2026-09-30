"""工具池的错误类型。

只覆盖配置与编程错误：注册重复、名字不合法、引用未注册的工具。运行期的失败
（越界调用、参数不合法、工具自身报错）不是异常，而是带明确错误码的结果——它们要回给
模型，见 :mod:`campfire.agent.tools.results`。
"""

from __future__ import annotations


class ToolError(Exception):
    """工具池的基类错误。"""


class ToolSpecError(ToolError):
    """注册形状不合法：名字或描述不合规。"""


class ToolRegistrationError(ToolError):
    """重复注册同名工具。

    不覆盖、不静默保留先注册的那个：工具名是权限判定与 `allowed-tools` 的键，
    重名意味着权限判定面对一个含义不明的名字。
    """


class ToolNotRegisteredError(ToolError):
    """引用了一个没有注册的工具名。

    两种来源：装配处直接取用未注册工具；或某个 skill 的 `allowed-tools` 指向了
    不存在的工具。后者是配置错误——静默收窄工具集会把 skill 作者的笔误藏起来。
    """

    def __init__(self, names: tuple[str, ...], known: tuple[str, ...]) -> None:
        """记录找不到的名字与当前已注册的名字。"""
        self.names = names
        self.known = known
        super().__init__(f"未注册的工具 {list(names)}（已注册：{', '.join(known) or '无'}）")
