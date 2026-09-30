"""skill 的数据形状与字段校验。

字段约束的真源是 docs/项目结构设计.md 第 4 节（Agent Skills 开放标准）：`name`
≤64 字符且只含小写字母、数字与连字符；`description` ≤1024 字符、非空；
`compatibility` ≤500 字符；`metadata` 是 string→string 的自由映射；
`allowed-tools` 是空格分隔的预授权列表。

本项目自有的元数据放在 `metadata` 下（不改标准格式），基座读取但不送入模型：
`autoload`（是否允许模型自动匹配）与 `surface`（所属面，供目录预算分组）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .errors import SkillFrontmatterError

# 只允许小写字母、数字与连字符；首尾不得是连字符、不得连续连字符——
# 这一条正则同时覆盖了标准里的四条约束。
# 用 fullmatch 校验（调用点）：`$` 匹配「结尾或结尾前换行」，`match` + `$` 会放进 `"x\n"`。
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NAME_MAX_LENGTH = 64
_DESCRIPTION_MAX_LENGTH = 1024
_COMPATIBILITY_MAX_LENGTH = 500
# allowed-tools 的单个工具名：与工具池注册名同形。
#
# 契约放在这里而不是 `agent/tools`：`allowed-tools` 是作者写下工具名的地方，而
# `agent/tools` 的池子要读 `Skill`；把契约放这边，两个子包就不必互相 import。
# 工具池复用本常量（`agent.tools.spec`），不另写一条正则。
#
# 同样用 fullmatch 校验：`$` 会放过尾随换行，而工具名里的换行足以撑破 <tool_availability>。
TOOL_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")

# 自有元数据键（见基座文档第 3 节末行）。
_METADATA_AUTOLOAD = "autoload"
_METADATA_SURFACE = "surface"


def _ensure_encodable(value: str, field: str, path: str) -> str:
    """拒绝无法编码为 UTF-8 的字符串（孤代理对）。

    YAML 允许 `"\\ud83d"` 这种落单的代理项；它在加载期一切正常，却会在落库或
    SSE 编码时才抛 `UnicodeEncodeError`——错误离现场很远，且那时已无法定位到文件。
    与其让它在远处炸，不如在这里拒绝。
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SkillFrontmatterError(
            path,
            f"{field} 含无法编码为 UTF-8 的字符（{exc.reason}）：落库与传输都会失败",
        ) from exc
    return value


def _require_str(frontmatter: Mapping[object, object], field: str, path: str, *, required: bool) -> str | None:
    """取一个字符串字段；缺省时按 `required` 决定报错还是返回 `None`。"""
    if field not in frontmatter:
        if required:
            raise SkillFrontmatterError(path, f"缺少必填字段 {field}")
        return None

    value = frontmatter[field]
    # YAML 会把 `license: 2024` 之类解析成非字符串；此时必须报错而不是强转，
    # 否则 `name: yes` 会变成 "True" 这种谁也不认识的 skill 名。
    if not isinstance(value, str):
        raise SkillFrontmatterError(path, f"{field} 必须是字符串，实际是 {type(value).__name__}")
    if not value.strip():
        raise SkillFrontmatterError(path, f"{field} 不能为空")
    return _ensure_encodable(value, field, path)


def _validate_name(name: str, path: str) -> str:
    if len(name) > _NAME_MAX_LENGTH:
        raise SkillFrontmatterError(path, f"name 超过 {_NAME_MAX_LENGTH} 字符（实际 {len(name)}）")
    if not NAME_PATTERN.fullmatch(name):
        raise SkillFrontmatterError(
            path,
            f"name={name!r} 不合法：只允许小写字母、数字与连字符，且首尾不得是连字符、不得连续连字符",
        )
    return name


def _validate_description(description: str, path: str) -> str:
    if len(description) > _DESCRIPTION_MAX_LENGTH:
        raise SkillFrontmatterError(path, f"description 超过 {_DESCRIPTION_MAX_LENGTH} 字符（实际 {len(description)}）")
    return description


