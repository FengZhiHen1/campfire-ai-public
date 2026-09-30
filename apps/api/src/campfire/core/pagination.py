"""面层共用的偏移量游标解析。

职责：把「十进制偏移量」形状的游标串解析成整数偏移量；形状非法返回 None，
      由调用方按各自的错误映射转 422。
边界：只做形状判定与解析，不产出错误响应，也不持有各面的分页窗口与单页条数
      上界——那些是各面自己的常量（如资料库面的 `ITEMS_MAX_LIMIT`）。
为什么放 core：多个面需要同一个形状闸门，各写一份就会漂移；而这份闸门必须与
      `int()` 的输入域严格同域，漂移的代价是「校验通过但解析抛错」——未捕获的
      `ValueError` 在生产上是 500，而契约要的是 422。
参考：无（本模块的理由自足，不引任何面文档）。
"""

from __future__ import annotations

#: 偏移量游标的位数上界（CORE-11：输入有界）。
#:
#: 上界不是防御性装饰，它挡住一条实测的 500 路径：CPython 3.11 起 `int()` 对超过
#: 4300 位的字符串抛 `ValueError`（整数串转换上限），一个 5000 位游标因此会从
#: 「形状合法」走到「解析抛错」。真实的游标位数远小于它——由本面产生的游标是
#: `PAGE_WINDOW_MAX`（三位数）量级的偏移量。
_MAX_CURSOR_DIGITS = 18

__all__ = ["parse_offset_cursor"]


def parse_offset_cursor(cursor: str | None) -> int | None:
    """把偏移量游标解析成整数；None 表示非法（由调用方转 422）。

    闸门与解析器必须同域，否则「校验通过」与「解析成功」是两件事。实测的两个反向
    例子（2026-10-01，本仓探针）：

    - `str.isdigit()` 对 Unicode 上标数字 `²` 为真，而 `int('²')` 抛 `ValueError`：
      闸门放过了解析不了的输入，未捕获异常 → 500（契约要 422）；
    - `str.isdigit()` 对全角数字 `１２３` 为真且 `int()` 成功，于是从未发出过的
      偏移量 123 被静默接受——「游标只由本面产生」这条不变量没有被真的守住。

    反过来，只写 `try: int(cursor)` 也不够：`int()` 接受正负号、首尾空白与下划线
    （`'+12'`、`' 12 '`、`'1_2'`），那是把闸门放宽到解析器的整个输入域。

    因此这里给出显式的形状：ASCII 十进制数字，且位数不超过
    :data:`_MAX_CURSOR_DIGITS`。在这个形状上 `int()` 必然成功——不存在能抛
    `ValueError` 的输入，闸门即解析器。

    Args:
        cursor: 查询串里的游标；None 表示未给（首页，偏移量 0）。

    Returns:
        偏移量（未给时为 0）；形状非法时返回 None。
    """
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdigit() or len(cursor) > _MAX_CURSOR_DIGITS:
        return None
    return int(cursor)
