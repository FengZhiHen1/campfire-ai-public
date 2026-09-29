"""分块后处理：框架不保证的部分（RAG 策略第 1.2 节）。

**为什么必须有这一层**（2026-09-29 在真实产物上实测）：

- 框架的 `MarkdownNodeParser` 按 `#` 层级切分并写出 `metadata["header_path"]`，
  但它**不对超长 section 二次切分**——实测一个 2248 字符的 section 原样成为一个
  节点，而 TokenHub 嵌入接口**单条文本硬上限 2000 字符**。不切就会在嵌入处失败。
- 表格与列表在本样本上**未被切断**（框架按 heading 边界切，天然不切进表格/列表
  内部）；但这是框架的实现细节而非书面承诺，因此这里仍做结构保护：超长切分
  **只在段落/句子边界进行**，绝不切进表格行或列表项之间。

设计约束（RAG 策略第 1.2 节与第 10 节参数表）：

- 目标块长 **400–800 字符**；硬上限 **2000 字符**。
- **结构边界处不重叠**（重叠会让同一内容在引用里出现两次，也让 `locator` 含混）。
- 超限的**不可分单元**（例如整页表格）标记为「未嵌入」并进人工处理队列，
  **不静默截断**——截断会制造错误依据。

字符计数用 `len(str)`（Unicode 码点）而非框架 `SentenceSplitter` 的 token 计数：
嵌入接口的限制是**字符**，中文下 token 与字符不是一回事（设计已指出该陷阱）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 目标块长（字符）。RAG 策略第 10 节参数表。
TARGET_MIN_CHARS = 400
TARGET_MAX_CHARS = 800

#: 硬上限（字符）：TokenHub 嵌入接口单条文本 ≤2000 字符，**留出余量**——
#: 我们拼接时会在块前加标题路径，那部分也计入单条文本。
HARD_MAX_CHARS = 2000
#: 标题路径占用的预留额度，避免「正文刚好 2000 + 标题」超限。
_HEADER_BUDGET_CHARS = 200

#: 列表项与表格行的识别：切分时不切断它们。
_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_ROW_PATTERN = re.compile(r"^\s*\|.*\|\s*$")

#: 句子边界：中文句号/问号/叹号/分号与英文对应标点，后接空白或结束。
_SENTENCE_END_PATTERN = re.compile(r"(?<=[。！？；!?;])|(?<=[.])\s+")

#: Markdown 标题行：`#` 一到六级 + 空白 + 标题文字。
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass
class Chunk:
    """一个待嵌入的块。"""

    text: str
    #: 框架给出的**父级**标题路径（如 `/规范/附件2/`），原样保留。
    header_path: str
    #: 章节路径：`header_path` + 当前章节标题（如 `/规范/附件2/一、基本要求/`）。
    #: 返回契约的 `locator` 用它——框架的 `header_path` **不含当前标题**（实测：
    #: `## 一、服务对象` 的节点 header_path 只有父级），直接拿它当 locator 会让
    #: 同章下所有块失去区分度。
    locator: str
    #: 在原文中的序号，便于回溯与稳定排序。
    chunk_index: int
    #: 超出硬限且不可再分时为 True；此类块**不送去嵌入**，进人工处理队列。
    needs_manual_review: bool = False
    review_reason: str | None = None


@dataclass
class ChunkingReport:
    """分块结果的统计，供摄取记账与问题排查。"""

    chunks: list[Chunk] = field(default_factory=list)
    #: 因超限且不可分而未嵌入的块（进人工处理队列）。
    unsplittable: list[Chunk] = field(default_factory=list)

    @property
    def embedded_chunks(self) -> list[Chunk]:
        """可送去嵌入的块（排除需人工处理的）。"""
        return [c for c in self.chunks if not c.needs_manual_review]


def _is_structural_line(line: str) -> bool:
    """判断一行是否是列表项或表格行——这类行不能被从中间切开。"""
    return bool(_LIST_ITEM_PATTERN.match(line) or _TABLE_ROW_PATTERN.match(line))


def _split_oversized_paragraph(paragraph: str, limit: int) -> tuple[list[str], str | None]:
    """切分单个超长段落：结构行不可切，否则按句子累积。"""
    lines = paragraph.splitlines()
    structural = sum(1 for line in lines if _is_structural_line(line))
    if lines and structural >= max(1, len(lines) // 2):
        return [], "超长且以表格或列表为主，切断会破坏结构"

    sentences = [s for s in _SENTENCE_END_PATTERN.split(paragraph) if s]
    if len(sentences) <= 1:
        return [], "超长且找不到句子边界"

    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(sentence) > limit:
            return [], "存在单句超过硬上限"
        if len(buffer) + len(sentence) <= limit:
            buffer += sentence
            continue
        if buffer:
            pieces.append(buffer)
        buffer = sentence
    if buffer:
        pieces.append(buffer)
    return pieces, None


def _split_oversized(text: str, limit: int) -> tuple[list[str], str | None]:
    """把超长文本切成若干块，返回（块列表，失败原因）。

    切分顺序（从最保守到最激进）：

    1. **段落边界**（空行）——最自然，优先使用。
    2. **句子边界**——段落本身仍超限时。
    3. **结构行不可切**：若单个段落由表格行/列表项构成且自身超限，**不切**，
       返回失败原因交由调用方标记为需人工处理（静默截断会制造错误依据）。
    """
    if len(text) <= limit:
        return [text], None

    pieces: list[str] = []
    for paragraph in (p for p in re.split(r"\n\s*\n", text) if p.strip()):
        if len(paragraph) <= limit:
            pieces.append(paragraph)
            continue

        split, reason = _split_oversized_paragraph(paragraph, limit)
        if reason is not None:
            return [], reason
        pieces.extend(split)

    return [p for p in pieces if p.strip()], None


def _merge_small_pieces(pieces: list[str], min_chars: int, max_chars: int) -> list[str]:
    """把小段落合并到目标块长，减少碎片（提高检索语义完整度）。"""
    merged: list[str] = []
    buffer = ""
    for piece in pieces:
        candidate = f"{buffer}\n\n{piece}" if buffer else piece
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            merged.append(buffer)
        buffer = piece
    if buffer:
        merged.append(buffer)

    # 合并后仍低于下限的相邻块再合一次（仅当不超上限）。
    compacted: list[str] = []
    for piece in merged:
        if compacted and len(piece) < min_chars and len(compacted[-1]) + len(piece) + 2 <= max_chars:
            compacted[-1] = f"{compacted[-1]}\n\n{piece}"
        else:
            compacted.append(piece)
    return compacted


def _leading_heading(text: str) -> str:
    """取文本首行的标题文字（去掉 `#` 标记）；首行不是标题时返回空串。"""
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    match = _HEADING_PATTERN.match(first.strip())
    return match.group(1).strip() if match else ""


def _join_locator(header_path: str, section_title: str) -> str:
    """拼出章节路径：父级路径 + 当前章节标题。

    框架的 `header_path` 是**父级**路径，不含当前标题（实测），因此必须补上，
    否则同一章下所有块的 `locator` 完全相同、引用无法定位到章节。
    """
    base = header_path if header_path and header_path != "/" else "/"
    if not section_title:
        return base
    return f"{base}{section_title}/" if base.endswith("/") else f"{base}/{section_title}/"


def _with_header(locator: str, text: str) -> str:
    """把章节路径拼到块前面，供嵌入时保留层级语义。

    拼接后的长度才是「单条文本」长度——因此硬限判断必须基于拼接结果。
    """
    if not locator or locator == "/":
        return text
    return f"{locator}\n{text}"


def chunk_markdown_section(
    header_path: str,
    text: str,
    start_index: int = 0,
    section_title: str = "",
) -> ChunkingReport:
    """对一个 section 做块长归一化（供摄取流水线逐节点调用）。

    入参是框架已按 heading 切好的 section；本函数只负责**块长**层面的后处理。
    返回报告：`chunks` 是最终块；`unsplittable` 是需人工处理的块（超限且不可分）。

    ``section_title`` 由调用方在**节点粒度**给出：超长 section 会被切成多块，
    只有首块还带着标题行，因此不能从块文本里现取（那样后续块的章节路径会丢）。
    缺省时回退为从文本首行取。
    """
    report = ChunkingReport()

    title = section_title or _leading_heading(text)
    locator = _join_locator(header_path, title)

    # 预算扣除章节路径开销：正文可用的硬限。
    body_limit = HARD_MAX_CHARS - (len(locator) + 1 if locator and locator != "/" else 0)
    body_limit = max(body_limit, TARGET_MAX_CHARS)

    pieces, reason = _split_oversized(text, body_limit)

    if reason is not None:
        oversized = Chunk(
            text=_with_header(locator, text),
            header_path=header_path,
            locator=locator,
            chunk_index=start_index,
            needs_manual_review=True,
            review_reason=reason,
        )
        report.chunks.append(oversized)
        report.unsplittable.append(oversized)
        return report

    pieces = _merge_small_pieces(pieces, TARGET_MIN_CHARS, body_limit)

    for offset, piece in enumerate(pieces):
        report.chunks.append(
            Chunk(
                text=_with_header(locator, piece),
                header_path=header_path,
                locator=locator,
                chunk_index=start_index + offset,
            )
        )
    return report
