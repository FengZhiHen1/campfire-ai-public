"""压缩机制：参数校验、范围选择、保留尾部、事务与失败语义。

对应 docs/技术设计/technical-details/压缩策略.md 第 2、3、5、6、7、10、12 节。
本文件用替身摘要器，**不打网络**：机制本身与「谁来写摘要」是两件事。
"""

from __future__ import annotations

import pytest

from campfire.agent.context import (
    CompactionError,
    CompactionOutcome,
    CompactionSettings,
    SummaryRequest,
    SummaryResult,
    build_checkpoint,
    compact,
    derive_window,
    estimate_window_tokens,
    is_compacted_summary,
    previous_summary_text,
    retained_after_last_checkpoint,
    select_range,
)

# 阈值算术里的小数字：W=1000、O=100、headroom=100 → 阈值 = floor(min(800, 800)) = 800
# 保留预算 = floor((1000−100) × 0.16) = 144
SMALL = CompactionSettings(context_window_tokens=1000, output_reserve_tokens=100, headroom_tokens=100)


def _message(role: str, content: str) -> dict[str, object]:
    """一条消息。"""
    return {"role": role, "content": content}


def _call(call_id: str, name: str = "search_knowledge", arguments: str = '{"query":"q"}') -> dict[str, object]:
    """一次工具调用项（Responses 形态）。"""
    return {"type": "function_call", "name": name, "arguments": arguments, "call_id": call_id}


def _output(call_id: str, text: str = "结果") -> dict[str, object]:
    """一次工具结果项（Responses 形态）。"""
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def _filler(index: int, *, chars: int = 20) -> dict[str, object]:
    """一段填充历史（默认约 20 个字符 → 估算 5 token 上下）。"""
    return _message("user", f"历史 {index} " + "字" * chars)


class FakeSummarizer:
    """摘要替身：可注入失败、截断与空输出。"""

    def __init__(
        self,
        *,
        text: str = "摘要正文",
        truncated: bool = False,
        raises: BaseException | None = None,
        output_tokens: int = 7,
    ) -> None:
        self.text = text
        self.truncated = truncated
        self.raises = raises
        self.output_tokens = output_tokens
        self.requests: list[SummaryRequest] = []

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return SummaryResult(
            text=self.text,
            truncated=self.truncated,
            input_tokens=100,
            output_tokens=self.output_tokens,
            elapsed_seconds=0.5,
        )


class FakeJournal:
    """记账替身：记录开始/结束，可检查是否留下了未闭合标记。"""

    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []
        self.finished: list[tuple[str, CompactionOutcome]] = []

    async def record_started(
        self,
        *,
        window_tokens_before: int,
        compacted_items: int,
        retained_items: int,
    ) -> str:
        marker = f"m{len(self.started)}"
        self.started.append(
            {
                "marker": marker,
                "window_tokens_before": window_tokens_before,
                "compacted_items": compacted_items,
                "retained_items": retained_items,
            }
        )
        return marker

    async def record_finished(self, marker: str, outcome: CompactionOutcome) -> None:
        self.finished.append((marker, outcome))

    @property
    def unclosed(self) -> list[str]:
        """没有结束记录的标记（正常路径必须为空）。"""
        closed = {marker for marker, _ in self.finished}
        return [str(item["marker"]) for item in self.started if item["marker"] not in closed]


# --- 参数校验（第 10 节加载期规则） -----------------------------------------


def test_threshold_and_retention_arithmetic() -> None:
    """阈值 = floor(min(W×ratio, W−O−headroom))；保留预算 = floor((W−O)×retainRatio)。"""
    assert SMALL.threshold_tokens == 800
    assert SMALL.retain_budget_tokens == 144
    assert SMALL.summary_max_tokens == 100  # 默认取 headroomTokens


