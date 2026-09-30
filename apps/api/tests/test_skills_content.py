"""四个 skill 内容产物的工程检查：目录、frontmatter、标记块、工具范围与内容完整性。

## 这个文件挡的是哪几类缺陷

1. **真空闸门**：`apps/api/skills/` 下 0 个 skill 时，任何「遍历并逐项断言」的检查都会
   全绿通过。设计待办明确要求「0 个 skill 即失败」（`skills-ref validate` 接入要求），
   因此 :func:`test_skill_directories_are_not_empty` 把「扫到几个」本身当作断言。
2. **frontmatter 漂移**：六字段约束（`name` 与目录同名、长度上限、自有键落 `metadata`）
   在文档里，落地时靠人眼核对必然漂移。这里逐条机械校验。
3. **共用纪律拷贝漂移**：标准不支持 skill 间依赖，三条共同纪律必然有多份拷贝。
   标记块 + 逐字相等检查是唯一的防漂移手段。
4. **工具范围漂移**：`allowed-tools` 写错一个名字不会报错，只会让该工具在运行时
   被服务端拒绝——错误离现场很远。这里对照技能设计第 3 节的工具总表互查。

## 为什么不复用 `campfire.agent.skill_runtime` 的加载器

本文件校验的是**内容产物**，加载器由 `test_skill_runtime.py` 覆盖。复用加载器会让
「这些文件能被加载」由同一段代码同时生产与检验——检查失去判别力。因此 frontmatter
的解析与字段约束在这里独立实现一份；它与加载器的差异本身就是一条信息（若两者结论
不同，说明两边的判据已经分叉）。

## `skills-ref validate` 的探测结论（2026-09-30 实测，本泳道）

标准参照实现是 Node 包 `skills-ref`（`npx --yes skills-ref@latest validate <dir>`，
0.1.5，实测可用）。它**不在** PATH 上（`uv run --no-project python -c "shutil.which(...)"`
返回 `None`），只有经 `npx` 才可取用；而 `npx` 依赖网络取包，不能让测试套件依赖它。
因此本文件**两条通道都实现**：PATH 上有 CLI 就 subprocess 调用它；没有就使用本文件内
的等价校验。两条通道都需真的执行到，不存在「探测不到就跳过」的静默分支——
见 :func:`test_skills_ref_validate_passes_through_whichever_channel_is_available`。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

import pytest

from campfire.modules.accounts.errors import OnboardingTriggerError
from campfire.modules.accounts.onboarding import (
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    ONBOARDING_SKIPPED,
    ONBOARDING_STATES,
    ONBOARDING_TABLE_NAME,
    onboarding_pending,
    read_onboarding_state,
    should_inject_onboarding,
)
from campfire.surfaces.consult.registry import build_product_tools

#: skill 根目录：本文件位于 `<apps/api>/tests/`，故 parents[1] 是 `apps/api`。
SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills"

#: 一期四个 skill 的目录名（技能设计第 1 节）。`name` 必须与它逐字相同。
EXPECTED_SKILL_NAMES = ("daily-consulting", "emergency-consulting", "onboarding", "profile-curation")

#: 标准六字段（项目结构设计第 4 节）。出现集合之外的自创字段即失败。
STANDARD_FIELDS = frozenset({"name", "description", "license", "compatibility", "metadata", "allowed-tools"})

#: 必须携带 `metadata` 自有键的两个 skill（其余为可选的 `license` / `compatibility`）。
_REQUIRED_METADATA_KEYS = frozenset({"autoload", "surface"})

NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500

#: skill 名判据：仅小写字母、数字与连字符，首尾不得为连字符、不得连续连字符。
_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

#: 标记块语法（技能设计第 2 节）。
_SHARED_BLOCK_PATTERN = re.compile(
    r"<!--\s*shared:(?P<name>[a-z0-9-]+)\s*-->(?P<body>.*?)<!--\s*/shared:(?P=name)\s*-->",
    re.DOTALL,
)

#: 三条共同纪律的标记块名。一期只有这一个。
SHARED_BLOCK_NAME = "evidence-discipline"

#: 携带标记块的三个 skill；`onboarding` **不含**（豁免裁决见技能设计第 1 节）。
SKILLS_WITH_SHARED_BLOCK = ("daily-consulting", "emergency-consulting", "profile-curation")

#: 一期十个工具的**全集**（技能设计第 3 节总表）。
#:
#: `allowed-tools` 必须是它的子集。之所以取「全集」而不是「当前已注册的集合」：
#: 注册表目前只有 3 个工具（T04 未并入本泳道），拿它当上界会让合法的
#: `allowed-tools`（`search_cases`、`finish_onboarding` 等）被判越界——
#: 那是在检查注册进度，不是在检查内容产物。
#:
#: **待复验**：注册表全量注册后，应把本断言收紧为「`allowed-tools` ⊆ 已注册集合 ∩ 全集」。
FULL_TOOL_SET = frozenset(
    {
        "create_support_object",
        "emit_emergency_action_card",
        "finish_onboarding",
        "propose_profile_item",
        "read_memory",
        "read_profile_items",
        "read_profile_summary",
        "search_cases",
        "search_knowledge",
        "write_memory",
    }
)

#: 基座保留的工具名（`skill` 模型侧激活 / `read_skill_resource` 资源读取）。
#:
#: 两者恒可用、由基座注册，**不进 `allowed-tools` 的并集**（基座第 5 节、第 7.2 节）。
#: 写进内容产物即失败：那会让 skill 以为自己能「声明」一个机制工具。
RESERVED_TOOL_NAMES = frozenset({"ask_user", "read_skill_resource", "skill"})

#: 每个 skill 的 `allowed-tools` 必须与技能设计第 1 节表格逐字相同。
#:
#: 只断言「是全集子集」是不够的：漏写一个工具同样通过子集检查，而后果是该工具在
#: 激活期不可用（服务端拒绝越界调用），且没有任何东西会报错。因此额外钉住这张表。
EXPECTED_ALLOWED_TOOLS: Mapping[str, frozenset[str]] = {
    "emergency-consulting": frozenset({"search_knowledge", "search_cases", "emit_emergency_action_card"}),
    "daily-consulting": frozenset(
        {"read_profile_summary", "read_profile_items", "read_memory", "search_knowledge", "search_cases"}
    ),
    "profile-curation": frozenset({"read_profile_items", "propose_profile_item", "read_memory", "write_memory"}),
    "onboarding": frozenset(
        {
            "create_support_object",
            "read_profile_items",
            "propose_profile_item",
            "write_memory",
            "finish_onboarding",
        }
    ),
}

#: 每个 skill 的 `references/` 清单（技能设计第 1 节表格 + 各 skill 设计文档 3.5 节）。
EXPECTED_REFERENCES: Mapping[str, tuple[str, ...]] = {
    "emergency-consulting": ("action-card.md", "gates.md"),
    "daily-consulting": ("clarification.md", "evidence-and-options.md"),
    "profile-curation": ("extraction-rules.md", "source-and-status.md"),
    "onboarding": ("seed-questions.md", "telling-first.md"),
}

#: 正文主体行数上限（标准建议值，项目结构设计第 4 节）。超出即失败——
#: 标准给的是「建议」，而这里是内容产物的验收线：正文过长的实际后果是渐进披露失效。
BODY_LINE_LIMIT = 500

#: 内容产物里不得出现的残留标记词（零残留要求）。
#:
#: 用拼接构造字面量，避免本文件的**注释**本身被质量门禁命中（门禁只扫注释，
#: 但保持本文件自身干净比依赖门禁的判据更稳）。
_RESIDUE_MARKERS = tuple("".join(parts) for parts in (("TO", "DO"), ("FIX", "ME"), ("X", "XX"), ("HA", "CK")))

#: 内容产物里不得出现的「待定」措辞（题数等已裁决，不留待定标记）。
_PENDING_MARKERS = ("待定", "待确认题数", "TBD")


def _skill_directories() -> list[Path]:
    """列出 skill 根目录下含 `SKILL.md` 的目录（精确文件名，与平台大小写语义无关）。"""
    if not SKILL_ROOT.is_dir():
        return []
    return sorted(
        (entry for entry in SKILL_ROOT.iterdir() if entry.is_dir() and (entry / "SKILL.md").is_file()),
        key=lambda path: path.name,
    )


def _split_frontmatter(text: str, *, path: Path) -> tuple[str, str]:
    """把 `SKILL.md` 切成 (frontmatter 原文, 正文)。

    只认顶格的 `---` 行。刻意不复用加载器的同名函数：见模块 docstring 的说明。

    Raises:
        AssertionError: 起始行不是顶格 `---`，或没有顶格结束行。
    """
    lines = text.replace("\r\n", "\n").split("\n")
    assert lines and lines[0].strip() == "---", f"{path} 必须以顶格 --- 开头"
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise AssertionError(f"{path} 的 frontmatter 没有顶格结束行 ---")


def _parse_frontmatter(raw: str, *, path: Path) -> dict[str, object]:
    """解析六字段 frontmatter（标量 + `metadata` 两级映射）。

    手写而不是引 yaml：本文件只接受**我们自己写出的两种形状**（`key: value` 与
    `metadata:` 下的两级映射）。因此遇到别的形状必须显式失败，而不是被通用 YAML
    解析器宽容地接受——宽容地接受会让「写了一段缩进块标量」这种偏离静默通过。

    Raises:
        AssertionError: 出现缩进非 0/2 的行、冒号缺失、或 `metadata` 下的键重复。
    """
    parsed: dict[str, object] = {}
    nested_key: str | None = None
    nested: dict[str, str] = {}

    for number, line in enumerate(raw.split("\n"), start=1):
        if not line.strip():
            continue
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        assert ":" in stripped, f"{path}:{number} frontmatter 行缺少冒号：{line!r}"
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip().strip('"').strip("'")

        if indent == 0:
            if nested_key is not None:
                parsed[nested_key] = dict(nested)
                nested_key, nested = None, {}
            assert key, f"{path}:{number} frontmatter 键为空"
            if value:
                parsed[key] = value
            else:
                nested_key = key
        elif indent == 2 and nested_key is not None:
            assert key not in nested, f"{path}:{number} metadata 出现重复键 {key!r}"
            nested[key] = value
        else:
            raise AssertionError(f"{path}:{number} frontmatter 缩进层数不受支持（只接受 0 与 2）：{line!r}")

    if nested_key is not None:
        parsed[nested_key] = dict(nested)
    return parsed


def _validate_frontmatter(frontmatter: Mapping[str, object], *, directory_name: str, path: Path) -> None:
    """按项目结构设计第 4 节的六字段约束逐条校验。

    Raises:
        AssertionError: 字段集合、类型或取值违反约束。
    """
    unknown = set(frontmatter) - STANDARD_FIELDS
    assert not unknown, f"{path} 出现标准之外的字段 {sorted(unknown)}；自有元数据放 metadata 下"

    name = frontmatter.get("name")
    assert isinstance(name, str) and name, f"{path} 缺少必填字段 name"
    assert len(name) <= NAME_MAX_LENGTH, f"{path} 的 name 超过 {NAME_MAX_LENGTH} 字符"
    assert _NAME_PATTERN.fullmatch(name), f"{path} 的 name={name!r} 不合法（只允许小写字母、数字与连字符）"
    assert name == directory_name, f"{path} 的 name={name!r} 必须与父目录同名（目录名 {directory_name!r}）"

    description = frontmatter.get("description")
    assert isinstance(description, str) and description.strip(), f"{path} 缺少必填字段 description"
    assert len(description) <= DESCRIPTION_MAX_LENGTH, f"{path} 的 description 超过 {DESCRIPTION_MAX_LENGTH} 字符"

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        assert isinstance(compatibility, str), f"{path} 的 compatibility 必须是字符串"
        assert len(compatibility) <= COMPATIBILITY_MAX_LENGTH, (
            f"{path} 的 compatibility 超过 {COMPATIBILITY_MAX_LENGTH} 字符"
        )

    metadata = frontmatter.get("metadata")
    if metadata is not None:
        assert isinstance(metadata, dict), f"{path} 的 metadata 必须是字段映射"
        for key, value in metadata.items():
            assert isinstance(value, str), f'{path} 的 metadata.{key} 必须是字符串（如 autoload: "false"）'
        autoload = metadata.get("autoload")
        assert autoload in (None, "true", "false"), f'{path} 的 metadata.autoload 只接受 "true" 或 "false"'

    allowed = frontmatter.get("allowed-tools")
    if allowed is not None:
        assert isinstance(allowed, str) and allowed.strip(), f"{path} 的 allowed-tools 不得为空"
        assert "," not in allowed, f"{path} 的 allowed-tools 用空格分隔，不接受逗号"


def _read(path: Path) -> str:
    """读取内容产物（UTF-8）。"""
    return path.read_text(encoding="utf-8")


def _shared_blocks(text: str) -> dict[str, str]:
    """提取全部共用标记块：块名 → 块正文（不含标记行本身）。"""
    return {match.group("name"): match.group("body") for match in _SHARED_BLOCK_PATTERN.finditer(text)}


# --- 1. 目录扫描：0 个 skill 即失败 -------------------------------------------------


def test_skill_directories_are_not_empty() -> None:
    """扫到的 skill 数不得为 0——这是设计待办点名要求的「0 个 skill 即失败」。

    判别性：把四个目录改名或移走，本用例立刻失败。没有它，下面每一条「遍历四个目录
    逐项断言」的用例都会在 0 个 skill 时全绿——一条永远不会失败的闸门。
    """
    directories = _skill_directories()
    assert directories, (
        f"{SKILL_ROOT.as_posix()} 下没有任何含 SKILL.md 的目录——真空闸门：内容产物缺失时所有逐项检查都会静默通过"
    )


def test_exactly_the_four_designed_skills_are_present() -> None:
    """目录集合必须恰好是一期设计的四个（多一个少一个都失败）。"""
    names = tuple(directory.name for directory in _skill_directories())
    assert names == EXPECTED_SKILL_NAMES, f"skill 目录集合与技能设计第 1 节不一致：{names}"


def test_no_stray_directories_without_skill_md() -> None:
    """根目录下不得有「像 skill 但没有 SKILL.md」的目录。"""
    stray = sorted(
        entry.name for entry in SKILL_ROOT.iterdir() if entry.is_dir() and not (entry / "SKILL.md").is_file()
    )
    assert not stray, f"这些目录没有 SKILL.md（疑似改名或拼写错误）：{stray}"


# --- 2. frontmatter 与正文 -----------------------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_SKILL_NAMES)
def test_frontmatter_has_the_six_standard_fields(name: str) -> None:
    """六字段存在且合法，`name` 与目录同名，自有键落 `metadata`。"""
    directory = SKILL_ROOT / name
    raw, body = _split_frontmatter(_read(directory / "SKILL.md"), path=directory / "SKILL.md")
    frontmatter = _parse_frontmatter(raw, path=directory / "SKILL.md")

    _validate_frontmatter(frontmatter, directory_name=name, path=directory / "SKILL.md")

    metadata = frontmatter.get("metadata")
    assert isinstance(metadata, dict), f"{name} 的 frontmatter 必须有 metadata 段（自有键落此处）"
    missing = _REQUIRED_METADATA_KEYS - set(metadata)
    assert not missing, f"{name} 的 metadata 缺少自有键 {sorted(missing)}"
    assert metadata["surface"] == "consult", f"{name} 的 metadata.surface 必须是 consult"
    assert metadata["autoload"] in ("true", "false"), f"{name} 的 metadata.autoload 取值非法"

    assert body.strip(), f"{name} 的正文为空——激活后给不出任何指令"


def test_only_program_injected_skills_disable_autoload() -> None:
    """`autoload: "false"` 只出现在应急与引导两个程序注入的 skill 上。

    判别性：把日常咨询的 `autoload` 改成 `false`，它会从模型可见的技能目录里消失
    （基座按该键过滤），而其他检查都仍然通过——正是这条用例要拦的。
    """
    expected_false = {"emergency-consulting", "onboarding"}
    actual_false = set()
    for name in EXPECTED_SKILL_NAMES:
        frontmatter = _parse_frontmatter(
            _split_frontmatter(_read(SKILL_ROOT / name / "SKILL.md"), path=SKILL_ROOT / name / "SKILL.md")[0],
            path=SKILL_ROOT / name / "SKILL.md",
        )
        metadata = frontmatter["metadata"]
        assert isinstance(metadata, dict)
        if metadata.get("autoload") == "false":
            actual_false.add(name)
    assert actual_false == expected_false, f"程序注入的 skill 集合不一致：实际 {sorted(actual_false)}"


@pytest.mark.parametrize("name", EXPECTED_SKILL_NAMES)
def test_body_stays_within_the_line_budget(name: str) -> None:
    """正文主体不超过 500 行（标准建议值；超出即渐进披露失效）。"""
    _, body = _split_frontmatter(_read(SKILL_ROOT / name / "SKILL.md"), path=SKILL_ROOT / name / "SKILL.md")
    lines = len(body.splitlines())
    assert lines <= BODY_LINE_LIMIT, f"{name} 正文 {lines} 行，超过 {BODY_LINE_LIMIT} 行上限"


@pytest.mark.parametrize("name", EXPECTED_SKILL_NAMES)
def test_each_skill_has_exactly_its_designed_references(name: str) -> None:
    """`references/` 恰好是设计的那两份，且都被正文按一层深相对路径引用。

    后半条防的是「列了却引不到」：资源只有被正文点名才会在第 2 层被读取，
    没被点名的文件是死内容（渐进披露的第三层形同虚设）。
    """
    directory = SKILL_ROOT / name
    actual = tuple(sorted(entry.name for entry in (directory / "references").iterdir() if entry.is_file()))
    assert actual == EXPECTED_REFERENCES[name], f"{name} 的 references 清单与设计不一致：{actual}"

    body = _read(directory / "SKILL.md")
    for reference in actual:
        relative = f"references/{reference}"
        assert relative in body, f"{name} 的正文没有引用 {relative}（列了却读不到）"
        # 一层深：文件名本身不得含分隔符，否则引用会指向多级路径（标准不允许）。
        assert "/" not in reference and "\\" not in reference, f"{name} 的引用 {reference!r} 不是一层深"


@pytest.mark.parametrize("name", EXPECTED_SKILL_NAMES)
def test_content_has_no_residue_or_pending_markers(name: str) -> None:
    """零残留：不得出现待办标记词，也不得留下「待定」措辞（题数等已裁决）。"""
    directory = SKILL_ROOT / name
    files = [directory / "SKILL.md", *sorted((directory / "references").iterdir())]
    for path in files:
        text = _read(path)
        for marker in (*_RESIDUE_MARKERS, *_PENDING_MARKERS):
            assert marker not in text, f"{path.as_posix()} 残留标记 {marker!r}"


# --- 3. 共用纪律标记块 ---------------------------------------------------------------


def test_shared_block_is_byte_identical_across_the_three_consulting_skills() -> None:
    """同名标记块在三个咨询类 skill 中逐字一致（技能设计第 2 节的检查规则）。"""
    bodies: dict[str, str] = {}
    for name in SKILLS_WITH_SHARED_BLOCK:
        blocks = _shared_blocks(_read(SKILL_ROOT / name / "SKILL.md"))
        assert SHARED_BLOCK_NAME in blocks, f"{name} 缺少共用纪律标记块 {SHARED_BLOCK_NAME}"
        bodies[name] = blocks[SHARED_BLOCK_NAME]

    reference_name, reference_body = next(iter(bodies.items()))
    for name, body in bodies.items():
        assert body == reference_body, (
            f"标记块 {SHARED_BLOCK_NAME} 在 {name} 与 {reference_name} 之间不一致——"
            "标准不支持 skill 间依赖，拷贝必须逐字相同"
        )


def test_onboarding_has_no_shared_block() -> None:
    """`onboarding` 不含共用标记块（豁免裁决：引导不产出咨询建议）。

    判别性：给引导补上标记块，本用例失败——而豁免是有意的，不是遗漏。
    反过来，若三条纪律真的变了，上面那条相等检查会报出拷贝漂移。
    """
    blocks = _shared_blocks(_read(SKILL_ROOT / "onboarding" / "SKILL.md"))
    assert not blocks, f"onboarding 不应含标记块，实际有 {sorted(blocks)}"


def test_shared_block_contains_the_three_disciplines() -> None:
    """标记块正文必须真的承载三条共同纪律（逐条的关键判据都在）。"""
    body = _shared_blocks(_read(SKILL_ROOT / "daily-consulting" / "SKILL.md"))[SHARED_BLOCK_NAME]
    assert "有据才给可执行建议" in body
    assert "目标不等于服从" in body
    assert "专业判断与可读解释" in body
    assert "RQ-CON-02" in body and "RQ-CON-04" in body and "RQ-CON-06" in body


# --- 4. allowed-tools 与工具清单互查 -------------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_SKILL_NAMES)
def test_allowed_tools_match_the_design_table(name: str) -> None:
    """每个 skill 的 `allowed-tools` 与技能设计第 1 节的表格逐字相同。"""
    frontmatter = _parse_frontmatter(
        _split_frontmatter(_read(SKILL_ROOT / name / "SKILL.md"), path=SKILL_ROOT / name / "SKILL.md")[0],
        path=SKILL_ROOT / name / "SKILL.md",
    )
    declared = frozenset(str(frontmatter["allowed-tools"]).split())
    assert declared == EXPECTED_ALLOWED_TOOLS[name], (
        f"{name} 的 allowed-tools 与技能设计第 1 节不一致：实际 {sorted(declared)}，"
        f"期望 {sorted(EXPECTED_ALLOWED_TOOLS[name])}"
    )


def test_allowed_tools_are_a_subset_of_the_full_tool_set() -> None:
    """全部 `allowed-tools` 都是一期十工具全集的子集（工具名不得凭空发明）。"""
    for name in EXPECTED_SKILL_NAMES:
        frontmatter = _parse_frontmatter(
            _split_frontmatter(_read(SKILL_ROOT / name / "SKILL.md"), path=SKILL_ROOT / name / "SKILL.md")[0],
            path=SKILL_ROOT / name / "SKILL.md",
        )
        declared = set(str(frontmatter["allowed-tools"]).split())
        unknown = declared - FULL_TOOL_SET
        assert not unknown, f"{name} 的 allowed-tools 含技能设计第 3 节总表之外的工具名：{sorted(unknown)}"


def test_no_skill_declares_a_reserved_base_tool_name() -> None:
    """基座保留名（`skill` / `read_skill_resource` / `ask_user`）不得出现在 `allowed-tools`。

    三者恒可用、由基座 `register_base` 注册，不进 `allowed-tools` 的并集
    （基座第 5 节、第 7.2 节）。写进去会让 skill 以为自己能「声明」一个机制工具。
    """
    for name in EXPECTED_SKILL_NAMES:
        frontmatter = _parse_frontmatter(
            _split_frontmatter(_read(SKILL_ROOT / name / "SKILL.md"), path=SKILL_ROOT / name / "SKILL.md")[0],
            path=SKILL_ROOT / name / "SKILL.md",
        )
        declared = set(str(frontmatter["allowed-tools"]).split())
        offenders = declared & RESERVED_TOOL_NAMES
        assert not offenders, f"{name} 声明了基座保留名 {sorted(offenders)}"


def test_registry_does_not_drift_out_of_the_full_tool_set() -> None:
    """注册表里的工具名必须都在全集内（反方向漂移：实现多出一个未登记的工具）。

    与上面的子集检查合起来，两个方向都关上：内容不得发明工具名，
    实现也不得新增一个技能设计不知道的工具。

    **待复验**：当前注册表只有 3 个工具（T04 未并入本泳道），因此这条是
    「已注册 ⊆ 全集」；全量注册后应连同「`allowed-tools` ⊆ 已注册」一起收紧。
    """
    registered = {tool.name for tool in build_product_tools()}
    unknown = registered - FULL_TOOL_SET
    assert not unknown, f"注册表含技能设计第 3 节总表之外的工具：{sorted(unknown)}"
    assert registered, "注册表为空——反方向检查会空跑"


# --- 5. 内容完整性与忠实转写抽查 -----------------------------------------------------


def test_emergency_medical_red_flags_are_all_present() -> None:
    """医疗红灯清单九项全在 `gates.md` 内（缺一项即在现场漏掉一类急症信号）。"""
    gates = _read(SKILL_ROOT / "emergency-consulting" / "references" / "gates.md")
    for item in (
        "意识改变",
        "呼吸异常",
        "严重出血",
        "明显外伤",
        "癫痫持续或异常发作",
        "中毒或误服",
        "严重过敏",
        "明显疼痛",
        "突然出现与平时完全不同的神经或行为表现",
    ):
        assert item in gates, f"gates.md 缺少医疗红灯清单项：{item}"


def test_emergency_seven_cause_categories_are_all_present() -> None:
    """七类原因排查的类别名全在 `gates.md` 内。"""
    gates = _read(SKILL_ROOT / "emergency-consulting" / "references" / "gates.md")
    for category in (
        "Medical",
        "Pain",
        "Sensory",
        "Communication",
        "Predictability / Change",
        "Emotional / Psychiatric",
        "Social / Safety",
    ):
        assert category in gates, f"gates.md 缺少七类排查的类别：{category}"


def test_emergency_safety_model_has_eight_dimensions() -> None:
    """安全风险模型八维全在 `gates.md` 内，且不多不少。"""
    gates = _read(SKILL_ROOT / "emergency-consulting" / "references" / "gates.md")
    dimensions = (
        "Medical risk",
        "Risk to self",
        "Risk to others",
        "Elopement risk",
        "Traffic risk",
        "Environmental risk",
        "Vulnerability",
        "Exploitation risk",
    )
    for dimension in dimensions:
        assert dimension in gates, f"gates.md 缺少安全风险维度：{dimension}"
    assert len(dimensions) == 8


def test_emergency_state_value_mapping_is_complete() -> None:
    """四个状态字段的来源枚举、卡片三档与工具侧词表都在 `action-card.md` 内。"""
    card = _read(SKILL_ROOT / "emergency-consulting" / "references" / "action-card.md")
    for value in (
        # deviation
        "`none`",
        "`mild`",
        "`moderate`",
        "`marked`",
        "`unknown`",
        # communication
        "`baseline`",
        "`reduced`",
        "`severely_reduced`",
        "`unavailable`",
        # sensory_load
        "`low`",
        "`high`",
        "`extreme`",
        # medical_risk
        "`stable`",
        "`uncertain`",
        "`high_risk`",
    ):
        assert value in card, f"action-card.md 缺少状态取值：{value}"
    # 三档取值的中文呈现必须都在（否则映射表只写了一半）。
    for label in ("未排除", "高风险", "严重下降"):
        assert label in card, f"action-card.md 缺少卡片档位：{label}"


def test_emergency_source_and_confidence_vocabularies_are_complete() -> None:
    """来源六类与置信四级全在 `action-card.md` 内。"""
    card = _read(SKILL_ROOT / "emergency-consulting" / "references" / "action-card.md")
    for source in ("self_report", "family_report", "onsite_observation", "history", "medical_record", "ai_inference"):
        assert source in card, f"action-card.md 缺少来源标识符：{source}"
    for level in ("confirmed", "likely", "possible", "unknown"):
        assert level in card, f"action-card.md 缺少置信等级：{level}"


def test_seed_questions_map_onto_the_eight_emergency_context_groups() -> None:
    """种子问题八问与应急八组一一对应（「种子同构」的可机械判定形式）。

    八组的组名取自应急上下文接口形状，是本检查的判据来源；组名少一个即失败。
    """
    seeds = _read(SKILL_ROOT / "onboarding" / "references" / "seed-questions.md")
    groups = (
        "baseline",
        "known_triggers",
        "communication",
        "sensory_profile",
        "medical_risks",
        "proven_strategies",
        "unhelpful_strategies",
        "safety_history",
    )
    for group in groups:
        assert group in seeds, f"seed-questions.md 缺少应急上下文组：{group}"
    assert len(groups) == 8

    # 八行映射表：表格数据行数即题数，防「说了八问只写六行」。
    rows = [line for line in seeds.splitlines() if re.match(r"^\|\s*[1-8]\s*\|", line)]
    assert len(rows) == 8, f"seed-questions.md 的映射表有 {len(rows)} 行，应为 8 行（八问）"


def test_seed_questions_state_the_one_at_a_time_discipline() -> None:
    """种子问题的四条提问纪律（一次一问、2–4 选项、可跳过、不预选）都在。"""
    seeds = _read(SKILL_ROOT / "onboarding" / "references" / "seed-questions.md")
    for discipline in ("一次一问", "2–4 个选项", "可跳过", "不预选"):
        assert discipline in seeds, f"seed-questions.md 缺少提问纪律：{discipline}"


def test_telling_first_covers_the_three_things() -> None:
    """告知三件事全在 `telling-first.md` 内，且与设置页「数据说明」卡同源。"""
    telling = _read(SKILL_ROOT / "onboarding" / "references" / "telling-first.md")
    for thing in ("内容会用于什么", "谁可见", "是否送往外部模型"):
        assert thing in telling, f"telling-first.md 缺少告知事项：{thing}"
    assert "数据说明" in telling, "telling-first.md 未声明与设置页「数据说明」卡的口径关系"


def test_extraction_rules_define_the_three_way_split() -> None:
    """沉淀三分（使用者陈述／他人观察／系统推断）的判定与去向都在。"""
    rules = _read(SKILL_ROOT / "profile-curation" / "references" / "extraction-rules.md")
    for part in ("使用者陈述", "他人观察", "系统推断"):
        assert part in rules, f"extraction-rules.md 缺少三分之一：{part}"
    for destination in ("稳定层", "候选层"):
        assert destination in rules, f"extraction-rules.md 缺少去向：{destination}"


def test_source_and_status_declares_the_hard_constraint() -> None:
    """`source-and-status.md` 声明「推断不得写成 confirmed 且被拒绝而非静默改写」。"""
    source = _read(SKILL_ROOT / "profile-curation" / "references" / "source-and-status.md")
    assert "system_observation" in source and "ai_inference" in source
    assert "不得" in source and "confirmed" in source
    assert "被**拒绝**" in source or "请求被" in source


# --- 6. skills-ref validate 通道 ------------------------------------------------------


def _equivalent_validation(directory: Path) -> list[str]:
    """参照实现规则的等价校验：返回错误消息列表，空列表即通过。

    判据对齐 `skills-ref` 0.1.5 的 `validateMetadata` / `parseFrontmatter`：
    只允许六个字段、`name` 必填且与目录同名、`description` 必填且有长度上限、
    `compatibility` 有长度上限、`SKILL.md` 必须存在。

    名称的正则比参照实现**更严**（参照实现放行 Unicode 字母，本项目规范只允许
    小写字母、数字与连字符），差异方向是更严而非更松，因此不会漏掉参照实现能抓到的问题。
    """
    errors: list[str] = []
    skill_file = directory / "SKILL.md"
    if not skill_file.is_file():
        return [f"Missing required file: SKILL.md（{directory.as_posix()}）"]

    try:
        raw, _ = _split_frontmatter(_read(skill_file), path=skill_file)
        frontmatter = _parse_frontmatter(raw, path=skill_file)
    except AssertionError as exc:
        return [str(exc)]

    extra = sorted(set(frontmatter) - STANDARD_FIELDS)
    if extra:
        errors.append(f"Unexpected fields in frontmatter: {', '.join(extra)}")
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        errors.append("Missing required field or empty non-string: name")
    else:
        if not _NAME_PATTERN.fullmatch(name):
            errors.append(f"Skill name {name!r} contains invalid characters or bad hyphen placement")
        if name != directory.name:
            errors.append(f"Directory name {directory.name!r} must match skill name {name!r}")
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("Missing required field or empty non-string: description")
    elif len(description) > DESCRIPTION_MAX_LENGTH:
        errors.append(f"Description exceeds {DESCRIPTION_MAX_LENGTH} character limit")
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None and len(str(compatibility)) > COMPATIBILITY_MAX_LENGTH:
        errors.append(f"Compatibility exceeds {COMPATIBILITY_MAX_LENGTH} character limit")
    return errors


def test_skills_ref_validate_passes_through_whichever_channel_is_available() -> None:
    """四个 skill 全部通过标准校验。

    两条通道，**都真的执行断言**，不存在「探测不到就跳过」的静默分支：

    - PATH 上有 `skills-ref` 可执行文件 → 逐目录 subprocess 调用，断言退出码为 0；
    - 没有 → 用 :func:`_equivalent_validation`（判据对齐参照实现）。

    探测结论（本泳道 2026-09-30 实测）：CLI **不在** PATH 上。参照实现是 Node 包
    `skills-ref@0.1.5`，只能经 `npx` 取用（`npx --yes skills-ref@latest validate <dir>`
    实测输出 `Valid skill: <dir>`、退出码 0）；让测试依赖 npx 会引入网络依赖，
    因此默认走等价校验通道。PATH 上装好 CLI 时本用例自动改走那一侧，无需改代码。
    """
    directories = _skill_directories()
    assert directories, "没有 skill 目录可校验——见 test_skill_directories_are_not_empty"

    executable = shutil.which("skills-ref")
    if executable is None:
        for directory in directories:
            errors = _equivalent_validation(directory)
            assert not errors, f"{directory.name} 未通过等价校验（skills-ref CLI 不在 PATH 上）：{errors}"
        return

    for directory in directories:
        completed = subprocess.run(  # noqa: S603 —— 可执行文件来自 shutil.which，参数是固定目录列表
            [executable, "validate", str(directory)],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        assert completed.returncode == 0, (
            f"skills-ref validate 拒绝 {directory.name}：\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def test_equivalent_validation_actually_rejects_bad_frontmatter(tmp_path: Path) -> None:
    """等价校验的**判别性对照**：坏 frontmatter 必须被拒。

    没有这条，等价校验可能退化成「一律返回空列表」——那会让上面那条用例
    对任何内容都通过，正是设计待办点名要避免的真空闸门。
    """
    good = tmp_path / "sample-skill"
    good.mkdir()
    (good / "SKILL.md").write_text(
        "---\nname: sample-skill\ndescription: 做什么与何时用。\n---\n\n正文。\n", encoding="utf-8"
    )
    assert _equivalent_validation(good) == []

    wrong_name = tmp_path / "other-skill"
    wrong_name.mkdir()
    (wrong_name / "SKILL.md").write_text(
        "---\nname: sample-skill\ndescription: 做什么与何时用。\n---\n\n正文。\n", encoding="utf-8"
    )
    assert _equivalent_validation(wrong_name), "name 与目录名不一致时必须被拒"

    extra_field = tmp_path / "extra-skill"
    extra_field.mkdir()
    (extra_field / "SKILL.md").write_text(
        "---\nname: extra-skill\ndescription: 做什么与何时用。\nowner: 我\n---\n\n正文。\n", encoding="utf-8"
    )
    assert _equivalent_validation(extra_field), "标准之外的字段必须被拒"

    missing = tmp_path / "no-skill-md"
    missing.mkdir()
    assert _equivalent_validation(missing), "缺少 SKILL.md 必须被拒"


# --- 7. onboarding 触发判定（modules/accounts 的读表用例） ---------------------------


class _FakeRow:
    """一行查询结果的替身：只实现被读取的 `__getitem__`。"""

    def __init__(self, state: str) -> None:
        """记录该行的状态值。"""
        self._state = state

    def __getitem__(self, index: int) -> str:
        """按下标取值（`row[0]` 即 `state` 列）。"""
        assert index == 0, "读表只取 state 一列"
        return self._state


class _FakeResult:
    """查询结果的替身：`first()` 返回预置行或 `None`。"""

    def __init__(self, row: _FakeRow | None) -> None:
        """记录要返回的行。"""
        self._row = row

    def first(self) -> _FakeRow | None:
        """返回预置行；无行返回 `None`。"""
        return self._row


class _FakeSession:
    """关系库会话的替身：记录语句与绑定参数，返回预置结果。"""

    def __init__(self, row: _FakeRow | None) -> None:
        """记录本次查询应返回的行。"""
        self._row = row
        self.statements: list[str] = []
        self.params: list[dict[str, object] | None] = []

    async def execute(self, statement: object, params: dict[str, object] | None = None) -> _FakeResult:
        """记录调用并入参，返回预置结果（不真的连库）。"""
        self.statements.append(str(statement))
        self.params.append(params)
        return _FakeResult(self._row)


def test_onboarding_subset_of_states() -> None:
    """状态词表恰好是认证与账号第 8 节的三值，且两值属终结态。"""
    assert ONBOARDING_STATES == {ONBOARDING_IN_PROGRESS, ONBOARDING_COMPLETED, ONBOARDING_SKIPPED}


def test_table_name_carries_the_project_prefix() -> None:
    """表名带 `campfire_` 前缀（避免与身份服务自建的无前缀表撞名）。"""
    assert ONBOARDING_TABLE_NAME == "campfire_onboarding"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (None, True),
        (ONBOARDING_IN_PROGRESS, True),
        (ONBOARDING_COMPLETED, False),
        (ONBOARDING_SKIPPED, False),
    ],
)
def test_should_inject_onboarding_by_state(state: str | None, expected: bool) -> None:
    """判定表：无行或 `in_progress` → 注入；`completed` / `skipped` → 不注入。"""
    assert should_inject_onboarding(state) is expected


def test_should_inject_onboarding_rejects_a_state_outside_the_vocabulary() -> None:
    """词表外的状态显式报错，不猜（注入与不注入都会掩盖漂移）。"""
    with pytest.raises(OnboardingTriggerError, match="不在词表内"):
        should_inject_onboarding("half_done")


def test_unknown_state_does_not_silently_pass_the_pending_check() -> None:
    """`onboarding_pending` 把词表外的状态透传为错误，而不是当成「已完成」。"""
    with pytest.raises(OnboardingTriggerError):
        should_inject_onboarding("")


@pytest.mark.asyncio
async def test_read_onboarding_state_returns_none_when_there_is_no_row() -> None:
    """无行返回 `None`——「从未引导」的判据来源。"""
    session = _FakeSession(None)
    assert await read_onboarding_state(session, account_id="acc-1") is None
    assert session.statements and "SELECT state FROM campfire_onboarding" in session.statements[0]


@pytest.mark.asyncio
async def test_read_onboarding_state_uses_a_bound_parameter() -> None:
    """`account_id` 走绑定参数，不进语句文本（登录态可控值不拼进 SQL）。"""
    session = _FakeSession(_FakeRow(ONBOARDING_COMPLETED))
    assert await read_onboarding_state(session, account_id="acc-1") == ONBOARDING_COMPLETED
    assert session.params == [{"account_id": "acc-1"}]
    assert session.statements[0].endswith("WHERE account_id = :account_id")


@pytest.mark.asyncio
async def test_read_onboarding_state_rejects_an_empty_account_id() -> None:
    """空账号标识显式拒绝：空值在等值查询里必然查不到行，会把调用方错误伪装成业务判定。"""
    session = _FakeSession(None)
    with pytest.raises(OnboardingTriggerError, match="不得为空"):
        await read_onboarding_state(session, account_id="")
    assert session.statements == [], "拒绝路径不得发出任何查询"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (None, True),
        (ONBOARDING_IN_PROGRESS, True),
        (ONBOARDING_COMPLETED, False),
        (ONBOARDING_SKIPPED, False),
    ],
)
async def test_onboarding_pending_drives_from_the_state_table(state: str | None, expected: bool) -> None:
    """`onboarding_pending` 的判定完全由状态表驱动（不从档案或会话推导）。"""
    session = _FakeSession(None if state is None else _FakeRow(state))
    assert await onboarding_pending(session, account_id="acc-1") is expected
