"""skill-loader 单元测试——发现/渐进披露/allowed-tools/metadata 透传。"""

from __future__ import annotations

from pathlib import Path

import pytest
from py_agent_kernel.skills import SkillLoader, SkillLoadError


def _make_skill(root: Path, name: str, *, description: str = "演示技能", metadata: dict | None = None,
                allowed_tools: list[str] | None = None, with_refs: bool = False) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = [f"name: {name}", f"description: {description}"]
    if allowed_tools:
        frontmatter.append("allowed-tools:")
        for t in allowed_tools:
            frontmatter.append(f"  - {t}")
    if metadata:
        frontmatter.append("metadata:")
        for k, v in metadata.items():
            frontmatter.append(f"  {k}: {v}")
    body = "\n".join(["---", *frontmatter, "---", "", f"# {name} 工作流指令正文"])
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    if with_refs:
        refs = skill_dir / "references"
        refs.mkdir()
        (refs / "ref.md").write_text("引用内容", encoding="utf-8")
    return skill_dir


class TestDiscovery:
    def test_discover_skill_packages(self, tmp_path):
        _make_skill(tmp_path, "skill-a")
        _make_skill(tmp_path, "skill-b")
        loader = SkillLoader()
        skills = loader.discover([tmp_path])
        assert {s.name for s in skills} == {"skill-a", "skill-b"}

    def test_missing_frontmatter_fields_rejected(self, tmp_path):
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: bad\n---\n正文", encoding="utf-8")
        loader = SkillLoader()
        with pytest.raises(SkillLoadError):
            loader.discover([tmp_path])

    def test_later_same_name_overrides(self, tmp_path):
        """同名 Skill 后加载者覆盖（加载顺序即优先级）。"""
        root1 = tmp_path / "r1"
        root2 = tmp_path / "r2"
        _make_skill(root1, "skill-x", description="旧")
        _make_skill(root2, "skill-x", description="新")
        loader = SkillLoader()
        loader.discover([root1, root2])
        assert loader.get("skill-x").description == "新"


class TestProgressiveDisclosure:
    def test_catalog_contains_name_and_description_only(self, tmp_path):
        _make_skill(tmp_path, "skill-a", description="应急咨询")
        loader = SkillLoader()
        loader.discover([tmp_path])
        catalog = loader.system_prompt_catalog()
        assert "skill-a" in catalog
        assert "应急咨询" in catalog
        assert "工作流指令正文" not in catalog  # 正文不常驻

    def test_body_loaded_on_demand(self, tmp_path):
        _make_skill(tmp_path, "skill-a")
        loader = SkillLoader()
        loader.discover([tmp_path])
        body = loader.get("skill-a").load_body()
        assert "工作流指令正文" in body
        assert "frontmatter" not in body or "name:" not in body

    def test_references_loaded_on_demand(self, tmp_path):
        _make_skill(tmp_path, "skill-a", with_refs=True)
        loader = SkillLoader()
        loader.discover([tmp_path])
        skill = loader.get("skill-a")
        assert skill.list_references() == ["ref.md"]
        assert "引用内容" in skill.load_reference("ref.md")


class TestMetadataAndAllowedTools:
    def test_metadata_passthrough(self, tmp_path):
        """metadata 原样透传（内核不解释 output-schema/surface/eval-set）。"""
        _make_skill(tmp_path, "skill-a", metadata={"output-schema": "EmergencyPlan", "surface": "emergency"})
        loader = SkillLoader()
        loader.discover([tmp_path])
        skill = loader.get("skill-a")
        assert skill.metadata == {"output-schema": "EmergencyPlan", "surface": "emergency"}

    def test_allowed_tools_filter(self, tmp_path):
        _make_skill(tmp_path, "skill-a", allowed_tools=["rag_search"])
        loader = SkillLoader()
        loader.discover([tmp_path])
        skill = loader.get("skill-a")
        assert skill.allows_tool("rag_search") is True
        assert skill.allows_tool("ticket_create") is False

    def test_no_allowed_tools_means_unrestricted(self, tmp_path):
        _make_skill(tmp_path, "skill-a")
        loader = SkillLoader()
        loader.discover([tmp_path])
        assert loader.get("skill-a").allows_tool("anything") is True
