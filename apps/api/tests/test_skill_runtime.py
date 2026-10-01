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
    CATALOG_BUDGET_TOKENS,
    MAX_RESOURCE_BYTES,
    SKILL_FILE_NAME,
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
    """配置指向的真实根目录必须可加载，且加载结果与磁盘事实一致。

    期望值从文件系统推导，而不是写死「零 skill」——写死会在第一份真实 SKILL.md 落地时
    变成一条假失败，也掩盖「什么都没加载却报通过」这种真空绿跑。
    """
    expected_names = tuple(
        sorted(entry.parent.name for entry in REPO_SKILL_ROOT.glob(f"*/{SKILL_FILE_NAME}") if entry.is_file())
    )
    expected_warnings = sorted(
        entry.name for entry in REPO_SKILL_ROOT.iterdir() if entry.is_dir() and not (entry / SKILL_FILE_NAME).is_file()
    )

    registry = SkillRegistry.discover(REPO_SKILL_ROOT)

    assert registry.names() == expected_names
    assert sorted(warning.path.rsplit("/", 1)[-1] for warning in registry.warnings) == expected_warnings


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

INVALID_DOCUMENTS: dict[str, tuple[str, str]] = {
    # 样例 → (文档, 期望在失败原因里出现的片段)
    "缺 frontmatter 起始行": ("name: x\ndescription: y\n", "必须以顶格的 `---` 开头"),
    "frontmatter 没有结束行": ("---\nname: {name}\ndescription: 描述\n", "没有结束行"),
    "根不是映射": ("---\njust a string\n---\n正文\n", "必须是字段映射"),
    "缺 name": ("---\ndescription: 描述\n---\n正文\n", "缺少必填字段 name"),
    "缺 description": ("---\nname: {name}\n---\n正文\n", "缺少必填字段 description"),
    "自创字段": ("---\nname: {name}\ndescription: 描述\nversion: 2\n---\n正文\n", "标准之外的字段"),
    "重复字段": ("---\nname: {name}\ndescription: 描述\ndescription: 又一遍\n---\n正文\n", "重复字段"),
    "name 非字符串": ("---\nname: 123\ndescription: 描述\n---\n正文\n", "name 必须是字符串"),
    "name 大写": ("---\nname: Daily\ndescription: 描述\n---\n正文\n", "name='Daily' 不合法"),
    "name 连续连字符": (
        "---\nname: daily--consulting\ndescription: 描述\n---\n正文\n",
        "不得连续连字符",
    ),
    "description 为空": ("---\nname: {name}\ndescription: '   '\n---\n正文\n", "description 不能为空"),
    "metadata 值非字符串": (
        "---\nname: {name}\ndescription: 描述\nmetadata:\n  autoload: false\n---\n正文\n",
        "metadata.autoload 必须是字符串",
    ),
    "metadata.autoload 取值非法": (
        "---\nname: {name}\ndescription: 描述\nmetadata:\n  autoload: 'maybe'\n---\n正文\n",
        'autoload 只接受 "true" 或 "false"',
    ),
    "metadata.surface 为空": (
        "---\nname: {name}\ndescription: 描述\nmetadata:\n  surface: ''\n---\n正文\n",
        "surface 不能为空",
    ),
    "allowed-tools 用逗号": (
        "---\nname: {name}\ndescription: 描述\nallowed-tools: read_a, write_b\n---\n正文\n",
        "不接受逗号",
    ),
    "allowed-tools 含非法名": (
        "---\nname: {name}\ndescription: 描述\nallowed-tools: 'read-a'\n---\n正文\n",
        "含非法工具名",
    ),
    "正文为空": ("---\nname: {name}\ndescription: 描述\n---\n\n", "正文为空"),
    "YAML 语法错误": ("---\nname: {name}\ndescription: [未闭合\n---\n正文\n", "不是合法 YAML"),
    "YAML 嵌套过深": (
        "---\nname: {name}\ndescription: 描述\nmetadata:\n  deep: " + "[" * 3000 + "]" * 3000 + "\n---\n正文\n",
        "嵌套过深",
    ),
    "孤代理对": (
        '---\nname: {name}\ndescription: "\\ud83d 应急"\n---\n正文\n',
        "无法编码为 UTF-8",
    ),
}


