"""SDK 会话条目 → parts/标题/预览的解析（纯逻辑，不连库）。

对应 `docs/技术设计/面/consult/HTTP与SSE契约.md` 第 3.2、3.3、7 节。

这里的每条用例钉的都是什么：

条目形状不是推测出来的，是实测的（真实 SDK + 真实 `SQLAlchemySession` 落库后
逐行读回）。因此下面的样本数据就是实测形状的忠实副本——写成「设想的形状」会让
用例通过而真实数据解析不出来：

1. 注入消息在落库后的角色也是 `user`：注入项经 `runner._as_input_item` 一律渲染为
   `{"role": "user", "content": …}`，与使用者消息同形。因此「首条使用者消息」必须
   靠内容前缀排除注入，否则会话标题会变成一段技能目录。
2. 助手消息的 content 是分片数组（`[{"type": "output_text", "text": …}]`），
   而使用者消息是字符串。只认一种形状会让另一种整批消失。
3. 思考文本在 `summary` 数组里，不在 `content` 里。
4. 工具结果只带 `call_id` 与 `output`：`ok` 与 `summary` 必须由水合重建，
   而重建的判据是 `output` 是不是 `<tool_error …>` 信封。
5. `candidate` 不在这里：它只在事件流里产出，不写会话存储——因此不需要「排除它」
   的代码，只需要一条用例钉住「它结构上不可能出现」。

    uv run pytest apps/api/tests/test_accounts_session_items.py
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

from campfire.agent.context import CitationRecord, window
from campfire.agent.runtime.ask_user_tool import ASK_USER_TOOL_NAME, build_ask_user_tool
from campfire.agent.tools import ToolResult
from campfire.agent.tools.pool import RESERVED_TOOL_NAMES
from campfire.modules.accounts import session_items
from campfire.modules.accounts.session_items import (
    ASK_USER_SUCCESS_OUTPUT,
    INJECTED_MESSAGE_PREFIXES,
    INTERRUPTED_TOOL_SUMMARY,
    PREVIEW_MAX_CHARS,
    QUESTION_BATCH_ID_PREFIX,
    QUESTION_ITEMS_MAX,
    TITLE_ELLIPSIS,
    TITLE_FALLBACK,
    TITLE_MAX_CHARS,
    TOOL_SUMMARY_MAX_CHARS,
    UNKNOWN_TOOL_NAME,
    MessagePart,
    StoredItem,
    build_messages,
    build_preview,
    build_title,
    first_user_message_text,
    is_injected_message,
    item_type,
    last_message_text,
    message_text,
    normalize_inline_text,
    parse_item,
    question_part,
    reasoning_text,
    tool_failure_message,
)

# 反向判据（工具是否真的已装配）要读装配处的注册清单。这里是**测试**，
# 不受 `modules/*` 的白名单约束——被测的正是「模块里那句注释与装配处的事实是否一致」，
# 因此这个跨层 import 是判据本身的一部分，不是穿透。
from campfire.surfaces.consult.registry import build_product_tools

# ---------------------------------------------------------------------------
# 实测形状的样本
# ---------------------------------------------------------------------------

#: 产品源码根（「防注释过期」那条用例要读 `session_items.py` 本身的文本）。
SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "campfire"


def _message_part_type_names() -> set[str]:
    """取 `MessagePart` 联合里各成员的 part 类型名（从 `type` 字段的 `Literal` 取值）。

    为什么需要这个函数、而且它必须能失败：**这是「台账与事实一致」那条用例的测量仪**。
    测不准（返回空集或返回一堆 `ForwardRef` 之类的东西）时，用例会变成一道恒真的空闸门
    ——这正是本包要防的形态。因此下面逐条断言解析结果，而不是直接把集合丢给调用方。

    实测坑（第一版就踩了）：`MessagePart` 是 `typing.Union[...]`，其 `__args__` 里是
    **TypedDict 类**，直接取 `__annotations__["type"]` 拿到的是 `typing.Literal['text']`
    这类 **`ForwardRef`**（本文件开了 `from __future__ import annotations`，注解是字符串），
    必须经 `typing.get_type_hints` 求值后才能取出字面量。

    Returns:
        形如 `{"text", "reasoning", "tool_call", "question"}` 的集合。
    """
    names: set[str] = set()
    for member in getattr(MessagePart, "__args__", ()):
        hints = get_type_hints(member)
        literal = hints.get("type")
        for value in get_args(literal):
            if isinstance(value, str):
                names.add(value)
    return names


def _stored(row_id: int, payload: dict) -> StoredItem:
    """造一条已解析的条目（与 `session_repository` 读出来后交给解析层的东西同形）。"""
    return StoredItem(row_id=row_id, data=payload)


def _injection(content: str = '<available_skills>\n  <skill name="x" />\n</available_skills>') -> dict:
    """一条实测形状的注入消息：角色同样是 `user`。"""
    return {"role": "user", "content": content}


def _user(text: str) -> dict:
    """一条使用者消息（content 是字符串——实测如此）。"""
    return {"role": "user", "content": text}


def _assistant(text: str, annotations: bool = False) -> dict:
    """一条助手消息（content 是分片数组——实测如此）。"""
    part: dict = {"annotations": [], "text": text, "type": "output_text"}
    if annotations:
        part["logprobs"] = []
    return {
        "id": f"__fake_{abs(hash(text)) % 1000}__",
        "content": [part],
        "role": "assistant",
        "status": "completed",
        "type": "message",
    }


def _reasoning(text: str) -> dict:
    """一条思考条目（文本在 `summary` 里——实测如此）。"""
    return {
        "id": "__fake_reasoning__",
        "summary": [{"text": text, "type": "summary_text"}],
        "type": "reasoning",
    }


def _function_call(name: str, call_id: str, arguments: str = "{}") -> dict:
    return {"arguments": arguments, "call_id": call_id, "name": name, "type": "function_call"}


def _function_output(call_id: str, output: str) -> dict:
    return {"call_id": call_id, "output": output, "type": "function_call_output"}


# ---------------------------------------------------------------------------
# 形状：解析与识别
# ---------------------------------------------------------------------------


def test_injected_message_is_also_a_user_role_message() -> None:
    """钉住那条最容易踩的实测事实：注入消息落库后角色也是 `user`。

    这条用例的判别性在于「若注入是助手角色，本用例失败」——而实现正是靠这一点
    才能只用内容前缀区分二者。它是下面「标题取首条使用者消息」用例的前提。
    """
    injection = _injection()

    assert injection["role"] == "user"
    assert is_injected_message(injection) is True
    # 使用者消息同角色、不同内容 → 不被当作注入。
    assert is_injected_message(_user("你好")) is False


@pytest.mark.parametrize("prefix", INJECTED_MESSAGE_PREFIXES)
def test_every_declared_envelope_prefix_is_recognized(prefix: str) -> None:
    """声明的每个信封前缀都必须真的被识别。

    `INJECTED_MESSAGE_PREFIXES` 是元组字面量，因此「声明了但不生效」是可能的
    （例如实现里漏了某项、或判定写成了全等）。逐个前缀验证，让补充清单时立刻有反馈。
    """
    assert is_injected_message(_injection(f"{prefix}…")) is True


def test_assistant_role_is_never_treated_as_injection() -> None:
    """助手消息永远是模型的产出，没有「注入的助手消息」。

    `InjectionItem` 允许 `assistant` 角色，但当前没有任何产出方用它；即便如此，
    判定必须只对 `user` 生效——否则一条恰好以信封开头、由模型自己写出的助手消息
    会在水合里被丢掉。
    """
    assert is_injected_message({"role": "assistant", "content": "<available_skills>"}) is False


def test_parse_item_rejects_non_object_and_broken_json() -> None:
    """损坏行与非对象 JSON 都必须返回 `None`，不抛异常。

    SDK 自己的读取路径对损坏行是跳过（捕获 `JSONDecodeError` 后 `continue`），
    本层保持同一取向：一行坏数据不该让整个列表页或水合失败。
    """
    assert parse_item("{not json") is None
    assert parse_item("[1, 2, 3]") is None
    assert parse_item(b"bytes") is None
    assert parse_item('{"role": "user"}') == {"role": "user"}


def test_item_type_reads_the_discriminator() -> None:
    """判别字段缺失或非字符串时返回 `None`（「认不出」的判据）。"""
    assert item_type({"type": "reasoning"}) == "reasoning"
    assert item_type({}) is None
    assert item_type({"type": 7}) is None


# ---------------------------------------------------------------------------
# 文本提取：两种 content 形状
# ---------------------------------------------------------------------------


def test_message_text_reads_both_content_shapes() -> None:
    """字符串与分片数组两种形状都要取到文本（实测两种都出现）。"""
    assert message_text(_user("使用者写的")) == "使用者写的"
    assert message_text(_assistant("助手写的")) == "助手写的"


def test_message_text_concatenates_multiple_text_parts() -> None:
    """同一消息的多个文本部件按顺序拼接（不是取第一个就返回）。"""
    item = {
        "role": "assistant",
        "content": [{"type": "output_text", "text": "前"}, {"type": "output_text", "text": "后"}],
    }

    assert message_text(item) == "前后"


def test_message_text_returns_none_when_no_readable_part() -> None:
    """认不出任何文本部件时返回 `None`，不凭空造空串。

    `None` 与空串的差别有语义：`None` 表示「这条取不出文本」（调用方据此跳过或记警告），
    空串会被当成一条合法但空的消息。
    """
    assert message_text({"role": "assistant", "content": []}) is None
    assert message_text({"role": "assistant", "content": [{"type": "image_url", "image_url": "…"}]}) is None
    assert message_text({"role": "assistant"}) is None


def test_message_text_keeps_readable_parts_and_drops_unknown_ones() -> None:
    """混合内容里保留认得的部件、丢掉认不出的（与压缩侧的保守判据刻意不同）。

    压缩判定（`window.message_text`）遇到认不出的部件整体返回 `None`——它宁可漏检也不
    误判。水合为呈现服务：一段含图片的消息，丢掉图片也好过整条历史消失。
    """
    item = {"role": "assistant", "content": [{"type": "output_text", "text": "答案"}, {"type": "image_url"}]}

    assert message_text(item) == "答案"


def test_reasoning_text_reads_summary_not_content() -> None:
    """思考文本在 `summary` 数组里，不能复用消息的 `content` 取法。"""
    assert reasoning_text(_reasoning("先想一下。")) == "先想一下。"
    # 实测形状里没有 content——若实现走 content，这条会返回 None。
    assert reasoning_text({"type": "reasoning", "content": "错位置"}) is None
    assert reasoning_text({"type": "reasoning"}) is None


# ---------------------------------------------------------------------------
# 工具结果的 ok / summary 重建
# ---------------------------------------------------------------------------


def test_tool_failure_message_extracts_body_from_envelope() -> None:
    """失败信封里取出说明文本（不含信封本身）。

    与事件流的取法一致（成功取产出文本、失败取信封内说明），好让水合出来的
    `summary` 与当时事件流里的那一句逐字相同。
    """
    envelope = '<tool_error code="tool_not_available">该工具此刻不可用</tool_error>'

    assert tool_failure_message(envelope) == "该工具此刻不可用"


def test_tool_failure_message_returns_none_for_success_output() -> None:
    """成功的产出文本不是信封 → `None`（即调用成功）。"""
    assert tool_failure_message("工具读到了档案") is None
    # 畸形信封（有开头没结尾）也不当成失败：宁可报成功，不做半截解析。
    assert tool_failure_message('<tool_error code="x">没有结尾') is None


# ---------------------------------------------------------------------------
# 水合：条目序列 → 消息序列
# ---------------------------------------------------------------------------


def test_hydration_unifies_fragmented_assistant_message() -> None:
    """核心用例：分片数组形状的助手消息必须能取出文本。

    这正是任务包点名的对抗用例——只认字符串 content 的实现会让每一条助手消息
    在水合里消失（对话只剩使用者的话）。
    """
    items = [_stored(1, _user("你好")), _stored(2, _assistant("你好，我在。"))]

    messages = build_messages(items)

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["parts"] == [{"type": "text", "text": "你好，我在。"}]


def test_hydration_excludes_injected_messages() -> None:
    """注入消息不进历史：使用者从未见过它们，呈现等于把应用上下文冒充成对话内容。"""
    items = [
        _stored(1, _injection()),
        _stored(2, _user("真正的第一句")),
        _stored(3, _assistant("回答")),
    ]

    messages = build_messages(items)

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["parts"] == [{"type": "text", "text": "真正的第一句"}]


def test_hydration_groups_one_run_into_one_assistant_message() -> None:
    """一次运行的产出（思考 + 工具调用 + 结果 + 正文）合成一条助手消息。

    依据是契约第 7 节把六种 part 都定义为「消息 content 的序列化，与流式事件同源
    同形」：流式期间它们累加到当前这条助手消息上。不分组的话，刷新前后同一段对话的
    消息条数会变（流式期间 1 条、刷新后 4 条）。
    """
    items = [
        _stored(1, _user("帮我查档案")),
        _stored(2, _reasoning("先想一下。")),
        _stored(3, _function_call("read_alpha", "call-1", json.dumps({"query": "档案"}))),
        _stored(4, _function_output("call-1", "工具读到了 档案")),
        _stored(5, _assistant("根据档案，是这样的。")),
    ]

    messages = build_messages(items)

    assert len(messages) == 2, "五条条目应合成「一条使用者 + 一条助手」两条消息"
    parts = messages[1]["parts"]
    assert [part["type"] for part in parts] == ["reasoning", "tool_call", "text"]
    assert parts[0] == {"type": "reasoning", "delta": "先想一下。"}
    assert parts[1] == {"type": "tool_call", "tool_name": "read_alpha", "ok": True, "summary": "工具读到了 档案"}
    assert parts[2] == {"type": "text", "text": "根据档案，是这样的。"}


def test_hydration_marks_tool_failure_from_result_envelope() -> None:
    """工具结果里的失败信封 → `ok=False` 且 `summary` 是信封内的说明。"""
    items = [
        _stored(1, _user("问")),
        _stored(2, _function_call("read_alpha", "call-1")),
        _stored(3, _function_output("call-1", '<tool_error code="tool_failed">后端炸了</tool_error>')),
    ]

    parts = build_messages(items)[1]["parts"]

    # 判别字段必须先断言：`MessagePart` 是判别联合，只写下标取值在静态上看不出是哪一种。
    assert parts[0]["type"] == "tool_call"
    assert parts[0]["ok"] is False
    assert parts[0]["summary"] == "后端炸了"


def test_hydration_fills_interrupted_tool_call() -> None:
    """被打断的调用（有调用、无结果）补成失败 part，而不是从历史里消失。

    依据：`_ToolCallTracker` 在运行触顶或取消时会给被打断的调用补一条结束事件。
    历史里若没有它，「当时调过一个没有结果的工具」这件事就查不到了。
    """
    items = [_stored(1, _user("问")), _stored(2, _function_call("read_alpha", "call-1"))]

    parts = build_messages(items)[1]["parts"]

    # 同上：先钉住判别字段，后取该 part 独有的键。
    assert parts[0]["type"] == "tool_call"
    assert parts[0]["ok"] is False
    assert parts[0]["summary"] == INTERRUPTED_TOOL_SUMMARY


def test_hydration_uses_row_id_as_message_id() -> None:
    """消息 `id` 取自行标识——真源里的稳定值，不是新造的序号。

    新旧造一套标识会让「同一条消息在两次水合里是不是同一条」没有答案。
    """
    messages = build_messages([_stored(41, _user("问")), _stored(42, _reasoning("想")), _stored(43, _assistant("答"))])

    assert messages[0]["id"] == "41"
    # 助手消息取第一个贡献条目的行标识（思考在前）。
    assert messages[1]["id"] == "42"


def test_hydration_skips_unknown_item_types_without_failing() -> None:
    """认不出的条目类型只跳过这一条，不让整次水合失败。

    读路径上「缺一段」比「全空」更接近事实（会话确实还有别的内容），但必须留下痕迹
    ——实现里记警告，用例只能钉住「不抛异常且其余内容仍在」。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, {"type": "some_future_item_type", "payload": "…"}),
        _stored(3, _assistant("答")),
    ]

    messages = build_messages(items)

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["parts"] == [{"type": "text", "text": "答"}]


