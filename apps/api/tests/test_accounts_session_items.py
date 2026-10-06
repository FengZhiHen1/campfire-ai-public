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
    ANSWERS_HEADER,
    ASK_USER_SUCCESS_OUTPUT,
    COMPACTED_SUMMARY_TAG,
    INJECTED_MESSAGE_PREFIXES,
    INTERRUPTED_TOOL_SUMMARY,
    PART_TYPE_QUESTION_RECORD,
    PREVIEW_MAX_CHARS,
    QUESTION_BATCH_ID_PREFIX,
    QUESTION_ITEMS_MAX,
    TITLE_ELLIPSIS,
    TITLE_FALLBACK,
    TITLE_MAX_CHARS,
    TOOL_SUMMARY_MAX_CHARS,
    UNKNOWN_TOOL_NAME,
    MessagePart,
    QuestionPart,
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
    question_answered_verdicts,
    question_record_part,
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


def test_hydration_rebuilds_a_question_record_part() -> None:
    """★ 主用例：带 `ask_user` 调用对的历史，水合后必须出现提问 part。

    这就是 T27 的缺陷现场——刷新后 `.question-card` 消失，因为后端从不产出
    提问 part（`history.ts` 因此永不命中）。

    判别性：把 `MessagePart` 联合里新加的 `QuestionRecordPart` 去掉（或删掉
    `add_tool_output` 里追加 part 的那三行）⇒ 本用例在第一处断言就失败。

    ⚠ T31 之后它叫 `question-record`（不再复用事件侧的 `question`，理由见
    `PART_TYPE_QUESTION_RECORD`），且**必须**带服务端判定的 `answered`。
    """
    parts = build_messages(_question_turn_items())[1]["parts"]

    questions = [part for part in parts if part["type"] == PART_TYPE_QUESTION_RECORD]

    assert len(questions) == 1, "刷新后必须仍有且只有一个提问 part（T24 的缺陷现场）"
    question = questions[0]
    assert question["batch_id"].startswith(QUESTION_BATCH_ID_PREFIX)
    assert _ASK_USER_CALL_ID in question["batch_id"], "批次标识必须能从调用标识追溯回来"
    assert [item["id"] for item in question["items"]] == ["object_name"]
    # 题干逐字保留：使用者要读的正是这句话。
    assert "你平时怎么称呼这孩子" in question["items"][0]["prompt"]
    assert question["items"][0]["allow_skip"] is True
    # ★ 这组题后面没有任何使用者消息 ⇒ 未作答 ⇒ **可作答**（本包修的那条）。
    assert question["answered"] is False


def test_hydration_question_record_part_shape_matches_the_wire_contract() -> None:
    """水合出的 `question-record` part 形状必须与契约第 7 节逐字一致。

    前端 `history.ts` 的 `case 'question-record'` 读的是 `batch_id` / `items` / `answered`，
    而 `parts.tsx` 的 `QuestionRecordPart` 再逐项读 `id` / `prompt` / `options`
    / `allow_skip`。少一个键或改一个名字，水合出的卡就是空的——
    而那种失败在浏览器里只表现为「卡片不出现」，不会报错。

    ★ 与 `test_question_event_part_shape_stays_wire_exact` 是**两条都承重**的用例：
    事件侧断 `{type, batch_id, items}`、水合侧断 `{type, batch_id, items, answered}`。
    去掉任一条，另一侧的「多一个字段」就没人看得见（那正是 T31 要防的
    「把回看侧字段塞进流出侧载荷」）。
    """
    parts = build_messages(_question_turn_items())[1]["parts"]
    question = next(part for part in parts if part["type"] == PART_TYPE_QUESTION_RECORD)

    assert set(question) == {"type", "batch_id", "items", "answered"}
    assert set(question["items"][0]) == {"id", "prompt", "options", "allow_skip"}


def test_question_event_part_shape_stays_wire_exact() -> None:
    """事件侧的 `question` part 形状**一字未动**：`{type, batch_id, items}` 三项。

    这是 T31 硬边界第 4 条（不许改动流出侧载荷）的机械守卫。`question` 描述的是
    「刚发出、尚未作答」的提问——发出即结束运行（基座 7.2 节），因此它的载荷里
    不可能有「已作答」。若有人把 `answered` 加到它上面，本用例红。

    判别性：往 `QuestionPart` 加一个字段（或把它换成 `QuestionRecordPart`）⇒ 红。
    """
    assert set(QuestionPart.__annotations__) == {"type", "batch_id", "items"}
    # 强判据：事件侧类型不在水合 parts 的取值域里（否则「水合会不会产出它」就没有答案）。
    assert "question" not in _message_part_type_names()
    assert "question" in session_items.NOT_REBUILT_PARTS


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

    question = next(part for part in build_messages(items)[1]["parts"] if part["type"] == PART_TYPE_QUESTION_RECORD)

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

    判别性：把 `question_record_part` 里 `output != ASK_USER_SUCCESS_OUTPUT` 那一句去掉，
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


