"""技能目录：把已加载的 skill 渲染成一条**只含 name 与 description** 的注入消息内容。

依据 docs/技术设计/technical-details/通用基座.md 第 3 节：

- 目录注入只含 ``name`` 与 ``description``；正文与资源在激活时才进入对话。
- **目录预算上限 4000 token**（2026-09-29 定）；超出时按 ``metadata.surface`` 分组，
  只注入当前面可见的 skill。
- 按面筛选后仍超出时**显式失败**，不截断：截断会让模型看到一份看似完整实为残缺的
  技能清单，那属于基座文档第 9 节禁止的静默降级。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

from .errors import SkillCatalogOverflowError
from .skill import Skill

# 2026-09-29 定：目录预算上限 4000 token。
CATALOG_BUDGET_TOKENS = 4000

# token 估算的比例基准：ASCII 约 4 字符 1 token。
_ASCII_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """估算一段文本占用的 token 数。

    这是**估算不是精确分词**：DeepSeek 的分词器不在本仓库依赖内（技术栈设计只声明
    全应用单一模型，未引入 tokenizer）。规则是「ASCII 每 4 字符 1 token，非 ASCII
    每字符 1 token」——对中英混排偏保守（宁可高估）。

    保守方向是刻意的：预算的作用是防止目录挤占上下文，低估会让这条上限形同虚设。
    需要精确值时由调用方注入真正的计数器（见 ``render_catalog`` 的 ``count_tokens``）。
    """
    ascii_chars = sum(1 for char in text if char.isascii())
    other_chars = len(text) - ascii_chars
    return math.ceil(ascii_chars / _ASCII_CHARS_PER_TOKEN) + other_chars


def _escape_attribute(value: str) -> str:
    """转义属性值，避免 description 里的引号或尖括号破坏目录信封。"""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def visible_to(skill: Skill, surface: str | None) -> bool:
    """判断一个 skill 是否对某个面可见。

    ``surface`` 为 ``None`` 表示调用方不限定面（全量可见）；skill 自身没有
    ``metadata.surface`` 时视为对所有面可见。
    """
    if surface is None:
        return True
    declared = skill.metadata.surface
    return declared is None or declared == surface


def render_catalog(
    skills: Iterable[Skill],
    *,
    surface: str | None = None,
    budget_tokens: int = CATALOG_BUDGET_TOKENS,
    count_tokens: Callable[[str], int] = estimate_tokens,
) -> str:
    """渲染技能目录消息内容。

    顺序按 ``name`` 排序，保证同一组 skill 每次渲染逐字一致——目录会作为消息落进
    会话历史，不稳定的顺序会让模型前缀缓存从目录处失效。

    超预算时先按 ``surface`` 收窄一次；仍超出则抛
    :class:`SkillCatalogOverflowError`。两条路径都返回/抛出确定结果，没有中间态。

    Raises:
        SkillCatalogOverflowError: 全量或按面收窄后的目录仍超出 ``budget_tokens``。
    """
    ordered = sorted(skills, key=lambda skill: skill.name)
    rendered = _render_entries(ordered)
    if count_tokens(rendered) <= budget_tokens:
        return rendered

    narrowed = [skill for skill in ordered if visible_to(skill, surface)]
    if len(narrowed) == len(ordered):
        raise SkillCatalogOverflowError(
            f"技能目录约 {count_tokens(rendered)} token，超出预算 {budget_tokens}；"
            f"按面 {surface!r} 筛选无法收窄（可见 {len(narrowed)} 个 skill）"
        )

    narrowed_rendered = _render_entries(narrowed)
    if count_tokens(narrowed_rendered) <= budget_tokens:
        return narrowed_rendered

    raise SkillCatalogOverflowError(
        f"技能目录约 {count_tokens(narrowed_rendered)} token，按面 {surface!r} 筛选后仍超出预算 {budget_tokens}"
    )


def _render_entries(skills: Sequence[Skill]) -> str:
    """渲染目录信封；空集合也返回信封本身，保持消息形状稳定。"""
    lines = ["<available_skills>"]
    for skill in skills:
        name = _escape_attribute(skill.name)
        description = _escape_attribute(skill.metadata.description)
        lines.append(f'  <skill name="{name}" description="{description}" />')
    lines.append("</available_skills>")
    return "\n".join(lines)