def test_hydration_returns_empty_list_for_session_without_messages() -> None:
    """没有消息的会话返回空列表（不是「水合失败」）。

    这一条与「水合失败抛错」是数据层的两种不同结果：面层据此给出 200 空列表与 404
    两种响应（契约第 3.3 节：失败不冒充空对话）。两者若在数据层就分不开，面层只能猜。
    """
    assert build_messages([]) == []


def test_hydration_handles_corrupted_row_by_skipping_it() -> None:
    """损坏行（解析失败）不进入结果——由读取层过滤，解析层只处理已解析的条目。"""
    # `parse_item` 是那条过滤的实现；这里验证它的判据与「跳过」一致。
    assert parse_item('{"role": "user"') is None


def test_tool_name_falls_back_to_named_placeholder() -> None:
    """工具名读不出来时用具名占位，不用空串。

    空串在界面上是一个「没有名字的工具」，与「名字读不出来」无法区分。
    """
    items = [_stored(1, _user("问")), _stored(2, {"type": "function_call", "call_id": "c1"})]

    parts = build_messages(items)[1]["parts"]

    assert parts[0]["type"] == "tool_call"
    assert parts[0]["tool_name"] == UNKNOWN_TOOL_NAME


def test_tool_summary_is_bounded() -> None:
    """工具产出很长时 `summary` 必须有界（CORE-11）。"""
    long_output = "长" * (TOOL_SUMMARY_MAX_CHARS * 3)
    items = [
        _stored(1, _user("问")),
        _stored(2, _function_call("read_alpha", "c1")),
        _stored(3, _function_output("c1", long_output)),
    ]

    parts = build_messages(items)[1]["parts"]

    assert parts[0]["type"] == "tool_call"
    summary = parts[0]["summary"]

    assert len(summary) == TOOL_SUMMARY_MAX_CHARS