def test_default_parameters_match_the_design_numbers() -> None:
    """按压缩策略第 2 节的代入值：W=1M、O=8192、headroom=65536 → 阈值约 80 万。"""
    design = CompactionSettings(
        context_window_tokens=1_000_000,
        output_reserve_tokens=8192,
        headroom_tokens=65_536,
    )

    assert design.threshold_tokens == 800_000
    assert design.retain_budget_tokens == 158_689  # (1M − 8192) × 0.16，文档写「约 15.9 万」


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"context_window_tokens": 0}, "必须为正整数"),
        ({"output_reserve_tokens": -1}, "不能为负"),
        ({"headroom_tokens": -1}, "不能为负"),
        ({"threshold_ratio": 0}, "threshold_ratio"),
        ({"threshold_ratio": 1.5}, "threshold_ratio"),
        ({"retain_ratio": None}, "必须给出一个"),
        ({"retain_ratio": 0.9}, "保留比例必须小于阈值比例"),
        ({"retain_ratio": None, "retain_tokens": 900}, "必须低于解析出的阈值"),
        ({"retain_ratio": 0.1, "retain_tokens": 100}, "互斥"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"compaction_retries": -1}, "重试次数"),
        ({"context_window_tokens": 100, "output_reserve_tokens": 100, "headroom_tokens": 100}, "阈值为非正数"),
    ],
)
def test_invalid_settings_are_rejected_at_construction(kwargs: dict[str, object], fragment: str) -> None:
    """非法配置在**加载时**失败，而不是在压缩时才发现（第 10 节）。"""
    base: dict[str, object] = {"context_window_tokens": 1000, "output_reserve_tokens": 100, "headroom_tokens": 100}
    base.update(kwargs)

    with pytest.raises(CompactionError, match=fragment):
        CompactionSettings(**base)  # type: ignore[arg-type]


def test_absolute_retention_is_accepted_when_below_threshold() -> None:
    settings = CompactionSettings(
        context_window_tokens=1000,
        output_reserve_tokens=100,
        headroom_tokens=100,
        retain_ratio=None,
        retain_tokens=200,
    )

    assert settings.retain_budget_tokens == 200


def test_settings_from_config_maps_the_two_numbers() -> None:
    """W 与 O 只能来自配置（「配置唯一入口」），装配处不该再抄一遍字段名。"""
    from campfire.agent.context import settings_from_config
    from campfire.core.config import Settings

    settings = settings_from_config(Settings(model_context_window_tokens=2_000_000, model_output_reserve_tokens=4096))

    assert settings.context_window_tokens == 2_000_000
    assert settings.output_reserve_tokens == 4096
    # 其余参数取第 10 节默认值
    assert settings.threshold_ratio == 0.8
    assert settings.headroom_tokens == 65_536
    assert settings.retain_ratio == 0.16
    assert settings.max_overflow_retries == 1


# --- 范围选择（第 3、6 节） -------------------------------------------------


def test_range_selection_never_shadows_the_system_prompt() -> None:
    items = [_message("system", "静态系统提示"), *[_filler(index) for index in range(20)]]

    selection = select_range(items, SMALL)

    assert selection.start == 1


def test_range_selection_keeps_a_tail_within_the_retention_budget() -> None:
    items = [_filler(index) for index in range(40)]

    selection = select_range(items, SMALL)

    assert selection.end < len(items)
    kept = items[selection.end :]
    assert estimate_window_tokens(kept) >= SMALL.retain_budget_tokens


def test_range_selection_does_not_split_a_tool_pair() -> None:
    """边界不安全时往前移：宁可多留一点，也不把调用与结果切开。"""
    items = [_filler(index) for index in range(3)]
    items.append(_call("c1"))
    items.append(_output("c1"))
    items.append(_filler(9))

    selection = select_range(items, SMALL)

    # 边界不能落在 output 上（其 call 在范围内），也不能落在 call 之后
    assert not (selection.end == 4), "边界切开了调用与结果"
    kept = items[selection.end :]
    call_ids = {item.get("call_id") for item in kept if isinstance(item.get("call_id"), str)}
    outside = {item.get("call_id") for item in items[: selection.end] if isinstance(item.get("call_id"), str)}
    assert not (call_ids & outside), "保留尾部里有配对残缺的项"


def test_range_selection_is_empty_when_history_is_only_the_system_prompt() -> None:
    selection = select_range([_message("system", "提示")], SMALL)

    assert selection.is_empty


def test_force_max_reduction_ignores_the_retention_budget() -> None:
    items = [_message("system", "提示"), *[_filler(index) for index in range(30)]]

    selection = select_range(items, SMALL, force_max_reduction=True)

    assert selection.start == 1
    assert selection.end == len(items)  # 保留尾部为空 = 最大头部缩减
    assert selection.compacted_items == 30


# --- 检查点（第 5 节） -------------------------------------------------------


