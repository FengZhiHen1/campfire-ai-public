"""上下文层的错误类型。

只有两类失败需要区分：引用索引的记录不合法（调用方参数问题），与注入项本身不合法。
索引写入失败不在这里包装——那是持久化异常，必须原样冒泡，不能被降级成「来源不可用」。
"""

from __future__ import annotations


class ContextError(Exception):
    """上下文层的基类错误。"""


class CitationError(ContextError):
    """引用记录不合法：缺标识、缺来源或缺业务回指。

    没有索引记录的注入消息不得成为「可引用依据」（基座文档第 4 节不变量），因此
    构造一条引用记录时就要求三者齐全——不能让「半条引用」存在。
    """


class InjectionError(ContextError):
    """注入项不合法：缺来源/内容，或出现了不被允许的消息角色。"""
