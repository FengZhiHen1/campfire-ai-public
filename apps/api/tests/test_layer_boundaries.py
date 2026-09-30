"""依赖白名单与基座禁项的机械检查。

docs/项目结构设计.md 第 7 节要求「依赖方向无环，并用白名单显式允许，而不是靠
约定」。本测试把那张表变成可执行断言：解析 apps/api/src/campfire 下每个模块
的 import，检查跨层引用是否落在白名单内。

同一节 agent 行的另一半禁项是「出现领域术语」，第 3 节把它展开成「基座不知道
自己被用在哪件事上：任何领域术语（咨询、档案、案例、支持对象…）」。它此前不在
本文件的覆盖范围内（只在文件头声明不覆盖），现在由两组字面检查接管，边界都写在
各自的常量处：

- `test_agent_layer_has_no_domain_terms`：按 :data:`DOMAIN_TERMS` 扫描 agent/
  的每一行（注释与 docstring 也算）；
- `test_agent_layer_does_not_cite_product_side_docs`：禁引产品面的契约与产品
  决策记录，也禁用产品需求编号为自己的决策立论。

不覆盖的部分（诚实声明）：表中「绕过用例服务直接写表」「直接访问数据库表」
「模块间不得互相依赖业务用例」三项既不是 import 关系也不是词面关系，
无法由本文件证明，需要各自的用例测试或审查。
"""

import ast
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "campfire"
SRC_MODULE_ROOT = "campfire"

LAYERS = ("agent", "surfaces", "tools", "modules", "core", "cli")

# 每层允许引用的同项目包前缀（不含该层自身，自身由 _owner_prefix 放行）。
# 依据 docs/项目结构设计.md 第 7 节的表。
ALLOWED: dict[str, set[str]] = {
    # 基座只允许 core/config（设计另列 core/logging，但该模块在目录设计中不存在）。
    # ``campfire.agent`` 自身在列：第 7 节的表把 agent/* 当作**一层**，层内子包
    # （runtime、skill_runtime、tools…）互相引用不构成跨层依赖；而 _owner_prefix
    # 只放行到 agent/<子包>，不放行兄弟子包，故必须显式列出。
    "agent": {"campfire.core.config", "campfire.agent"},
    "surfaces": {"campfire.agent", "campfire.tools", "campfire.modules", "campfire.core"},
    # 产品侧工具**实现**基座定义的接口：`ToolHandler` 收 `ToolContext`、返回
    # `ToolOutcome`（两者都在 `agent/tools`）。不依赖基座的类型就不是基座的工具，
    # 因此放行 `campfire.agent.tools`——**只放行它**，不放行整个 `campfire.agent`
    # （运行编排、模型网关、运行记录与产品工具无关）。反方向不变：`agent/*` 仍不得
    # 依赖 `tools/*`（见上一行）。依据见 docs/项目结构设计.md 第 7 节。
    "tools": {"campfire.agent.tools", "campfire.modules", "campfire.core"},
    "modules": {"campfire.core"},
    "core": {"campfire.core"},
    # 本地运维入口：禁止 import surfaces、禁止暴露成服务端点。
    #
    # **为什么放行 memory 与 accounts**（2026-09-30 定调级修正）：账号注销的编排
    # （`core/auth/deletion`）需要一个「清除该账号在记忆领域的数据」的实现，
    # 而 `core/*` 不得依赖 `modules/*`。因此实现放 `modules/memory/purge.py`、
    # **由装配处（CLI）注入**给编排——与其他领域的清除者同一种做法。
    # 邀请码与账号状态机在 `modules/accounts`（运营子命令直接调用）。
    # CLI 是运维编排点，放行它符合既有定调。
    # 该修正同时同步《项目结构设计》第 7 节与 `cli/__init__.py` 的 docstring
    # （三者此前互不一致，见 docs/TODO.md 的定调级条目）。
    #
    # `campfire.cli` 自身在列，理由与 `agent` 那一行**完全相同**：第 7 节的表把
    # `cli/*` 当作**一层**，层内文件互相引用（`__main__` 用 `operator`）不构成跨层依赖；
    # 而 `_owner_prefix` 对层根下的文件只放行到 `cli/<文件名>`，**不放行兄弟文件**，
    # 故必须显式列出。
    #
    # **为什么放行 profile**（2026-09-30，随 `modules/profile` 落地）：注销要满足
    # `AC-24`「其档案……不再存在」，因此 CLI 必须注入档案侧的 purger
    # （`modules/profile/purge.ProfileAccountPurger`），与 memory 侧同一种做法。
    # 该注入是 docs/TODO.md「`cli` 白名单与注销编排的冲突」一条明确预告的后续动作
    # （原文：「档案模块落地时须补一个 purger 并注入 CLI」）。
    "cli": {
        "campfire.cli",
        "campfire.core",
        "campfire.modules.accounts",
        "campfire.modules.library",
        "campfire.modules.memory",
        "campfire.modules.profile",
    },
}