# ---------------------------------------------------------------------------
# 标题：首条使用者消息
# ---------------------------------------------------------------------------


def test_title_uses_first_user_message_not_first_message() -> None:
    """核心用例：标题取首条使用者消息，跳过在前面落库的注入消息。

    实测注入消息先于使用者消息落库（同一批 `add_items` 里注入在前），因此实现若取
    「第一条消息」会得到一段技能目录当标题。这正是质量地板点名的对抗用例之一。
    """
    items = [
        _stored(1, _injection()),
        _stored(2, _injection("<tool_availability>\n</tool_availability>")),
        _stored(3, _user("这是真正想说的话")),
    ]

    assert build_title(first_user_message_text(items)) == "这是真正想说的话"


def test_title_truncates_at_24_chars_with_ellipsis() -> None:
    """超长取前 24 字符 + 省略号（裁决 5 的 N=24）。"""
    text = "一" * 30

    title = build_title(text)

    assert title == "一" * TITLE_MAX_CHARS + TITLE_ELLIPSIS
    assert len(title) == TITLE_MAX_CHARS + 1


def test_title_falls_back_when_no_user_message() -> None:
    """对抗用例：只有注入消息、或完全空白的首条消息 → 回退「新对话」。"""
    assert build_title(None) == TITLE_FALLBACK
    assert build_title("   \n\t ") == TITLE_FALLBACK
    # 只有注入消息的会话：没有使用者消息可作标题。
    assert build_title(first_user_message_text([_stored(1, _injection())])) == TITLE_FALLBACK


