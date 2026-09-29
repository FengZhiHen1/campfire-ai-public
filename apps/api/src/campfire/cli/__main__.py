"""``python -m campfire.cli`` 的入口。

**当前只报告未实现，不假装可用**：摄取流水线依赖 LlamaIndex 的摄取与嵌入适配，
而技术栈设计的 ``TECH-14`` 四点（``PGVectorStore`` 自带表结构能否承载我们的
item/chunk 与状态字段、元数据过滤是否真在 SQL 层执行、分块能否保证不切断表格与
列表项、版本节奏与依赖体量）**尚未核实**，未核实前不写首版摄取实现。

入口形态按设计接好（``python -m campfire.cli ingest <路径>``），
因此退出码 2 并说明缺什么，而不是静默成功或抛栈。
"""

import sys

_NOT_IMPLEMENTED_MESSAGE = (
    "campfire.cli 的摄取尚未实现。\n"
    "设计的入口形态：python -m campfire.cli ingest <路径>\n"
    "阻塞项：LlamaIndex 摄取与嵌入适配未落地，且 TECH-14 四点待核实\n"
    "依据：docs/技术设计/technical-details/RAG策略.md 第 7 节\n"
)


def main() -> int:
    """入口点。返回退出码而不是 ``sys.exit``，便于测试直接断言。"""
    print(_NOT_IMPLEMENTED_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