# ---------------------------------------------------------------------------
# 基座禁项的词面落点：领域术语与产品侧引用。
#
# docs/项目结构设计.md 第 7 节 agent 行的禁项有两半：import 白名单（上面已覆盖）
# 与「出现领域术语」。第 3 节把它展开成「基座不知道自己被用在哪件事上：任何领域
# 术语（咨询、档案、案例、支持对象…）」。这一半此前只靠人工审查，下面两个常量把
# 它变成可执行断言。
# ---------------------------------------------------------------------------

DOMAIN_TERMS: tuple[str, ...] = (
    "咨询",
    "档案",
    "案例",
    "支持对象",
    "应急",
    "医疗",
    "记忆",
    "检索",
    "资料",
    "孤独症",
    "自闭症",
)
"""产品侧领域术语词表；agent 层任何一行都不得出现（注释与 docstring 同样算）。

收录判据：只收「在本仓只可能指产品概念」的词。基座自身不做检索、不存记忆、
不产资料、不面向特定人群，所以这些词出现在 agent/ 里就是在说产品侧的东西。
判定按字面做，因此与领域词同形的通用措辞会一并命中（例如「进程内记忆」）——
那种情况下改措辞，不要从词表里删词：删词会放过真正的领域泄漏。
增删方法：直接改这个元组。命中集合是与 :data:`KNOWN_DOMAIN_TERM_HITS` 精确比对的，
改动后跑测试即可，失败消息会给出实际命中位置——据它判断是该改注释，还是这个词
本就该收放（该收放就改这里，并在本 docstring 里写清理由）。
"""

KNOWN_DOMAIN_TERM_HITS: dict[tuple[str, str], int] = {
    # 已知且允许的命中，键是 (相对路径, 术语)，值是命中行数。
    # 它们不是待修缺口，只有一处合法来源：陈述禁项与归属边界本身必须把被禁的词写
    # 出来，即 agent/__init__.py 的「出现领域术语（咨询、档案、案例、支持对象…）」
    # 与 agent/context/__init__.py 的「记忆、档案、检索的语义与生命周期不归基座」。
    # agent/ 里其它任何位置出现词表里的词，都要先改掉注释，而不是往这张表里加。
    ("agent/__init__.py", "咨询"): 2,
    ("agent/__init__.py", "档案"): 2,
    ("agent/__init__.py", "案例"): 2,
    ("agent/__init__.py", "支持对象"): 2,
    ("agent/context/__init__.py", "记忆"): 2,
    ("agent/context/__init__.py", "档案"): 2,
    ("agent/context/__init__.py", "检索"): 2,
}

FORBIDDEN_DOC_REFERENCES: tuple[str, ...] = (
    "docs/技术设计/面/",
    "docs/技术设计/decisions/",
)
"""基座不得引用的产品侧文档：面的契约与产品决策记录。

基座的契约与机制理由必须自足。引用产品侧文档会把依据变成悬空引用（产品侧改名或
重写，基座的一致性依据就没了），也与第 3 节「不知道自己被用在哪件事上」相反。
基座自己的机制文档（technical-details/ 下的通用基座、压缩策略等）、仓库级设计
文档（项目结构设计、技术栈设计、TODO）与产品侧文档的反向引用不在禁列。
"""