def test_title_is_exactly_24_chars_without_ellipsis_at_boundary() -> None:
    """恰好 24 字符时不加省略号（边界）。"""
    text = "二" * TITLE_MAX_CHARS

    assert build_title(text) == text
    assert TITLE_ELLIPSIS not in build_title(text)


def test_title_collapses_newlines_into_single_line() -> None:
    """标题是单行文本：换行与制表折成空格，否则含换行的消息会撑破列表行。"""
    assert normalize_inline_text("第一行\n第二行") == "第一行 第二行"
    assert normalize_inline_text("  两边有空白  ") == "两边有空白"
    assert build_title("第一行\n第二行") == "第一行 第二行"


def test_first_user_message_text_skips_items_without_readable_text() -> None:
    """前导的空消息（取不出文本）不阻断后续搜索。"""
    items = [_stored(1, {"role": "user", "content": []}), _stored(2, _user("后来的一句"))]

    assert first_user_message_text(items) == "后来的一句"


# ---------------------------------------------------------------------------
# 预览：末条消息
# ---------------------------------------------------------------------------


def test_preview_uses_last_message_not_last_item() -> None:
    """对抗用例：末条是思考段/工具结果时，预览取最近一条消息。

    拿思维过程或工具输出当预览会让列表显示一段既不是问题也不是回答的文本。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _assistant("回答")),
        _stored(3, _reasoning("再想一下")),
        _stored(4, _function_output("c1", "工具输出")),
    ]

    assert build_preview(last_message_text(items)) == "回答"


def test_preview_returns_none_when_nothing_readable() -> None:
    """没有任何可呈现消息时返回 `None`（契约第 3.2 节：`null`）。

    `None` 而不是空串：列表页对缺失字段的处理是不渲染该行，空串会渲染一行空白。
    """
    assert build_preview(None) is None
    assert build_preview("   ") is None
    assert build_preview(last_message_text([_stored(1, _reasoning("只有思考"))])) is None


def test_preview_is_bounded() -> None:
    """预览有上界（CORE-11）。"""
    preview = build_preview("字" * (PREVIEW_MAX_CHARS * 2))

    assert preview is not None
    assert len(preview) == PREVIEW_MAX_CHARS + 1


def test_preview_skips_injected_messages() -> None:
    """注入消息不当预览（同标题的判据）。"""
    items = [_stored(1, _user("问")), _stored(2, _assistant("答")), _stored(3, _injection())]

    assert build_preview(last_message_text(items)) == "答"


# ---------------------------------------------------------------------------
# candidate：结构上不可能出现在会话真源里
# ---------------------------------------------------------------------------


def test_candidate_cannot_appear_in_hydration() -> None:
    """`candidate` 不进历史——它只在事件流里产出，不写会话存储。

    依据契约第 7 节：「`candidate` 不进历史：它不进消息流（项目结构设计第 9 节），
    仅经 SSE 计数」。因此这里不需要「排除 candidate」的代码——`ToolResult.candidates`
    由 `assembly._invoke` 转成 `CandidateEvent` 发给面层，从不进入 `session.add_items`。

    本用例钉住的是水合不会凭空产出 candidate part：若将来有人把候选写进会话存储，
    它要么被当成认不出的条目跳过（并记警告），要么以别的形状出现——但绝不能变成一条
    candidate part。因此断言「结果里没有任何 candidate part」。
    """
    items = [
        _stored(1, _user("问")),
        # 假设有人真的把候选塞进了消息内容（这是不该发生的），水合也只当文本处理。
        _stored(2, {"type": "message", "role": "assistant", "content": "候选：某条推断"}),
    ]

    parts = build_messages(items)[1]["parts"]

    assert all(part["type"] != "candidate" for part in parts)
    assert parts == [{"type": "text", "text": "候选：某条推断"}]


# ---------------------------------------------------------------------------
# 跨模块：文本部件词表不许单侧漂移
# ---------------------------------------------------------------------------

#: 分片 content 里算作文本的部件类型；两处实现各自的集合都必须等于它。
#:
#: 写成字面量而不是取任一侧来互比：拿一侧当基准时，两侧一起漂移就仍然全绿。它不是
#: 第三份定义——它是这条跨模块相等关系的比对基准，只在本节出现。
TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})


def test_text_part_types_agree_across_the_two_parsers() -> None:
    """两处解析同一种持久化格式，文本部件词表必须一致（`session_items` 文件头的承诺）。

    `modules/*` 不得 import `agent/*`（项目结构设计第 7 节），因此这份词表必须在两处
    各写一份，相等关系只能靠本用例机械守住。漂移方向是不对称且静默的：一侧把某部件
    当文本、另一侧不当，两侧模块自己的用例都仍然自洽——基座侧遇到认不出的部件整体
    返回 `None`（压缩漏检，方向安全），本模块侧丢掉该部件（历史少一段）。因此两侧都
    与上面那个字面量互比，不互相 import。
    """
    assert window._TEXT_PART_TYPES == TEXT_PART_TYPES
    assert session_items._TEXT_PART_TYPES == TEXT_PART_TYPES


# ---------------------------------------------------------------------------
# 提问的水合（★ T27 的主缺陷：刷新后提问卡消失）
#
# 实测（T27 第 0 步，真实栈 + 真实浏览器）：
#   - 运行结束后（未刷新）：`.question-card` = 1（live 通路是好的，不必修）；
#   - 刷新后：`.question-card` = 0、`[data-question-submit]` = 0 ⇒ 提问卡消失、无法作答。
# 根因是 `MessagePart` 联合里没有 `question`（见该联合的说明）。
# ---------------------------------------------------------------------------

#: `ask_user` 调用参数的实测形状（T27 第 0 步从真实会话取回，逐字）。
_ASK_USER_ARGUMENTS = json.dumps(
    {
        "items": [
            {
                "id": "object_name",
                "prompt": "你平时怎么称呼这孩子？（小名、昵称、随便一个称呼都行，不用真实姓名）",
                "options": [],
                "allow_skip": True,
            }
        ]
    },
    ensure_ascii=False,
)

_ASK_USER_CALL_ID = "call_00_hmnfjj03n9utxqi42dgoxyq7"


def _ask_user_call(call_id: str = _ASK_USER_CALL_ID, arguments: str = _ASK_USER_ARGUMENTS) -> dict:
    """实测形状的 `ask_user` 调用条目。"""
    return {
        "arguments": arguments,
        "call_id": call_id,
        "name": "ask_user",
        "type": "function_call",
        "id": "__fake_id__",
    }


def _ask_user_output(call_id: str = _ASK_USER_CALL_ID, output: str = ASK_USER_SUCCESS_OUTPUT) -> dict:
    """实测形状的 `ask_user` 结果条目。"""
    return {"call_id": call_id, "output": output, "type": "function_call_output"}


#: 会话真源里那条 assistant 消息的条目序列（T27 第 0 步实测的裁剪版）：
#: 助手正文 → 思考 → 调用 → 结果。真实会话里前面还有 skill 激活对与两次
#: `read_skill_resource`，它们不影响本节的判据。
def _question_turn_items() -> list[StoredItem]:
    return [
        _stored(1, _user("我家孩子5岁，最近在超市里一听到广播声就会捂住耳朵、蹲在地上不肯走。")),
        _stored(2, _reasoning("先想一下。")),
        _stored(3, _assistant("收到——我先花几步把档案开头建起来。")),
        _stored(4, _ask_user_call()),
        _stored(5, _ask_user_output()),
    ]


def test_ask_user_success_output_matches_the_tool_handler() -> None:
    """`ASK_USER_SUCCESS_OUTPUT` 必须与真实的 `ask_user` 回执逐字一致。

    这条是**判据的判据**：水合靠这句话判定「这次提问真的产出了」。它一旦漂移，
    提问会在水合里静默消失——回到本包修的那个缺陷，而且没有任何用例会红。
    因此这里直接调用真实 handler，而不是再抄一份字面量。

    判别性：改 `ask_user_tool.handler` 的返回文案（或改本模块的常量）⇒ 本用例红。
    """
    import asyncio

    from campfire.agent.context import CitationRecorder
    from campfire.agent.tools import ActivationState, ToolContext

    class _Index:
        """最小引用索引；本用例不产生引用，只需满足构造。

        显式实现协议的两个成员并给出**正确的返回类型**（`Sequence[CitationRecord]`）——
        返回 `list[object]` 会被 mypy 判成「这个替身不够格当索引」，而那正是
        「替身必须满足真实契约」的判据，不能靠类型逃逸抹掉。
        """

        async def add(self, record: CitationRecord) -> None:
            del record

        async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
            del run_id
            return []

    tool = build_ask_user_tool()
    context = ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_Index(), run_id="run-1"),
    )
    outcome = asyncio.run(tool.invoke(context, _ASK_USER_ARGUMENTS))

    assert isinstance(outcome, ToolResult)
    assert outcome.text == ASK_USER_SUCCESS_OUTPUT
    assert outcome.question is not None
    # 工具名常量也要与基座一致：`modules/*` 不得 import `agent/*`，只能是字面量。
    assert tool.name == ASK_USER_TOOL_NAME
    assert tool.name == session_items.ASK_USER_TOOL_NAME


def test_hydration_rebuilds_a_question_part() -> None:
    """★ 主用例：带 `ask_user` 调用对的历史，水合后必须出现提问 part。

    这就是 T27 的缺陷现场——刷新后 `.question-card` 消失，因为后端从不产出
    `question` part（`history.ts` 的 `case 'question'` 因此永不命中）。

    判别性：把 `MessagePart` 联合里新加的 `QuestionPart` 去掉（或删掉
    `add_tool_output` 里追加 part 的那三行）⇒ 本用例在第一处断言就失败。
    """
    parts = build_messages(_question_turn_items())[1]["parts"]

    questions = [part for part in parts if part["type"] == "question"]

    assert len(questions) == 1, "刷新后必须仍有且只有一个提问 part（T24 的缺陷现场）"
    question = questions[0]
    assert question["batch_id"].startswith(QUESTION_BATCH_ID_PREFIX)
    assert _ASK_USER_CALL_ID in question["batch_id"], "批次标识必须能从调用标识追溯回来"
    assert [item["id"] for item in question["items"]] == ["object_name"]
    # 题干逐字保留：使用者要读的正是这句话。
    assert "你平时怎么称呼这孩子" in question["items"][0]["prompt"]
    assert question["items"][0]["allow_skip"] is True


def test_hydration_question_part_shape_matches_the_wire_contract() -> None:
    """水合出的 `question` part 形状必须与契约第 7 节逐字一致（前端两侧共用一组键）。

    前端 `history.ts` 的 `case 'question'` 读的是 `batch_id` / `items`，
    而 `parts.tsx` 的 `QuestionRecordPart` 再逐项读 `id` / `prompt` / `options`
    / `allow_skip`。少一个键或改一个名字，水合出的卡就是空的——
    而那种失败在浏览器里只表现为「卡片不出现」，不会报错。
    """
    parts = build_messages(_question_turn_items())[1]["parts"]
    question = next(part for part in parts if part["type"] == "question")

    assert set(question) == {"type", "batch_id", "items"}
    assert set(question["items"][0]) == {"id", "prompt", "options", "allow_skip"}


def test_hydration_rebuilds_options_when_present() -> None:
    """选项被保留（含可选 `description`）：提问卡的三条通道里有一半靠它。"""
    arguments = json.dumps(
        {
            "items": [
                {
                    "id": "start_choice",
                    "prompt": "你想从哪个开始？",
                    "options": [
                        {"label": "先建档", "description": "大约七八个问题"},
                        {"label": "先回答我的问题"},
                    ],
                    "allow_skip": False,
                }
            ]
        },
        ensure_ascii=False,
    )
    items = [_stored(1, _user("问")), _stored(2, _ask_user_call(arguments=arguments)), _stored(3, _ask_user_output())]

    question = next(part for part in build_messages(items)[1]["parts"] if part["type"] == "question")

    assert question["items"][0]["options"] == [
        {"label": "先建档", "description": "大约七八个问题"},
        {"label": "先回答我的问题"},
    ]
    assert question["items"][0]["allow_skip"] is False


def test_hydration_does_not_rebuild_a_question_from_a_failed_call() -> None:
    """★ 反伪造：参数不合法的那次 `ask_user` **没有**向使用者呈现过任何东西。

    基座的 `QuestionGate` 刻意不因参数错误结束运行、也不发 `question` 事件
    （见 `agent/runtime/assembly.py` 的说明）。若水合只看参数形状，就会给一张
    「当时从未出现过」的提问卡——那是本模块明确禁止的伪造。

    判别性：把 `question_part` 里 `output != ASK_USER_SUCCESS_OUTPUT` 那一句去掉，
    本用例失败（会凭空造出一张卡）。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output(output='<tool_error code="tool_invalid_arguments">items 为空</tool_error>')),
    ]

    parts = build_messages(items)[1]["parts"]

    assert [part["type"] for part in parts] == ["tool_call"], "失败的调用不得产出提问 part"
    # 判别字段必须先断言：`MessagePart` 是判别联合，只写下标取值在静态上看不出是哪一种
    # （与文件里既有用例同一写法）。
    first = parts[0]
    assert first["type"] == "tool_call"
    assert first["ok"] is False


