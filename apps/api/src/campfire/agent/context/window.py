"""模型窗口的派生：只裁模型看到的上下文，不动落库的对话。

职责：给定历史与要追加的项，返回本轮模型输入（本模块是纯函数）。
边界：它不认识 SDK 类型，也不写任何存储——落库由 SDK 会话负责，
「窗口裁剪不影响落库」因此是结构性的。
参考：docs/技术设计/technical-details/压缩策略.md 第 3、5、8 节；
基座文档「已知偏差」。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

ItemT = TypeVar("ItemT")

COMPACTED_SUMMARY_TAG = "<compacted-summary>"
"""摘要检查点的开标签；压缩机制写入它，窗口派生靠它定位。"""

COMPACTED_SUMMARY_CLOSE_TAG = "</compacted-summary>"
"""摘要检查点的闭标签。开闭成对才算检查点。"""


_TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
"""分片 content 里算作文本的部件类型。"""


def message_text(item: object) -> str | None:
    """从一个形如消息的映射里取文本 content；取不到或形状不认识返回 `None`。

    只依赖 `get` 这一个鸭子类型接口：SDK 的消息项与普通字典都能直接用，不必把
    SDK 类型引入本模块。

    支持两种 content 形状，因为实测两种都会出现：使用者消息是字符串，而 SDK 落库的
    助手消息是分片数组（形如 `[{"type": "output_text", "text": "…"}]`）。只认字符串会让
    检查点判定在分片形状上永远漏检——方向安全（不裁剪历史），但压缩会静默失效。
    遇到不认识的部件（例如图片）时返回 `None`，不猜、不拼半句。
    """
    getter = getattr(item, "get", None)
    if not callable(getter):
        return None
    content = getter("content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
            continue
        part_getter = getattr(part, "get", None)
        if not callable(part_getter) or part_getter("type", None) not in _TEXT_PART_TYPES:
            return None
        text = part_getter("text", None)
        if not isinstance(text, str):
            return None
        parts.append(text)
    return "".join(parts)


def is_compacted_summary(item: object) -> bool:
    """判断一项是否是压缩摘要检查点。

    判定是整条信封：去掉首尾空白后必须以开标签开头、以闭标签结尾。子串包含不算。

    标签按整条信封判定（`startswith` 开标签且 `endswith` 闭标签），不是子串包含。
    理由是实测过的：按子串包含判定时，一句正常的对话——例如使用者问「你上一轮写的
    `<compacted-summary>` 是什么意思」——会被当成检查点，于是没有任何摘要就把历史裁掉，
    违反压缩策略第 8 节第 1 条。误判的代价（丢历史、当次看不到）远高于漏判的代价
    （不做裁剪，只是压缩没生效）。

    已知残余风险（有意接受）：使用者若把一整条检查点原文贴回来，那条消息会被当成检查点。
    这一窗口很窄，且修正它需要压缩写入方给出「不可能出现在使用者内容里」的标记
    （例如带属性的标签），那属于压缩机制的契约，不在这里发明。
    """
    content = message_text(item)
    if content is None:
        return False
    stripped = content.strip()
    if len(stripped) < len(COMPACTED_SUMMARY_TAG) + len(COMPACTED_SUMMARY_CLOSE_TAG):
        return False
    return stripped.startswith(COMPACTED_SUMMARY_TAG) and stripped.endswith(COMPACTED_SUMMARY_CLOSE_TAG)


def is_system_message(item: object) -> bool:
    """判断一项是否是系统消息。"""
    getter = getattr(item, "get", None)
    if not callable(getter):
        return False
    return getter("role", None) == "system"


def last_checkpoint_index(
    history: Sequence[ItemT],
    *,
    is_checkpoint: Callable[[object], bool] = is_compacted_summary,
) -> int | None:
    """返回最后一条摘要检查点的下标；没有返回 `None`。

    以及基座文档「已知偏差」里的一条实测约束：读回顺序契约虽然存在，但官方没把
    `limit=None` 的读回顺序写成硬保证，所以定位最后一条摘要消息靠内容里的
    `<compacted-summary>` 标签，而不是靠顺序。

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
    """返回历史开头连续 system 消息的条数（系统提示的那一段）。

    前提：系统提示是历史的前缀。 若将来 SDK 会话允许在首条非 system 消息之后再追加
    system 项，那一段会被压缩窗口遮蔽——压缩策略第 3 节只承诺「不遮蔽系统提示」，
    而前缀之外 system 项的存在与否尚未核实（记在实施前必须验证的事项里）。
    """
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
    """派生本轮模型窗口：`[前导 system 消息] + [最后一条摘要起的全部历史] + appended`。

    依据 docs/技术设计/technical-details/压缩策略.md：

    - 第 5 节：摘要作为一条消息追加进会话；此后窗口 = `[系统提示]` + `[最后一条
      摘要消息起的全部历史]`。这条规则可完全从会话历史推导，因此不另存「窗口配方」。
    - 第 8 节第 1 条：只在末尾追加；不改写、不插入、不重排历史消息；不得做滑动
      窗口——从头部裁剪等于移动前缀，每轮全量击穿缓存。窗口因此只能是「前缀 + 后缀」
      两段拼接，绝不是「保留最近 N 条」。
    - 第 3 节：系统提示永不被遮蔽，所以前导 system 消息原样留在窗口最前。

    本模块是纯函数：给定历史与要追加的项，返回本轮模型输入。它不认识 SDK 类型，也不写
    任何存储——落库由 SDK 会话负责，「窗口裁剪不影响落库」因此是结构性的。

    没有检查点、或检查点就在历史开头时退化为全量历史（不做任何裁剪）。返回新列表，
    不改动传入序列——历史是会话真源，任何就地修改都会污染下一轮。

    追加顺序由调用方给定（注入项在前、本轮新输入在后），本函数不重排。
    """
    checkpoint = last_checkpoint_index(history, is_checkpoint=is_checkpoint)
    if checkpoint is None or checkpoint == 0:
        return [*history, *appended]

    preamble_count = min(leading_system_count(history, is_system_prompt=is_system_prompt), checkpoint)
    return [*history[:preamble_count], *history[checkpoint:], *appended]