def test_question_record_part_rejects_bad_input() -> None:
    """`question_record_part` 的每一条判据都各有一个「喂坏输入 ⇒ 立刻失败」的对照。

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
    assert question_record_part(call_id, good_arguments, ASK_USER_SUCCESS_OUTPUT, answered=False) is not None

    for label, (given_call_id, arguments, output) in cases.items():
        assert question_record_part(given_call_id, arguments, output, answered=False) is None, (
            f"{label} 必须重建不出提问"
        )


def test_hydration_keeps_the_tool_call_row_next_to_the_question() -> None:
    """提问 part 与那次工具调用同在一条助手消息里（不是新开一条消息）。

    依据是契约第 7 节的分组规则：一次运行的产出合成一条助手消息。分成两条会让
    刷新前后的消息条数变化（流式期间 1 条、刷新后 2 条）。
    """
    messages = build_messages(_question_turn_items())

    assert len(messages) == 2, "一条使用者 + 一条助手"
    parts = messages[1]["parts"]
    types = [part["type"] for part in parts]
    assert types == ["reasoning", "text", "tool_call", PART_TYPE_QUESTION_RECORD]
    # 工具行仍在（它是「向你提问 · 已结束」那句话的来源，T24 靠它看见「已结束」）。
    # 判别字段先断言再取该 part 独有的键（同文件既有用例的写法）。
    tool_part = parts[2]
    assert tool_part["type"] == "tool_call"
    assert tool_part["tool_name"] == ASK_USER_TOOL_NAME


# ---------------------------------------------------------------------------
# T31：`answered` 的三态判定（★ 本包的主承重区）
#
# 这条路要修的是 T27 自己登记的残余（其报告 §8.1-1）：
# **刷新后提问卡不能继续作答** ⇒ 一组**从未被作答**的提问在功能上永久丢失。
#
# 三个状态的呈现由前端决定，但**判定必须由服务端给出**（硬边界 1：不许让前端猜）。
# 下面每条用例都对应一个具体的失败方向，其中两条是**互相反向**的误判。
# ---------------------------------------------------------------------------


def _answer(text_ids: Sequence[str] = ("object_name",)) -> dict:
    """一条实测形状的作答消息（逐字对齐 `answers.render_answers` 的产出形状）。"""
    lines = [ANSWERS_HEADER] + [f"{item_id}：可以" for item_id in text_ids]
    return {"role": "user", "content": "\n".join(lines)}


def _current_time_injection() -> dict:
    """一条每轮都会注入的 T27 时间信封（T31 实测的坑 1 的载体）。

    名字带 `current_time` 而不是 `_injection`：后者是本文件既有的辅助函数
    （`_injection(content)`），同名会**静默覆盖**它并让「每个声明的前缀都被识别」
    那条用例以 TypeError 失败——那看起来像实现坏了，其实是本函数抢了名字。
    """
    return {
        "role": "user",
        "content": "<current_time>\n  现在是 2026-10-06T00:00:00+00:00（UTC）。\n</current_time>",
    }


def test_question_answered_header_matches_the_renderer() -> None:
    """★ `ANSWERS_HEADER` 必须与 `answers.render_answers` 的产出逐字一致。

    这是**判据的判据**：水合靠这句话判定「这组题被作答了」。它一旦与渲染器漂移，
    **已作答**的组会被判成**未作答** ⇒ 使用者重复作答（任务书 §三 点名的
    「最危险的失败方向」），而且没有任何用例会红。

    因此这里直接跑真实渲染器，而不是再抄一份字面量。
    """
    from campfire.surfaces.consult.answers import AnswerItem, render_answers

    rendered = render_answers([AnswerItem(id="object_name", value="可以")])
    assert rendered.split("\n")[0] == ANSWERS_HEADER
    assert rendered.startswith(ANSWERS_HEADER)


def test_question_answered_checkpoint_tag_matches_the_compaction_parser() -> None:
    """★ `COMPACTED_SUMMARY_TAG` 必须与 `agent/context/window` 的同名常量一致。

    `modules/*` 不得 import `agent/*`（项目结构设计第 7 节），因此这份字面量必须在两处
    各写一份，相等关系只能靠本用例机械守住。漂移的后果是**静默**的：判据认不出复述块，
    于是把「无法判定」当成「未作答」，或在反向把它当成作答。
    """
    assert COMPACTED_SUMMARY_TAG == window.COMPACTED_SUMMARY_TAG


def test_question_answered_true_when_followed_by_the_answers_message() -> None:
    """**已作答** ⇒ `True`（★ 反向误判的靶子：这一条判错会让使用者重复作答）。"""
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, _answer()),
        _stored(5, _assistant("收到。")),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: True}


def test_question_answered_true_when_the_answer_came_after_another_message() -> None:
    """★ 判据取「存在作答」而不是「第一条就是作答」（失败方向选安全的那边）。

    窗口里可能先出现一条新话题、**之后**才出现作答（使用者先说了别的，再回头把那组题答了）。
    按「第一条」判会给出 `False` ⇒ 卡片重新变成可作答 ⇒ **使用者对同一组题作答两次**
    （任务书 §三 点名的方向）；按「存在」判给出 `True` ⇒ 只读。

    反向的代价对比：这个读法唯一漏掉的是「先发新话题、再回头作答」的组被当成已作答——
    而那组**确实是被作答了**，只读是正确的。两种读法在真实库 60 组上读数相同
    （T31 实测：31/29/0 两者一致），因此这条只能靠构造用例证明。

    判别性：把 `_window_verdict` 的 `any(...)` 改回 `bodies[0].lstrip().startswith(...)` ⇒ 红。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, _user("我先说个别的：昨天他又不肯出门。")),
        _stored(5, _answer()),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: True}


def test_question_answered_false_when_the_user_moved_on() -> None:
    """**未作答**（使用者忽略提问去问别的）⇒ `False`。

    这一条正是**表头那一半承重**的地方：只按「后面有没有使用者消息」判会把它误判成
    已作答 ⇒ **永久失去补答能力**（本包要修的那个缺陷换了张脸回来）。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, _user("换个话题：我想先说说别的。")),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: False}


def test_question_answered_false_when_nothing_follows() -> None:
    """**未作答**（提问后什么都没有）⇒ `False` ⇒ 前端可作答（本包修的那条）。"""
    items = [_stored(1, _user("问")), _stored(2, _ask_user_call()), _stored(3, _ask_user_output())]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: False}
    # 端到端：水合出的 part 也必须是 `answered=False`（前端据此渲染成可作答）。
    part = next(p for p in build_messages(items)[1]["parts"] if p["type"] == PART_TYPE_QUESTION_RECORD)
    assert part["answered"] is False


def test_question_answered_skips_injected_rows_before_the_user_message() -> None:
    """★ 坑 1：注入排在本次使用者消息**之前**（`runner.py:402-405`）。

    实测的落库顺序是 `activated_record → 注入 → 使用者消息`。若判据把注入当成
    「后继使用者消息」，它会看到那条 `<current_time>`（不是作答）⇒ 把**已作答**
    判成**未作答** ⇒ 使用者重复作答。

    判别性：把 `_window_verdict` 里的 `is_injected_message` 跳过那句删掉 ⇒ 本用例红
    （注入进 bodies ⇒ 重复检测/表头判定给出 `None` 或 `False`）。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, _current_time_injection()),
        _stored(5, _answer()),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: True}


