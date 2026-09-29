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
from campfire.modules.library.ingestion import parse_frontmatter


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


def test_oversized_table_is_split_not_truncated() -> None:
    """超长表格按行切分，**内容一行不少**（不截断是硬要求）。

    本用例原先断言"超长表格进人工队列"。2026-09-29 改为按行切分（依据见
    `test_oversized_table_splits_by_rows_and_repeats_header`），因此断言随之
    更新——但**"不截断"这条不变量不变**：切分只改变分块边界，不丢行。
    """
    rows = "\n".join(f"| 9:{i:02d} | 活动{i} | 说明文字若干 |" for i in range(120))
    table = f"| 时间 | 活动 | 说明 |\n|---|---|---|\n{rows}"
    assert len(table) > HARD_MAX_CHARS

    report = chunk_markdown_section("/附录/", table)

    assert len(report.chunks) > 1, "超长表格应被切分"
    assert report.unsplittable == [], "按行切分后不应再有不可分单元"
    joined = "\n".join(c.text for c in report.chunks)
    # 关键：内容完整保留，未截断。
    assert "活动0" in joined
    assert "活动119" in joined
    for i in range(120):
        assert f"活动{i} " in joined, f"第 {i} 行丢失"
    assert all(len(c.text) <= HARD_MAX_CHARS for c in report.chunks)


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


# ---------------------------------------------------------------- 章节路径


def test_locator_includes_current_section_title() -> None:
    """`locator` 必须含当前章节标题——框架的 header_path 只有父级路径。

    实测依据：`## 一、服务对象` 节点的 header_path 只有 `/规范/`，直接拿它当
    locator 会让同章下所有块指向同一位置，引用回指（`AC-05`）失准。
    """
    report = chunk_markdown_section("/规范/", "## 一、服务对象\n\n辖区内的儿童。")

    assert report.chunks[0].locator == "/规范/一、服务对象/"
    # header_path 原样保留框架语义，不被改写。
    assert report.chunks[0].header_path == "/规范/"


def test_locator_nests_under_appendix() -> None:
    """附件下的子章节嵌套正确（附件内部小节不与规范正文各章混同）。"""
    report = chunk_markdown_section("/规范/附件2/", "### 一、基本要求\n\n填写说明。")

    assert report.chunks[0].locator == "/规范/附件2/一、基本要求/"


def test_locator_keeps_section_title_across_split_pieces() -> None:
    """超长 section 切成多块时，**每一块**都保留章节标题，而不是只有首块。

    切分后标题行只在首块里，因此章节名必须在切分前取好并传入——否则后续块的
    locator 会退化成父级路径，多块指向同一位置。
    """
    body = "## 三、服务内容\n\n" + _long_paragraph(400) + "\n\n" + _long_paragraph(400)
    report = chunk_markdown_section("/规范/", body)

    assert len(report.chunks) > 1, "本用例需要产生多块"
    assert all(c.locator == "/规范/三、服务内容/" for c in report.chunks)


def test_locator_falls_back_to_parent_without_heading() -> None:
    """块文本没有标题行时退回父级路径（不编造章节名）。"""
    report = chunk_markdown_section("/规范/", "没有标题的正文。")

    assert report.chunks[0].locator == "/规范/"


def test_locator_handles_root_header() -> None:
    """根路径（`/`）下的块不产生空 locator。"""
    report = chunk_markdown_section("/", "## 一、服务对象\n\n正文。")

    assert report.chunks[0].locator == "/一、服务对象/"


# ---------------------------------------------------------------- 超长表格


