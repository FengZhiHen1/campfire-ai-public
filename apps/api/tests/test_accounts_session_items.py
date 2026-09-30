"""SDK 会话条目 → parts/标题/预览的解析（纯逻辑，不连库）。

对应 ``docs/技术设计/面/consult/HTTP与SSE契约.md`` 第 3.2、3.3、7 节。

## 这里的每条用例钉的都是什么

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

import pytest

from campfire.modules.accounts.session_items import (
    INJECTED_MESSAGE_PREFIXES,
    INTERRUPTED_TOOL_SUMMARY,
    PREVIEW_MAX_CHARS,
    TITLE_ELLIPSIS,
    TITLE_FALLBACK,
    TITLE_MAX_CHARS,
    TOOL_SUMMARY_MAX_CHARS,
    UNKNOWN_TOOL_NAME,
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
    reasoning_text,
    tool_failure_message,
)

# ---------------------------------------------------------------------------
# 实测形状的样本
# ---------------------------------------------------------------------------


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

    assert parts[0]["ok"] is False
    assert parts[0]["summary"] == "后端炸了"


def test_hydration_fills_interrupted_tool_call() -> None:
    """被打断的调用（有调用、无结果）补成失败 part，而不是从历史里消失。

    依据：`_ToolCallTracker` 在运行触顶或取消时会给被打断的调用补一条结束事件。
    历史里若没有它，「当时调过一个没有结果的工具」这件事就查不到了。
    """
    items = [_stored(1, _user("问")), _stored(2, _function_call("read_alpha", "call-1"))]

    parts = build_messages(items)[1]["parts"]

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

    assert parts[0]["tool_name"] == UNKNOWN_TOOL_NAME


def test_tool_summary_is_bounded() -> None:
    """工具产出很长时 `summary` 必须有界（CORE-11）。"""
    long_output = "长" * (TOOL_SUMMARY_MAX_CHARS * 3)
    items = [
        _stored(1, _user("问")),
        _stored(2, _function_call("read_alpha", "c1")),
        _stored(3, _function_output("c1", long_output)),
    ]

    summary = build_messages(items)[1]["parts"][0]["summary"]

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