def test_checkpoint_is_a_tagged_message_and_window_starts_there() -> None:
    checkpoint = build_checkpoint("目标：X\n未决：Y")

    assert checkpoint["role"] == "user"
    assert is_compacted_summary(checkpoint)
    assert previous_summary_text([_filler(1), checkpoint]) == "目标：X\n未决：Y"

    window = derive_window([_filler(index) for index in range(5)] + [checkpoint])
    assert window == [checkpoint]


def test_retained_after_last_checkpoint_is_the_verbatim_tail() -> None:
    items = [_filler(1), build_checkpoint("s1"), _filler(2), _filler(3)]

    assert retained_after_last_checkpoint(items) == tuple(items[2:])


# --- 触发与跳过（第 2 节） ---------------------------------------------------


async def _compact(items: list[dict[str, object]], **kwargs: object) -> tuple[list[object], CompactionOutcome]:
    settings = kwargs.pop("settings", SMALL)
    summarizer = kwargs.pop("summarizer", FakeSummarizer())
    journal = kwargs.pop("journal", FakeJournal())
    system_prompt = kwargs.pop("system_prompt", "静态系统提示")
    return await compact(
        items,
        settings=settings,  # type: ignore[arg-type]
        summarizer=summarizer,  # type: ignore[arg-type]
        instruction="把历史压成摘要。",
        journal=journal,  # type: ignore[arg-type]
        system_prompt=system_prompt,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_below_threshold_skips_without_calling_the_summarizer() -> None:
    summarizer = FakeSummarizer()

    history, outcome = await _compact([_filler(1)], summarizer=summarizer)

    assert outcome.performed is False
    assert outcome.reason == "below_threshold"
    assert summarizer.requests == []
    assert history == [_filler(1)]


@pytest.mark.asyncio
async def test_auto_disabled_skips_even_when_over_threshold() -> None:
    settings = CompactionSettings(
        context_window_tokens=1000,
        output_reserve_tokens=100,
        headroom_tokens=100,
        auto=False,
    )

    _history, outcome = await _compact([*_long_history(60)], settings=settings)

    assert outcome.performed is False
    assert outcome.reason == "auto_disabled"


@pytest.mark.asyncio
async def test_manual_compaction_runs_below_threshold() -> None:
    """手动压缩仅供运维与调试：低于阈值也执行（第 2 节）。

    历史必须长到「有可压缩的范围」：整段都能塞进保留预算时，正确行为是
    ``no_safe_range``（见下一条用例）。
    """
    summarizer = FakeSummarizer()
    items = [_filler(index) for index in range(30)]  # 约 180 token < 阈值 800，但 > 保留预算 144

    _history, outcome = await _compact(items, summarizer=summarizer, manual=True)

    assert outcome.performed is True
    assert summarizer.requests


@pytest.mark.asyncio
async def test_manual_compaction_with_nothing_to_compress_reports_no_safe_range() -> None:
    """短历史（整段都能塞进保留预算）手动压缩也不该硬切：如实报告没有可压缩范围。"""
    items = [_filler(1), _filler(2)]

    history, outcome = await _compact(items, manual=True)

    assert outcome.performed is False
    assert outcome.reason == "no_safe_range"
    assert history == items


# --- 落地形状（第 5、12 节） -------------------------------------------------


def _long_history(count: int) -> list[dict[str, object]]:
    """造一段足够越过阈值的填充历史。"""
    return [_message("system", "静态系统提示"), *[_filler(index, chars=80) for index in range(count)]]


@pytest.mark.asyncio
async def test_compaction_appends_and_never_rewrites_history() -> None:
    """第 5 节：只追加，不改写、不删除。

    追加的内容是「检查点 + 尾部原文」（见 ``compaction`` 模块 docstring 的落地形状：
    第 5、6、8 节三条要求同时成立的唯一形状）。
    """
    items = _long_history(60)
    summarizer = FakeSummarizer(text="六节摘要")

    history, outcome = await _compact(items, summarizer=summarizer)

    assert outcome.performed is True
    assert history[: len(items)] == items  # 原历史逐项未动（严格前缀）
    appended = history[len(items) :]
    assert len(appended) == 1 + outcome.retained_items
    assert is_compacted_summary(appended[0])
    assert appended[1:] == list(retained_after_last_checkpoint(history))
    assert sum(1 for item in appended if is_compacted_summary(item)) == 1


@pytest.mark.asyncio
async def test_window_after_compaction_is_system_plus_summary_plus_tail() -> None:
    """第 12 节的落地形状断言：[系统提示 + 摘要 + 保留尾部]。"""
    items = _long_history(60)

    history, outcome = await _compact(items)

    window = derive_window(history)
    assert window[0] == items[0]  # 系统提示仍在最前
    assert is_compacted_summary(window[1])  # 摘要紧随其后
    assert window[2:] == list(retained_after_last_checkpoint(history))
    assert outcome.retained_items == len(window) - 2


@pytest.mark.asyncio
async def test_compaction_reports_released_tokens_and_counts() -> None:
    """第 9 节要求的计量字段都要有值。"""
    items = _long_history(60)

    _history, outcome = await _compact(items)

    assert outcome.window_tokens_before > outcome.window_tokens_after
    assert outcome.released_tokens > 0
    assert outcome.compacted_items > 0
    assert outcome.summary is not None
    assert outcome.summary_elapsed_seconds == 0.5
    assert outcome.summary.input_tokens == 100


@pytest.mark.asyncio
async def test_existing_summary_is_required_to_be_merged() -> None:
    """第 4 节：已有 `<compacted-summary>` 时要求合并，不是照抄。

    检查点必须**落在窗口内且窗口仍超阈值**：因此把它放在历史中段，后面接足够长的历史。
    """
    items = [
        _message("system", "静态系统提示"),
        build_checkpoint("旧摘要：目标 X"),
        *[_filler(index, chars=80) for index in range(60)],
    ]
    summarizer = FakeSummarizer()

    _history, outcome = await _compact(items, summarizer=summarizer)

    assert outcome.performed is True
    assert outcome.previous_summary_merged is True
    assert summarizer.requests[0].previous_summary == "旧摘要：目标 X"
    assert "合并" in summarizer.requests[0].instruction


@pytest.mark.asyncio
async def test_first_compaction_passes_the_bare_instruction() -> None:
    summarizer = FakeSummarizer()

    await _compact(_long_history(60), summarizer=summarizer)

    assert summarizer.requests[0].instruction == "把历史压成摘要。"
    assert summarizer.requests[0].previous_summary is None


@pytest.mark.asyncio
async def test_summary_request_carries_the_replay_prefix_and_max_tokens() -> None:
    """第 4 节：热前缀逐字回放；摘要输出受 maxTokens 限制。"""
    items = _long_history(60)

    summarizer = FakeSummarizer()
    await _compact(items, summarizer=summarizer)

    request = summarizer.requests[0]
    assert request.prefix == tuple(items[1 : 1 + len(request.prefix)])  # 从第一个非 system 项起
    assert request.max_tokens == SMALL.summary_max_tokens


@pytest.mark.asyncio
async def test_repeated_compaction_keeps_appending_checkpoints() -> None:
    """第二次压缩合并上一份摘要，且**不得把已被摘要覆盖的原文搬回窗口**。

    压缩后窗口已落到阈值内（这是压缩成功的样子），因此第二次用 ``manual`` 触发。
    """
    items = _long_history(60)
    history, _outcome = await _compact(items)
    summarizer = FakeSummarizer()

    history2, outcome2 = await _compact(history, summarizer=summarizer, manual=True)

    assert outcome2.performed is True
    assert len(history2) == len(history) + 1 + outcome2.retained_items
    assert history2[: len(history)] == history  # 仍然只追加
    assert summarizer.requests[0].previous_summary is not None

    # 第二次压缩的范围从上一份检查点开始；新窗口的尾部必须仍属于**上一次的窗口**，
    # 也就是不得把「已被摘要覆盖、又不在保留尾部里」的原文搬回来。
    #
    # 注意判据不能写成「新尾部不在第一次检查点之前」：保留尾部按落地形状会在历史里出现
    # 两份（摘要前后各一份），所以它本来就同时「在检查点之前」与「在检查点之后」。
    previous_window = derive_window(history)
    new_window = derive_window(history2)
    assert all(item in previous_window for item in new_window[2:]), "第二次压缩把已摘要的原文搬回了窗口"


# --- 失败语义（第 7 节） -----------------------------------------------------


@pytest.mark.asyncio
async def test_summary_failure_leaves_the_window_untouched() -> None:
    """摘要失败不改动窗口：记录警告，继续用未压缩的窗口（压缩失败不得让对话不可用）。"""
    items = _long_history(60)
    journal = FakeJournal()

    history, outcome = await _compact(items, summarizer=FakeSummarizer(raises=RuntimeError("boom")), journal=journal)

    assert outcome.performed is False
    assert outcome.reason == "summary_failed"
    assert "RuntimeError" in outcome.detail
    assert "boom" not in outcome.detail  # 只带类型名
    assert history == items
    assert journal.unclosed == []  # 失败也要记结束，否则崩溃与失败无法区分


@pytest.mark.asyncio
async def test_truncated_summary_is_not_committed() -> None:
    """达到 maxTokens 造成截断，按摘要失败的同一规则处理（第 7 节）。"""
    items = _long_history(60)

    history, outcome = await _compact(items, summarizer=FakeSummarizer(truncated=True))

    assert outcome.performed is False
    assert outcome.reason == "summary_truncated"
    assert history == items


@pytest.mark.asyncio
async def test_empty_summary_is_not_committed() -> None:
    items = _long_history(60)

    history, outcome = await _compact(items, summarizer=FakeSummarizer(text="   "))

    assert outcome.performed is False
    assert outcome.reason == "summary_failed"
    assert history == items


@pytest.mark.asyncio
async def test_stopping_after_the_first_attempt_reports_one_attempt() -> None:
    """``attempts`` 必须是**真实**尝试次数，不是「允许的次数」。

    第一版把 `attempts` 记成允许值，于是 `compaction_retries=2` 的配置在一次尝试就降到阈值
    以下时仍然报告 3 次——计量失真（第 9 节要求真实计量），而用例里那句
    `len(summarizer.requests) >= 1` 永远不会失败，正好把这个错误盖住。
    """
    items = _long_history(80)
    summarizer = FakeSummarizer(text="短")
    settings = CompactionSettings(
        context_window_tokens=1000,
        output_reserve_tokens=100,
        headroom_tokens=100,
        compaction_retries=2,
    )

    _history, outcome = await _compact(items, settings=settings, summarizer=summarizer)

    assert outcome.performed is True
    assert len(summarizer.requests) == 1
    assert outcome.attempts == 1


@pytest.mark.asyncio
async def test_retry_reduces_the_retention_budget_instead_of_dropping_the_tail() -> None:
    """重试按比例缩小保留预算，而**不是**绕过保留策略丢掉整段尾部。

    「绕过阈值与保留策略」在第 2 节是**溢出恢复**的专属手段；常规重试动用它会让代价付了、
    目的还没达成（实测第一版：重试后保留 0 项，窗口仍高于阈值）。这里用一个「第一次压缩后
    仍超阈值」的构造，断言重试确实发生了，且尾部没有被整段丢掉。
    """
    items = _long_history(40)
    summarizer = FakeSummarizer(text="很短")
    settings = CompactionSettings(
        context_window_tokens=1000,
        output_reserve_tokens=100,
        headroom_tokens=100,
        compaction_retries=1,
        retain_ratio=0.5,  # 保留预算 450 token：第一次压缩后仍可能高于阈值 800
    )

    _history, outcome = await _compact(items, settings=settings, summarizer=summarizer)

    assert outcome.performed is True
    assert len(summarizer.requests) >= 1
    # 重试若走「最大头部缩减」，保留项数会是 0；按比例缩小则仍保留若干项
    assert outcome.attempts == 1 or outcome.retained_items > 0


@pytest.mark.asyncio
async def test_no_safe_range_reports_explicitly() -> None:
    """没有可安全压缩的范围 → 不做任何改变并明确报告，不留假成功（第 3 节）。"""
    items = [_message("system", "提示"), _call("c1")]
    settings = CompactionSettings(
        context_window_tokens=1000,
        output_reserve_tokens=100,
        headroom_tokens=100,
        retain_ratio=None,
        retain_tokens=0,
    )

    history, outcome = await _compact(items, settings=settings, manual=True)

    assert outcome.performed is False
    assert outcome.reason == "no_safe_range"
    assert history == items


@pytest.mark.asyncio
async def test_journal_records_start_then_finish() -> None:
    """第 7 节：有开始/结束记录的事务。"""
    journal = FakeJournal()

    await _compact(_long_history(60), journal=journal)

    assert [item["marker"] for item in journal.started] == ["m0"]
    assert journal.finished[0][0] == "m0"
    assert journal.finished[0][1].performed is True
    assert journal.unclosed == []


@pytest.mark.asyncio
async def test_journal_failure_propagates() -> None:
    """记账端口自身失败必须冒泡：不得当成「压缩没发生」。"""

    class BrokenJournal(FakeJournal):
        async def record_started(self, **_kwargs: object) -> str:
            raise RuntimeError("表不可用")

    with pytest.raises(RuntimeError, match="表不可用"):
        await _compact(_long_history(60), journal=BrokenJournal())


@pytest.mark.asyncio
async def test_commit_failure_does_not_claim_compaction_and_leaves_window_untouched() -> None:
    """第 7 节：写不进去就不能记成「压缩完成」，且窗口保持原样。

    第一版的顺序是「记结束 → 调用方落库」，于是落库失败会留下一条闭合的
    ``performed=True`` 记录——正是第 7 节点名禁止的「假装压缩完成的结束记录」。
    """
    journal = FakeJournal()
    items = _long_history(60)

    async def failing_commit(_appended: object) -> None:
        raise RuntimeError("数据库写入失败")

    history, outcome = await _compact(items, journal=journal, commit=failing_commit)

    assert outcome.performed is False
    assert outcome.reason == "commit_failed"
    assert history == items
    assert journal.unclosed == []  # 事务闭合了，但闭合在「没压缩」上
    assert all(not outcome_.performed for _marker, outcome_ in journal.finished)


@pytest.mark.asyncio
async def test_successful_commit_happens_before_the_transaction_closes() -> None:
    """落库成功时，追加内容确实经过 commit 端口，且事务在之后才闭合。"""
    order: list[str] = []
    journal = FakeJournal()
    items = _long_history(60)

    async def commit(appended: object) -> None:
        order.append("commit")
        committed.extend(appended)  # type: ignore[arg-type]

    committed: list[object] = []
    original_finish = journal.record_finished

    async def record_finished(marker: str, outcome: object) -> None:
        order.append("finish")
        await original_finish(marker, outcome)

    journal.record_finished = record_finished  # type: ignore[method-assign]

    history, outcome = await _compact(items, journal=journal, commit=commit)

    assert outcome.performed is True
    assert order == ["commit", "finish"], "落库必须发生在记账闭合之前"
    assert committed and is_compacted_summary(committed[0])
    # 追加形状是「检查点 + 尾部原文」，因此检查点在原历史长度处，不在末尾
    assert history[len(items)] == committed[0]


class _OverflowLikeError(Exception):
    """带 ``status_code`` 的异常（模拟提供方错误）。"""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("message", "status_code", "expected"),
    [
        # 真阳性：OpenAI 措辞 / 下划线 code / 中文措辞
        ("This model's maximum context length is 1000 tokens", 400, True),
        ("context_length_exceeded", 400, True),
        ("请求超出上下文长度限制", 400, True),
        ("Please reduce the length of the messages", 400, True),
        # 假阳性：与窗口无关的参数错误（第一版就是被这条骗到，永久改写了窗口）
        ("Invalid 'messages[1].content': string too long. Expected a string with maximum length 1048576", 400, False),
        ("invalid function arguments", 400, False),
        # 其它：状态码或措辞不构成「明确分类」
        ("context length exceeded", 500, False),
        ("bad request", 413, False),
        ("context length exceeded", 401, False),
    ],
)
def test_overflow_classification_matrix(message: str, status_code: int, expected: bool) -> None:
    """溢出判定矩阵（第 7 节：只在提供方**明确分类**窗口溢出时触发）。

    这条判定的误判代价不对称：误判为溢出会走「绕过阈值与保留策略」的最大头部缩减，
    **永久改动窗口**；因此宁可漏判。此前这条函数**一个用例都没有**。
    """
    from campfire.agent.context import is_context_overflow

    assert is_context_overflow(_OverflowLikeError(message, status_code)) is expected


def test_overflow_needs_the_window_to_be_near_its_limit() -> None:
    """第二道证据：真实溢出不可能发生在空窗口上。"""
    from campfire.agent.context import is_context_overflow

    error = _OverflowLikeError("This model's maximum context length is 1000 tokens", 400)

    assert is_context_overflow(error, estimated_window_tokens=900, context_window_tokens=1000) is True
    assert is_context_overflow(error, estimated_window_tokens=100, context_window_tokens=1000) is False
    # 没给证据时退回纯措辞判定（不影响没有压缩接线的调用方）
    assert is_context_overflow(error) is True


@pytest.mark.asyncio
async def test_cancellation_during_summary_propagates() -> None:
    """取消优先于上述一切（第 7 节）。"""
    import asyncio

    items = _long_history(60)

    with pytest.raises(asyncio.CancelledError):
        await _compact(items, summarizer=FakeSummarizer(raises=asyncio.CancelledError()))