def _parse_metadata(frontmatter: Mapping[object, object], path: str) -> Mapping[str, str]:
    """校验 `metadata`：string→string 的自由映射，自有键在这里读取。"""
    raw = frontmatter.get("metadata")
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, dict):
        raise SkillFrontmatterError(path, f"metadata 必须是字段映射，实际是 {type(raw).__name__}")

    parsed: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise SkillFrontmatterError(path, f"metadata 的键必须是字符串，实际是 {type(key).__name__}")
        if not isinstance(value, str):
            raise SkillFrontmatterError(
                path,
                f'metadata.{key} 必须是字符串（如 autoload: "false"），实际是 {type(value).__name__}',
            )
        parsed[_ensure_encodable(key, "metadata 的键", path)] = _ensure_encodable(value, f"metadata.{key}", path)

    # 自有键在加载时校验，不留到读取属性时才炸：那时已经离错误来源很远了。
    autoload = parsed.get(_METADATA_AUTOLOAD)
    if autoload is not None and autoload not in {"true", "false"}:
        raise SkillFrontmatterError(path, f'metadata.autoload 只接受 "true" 或 "false"，实际是 {autoload!r}')

    surface = parsed.get(_METADATA_SURFACE)
    if surface is not None and not surface.strip():
        raise SkillFrontmatterError(path, "metadata.surface 不能为空字符串：空值会让该 skill 对所有面都不可见")
    return MappingProxyType(parsed)


def _parse_allowed_tools(frontmatter: Mapping[object, object], path: str) -> frozenset[str]:
    """校验 `allowed-tools`：空格分隔的预授权工具名列表。"""
    raw = _require_str(frontmatter, "allowed-tools", path, required=False)
    if raw is None:
        return frozenset()
    if "," in raw:
        raise SkillFrontmatterError(path, "allowed-tools 用空格分隔，不接受逗号")

    tools = raw.split()
    for tool in tools:
        if not TOOL_NAME_PATTERN.fullmatch(tool):
            raise SkillFrontmatterError(
                path,
                f"allowed-tools 含非法工具名 {tool!r}：只允许小写字母、数字与下划线，且以字母开头",
            )
    return frozenset(tools)


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """一个 skill 的 frontmatter 事实。

    `metadata` 与 `allowed_tools` 都是不可变容器：加载后的元数据不得被就地改写，
    否则「同一个 skill 在不同轮次看到不同工具集」这类问题无法追查。
    """

    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: Mapping[str, str]
    allowed_tools: frozenset[str]

    @property
    def autoload(self) -> bool:
        """是否允许模型按 `description` 自动匹配激活。

        缺省为 `True`（标准里 skill 的默认语义就是可被模型选择）；本项目用
        `metadata.autoload: "false"` 把只能由程序注入的 skill 排除在自动匹配之外。
        """
        # 取值已在 _parse_metadata 中校验过，这里只做解读。
        return self.metadata.get(_METADATA_AUTOLOAD, "true") == "true"

    @property
    def surface(self) -> str | None:
        """所属面（供目录预算分组）；`None` 表示不限定面，对所有面可见。"""
        return self.metadata.get(_METADATA_SURFACE)


@dataclass(frozen=True, slots=True)
class Skill:
    """一个已加载并通过校验的 skill：元数据 + 正文 + 所在目录。"""

    metadata: SkillMetadata
    body: str
    directory: Path

    @property
    def name(self) -> str:
        """skill 名，同时也是它的目录名。"""
        return self.metadata.name


def build_metadata(frontmatter: Mapping[object, object], *, path: str, directory_name: str) -> SkillMetadata:
    """把 frontmatter 映射校验成 :class:`SkillMetadata`。

    `directory_name` 用于执行标准里的「`name` 必须与父目录同名」——这一条只有
    发现阶段知道目录名，所以在这里收口，避免两个地方各判一次。

    Raises:
        SkillFrontmatterError: 必填字段缺失、类型不符、取值越界，或 name 与目录名不一致。
    """
    name = _validate_name(_require_str(frontmatter, "name", path, required=True) or "", path)
    if name != directory_name:
        raise SkillFrontmatterError(path, f"name={name!r} 必须与父目录同名（目录名 {directory_name!r}）")

    description = _validate_description(_require_str(frontmatter, "description", path, required=True) or "", path)
    license_name = _require_str(frontmatter, "license", path, required=False)

    compatibility = _require_str(frontmatter, "compatibility", path, required=False)
    if compatibility is not None and len(compatibility) > _COMPATIBILITY_MAX_LENGTH:
        raise SkillFrontmatterError(
            path,
            f"compatibility 超过 {_COMPATIBILITY_MAX_LENGTH} 字符（实际 {len(compatibility)}）",
        )

    return SkillMetadata(
        name=name,
        description=description,
        license=license_name,
        compatibility=compatibility,
        metadata=_parse_metadata(frontmatter, path),
        allowed_tools=_parse_allowed_tools(frontmatter, path),
    )