def test_question_part_rejects_bad_input() -> None:
    """`question_part` 的每一条判据都各有一个「喂坏输入 ⇒ 立刻失败」的对照。

    这是任务书要求的**反空断言**：完整性断言（「每个 question 事件都能水合」）若是
    恒真的空闸门就毫无价值。这里逐条喂坏输入，断言它返回 `None` 而不是造一张卡。
    """
    call_id = "call-1"
    good_arguments = _ASK_USER_ARGUMENTS

    cases = {
        "没有调用标识": ("", good_arguments, ASK_USER_SUCCESS_OUTPUT),
        "产出是工具错误": (call_id, good_arguments, '<tool_error code="tool_failed">炸了</tool_error>'),
        "产出是空串": (call_id, good_arguments, ""),
        "参数不是 JSON": (call_id, "{不是 JSON", ASK_USER_SUCCESS_OUTPUT),
        "参数不是对象": (call_id, "[1, 2]", ASK_USER_SUCCESS_OUTPUT),
        "参数里没有 items": (call_id, json.dumps({"other": 1}), ASK_USER_SUCCESS_OUTPUT),
        "items 是空数组": (call_id, json.dumps({"items": []}), ASK_USER_SUCCESS_OUTPUT),
        "参数不是字符串": (call_id, {"items": []}, ASK_USER_SUCCESS_OUTPUT),
        "题没有题干": (
            call_id,
            json.dumps({"items": [{"id": "a", "prompt": "   "}]}),
            ASK_USER_SUCCESS_OUTPUT,
        ),
        "题没有标识": (call_id, json.dumps({"items": [{"prompt": "问"}]}), ASK_USER_SUCCESS_OUTPUT),
        "题数超上界": (
            call_id,
            json.dumps({"items": [{"id": f"i{n}", "prompt": "问"} for n in range(QUESTION_ITEMS_MAX + 1)]}),
            ASK_USER_SUCCESS_OUTPUT,
        ),
    }

    # 对照组：同一形状的好输入必须**不**返回 None——否则「一切都返回 None」也能全绿。
    assert question_part(call_id, good_arguments, ASK_USER_SUCCESS_OUTPUT) is not None

    for label, (given_call_id, arguments, output) in cases.items():
        assert question_part(given_call_id, arguments, output) is None, f"{label} 必须重建不出提问"