def test_question_answered_ignores_repeated_identical_injections() -> None:
    """★ 注入不参与「复述」判据：同一段注入出现两次**不是**压缩复述。

    这是「跳过注入」那一半真正承重的地方（它的价值不在「第一条是谁」，而在**别把注入
    算进复述检测**）：一次窗口里可能落进两轮的注入，而技能目录注入在目录不变时**逐字相同**。
    若不跳过注入，重复检测会把它当成复述 ⇒ 返回 `None` ⇒ **一组其实已作答的题变成只读**
    （方向上是安全的，但它是一次凭空的误判，会把可补答的组错误地锁住）。

    真实库里当前没有实例（T31 实测：60 个窗口里含重复注入正文的 = 0；全库含重复注入正文的
    会话 = 0），但机制在——`runner._render_current_time` 是**每轮**注入的。因此这条只能靠
    构造用例证明。

    判别性：把 `_window_verdict` 里的 `if is_injected_message(item): continue` 删掉 ⇒ 红
    （重复检测命中 ⇒ 返回 `None` 而不是 `True`）。
    """
    items = [
        _stored(1, _user("第一轮")),
        _stored(2, _ask_user_call(call_id="call-A")),
        _stored(3, _ask_user_output(call_id="call-A")),
        # 下一轮的注入：两条**逐字相同**的技能目录信封（目录没变）。
        _stored(4, _injection()),
        _stored(5, _injection()),
        _stored(6, _answer()),
    ]

    assert question_answered_verdicts(items) == {"call-A": True}


def test_question_answered_separates_two_batches_with_identical_items() -> None:
    """★ 位置那一半承重：两组题**题标识完全相同**，A 已作答 / B 未作答。

    只按「历史里有没有作答消息」判会把 A 的作答算到 B 头上 ⇒ B 被判成已作答
    ⇒ **永久失去补答能力**。位置窗口正是为了分开它们。

    判别性：把 `question_answered_verdicts` 的窗口起点（`start`）改成 0（扫整段历史）⇒ 红。
    """
    items = [
        _stored(1, _user("第一轮")),
        _stored(2, _ask_user_call(call_id="call-A")),
        _stored(3, _ask_user_output(call_id="call-A")),
        _stored(4, _answer()),
        _stored(5, _user("第二轮")),
        _stored(6, _ask_user_call(call_id="call-B")),
        _stored(7, _ask_user_output(call_id="call-B")),
        _stored(8, _user("我还有个新问题，先不回答这组。")),
    ]

    assert question_answered_verdicts(items) == {"call-A": True, "call-B": False}


def test_question_answered_null_when_a_late_answer_lands_in_a_later_window() -> None:
    """★ 跨窗口的迟到作答 ⇒ A 判 `None`（而不是 `False`）。

    构造（产品代码实测复现，T31 r3）：

        call(A) → out(A) → user("换个话题") → call(B) → out(B) → user(作答)

    真值是「那条作答是给 **A** 的迟到作答」（使用者在 B 提问之后才回头把 A 答了），
    B 并未被作答。而按「本组窗口里有没有表头消息」判会给出 `A=False`、`B=True`：

    - `A=False` ⇒ A 的卡片重新变成可作答 ⇒ 使用者**对 A 重复作答**（本包要消除的方向）；
    - `B=True` ⇒ B 永久失去补答（服务端无法区分，见报告「残余」一节，本包不修）。

    A 侧可以判：那条表头消息**落在比 A 更晚的提问的窗口里**，因此它完全可能就是 A 的
    迟到作答 ⇒ 服务端不得断言「A 未被作答」⇒ `None`（fail-closed，只读）。

    判别性：撤掉 `question_answered_verdicts` 里那句跨窗口迟到作答的检查 ⇒ 本用例红
    （A 变回 `False`）。它只把 `False` 降级成 `None`，因此**不会**制造新的
    「永久失去补答」——B 的 `True` 不受影响（这是本包明确登记、不修的残余）。
    """
    items = [
        _stored(1, _user("问 A")),
        _stored(2, _ask_user_call(call_id="call-A")),
        _stored(3, _ask_user_output(call_id="call-A")),
        _stored(4, _user("换个话题：我想先说说别的。")),
        _stored(5, _ask_user_call(call_id="call-B")),
        _stored(6, _ask_user_output(call_id="call-B")),
        _stored(7, _answer()),
    ]

    verdicts = question_answered_verdicts(items)

    # 核心断言：A 绝不能是 `False`（那会让使用者重复作答）。
    assert verdicts["call-A"] is not False, "A 被误判为未作答 ⇒ 卡片可作答 ⇒ 使用者会对 A 重复作答"
    # B 的 `True` 是本包不修的残余（无法区分，见报告）；这里把它钉成事实记录。
    assert verdicts["call-B"] is True


