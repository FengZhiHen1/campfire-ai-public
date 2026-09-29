"""skill 资源的列举与按需读取。

依据 docs/技术设计/technical-details/通用基座.md 第 3 节：``references/`` 与
``assets/`` 按需读取；**相对路径、一层深，不做多级引用链**。

三条边界都是显式的：

- 只认 ``references/<文件名>`` 与 ``assets/<文件名>`` 两种形状，多一层即拒绝；
- 拒绝绝对路径与 ``..``（越界读取不是「找不到」，是明确的拒绝）；
- 单文件体积上限，避免一次读取把上下文挤爆（有界性要求）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import SkillResourceError
from .skill import Skill

# 按需读取的资源根目录；顺序即资源指引中的展示顺序。
RESOURCE_DIRECTORIES: tuple[str, ...] = ("references", "assets")

# 单个资源的体积上限（256 KiB）。取值理由：资源是给人读的文档片段，
# 超过这个量级说明该拆分或改由检索通道供给，而不是整份塞进对话。
MAX_RESOURCE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class SkillResource:
    """一个可读取的 skill 资源。"""

    relative_path: str
    """相对 skill 目录的路径，形如 ``references/clarification.md``。"""

    directory: str
    """所属资源根目录（``references`` 或 ``assets``）。"""


def list_resources(skill: Skill) -> tuple[SkillResource, ...]:
    """列出 skill 的资源文件（一层深、按路径排序、确定性顺序）。

    不存在的资源目录直接跳过；非文件条目（子目录）忽略，因为标准只允许一层深。
    """
    found: list[SkillResource] = []
    for directory_name in RESOURCE_DIRECTORIES:
        directory = skill.directory / directory_name
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir(), key=lambda path: path.name):
            if entry.is_file():
                found.append(SkillResource(relative_path=f"{directory_name}/{entry.name}", directory=directory_name))
    return tuple(found)


def read_resource(skill: Skill, relative_path: str, *, max_bytes: int = MAX_RESOURCE_BYTES) -> str:
    """按相对路径读取一份资源。

    参数与返回都是显式的：越界、层数不对、不是文件、非 UTF-8、超出体积上限，各自
    抛 :class:`SkillResourceError` 并说明原因，绝不返回空字符串冒充「读到了但是空」。

    Raises:
        SkillResourceError: 路径形状不合法、越出 skill 目录、文件不存在、体积超限或非 UTF-8。
    """
    parts = Path(relative_path).parts
    if Path(relative_path).is_absolute() or len(parts) != 2 or parts[0] not in RESOURCE_DIRECTORIES:
        allowed = "、".join(f"{name}/<文件名>" for name in RESOURCE_DIRECTORIES)
        raise SkillResourceError(f"资源路径 {relative_path!r} 不合法；只接受一层深的相对路径：{allowed}")

    target = skill.directory.joinpath(*parts)
    resolved = target.resolve()
    # 双保险：上面的形状检查已排除 `..`，这里再挡一次符号链接把读取引到目录之外。
    if not resolved.is_relative_to(skill.directory.resolve()):
        raise SkillResourceError(f"资源路径 {relative_path!r} 越出 skill 目录")

    if not target.is_file():
        raise SkillResourceError(f"资源不存在或不是文件：{relative_path!r}")

    if target.stat().st_size > max_bytes:
        raise SkillResourceError(f"资源 {relative_path!r} 超过体积上限 {max_bytes} 字节")

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillResourceError(f"资源 {relative_path!r} 不是 UTF-8 文本") from exc
