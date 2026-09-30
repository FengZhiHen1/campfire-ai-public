"""skill 资源的列举与按需读取。

职责：列举 `references/` 与 `assets/` 下的资源，并按需读取一份。
边界：只认一层深的相对路径；拒绝绝对路径、`..`、NUL 与 `:`；单文件体积有上限。
参考：docs/技术设计/technical-details/通用基座.md 第 3 节、第 4 节。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import SkillResourceError
from .skill import Skill

# 四条边界都是显式的：
#
# - 只认 `references/<文件名>` 与 `assets/<文件名>` 两种形状，多一层即拒绝；
# - 相对路径、一层深，不做多级引用链。
# - 拒绝绝对路径、`..`、NUL 与 `:`（越界或不可移植的读取不是「找不到」，是明确的拒绝）；
# - 列举与读取用同一组判据：列举时就把不合格的条目标成「不可用」并带上原因，而不是
#   列出一份读不到的清单——第 4 节要求注入失败显式标注该来源不可用。
#
# 按需读取的资源根目录；顺序即资源指引中的展示顺序。
RESOURCE_DIRECTORIES: tuple[str, ...] = ("references", "assets")

# 单文件体积上限，避免一次读取把上下文挤爆（有界性要求）。
# 单个资源的体积上限（256 KiB）。取值理由：资源是给人读的文档片段，
# 超过这个量级说明该拆分或改由外部数据通道供给，而不是整份塞进对话。
MAX_RESOURCE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class SkillResource:
    """一个 skill 资源条目。

    `issue` 非空表示它存在但不可读（越界符号链接、超体积、非 UTF-8 之外的结构性
    问题）。这样的条目仍会被列出——显式标注不可用，好过让它悄悄消失。
    """

    relative_path: str
    """相对 skill 目录的路径，形如 `references/clarification.md`。"""

    directory: str
    """所属资源根目录（`references` 或 `assets`）。"""

    issue: str | None = None
    """不可读的原因；`None` 表示可以正常读取。"""


def list_resources(skill: Skill, *, max_bytes: int = MAX_RESOURCE_BYTES) -> tuple[SkillResource, ...]:
    """列出 skill 的资源文件（一层深、按路径排序、确定性顺序）。

    不存在的资源目录直接跳过；子目录忽略（标准只允许一层深）。每个条目都经
    :func:`_inspect` 判定可读性，不可读的带 `issue` 返回。
    """
    found: list[SkillResource] = []
    for directory_name in RESOURCE_DIRECTORIES:
        directory = skill.directory / directory_name
        if not _is_directory(directory):
            continue
        for entry in sorted(directory.iterdir(), key=lambda path: path.name):
            if not _is_regular_file(entry):
                continue
            relative_path = f"{directory_name}/{entry.name}"
            found.append(
                SkillResource(
                    relative_path=relative_path,
                    directory=directory_name,
                    issue=_inspect(skill, entry, relative_path, max_bytes=max_bytes),
                )
            )
    return tuple(found)


def read_resource(skill: Skill, relative_path: str, *, max_bytes: int = MAX_RESOURCE_BYTES) -> str:
    """按相对路径读取一份资源。

    参数与返回都是显式的：越界、层数不对、不是文件、非 UTF-8、超出体积上限，各自
    抛 :class:`SkillResourceError` 并说明原因，绝不返回空字符串冒充「读到了但是空」。

    Raises:
        SkillResourceError: 路径形状不合法、越出 skill 目录、文件不存在、体积超限或非 UTF-8。
    """
    _validate_shape(relative_path)
    parts = Path(relative_path).parts
    target = _resolve_target(skill, relative_path, parts)

    if not _is_regular_file(target):
        raise SkillResourceError(f"资源不存在或不是文件：{relative_path!r}")

    size = _stat_size(target, relative_path)
    if size > max_bytes:
        raise SkillResourceError(f"资源 {relative_path!r} 超过体积上限 {max_bytes} 字节")

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillResourceError(f"资源 {relative_path!r} 不是 UTF-8 文本") from exc
    except OSError as exc:
        # 权限、被占用、读一半被删——都归成同一个显式
        # 拒绝，不让裸 OSError 逃出去。
        raise SkillResourceError(f"资源 {relative_path!r} 读取失败（{type(exc).__name__}）") from exc


def _validate_shape(relative_path: str) -> None:
    """校验路径形状。

    Raises:
        SkillResourceError: 绝对路径、层数不对、不在允许的根目录下，或含 NUL / `:`。
    """
    allowed = "、".join(f"{name}/<文件名>" for name in RESOURCE_DIRECTORIES)
    if "\x00" in relative_path or ":" in relative_path:
        # NUL 会让 Path 操作抛裸 ValueError；`:` 在 Windows 上指 NTFS 备用数据流
        # （`guide.md:hidden`），那是列举永远看不到的第二份内容。
        raise SkillResourceError(f"资源路径 {relative_path!r} 含不可移植字符（NUL 或 ':'），拒绝读取")

    parts = Path(relative_path).parts
    if Path(relative_path).is_absolute() or len(parts) != 2 or parts[0] not in RESOURCE_DIRECTORIES:
        raise SkillResourceError(f"资源路径 {relative_path!r} 不合法；只接受一层深的相对路径：{allowed}")


def _resolve_target(skill: Skill, relative_path: str, parts: tuple[str, ...]) -> Path:
    """把相对路径解析成文件；

    Raises:
        SkillResourceError: 解析后越出 skill 目录（例如符号链接指到外面）。
    """
    target = skill.directory.joinpath(*parts)
    try:
        resolved = target.resolve()
        root = skill.directory.resolve()
    except OSError as exc:
        raise SkillResourceError(f"资源路径 {relative_path!r} 无法解析（{type(exc).__name__}）") from exc

    # 双保险：形状检查已排除 `..`，这里再挡一次符号链接把读取引到目录之外。
    if not resolved.is_relative_to(root):
        raise SkillResourceError(f"资源路径 {relative_path!r} 越出 skill 目录")
    return target


def _inspect(skill: Skill, entry: Path, relative_path: str, *, max_bytes: int) -> str | None:
    """返回不可读的原因；可读返回 `None`。用于列举时标注，不抛异常。"""
    try:
        resolved = entry.resolve()
        if not resolved.is_relative_to(skill.directory.resolve()):
            return "越出 skill 目录"
    except OSError as exc:
        return f"路径无法解析（{type(exc).__name__}）"

    size = _stat_size(entry, relative_path)
    if size < 0:
        return "无法获取文件大小"
    if size > max_bytes:
        return f"超过体积上限 {max_bytes} 字节"
    return None


def _stat_size(path: Path, relative_path: str) -> int:
    """取文件大小；失败返回 -1（由调用方决定是拒绝还是标注）。"""
    try:
        return path.stat().st_size
    except OSError:
        return -1


def _is_regular_file(path: Path) -> bool:
    """是否是普通文件；不抛异常。"""
    try:
        return path.is_file()
    except OSError:
        return False


def _is_directory(path: Path) -> bool:
    """是否是目录；不抛异常。"""
    try:
        return path.is_dir()
    except OSError:
        return False
