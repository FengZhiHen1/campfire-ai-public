"""规范文本投影：把结构化产出摊平成一段可读文本，供盲评使用。

职责：给正文与结构化块（行动卡 / 提问）一个**固定、可复现**的文本形状，让评审者只读
一份文本就能看到使用者实际会看到的内容。

三条硬约束（这一层存在的全部理由）：

1. **不改写**：只用标签与原文，不总结、不润色、不删内容、不调序——分节顺序、行顺序、
   标注指向的行号都原样保留。评审要判断「系统到底说了什么」，任何一句改写都会让结论
   失去依据。
2. **不隐藏**：正文为空就明确写「本轮没有正文」；空的卡片分节、缺失的选项都如实写出来，
   而不是省略（省略会让评审误以为系统没说）。
3. **可复核**：文本里保留 `card_id` / `batch_id` / 题目标识，评审的引文可以指回原始载荷，
   与 `structured` 里的 JSON 一一对应。
"""

from __future__ import annotations

from typing import Any

#: 投影里各类块的标签（固定字面量：评审指南按这些标签讲「证据在哪一段」）。
TEXT_HEADING = "【正文】"
CARD_HEADING = "【行动卡】"
QUESTION_HEADING = "【结构化提问】"
NO_TEXT_MARK = "（本轮没有正文）"


def _card_block(payload: dict[str, Any], index: int) -> str:
    """一张行动卡的投影：标题 + 分节（含逐行原文）+ 状态 + 标注。"""
    card_id = str(payload.get("card_id") or "")
    title = str(payload.get("title") or "")
    lines: list[str] = [f"{CARD_HEADING}{index}｜{title}（card_id={card_id}）"]

    sections = payload.get("sections") or []
    if not sections:
        lines.append("  （这张卡没有分节）")
    for section in sections:
        key = str(section.get("key") or "")
        heading = str(section.get("heading") or "")
        lines.append(f"  分节「{heading}」（key={key}）：")
        body = section.get("lines") or []
        if not body:
            lines.append("    （该分节没有文本行）")
        for line_no, text in enumerate(body, start=1):
            lines.append(f"    {line_no}. {text}")

    states = payload.get("states") or []
    if states:
        lines.append("  状态：")
        for state in states:
            lines.append(f"    {state.get('key')} = {state.get('value')}")

    annotations = payload.get("annotations") or []
    if annotations:
        lines.append("  标注：")
        for annotation in annotations:
            lines.append(f"    第 {annotation.get('target')} 行 — {annotation.get('kind')}")
    return "\n".join(lines)


def _question_block(payload: dict[str, Any], index: int) -> str:
    """一组结构化提问的投影：题干 + 选项 + 是否允许跳过。"""
    batch_id = str(payload.get("batch_id") or "")
    lines: list[str] = [f"{QUESTION_HEADING}{index}｜batch_id={batch_id}"]
    items = payload.get("items") or []
    if not items:
        lines.append("  （这一组没有题目）")
    for item_no, item in enumerate(items, start=1):
        item_id = str(item.get("id") or "")
        lines.append(f"  题{item_no}（id={item_id}）：{item.get('prompt')}")
        options = item.get("options") or []
        if options:
            rendered = []
            for option in options:
                label = option.get("label")
                value = option.get("value")
                rendered.append(f"{label}（value={value}）" if value is not None else str(label))
            lines.append("    选项：" + " / ".join(rendered))
        else:
            lines.append("    选项：（无，纯自由回答）")
        lines.append(f"    允许跳过：{'是' if item.get('allow_skip') else '否'}")
    return "\n".join(lines)


def project(text: str, structured: list[dict[str, Any]]) -> str:
    """把正文与结构化块投影成一段文本（无结构化内容时原样返回正文）。

    `structured` 里每项形如 `{"kind": "action_card"|"question", ...原始字段}`。
    未知 `kind` 一律原样以 JSON 文本呈现——宁可丑，不可丢。
    """
    if not structured:
        return text

    import json

    blocks: list[str] = []
    body = text.strip()
    blocks.append(f"{TEXT_HEADING}\n{body}" if body else f"{TEXT_HEADING}\n{NO_TEXT_MARK}")
    counters: dict[str, int] = {}
    for item in structured:
        kind = str(item.get("kind") or "")
        counters[kind] = counters.get(kind, 0) + 1
        if kind == "action_card":
            blocks.append(_card_block(item, counters[kind]))
        elif kind == "question":
            blocks.append(_question_block(item, counters[kind]))
        else:
            blocks.append(
                f"【未识别的结构化产出：{kind}】\n"
                + json.dumps({k: v for k, v in item.items() if k != "kind"}, ensure_ascii=False, sort_keys=True)
            )
    return "\n\n".join(blocks)


__all__ = [
    "CARD_HEADING",
    "NO_TEXT_MARK",
    "QUESTION_HEADING",
    "TEXT_HEADING",
    "project",
]