def test_hydration_keeps_the_tool_call_row_next_to_the_question() -> None:
    """提问 part 与那次工具调用同在一条助手消息里（不是新开一条消息）。

    依据是契约第 7 节的分组规则：一次运行的产出合成一条助手消息。分成两条会让
    刷新前后的消息条数变化（流式期间 1 条、刷新后 2 条）。
    """
    messages = build_messages(_question_turn_items())

    assert len(messages) == 2, "一条使用者 + 一条助手"
    parts = messages[1]["parts"]
    types = [part["type"] for part in parts]
    assert types == ["reasoning", "text", "tool_call", "question"]
    # 工具行仍在（它是「向你提问 · 已结束」那句话的来源，T24 靠它看见「已结束」）。
    # 判别字段先断言再取该 part 独有的键（同文件既有用例的写法）。
    tool_part = parts[2]
    assert tool_part["type"] == "tool_call"
    assert tool_part["tool_name"] == ASK_USER_TOOL_NAME


def test_part_ledger_agrees_with_the_code_facts() -> None:
    """★ 防注释过期（本缺陷的成因）：能力台账必须与代码事实一致。

    **为什么不按字面扫某个词**：这条守卫最初就是这么写的，结果**误伤了它自己的说明
    文字**——命中的 5 处全是「为什么旧注释是错的」的订正说明。判「某个能力存在吗」要
    区分**载体**与**使它成立的东西**：字面出现 ≠ 断言存在。按字面扫还有更坏的后果：
    绕过它最省事的办法是**删掉那段说明**，而说明正是防止下一个人的唯一线索。

    因此判据改成**语义一致性**：本模块声明两份台账（`PART_PROVENANCE` /
    `NOT_REBUILT_PARTS`），本用例断言台账与代码事实逐条一致——注释怎么措辞都不影响结论。

    判别性（四条各自独立可红）：
    1. 往 `PART_PROVENANCE` 加一个不在 `MessagePart` 联合里的名字 ⇒ 红；
    2. 把 `question` 从联合摘掉但留在台账里 ⇒ 红（同上一条路径）；
    3. 往 `NOT_REBUILT_PARTS` 加一个**已在**联合里的名字 ⇒ 红；
    4. `NOT_REBUILT_PARTS` 的某条理由写成空串 ⇒ 红（「未做」与「忘了做」必须可分）。
    """
    union_part_types = _message_part_type_names()

    # 反空跑：解析必须真的看到东西，否则下面的断言只是在空集合上成立。
    assert union_part_types, "没能从 MessagePart 联合里解析出任何 part 类型，本用例会空跑"
    assert session_items.PART_PROVENANCE, "能力台账为空，本用例会空跑"

    declared_rebuildable = set(session_items.PART_PROVENANCE)
    declared_not_rebuilt = set(session_items.NOT_REBUILT_PARTS)

    # 判据 1：台账说可重建的，必须真的在联合里。
    assert declared_rebuildable <= union_part_types, (
        "PART_PROVENANCE 声明了可重建、但 MessagePart 联合里没有的 part："
        f"{sorted(declared_rebuildable - union_part_types)}——这正是旧注释那种「说的与做的不一致」"
    )

    # 判据 2：台账说不重建的，必须真的不在联合里。
    assert not (declared_not_rebuilt & union_part_types), (
        "NOT_REBUILT_PARTS 声明了不重建、但它其实已经在 MessagePart 联合里："
        f"{sorted(declared_not_rebuilt & union_part_types)}——那份「未重建」说明已经过期"
    )

    # 判据 3：联合里的每个 part 都必须在台账里有归属（漏登记 = 没人负责）。
    assert union_part_types == declared_rebuildable, (
        "MessagePart 联合与能力台账不一致。"
        f"只在联合里：{sorted(union_part_types - declared_rebuildable)}；"
        f"只在台账里：{sorted(declared_rebuildable - union_part_types)}"
    )

    # 判据 4：不重建的每一条都必须写明理由。
    empty_reasons = [name for name, reason in session_items.NOT_REBUILT_PARTS.items() if not reason.strip()]
    assert not empty_reasons, f"这些 part 声明未重建但没写理由：{empty_reasons}"

    # 判据 5：台账里点名的工具必须真的已装配——把「工具已装配」与「台账说它不存在」
    # 变成不可能同时为真。这是本缺陷的核心：旧注释说工具没实现，而工具早就装好了。
    assert ASK_USER_TOOL_NAME in RESERVED_TOOL_NAMES
    assert session_items.ASK_USER_TOOL_NAME == ASK_USER_TOOL_NAME
    registered = {tool.name for tool in build_product_tools()}
    assert session_items.EMERGENCY_ACTION_CARD_TOOL_NAME in registered, (
        "台账（NOT_REBUILT_PARTS）用这个名字陈述「载荷可重建」；若它已不在注册清单里，那份说明就成了新的过期断言"
    )


def test_part_ledger_covers_the_six_parts_of_the_contract() -> None:
    """台账必须覆盖契约第 7 节列的六种 part（一个不漏）。

    没有这一条，「两张表都空了」也能让上面那条通过——而空台账正是**最彻底的过期**：
    它连「这里曾经有什么」都不再说。
    """
    contract_parts = {"text", "reasoning", "tool_call", "citation", "question", "action_card"}

    covered = set(session_items.PART_PROVENANCE) | set(session_items.NOT_REBUILT_PARTS)

    assert covered == contract_parts, (
        f"契约第 7 节的六种 part 与台账不一致：未覆盖 {sorted(contract_parts - covered)}，"
        f"多出 {sorted(covered - contract_parts)}"
    )
