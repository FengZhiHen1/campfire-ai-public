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

不覆盖的部分（诚实声明）：表中「直接访问数据库表」只被覆盖了一半——面层 import
存储层模块（`repository` / `store` / `ledger` / `models`）与「经包取存储层成员」
（`from campfire.modules.accounts import <存储层函数>`）都由
`test_surfaces_do_not_import_storage_modules` 拦下，而在面层直接写 SQLAlchemy
语句仍拦不下；「绕过用例服务直接写表」「模块间不得互相依赖业务用例」两项同样既不是
import 关系也不是词面关系，无法由本文件证明，需要各自的用例测试或审查。该规则的
层范围与残余缺口写在 `GUARDED_LAYERS` 处。
"""

import ast
import re
from collections import Counter
from collections.abc import Iterator
from functools import lru_cache
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


# ---------------------------------------------------------------------------
# 面层不得直连存储层模块（第 5 节「不直接访问数据库表」）。
#
# 上面的白名单按前缀放行整支 `campfire.modules` / `campfire.core`：「面层经用例服务
# 取数」与「面层绕过用例服务直连仓储」在它眼里是同一种 import。这一段把后者变成
# 可执行断言，判据是模块路径的命名。
#
# 覆盖：`surfaces/*` import 别的层里名字属于存储层的模块。词表取自本仓的实际用法
# ——`repository` / `*_repository`（`accounts.session_repository`、
# `profile.repository`）、`store`（`memory.store`）、`ledger`（`memory.ledger`）、
# `models`（`accounts.models`）。改名即改约定，这里跟着改。
#
# 「模块」按事实判：候选路径必须在 `src/campfire` 下真的落在 `.py` 文件或包上。只按
# 名字字面判会把函数当模块——`modules.library.ingestion.build_vector_store` 末段以
# `_store` 结尾，而它是摄取链里的一个函数（`tools/library.py` 就 import 了它）。
#
# 判据与写法无关，这是本段的要点：同一个存储层目标有三种到达方式，三条都要红。
#
# 1. `from campfire.modules.accounts.session_repository import get_session_owner`
#    ——模块路径本身落在存储层；
# 2. `from campfire.modules.accounts import session_repository`
#    ——模块路径看着是包，被引入的名字才是存储层模块；
# 3. `from campfire.modules.accounts import delete_session_owners_for_account`
#    ——包级名字来自哪一层，光看这行看不出来，要回到该包的 `__init__.py` 解出它的
#    定义模块（`from <模块> import <名字>`）才判得了。
#
# 第 3 条覆盖包级再导出这一层：存储层函数一旦被登记进包级 `__all__`，同一处穿透就只剩
# 这个写法能过；而登记被撤掉之后，照旧写这行的人仍然是在直连存储层（运行时
# ImportError）。两种成因都要判红，判据取定义模块而不是导出面——导出面会变，名字定义
# 在哪一层不会变。解不出定义模块的名字不判（不猜），否则假红会逼后来人放宽规则。
# ---------------------------------------------------------------------------

GUARDED_LAYERS: tuple[str, ...] = ("surfaces",)
"""受本规则约束的层。

