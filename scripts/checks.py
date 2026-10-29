"""按影响面选择检查：`quick`（改动相关）与 `full`（完整确定性门禁）。

为什么要有这个脚本

完整门禁（ruff/mypy/设计文档/迁移/pytest/lint/vitest/build）是**发布前**的判据，
但每改一行就全跑一遍，代价落在最没信息量的地方：没碰前端的改动也等前端的构建。
`quick` 按「这次到底动了什么」选子集，`full` 保持完整——两者共用同一份命令清单，
不产生第二份真源。

两条硬纪律（都是「看起来绿了但什么都没验」的防口）

1. **未知路径不能静默当成文档**：路径落在已知类别之外时，`quick` 报 `uncovered` 并
   以退出码 2 结束。它不会因为「没有对应的检查」就当作通过——那正是最坏的一种绿。
2. **选不出 pytest 范围也不许静默**：改动落在源码上而无法机械映射到相关测试文件时，
   `quick` 停下来要求显式 `--pytest <文件>`，而不是跳过测试报绿。

用法：

    uv run python scripts/checks.py quick --base dev            # 只看本次改动
    uv run python scripts/checks.py quick --base dev --dry-run  # 只打印将要跑的命令
    uv run python scripts/checks.py quick --pytest apps/api/tests/test_x.py::test_y
    uv run python scripts/checks.py full                        # 完整确定性门禁
    uv run python scripts/checks.py full --dry-run

`full` 与 CI 的差异只有两处，都是**去重**、不是降级：

- 前端不单独跑 `typecheck`：`build` 的脚本本身就是
  `sync-tokens → tsc --noEmit → vite build → 契约类名检查`，单独再跑一次 tsc 只是耗时。
- pytest 显式带 `-m "not live_model"`：真正调用外部模型供应商的用例必须显式开启
  （`--live-model` 或 `CAMPFIRE_LIVE_MODEL=1`），见 `apps/api/tests/conftest.py`。
  这里写出来是为了让「跑了什么」在命令行上可见，而不是靠 conftest 的默认值。

退出码：0 通过；1 有检查失败；2 范围无法确定/有未覆盖路径（需人工确认后重跑）。
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: 仓库根：本文件位于 `<root>/scripts/`，因此不依赖当前工作目录。
ROOT = Path(__file__).resolve().parents[1]

#: 应用测试目录（`pyproject.toml` 的 `testpaths` 之一）。
API_TESTS = Path("apps/api/tests")

#: 仓库级工具测试目录（`scripts/worktree.py`、`scripts/checks.py` 的针对性测试）。
SCRIPT_TESTS = Path("scripts/tests")

#: CareBench 评测工具根目录（仓库相对，带结尾斜杠便于前缀判断）。
EVAL_ROOT = "evaluation/carebench/"

#: CareBench 工具自己的测试目录（`pyproject.toml` 的 `testpaths` 之一：全部是
#: 确定性替身，不联网、不连库、不调模型）。
EVAL_TESTS = Path("evaluation/carebench/tests")

#: 排除真实模型用例的表达式（与 conftest 的开关配套，见模块 docstring）。
LIVE_MODEL_EXPR = "not live_model"

#: 类别名（报告与选检查都用它们）。
CAT_PY_SRC = "python-src"
CAT_PY_TESTS = "python-tests"
CAT_PY_CONFIG = "python-config"
CAT_SCRIPTS = "scripts"
CAT_SCRIPT_TESTS = "script-tests"
CAT_EVAL_SRC = "eval-src"
CAT_EVAL_TESTS = "eval-tests"
CAT_EVAL_DATA = "eval-data"
CAT_WEB = "web"
CAT_WEB_CONFIG = "web-config"
CAT_DOCS = "docs"
CAT_MIGRATIONS = "migrations"
CAT_CI = "ci"
CAT_OPS = "ops"
CAT_UNKNOWN = "unknown"

#: `apps/api` 的 Python 改动面：ruff + mypy + 定向 pytest（mypy 只配这两个路径）。
PYTHON_CATEGORIES = frozenset({CAT_PY_SRC, CAT_PY_TESTS, CAT_SCRIPTS, CAT_SCRIPT_TESTS})

#: CareBench 工具的改动面：ruff（只对 `.py`）+ 工具自身的确定性 pytest 树。
#: mypy 只配 `apps/api/{src,tests}`，对 `evaluation/` 不做类型断言，因此这里不排它。
EVAL_CATEGORIES = frozenset({CAT_EVAL_SRC, CAT_EVAL_TESTS, CAT_EVAL_DATA})

#: 没有任何确定性检查覆盖的类别（`quick` 遇到即阻塞）。
UNCOVERED_CATEGORIES = frozenset({CAT_UNKNOWN, CAT_CI, CAT_OPS})

#: 前端样式契约：`apps/web` 的 `build` 第一步 `sync-tokens` 逐字节读它，判据只有 build 把得住。
WEB_CONTRACT_PATHS = frozenset({"docs/design/tokens.css"})

#: 测试基础设施：改它等于改「所有用例怎么跑」，不能当成可跑的 pytest 目标
#: （`conftest.py` 零用例，单独跑是退出码 5）。
TEST_INFRA_NAMES = frozenset({"conftest.py"})

#: 测试包标记（`from .conftest import` 依赖它），同 :data:`TEST_INFRA_NAMES`。
TEST_INFRA_PATHS = frozenset({"apps/api/tests/__init__.py"})

#: 源码路径里的「容器层」词：它们只是目录，不携带「哪个模块」的信息。
_CONTAINER_PARTS = frozenset({"campfire", "modules", "core", "src", "surfaces", "agent", "tools", "cli"})


@dataclass(frozen=True)
class Step:
    """一条要执行的检查命令。"""

    key: str
    title: str
    argv: tuple[str, ...]

    def display(self) -> str:
        """给报告与 `--dry-run` 用的命令行文本（含空格的参数加引号，便于直接复制粘贴）。"""
        return " ".join(shlex.quote(part) for part in self.argv)


def _run(argv: list[str]) -> str:
    """跑一条 git 命令并返回 stdout。

    Raises:
        SystemExit: git 失败（例如基线分支不存在）——直接结束，不猜。
    """
    proc = subprocess.run(["git", *argv], cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise SystemExit(f"git {' '.join(argv)} 失败：{detail}")
    return proc.stdout


def _null_separated(*args: str) -> list[str]:
    """跑一条 git 命令并按 NUL 切分输出（`-z` 模式）。

    为什么必须用 `-z`（2026-10-29 实测）：默认输出会给**非 ASCII 路径加引号并转义**
    （`"docs/\346\226\207\346\241\243/..."`），也会把含空格的路径加引号。于是
    `docs/需求/…` 这类中文文档会被归成 `unknown`，`quick` 直接阻塞——那是本工具自己
    造的假失败。`-z` 输出的路径不做任何转义，切分是唯一可靠的解析方式。
    """
    return [part for part in _run(list(args)).split("\0") if part]


def changed_paths(base: str) -> list[str]:
    """本分支相对 `base` 的改动路径 + 未提交改动（含未跟踪文件）。

    用三点比较 `base...HEAD`：只算「本分支引入的」改动，不把基线分支自己的新提交
    当成自己的改动（那会让每个人都在跑别人的活）。

    重命名按**两边都算**处理：

    - 已提交部分用 `--no-renames`，git 会把重命名拆成「删一个 + 加一个」；
    - 未提交部分 `git status -z` 对 `R`/`C` 条目会额外输出一行原路径（`-z` 下顺序是
      「新路径后跟原路径」），两者都收进来。

    只收新路径会让「删掉的那个文件」从影响面里消失——删掉的源码/测试同样是改动。

    Args:
        base: 基线分支名（如 `dev`）。

    Returns:
        去重后的仓库相对路径列表（顺序稳定：已提交在前，未提交在后）。
    """
    committed = _null_separated("diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD")

    uncommitted: list[str] = []
    tokens = _null_separated("status", "--porcelain=v1", "-z", "--untracked-files=all")
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        status = entry[:2]
        uncommitted.append(entry[3:])
        if "R" in status or "C" in status:
            # 重命名/复制：`-z` 下紧随其后的那一条是原路径。
            index += 1
            if index < len(tokens):
                uncommitted.append(tokens[index])
        index += 1

    seen: set[str] = set()
    ordered: list[str] = []
    for path in [*committed, *uncommitted]:
        if path and path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def classify(path: str) -> str:
    """把仓库相对路径归类。

    未知路径返回 :data:`CAT_UNKNOWN`——**这不是「当作文档」**，调用方必须把它报出来
    并阻塞（见模块 docstring 第 1 条纪律）。

    Args:
        path: 仓库相对路径。

    Returns:
        类别名（`CAT_*`）。
    """
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):  # 不能用 lstrip("./")：它会把 `.github/` 的点也吃掉
        normalized = normalized[2:]
    name = normalized.rsplit("/", 1)[-1]

    if normalized.startswith("apps/api/src/"):
        return CAT_PY_SRC
    if normalized.startswith("apps/api/tests/"):
        return CAT_PY_TESTS
    if normalized.startswith("apps/api/alembic/") or normalized in {"alembic.ini", "apps/api/alembic.ini"}:
        return CAT_MIGRATIONS
    if name in {"package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"}:
        # 前端工程配置（根与 apps/web 各有一份）：改动面比 src 更大，必须连构建一起跑。
        return CAT_WEB_CONFIG
    if normalized.startswith("apps/web/src/") or normalized.startswith("apps/web/tests/"):
        return CAT_WEB
    if normalized.startswith("apps/web/"):
        # 前端工程配置（vite/tsconfig/构建脚本）：改动面比 src 更大。
        return CAT_WEB_CONFIG
    if normalized.startswith("scripts/tests/"):
        # 工具自己的测试与「工具实现」分开：改测试就要跑测试（见 `pytest_files_for`），
        # 归成 `scripts` 会让「只改了测试」的改动选不出任何 pytest 目标而报绿。
        return CAT_SCRIPT_TESTS
    if normalized.startswith("scripts/"):
        return CAT_SCRIPTS
    if normalized.startswith(EVAL_ROOT):
        # CareBench 评测工具（2026-10-29 补）：此前整棵树落到 `unknown`，改一行评测
        # 脚本就让 `quick` 阻塞。这里按「能跑的检查」拆三类——源码与测试走 ruff，
        # 案例/快照/样例配置这类非 Python 数据没有独立 linter，但它们正是工具自身
        # 用例的输入（`test_cases` / `test_knowledge_content` / 冻结与核验用例），
        # 所以同样由该工具的确定性 pytest 校验。文档（README、protocol/）仍归文档，
        # 由设计文档一致性检查把关，不在评测工具这条线上吞掉。
        if name.endswith(".md"):
            return CAT_DOCS
        if normalized.startswith(f"{EVAL_ROOT}tests/"):
            return CAT_EVAL_TESTS
        if name.endswith(".py"):
            return CAT_EVAL_SRC
        return CAT_EVAL_DATA
    if name in {"pyproject.toml", "uv.lock"}:
        # 按文件名判定：`apps/api/pyproject.toml` 也是依赖清单，落到 unknown 会假阻塞。
        return CAT_PY_CONFIG
    if normalized.startswith(".github/"):
        return CAT_CI
    if normalized.startswith("infrastructure/") or name.startswith("docker-compose") or name == "Dockerfile":
        return CAT_OPS
    if normalized.startswith("docs/") or name in {"README.md", "AGENTS.md"} or normalized.startswith("archive/README"):
        return CAT_DOCS
    return CAT_UNKNOWN


def _area_tokens(src_path: str) -> list[str]:
    """从一个 `apps/api/src` 路径里抽出可用于匹配测试文件的关键词（按特异性排序）。

    例：`apps/api/src/campfire/modules/library/routes.py`
    → `["library", "routes"]`（`campfire`/`modules` 这类容器层词不携带模块信息，跳过；
    文件名词放最后，因为 `routes.py`/`store.py` 这种名字太泛）。

    Args:
        src_path: `apps/api/src/` 下的路径。

    Returns:
        关键词列表（可能为空）。
    """
    relative = src_path.split("apps/api/src/", 1)[-1]
    parts = [part for part in relative.split("/") if part]
    tokens: list[str] = []
    for part in parts[:-1]:
        if part in _CONTAINER_PARTS or part.startswith("."):
            continue
        tokens.append(part)
    stem = parts[-1].removesuffix(".py") if parts else ""
    if stem and stem != "__init__" and stem not in _CONTAINER_PARTS:
        tokens.append(stem)
    return tokens


def existing_paths(paths: list[str]) -> list[str]:
    """只留下**当前仍存在**的路径（删除的文件不能交给 ruff/pytest 当参数）。

    删除也是改动：它参与归类与影响面判断（删掉源码照样要跑相关检查），
    但不能出现在「跑这些文件」的参数里——pytest 对不存在的路径直接报错退出 4，
    ruff 报 E902，两者都会把「删了个文件」变成一条看起来像工具坏了的红。
    """
    return [path for path in paths if (ROOT / path).is_file()]


def is_test_infrastructure(path: str) -> bool:
    """该路径是否属于「测试基础设施」（改它会影响全部用例的运行方式）。

    Args:
        path: 仓库相对路径。

    Returns:
        是否属于测试基础设施。
    """
    normalized = path.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] in TEST_INFRA_NAMES or normalized in TEST_INFRA_PATHS


def pytest_files_for(paths: list[str], existing_tests: list[Path]) -> list[str] | None:
    """从改动路径推出要跑的 pytest 文件；推不出时返回 `None`（调用方必须阻塞）。

    规则（刻意保守——宁可让调用方显式 `--pytest`，也不假装「跑过了相关测试」）：

    1. 改到测试文件本身（应用测试、工具测试或 CareBench 测试）→ 直接跑它；已被删除的不跑
       （只计入影响面），测试基础设施（`conftest.py`、tests 包标记）也不跑，
       由调用方升级为全量。
    2. 改到 `scripts/*.py` → 跑 `scripts/tests/test_<stem>*.py`（若存在）。
    3. 改到 CareBench 的源码或数据（案例、快照、样例配置）→ 跑 `EVAL_TESTS` 整棵树：
       该工具的用例跨文件互相校验（案例 ↔ 冻结 ↔ 核验），按文件名猜单个目标容易漏判，
       而整棵测试树是确定性的、几十条、秒级。
    4. 改到 `apps/api` 源码 → 用路径里的**第一个**非容器层词去匹配 `test_<词>_*.py`；
       匹配不到再退到文件名（如 `pending_write` → `test_pending_write_*.py`）；
       仍匹配不到 → `None`。

    规则 1 与规则 3 可以同时命中（源码 + 该工具某个既有测试一起改）：此时目录已经覆盖
    那个子文件，返回值按 :func:`_drop_covered_by_selected_dirs` 归一化，只留目录。

    Args:
        paths: 改动路径（仓库相对）。可以含已被删除的路径：它只影响分类，
            不会成为「要跑的文件」。
        existing_tests: 现有的测试文件路径列表（用于匹配）。

    Returns:
        选中的测试文件（仓库相对路径，已排序去重）；无法确定时 `None`。
    """
    by_name = {path.name: path for path in existing_tests}
    selected: set[str] = set()
    src_changed: list[str] = []
    unresolved = False
    alive = set(existing_paths(paths))
    eval_tests_path = EVAL_TESTS.as_posix()

    for path in paths:
        category = classify(path)
        if category in {CAT_PY_TESTS, CAT_SCRIPT_TESTS, CAT_EVAL_TESTS}:
            # 改到测试自己 → 跑它（删除的测试没有可跑的目标，跳过即可）。
            # 测试基础设施不在此列：它自己零用例（退出码 5），由 `quick_plan` 升级为全量。
            if path in alive and not is_test_infrastructure(path):
                selected.add(path)
        elif category in {CAT_EVAL_SRC, CAT_EVAL_DATA}:
            # 目标是一个目录：删除/新增单个文件都不会把它变成不存在的路径（pytest 对
            # 不存在的路径退出码 4）。目录缺失是仓库缺陷，返回 `None` 让调用方阻塞，
            # 而不是报「没有测试要跑」。
            if (ROOT / EVAL_TESTS).is_dir():
                selected.add(eval_tests_path)
            else:
                unresolved = True
        elif category == CAT_SCRIPTS and path.endswith(".py"):
            stem = path.rsplit("/", 1)[-1].removesuffix(".py")
            matches = sorted(name for name in by_name if name.startswith(f"test_{stem}"))
            selected.update(str(by_name[name]) for name in matches)
        elif category == CAT_PY_SRC and path.endswith(".py"):
            src_changed.append(path)

    for path in src_changed:
        found: list[str] = []
        for token in _area_tokens(path):
            found = sorted(str(test) for test in existing_tests if test.name.startswith(f"test_{token}_"))
            if not found:
                found = sorted(str(test) for test in existing_tests if test.name == f"test_{token}.py")
            if found:
                break
            found = sorted(str(test) for test in existing_tests if token in test.name)
            if found:
                break
        if not found:
            unresolved = True
        selected.update(found)

    if unresolved:
        return None
    return _drop_covered_by_selected_dirs(sorted(selected))


def _drop_covered_by_selected_dirs(selected: list[str]) -> list[str]:
    """去掉被已选目录覆盖的子路径，让每个目标只出现一次。

    `pytest 目录 目录/文件` 实测**不会**重复收集（pytest 9.0.3 按 nodeid 去重，
    `evaluation/carebench/tests` 与 `.../tests/test_verify.py` 同时传入，收集数仍是
    125 = 125）。归一化的理由不是「会跑两遍」，而是：计划与报告不该印出两个目标，
    而且「子文件确实被目录覆盖」这件事要由我们保证，不能靠 pytest 的内部去重——那是
    没被本仓断言过的行为，换版本就没有保证。

    Args:
        selected: 已选目标（仓库相对路径，可含目录）。

    Returns:
        去掉「父目录已被选中」的条目后的列表（保持原顺序）。
    """
    directories = [path for path in selected if (ROOT / path).is_dir()]
    if not directories:
        return selected
    return [
        path
        for path in selected
        if not any(path != directory and path.startswith(f"{directory.rstrip('/')}/") for directory in directories)
    ]


def existing_test_files() -> list[Path]:
    """收集现有测试文件（应用测试树 + 仓库级工具测试树）。

    CareBench 测试树刻意不在这里：它不按文件名映射（见 `pytest_files_for` 规则 3），
    混进来只会让 `apps/api` 源码的按名匹配多出无关命中。
    """
    files: list[Path] = []
    for tree in (API_TESTS, SCRIPT_TESTS):
        directory = ROOT / tree
        if directory.is_dir():
            files.extend(path.relative_to(ROOT) for path in sorted(directory.rglob("test_*.py")))
    return files


def _ruff_step(paths: list[str]) -> list[Step]:
    """ruff check + format 检查；改动文件多时退回整个仓库（省命令行长度）。"""
    targets = paths if 0 < len(paths) <= 40 else ["."]
    return [
        Step(key="ruff", title="ruff check", argv=("uv", "run", "ruff", "check", *targets)),
        Step(key="ruff-format", title="ruff format --check", argv=("uv", "run", "ruff", "format", "--check", *targets)),
    ]


def quick_plan(base: str, pytest_override: list[str] | None) -> tuple[list[Step], list[str], list[str]]:
    """生成 `quick` 的计划。

    Args:
        base: 基线分支。
        pytest_override: 显式指定的 pytest 目标（给了就完全按它跑）。

    Returns:
        `(steps, report_lines, problems)`：`problems` 非空表示范围无法确定，
        调用方应阻塞而不是跑半套。
    """
    paths = changed_paths(base)
    steps: list[Step] = []
    report: list[str] = []
    problems: list[str] = []

    if not paths:
        report.append("本次改动为空（相对基线无差异、工作区干净）：没有需要跑的检查")
        return steps, report, problems

    categories: dict[str, list[str]] = {}
    for path in paths:
        categories.setdefault(classify(path), []).append(path)
    report.append(
        f"改动 {len(paths)} 个文件，类别："
        + "、".join(f"{cat}({len(items)})" for cat, items in sorted(categories.items()))
    )

    covered = set(categories)
    uncovered = sorted(covered & UNCOVERED_CATEGORIES)
    if uncovered:
        detail = "；".join(f"{cat}: {', '.join(categories[cat][:5])}" for cat in uncovered)
        problems.append(
            f"以下路径没有对应的确定性检查：{detail}——"
            "本脚本不把它当成「无需检查」；请人工确认后加 --accept-unchecked，或跑 full"
        )

    live_paths = existing_paths(paths)
    python_touched = bool(covered & PYTHON_CATEGORIES)
    eval_touched = bool(covered & EVAL_CATEGORIES)
    py_config_touched = CAT_PY_CONFIG in covered
    mypy_step = Step(
        key="mypy",
        title="mypy（src + tests 必须一起传）",
        argv=("uv", "run", "mypy", "apps/api/src/campfire", "apps/api/tests"),
    )
    full_pytest_step = Step(
        key="pytest-full",
        title=f"pytest（全量，排除 {LIVE_MODEL_EXPR.split()[-1]}）",
        argv=("uv", "run", "pytest", "-m", LIVE_MODEL_EXPR),
    )

    if python_touched or py_config_touched:
        ruff_targets = [path for path in live_paths if path.endswith(".py")]
        steps.extend(_ruff_step(ruff_targets or ["."]))
        # mypy 不能按文件跑：分开跑时 `apps.api.tests.*` 的绝对导入会让它报
        # 「Source file found twice under different module names」并整体中止（伪装成全绿）。
        steps.append(mypy_step)
        if py_config_touched and not python_touched:
            # 只动了 pyproject.toml / uv.lock（2026-10-29 修）：依赖与 pytest/ruff/mypy 的
            # 配置都在这个文件里，改错会立刻影响**全部**检查，因此不能只跑改动文件——
            # 必须过 lint、mypy 与完整 pytest。此前这里只跑了 ruff，等于把「锁文件升级
            # 后全套测试还绿吗」这件事交给发布前那一刻。
            #
            # 全量 pytest 在下方按 `needs_full_pytest` 统一排一次（不重复排）。
            report.append("配置改动（pyproject.toml / uv.lock）：跑 lint + mypy + 全量 pytest")
    elif eval_touched:
        # CareBench 工具（2026-10-29 补）：ruff 覆盖 `evaluation/`（它不在 ruff 的 exclude
        # 里），评测源码与测试拿同一份 lint 判据。纯数据改动（案例/快照/样例配置）没有
        # 可 lint 的对象，只排该工具的确定性 pytest；mypy 只配 `apps/api`，对这里不做断言。
        #
        # 与 `apps/api` 的 Python 改动同时出现时走上面那条分支：ruff 目标里已包含评测的
        # `.py`，一条 ruff 步骤覆盖两处，不重复排。
        eval_py = [path for path in live_paths if path.endswith(".py")]
        if eval_py:
            steps.extend(_ruff_step(eval_py))

    if CAT_DOCS in covered:
        steps.append(
            Step(
                key="design-docs",
                title="设计文档一致性",
                argv=("uv", "run", "python", "scripts/check_design_docs.py"),
            )
        )

    # 迁移门禁的触发面比「改了 alembic/」更宽：ORM 模型与数据库引擎定义改了同样会漂移。
    model_or_db_touched = any(
        path.endswith("models.py") or path.startswith("apps/api/src/campfire/core/db") for path in paths
    )
    if CAT_MIGRATIONS in covered or model_or_db_touched:
        steps.append(
            Step(
                key="alembic",
                title="迁移与模型是否漂移（需要本机 PostgreSQL 已升级到 head）",
                argv=("uv", "run", "alembic", "check"),
            )
        )
        if model_or_db_touched and CAT_MIGRATIONS not in covered:
            report.append("改了 ORM 模型/引擎定义：一并跑迁移漂移检查（alembic check）")

    # 测试基础设施（conftest/包标记）影响整棵测试树，按 `testing.md` §7 升级为全量 pytest。
    test_infra_touched = any(is_test_infrastructure(path) for path in paths)
    if test_infra_touched:
        report.append("测试基础设施改动：升级为全量 pytest")

    needs_full_pytest = py_config_touched or test_infra_touched
    tests_wanted = needs_full_pytest or bool(covered & (PYTHON_CATEGORIES | EVAL_CATEGORIES | {CAT_MIGRATIONS}))
    if tests_wanted:
        if pytest_override:
            selected = list(pytest_override)
            report.append(f"pytest 目标由 --pytest 显式给定：{len(selected)} 项")
            steps.append(
                Step(
                    key="pytest",
                    title=f"pytest（{len(selected)} 个目标，排除 live_model）",
                    argv=("uv", "run", "pytest", "-m", LIVE_MODEL_EXPR, *selected),
                )
            )
        elif needs_full_pytest:
            # 依赖清单 / 测试基础设施改动影响每一轮检查，跑全量而不是按路径推断。
            steps.append(full_pytest_step)
        else:
            selection = pytest_files_for(paths, existing_test_files())
            if selection is None:
                problems.append(
                    "无法从改动机械推出相关的 pytest 文件（源码路径匹配不到测试）——"
                    "请用 --pytest <文件或 nodeid> 显式指定，或跑 full；"
                    "本脚本不会在没有测试的情况下报绿"
                )
                selected = []
            else:
                selected = selection
                report.append(
                    f"pytest 范围（按改动推出）：{', '.join(selected)}"
                    if selected
                    else "pytest：改动不影响现有测试文件"
                )
            if selected:
                steps.append(
                    Step(
                        key="pytest",
                        title=f"pytest（{len(selected)} 个目标，排除 live_model）",
                        argv=("uv", "run", "pytest", "-m", LIVE_MODEL_EXPR, *selected),
                    )
                )

    # 样式契约归「文档」，但消费者是前端构建（sync-tokens + 契约类名断言），必须一起跑。
    web_contract_touched = any(path in WEB_CONTRACT_PATHS for path in paths)
    if web_contract_touched:
        report.append(f"前端样式契约改动（{'、'.join(sorted(WEB_CONTRACT_PATHS))}）：跑前端 lint/test/build")

    if CAT_WEB in covered or CAT_WEB_CONFIG in covered or web_contract_touched:
        steps.append(Step(key="web-lint", title="前端 oxlint", argv=("pnpm", "--filter", "@campfire/web", "lint")))
        steps.append(Step(key="web-test", title="前端 vitest", argv=("pnpm", "--filter", "@campfire/web", "test")))
        # 构建才覆盖 tsc 与契约类名断言；依赖/配置/样式契约改动必须走构建。
        if CAT_WEB_CONFIG in covered or web_contract_touched:
            steps.append(
                Step(
                    key="web-build",
                    title="前端构建（含 tsc 与契约样式断言）",
                    argv=("pnpm", "--filter", "@campfire/web", "build"),
                )
            )
        else:
            report.append("前端只动了 src/tests：跑 lint 与 vitest，构建留给 full（build 含 tsc，较慢）")

    return steps, report, problems


def full_plan() -> list[Step]:
    """`full` 的完整确定性门禁（与 CI 等价，去掉两处重复）。"""
    return [
        Step(key="ruff", title="ruff check", argv=("uv", "run", "ruff", "check", ".")),
        Step(key="ruff-format", title="ruff format --check", argv=("uv", "run", "ruff", "format", "--check", ".")),
        Step(
            key="mypy",
            title="mypy（src + tests 必须一起传）",
            argv=("uv", "run", "mypy", "apps/api/src/campfire", "apps/api/tests"),
        ),
        Step(
            key="design-docs",
            title="设计文档一致性",
            argv=("uv", "run", "python", "scripts/check_design_docs.py"),
        ),
        Step(key="alembic-upgrade", title="迁移升级到 head", argv=("uv", "run", "alembic", "upgrade", "head")),
        Step(key="alembic-check", title="迁移无漂移（模型与迁移不一致即失败）", argv=("uv", "run", "alembic", "check")),
        Step(
            key="pytest",
            title=f"pytest（全量，显式排除 {LIVE_MODEL_EXPR.split()[-1]}）",
            argv=("uv", "run", "pytest", "-m", LIVE_MODEL_EXPR),
        ),
        Step(key="web-lint", title="前端 oxlint", argv=("pnpm", "--filter", "@campfire/web", "lint")),
        Step(key="web-test", title="前端 vitest", argv=("pnpm", "--filter", "@campfire/web", "test")),
        Step(
            key="web-build",
            title="前端构建（build 已含 tsc --noEmit，故不再单独 typecheck）",
            argv=("pnpm", "--filter", "@campfire/web", "build"),
        ),
    ]


def run_steps(steps: list[Step], dry_run: bool, keep_going: bool) -> tuple[list[Step], list[Step]]:
    """按顺序执行检查。

    Args:
        steps: 计划。
        dry_run: 只打印命令，不执行。
        keep_going: 某步失败后是否继续跑后续步骤。

    Returns:
        `(passed, failed_and_skipped)`：已通过步骤，以及失败/因提前停止而未跑的步骤。
    """
    passed: list[Step] = []
    problems: list[Step] = []
    stopped = False
    for step in steps:
        print(f"\n=== {step.title}\n$ {step.display()}", flush=True)
        if dry_run:
            passed.append(step)  # dry-run 下「将要执行」即算已展示
            continue
        if stopped:
            print("（已因前一步失败跳过）", flush=True)
            problems.append(step)
            continue
        proc = subprocess.run(list(step.argv), cwd=ROOT)
        if proc.returncode == 0:
            passed.append(step)
            continue
        problems.append(step)
        if not keep_going:
            stopped = True
    return passed, problems


def _print_report(report: list[str]) -> None:
    """打印「本轮选了哪些检查、为什么」。"""
    if report:
        print("\n选定范围：")
        for line in report:
            print(f"  - {line}")


def main(argv: list[str] | None = None) -> int:
    """命令行入口；返回进程退出码（见模块 docstring）。"""
    parser = argparse.ArgumentParser(
        prog="checks.py",
        description="按影响面选择工程检查（quick）或跑完整确定性门禁（full）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    quick = sub.add_parser("quick", help="按 git diff 与未提交改动选检查")
    quick.add_argument("--base", default="dev", help="基线分支（默认 dev）")
    quick.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令")
    quick.add_argument(
        "--pytest",
        nargs="+",
        metavar="TARGET",
        help="显式指定 pytest 目标（文件或 nodeid）；给了就完全按它跑，不再自动推断",
    )
    quick.add_argument(
        "--accept-unchecked",
        action="store_true",
        help="人工确认「没有对应检查的路径」可以接受（默认会阻塞并退出码 2）",
    )
    quick.add_argument("--keep-going", action="store_true", help="某步失败后继续跑后续步骤")

    full = sub.add_parser("full", help="完整确定性门禁（与 CI 等价，去掉重复的 tsc）")
    full.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令")
    full.add_argument("--keep-going", action="store_true", help="某步失败后继续跑后续步骤")

    args = parser.parse_args(argv)

    if args.command == "quick":
        steps, report, problems = quick_plan(args.base, args.pytest)
        _print_report(report)
        if problems and not args.accept_unchecked:
            for problem in problems:
                print(f"\n阻塞：{problem}", file=sys.stderr)
            print(
                "\n范围不确定时不跑半步、也不报绿。确认路径可接受后重跑并加 --accept-unchecked，"
                "或用 --pytest 指定目标。",
                file=sys.stderr,
            )
            return 2
        if problems and args.accept_unchecked:
            for problem in problems:
                print(f"\n已显式接受：{problem}", file=sys.stderr)
        if not steps:
            print("\n没有需要执行的检查。")
            return 0
        passed, failed = run_steps(steps, args.dry_run, args.keep_going)
        return _summarize(passed, failed, dry_run=args.dry_run)

    steps = full_plan()
    _print_report(
        [
            "完整确定性门禁：ruff / mypy(src+tests) / 设计文档 / 迁移门禁 / pytest / 前端 lint+vitest+build",
            "前端不单独跑 typecheck：build 已包含 tsc --noEmit（重复跑只耗时，不增加判据）",
            f"pytest 显式带 -m '{LIVE_MODEL_EXPR}'：真实模型用例需 --live-model 显式开启",
        ]
    )
    passed, failed = run_steps(steps, args.dry_run, args.keep_going)
    return _summarize(passed, failed, dry_run=args.dry_run)


def _summarize(passed: list[Step], failed: list[Step], dry_run: bool) -> int:
    """打印总结并给出退出码。"""
    if dry_run:
        print(f"\n--dry-run：上面是全部 {len(passed) + len(failed)} 步计划，未执行任何命令。")
        return 0
    print(f"\n通过 {len(passed)} 步：{', '.join(step.key for step in passed) or '（无）'}")
    if failed:
        print(f"失败 {len(failed)} 步：{', '.join(step.key for step in failed)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