def test_question_answered_null_when_a_compaction_checkpoint_is_in_the_window() -> None:
    """★ 坑 2：压缩会**复述**旧尾部 ⇒ 无法判定 ⇒ `None`（fail-closed）。

    `compaction.appended_items` 追加「[检查点] + [尾部原文]」，被保留的尾部因此在历史里
    存在**两份**（`compaction.py:468` 自己写明这个代价）。当前库里没有实例
    （T31 实测 `<compacted-summary>` = 0），但这是必然机制。

    这一条的**方向**是关键：复述块里的旧作答消息与本组的作答在形状上无法区分 ⇒
    猜成 `True` 会让本组**永久无法补答**；猜成 `False` 会让使用者**重复作答**。
    **两边都不许猜** ⇒ `None` ⇒ 前端只读。

    ★ 构造的形状是**两轮提问**，这一点是承重的前提：A 组的作答（第 4 条）落在 B 组的
    窗口**之外**（窗口从 B 的回执之后开始），因此窗口里那条表头消息**只有一份**
    ——「同一正文出现两份」那条检测**抓不到它**，只有「窗口里出现检查点」这一条能抓。
    若把检查点判成「跳过」（而不是返回 `None`），它会落到
    `is_injected_message` 上被静默跳过（`<compacted-summary>` 也登记在
    `INJECTED_MESSAGE_PREFIXES` 里），于是 bodies = [复述的作答, 新话题] ⇒ 返回 `True`
    ⇒ **未作答被误判成已作答**。

    判别性：把 `_window_verdict` 里 `if _is_compaction_checkpoint(item): return None`
    改成 `continue` ⇒ 本用例红。
    """
    items = [
        _stored(1, _user("第一轮")),
        _stored(2, _ask_user_call(call_id="call-A")),
        _stored(3, _ask_user_output(call_id="call-A")),
        _stored(4, _answer()),
        _stored(5, _user("第二轮")),
        _stored(6, _ask_user_call(call_id="call-B")),
        _stored(7, _ask_user_output(call_id="call-B")),
        # 压缩发生在这里：检查点 + 被保留的尾部（含 A 组的那条作答）被**整块追加**。
        _stored(8, {"role": "user", "content": f"{COMPACTED_SUMMARY_TAG}\n旧摘要\n</compacted-summary>"}),
        _stored(9, _answer()),
        _stored(10, _user("压缩之后我发了一条新话题。")),
    ]

    verdicts = question_answered_verdicts(items)

    # A 组的窗口里就是那条原始作答 ⇒ 已作答。
    assert verdicts["call-A"] is True
    # B 组：窗口里那条表头消息是**复述**的（不是 B 组的作答）⇒ 判不出来 ⇒ 只读。
    assert verdicts["call-B"] is None


def test_question_answered_null_when_the_user_body_repeats() -> None:
    """★ 坑 2 的第二种表现：窗口里同一段使用者正文出现**两次** ⇒ `None`。

    复述块的边界恰好落在窗口内部时，检查点本身不在窗口里，但复述的事实仍然可见
    （同一段正文两份）。判据必须看得见它——否则会把复述里的旧作答当成本组的作答。

    判别性：把 `_window_verdict` 里的重复检测删掉 ⇒ 红。
    """
    body = _answer()
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, dict(body)),
        _stored(5, dict(body)),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: None}


def test_question_answered_null_when_a_user_message_has_no_readable_text() -> None:
    """★ 判据看不到内容时**不猜** ⇒ `None`（fail-closed）。

    这是「反空断言」的另一面：若把「读不出文本」当成「不是作答」，判据就在**没有依据**时
    给出一个看起来确定的结论。三条 fail-closed 路径都必须有用例。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: None}


def test_question_answered_ignores_a_failed_ask_user_call() -> None:
    """★ 失败的 `ask_user`（参数不合法）**不作为窗口终点**。

    它从未向使用者呈现过任何东西（`QuestionGate` 也不为它结束运行），因此不产生 part。
    若把它算作终点，一次「先失败一次、再成功一次」的会话会把上一组的窗口切碎——
    上一组的真实作答落到窗口之外 ⇒ 判成未作答 ⇒ **使用者重复作答**。

    判别性：把 `_ask_user_turns` 里 `output != ASK_USER_SUCCESS_OUTPUT` 那句删掉 ⇒ 红。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call(call_id="call-ok")),
        _stored(3, _ask_user_output(call_id="call-ok")),
        # 一次失败的调用（参数不合法）夹在窗口里，且**在**真实作答之前。
        _stored(4, _ask_user_call(call_id="call-bad")),
        _stored(
            5,
            _ask_user_output(
                call_id="call-bad",
                output='<tool_error code="tool_invalid_arguments">items 为空</tool_error>',
            ),
        ),
        _stored(6, _answer()),
    ]

    verdicts = question_answered_verdicts(items)

    # 失败的调用不进结论（它没有 part）。
    assert verdicts == {"call-ok": True}


