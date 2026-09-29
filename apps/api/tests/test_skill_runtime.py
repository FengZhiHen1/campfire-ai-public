"""skill 机制：发现、校验、目录预算、激活与资源边界。

对应 docs/技术设计/technical-details/通用基座.md 第 3 节与第 11 节的验证方式：
非法 frontmatter 有拒绝加载的用例；目录只含 name 与 description；同形激活；
资源一层深。这些用例刻意覆盖**拒绝路径**——一个只测成功路径的 skill 加载器无法
证明它真的会拒绝。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campfire.agent.skill_runtime import (
    SkillCatalogOverflowError,
    SkillDiscoveryError,
    SkillFrontmatterError,
    SkillNotFoundError,
    SkillRegistry,
    SkillResourceError,
    estimate_tokens,
    list_resources,
    read_resource,
    render_activation,
)

REPO_SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills"

VALID_FRONTMATTER = """---
name: {name}
description: 做什么与何时用：用于测试的技能描述。
metadata:
  surface: consult
allowed-tools: read_alpha write_beta
---
"""


def _make_skill(root: Path, name: str, *, frontmatter: str | None = None, body: str = "正文指令。\n") -> Path:
    """在 ``root`` 下造一个 skill 目录，返回 ``SKILL.md`` 路径。

    ``frontmatter`` 缺省时用合法模板（其中的 ``{name}`` 以目录名填充）；显式传入时
    原样使用——非法样例需要保持自己写的那份文本不变。
    """
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    text = (frontmatter if frontmatter is not None else VALID_FRONTMATTER.format(name=name)) + body
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    return directory / "SKILL.md"


# --- 正常路径 ---------------------------------------------------------------


def test_valid_skill_is_loaded_with_all_standard_fields(tmp_path: Path) -> None:
    _make_skill(tmp_path, "daily-consulting")

    registry = SkillRegistry.discover(tmp_path)
    skill = registry.get("daily-consulting")

    assert skill.metadata.name == "daily-consulting"
    assert skill.metadata.description.startswith("做什么与何时用")
    assert skill.metadata.surface == "consult"
    assert skill.metadata.autoload is True
    assert skill.metadata.allowed_tools == frozenset({"read_alpha", "write_beta"})
    assert skill.body == "正文指令。"


def test_repository_skill_root_loads_without_error() -> None:
    """配置指向的真实根目录必须可加载（当前为空，也不得报错）。"""
    registry = SkillRegistry.discover(REPO_SKILL_ROOT)

    assert registry.names() == ()
    # 空目录不是错误，但也必须留下可核对的痕迹：目录清单之外的普通文件被忽略。
    assert all(warning.code == "skill_directory_without_skill_md" for warning in registry.warnings)


def test_missing_root_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(SkillDiscoveryError, match="不存在"):
        SkillRegistry.discover(tmp_path / "not-there")


def test_directory_without_skill_md_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    _make_skill(tmp_path, "good-one")
    (tmp_path / "not-a-skill").mkdir()
    (tmp_path / "README.md").write_text("根目录说明", encoding="utf-8")

    registry = SkillRegistry.discover(tmp_path)

    assert registry.names() == ("good-one",)
    assert [warning.code for warning in registry.warnings] == ["skill_directory_without_skill_md"]


def test_get_reports_unknown_name_without_raising_through_the_run(tmp_path: Path) -> None:
    _make_skill(tmp_path, "good-one")
    registry = SkillRegistry.discover(tmp_path)

    with pytest.raises(SkillNotFoundError) as error:
        registry.get("nope")

    assert "good-one" in str(error.value)


# --- 拒绝路径：frontmatter ---------------------------------------------------

INVALID_DOCUMENTS: dict[str, str] = {
    "缺 frontmatter 起始行": "name: x\ndescription: y\n",
    "frontmatter 没有结束行": "---\nname: {name}\ndescription: 描述\n",
    "根不是映射": "---\njust a string\n---\n正文\n",
    "缺 name": "---\ndescription: 描述\n---\n正文\n",
    "缺 description": "---\nname: {name}\n---\n正文\n",
    "自创字段": "---\nname: {name}\ndescription: 描述\nversion: 2\n---\n正文\n",
    "重复字段": "---\nname: {name}\ndescription: 描述\ndescription: 又一遍\n---\n正文\n",
    "name 非字符串": "---\nname: 123\ndescription: 描述\n---\n正文\n",
    "name 大写": "---\nname: Daily\ndescription: 描述\n---\n正文\n",
    "name 连续连字符": "---\nname: daily--consulting\ndescription: 描述\n---\n正文\n",
    "description 为空": "---\nname: {name}\ndescription: '   '\n---\n正文\n",
    "metadata 值非字符串": "---\nname: {name}\ndescription: 描述\nmetadata:\n  autoload: false\n---\n正文\n",
    "metadata.autoload 取值非法": "---\nname: {name}\ndescription: 描述\nmetadata:\n  autoload: 'maybe'\n---\n正文\n",
    "metadata.surface 为空": "---\nname: {name}\ndescription: 描述\nmetadata:\n  surface: ''\n---\n正文\n",
    "allowed-tools 用逗号": "---\nname: {name}\ndescription: 描述\nallowed-tools: read_a, write_b\n---\n正文\n",
    "allowed-tools 含非法名": "---\nname: {name}\ndescription: 描述\nallowed-tools: 'read-a'\n---\n正文\n",
    "正文为空": "---\nname: {name}\ndescription: 描述\n---\n\n",
    "YAML 语法错误": "---\nname: {name}\ndescription: [未闭合\n---\n正文\n",
}


@pytest.mark.parametrize("case", sorted(INVALID_DOCUMENTS), ids=sorted(INVALID_DOCUMENTS))
def test_invalid_frontmatter_is_rejected(tmp_path: Path, case: str) -> None:
    _make_skill(tmp_path, "sample", frontmatter=INVALID_DOCUMENTS[case].format(name="sample"), body="")

    with pytest.raises(SkillDiscoveryError) as error:
        SkillRegistry.discover(tmp_path)

    assert "sample" in str(error.value)


def test_name_must_equal_directory_name(tmp_path: Path) -> None:
    _make_skill(tmp_path, "directory-name", frontmatter=VALID_FRONTMATTER.format(name="another-name"))

    with pytest.raises(SkillDiscoveryError, match="必须与父目录同名"):
        SkillRegistry.discover(tmp_path)


def test_name_length_limit_is_enforced(tmp_path: Path) -> None:
    long_name = "a" * 65
    _make_skill(tmp_path, long_name)

    with pytest.raises(SkillDiscoveryError, match="超过 64 字符"):
        SkillRegistry.discover(tmp_path)


def test_all_problems_are_reported_at_once(tmp_path: Path) -> None:
    """一次加载报出全部问题，而不是改一个报一个。"""
    _make_skill(tmp_path, "bad-one", frontmatter="---\ndescription: 缺 name\n---\n正文\n")
    _make_skill(tmp_path, "bad-two", frontmatter="---\nname: bad-two\n---\n正文\n")
    _make_skill(tmp_path, "good-one")

    with pytest.raises(SkillDiscoveryError) as error:
        SkillRegistry.discover(tmp_path)

    assert len(error.value.problems) == 2
    assert "bad-one" in str(error.value)
    assert "bad-two" in str(error.value)


def test_non_utf8_skill_file_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "sample"
    directory.mkdir()
    (directory / "SKILL.md").write_bytes(b"---\nname: sample\n---\n\xff\xfe\x00\x01")

    with pytest.raises(SkillDiscoveryError, match="UTF-8"):
        SkillRegistry.discover(tmp_path)


def test_body_size_is_only_a_warning(tmp_path: Path) -> None:
    """标准给的是建议值，超出只告警，不阻断加载。"""
    _make_skill(tmp_path, "long-one", body="中文正文内容较长。\n" * 700)

    registry = SkillRegistry.discover(tmp_path)

    codes = {warning.code for warning in registry.warnings}
    assert "skill_body_too_long" in codes
    assert "skill_body_too_large" in codes


# --- 目录渲染 ---------------------------------------------------------------


def test_catalog_contains_only_name_and_description(tmp_path: Path) -> None:
    _make_skill(tmp_path, "daily-consulting")
    registry = SkillRegistry.discover(tmp_path)

    catalog = registry.catalog()

    assert '<skill name="daily-consulting" description="做什么与何时用：用于测试的技能描述。" />' in catalog
    assert "正文指令" not in catalog
    assert "read_alpha" not in catalog


def test_catalog_excludes_skills_the_model_must_not_auto_match(tmp_path: Path) -> None:
    frontmatter = VALID_FRONTMATTER.format(name="emergency").replace("  surface: consult", '  autoload: "false"')
    _make_skill(tmp_path, "emergency", frontmatter=frontmatter)
    _make_skill(tmp_path, "daily")

    registry = SkillRegistry.discover(tmp_path)

    assert registry.catalog().count("<skill ") == 1
    assert "emergency" not in registry.catalog()
    # 但它仍然是一个已注册、可被程序注入激活的 skill
    assert registry.get("emergency").metadata.autoload is False


def test_catalog_escapes_attribute_characters(tmp_path: Path) -> None:
    frontmatter = """---
