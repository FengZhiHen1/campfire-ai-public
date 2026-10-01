"""人工处理队列的单元测试：摘录截断与复核件行构造（不起库、不调模型）。

RAG 策略第 1.2 节要求超限且不可分的单元「计入人工处理队列，不静默截断」。本文件只测
那批复核件里与数据库无关的两件事：

1. 摘录的截断上界与留痕——复核件本身就是「不静默截断」的落点，它的摘录不能偷偷截断；
2. 行的构造校验——没有原因的块交不出去，必须显式拒绝而不是补一个默认值。

落库、替换与撤下清理在集成测试 `test_library_manual_review_integration.py` 里。
"""

from __future__ import annotations

import uuid

import pytest

from campfire.modules.library.chunking import TARGET_MAX_CHARS, Chunk, chunk_markdown_section
from campfire.modules.library.manual_review import (
    MANUAL_REVIEW_EXCERPT_CHARS,
    ManualReviewError,
    build_excerpt,
    build_row,
)

#: 一段无法二次切分的超长单元：单段、无标点，因此既没有段落边界也没有句子边界。
UNSPLITTABLE = "甲" * 2500


def test_excerpt_keeps_short_text_intact() -> None:
    """不超过上界的正文原样返回——不加任何说明文字。"""
    assert build_excerpt("短正文。") == "短正文。"


def test_excerpt_bound_reuses_the_target_chunk_length() -> None:
    """摘录上界取同模块的目标块长，不另造数字（CORE-11 要求上界有理由）。

    判别性：把常量改成自造值（如 500）而不同时改这个断言，本用例失败——改的人
    必须重新说明依据，而不是悄悄换一个阈值。
    """
    assert MANUAL_REVIEW_EXCERPT_CHARS == TARGET_MAX_CHARS


@pytest.mark.parametrize("length", [MANUAL_REVIEW_EXCERPT_CHARS, MANUAL_REVIEW_EXCERPT_CHARS - 1])
def test_excerpt_at_or_below_the_bound_is_not_truncated(length: int) -> None:
    """恰好等于上界时不截断——边界是「超过才截」，差一位就会多出一行无用的说明。"""
    text = "乙" * length

    assert build_excerpt(text) == text


def test_excerpt_truncates_long_text_and_records_the_original_length() -> None:
    """超过上界：截断 + 在末尾写明原文总长（复核人据此知道手上不是全部内容）。"""
    excerpt = build_excerpt(UNSPLITTABLE)

    assert excerpt.startswith("甲" * MANUAL_REVIEW_EXCERPT_CHARS)
    assert "原文共 2500 字符" in excerpt
    assert f"此处保留前 {MANUAL_REVIEW_EXCERPT_CHARS} 字符" in excerpt
    assert len(excerpt) > MANUAL_REVIEW_EXCERPT_CHARS


def test_chunking_gives_manual_chunks_a_locator_and_a_reason() -> None:
    """manual 块一定带 locator 与 review_reason——这两列因此可以声明为 NOT NULL。

    定位的现实边界：没有 `#` 标题、首行也不是标题的源文件里，locator 取值是 `/`
    （`_join_locator` 的根路径），即「该文件没有章节路径」的如实表示，而不是一个
    编造出来的位置。此时定位退化为 `source_path` + 正文摘录。
    """
    report = chunk_markdown_section("/", UNSPLITTABLE)

    assert report.unsplittable, "无边界可切的超长单元必须进人工队列"
    manual = report.unsplittable[0]
    assert manual.locator == "/", "无标题源文件的 locator 是根路径，不是编出来的章节名"
    assert manual.review_reason, "进队列的块必须带原因，否则复核件交不出去"


def test_build_row_carries_locator_reason_and_excerpt() -> None:
    """复核件行带上运维定位与处置所需的全部字段。"""
    item_id = uuid.uuid4()
    chunk = Chunk(
        text="正文" * 10,
        header_path="/规范/",
        locator="/规范/一、基本要求/",
        chunk_index=3,
        needs_manual_review=True,
        review_reason="超长且找不到句子边界",
    )

    row = build_row(library="knowledge", item_id=item_id, source_path="/tmp/guide.md", chunk=chunk)

    assert row.library == "knowledge"
    assert row.item_id == item_id
    assert row.source_path == "/tmp/guide.md"
    assert row.locator == "/规范/一、基本要求/"
    assert row.review_reason == "超长且找不到句子边界"
    assert row.excerpt == "正文" * 10


def test_build_row_rejects_a_manual_chunk_without_a_reason() -> None:
    """没有原因的块被显式拒绝：补一个「未知原因」的默认值等于让复核件交不出去。

    判别性：把 `build_row` 里的校验删掉，本用例失败（不抛异常，改为写入一行没有
    原因的行）。
    """
    chunk = Chunk(
        text="正文",
        header_path="/",
        locator="/",
        chunk_index=0,
        needs_manual_review=True,
        review_reason=None,
    )

    with pytest.raises(ManualReviewError):
        build_row(library="knowledge", item_id=uuid.uuid4(), source_path="/tmp/x.md", chunk=chunk)