只列 `surfaces`：`tools/` 与 `cli/` 里现有同类穿透（分别 import 了 `modules.*` 的
`repository` / `store` / `models`），把它们纳入要先修掉那些存量——那是一次独立的
改动，不是本规则的附带结果。另有一层理由：「经包取成员」这条会命中 `models` 里的
数据形状（`tools/profile.py` 从 `modules.profile` 取 `DOMAINS` 与
`MAX_DISPLAY_NAME_LENGTH` 做工具入参校验），纳入 tools 会要求它们既不能经包取、也
不能直连模块——没有合规写法可退，须先裁定「models 算不算存储层」。
"""

_INTERNAL_MODULE_NAMES: frozenset[str] = frozenset({"store", "ledger", "models"})
"""按路径段精确比对的存储层模块名。"""

_INTERNAL_MODULE_SUFFIXES: tuple[str, ...] = ("_store", "_ledger", "_models")
"""带前缀的同义模块名（`sdk_models` 这类）。"""

_INTERNAL_MODULE_SUBSTRING = "repository"
"""含此子串的路径段一律算存储层（`repository`、`session_repository`、`repositories`）。"""


def _is_internal_implementation(target: str) -> bool:
    """该 import 目标是否落在存储层模块上。

    逐段比对而不是只看最后一段：`campfire.modules.x.repository.helpers` 这种更深的
    路径同样属于存储层。开头两段（`campfire` 与层名）跳过，免得层名之类的位置撞上词表。
    """
    for segment in target.split(".")[2:]:
        lowered = segment.lower()
        if _INTERNAL_MODULE_SUBSTRING in lowered:
            return True
        if lowered in _INTERNAL_MODULE_NAMES or lowered.endswith(_INTERNAL_MODULE_SUFFIXES):
            return True
    return False


def _is_campfire_module(target: str) -> bool:
    """该 import 路径在本仓真的落在模块上（`.py` 文件或包）。

    用来把「模块名」与同名的函数、常量分开：`modules.library.ingestion.build_vector_store`
    的末段以 `_store` 结尾，但它是摄取链里的一个函数，不是存储层模块——只看字面会把它
    当成穿透。module 路径本身（`...repository`）与展开出来的成员路径都过这一关。
    """
    path = SRC_ROOT.joinpath(*target.split(".")[1:])
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _package_init_path(target: str) -> Path | None:
    """target 指向本仓的一个包时返回其 `__init__.py`，否则 None。

    只有包需要「成员解析」：`from <模块> import <名字>` 的模块路径本身已由
    :func:`_is_campfire_module` 与 :func:`_is_internal_implementation` 判过。
    """
    init = SRC_ROOT.joinpath(*target.split(".")[1:]) / "__init__.py"
    return init if init.is_file() else None


@lru_cache(maxsize=None)
def _package_reexports(package: str) -> dict[str, str]:
    """包级名字 → 再导出它的来源模块（键是包级可见的名字）。

    包级可见性就是 `__init__.py` 里那些 `from <模块> import <名字>` 造出来的；沿它们
    解析，才知道 `from campfire.modules.accounts import X` 里的 X 到底来自哪一层。
    只记来源模块、不记 `模块.名字`：判据是「定义在哪一层」，把名字并进路径会让一个
    恰好叫 `*_repository` 的用例层函数被误判。
    """
    init = _package_init_path(package)
    if init is None:
        return {}
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(init.read_text(encoding="utf-8"), filename=str(init))):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            # `from .x import y` 在包的 `__init__.py` 里指本包（level=1 即本包）
            base = package
            for _ in range(node.level - 1):
                base = base.rsplit(".", 1)[0]
            module = f"{base}.{node.module}" if node.module else base
        else:
            if not node.module or not _is_project_module(node.module):
                continue
            module = node.module
        for alias in node.names:
            if alias.name != "*":
                found.setdefault(alias.asname or alias.name, module)
    return found


def _defined_names(node: ast.stmt) -> list[str]:
    """模块顶层一条语句定义的名字（函数、类、赋值与注解赋值）。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