def test_question_answered_null_when_the_same_call_appears_twice() -> None:
    """★ 同一次提问在历史里出现两份（复述的最坏形态）⇒ `None`（两侧一起 fail-closed）。

    「哪一份的窗口才是本组的窗口」没有答案。判据不得任选一份——选错任一边的代价都是
    上面两条点名的失败方向之一。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call()),
        _stored(3, _ask_user_output()),
        _stored(4, _answer()),
        # 复述：整对调用/结果（连同作答）再出现一次。
        _stored(5, _ask_user_call()),
        _stored(6, _ask_user_output()),
    ]

    assert question_answered_verdicts(items) == {_ASK_USER_CALL_ID: None}


def test_question_answered_empty_input_yields_no_verdicts() -> None:
    """**反空断言**：喂空集 ⇒ 立刻空结果（而不是一条恒真的完整性断言）。

    若判据实现成「每组都必定有一个结论」，它就必须在空集上撒一个值出来——
    这里明确断言**不撒**：没有提问就没有结论，调用方（`_Hydration`）按缺键 fail-closed。
    """
    assert question_answered_verdicts([]) == {}
    # 非 0 正例对照：同一函数在真实形状上必须给出非空结论（否则上面的空集断言恒真）。
    assert question_answered_verdicts(_question_turn_items()) == {_ASK_USER_CALL_ID: False}


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


def test_part_ledger_covers_the_seven_parts_of_the_contract() -> None:
    """台账必须覆盖契约第 7 节列的七种 part（一个不漏）。

    没有这一条，「两张表都空了」也能让上面那条通过——而空台账正是**最彻底的过期**：
    它连「这里曾经有什么」都不再说。

    ★ T31 之后是**七种**：六种原有 part 加 `question-record`（水合侧专有）。
    事件侧的 `question` 也在契约表里，因此两张表合起来必须同时含 `question` 与
    `question-record`——前者在 `NOT_REBUILT_PARTS`（它不在水合 parts 的取值域里），
    后者在 `PART_PROVENANCE`。

    ★ T32 之后 `action_card` 从 `NOT_REBUILT_PARTS` 移到 `PART_PROVENANCE`：
    它现在真的在水合 parts 的取值域里。**本用例的集合不变**（七种仍是七种）——
    变的只是它落在哪张表，而那由上面那条用例的判据 1/2/3 机械守住。
    """
    contract_parts = {"text", "reasoning", "tool_call", "citation", "question", "question-record", "action_card"}

    covered = set(session_items.PART_PROVENANCE) | set(session_items.NOT_REBUILT_PARTS)

    assert covered == contract_parts, (
        f"契约第 7 节的七种 part 与台账不一致：未覆盖 {sorted(contract_parts - covered)}，"
        f"多出 {sorted(covered - contract_parts)}"
    )


# ---------------------------------------------------------------------------
# 行动卡的水合（★ T32 的主缺陷：刷新后行动卡消失）
#
# 实测（T32 第 0 步，用**产品代码** build_messages 对一条调用对做水合）：
#   现状（HEAD）产出的 part 类型 = ['tool_call']，action_card 数 = 0 ⇒ 红。
# 缺陷形态与提问卡当初一模一样：live 通路是好的，只有刷新后（历史水合）卡片消失。
# 根因是 `MessagePart` 联合里没有 `action_card`（见该联合的说明）。
# ---------------------------------------------------------------------------

#: 一条真实的 `emit_emergency_action_card` 参数（形状取自 `EmitEmergencyActionCardArgs`；
#: `annotations` 用**输入形状** `{line_ref, source, confidence}`——这正是落库的形状，
#: 也是本包第一版实现踩过的坑，见 `_card_annotations` 的说明）。
_CARD_ARGUMENTS = json.dumps(
    {
        "sections": [
            {"key": "status", "heading": "当前状态", "lines": ["当前沟通较平时明显减少，等待至少 10 秒"]},
            {"key": "communicate", "heading": "立即怎么沟通", "lines": ["一次只让一个人讲话"]},
            {"key": "do_now", "heading": "立即做", "lines": ["把灯光调暗，减少在场人数"]},
            {"key": "avoid", "heading": "不要做", "lines": ["不要突然触碰"]},
            {"key": "medical_checks", "heading": "需要的医疗检查", "lines": ["需要确认有无疼痛来源"]},
            {"key": "safety", "heading": "安全措施", "lines": ["移开通道上的障碍物"]},
            {"key": "when_to_escalate", "heading": "何时升级", "lines": ["出现意识改变时立即求助"]},
        ],
        "states": [
            {"key": "deviation", "value": "marked"},
            {"key": "communication", "value": "reduced"},
            {"key": "sensory_load", "value": "high"},
            {"key": "medical_risk", "value": "uncertain"},
        ],
        "annotations": [{"line_ref": 2, "source": "ai_inference", "confidence": "possible"}],
    },
    ensure_ascii=False,
)

_CARD_CALL_ID = "call_00_t32jbhu0000000000000001"
#: 成功回执里那个 `card_id` 的实测取值形状（`uuid4().hex`，32 位小写十六进制）。
_CARD_ID = "7794fb3c041c44c291ebd0bc879755fa"


def _card_call(call_id: str = _CARD_CALL_ID, arguments: str = _CARD_ARGUMENTS) -> dict:
    """实测形状的 `emit_emergency_action_card` 调用条目。"""
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": "emit_emergency_action_card",
        "arguments": arguments,
    }


def _card_output(call_id: str = _CARD_CALL_ID, output: str | None = None) -> dict:
    """实测形状的行动卡结果条目（成功回执原文，取自 `tools/emergency_card.py:406`）。"""
    receipt = (
        output if output is not None else json.dumps({"card_id": _CARD_ID, "state": "emitted"}, ensure_ascii=False)
    )
    return {"type": "function_call_output", "call_id": call_id, "output": receipt}


def _card_turn_items() -> list[StoredItem]:
    return [
        _stored(1, _user("他现在在商场里捂着耳朵蹲下了，我该怎么办？")),
        _stored(2, _reasoning("先判断现场变量。")),
        _stored(3, _card_call()),
        _stored(4, _card_output()),
    ]


def test_action_card_title_and_sections_match_the_tool() -> None:
    """★ 判据的判据：两份字面量必须与**真实工具**逐字一致。

    与 `test_ask_user_success_output_matches_the_tool_handler` 同法，而不是再抄一份
    字面量互比（那样两侧一起漂移仍然全绿）。`modules/*` 不得 import `tools/*`
    （项目结构设计第 7 节），因此相等关系只能由本用例守。

    它同时**跑真实工具**并把真实回执喂给 `action_card_success_card_id`——于是
    「回执格式」这一份跨层约定也被钉住：改回执的键名或 `state` 取值 ⇒ 本用例红。

    判别性：改 `tools/emergency_card.py` 的 `CARD_TITLE` / `SECTION_KEYS` /
    回执键名 / `state` 取值 ⇒ 本用例红（而水合会静默停止产出卡片，若不跑工具就没人看得见）。
    """
    import asyncio

    from campfire.agent.context import CitationRecorder
    from campfire.agent.tools import ActivationState, ToolContext
    from campfire.tools.emergency_card import CARD_TITLE, SECTION_KEYS

    class _Index:
        """最小引用索引（本工具不产出引用，故不落任何东西）。"""

        async def add(self, record: CitationRecord) -> None:
            del record

        async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
            del run_id
            return []

    tool = _product_tool("emit_emergency_action_card")
    context = ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_Index(), run_id="run-1"),
        payload={"account_id": "acct-1"},
    )
    # ★ 走**真实 ToolSpec**（含参数模型的解析与词表校验），而不是直接调 handler：
    # 判据要断的是「产出侧真的产出了什么」。
    outcome = asyncio.run(tool.invoke(context, _CARD_ARGUMENTS))

    assert isinstance(outcome, ToolResult)
    card = outcome.cards[0]

    # 1) 标题字面量。
    assert card.title == CARD_TITLE
    assert session_items.ACTION_CARD_TITLE == CARD_TITLE
    # 2) 七节的键与**顺序**。
    assert tuple(section.key for section in card.sections) == SECTION_KEYS
    assert session_items.ACTION_CARD_SECTION_KEYS == SECTION_KEYS
    # 3) 回执格式：我的判据必须能从**真实回执**里取出那个 card_id。
    assert session_items.action_card_success_card_id(outcome.text) == card.card_id
    # 4) 工具名常量也要与注册清单一致。
    assert tool.name == session_items.EMERGENCY_ACTION_CARD_TOOL_NAME


def _product_tool(name: str):
    """按名字取一个已装配的产品工具（判据要跑真实工具，而不是它的替身）。"""
    for tool in build_product_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"工具 {name!r} 不在产品工具注册清单里")


def test_hydration_rebuilds_an_action_card_part() -> None:
    """★ 主用例：带 `emit_emergency_action_card` 调用对的历史，水合后必须出现行动卡 part。

    这就是本包的缺陷现场——刷新后 `.action-card` 消失，因为后端从不产出行动卡 part
    （`history.ts` 的 `case 'action_card'` 因此永不命中）。

    判别性：把 `MessagePart` 联合里的 `ActionCardPart` 去掉（或删掉 `add_tool_output`
    里分派 `emit_emergency_action_card` 的那几行）⇒ 本用例在第一处断言就失败。
    """
    parts = build_messages(_card_turn_items())[1]["parts"]

    cards = [part for part in parts if part["type"] == "action_card"]

    assert len(cards) == 1, "刷新后必须仍有且只有一个行动卡 part"
    card = cards[0]
    # ★ `card_id` 取自回执真值，**不是**派生值——前端凭它与最新卡比较判旧卡失效，
    # 派生值会让同一张卡在两个时刻拿到两个 id。
    assert card["card_id"] == _CARD_ID
    assert card["title"] == "现场行动卡"
    assert [section["key"] for section in card["sections"]] == [
        "status",
        "communicate",
        "do_now",
        "avoid",
        "medical_checks",
        "safety",
        "when_to_escalate",
    ]
    assert card["states"] == [
        {"key": "deviation", "value": "marked"},
        {"key": "communication", "value": "reduced"},
        {"key": "sensory_load", "value": "high"},
        {"key": "medical_risk", "value": "uncertain"},
    ]
    # ★ 标注必须是**线格式**（`{target, kind}`），不是落库的输入形状。
    assert card["annotations"] == [{"target": "2", "kind": "ai_inference:possible"}]
    # 题干逐字保留：使用者要读的正是这些行。
    assert "把灯光调暗" in card["sections"][2]["lines"][0]


def test_hydration_action_card_part_shape_matches_the_wire_contract() -> None:
    """水合出的 `action_card` part 形状必须与契约第 7 节 + 基座 7.3 节逐字一致。

    前端 `history.ts` 的 `case 'action_card'` 读的是 `card_id` / `title` / `sections` /
    `states` / `annotations`，而 `parts.tsx` 的 `ActionCardPart` 再逐项读
    `key` / `heading` / `lines` 与 `target` / `kind`。少一个键或改一个名字，
    水合出的卡就是空的——而那种失败在浏览器里只表现为「卡片不出现」，不会报错。

    ★ 与**事件侧**的同一形状的相等关系：本包刻意不另立「水合侧专有」的 part 类型
    （与提问那一对相反），理由是回看侧要说的事实与流出侧完全一样。因此这里断言
    字段集合**恰好**是基座 7.3 节那五个 + `type`——多一个字段就说明有人把回看侧的
    东西塞进了流出侧载荷（那正是 T31 对提问明确禁止的形态）。
    """
    parts = build_messages(_card_turn_items())[1]["parts"]
    card = next(part for part in parts if part["type"] == "action_card")

    assert set(card) == {"type", "card_id", "title", "sections", "states", "annotations"}
    assert set(card["sections"][0]) == {"key", "heading", "lines"}
    assert set(card["states"][0]) == {"key", "value"}
    assert set(card["annotations"][0]) == {"target", "kind"}
    # 事件侧的形状是本模块**不产出**的一份读数，它同样按基座 7.3 节断死。
    assert {state["key"] for state in card["states"]} <= {
        "deviation",
        "communication",
        "sensory_load",
        "medical_risk",
    }


def test_hydration_does_not_rebuild_an_action_card_from_a_failed_call() -> None:
    """参数不合法的那次调用**没有**呈现过任何东西 ⇒ 不得产出行动卡。

    参数不合法的调用在 `ToolSpec._parse` 就得到
    `<tool_error code="tool_invalid_arguments">…</tool_error>`，`ToolResult` **从不构造**，
    因此事件流里**没有**任何卡片（`test_emergency_card.py` 的
    `test_no_action_card_event_is_emitted_for_a_rejected_payload` 断的就是这一条）。
    若水合不管产出、只看参数形状，就会给一张「当时从未出现过」的行动卡——那是伪造。

    ⚠ **本条用例实际承重的是哪一处，我实测过并如实写明**（消融读数见报告 §5.2）：
    拦下它的是 `add_tool_output` 里的 **`ok` 闸门**（`failure is not None` ⇒ 提前返回），
    **不是** `action_card_part` 内部的回执判据——因为 `ok=False` 时根本走不到那里。
    我最初的写法以为它测的是后者，**消融 A 证明它没有变红**（那正是「判据无用」的读数）。
    因此这一条留着（它确实钉住了一个真实分支），而**隔离回执判据**由下面那条用例承担。
    """
    items = [
        _stored(1, _user("问")),
        _stored(2, _card_call()),
        _stored(
            3,
            _card_output(
                output=(
                    '<tool_error code="tool_invalid_arguments">'
                    "工具 emit_emergency_action_card 的参数不符合 schema：sections: too_short</tool_error>"
                )
            ),
        ),
    ]

    parts = build_messages(items)[1]["parts"]

    assert [part["type"] for part in parts] == ["tool_call"], "失败的调用不得产出行动卡 part"
    first = parts[0]
    assert first["type"] == "tool_call"
    assert first["ok"] is False


def test_action_card_requires_a_success_receipt_not_just_parsable_arguments() -> None:
    """★ **判据必须取自产出侧**：参数完全合法、但产出不是成功回执 ⇒ 不得产出行动卡。

    ★ 这是本包对 T27 核心裁决的直接落实，而且是**隔离**的那一条
    （上面那条被 `ok` 闸门提前拦下，测不到这里）。本用例刻意用
    **不是工具错误信封**的产出，于是 `ok` 闸门放行、**只有**回执判据能拦住它：

    - 产出是任意成功文本（例如工具其实只发了一半就崩了，或形状漂移）；
    - 产出是 `state` 不是 `emitted` 的 JSON；
    - 产出是没有 `card_id` 的 JSON。

    判别性（**实测，见报告 §5.2 的消融 A**）：把 `action_card_part` 开头的
    `card_id = action_card_success_card_id(output); if card_id is None: return None`
    换成「只看参数形状」的读法 ⇒ 本用例红——水合会造出一张当时从未呈现给使用者的卡。
    """

    def args_only_items(output: str) -> list[StoredItem]:
        return [_stored(1, _user("问")), _stored(2, _card_call()), _stored(3, _card_output(output=output))]

    not_success_receipts = {
        # 成功文本但**不是**本工具的回执格式（`ok` 闸门会放行它）。
        "任意成功文本": "已发出行动卡",
        # state 是产出侧另一个取值（本工具只产 `emitted`；这条挡「别人写的同源回执」）。
        "state 不是 emitted": json.dumps({"card_id": _CARD_ID, "state": "rejected"}, ensure_ascii=False),
        # 有 state 但没有真值 id ⇒ 无法稳定标识这张卡 ⇒ 不产出（不让前端拿到空 id）。
        "没有 card_id": json.dumps({"state": "emitted"}, ensure_ascii=False),
        "card_id 是空串": json.dumps({"card_id": "", "state": "emitted"}, ensure_ascii=False),
        "card_id 不是字符串": json.dumps({"card_id": 7, "state": "emitted"}, ensure_ascii=False),
    }

    # 对照组（非 0 正例）：同一条调用配**真正的**成功回执时必须产出卡片——
    # 否则「一律不产出」也能让上面全部通过。
    assert (
        len(
            [
                p
                for p in build_messages(args_only_items(_card_output()["output"]))[1]["parts"]
                if p["type"] == "action_card"
            ]
        )
        == 1
    )

    for label, output in not_success_receipts.items():
        parts = build_messages(args_only_items(output))[1]["parts"]
        types = [part["type"] for part in parts]
        assert types == ["tool_call"], f"{label} ⇒ 不得产出行动卡（实际 part 类型：{types}）"
        # 工具行本身仍是成功的（产出不是错误信封）——这正是本用例隔离出回执判据的证据；
        # 若这里 ok 是 False，那就说明 ok 闸门先拦下了，本用例不再隔离任何东西。
        tool_part = parts[0]
        assert tool_part["type"] == "tool_call"
        assert tool_part["ok"] is True, f"{label}：ok 闸门先拦下了，本用例没有隔离到回执判据"


def test_action_card_id_is_stable_across_two_hydrations() -> None:
    """★ `card_id` 在同一行数据上两次水合必须一致（稳定性）。

    编排者硬边界第 4 条要求「稳定且可重复的派生值」。本包的做法**不是派生**，
    而是**取回回执里的真值**——稳定性因此来自「同样的输入、纯函数」，
    而不是来自「派生规则恰好不撞车」。本用例同时钉住这两件事：
    id 稳定，且它**等于回执里的那个值**。
    """
    first = next(p for p in build_messages(_card_turn_items())[1]["parts"] if p["type"] == "action_card")
    second = next(p for p in build_messages(_card_turn_items())[1]["parts"] if p["type"] == "action_card")

    assert first["card_id"] == second["card_id"]
    assert first["card_id"] == _CARD_ID
    # 非 0 正例对照：整张卡也必须逐字一致（不是只有 id 一样）。
    assert first == second


def test_action_card_part_rejects_bad_input() -> None:
    """**反空断言**：`action_card_part` 的每一条判据都各有一个「喂坏输入 ⇒ 立刻失败」的对照。

    任务书 §六-6：完整性断言若是恒真的空闸门就毫无价值。这里逐条喂坏输入，
    断言它返回 `None` 而不是造一张**半截卡**（缺节的卡在界面上是「少了几节」，
    且缺得静默——本模块明令「重建不了就不产出」）。
    """
    good_output = json.dumps({"card_id": _CARD_ID, "state": "emitted"}, ensure_ascii=False)
    sections = json.loads(_CARD_ARGUMENTS)["sections"]

    def args_with(**overrides: object) -> str:
        payload = json.loads(_CARD_ARGUMENTS)
        payload.update(overrides)
        return json.dumps(payload, ensure_ascii=False)

    cases = {
        "回执是工具错误": (_CARD_ARGUMENTS, '<tool_error code="tool_failed">炸了</tool_error>'),
        "回执 state 不是 emitted": (_CARD_ARGUMENTS, json.dumps({"card_id": _CARD_ID, "state": "rejected"})),
        "回执没有 card_id": (_CARD_ARGUMENTS, json.dumps({"state": "emitted"})),
        "回执 card_id 是空串": (_CARD_ARGUMENTS, json.dumps({"card_id": "", "state": "emitted"})),
        "回执不是 JSON": (_CARD_ARGUMENTS, "已发卡"),
        "回执是空串": (_CARD_ARGUMENTS, ""),
        "参数不是 JSON": ("{不是 JSON", good_output),
        "参数不是对象": ("[1, 2]", good_output),
        "参数不是字符串": ({"sections": []}, good_output),
        "缺 sections": (json.dumps({"states": [], "annotations": []}), good_output),
        # 七节是硬结构：少一节就是一张残缺的卡（缺节得静默，比缺整张卡更危险）。
        "只有六节": (args_with(sections=sections[:6]), good_output),
        # 同一节出现两次 ⇒ 「这一节是什么」有两个答案。
        "某节重复": (args_with(sections=[*sections, sections[0]]), good_output),
        # 未知的节键：不在七个规范键里 ⇒ 拒绝（否则七节不齐，且顺序语义崩掉）。
        "合同外的节键": (
            args_with(sections=[*sections[:6], {"key": "future", "heading": "x", "lines": ["y"]}]),
            good_output,
        ),
        "某节没有行": (
            args_with(sections=[{**sections[0], "lines": []}, *sections[1:]]),
            good_output,
        ),
        "某节小标题为空": (
            args_with(sections=[{**sections[0], "heading": "  "}, *sections[1:]]),
            good_output,
        ),
        "某行不是字符串": (
            args_with(sections=[{**sections[0], "lines": [1]}, *sections[1:]]),
            good_output,
        ),
        "某行超长（不截断，整体跳过）": (
            args_with(
                sections=[
                    {**sections[0], "lines": ["长" * (session_items.ACTION_CARD_TEXT_MAX_CHARS + 1)]},
                    *sections[1:],
                ]
            ),
            good_output,
        ),
        "states 不是数组": (args_with(states="x"), good_output),
        "state 缺 value": (args_with(states=[{"key": "deviation"}]), good_output),
        "state 的 value 为空": (args_with(states=[{"key": "deviation", "value": ""}]), good_output),
        "annotations 不是数组": (args_with(annotations="x"), good_output),
        # 标注是**输入形状**：线格式的 {target, kind} 在参数里是形状漂移，不得当合法。
        "标注用了线格式的键": (args_with(annotations=[{"target": "2", "kind": "x:y"}]), good_output),
        "标注缺 source": (args_with(annotations=[{"line_ref": 1, "confidence": "likely"}]), good_output),
        "标注 line_ref 是 0": (
            args_with(annotations=[{"line_ref": 0, "source": "history", "confidence": "likely"}]),
            good_output,
        ),
        "标注 line_ref 是字符串": (
            args_with(annotations=[{"line_ref": "1", "source": "history", "confidence": "likely"}]),
            good_output,
        ),
    }

    # 对照组：同一形状的好输入必须**不**返回 None——否则「一切都返回 None」也能全绿。
    assert session_items.action_card_part(_CARD_ARGUMENTS, good_output) is not None

    for label, (arguments, output) in cases.items():
        assert session_items.action_card_part(arguments, output) is None, f"{label} 必须重建不出行动卡"


def test_action_card_annotations_are_encoded_like_the_tool_does() -> None:
    """★ `annotations` 必须被**编码**成线格式 `{target, kind}`，而不是原样搬运。

    这是本包一处**由实测纠正**的判断（第一版按「原样搬运」实现，探针证明它产不出
    任何卡片）。落库的参数是 `{line_ref: int, source, confidence}`，线格式是
    `{target: str, kind: "来源:置信"}`；工具侧 handler 用
    `_encode_annotation_kind` 做这个转换，水合必须做同一个。

    **它只需要分隔约定、不需要产品侧词表**：本用例因此同时断言
    ① 我的编码能被**工具侧的** `decode_annotation_kind` 解回（分隔符与词表口径一致），
    ② 词表外的取值**不被**我拒绝（那是消费侧可见的处置，不是水合该猜的事）。

    判别性：把 `_card_annotations` 的编码改回「原样搬运 target/kind」⇒ 本用例红。
    """
    from campfire.tools.emergency_card import ANNOTATION_CONFIDENCES, ANNOTATION_SOURCES, decode_annotation_kind

    part = session_items.action_card_part(_CARD_ARGUMENTS, _card_output()["output"])

    assert part is not None
    assert part["annotations"] == [{"target": "2", "kind": "ai_inference:possible"}]
    # ① 反向：工具侧的还原函数认得出它（分隔符与两段词表口径一致）。
    assert decode_annotation_kind(part["annotations"][0]["kind"]) == ("ai_inference", "possible")

    # ② 词表口径一致性的**非 0 正例**：产出侧的词表确实是我这份编码的取值域来源。
    assert "ai_inference" in ANNOTATION_SOURCES
    assert "possible" in ANNOTATION_CONFIDENCES

    # ③ 词表外的取值**不**被水合拒绝（不在这里复述词表 ⇒ 不制造静默消失）。
    drifted = json.loads(_CARD_ARGUMENTS)
    drifted["annotations"] = [{"line_ref": 1, "source": "future_source", "confidence": "future_level"}]
    part_drifted = session_items.action_card_part(json.dumps(drifted, ensure_ascii=False), _card_output()["output"])

    assert part_drifted is not None, "词表外的取值不得让整张卡消失（前端会可见地丢弃那一条）"
    assert part_drifted["annotations"] == [{"target": "1", "kind": "future_source:future_level"}]


def test_hydration_keeps_the_tool_call_row_next_to_the_action_card() -> None:
    """行动卡 part 与那次工具调用同在一条助手消息里（不是新开一条消息）。

    依据是契约第 7 节的分组规则：一次运行的产出合成一条助手消息。分成两条会让
    刷新前后的消息条数变化（流式期间 1 条、刷新后 2 条）。
    """
    messages = build_messages(_card_turn_items())

    assert len(messages) == 2, "一条使用者 + 一条助手"
    parts = messages[1]["parts"]
    assert [part["type"] for part in parts] == ["reasoning", "tool_call", "action_card"]
    tool_part = parts[1]
    assert tool_part["type"] == "tool_call"
    assert tool_part["tool_name"] == session_items.EMERGENCY_ACTION_CARD_TOOL_NAME
    assert tool_part["ok"] is True


def test_action_card_and_question_can_coexist_in_one_message() -> None:
    """★ 同一批工具调用里两种产出并存时，两个 part 都必须产出（互不吞掉）。

    这是「分派分支」这一处最可能的实现错误：把两个 `if` 写成一个 `if/elif`
    或过早 `return`，于是后出现的那个静默消失。真实运行里两者可以在同一条运行里
    先后出现（卡片之后模型可以继续输出，基座 7.3 节）。

    判别性：把 `add_tool_output` 里 `ask_user` 分支末尾的 `return` 去掉但改成
    `if/elif` ⇒ 本用例红（少一个 part）。
    """
    # SDK 会把同批调用**连排**、再连排它们的结果（T31/T32 实测：23/62 的
    # 「下一行」不是自己的输出）——本用例刻意用这个真实形状，而不是紧邻形状。
    items = [
        _stored(1, _user("问")),
        _stored(2, _ask_user_call(call_id="call-ask")),
        _stored(3, _card_call(call_id="call-card")),
        _stored(4, _ask_user_output(call_id="call-ask")),
        _stored(5, _card_output(call_id="call-card")),
    ]

    parts = build_messages(items)[1]["parts"]
    types = [part["type"] for part in parts]

    assert types == ["tool_call", "tool_call", PART_TYPE_QUESTION_RECORD, "action_card"], (
        f"两种产出都要在，且按结果行的顺序排列；实际 = {types}"
    )
