"""上下文层：引用索引不变量、注入项排序与失败告知、窗口派生。

对应 docs/技术设计/technical-details/通用基座.md 第 4 节、第 11 节与
docs/技术设计/technical-details/压缩策略.md 第 3、5、8 节。重点在**不变量与拒绝路径**：
「没有索引记录不得成为可引用依据」「注入失败必须显式标注」「不得做滑动窗口」。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from campfire.agent.context import (
    CitationError,
    CitationIndex,
    CitationRecord,
    CitationRecorder,
    InjectionBatch,
    InjectionError,
    InjectionItem,
    InjectionPriority,
    InjectionRenderError,
    UnavailableSource,
    derive_window,
    last_checkpoint_index,
    message_text,
)

FIXED_TIME = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class FakeCitationIndex:
    """引用索引的测试替身：可注入写入失败。"""

    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.records: list[CitationRecord] = []
        self.fail_on_add = fail_on_add

    async def add(self, record: CitationRecord) -> None:
        if self.fail_on_add:
            raise RuntimeError("索引写入失败")
        self.records.append(record)

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return [record for record in self.records if record.run_id == run_id]


def _recorder(index: FakeCitationIndex, *, run_id: str = "run-1") -> CitationRecorder:
    counter = iter(range(1, 1000))
    return CitationRecorder(
        index,
        run_id=run_id,
        clock=lambda: FIXED_TIME,
        id_factory=lambda: f"cite-{next(counter)}",
    )


def test_fake_index_satisfies_the_port() -> None:
    """端口是结构化的 Protocol：实现不需要 import 基座的类型。"""
    assert isinstance(FakeCitationIndex(), CitationIndex)


# --- 引用索引 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_writes_the_index_before_returning_a_credential() -> None:
    index = FakeCitationIndex()
    recorder = _recorder(index)

    record = await recorder.record(source="knowledge", reference="kb-42", summary="标题")

    assert index.records == [record]
    assert record.citation_id == "cite-1"
    assert record.run_id == "run-1"
    assert record.source == "knowledge"
    assert record.reference == "kb-42"
    assert record.recorded_at == FIXED_TIME
    assert recorder.issued == (record,)


@pytest.mark.asyncio
async def test_failed_index_write_does_not_issue_a_citation() -> None:
    """写入失败时不得留下可引用凭据，也不得降级成「无引用」继续。"""
    index = FakeCitationIndex(fail_on_add=True)
    recorder = _recorder(index)

    with pytest.raises(RuntimeError, match="索引写入失败"):
        await recorder.record(source="knowledge", reference="kb-42")

    assert recorder.issued == ()
    assert index.records == []


@pytest.mark.asyncio
async def test_record_requires_source_and_reference() -> None:
    recorder = _recorder(FakeCitationIndex())

    with pytest.raises(CitationError, match="来源"):
        await recorder.record(source="", reference="kb-42")
    with pytest.raises(CitationError, match="业务回指"):
        await recorder.record(source="knowledge", reference="")


def test_recorder_requires_run_id() -> None:
    with pytest.raises(CitationError, match="run_id"):
        CitationRecorder(FakeCitationIndex(), run_id="")


@pytest.mark.asyncio
async def test_issued_order_matches_write_order() -> None:
    index = FakeCitationIndex()
    recorder = _recorder(index)

    first = await recorder.record(source="a", reference="1")
    second = await recorder.record(source="b", reference="2")

    assert recorder.issued == (first, second)
    assert await index.list_for_run("run-1") == [first, second]


# --- 注入项 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_orders_by_priority_and_records_referable_items_only() -> None:
    index = FakeCitationIndex()
    recorder = _recorder(index)
    batch = InjectionBatch(
        [
            InjectionItem(source="retrieved", content="资料", reference="kb-1", summary="资料摘要"),
            InjectionItem(
                source="skill-catalog", content="<available_skills/>", priority=InjectionPriority.SKILL_CATALOG
            ),
            InjectionItem(source="profile", content="档案摘要"),
        ]
    )

    messages = await batch.render(recorder)

    assert [message["content"] for message in messages] == ["<available_skills/>", "资料", "档案摘要"]
    assert [record.reference for record in recorder.issued] == ["kb-1"]
    assert [record.source for record in index.records] == ["retrieved"]


@pytest.mark.asyncio
async def test_render_preserves_input_order_within_the_same_priority() -> None:
    batch = InjectionBatch([InjectionItem(source=f"s{index}", content=f"c{index}") for index in range(3)])

    messages = await batch.render(_recorder(FakeCitationIndex()))

    assert [message["content"] for message in messages] == ["c0", "c1", "c2"]


@pytest.mark.asyncio
async def test_render_is_empty_without_items() -> None:
    assert await InjectionBatch().render(_recorder(FakeCitationIndex())) == ()


@pytest.mark.parametrize("role", ["system", "tool", ""])
def test_injection_rejects_roles_outside_the_allowed_set(role: str) -> None:
    """系统提示必须静态：注入消息不得借 system 角色改写它（压缩策略第 8 节）。

    静态类型已排除 ``system``，但装配处的调用方不一定经过类型检查，因此运行期同样校验，
    并且挡住 ``tool`` 这类不属于注入消息的角色。
    """
    with pytest.raises(InjectionError, match="不被允许"):
        InjectionItem(source="catalog", content="x", role=role)  # type: ignore[arg-type]


def test_injection_rejects_empty_source_or_content() -> None:
    with pytest.raises(InjectionError, match="来源"):
        InjectionItem(source="", content="x")
    with pytest.raises(InjectionError, match="内容"):
        InjectionItem(source="s", content="")


def test_injection_rejects_summary_without_reference() -> None:
    """有摘要却没有业务回指的引用无法回指，必须在构造时就挡住。"""
    with pytest.raises(InjectionError, match="业务回指"):
        InjectionItem(source="s", content="x", summary="摘要")


@pytest.mark.asyncio
async def test_unavailable_sources_are_explicitly_told_not_silently_dropped() -> None:
    batch = InjectionBatch(
        [InjectionItem(source="retrieved", content="资料")],
        [UnavailableSource(source="profile", reason="TimeoutError")],
    )

    messages = await batch.render(_recorder(FakeCitationIndex()))

    assert len(messages) == 2
    status = messages[-1]
    assert "<unavailable_sources>" in status["content"]
    assert 'name="profile"' in status["content"]
    assert 'reason="TimeoutError"' in status["content"]


@pytest.mark.asyncio
async def test_unavailable_source_attributes_are_escaped() -> None:
    batch = InjectionBatch(
        unavailable=[UnavailableSource(source='a"b', reason="<boom>")],
    )

    messages = await batch.render(_recorder(FakeCitationIndex()))

    assert "&quot;" in messages[0]["content"]
    assert "&lt;boom&gt;" in messages[0]["content"]


@pytest.mark.asyncio
async def test_unavailable_notice_is_a_status_level_item_appended_last() -> None:
    """失败告知是 STATUS 档的一员，并由 ordered() 追加在该档的末尾。

    契约是「它必然出现在业务上下文之后」，因此必需那句在最前、告知在最后。
    """
    batch = InjectionBatch(
        [
            InjectionItem(source="status-source", content="系统状态", priority=InjectionPriority.STATUS),
            InjectionItem(source="retrieved", content="资料"),
        ],
        [UnavailableSource(source="profile", reason="TimeoutError")],
    )

    messages = await batch.render(_recorder(FakeCitationIndex()))

    contents = [message["content"] for message in messages]
    assert contents[0] == "资料"
    assert contents[1] == "系统状态"
    assert "<unavailable_sources>" in contents[-1]


@pytest.mark.asyncio
async def test_partial_render_failure_reports_what_already_reached_the_index() -> None:
    """写到一半失败不得被当作成功：已落索引的引用必须随错误一起交出来。

    否则索引里有记录、窗口里没有消息，``run_finished`` 会报出一条模型从未看到的依据。
    """
    index = FakeCitationIndex()
    recorder = _recorder(index)
    batch = InjectionBatch(
        [
            InjectionItem(source="first", content="第一条", reference="ref-1"),
            InjectionItem(source="second", content="第二条", reference="ref-2"),
        ]
    )

    original_add = index.add

    async def flaky_add(record: CitationRecord) -> None:
        if record.reference == "ref-2":
            raise RuntimeError("索引写入失败")
        await original_add(record)

    index.add = flaky_add  # type: ignore[method-assign]

    with pytest.raises(InjectionRenderError) as error:
        await batch.render(recorder)

    assert [record.reference for record in error.value.recorded] == ["ref-1"]
    assert [message["content"] for message in error.value.rendered] == ["第一条"]
    # 没有「部分成功」的返回值可用，调用方只能按失败处置
    assert "RuntimeError" in str(error.value)


# --- 窗口派生 ---------------------------------------------------------------


def _message(role: str, content: str) -> dict[str, str]:
    """一个形如消息的最小映射（不需要 SDK 类型）。"""
    return {"role": role, "content": content}


def test_no_checkpoint_means_full_history() -> None:
    """不得做滑动窗口：没有摘要检查点时窗口就是全量历史。"""
    history = [_message("user", f"m{index}") for index in range(50)]

    window = derive_window(history)

    assert window == history


def test_window_starts_at_the_last_checkpoint() -> None:
    history = [
        _message("user", "旧 1"),
        _message("assistant", "旧 2"),
        _message("user", "<compacted-summary>检查点</compacted-summary>"),
        _message("user", "新 1"),
        _message("assistant", "新 2"),
    ]

    window = derive_window(history)

    assert window == history[2:]


def test_later_checkpoint_wins() -> None:
    history = [
        _message("user", "m0"),
        _message("user", "<compacted-summary>第一次</compacted-summary>"),
        _message("user", "m2"),
        _message("user", "<compacted-summary>第二次</compacted-summary>"),
        _message("user", "m4"),
    ]

    assert derive_window(history) == history[3:]


def test_leading_system_messages_are_never_shadowed() -> None:
    """系统提示永不被遮蔽（压缩策略第 3 节）：窗口 = 系统提示 + 摘要起的历史。"""
    history = [
        _message("system", "静态系统提示"),
        _message("user", "m1"),
        _message("user", "<compacted-summary>检查点</compacted-summary>"),
        _message("user", "m3"),
    ]

    window = derive_window(history)

    assert window == [history[0], history[2], history[3]]


def test_checkpoint_is_located_by_tag_not_by_position() -> None:
    """读回顺序不是硬保证，因此靠内容标签定位最后一条摘要。

    用例刻意让**真正的检查点不在末位**：若实现改成「取最后一条消息」，它会失败。
    """
    history = [
        _message("user", "m0"),
        _message("user", "<compacted-summary>检查点</compacted-summary>"),
        _message("user", "m2"),
    ]

    assert last_checkpoint_index(history) == 1
    assert derive_window(history) == history[1:]


def test_quoting_the_tag_in_normal_content_is_not_a_checkpoint() -> None:
    """正文提到标签**不得**成为检查点：那会在没有任何摘要的情况下裁掉历史。

    初版用子串包含判定，于是使用者问一句「你上一轮写的 <compacted-summary> 是什么」
    就会触发一次窗口裁剪，被裁掉的内容当次看不到——压缩策略第 8 节第 1 条禁止滑动窗口。
    """
    history = [
        _message("user", "重要历史 A"),
        _message("assistant", "重要历史 B"),
        _message("user", "你上一轮写的 <compacted-summary> 是什么意思？"),
        _message("assistant", "那是我总结历史用的标签"),
    ]

    assert last_checkpoint_index(history) is None
    assert derive_window(history) == history


def test_only_the_exact_envelope_counts_as_a_checkpoint() -> None:
    """只有开闭标签成对框住整条消息才算检查点；近似形态一律不算。

    漏判的方向是安全的（不裁剪，只是压缩没生效），误判的方向会丢历史，因此从严。
    """
    variants = [
        "<COMPACTED-SUMMARY>大写变体</COMPACTED-SUMMARY>",
        "<compacted-summary>缺少闭标签",
        "缺少开标签</compacted-summary>",
        "<compacted-summary >带空格的开标签</compacted-summary >",
        "<compacted-summary/>自闭合",
        "&lt;compacted-summary&gt;被转义的&lt;/compacted-summary&gt;",
    ]

    for variant in variants:
        history = [_message("user", "m0"), _message("user", variant), _message("user", "m2")]
        assert last_checkpoint_index(history) is None, variant


def test_envelope_with_surrounding_whitespace_is_still_a_checkpoint() -> None:
    history = [_message("user", "m0"), _message("user", "\n  <compacted-summary>摘要</compacted-summary>\n")]

    assert last_checkpoint_index(history) == 1


def test_message_text_reads_both_content_shapes() -> None:
    """两种 content 形状都要能取到文本。

    实测：使用者消息是字符串，而 SDK 落库的助手消息是分片数组
    （``[{"type": "output_text", "text": "…"}]``）。只认字符串会让检查点在分片形状上
    永远漏检——方向安全（不裁剪历史），但压缩会静默失效。
    """
    assert message_text({"role": "user", "content": "纯文本"}) == "纯文本"
    assert (
        message_text(
            {
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "第一段"},
                    {"type": "output_text", "text": "第二段"},
                ],
            }
        )
        == "第一段第二段"
    )


def test_checkpoint_detection_works_on_list_shaped_content() -> None:
    history = [
        {"role": "user", "content": "旧"},
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "<compacted-summary>摘要</compacted-summary>"}],
        },
        {"role": "user", "content": "新"},
    ]

    assert last_checkpoint_index(history) == 1
    assert derive_window(history) == history[1:]


def test_message_text_refuses_unknown_shapes_instead_of_guessing() -> None:
    """不认识的部件（如图片）返回 None：不猜、不拼半句。"""
    assert message_text({"role": "user", "content": [{"type": "input_image", "image_url": "x"}]}) is None
    assert message_text({"role": "user", "content": 42}) is None
    assert message_text("不是映射") is None
    assert message_text({"role": "user"}) is None


def test_window_appends_new_items_after_history() -> None:
    history = [_message("user", "m0"), _message("assistant", "m1")]
    injected = [_message("user", "<available_skills/>")]
    user_input = [_message("user", "本轮新输入")]

    window = derive_window(history, appended=[*injected, *user_input])

    assert window == [*history, *injected, *user_input]
    assert window[-1]["content"] == "本轮新输入"


def test_empty_history_and_empty_appended() -> None:
    assert derive_window([]) == []
    assert derive_window([], appended=[_message("user", "x")]) == [_message("user", "x")]


def test_derive_window_does_not_mutate_inputs() -> None:
    history = [_message("user", "m0"), _message("user", "<compacted-summary>s</compacted-summary>")]
    appended = [_message("user", "new")]

    window = derive_window(history, appended=appended)
    window.append(_message("user", "改动返回值"))

    assert len(history) == 2
    assert appended == [_message("user", "new")]


def test_window_works_with_non_mapping_items() -> None:
    """历史里可能有 SDK 的项类型；无法取字段的项按「不是检查点」处理，不炸。"""

    class Opaque:
        pass

    history = [Opaque(), _message("user", "m1")]

    assert derive_window(history) == history


def test_repeated_derivation_is_stable() -> None:
    history = [
        _message("user", "m0"),
        _message("user", "<compacted-summary>s</compacted-summary>"),
        _message("user", "m2"),
    ]

    assert derive_window(history) == derive_window(history)
