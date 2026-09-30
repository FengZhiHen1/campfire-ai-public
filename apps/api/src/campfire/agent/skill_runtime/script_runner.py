"""`scripts/` 运行器端口——一期不实现，只保留端口。

职责：声明脚本运行器的调用形状，供将来接入。
边界：一期不提供任何实现，也不预先发明参数结构、退出码与结果类型。
参考：docs/技术设计/technical-details/通用基座.md 第 10 节。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ScriptRunner(Protocol):
    """执行 skill `scripts/` 下脚本的端口。

    依据 docs/技术设计/technical-details/通用基座.md 第 10 节：脚本运行器属扩展缝，
    启用条件是「出现必须自带脚本的 skill，且有受限执行环境」。因此这里只声明形状，
    不提供任何实现，也不预先发明参数结构、退出码与结果类型——那些应当随第一个真实
    消费者一起定，现在发明只会得到一份没人用过的契约。

    同时是为了让「基座不认识 `scripts/`」这件事有一个可检索的落点：将来有人问
    「skill 的脚本在哪执行」，答案是这个文件，而不是一段散落的注释。

    一期没有任何实现：调用方若拿到 `None`，正确处置是显式失败并说明脚本执行
    不可用，而不是当作「脚本没有输出」继续。
    """

    async def run(self, *, skill_name: str, relative_path: str, timeout_seconds: float) -> str:
        """执行一个脚本并返回其标准输出；失败必须以异常表达。"""
        ...