@pytest.mark.parametrize("case", sorted(INVALID_DOCUMENTS), ids=sorted(INVALID_DOCUMENTS))
def test_invalid_frontmatter_is_rejected_with_the_expected_reason(tmp_path: Path, case: str) -> None:
    """每条非法样例都断言**具体原因**——只断言「被拒绝」无法区分按规则拒绝与因别的原因失败。"""
    document, expected = INVALID_DOCUMENTS[case]
    _make_skill(tmp_path, "sample", frontmatter=document.format(name="sample"), body="")

    with pytest.raises(SkillDiscoveryError) as error:
        SkillRegistry.discover(tmp_path)

    assert expected in str(error.value), f"期望失败原因包含 {expected!r}，实际：{error.value}"


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
    # 单个 ASCII 词段按 1.5 权重向上取整，短串会略偏高——保守方向是刻意的
    assert estimate_tokens("abcd") == 2
    # 中文字符按 1.25 token/字符计（实测约 1.0–1.25），刻意取偏高一侧
    assert estimate_tokens("中文正文") == 5


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


def test_activation_wraps_the_body_verbatim(tmp_path: Path) -> None:
    """激活载荷的正文必须与 SKILL.md 正文逐字一致（不是摘要、不是重写）。

    「模型侧工具与应用侧注入同形」的**跨路径**断言要等运行编排落地才能写（两条路径
    都要先存在）；这里先锁住内容契约，免得同形断言退化成自比自。
    """
    _make_skill(tmp_path, "sample")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    payload = render_activation(skill)

    assert payload == '<skill_content name="sample">\n正文指令。\n</skill_content>'


def test_activation_marks_unreadable_resources_instead_of_hiding_them(tmp_path: Path) -> None:
    """存在但读不了的资源照样列出并带原因：显式标注不可用，好过让它从清单里消失。"""
    directory = tmp_path / "sample"
    _make_skill(tmp_path, "sample")
    references = directory / "references"
    references.mkdir()
    (references / "guide.md").write_text("参考", encoding="utf-8")
    (references / "huge.md").write_bytes(b"x" * (MAX_RESOURCE_BYTES + 1))

    skill = SkillRegistry.discover(tmp_path).get("sample")
    payload = render_activation(skill)

    assert '<resource path="references/guide.md" />' in payload
    assert 'path="references/huge.md"' in payload
    assert "reason=" in payload


def test_repository_constants_match_the_design_numbers() -> None:
    """设计里写死的两个数字必须有测试锁定，否则改动它们不会惊动任何检查。"""
    assert CATALOG_BUDGET_TOKENS == 4000  # 基座文档第 3 节（2026-09-29 定）
    assert MAX_RESOURCE_BYTES == 256 * 1024


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


# --- 对抗性审查回归：曾经静默通过的缺陷 -------------------------------------
#
# 下面每条都对应一次实测发现的缺陷。它们曾经「加载成功、无告警」，因此用例的要点是
# **断言加载结果本身**，而不是断言「没有抛异常」。


def test_indented_delimiters_inside_block_scalars_do_not_end_frontmatter(tmp_path: Path) -> None:
    """块标量里的缩进 `---` / `...` 不是分隔符。

    初版按 ``line.strip()`` 找结束行，于是下面这份文档会在这里提前收尾：``metadata``
    与 ``allowed-tools`` 被静默吞进正文，``autoload: "false"`` 随之丢失——本该只由程序
    注入的 skill 变成可被模型自动匹配，且**没有任何告警**。
    """
    document = (
        "---\n"
        "name: sample\n"
        "description: |\n"
        "  第一行\n"
        "  ---\n"
        "  第二行\n"
        "compatibility: |\n"
        "  需要 Python 3.12\n"
        "  ...\n"
        "  其余环境说明\n"
        "metadata:\n"
        '  autoload: "false"\n'
        "  surface: consult\n"
        "allowed-tools: read_alpha write_beta\n"
        "---\n"
        "正文\n"
    )
    _make_skill(tmp_path, "sample", frontmatter=document, body="")

    skill = SkillRegistry.discover(tmp_path).get("sample")

    assert skill.metadata.description == "第一行\n---\n第二行\n"
    assert skill.metadata.compatibility == "需要 Python 3.12\n...\n其余环境说明\n"
    assert skill.metadata.autoload is False
    assert skill.metadata.surface == "consult"
    assert skill.metadata.allowed_tools == frozenset({"read_alpha", "write_beta"})
    assert skill.body == "正文"
    # 该 skill 不得出现在模型可见目录里
    assert skill.name not in SkillRegistry.discover(tmp_path).catalog()