@lru_cache(maxsize=None)
def _package_members(package: str) -> dict[str, str]:
    """包内子模块顶层定义的名字 → 定义它的模块（同名取路径序首个，保证确定性）。

    为什么不止看再导出：包级 `__all__` 会变，而「这个名字定义在存储层」不会变。
    再导出被撤掉之后照旧写 `from <包> import <存储层名字>` 仍然是在直连存储层
    （那行在运行期 ImportError），故仍判红——判据是定义位置，不是导出面。
    """
    init = _package_init_path(package)
    if init is None:
        return {}
    found: dict[str, str] = {}
    for path in sorted(init.parent.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        module = ".".join([SRC_MODULE_ROOT, *path.relative_to(SRC_ROOT).with_suffix("").parts])
        for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
            for name in _defined_names(node):
                found.setdefault(name, module)
    return found


def _package_member_module(package: str, name: str) -> str | None:
    """经包取成员时该成员的定义模块；解不出返回 None（不猜，不判）。"""
    return _package_reexports(package).get(name) or _package_members(package).get(name)


def _package_member_imports_in_source(source: str) -> set[tuple[str, str]]:
    """源码里「经包取成员」的 import，逐项为 `(包路径, 成员名)`。

    与 :func:`_module_paths_in_source` 互补：那条管 `from <模块> import <名字>`，这条管
    `from <包> import <名字>`——同一个存储层目标的两种写法都要看得见。
    """
    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        if not _is_project_module(node.module) or _package_init_path(node.module) is None:
            continue
        found.update((node.module, alias.name) for alias in node.names if alias.name != "*")
    return found


def _module_paths_in_source(source: str) -> set[str]:
    """一段源码可能触碰的同项目模块路径。

    比 :func:`_campfire_imports` 多展开一层：`from campfire.modules.accounts import
    session_repository` 的模块路径是 `campfire.modules.accounts`（看着像包级取用），
    而被引入的 `session_repository` 正是要盯的存储层模块——不展开就会漏掉这种写法。
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if _is_project_module(alias.name))
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 是包内相对导入，必然同包，不构成跨模块引用
            if node.level or not node.module or not _is_project_module(node.module):
                continue
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _storage_violations_in_source(source: str, relative: Path, own_prefix: str) -> list[str]:
    """一段源码里到达存储层的写法（两种），返回可读的违规描述。

    own_prefix 是这段源码自身所在层的前缀：同层文件互相引用不算跨模块
    （与白名单的 `_owner_prefix` 同一口径）。
    """
    violations: list[str] = []
    for target in sorted(_module_paths_in_source(source)):
        if target == own_prefix or target.startswith(f"{own_prefix}."):
            continue
        if _is_campfire_module(target) and _is_internal_implementation(target):
            violations.append(f"{relative.as_posix()} 直连了存储层模块 {target}")
    for package, name in sorted(_package_member_imports_in_source(source)):
        if package == own_prefix or package.startswith(f"{own_prefix}."):
            continue
        module = _package_member_module(package, name)
        if module is not None and _is_internal_implementation(module):
            violations.append(f"{relative.as_posix()} 经包 {package} 取到了存储层模块 {module} 的成员 {name}")
    return violations


def _storage_import_violations() -> list[str]:
    """受约束层里直连存储层模块或经包取存储层成员的 import。"""
    violations: list[str] = []
    for path in _iter_layered_modules():
        relative = path.relative_to(SRC_ROOT)
        layer = _layer_of(relative)
        if layer not in GUARDED_LAYERS:
            continue
        own_prefix = f"{SRC_MODULE_ROOT}.{layer}"
        violations.extend(_storage_violations_in_source(path.read_text(encoding="utf-8"), relative, own_prefix))
    return violations


def test_storage_import_guard_detects_its_patterns() -> None:
    """防止守门退化为空跑：判定与收集都必须真的认得出样例。"""
    assert _is_internal_implementation("campfire.modules.accounts.session_repository")
    assert _is_internal_implementation("campfire.modules.profile.repository")
    assert _is_internal_implementation("campfire.modules.memory.store")
    assert _is_internal_implementation("campfire.modules.memory.ledger")
    assert _is_internal_implementation("campfire.modules.accounts.models")
    # 合法的目标不得命中：假红会逼着后来人放宽规则
    assert not _is_internal_implementation("campfire.modules.accounts")
    assert not _is_internal_implementation("campfire.modules.accounts.sessions")
    assert not _is_internal_implementation("campfire.modules.profile.service")
    assert not _is_internal_implementation("campfire.core.config")

    aliased = _module_paths_in_source("from campfire.modules.accounts import session_repository\n")
    assert "campfire.modules.accounts.session_repository" in aliased
    assert any(_is_campfire_module(target) and _is_internal_implementation(target) for target in aliased)

    legal = _module_paths_in_source("from campfire.modules.accounts import register_session\n")
    assert not [target for target in legal if _is_internal_implementation(target)]

    # 模块判定按事实：真模块认得出，同名的函数不算穿透
    assert _is_campfire_module("campfire.modules.accounts.session_repository")
    assert _is_campfire_module("campfire.modules.profile.repository")
    assert _is_campfire_module("campfire.modules.accounts")
    assert not _is_campfire_module("campfire.modules.library.ingestion.build_vector_store")
    assert not _is_campfire_module("campfire.modules.profile.repository.ITEMS_DEFAULT_LIMIT")


def test_storage_member_guard_detects_its_patterns() -> None:
    """防止「经包取存储层成员」这一路退化为空跑：解析、收集与整条判定都要认得出样例。

    与 :func:`test_storage_import_guard_detects_its_patterns` 分开写，是为了让
    「模块写法」与「成员写法」各有自己的反空跑断言——一路失效时另一路不会替它顶绿。
    """
    # 解析要认得出两种成因：包确实再导出了存储层名字，或再导出撤掉后名字仍定义在存储层
    assert _package_member_module("campfire.modules.accounts", "delete_session_owners_for_account") == (
        "campfire.modules.accounts.session_repository"
    )
    assert _is_internal_implementation(_package_member_module("campfire.modules.accounts", "get_session_owner") or "")
    # 数据形状按同一判据（与「直连 `accounts.models` 已红」保持一致，不因写法改变结论）
    assert (
        _package_member_module("campfire.modules.accounts", "INVITE_CODE_TTL_DAYS")
        == "campfire.modules.accounts.models"
    )

    # 合法目标不得命中：面层真正在用的用例层成员
    assert (
        _package_member_module("campfire.modules.accounts", "discard_session_owner")
        == "campfire.modules.accounts.sessions"
    )
    assert _package_member_module("campfire.modules.profile", "list_objects") == "campfire.modules.profile.service"
    assert not _is_internal_implementation(
        _package_member_module("campfire.modules.profile", "read_session_bindings") or ""
    )
    # 解不出的名字不猜（`core/db` 的成员定义在包内而非子模块，属这一档）
    assert _package_member_module("campfire.modules.accounts", "no_such_member_here") is None

    # 收集器只收「经包取成员」这一种；模块写法归另一条通道
    assert _package_member_imports_in_source(
        "from campfire.modules.accounts import delete_session_owners_for_account\n"
    ) == {("campfire.modules.accounts", "delete_session_owners_for_account")}
    assert (
        _package_member_imports_in_source(
            "from campfire.modules.accounts.session_repository import get_session_owner\n"
        )
        == set()
    )

    # 整条判定：这种写法真的产出违规（合成源码，不动真实文件）
    synthetic = _storage_violations_in_source(
        "from campfire.modules.accounts import delete_session_owners_for_account\n",
        Path("surfaces/consult/probe.py"),
        "campfire.surfaces",
    )
    assert len(synthetic) == 1
    assert "delete_session_owners_for_account" in synthetic[0]
    assert "campfire.modules.accounts.session_repository" in synthetic[0]
    # 同层包互相引用不算跨模块（与模块写法同一口径）
    assert (
        _storage_violations_in_source(
            "from campfire.surfaces.consult import assembly\n",
            Path("surfaces/consult/probe.py"),
            "campfire.surfaces",
        )
        == []
    )

    # 受约束层真的存在「经包取成员」的 import，否则上面那条断言只是在空集合上成立
    guarded = [path for path in _iter_layered_modules() if _layer_of(path.relative_to(SRC_ROOT)) in GUARDED_LAYERS]
    real = {entry for path in guarded for entry in _package_member_imports_in_source(path.read_text(encoding="utf-8"))}
    assert real, "受约束层没有解析出任何「经包取成员」的 import，这一路守门会空跑"


def test_surfaces_do_not_import_storage_modules() -> None:
    """面层不得 import 其它模块的存储层模块（第 5 节「不直接访问数据库表」）。

    取数一律经用例层：调用 `modules/*` 的用例模块，或它所在包的包级导出。
    """
    guarded = [path for path in _iter_layered_modules() if _layer_of(path.relative_to(SRC_ROOT)) in GUARDED_LAYERS]

    assert guarded, "受约束的层没有任何模块，检查会空跑"

    # 收集器在真实文件上必须看得见东西，否则下面那条断言只是在空集合上成立
    scanned = {target for path in guarded for target in _module_paths_in_source(path.read_text(encoding="utf-8"))}
    assert scanned, "受约束层的 import 一个都没解析出来，守门会空跑"

    violations = _storage_import_violations()

    assert not violations, "面层直连了存储层模块，应改经用例层取数：\n" + "\n".join(violations)


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
