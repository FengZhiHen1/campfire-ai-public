"""生产代码注释点名的测试必须真的存在。

职责：扫描 `apps/api/src/campfire/**` 的注释与 docstring，取出其中点名的测试，逐条
核对它真的存在——文件名的情形核对那个文件在 `apps/api/tests/` 下存在，裸名的情形
按 AST 在 `apps/api/tests/**` 里查找同名 `def`。

为什么不并进 `test_layer_boundaries.py`：那个文件的覆盖范围已经写死为
docs/项目结构设计.md 第 7 节那张表的机械化（依赖白名单 + 基座禁项），本文件守的是
注释与测试之间的一致性。两者的问题域、失效方式与「什么改动该同步哪条检查」都不同，
混在一起会让范围变得看不出来。

本仓这一族缺陷的来源是同一个形状：注释声称「有某条测试守住这个性质」，而那条测试
根本不存在，于是注释承诺的性质实际无人守——排查时又看不出差别，因为注释读起来是
自足的。此前只靠人工逐个核对，核对完不留任何机械约束，所以反复复发。

纳入的写法（按本仓实际出现过的形态收集，样例见
`test_comment_test_reference_guard_detects_its_patterns`）：

- 带路径的测试文件：`apps/api/tests/test_x.py`、`tests/test_x.py`；
- 裸文件名的测试文件：`test_x.py`；
- 测试基建文件：`conftest.py`（带 `tests/` 段的写法与裸文件名都算）；
- 裸名：`test_x`。`tests/test_y.py::test_x` 里的用例名按裸名处理，前面的文件另算一条。

不覆盖的部分（诚实声明）：

- 只写「有测试断言」「由集成测试守护」而不点名的引用：没有名字可核；
- 不带 `.py` 的裸 `conftest`（本仓 `modules/library/embedding.py` 有这种措辞）：那是
  散文式提及而不是文件点名，纳入等于把陈述当成承诺；
- 名字存在不等于那条守卫真的钉住了注释声称的性质。D-68 的原始形态是「点名了一个真实
  存在的测试文件，而该文件里根本没有这条守卫」——机器只能证明名字在，证明不了断言在。
  本文件拦的是「名字不存在」那一半，另一半仍归人工核对与评审；
- 被点名的测试是否真在跑（`skip` / `xfail` 的用例同样算存在），也不在覆盖范围。
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "campfire"
TESTS_ROOT = Path(__file__).resolve().parent

_PY_PATH = re.compile(r"[A-Za-z0-9_./\\-]+\.py")
"""注释里的 `.py` 路径或文件名。先整段认出来，再判它是不是测试侧的文件。"""

_TESTS_SEGMENT = re.compile(r"(?:^|/)tests/")
"""`tests` 必须是完整的路径段：`ml_tests/` 这类同后缀目录不算。"""

_TEST_FILE_STEM = re.compile(r"\Atest_[A-Za-z0-9_]+\Z")
"""测试文件名主干：`test_` 开头。比对的是去掉 `.py` 之后的那一段。"""

_TEST_INFRA_FILE_NAMES = frozenset({"conftest.py"})
"""不带 `test_` 前缀但确属测试侧的文件名。"""

_TEST_NAME = re.compile(r"(?<![A-Za-z0-9_./])test_[A-Za-z0-9_]+")
"""裸测试名。