def test_indented_opening_line_is_not_a_frontmatter_start(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample", frontmatter="  ---\nname: sample\ndescription: 描述\n---\n正文\n", body="")

    with pytest.raises(SkillDiscoveryError, match="顶格"):
        SkillRegistry.discover(tmp_path)


def test_read_failure_is_aggregated_instead_of_escaping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """读到一半失败（并发删除、权限）也要并进 problems，不让裸 OSError 逃出去。"""
    _make_skill(tmp_path, "sample")
    original_read_text = Path.read_text

    def flaky_read_text(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if self.name == SKILL_FILE_NAME:
            raise PermissionError(13, "Permission denied")
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)

    with pytest.raises(SkillDiscoveryError, match="读取失败"):
        SkillRegistry.discover(tmp_path)


def test_skill_file_name_must_match_case_exactly(tmp_path: Path) -> None:
    """``skill.md`` 在大小写不敏感的文件系统上会被 ``is_file()`` 认成 ``SKILL.md``。

    行为必须与平台无关：只认精确文件名，其余当作「目录缺少 SKILL.md」并告警。
    因此这里**无条件**断言未加载——如果实现退回 ``(entry / SKILL_FILE_NAME).is_file()``，
    本条会在 Windows 上失败（把目录里的小写文件当成 skill 加载）。
    """
    directory = tmp_path / "sample"
    directory.mkdir()
    (directory / "skill.md").write_text(VALID_FRONTMATTER.format(name="sample") + "正文\n", encoding="utf-8")

    registry = SkillRegistry.discover(tmp_path)

    assert registry.names() == ()
    assert [warning.code for warning in registry.warnings] == ["skill_directory_without_skill_md"]


@pytest.mark.parametrize("relative_path", ["references/x\x00.md", "references/guide.md:hidden"])
def test_read_resource_rejects_unportable_characters(tmp_path: Path, relative_path: str) -> None:
    """NUL 会让 Path 操作抛裸 ValueError；``:`` 在 Windows 上指 NTFS 备用数据流。"""
    _make_skill(tmp_path, "sample")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    (references / "guide.md").write_text("参考", encoding="utf-8")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    with pytest.raises(SkillResourceError, match="不可移植字符"):
        read_resource(skill, relative_path)


def test_list_resources_marks_unreadable_entries(tmp_path: Path) -> None:
    """列举与读取用同一组判据：列出来却读不了的条目必须带 issue。"""
    _make_skill(tmp_path, "sample")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    (references / "ok.md").write_text("参考", encoding="utf-8")
    (references / "big.md").write_text("x" * 64, encoding="utf-8")
    skill = SkillRegistry.discover(tmp_path).get("sample")

    resources = {resource.relative_path: resource.issue for resource in list_resources(skill, max_bytes=16)}

    assert resources == {"references/big.md": "超过体积上限 16 字节", "references/ok.md": None}


def test_symlink_escaping_the_skill_directory_is_marked(tmp_path: Path) -> None:
    _make_skill(tmp_path, "sample")
    outside = tmp_path / "outside.md"
    outside.write_text("目录外的内容", encoding="utf-8")
    references = tmp_path / "sample" / "references"
    references.mkdir()
    try:
        (references / "link.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("本机不允许创建符号链接")

    skill = SkillRegistry.discover(tmp_path).get("sample")

    listed = {resource.relative_path: resource.issue for resource in list_resources(skill)}
    assert listed["references/link.md"] == "越出 skill 目录"
    with pytest.raises(SkillResourceError, match="越出 skill 目录"):
        read_resource(skill, "references/link.md")


def test_column_zero_delimiter_inside_block_scalar_fails_loudly(tmp_path: Path) -> None:
    """顶格 `---` / `...` 落在块标量里时，必须**明确失败**而不是静默丢字段。

    这类文档按 YAML 规范会让块标量在该行结束，于是其后的 ``metadata``、``allowed-tools``
    落到 frontmatter 之外、被当成正文吞掉。实测（含 `|1` 显式缩进指示符）能把
    ``autoload: "false"`` 吞掉，使本该只由程序注入的 skill 变成可被模型自动匹配，
    而且既不报错也不告警——正是「不得静默加载」禁止的处置。
    """
    document = (
        "---\n"
        "name: trick-f\n"
        "description: |1\n"
        " 第一行\n"
        "---\n"
        "metadata:\n"
        '  autoload: "false"\n'
        "allowed-tools: read_alpha\n"
        "---\n"
        "正文。\n"
    )
    _make_skill(tmp_path, "trick-f", frontmatter=document, body="")

    with pytest.raises(SkillDiscoveryError, match="正文以标准字段"):
        SkillRegistry.discover(tmp_path)


def test_column_zero_end_marker_inside_block_scalar_fails_loudly(tmp_path: Path) -> None:
    document = (
        "---\n"
        "name: trick-b\n"
        "description: |\n"
        "  说明：第一行本身就是 ---\n"
        "...\n"
        "metadata:\n"
        '  autoload: "false"\n'
        "---\n"
        "正文。\n"
    )
    _make_skill(tmp_path, "trick-b", frontmatter=document, body="")

    with pytest.raises(SkillDiscoveryError, match="正文以标准字段"):
        SkillRegistry.discover(tmp_path)


def test_body_may_mention_standard_fields_after_the_first_line(tmp_path: Path) -> None:
    """正文**中间**出现标准字段是合法内容（指令里举例很常见），不得误伤。"""
    body = "用法示例：\nmetadata:\n  surface: consult\n\n以上是举例。\n"
    _make_skill(tmp_path, "sample", body=body)

    skill = SkillRegistry.discover(tmp_path).get("sample")

    assert skill.body.startswith("用法示例：")


def test_tool_name_pattern_rejects_trailing_newline() -> None:
    """``$`` 会匹配「结尾或结尾前换行」，所以必须用 fullmatch 校验。

    带换行的工具名会被原样写进 ``<tool_availability>`` 信封，把信封撑破。
    """
    from campfire.agent.skill_runtime.skill import TOOL_NAME_PATTERN

    assert TOOL_NAME_PATTERN.match("read_x\n") is not None  # 记录 `$` 的危险语义
    assert TOOL_NAME_PATTERN.fullmatch("read_x\n") is None
    assert TOOL_NAME_PATTERN.fullmatch("read_x") is not None


def test_skill_name_pattern_rejects_trailing_newline() -> None:
    """与工具名同理：``$`` 会放过尾随换行，必须用 fullmatch。"""
    from campfire.agent.skill_runtime.skill import NAME_PATTERN

    assert NAME_PATTERN.match("daily\n") is not None
    assert NAME_PATTERN.fullmatch("daily\n") is None
    assert NAME_PATTERN.fullmatch("daily-consulting") is not None
    """按代理分词器（tiktoken ``cl100k_base``）实测值校准的三条下界断言。

    数字是**实测值**，不是拍的阈值：``a `` ×200 → 201、emoji ×100 → 200、
    ``中文`` ×80 → 160。断言「估算 ≥ 实测」，否则 4000 token 那条预算就不是上界。
    """
    assert estimate_tokens("a " * 200) >= 201
    assert estimate_tokens("🙂" * 100) >= 200
    assert estimate_tokens("中文" * 80) >= 160
    assert estimate_tokens("") == 0


def test_estimate_tokens_on_the_shape_the_catalog_actually_has() -> None:
    """目录的真实形状（name + 中文 description + 少量标签）必须被保守估计。

    实测：50 条这样的目录约 1558 token（cl100k），估算 1733，比值 1.11。
    """
    catalog = (
        "<available_skills>\n"
        + "\n".join(
            f'  <skill name="skill-{index}" description="这是一个中文描述，说明做什么与何时用。" />'
            for index in range(50)
        )
        + "\n</available_skills>"
    )

    assert estimate_tokens(catalog) >= 1558


def test_estimate_tokens_may_underestimate_punctuation_heavy_ascii() -> None:
    """已知的**低估**形状：标点密集的中英混排（含文件路径）实测比值 0.95。

    这条断言是刻意的：`estimate_tokens` 的 docstring 说它是「估算不是上界」，
    如果哪天有人把权重调回「必上界」，这条会先失败——它守住的是**声明与实际一致**。
    """
    sample = "应急咨询 skill 的第一层闸门：先排除医疗危险（见 references/gates.md）。" * 10

    assert estimate_tokens(sample) < 360  # cl100k 实测 360
    # 但它不会低到离谱：仍在同一量级
    assert estimate_tokens(sample) > 300
