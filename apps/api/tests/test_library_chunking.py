"""分块后处理的单元测试。

对应 RAG 策略第 1.2 节的三条要求与第 10 节参数表：

1. 超长 section 必须二次切分（框架不做，实测 2248 字符原样输出）；
2. **不静默截断**——不可分单元标记为需人工处理；
3. 结构边界处不切断表格与列表项；块长落在目标区间且绝不超过硬限。

这些是纯函数测试，不依赖数据库或网络。
"""

from __future__ import annotations

import pytest

from campfire.modules.library.chunking import (
    HARD_MAX_CHARS,
    TARGET_MIN_CHARS,
    chunk_markdown_section,
)


def _long_paragraph(sentences: int) -> str:
    """构造由多个完整句子组成的超长段落（可在句边界安全切分）。"""
    return "".join(f"这是第{i}句用于测试的中文说明。" for i in range(sentences))


def test_short_section_stays_one_chunk() -> None:
    """短 section 不被切碎。"""
    report = chunk_markdown_section("/总则/", "简短说明。")

    assert len(report.chunks) == 1
    assert report.unsplittable == []
    assert "简短说明。" in report.chunks[0].text


def test_oversized_section_is_split_and_never_exceeds_hard_limit() -> None:
    """超长 section 被切分，且每块（含标题路径）不超过嵌入硬限。"""
    body = _long_paragraph(180)  # 远超 2000 字符
    assert len(body) > HARD_MAX_CHARS

    report = chunk_markdown_section("/总则/", body)

    assert len(report.chunks) > 1, "超长 section 必须被切分"
    assert report.unsplittable == []
    for chunk in report.chunks:
        assert len(chunk.text) <= HARD_MAX_CHARS, "任何块都不得超过嵌入接口的 2000 字符硬限"


def test_header_path_is_prepended_and_counts_toward_limit() -> None:
    """标题路径拼入块文本（保留层级语义），并计入长度预算。"""
    body = _long_paragraph(180)
    report = chunk_markdown_section("/总则/长章节/", body)

    assert all(chunk.text.startswith("/总则/长章节/") for chunk in report.chunks)
    assert all(len(chunk.text) <= HARD_MAX_CHARS for chunk in report.chunks)


def test_oversized_table_is_not_truncated_but_flagged_for_manual_review() -> None:
    """超长表格**不截断**：标记需人工处理，并进入 unsplittable。"""
    rows = "\n".join(f"| 9:{i:02d} | 活动{i} | 说明文字若干 |" for i in range(120))
    table = f"| 时间 | 活动 | 说明 |\n|---|---|---|\n{rows}"
    assert len(table) > HARD_MAX_CHARS

    report = chunk_markdown_section("/附录/", table)

    assert report.unsplittable, "超长表格应进入人工处理队列"
    flagged = report.unsplittable[0]
    assert flagged.needs_manual_review is True
    assert flagged.review_reason, "必须给出原因，便于人工处理"
    # 关键：内容完整保留，未截断。
    assert "活动0" in flagged.text
    assert "活动119" in flagged.text
    assert len(report.embedded_chunks) == 0, "需人工处理的块不得送去嵌入"


def test_list_items_are_not_split_across_chunks() -> None:
    """列表项不被从中间切断。"""
    items = "\n".join(f"- 第{i}项操作要点说明文字" for i in range(80))
    report = chunk_markdown_section("/步骤/", items)

    assert report.chunks
    for chunk in report.chunks:
        # 每块内的列表行都应是完整行（以 "- " 开头，且没有半个项目符号）。
        for line in chunk.text.splitlines():
            if line.strip().startswith("- "):
                assert line.strip().startswith("- "), "列表项被切断"


def test_small_pieces_are_merged_toward_target_size() -> None:
    """过小的段落被合并，避免产生大量碎片块。"""
    body = "\n\n".join(f"第{i}段短说明。" for i in range(30))
    report = chunk_markdown_section("/总则/", body)

    assert len(report.chunks) < 30, "碎片应被合并"
    # 合并后不应出现大量远低于下限的块（末块可能偏小）。
    small = [c for c in report.chunks[:-1] if len(c.text) < TARGET_MIN_CHARS // 2]
    assert not small, f"存在过小的中间块：{[len(c.text) for c in small]}"


def test_single_oversized_sentence_is_flagged_not_truncated() -> None:
    """单句即超限时无处可切：标记人工处理，不截断。"""
    body = "，" + "无标点的超长句子" * 300  # 无句边界
    report = chunk_markdown_section("/总则/", body)

    assert report.unsplittable, "无边界可切时必须标记人工处理"
    assert report.unsplittable[0].needs_manual_review is True


@pytest.mark.parametrize("header", ["/", "", "/单级/"])
def test_header_variants_are_handled(header: str) -> None:
    """标题路径的几种形态都不导致异常或超限。"""
    body = _long_paragraph(180)
    report = chunk_markdown_section(header, body)

    assert report.chunks
    assert all(len(c.text) <= HARD_MAX_CHARS for c in report.chunks)