开头的否定前视是这条规则的要点：`latest_bound_object_id` 的后半段正好是
`test_bound_object_id`（本仓 `modules/profile/repository.py` 真有这个函数），按子串
匹配会把它当成点名了一条测试。判据取「整词的边界」而不是「出现过这个子串」，这与
`test_layer_boundaries.py` 里「`build_vector_store` 是函数不是模块」的处理同一口径
——标识符与子串的形状相同，只能按事实与边界分辨。
"""

_KIND_LABELS = {"file": "文件引用", "bare": "裸名引用"}

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
"""可能带 docstring 的节点：模块、类、函数与方法。"""


class _TestReference(NamedTuple):
    """生产代码注释里点名的一处测试引用。"""

    line: int
    kind: str
    name: str


def _test_file_reference(token: str) -> str | None:
    """`.py` 字面量若是测试侧文件，返回它在 `tests/` 下的相对路径，否则 None。

    判据有两路，取并集：文件名主干以 `test_` 开头，或写入的路径里有一段完整的
    `tests/`（`conftest.py` 这类不带 `test_` 前缀的测试基建文件由此纳入）。
    """
    normalized = token.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    if (
        _TEST_FILE_STEM.match(basename.removesuffix(".py")) is None
        and basename not in _TEST_INFRA_FILE_NAMES
        and _TESTS_SEGMENT.search(normalized) is None
    ):
        return None
    segment = _TESTS_SEGMENT.search(normalized)
    return normalized[segment.end() :] if segment else basename


def _references_in_text(text: str, start_line: int) -> list[_TestReference]:
    """一段注释或 docstring 里点名的测试引用。

    `start_line` 是这段文本在源文件里的起始行号，用来报出可定位的 `文件:行`。

    先把 `.py` 字面量整段屏蔽掉再找裸名：否则 `test_x.py` 会被同时算成文件引用与裸名
    引用，而裸名的判据（tests 下有同名 def 或同名文件）对第二种算法并不成立。
    """
    found: list[_TestReference] = []
    masked = list(text)
    for match in _PY_PATH.finditer(text):
        for index in range(match.start(), match.end()):
            masked[index] = " "
        relative = _test_file_reference(match.group(0))
        if relative is not None:
            found.append(_TestReference(start_line + text.count("\n", 0, match.start()), "file", relative))
    for match in _TEST_NAME.finditer("".join(masked)):
        found.append(_TestReference(start_line + text.count("\n", 0, match.start()), "bare", match.group(0)))
    return found


def _comment_units(source: str) -> list[tuple[int, str]]:
    """源码里的注释：(起始行号, 注释原文)。"""
    return [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]


def _docstring_units(source: str) -> list[tuple[int, str]]:
    """源码里的 docstring：(起始行号, 文本原文)，含类与函数的。"""
    units: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, _DOCSTRING_OWNERS):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            units.append((first.value.lineno, first.value.value))
    return units


def _references_in_source(source: str) -> list[_TestReference]:
    """一个源文件里点名的全部测试引用（注释与 docstring 都算，代码不算）。"""
    units = _comment_units(source) + _docstring_units(source)
    return [reference for line, text in units for reference in _references_in_text(text, line)]


@lru_cache(maxsize=None)
def _test_case_names() -> frozenset[str]:
    """`apps/api/tests/**` 里定义的全部用例名。

    按 AST 取 `def` / `async def` 的定义名，不做子串匹配：本仓的注释会提到生产侧函数
    （`latest_bound_object_id`），子串匹配分不开「提到一个名字」与「点名一条测试」。
    含类内方法：用例按类分组时名字同样是可被点名的用例。
    """
    names: set[str] = set()
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return frozenset(names)


def _reference_exists(reference: _TestReference) -> bool:
    """被点名的测试真的存在。

    文件引用按路径存在性判。裸名先按同名文件再按同名 `def` 判——本仓的注释常用裸名指
    整份文件（`test_layer_boundaries`、`test_agent_runtime`），那种写法同样是「那份测试
    存在」的承诺，不该因为少写了 `.py` 就放过。
    """
    if reference.kind == "file":
        return (TESTS_ROOT / reference.name).is_file()
    return (TESTS_ROOT / f"{reference.name}.py").is_file() or reference.name in _test_case_names()


def _production_sources() -> list[tuple[str, str]]:
    """生产侧（`src/campfire`）的全部 Python 源文件：(相对路径, 源码)。"""
    return [
        (path.relative_to(SRC_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(SRC_ROOT.rglob("*.py"))
    ]


def _missing_test_references(sources: Iterable[tuple[str, str]]) -> list[str]:
    """点名的测试不存在的引用，逐条可读。"""
    return [
        f"{relative}:{reference.line} 注释点名的测试不存在（{_KIND_LABELS[reference.kind]}）：{reference.name}"
        for relative, source in sources
        for reference in _references_in_source(source)
        if not _reference_exists(reference)
    ]


def test_comment_test_reference_guard_detects_its_patterns() -> None:
    """防止守门退化为空跑：识别、解析与整条判定都必须真的认得出样例。

    这里的合成源码只存在于内存里，不落盘、不动真实文件；真实文件上的消融另跑。
    """
    sample = (
        '"""两处常量由 `apps/api/tests/test_cache.py::test_pool_decodes_responses` 钉住。"""\n'
        "# 由 test_text_part_types_agree_across_the_two_parsers 守住\n"
        "# 测试基建见 apps/api/tests/conftest.py\n"
        "# 裸文件名 test_emergency_card.py 也算一条\n"
    )
    references = _references_in_source(sample)
    assert _TestReference(1, "file", "test_cache.py") in references
    assert _TestReference(1, "bare", "test_pool_decodes_responses") in references
    assert _TestReference(2, "bare", "test_text_part_types_agree_across_the_two_parsers") in references
    assert _TestReference(3, "file", "conftest.py") in references
    assert _TestReference(4, "file", "test_emergency_card.py") in references

    # 子串不是引用：`latest_bound_object_id` 里含 `test_`，按子串匹配会假红
    assert _references_in_source("# 留着它会成为 latest_bound_object_id 的输入\n") == []
    # 只有前缀、没有名字的写法不是引用
    assert _references_in_source("# test_ 开头的函数都是用例\n") == []
    # 生产侧模块路径不是测试引用（注释里到处都有，收了会假红满天）
    assert _references_in_source("# 见 agent/context/window.py 的 message_text\n") == []
    # 边界：不带 `.py` 的裸 `conftest` 是散文式提及，本规则不收（本仓 embedding.py 有这种措辞）
    assert _references_in_source("# 构造会抛 InvalidURL（本机实测，conftest 已留档）。\n") == []

    # 解析按事实：真用例名查得到，不存在的查不到
    assert "test_pool_decodes_responses" in _test_case_names()
    assert "test_no_such_guard_exists" not in _test_case_names()

    # 整条判定：引用不存在的测试必须产出违规
    missing = _missing_test_references([("surfaces/consult/probe.py", "# 由 `test_no_such_guard_exists` 守住\n")])
    assert len(missing) == 1, f"引用不存在的测试没有判红：{missing}"
    assert "test_no_such_guard_exists" in missing[0]
    assert "surfaces/consult/probe.py:1" in missing[0]
    # 引用真实存在的测试不判红：假红会逼后来人放宽规则
    assert _missing_test_references([("surfaces/consult/probe.py", "# 由 `test_layer_boundaries` 守住\n")]) == []
    assert _missing_test_references([("surfaces/consult/probe.py", "# 见 tests/test_cache.py:1\n")]) == []


def test_comment_named_tests_exist() -> None:
    """生产代码注释/docstring 里点名的测试必须真的存在。"""
    sources = _production_sources()
    assert sources, "src/campfire 下一个 Python 文件都没扫到，检查会空跑"

    references = [reference for _, source in sources for reference in _references_in_source(source)]
    kinds = {reference.kind for reference in references}
    assert kinds == {"file", "bare"}, (
        f"两类引用没有各自命中（实际 {sorted(kinds)}）——写法的识别通道可能失效了，"
        "先核对提取规则与真实文件的写法，不要直接放宽这条断言"
    )

    violations = _missing_test_references(sources)
    assert not violations, "注释点名的测试不存在——注释在撒谎，或那条测试被删了：\n" + "\n".join(violations)
