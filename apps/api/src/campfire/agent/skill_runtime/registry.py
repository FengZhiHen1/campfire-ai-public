"""skill 发现与注册表。

依据 docs/技术设计/technical-details/通用基座.md 第 3 节「发现」行：扫描配置根目录
下的 `*/SKILL.md`、解析 frontmatter，不合法即拒绝加载并在启动时失败，不得以
空元数据静默加载。根目录由配置指定（`Settings.skill_root`，环境变量 `SKILL_ROOT`，
默认应用内 `skills/`）。

两条纪律的具体落法：

- 一次报全部问题：所有不合法的 skill 聚合成一个 :class:`SkillDiscoveryError`
  抛出，而不是改一个报一个。
- 非致命问题不静默：目录缺少 `SKILL.md`、正文过长这类「可疑但不非法」的情况
  记为 :class:`SkillWarning` 挂在注册表上，由装配处决定怎么记录——不吞掉，也不假装
  是错误。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .catalog import CATALOG_BUDGET_TOKENS, estimate_tokens, render_catalog
from .errors import SkillDiscoveryError, SkillFrontmatterError, SkillNotFoundError
from .frontmatter import parse_frontmatter
from .skill import Skill, build_metadata

SKILL_FILE_NAME = "SKILL.md"

# 标准建议（非强制）：主体不超过 500 行、约 5000 token。超出只告警——
# 它是「建议」级别，把它变成硬失败会与标准本身冲突。
BODY_LINE_HINT = 500
BODY_TOKEN_HINT = 5000

_WARNING_MISSING_SKILL_FILE = "skill_directory_without_skill_md"
_WARNING_BODY_TOO_LONG = "skill_body_too_long"
_WARNING_BODY_TOO_LARGE = "skill_body_too_large"


@dataclass(frozen=True, slots=True)
class SkillWarning:
    """一条非致命的加载期发现。"""

    code: str
    path: str
    detail: str


class SkillRegistry:
    """已加载的 skill 集合：按名字取用、渲染目录。

    实例只经 :meth:`discover` 构造，因此「注册表里的每个 skill 都通过了校验」是
    构造前提，不需要在每个使用点重复防御。
    """

    def __init__(
        self,
        *,
        root: Path,
        skills: Mapping[str, Skill],
        warnings: tuple[SkillWarning, ...] = (),
    ) -> None:
        """直接构造注册表；常规路径请用 :meth:`discover` 以保证「已通过校验」的前提。"""
        self.root = root
        self._skills = MappingProxyType(dict(skills))
        self.warnings = warnings

    @classmethod
    def discover(cls, root: Path | str) -> SkillRegistry:
        """扫描根目录并加载全部 skill；任何一个不合法都让整体失败。

        Raises:
            SkillDiscoveryError: 根目录不存在，或存在不合法的 skill（problems 携带全部明细）。
        """
        root_path = Path(root)
        if not root_path.is_dir():
            raise SkillDiscoveryError(f"skill 根目录不存在或不是目录：{root_path}")

        try:
            entries = sorted(root_path.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise SkillDiscoveryError(f"skill 根目录无法列出：{root_path.as_posix()}（{type(exc).__name__}）") from exc

        skills: dict[str, Skill] = {}
        warnings: list[SkillWarning] = []
        problems: list[str] = []

        for entry in entries:
            if not _is_directory(entry):
                # 根目录下的普通文件（如 README.md）不是 skill，也不该被当错误。
                continue

            # 按精确名字判定，不靠文件系统的大小写语义：Windows 上
            # `skill.md` 会被 `is_file()` 认成 `SKILL.md`，同一棵树在 CI 的
            # Linux 上却会变成「目录下没有 SKILL.md」——行为必须与平台无关。
            skill_file = _exact_skill_file(entry)
            if skill_file is None:
                warnings.append(
                    SkillWarning(
                        code=_WARNING_MISSING_SKILL_FILE,
                        path=entry.as_posix(),
                        detail=f"目录下没有 {SKILL_FILE_NAME}（精确文件名），已跳过（疑似改名或拼写错误）",
                    )
                )
                continue

            try:
                skill = _load_skill(skill_file, directory_name=entry.name)
            except SkillFrontmatterError as exc:
                problems.append(str(exc))
                continue
            except UnicodeDecodeError as exc:
                problems.append(f"{skill_file.as_posix()}: 不是 UTF-8 文本（{exc.reason}）")
                continue
            except OSError as exc:
                # 权限、被占用、读到一半被删：不让裸 OSError 逃出去，破坏
                # 「一次加载报出全部问题」。取消不属于 Exception，照旧冒泡。
                problems.append(f"{skill_file.as_posix()}: 读取失败（{type(exc).__name__}）")
                continue

            skills[skill.name] = skill
            warnings.extend(_inspect_body(skill))

        if problems:
            raise SkillDiscoveryError(
                f"skill 根目录 {root_path.as_posix()} 下有 {len(problems)} 个 skill 不合法，已拒绝加载",
                problems=tuple(problems),
            )

        return cls(root=root_path, skills=skills, warnings=tuple(warnings))

    @property
    def skills(self) -> Mapping[str, Skill]:
        """全部已加载的 skill，按名字索引。"""
        return self._skills

    def names(self) -> tuple[str, ...]:
        """已注册的 skill 名（字典序）。"""
        return tuple(sorted(self._skills))

    def get(self, name: str) -> Skill:
        """按名字取 skill。

        Raises:
            SkillNotFoundError: 名字未注册。这是可恢复错误：调用方（工具层）应把它
                作为工具结果回给模型，而不是中断本次运行。
        """
        try:
            return self._skills[name]
        except KeyError as exc:
            raise SkillNotFoundError(name, self.names()) from exc

    def activation_candidates(self) -> tuple[Skill, ...]:
        """允许模型自动匹配的 skill，即目录里列出的那一批。

        依据：基座文档第 3 节把 `metadata.autoload` 定义为「是否允许模型自动匹配」，
        且该键不送入模型。既然模型看不到这个标记，唯一不泄标记又能守住语义的做法
        就是——不进入目录；程序注入的激活不受此限（第 3 节「激活（应用侧）」）。
        """
        return tuple(skill for skill in self._skills.values() if skill.metadata.autoload)

    def catalog(
        self,
        *,
        surface: str | None = None,
        budget_tokens: int = CATALOG_BUDGET_TOKENS,
        count_tokens: Callable[[str], int] = estimate_tokens,
    ) -> str:
        """渲染模型可见的技能目录（只含 `name` 与 `description`）。"""
        return render_catalog(
            self.activation_candidates(),
            surface=surface,
            budget_tokens=budget_tokens,
            count_tokens=count_tokens,
        )

    def visible_to(self, surface: str | None) -> tuple[Skill, ...]:
        """对某个面可见的 skill 全集（含不可自动匹配的），按名字排序。"""
        return tuple(
            skill
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
            if surface is None or skill.metadata.surface in (None, surface)
        )


def _is_directory(path: Path) -> bool:
    """是否是目录；不抛异常（权限不足时当作不是，交由上层告警处理）。"""
    try:
        return path.is_dir()
    except OSError:
        return False


def _exact_skill_file(directory: Path) -> Path | None:
    """在目录里按精确名字找 `SKILL.md`；找不到返回 `None`。"""
    try:
        for child in directory.iterdir():
            if child.name == SKILL_FILE_NAME and child.is_file():
                return child
    except OSError:
        return None
    return None


def _load_skill(skill_file: Path, *, directory_name: str) -> Skill:
    """读取并校验单个 `SKILL.md`。"""
    text = skill_file.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text, path=skill_file.as_posix())
    metadata = build_metadata(frontmatter, path=skill_file.as_posix(), directory_name=directory_name)

    if not body.strip():
        # 空正文的 skill 激活后什么也不会发生——那是空壳，不是「没有指令」。
        raise SkillFrontmatterError(skill_file.as_posix(), "SKILL.md 正文为空；激活后必须能给模型指令")

    return Skill(metadata=metadata, body=body, directory=skill_file.parent)


def _inspect_body(skill: Skill) -> Iterable[SkillWarning]:
    """对正文做只告警的规模检查（标准给的是建议值）。"""
    lines = len(skill.body.splitlines())
    if lines > BODY_LINE_HINT:
        yield SkillWarning(
            code=_WARNING_BODY_TOO_LONG,
            path=skill.directory.as_posix(),
            detail=f"正文 {lines} 行，超过标准建议的 {BODY_LINE_HINT} 行",
        )

    tokens = estimate_tokens(skill.body)
    if tokens >= BODY_TOKEN_HINT:
        yield SkillWarning(
            code=_WARNING_BODY_TOO_LARGE,
            path=skill.directory.as_posix(),
            detail=f"正文约 {tokens} token，达到标准建议上限 {BODY_TOKEN_HINT}（估算值，非精确分词）",
        )
