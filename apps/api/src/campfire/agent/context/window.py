"""模型窗口的派生：只裁模型看到的上下文，不动落库的对话。

依据 docs/技术设计/technical-details/压缩策略.md：

- 第 5 节：摘要作为**一条消息追加**进会话；此后**窗口 = ``[系统提示]`` + ``[最后一条
  摘要消息起的全部历史]``**。这条规则可完全从会话历史推导，因此不另存「窗口配方」。
- 第 8 节第 1 条：**只在末尾追加**；不改写、不插入、不重排历史消息；**不得做滑动
  窗口**——从头部裁剪等于移动前缀，每轮全量击穿缓存。窗口因此只能是「前缀 + 后缀」
  两段拼接，绝不是「保留最近 N 条」。
- 第 3 节：**系统提示永不被遮蔽**，所以前导 system 消息原样留在窗口最前。

以及基座文档「已知偏差」里的一条实测约束：读回顺序契约虽然存在，但官方没把
``limit=None`` 的读回顺序写成硬保证，所以**定位最后一条摘要消息靠内容里的
``<compacted-summary>`` 标签，而不是靠顺序**。

本模块是纯函数：给定历史与要追加的项，返回本轮模型输入。它不认识 SDK 类型，也不写
任何存储——落库由 SDK 会话负责，「窗口裁剪不影响落库」因此是结构性的。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

ItemT = TypeVar("ItemT")

COMPACTED_SUMMARY_TAG = "<compacted-summary>"
"""摘要检查点的标签；压缩机制写入它，窗口派生靠它定位。"""


def _string_field(item: object, field: str) -> str | None:
    """从一个形如消息的映射里取字符串字段；取不到返回 ``None``。

    只依赖 ``get`` 这一个鸭子类型接口：SDK 的消息项与普通字典都能直接用，不必把
    SDK 类型引入本模块。
    """
    getter = getattr(item, "get", None)
    if not callable(getter):
        return None
    value = getter(field, None)
    return value if isinstance(value, str) else None


def is_compacted_summary(item: object) -> bool:
    """判断一项是否是压缩摘要检查点（靠标签，不靠位置）。"""
    content = _string_field(item, "content")
    return content is not None and COMPACTED_SUMMARY_TAG in content


def is_system_message(item: object) -> bool:
    """判断一项是否是系统消息。"""
    return _string_field(item, "role") == "system"


def last_checkpoint_index(
    history: Sequence[ItemT],
    *,
    is_checkpoint: Callable[[object], bool] = is_compacted_summary,
) -> int | None:
    """返回最后一条摘要检查点的下标；没有返回 ``None``。

    有多个检查点时取最后一个：压缩是「合并进同一结构」，越晚的越完整。
    """
    found: int | None = None
    for index, item in enumerate(history):
        if is_checkpoint(item):
            found = index
    return found


def leading_system_count(
    history: Sequence[ItemT],
    *,
    is_system_prompt: Callable[[object], bool] = is_system_message,
) -> int:
    """返回历史开头连续 system 消息的条数（系统提示的那一段）。"""
    count = 0
    for item in history:
        if not is_system_prompt(item):
            break
        count += 1
    return count


def derive_window(
    history: Sequence[ItemT],
    *,
    appended: Sequence[ItemT] = (),
    is_checkpoint: Callable[[object], bool] = is_compacted_summary,
    is_system_prompt: Callable[[object], bool] = is_system_message,
) -> list[ItemT]:
    """派生本轮模型窗口：``[前导 system 消息] + [最后一条摘要起的全部历史] + appended``。

    没有检查点、或检查点就在历史开头时退化为全量历史（不做任何裁剪）。返回新列表，
    不改动传入序列——历史是会话真源，任何就地修改都会污染下一轮。

    追加顺序由调用方给定（注入项在前、本轮新输入在后），本函数不重排。
    """
    checkpoint = last_checkpoint_index(history, is_checkpoint=is_checkpoint)
    if checkpoint is None or checkpoint == 0:
        return [*history, *appended]

    preamble_count = min(leading_system_count(history, is_system_prompt=is_system_prompt), checkpoint)
    return [*history[:preamble_count], *history[checkpoint:], *appended]