name: sample
description: 含引号 " 与 <尖括号> 与 & 的描述
---
正文。
"""
    _make_skill(tmp_path, "sample", frontmatter=frontmatter)

    catalog = SkillRegistry.discover(tmp_path).catalog()

    assert "&quot;" in catalog
    assert "&lt;尖括号&gt;" in catalog
    assert "&amp;" in catalog
    assert catalog.count("<skill ") == 1


def test_catalog_order_is_deterministic(tmp_path: Path) -> None:
    for name in ("zeta", "alpha", "mid"):
        _make_skill(tmp_path, name)
    registry = SkillRegistry.discover(tmp_path)

    first = registry.catalog()
    second = registry.catalog()

    assert first == second
    assert first.index("alpha") < first.index("mid") < first.index("zeta")


def test_catalog_narrows_by_surface_when_over_budget(tmp_path: Path) -> None:
    """超预算时按 ``metadata.surface`` 收窄到当前面可见的 skill。"""
    for index in range(6):
        _make_skill(tmp_path, f"consult-{index}")
    other = VALID_FRONTMATTER.format(name="other-one").replace("surface: consult", "surface: other")
    _make_skill(tmp_path, "other-one", frontmatter=other)
    registry = SkillRegistry.discover(tmp_path)

    full = registry.catalog(budget_tokens=10_000)
    narrowed = registry.catalog(surface="consult", budget_tokens=estimate_tokens(full) - 1)

    assert "other-one" in full
    assert "other-one" not in narrowed
    assert "consult-0" in narrowed


def test_catalog_fails_explicitly_when_narrowing_is_not_enough(tmp_path: Path) -> None:
    for index in range(6):
        _make_skill(tmp_path, f"consult-{index}")
    registry = SkillRegistry.discover(tmp_path)

    with pytest.raises(SkillCatalogOverflowError, match="预算"):
        registry.catalog(surface="consult", budget_tokens=20)


def test_catalog_budget_uses_the_injected_counter(tmp_path: Path) -> None:
    """计数器可注入：预算判定不绑定在某一种估算实现上。"""
    _make_skill(tmp_path, "sample")
    registry = SkillRegistry.discover(tmp_path)

    with pytest.raises(SkillCatalogOverflowError):
        registry.catalog(budget_tokens=500, count_tokens=lambda _text: 1000)

    assert registry.catalog(budget_tokens=500, count_tokens=lambda _text: 0)


def test_estimate_tokens_is_conservative_for_cjk() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    # 中文字符按 1 字符 1 token 计，刻意高估于 ASCII 比例
    assert estimate_tokens("中文正文") == 4


# --- 激活与资源 -------------------------------------------------------------


def test_activation_contains_body_and_resource_guide(tmp_path: Path) -> None:
    directory = tmp_path / "sample"
    _make_skill(tmp_path, "sample")
    (directory / "references").mkdir()
    (directory / "references" / "guide.md").write_text("参考", encoding="utf-8")
    (directory / "assets").mkdir()
    (directory / "assets" / "card.md").write_text("素材", encoding="utf-8")
    (directory / "scripts").mkdir()
    (directory / "scripts" / "run.py").write_text("print(1)", encoding="utf-8")

    registry = SkillRegistry.discover(tmp_path)
    payload = render_activation(registry.get("sample"))

    assert '<skill_content name="sample">' in payload
    assert "正文指令。" in payload
    assert "assets/card.md" in payload
    assert "references/guide.md" in payload
    # 一期不执行脚本，就不把脚本列成可用资源
    assert "scripts/run.py" not in payload


def test_activation_is_identical_for_repeated_renders(tmp_path: Path) -> None:
    """模型侧工具与应用侧注入共用同一渲染，同形由此保证。"""
    _make_skill(tmp_path, "sample")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    assert render_activation(skill) == render_activation(skill)


def test_list_resources_is_one_level_deep_and_sorted(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    (references / "b.md").write_text("b", encoding="utf-8")
    (references / "a.md").write_text("a", encoding="utf-8")
    (references / "nested").mkdir()
    (references / "nested" / "deep.md").write_text("d", encoding="utf-8")

    skill = SkillRegistry.discover(tmp_path).get("sample")

    assert [resource.relative_path for resource in list_resources(skill)] == [
        "references/a.md",
        "references/b.md",
    ]


def test_read_resource_returns_content(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    (references / "guide.md").write_text("参考正文", encoding="utf-8")

    skill = SkillRegistry.discover(tmp_path).get("sample")

    assert read_resource(skill, "references/guide.md") == "参考正文"


@pytest.mark.parametrize(
    "relative_path",
    ["../SKILL.md", "references/../SKILL.md", "/etc/passwd", "references/a/b.md", "other/a.md", "references"],
)
def test_read_resource_rejects_out_of_bounds_paths(tmp_path: Path, relative_path: str) -> None:
    _make_skill(tmp_path, "sample")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    with pytest.raises(SkillResourceError):
        read_resource(skill, relative_path)


def test_read_resource_rejects_missing_file(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    with pytest.raises(SkillResourceError, match="不存在"):
        read_resource(skill, "references/nope.md")


def test_read_resource_rejects_oversized_file(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    (references / "big.md").write_text("x" * 64, encoding="utf-8")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    with pytest.raises(SkillResourceError, match="体积上限"):
        read_resource(skill, "references/big.md", max_bytes=16)


def test_read_resource_rejects_non_utf8(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    (references / "binary.md").write_bytes(b"\xff\xfe\x00")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    with pytest.raises(SkillResourceError, match="UTF-8"):
        read_resource(skill, "references/binary.md")


def test_frontmatter_error_carries_path_and_detail(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample", frontmatter="---\ndescription: 缺 name\n---\n正文\n")

    with pytest.raises(SkillDiscoveryError) as error:
        SkillRegistry.discover(tmp_path)

    assert error.value.problems[0].startswith(tmp_path.as_posix())
    assert isinstance(error.value.problems, tuple)


def test_crlf_bom_and_document_end_marker_are_tolerated(tmp_path: Path) -> None:
    """结束行允许 ``...``（YAML 文档结束符），并容忍 CRLF 与 BOM。"""
    directory = tmp_path / "sample"
    directory.mkdir()
    text = "\ufeff---\r\nname: sample\r\ndescription: 描述\r\n...\r\n正文\r\n"
    (directory / "SKILL.md").write_text(text, encoding="utf-8")

    skill = SkillRegistry.discover(tmp_path).get("sample")

    assert skill.body == "正文"
    assert skill.metadata.description == "描述"


def test_build_metadata_rejects_non_string_license(tmp_path: Path) -> None:
    """非字符串字段必须报错而不是强转（``name: yes`` 曾会被转成 ``True``）。"""
    from campfire.agent.skill_runtime.skill import build_metadata

    with pytest.raises(SkillFrontmatterError, match="必须是字符串"):
        build_metadata(
            {"name": "sample", "description": "描述", "license": 2024},
            path="sample/SKILL.md",
            directory_name="sample",
        )