def test_oversized_table_splits_by_rows_and_repeats_header() -> None:
    """超长表格**按行切分、每片重复表头**——不整块判为"不可分"。

    已修缺陷的回归（2026-09-29）：早先一律判"以表格为主，切断会破坏结构"，
    导致 PMC 论文的 27 种循证实践清单（Table 2，8,487 字符）**不进检索**——
    而"有哪些循证实践"正是最可能的提问。结构保护的本意是不切断**行内**，
    按行分段并重复表头产出的每片仍是合法且自解释的表格。
    """
    rows = [
        f"| 实践{i} | 这是第{i}种循证实践的定义说明文字，需要足够长以避免碎片并撑过硬上限 |"
        for i in range(60)
    ]
    table = "\n".join(["| 实践 | 定义 |", "|---|---|", *rows])
    assert len(table) > HARD_MAX_CHARS, "本用例需要超长表格"

    report = chunk_markdown_section("/规范/", table)

    assert report.unsplittable == [], "表格不应被判为不可分"
    assert len(report.chunks) > 1, "超长表格应被切成多片"
    for chunk in report.chunks:
        # 每片都要有自己的表头与分隔行——否则列义丢失。
        assert "| 实践 | 定义 |" in chunk.text
        assert "|---|---|" in chunk.text
        assert len(chunk.text) <= HARD_MAX_CHARS


def test_table_without_recognizable_header_still_goes_to_manual() -> None:
    """表头识别不出时仍交人工——宁可漏嵌也不产出列义不明的碎片。"""
    # 没有 `|---|` 分隔行，不是标准 Markdown 表格。
    rows = [f"| 实践{i} | 这是第{i}种实践的定义文字，需要足够长以撑过硬上限 |" for i in range(120)]
    body = "\n".join(rows)
    assert len(body) > HARD_MAX_CHARS

    report = chunk_markdown_section("/规范/", body)

    assert report.unsplittable, "无表头的结构块应进人工队列"
    assert "无法按行切分" in (report.unsplittable[0].review_reason or "")


def test_oversized_list_is_not_silently_dropped() -> None:
    """超长列表不是表格：走表格分支会安全退回——但绝不静默丢弃。"""
    items = [f"- 第{i}项：这是一条足够长的列表项内容用于测试超长处理" for i in range(80)]
    body = "\n".join(items)
    assert len(body) > HARD_MAX_CHARS

    report = chunk_markdown_section("/规范/", body)

    assert report.chunks
    assert report.unsplittable or len(report.chunks) > 1


# ---------------------------------------------------------------- frontmatter


def test_frontmatter_is_split_from_body() -> None:
    """frontmatter 被解析为元数据，**不进入正文**（进正文会污染检索内容）。"""
    text = "---\ntitle: 测试标题\nsource: WHO 2024\napplicable_scope: 学龄前儿童\n---\n\n# 正文标题\n\n正文内容。\n"

    metadata, body = parse_frontmatter(text)

    assert metadata["title"] == "测试标题"
    assert metadata["source"] == "WHO 2024"
    assert metadata["applicable_scope"] == "学龄前儿童"
    assert "---" not in body
    assert "source:" not in body, "元数据不得留在正文里"
    assert body.startswith("# 正文标题")


def test_no_frontmatter_returns_original_text() -> None:
    """没有 frontmatter 时原样返回，不误截断。"""
    text = "# 标题\n\n正文内容。\n"

    metadata, body = parse_frontmatter(text)

    assert metadata == {}
    assert body == text


def test_unterminated_frontmatter_is_treated_as_body() -> None:
    """只有起始分隔符（未闭合）时按普通正文处理——宁可当正文也不错位截断。"""
    text = "---\ntitle: 半截\n\n正文继续。\n"

    metadata, body = parse_frontmatter(text)

    assert metadata == {}
    assert body == text


def test_frontmatter_values_may_be_quoted() -> None:
    """带引号的值被去掉引号；空行与注释行被跳过。"""
    text = "---\n# 注释\nsource: \"带引号的出处\"\n\nscope: '单引号'\n---\n正文\n"

    metadata, body = parse_frontmatter(text)

    assert metadata["source"] == "带引号的出处"
    assert metadata["scope"] == "单引号"
    assert body.strip() == "正文"
