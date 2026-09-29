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

from campfire.agent.markup import escape_attribute

from .errors import SkillCatalogOverflowError
from .skill import Skill

# 2026-09-29 定：目录预算上限 4000 token。
CATALOG_BUDGET_TOKENS = 4000

# ASCII 的经验比例基准：约 4 字符 1 token（只用于散文；稀疏 ASCII 由词段数兜底）。
_ASCII_CHARS_PER_TOKEN = 4
# 非 ASCII 且非 CJK 的字符（emoji、符号）按 2 token/字符计。
_WIDE_NON_CJK_TOKENS = 2


def _is_cjk(char: str) -> bool:
    """判断是否落在 CJK 区段（含全角标点与扩展区）。"""
    code = ord(char)
    return (
        0x3000 <= code <= 0x9FFF  # CJK 标点、假名、汉字基本区
        or 0xF900 <= code <= 0xFAFF  # 兼容汉字
        or 0xFF00 <= code <= 0xFFEF  # 全角字符
        or 0x20000 <= code <= 0x2FA1F  # 扩展 B 及以后
    )


def estimate_tokens(text: str) -> int:
    """估算一段文本占用的 token 数。**取值刻意取保守上界。**

    这是**估算不是精确分词**：DeepSeek 的分词器不在本仓库依赖内（技术栈设计只声明
    全应用单一模型，未引入 tokenizer）。规则：

    - ASCII：``max(字符数 / 4, 非空白连续段数)``——后者兜住稀疏 ASCII（``a a a``
      这类每个词都自成 token 的形态），只按 4 字符折算会低估一半；
    - 非 ASCII 且非 CJK（emoji、符号）：2 token/字符；
    - CJK：1 token/字符。

    这三条不是猜的。初版只写「ASCII/4 + 非 ASCII 各 1 token」并声称「宁可高估」，
    该说法被一次对抗性审查用代理分词器（tiktoken ``cl100k_base``）实测证伪：
    稀疏 ASCII 与 emoji 都低估到 0.5 倍，而目录预算的作用正是防挤占上下文，
    低估会让 4000 token 这条上限形同虚设。CJK 维持 1 token/字符，是因为实测
    0.88 token/字符，再乘 2 会把中文目录的可用容量砍掉一半。

    **代理结论的边界**：上述倍数来自 ``cl100k_base``，不是 DeepSeek 的分词器；
    「稀疏 ASCII 与 emoji 被低估」的方向对任何带空格前缀词表的 BPE 都成立，
    具体倍数未在真实模型上验证。需要精确值时由调用方注入真正的计数器
    （见 :func:`render_catalog` 的 ``count_tokens``）。
    """
    ascii_chars = 0
    ascii_runs = 0
    in_run = False
    cjk_chars = 0
    wide_chars = 0

    for char in text:
        if char.isascii():
            ascii_chars += 1
            if char.isspace():
                in_run = False
            elif not in_run:
                ascii_runs += 1
                in_run = True
        else:
            in_run = False
            if _is_cjk(char):
                cjk_chars += 1
            else:
                wide_chars += 1

    ascii_tokens = max(math.ceil(ascii_chars / _ASCII_CHARS_PER_TOKEN), ascii_runs)
    return ascii_tokens + cjk_chars + wide_chars * _WIDE_NON_CJK_TOKENS


def visible_to(skill: Skill, surface: str | None) -> bool:
    """判断一个 skill 是否对某个面可见。

    ``surface`` 为 ``None`` 表示调用方不限定面（全量可见）；skill 自身没有
    ``metadata.surface`` 时视为对所有面可见。

    **这是「面可见性」，不是「模型可选性」**：两者不是一回事，别用它拼目录。
    模型可见的那批由 ``SkillRegistry.activation_candidates`` 决定（排除了
    ``autoload: "false"``）；本函数只用于超预算时的按面收窄。
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

    **入参必须是模型可选的那批 skill**（``SkillRegistry.activation_candidates``）；
    直接传全部 skill 会把 ``autoload: "false"`` 的 skill 列给模型，等于让它自动匹配
    一个本不该被自动匹配的能力。

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
        name = escape_attribute(skill.name)
        description = escape_attribute(skill.metadata.description)
        lines.append(f'  <skill name="{name}" description="{description}" />')
    lines.append("</available_skills>")
    return "\n".join(lines)
