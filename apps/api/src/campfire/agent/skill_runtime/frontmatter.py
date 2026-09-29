"""SKILL.md 的 frontmatter 解析。

只做「文本 → 映射」这一层，字段语义与校验在 :mod:`campfire.agent.skill_runtime.skill`。

严格性的三条来源（docs/项目结构设计.md 第 4 节、通用基座第 3 节）：

1. frontmatter **只用标准的六个字段**，出现自创字段即拒绝——否则拼错的字段名会被
   静默忽略，skill 的行为与作者预期不一致。
2. 重复键即拒绝：PyYAML 默认静默保留最后一个，等于悄悄丢数据。
3. 非映射根（例如整段是字符串或列表）即拒绝，而不是当作空元数据。
"""

from __future__ import annotations

import yaml

from .errors import SkillFrontmatterError

# Agent Skills 开放标准的六个字段；顺序即文档顺序。
STANDARD_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
)

_FRONTMATTER_DELIMITERS = ("---", "...")
_UTF8_BOM = "\ufeff"


class _StrictSafeLoader(yaml.SafeLoader):
    """在 ``SafeLoader`` 上补一条重复键检查。"""


def _construct_mapping(loader: _StrictSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
    """构造映射前先查重复键，命中即报错并带上 YAML 行号。"""
    loader.flatten_mapping(node)
    seen: list[object] = []
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if any(existing == key for existing in seen):
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"frontmatter 出现重复字段：{key!r}",
                key_node.start_mark,
            )
        seen.append(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def split_frontmatter(text: str, *, path: str) -> tuple[str, str]:
    """把 ``SKILL.md`` 切成 (frontmatter 原文, 正文)。

    容忍 UTF-8 BOM 与 CRLF：它们不改变语义，不该成为加载失败的理由。

    **分隔符只认顶格行**。这条不是洁癖：YAML 块标量（``|`` / ``>``）里的缩进 ``---``
    会让「按 strip 找结束行」的实现提前收尾，把后面的 ``metadata``、``allowed-tools``
    静默吞进正文——实测能把 ``autoload: "false"`` 吞掉，使本该只由程序注入的 skill
    变成可被模型自动匹配。静默加载正是基座文档第 3 节禁止的处置。

    Raises:
        SkillFrontmatterError: 缺少顶格的 ``---`` 起始行，或没有顶格的结束行。
    """
    normalized = text.lstrip(_UTF8_BOM).replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    if not lines or lines[0].rstrip() != "---":
        raise SkillFrontmatterError(path, "文档必须以顶格的 `---` 开头（frontmatter 缺失）")

    for index in range(1, len(lines)):
        line = lines[index]
        if line != line.lstrip():
            # 缩进行属于上一行的块标量内容，不可能是分隔符。
            continue
        if line.rstrip() in _FRONTMATTER_DELIMITERS:
            body = "\n".join(lines[index + 1 :]).strip("\n")
            return "\n".join(lines[1:index]), body

    raise SkillFrontmatterError(path, "frontmatter 没有结束行（缺少顶格的 `---` 或 `...`）")


def parse_frontmatter(text: str, *, path: str) -> tuple[dict[object, object], str]:
    """解析 ``SKILL.md``：返回 (frontmatter 映射, 正文)。

    键类型是 ``object`` 而不是 ``str``：YAML 允许 ``123: x`` 这种键，先如实承载、
    再由调用方校验，比在这里假装键一定是字符串更诚实。

    Raises:
        SkillFrontmatterError: 分段失败、YAML 非法、根不是映射，或出现标准之外的字段。
    """
    raw, body = split_frontmatter(text, path=path)

    try:
        loaded = yaml.load(raw, Loader=_StrictSafeLoader)  # noqa: S506 —— _StrictSafeLoader 继承 SafeLoader
    except yaml.YAMLError as exc:
        detail = str(getattr(exc, "problem", None) or exc).strip()
        raise SkillFrontmatterError(path, f"frontmatter 不是合法 YAML：{detail}") from exc

    if loaded is None:
        raise SkillFrontmatterError(path, "frontmatter 为空；六个标准字段中 name 与 description 为必填")
    if not isinstance(loaded, dict):
        raise SkillFrontmatterError(path, f"frontmatter 根必须是字段映射，实际是 {type(loaded).__name__}")

    unknown = [key for key in loaded if key not in STANDARD_FIELDS]
    if unknown:
        allowed = "、".join(STANDARD_FIELDS)
        raise SkillFrontmatterError(
            path,
            f"出现标准之外的字段 {unknown}；只允许 {allowed}，自有元数据放 metadata 下",
        )

    return loaded, body