REQUIREMENT_CODE = re.compile(r"RQ-[A-Z]{2,}-\d+")
"""产品需求编号；以它给基座的决策立论，等同于把理由外借，同样禁。"""


def _layer_of(relative: Path) -> str | None:
    """返回模块所属的层；``main.py``、``worker.py`` 等入口不属于任何层。"""
    first = relative.parts[0]
    return first if first in LAYERS else None


def _owner_prefix(relative: Path) -> str:
    """返回模块自身所属的包前缀，用于放行包内互相引用。"""
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join([SRC_MODULE_ROOT, *parts[:2]])


def _campfire_imports(path: Path) -> set[str]:
    """收集一个文件对同项目模块的绝对 import 目标。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if _is_project_module(alias.name))
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 是包内相对导入，必然同包，不需要判白名单
            if node.level == 0 and node.module and _is_project_module(node.module):
                found.add(node.module)
    return found


def _is_project_module(name: str) -> bool:
    return name == SRC_MODULE_ROOT or name.startswith(f"{SRC_MODULE_ROOT}.")


def _is_allowed(target: str, allowed: set[str]) -> bool:
    for entry in allowed:
        if target == entry or target.startswith(f"{entry}.") or entry.startswith(f"{target}."):
            return True
    return False


def _iter_layered_modules() -> list[Path]:
    return [path for path in sorted(SRC_ROOT.rglob("*.py")) if _layer_of(path.relative_to(SRC_ROOT))]


def test_every_layer_is_actually_scanned() -> None:
    """防止检查本身退化为空跑：五个层都必须有 Python 文件。"""
    layers = {_layer_of(path.relative_to(SRC_ROOT)) for path in _iter_layered_modules()}

    assert layers == set(LAYERS)


def test_layer_imports_respect_the_whitelist() -> None:
    violations: list[str] = []
    for path in _iter_layered_modules():
        relative = path.relative_to(SRC_ROOT)
        layer = _layer_of(relative)
        assert layer is not None
        allowed = ALLOWED[layer] | {_owner_prefix(relative)}
        for target in sorted(_campfire_imports(path)):
            if not _is_allowed(target, allowed):
                violations.append(f"{relative.as_posix()} 引用了白名单外的 {target}")

    assert not violations, "依赖白名单被越过：\n" + "\n".join(violations)


def test_agent_layer_has_no_domain_modules() -> None:
    """基座不得依赖 modules/tools/surfaces（第 7 节表首行）。"""
    for path in _iter_layered_modules():
        if _layer_of(path.relative_to(SRC_ROOT)) != "agent":
            continue
        for target in _campfire_imports(path):
            assert not target.startswith(("campfire.modules", "campfire.tools", "campfire.surfaces")), (
                f"基座出现了业务依赖：{path.name} -> {target}"
            )


def test_worker_entry_does_not_import_surfaces() -> None:
    """worker 入口禁止 import surfaces/*（第 7 节表末行）。"""
    imports = _campfire_imports(SRC_ROOT / "worker.py")

    assert not [target for target in imports if target.startswith("campfire.surfaces")]


def test_cli_layer_does_not_import_surfaces() -> None:
    """本地摄取入口禁止 import surfaces/*（第 7 节新增行）。"""
    cli_modules = [path for path in _iter_layered_modules() if _layer_of(path.relative_to(SRC_ROOT)) == "cli"]

    assert cli_modules, "cli 层没有任何模块，检查会空跑"

    for path in cli_modules:
        for target in _campfire_imports(path):
            assert not target.startswith("campfire.surfaces"), f"cli 越界依赖：{path.name} -> {target}"


def _iter_agent_modules() -> list[Path]:
    """agent 层的全部 Python 文件。"""
    return [path for path in _iter_layered_modules() if _layer_of(path.relative_to(SRC_ROOT)) == "agent"]


def _scan_agent_lines() -> Iterator[tuple[str, int, str]]:
    """逐行产出 (相对路径, 行号, 行内容)；两个词面检查共用它。"""
    for path in _iter_agent_modules():
        relative = path.relative_to(SRC_ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            yield relative, number, line


def _domain_terms_in_line(line: str) -> list[str]:
    """这一行命中的领域术语（按词表顺序）。"""
    return [term for term in DOMAIN_TERMS if term in line]


def _product_side_references_in_line(line: str) -> list[str]:
    """这一行引用的产品侧依据：禁列里的文档路径，或产品需求编号。"""
    found = [reference for reference in FORBIDDEN_DOC_REFERENCES if reference in line]
    found.extend(match.group(0) for match in REQUIREMENT_CODE.finditer(line))
    return found


def test_layer_term_guard_detects_its_patterns() -> None:
    """防止守门退化为空跑：两个判定函数必须真的认得出样例。"""
    assert _domain_terms_in_line("例如应急卡片直接激活指定 skill") == ["应急"]
    assert _domain_terms_in_line("本轮的业务注入项与取数失败的来源") == []

    assert _product_side_references_in_line("契约见 docs/技术设计/面/consult/HTTP与SSE契约.md") == ["docs/技术设计/面/"]
    assert _product_side_references_in_line("决策记录见 docs/技术设计/decisions/某决策.md") == [
        "docs/技术设计/decisions/"
    ]
    assert _product_side_references_in_line("代价落在首字时延上（`RQ-EMG-03`）") == ["RQ-EMG-03"]
    assert _product_side_references_in_line("参考 docs/技术设计/technical-details/通用基座.md 第 2 节") == []


def test_agent_layer_has_no_domain_terms() -> None:
    """基座不得出现领域术语；例外只有陈述禁项本身的那 4 行（第 3 节不变量）。

    命中集合与 :data:`KNOWN_DOMAIN_TERM_HITS` 精确比对，而不是 xfail：xfail(strict)
    期间新增一处领域词只会得到 XFAIL（静默通过），检查就白设了。精确比对让新增立刻
    失败，也让「已经改好但没同步改表」立刻失败（提示删除对应条目）。
    """
    modules = _iter_agent_modules()
    assert modules, "agent 层没有任何模块，检查会空跑"

    hits = [
        (relative, number, term)
        for relative, number, line in _scan_agent_lines()
        for term in _domain_terms_in_line(line)
    ]
    actual = Counter((relative, term) for relative, _, term in hits)
    known = Counter(KNOWN_DOMAIN_TERM_HITS)
    if actual == known:
        return

    added = actual - known
    removed = known - actual
    details = [
        f"{relative} 的「{term}」多出 {added[(relative, term)]} 处，该词实际命中行："
        + "、".join(str(number) for rel, number, hit_term in hits if rel == relative and hit_term == term)
        for relative, term in sorted(added)
    ]
    details.extend(
        f"已知条目 ({relative}, {term}) 命中数不符：表里 {known[(relative, term)]} 行，实际 {actual[(relative, term)]} 行"
        "（改好了就同步删掉或修改表里的条目；实际为 0 也可能是扫描失效，先核对路径）"
        for relative, term in sorted(removed)
    )
    raise AssertionError("基座出现了领域术语：\n" + "\n".join(details))


def test_agent_layer_does_not_cite_product_side_docs() -> None:
    """基座不得引用产品面的契约与产品决策记录，也不得以需求编号立论。"""
    modules = _iter_agent_modules()
    assert modules, "agent 层没有任何模块，检查会空跑"

    violations = [
        f"{relative}:{number} 引用了产品侧依据 {reference}：{line.strip()}"
        for relative, number, line in _scan_agent_lines()
        for reference in _product_side_references_in_line(line)
    ]

    assert not violations, "基座的契约与机制理由外借到了产品侧：\n" + "\n".join(violations)
