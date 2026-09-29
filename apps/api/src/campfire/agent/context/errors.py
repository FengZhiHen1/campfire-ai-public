"""上下文层的错误类型。

三类失败各自有明确归属：引用记录不合法（参数问题）、注入项不合法（形状问题）、
注入渲染写到一半失败（**部分已落库**，调用方必须知道）。索引写入的一般性失败不在这里
包装——它是持久化异常，必须带着「已写了哪几条」的事实冒泡。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .citations import CitationRecord
    from .injection import InjectionMessage


class ContextError(Exception):
    """上下文层的基类错误。"""


class CitationError(ContextError):
    """引用记录不合法：缺标识、缺来源或缺业务回指。

    没有索引记录的注入消息不得成为「可引用依据」（基座文档第 4 节不变量），因此
    构造一条引用记录时就要求三者齐全——不能让「半条引用」存在。
    """


class InjectionError(ContextError):
    """注入项不合法：缺来源/内容，或出现了不被允许的消息角色。"""


class InjectionRenderError(ContextError):
    """注入批量渲染**写到一半失败**。

    这不是「某条注入不合法」，而是「已经写了一半」：索引里可能留下了记录，而窗口里
    一条消息都没有。因此本错误携带 ``recorded``（已落索引的引用）与 ``rendered``
    （已渲染的消息），让调用方能把本次运行标为注入失败，而不是当作「没有注入」继续——
    否则 ``run_finished`` 会报出一条模型从未看到的依据。

    ``detail`` 只带异常**类型名**，不带原始消息：原始消息可能含连接串与凭据
    （见 AGENTS.md 安全条款）。
    """

    def __init__(
        self,
        detail: str,
        *,
        recorded: tuple["CitationRecord", ...] = (),
        rendered: tuple["InjectionMessage", ...] = (),
    ) -> None:
        """记录失败说明、已落索引的引用与已渲染的消息。"""
        self.recorded = recorded
        self.rendered = rendered
        super().__init__(detail)
