"""py-agent-kernel skill-loader（Agent Skills 标准）。

流程（Agent内核框架 §七）：
扫描发现 → frontmatter 解析 → name+description 注入系统提示 →
模型选定后按需加载完整指令 → allowed-tools 过滤。

渐进披露三层：description 常驻 → 正文按需 → references 再按需。
metadata 原样透传（内核不解释其内容——宿主的 output-schema/surface/eval-set
约定挂在此处）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Skill:
    """Skill 包（Agent Skills 标准目录：SKILL.md + 可选 scripts/ references/）。

    渐进披露：
    - name/description 常驻系统提示（loader 加载即得）
    - load_body() 按需加载完整指令正文（模型选定后）
    - load_reference() 再按需加载引用文件
    """

    name: str
    description: str
    skill_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] | None = None

    def load_body(self) -> str:
        """按需加载 SKILL.md 正文（frontmatter 之后的工作流指令）。"""
        skill_md = self.skill_dir / "SKILL.md"
        raw = skill_md.read_text(encoding="utf-8")
        return _strip_frontmatter(raw)

    def list_references(self) -> list[str]:
        """引用文件清单（references/ 目录）。"""
        refs = self.skill_dir / "references"
        if not refs.is_dir():
            return []
        return sorted(p.name for p in refs.iterdir() if p.is_file())

    def load_reference(self, name: str) -> str:
        """按需加载引用文件。"""
        ref = self.skill_dir / "references" / name
        if not ref.is_file():
            raise FileNotFoundError(f"Skill {self.name} 引用文件不存在: {name}")
        return ref.read_text(encoding="utf-8")

    def allows_tool(self, tool_name: str) -> bool:
        """allowed-tools 过滤（None 表示不限制）。"""
        if self.allowed_tools is None:
            return True
        return tool_name in self.allowed_tools


def _strip_frontmatter(raw: str) -> str:
    """剥离 YAML frontmatter，返回正文。"""
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            return raw[end + 4 :].lstrip("\n")
    return raw


def _parse_skill_md(skill_md: Path) -> Skill:
    """解析 SKILL.md（frontmatter: name/description/metadata/allowed-tools）。"""
    raw = skill_md.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            frontmatter = yaml.safe_load(raw[3:end]) or {}

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not name or not description:
        raise SkillLoadError(f"SKILL.md 缺少必填 frontmatter 字段 name/description: {skill_md}")

    allowed_tools_raw = frontmatter.get("allowed-tools")
    allowed_tools: list[str] | None = None
    if isinstance(allowed_tools_raw, list):
        allowed_tools = [str(t) for t in allowed_tools_raw]

    return Skill(
        name=str(name),
        description=str(description),
        skill_dir=skill_md.parent,
        metadata=frontmatter.get("metadata") or {},
        allowed_tools=allowed_tools,
    )


class SkillLoadError(Exception):
    """Skill 包加载失败（SKILL.md 缺失/frontmatter 非法）。"""


class SkillLoader:
    """Skill 扫描与目录汇总。

    来源：扩展 skills/ 常规目录（自动发现）+ resources_discover 动态贡献路径。
    每个 Skill 是含 SKILL.md 的子目录。
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def discover(self, skill_roots: list[Path]) -> list[Skill]:
        """扫描 skill 根目录列表，发现并解析全部 Skill 包。

        根目录下每个含 SKILL.md 的子目录（或根本身含 SKILL.md）即一个 Skill。
        同名 Skill 后加载者覆盖（加载顺序即优先级，与扩展一致）。
        """
        for root in skill_roots:
            root = Path(root)
            if not root.is_dir():
                continue
            if (root / "SKILL.md").is_file():
                self._register(_parse_skill_md(root / "SKILL.md"))
                continue
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "SKILL.md").is_file():
                    self._register(_parse_skill_md(child / "SKILL.md"))
        return self.skills

    def _register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def system_prompt_catalog(self) -> str:
        """常驻系统提示的 Skill 目录（name + description 渐进披露第一层）。"""
        if not self._skills:
            return ""
        lines = ["可用 Skills（选定后按需加载完整指令）："]
        for skill in self._skills.values():
            lines.append(f"- {skill.name}: {skill.description}")
        return "\n".join(lines)


__all__ = ["Skill", "SkillLoader", "SkillLoadError"]
