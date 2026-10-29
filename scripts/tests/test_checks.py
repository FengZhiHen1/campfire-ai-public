"""`scripts/checks.py` 的针对性测试（纯标准库，不执行任何真实检查命令）。

这里钉的是两类最容易退化的东西：

1. **路径归类**：未知路径必须落到 `unknown`（进而阻塞），不能被「顺手当作文档」；
2. **选检查的判据**：前端 src 改动不跑构建、依赖/配置改动跑构建、真模型用例被显式排除、
   `full` 不重复跑 tsc——这些都是「省时间」与「不漏判据」之间的边界，写成断言才不会
   在下次调整时被悄悄改掉。

`--dry-run` 的用例只打印计划，不执行命令，因此它们既快又不依赖本机环境。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_checks():  # noqa: ANN202 —— 返回模块对象；避免在测试模块顶层做导入副作用
    """按路径加载 `scripts/checks.py`（`scripts/` 不是包，不能 `import checks`）。

    必须先塞进 `sys.modules` 再执行：`@dataclass` 在装饰期会按
    `sys.modules[cls.__module__]` 回查模块字典，不注册就会抛
    `AttributeError: 'NoneType' object has no attribute '__dict__'`（实测踩到）。
    """
    path = ROOT / "scripts" / "checks.py"
    spec = importlib.util.spec_from_file_location("checks_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["checks_under_test"] = module
    spec.loader.exec_module(module)
    return module


checks = _load_checks()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("apps/api/src/campfire/main.py", checks.CAT_PY_SRC),
        ("apps/api/tests/test_health.py", checks.CAT_PY_TESTS),
        ("apps/api/alembic/versions/0001_init.py", checks.CAT_MIGRATIONS),
        ("alembic.ini", checks.CAT_MIGRATIONS),
        ("apps/web/src/features/chat/view/ChatPage.tsx", checks.CAT_WEB),
        ("apps/web/tests/routes-coverage.test.ts", checks.CAT_WEB),
        ("apps/web/package.json", checks.CAT_WEB_CONFIG),
        ("apps/web/vite.config.ts", checks.CAT_WEB_CONFIG),
        ("package.json", checks.CAT_WEB_CONFIG),
        ("pnpm-lock.yaml", checks.CAT_WEB_CONFIG),
        ("scripts/worktree.py", checks.CAT_SCRIPTS),
        ("scripts/tests/test_checks.py", checks.CAT_SCRIPT_TESTS),
        ("scripts/tests/test_worktree.py", checks.CAT_SCRIPT_TESTS),
        ("pyproject.toml", checks.CAT_PY_CONFIG),
        ("uv.lock", checks.CAT_PY_CONFIG),
        ("docs/需求/功能需求与验收.md", checks.CAT_DOCS),
        ("README.md", checks.CAT_DOCS),
        ("AGENTS.md", checks.CAT_DOCS),
        (".github/workflows/ci.yml", checks.CAT_CI),
        ("infrastructure/nginx/nginx.conf", checks.CAT_OPS),
        ("docker-compose.yml", checks.CAT_OPS),
        ("marketing/whatever.py", checks.CAT_UNKNOWN),
        ("data/cases/manifest.json", checks.CAT_UNKNOWN),
    ],
)
def test_classify_maps_paths_to_categories(path: str, expected: str) -> None:
    """每条归类都要有明确答案；未知路径必须是 `unknown` 而不是被猜成文档。"""
    assert checks.classify(path) == expected


def test_unknown_and_uncovered_categories_are_the_blocking_set() -> None:
    """阻塞集合必须包含未知、CI 与运维：这三类有改动时 `quick` 不能报绿。"""
    assert {checks.CAT_UNKNOWN, checks.CAT_CI, checks.CAT_OPS} <= checks.UNCOVERED_CATEGORIES


def test_changed_test_file_is_selected_directly() -> None:
    """改到测试文件本身 → 就跑它。"""
    selection = checks.pytest_files_for(
        ["apps/api/tests/test_health.py"],
        checks.existing_test_files(),
    )

    assert selection == ["apps/api/tests/test_health.py"]


def test_source_change_maps_to_area_tests() -> None:
    """源码改动按路径里的模块词映射到同名测试（`modules/library` → `test_library_*`）。"""
    selection = checks.pytest_files_for(
        ["apps/api/src/campfire/modules/library/routes.py"],
        checks.existing_test_files(),
    )

    assert selection is not None
    assert selection, "源码改动必须能选出一组测试，否则等于静默不测"
    assert all(Path(item).name.startswith("test_library") for item in selection)


def test_script_change_maps_to_its_own_tests() -> None:
    """改到 `scripts/worktree.py` → 跑 `scripts/tests/test_worktree*.py`。"""
    selection = checks.pytest_files_for(
        ["scripts/worktree.py"],
        checks.existing_test_files(),
    )

    assert selection == ["scripts/tests/test_worktree.py"]


def test_unmappable_source_change_is_reported_not_silently_skipped() -> None:
    """映射不到测试的源码改动返回 `None`（调用方据此阻塞，而不是「没有测试要跑」）。"""
    selection = checks.pytest_files_for(
        ["apps/api/src/campfire/no_such_module.py"],
        checks.existing_test_files(),
    )

    assert selection is None


def test_quick_plan_blocks_on_paths_without_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有对应检查的路径 → `problems` 非空（`main` 会据此退出码 2）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["infrastructure/nginx/nginx.conf"])

    steps, _report, problems = checks.quick_plan("dev", None)

    assert steps == []
    assert problems and "infrastructure/nginx/nginx.conf" in problems[0]


def test_quick_plan_selects_docs_check_for_docs_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """只改文档 → 只跑设计文档一致性检查。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["docs/需求/功能需求与验收.md"])

    steps, _report, problems = checks.quick_plan("dev", None)

    assert problems == []
    assert [step.key for step in steps] == ["design-docs"]


def test_quick_plan_runs_lint_and_tests_but_not_build_for_web_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """前端 src 改动：lint + vitest，不跑构建（构建含 tsc，慢且这里用不上）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["apps/web/src/features/chat/view/ChatPage.tsx"])

    steps, _report, problems = checks.quick_plan("dev", None)

    assert problems == []
    assert [step.key for step in steps] == ["web-lint", "web-test"]


def test_quick_plan_runs_build_for_web_config_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """前端依赖/配置改动：必须跑构建（tsc 与契约类名断言都在 build 里）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["apps/web/package.json"])

    steps, _report, problems = checks.quick_plan("dev", None)

    assert problems == []
    assert [step.key for step in steps] == ["web-lint", "web-test", "web-build"]


def test_quick_plan_uses_explicit_pytest_targets_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--pytest` 给了目标就完全按它跑（便于 subagent 指定单个 nodeid）。"""
    monkeypatch.setattr(
        checks,
        "changed_paths",
        lambda base: ["apps/api/src/campfire/modules/library/routes.py"],
    )

    steps, _report, problems = checks.quick_plan("dev", ["apps/api/tests/test_library_routes_integration.py::test_x"])

    assert problems == []
    pytest_steps = [step for step in steps if step.key == "pytest"]
    assert len(pytest_steps) == 1
    assert pytest_steps[0].argv[-1] == "apps/api/tests/test_library_routes_integration.py::test_x"


def test_quick_plan_blocks_when_pytest_scope_cannot_be_derived(monkeypatch: pytest.MonkeyPatch) -> None:
    """源码映射不到测试且没给 `--pytest` → 阻塞（不许跳过测试报绿）。"""
    monkeypatch.setattr(
        checks,
        "changed_paths",
        lambda base: ["apps/api/src/campfire/no_such_module.py"],
    )

    steps, _report, problems = checks.quick_plan("dev", None)

    assert problems and "--pytest" in problems[0]
    assert not [step for step in steps if step.key == "pytest"]


def test_quick_plan_keeps_mypy_paths_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """mypy 必须一次传 src + tests（分开跑会因模块名重复而整体中止）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["apps/api/tests/test_health.py"])

    steps, _report, _problems = checks.quick_plan("dev", None)

    mypy_steps = [step for step in steps if step.key == "mypy"]
    assert len(mypy_steps) == 1
    assert mypy_steps[0].argv[-2:] == ("apps/api/src/campfire", "apps/api/tests")


def test_full_plan_covers_every_gate_without_duplicate_typecheck() -> None:
    """`full` 覆盖完整门禁，且不重复跑 typecheck（build 已含 tsc）。"""
    argv_text = [" ".join(step.argv) for step in checks.full_plan()]

    assert any("ruff check" in item for item in argv_text)
    assert any("ruff format --check" in item for item in argv_text)
    assert any("mypy" in item for item in argv_text)
    assert any("check_design_docs.py" in item for item in argv_text)
    assert any("alembic upgrade head" in item for item in argv_text)
    assert any("alembic check" in item for item in argv_text)
    assert any(item.startswith("uv run pytest") for item in argv_text)
    assert any("web" in item and "lint" in item for item in argv_text)
    assert any("web" in item and "test" in item for item in argv_text)
    assert any("web" in item and "build" in item for item in argv_text)
    assert not any("typecheck" in item for item in argv_text), "build 已含 tsc，不得重复 typecheck"


def test_full_plan_excludes_live_model_tests_explicitly() -> None:
    """pytest 步骤显式带 `-m 'not live_model'`：真模型用例必须显式开启。"""
    pytest_steps = [step for step in checks.full_plan() if step.key == "pytest"]

    assert len(pytest_steps) == 1
    argv = pytest_steps[0].argv
    assert "-m" in argv
    assert argv[argv.index("-m") + 1] == checks.LIVE_MODEL_EXPR == "not live_model"


def test_full_dry_run_prints_plan_without_running(capsys: pytest.CaptureFixture[str]) -> None:
    """`full --dry-run` 只打印命令并返回 0（不执行任何检查）。"""
    exit_code = checks.main(["full", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ruff check" in captured.out
    assert "uv run pytest" in captured.out
    assert "未执行任何命令" in captured.out


# --- changed_paths：非 ASCII / 空格 / 重命名 ---------------------------------


def _git(repo: Path, *args: str) -> None:
    """在临时仓库里跑一条 git 命令（提交身份写死，免得依赖宿主机配置）。"""
    identity = {
        "GIT_AUTHOR_NAME": "checks-test",
        "GIT_AUTHOR_EMAIL": "checks@example.com",
        "GIT_COMMITTER_NAME": "checks-test",
        "GIT_COMMITTER_EMAIL": "checks@example.com",
    }
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **identity},
    )


def _temp_repo(tmp_path: Path, baseline_files: dict[str, str] | None = None) -> Path:
    """一个 `dev` 为基线、当前在 `task/probe` 上的临时仓库。

    Args:
        tmp_path: pytest 的临时目录。
        baseline_files: 要**先在 `dev` 上**存在的文件（路径 → 内容）。重命名用例必须先有
            旧文件在基线里，否则「加了又删」在三点 diff 里净变化为零，测不到重命名。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    files = {"base.md": "base\n", **(baseline_files or {})}
    for name, content in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "switch", "-q", "-c", "task/probe")
    return repo


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def test_changed_paths_keeps_non_ascii_and_space_paths_unquoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中文与含空格的路径必须原样返回（默认输出会给它们加引号并转义成八进制）。

    真的踩到过：`docs/需求/…` 被解析成 `"docs\\346\\226\\207…"`，于是归类落到 `unknown`，
    `quick` 直接阻塞——本工具自己造的假失败。
    """
    repo = _temp_repo(tmp_path)
    (repo / "docs" / "需求").mkdir(parents=True)
    (repo / "docs" / "需求" / "功能需求与验收.md").write_text("需求\n", encoding="utf-8")
    (repo / "docs" / "带 空格 的 文档.md").write_text("空格\n", encoding="utf-8")
    _commit_all(repo, "docs")
    monkeypatch.setattr(checks, "ROOT", repo)

    paths = checks.changed_paths("dev")

    assert "docs/需求/功能需求与验收.md" in paths
    assert "docs/带 空格 的 文档.md" in paths
    assert all('"' not in path for path in paths), "路径不得带 git 的引号/转义"
    assert checks.classify("docs/需求/功能需求与验收.md") == checks.CAT_DOCS


def test_changed_paths_includes_both_sides_of_a_committed_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已提交的重命名：原路径与被删的那一侧同样算改动（`--no-renames`）。

    只看新路径会让「删掉的文件」从影响面里消失——比如把一个源码模块改名，
    被删模块的测试就再也不会被选中。
    """
    repo = _temp_repo(tmp_path, {"docs/旧名.md": "旧\n"})
    _git(repo, "mv", "docs/旧名.md", "docs/新名.md")
    _commit_all(repo, "rename")
    monkeypatch.setattr(checks, "ROOT", repo)

    paths = checks.changed_paths("dev")

    assert "docs/旧名.md" in paths, "重命名的原路径同样是改动"
    assert "docs/新名.md" in paths


def test_changed_paths_includes_both_sides_of_an_uncommitted_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未提交的重命名：`git status -z` 的 `R` 条目会带两条路径，两边都要收。"""
    repo = _temp_repo(tmp_path, {"docs/旧名.md": "旧\n"})
    _git(repo, "mv", "docs/旧名.md", "docs/新名.md")  # 不提交：只留在工作区
    monkeypatch.setattr(checks, "ROOT", repo)

    paths = checks.changed_paths("dev")

    assert "docs/旧名.md" in paths
    assert "docs/新名.md" in paths


# --- 只在改动面里才出现的检查 ------------------------------------------------


def test_quick_plan_runs_script_tests_when_only_they_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """只改了工具自己的测试 → 必须真的跑它（此前的形状是「一条 pytest 都没跑却报绿」）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["scripts/tests/test_checks.py"])

    steps, report, problems = checks.quick_plan("dev", None)

    assert problems == []
    pytest_steps = [step for step in steps if step.key == "pytest"]
    assert len(pytest_steps) == 1, f"没有 pytest 步骤：{report}"
    assert "scripts/tests/test_checks.py" in pytest_steps[0].argv


def test_quick_plan_runs_mypy_and_full_pytest_for_lockfile_only_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """只动 pyproject/uv.lock → mypy + 全量 pytest（配置改错会影响所有检查）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["uv.lock"])

    steps, _report, problems = checks.quick_plan("dev", None)

    assert problems == []
    keys = [step.key for step in steps]
    assert "mypy" in keys
    full = [step for step in steps if step.key == "pytest-full"]
    assert len(full) == 1, "锁文件改动必须跑全量 pytest"
    assert full[0].argv == ("uv", "run", "pytest", "-m", checks.LIVE_MODEL_EXPR)
    assert "pytest" not in keys, "全量与按改动推断的 pytest 不能同时排（会重复跑）"


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/src/campfire/modules/library/models.py",
        "apps/api/src/campfire/core/db/engine.py",
    ],
)
def test_quick_plan_runs_alembic_check_for_model_or_engine_changes(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """ORM 模型/引擎定义改了就跑迁移漂移检查（此前只由 `alembic/` 目录触发）。"""
    monkeypatch.setattr(checks, "changed_paths", lambda base: [path])

    steps, _report, _problems = checks.quick_plan("dev", None)

    assert "alembic" in [step.key for step in steps]


def test_deleted_test_file_is_not_handed_to_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """删除的测试文件不能成为 pytest 目标（不存在的路径会让 pytest 退出 4）。

    删除仍要计入影响面：它照样触发 ruff/mypy 与「改动过测试」的判断。
    """
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["apps/api/tests/test_已删除的用例.py"])

    steps, report, problems = checks.quick_plan("dev", None)

    assert problems == []
    assert "ruff" in [step.key for step in steps], "删除同样是改动，lint 仍要跑"
    assert not [step for step in steps if step.key == "pytest"], "不得把不存在的文件交给 pytest"
    assert all("test_已删除的用例.py" not in step.argv for step in steps)
    assert "不影响现有测试文件" in report[-1]


# --- 影响面的三处缺口（2026-10-29 修）---------------------------------------


def test_style_contract_change_runs_frontend_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """改 `docs/design/tokens.css` 必须跑前端 build。

    缺陷形状（修复前实测）：它的归类是 `docs`，于是 `quick` 只排了设计文档检查——
    而 `apps/web` 的 `build` 第一步 `sync-tokens` 逐字节读这个文件，契约类名断言也在
    `build` 里。`checks.py` 里那条 `docs/design/tokens.css` 的判断写在了
    「前端分支内部」，而该分支根本不会被这个路径进入，等于一行**永不生效**的判据。
    """
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["docs/design/tokens.css"])

    steps, report, problems = checks.quick_plan("dev", None)

    assert problems == []
    keys = [step.key for step in steps]
    assert keys == ["design-docs", "web-lint", "web-test", "web-build"], keys
    assert any("样式契约" in line for line in report), "报告里要说明「为什么连构建也跑了」"


def test_app_pyproject_is_a_python_config_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """`apps/api/pyproject.toml` 是应用的依赖清单，不能落到 `unknown` 去阻塞 `quick`。

    修复前实测：`quick` 对这条路径直接退出码 2（unknown）。那会诱使人加
    `--accept-unchecked`，把一次真实的依赖改动「接受」成无需检查。
    """
    assert checks.classify("apps/api/pyproject.toml") == checks.CAT_PY_CONFIG
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["apps/api/pyproject.toml"])

    steps, _report, problems = checks.quick_plan("dev", None)

    assert problems == []
    keys = [step.key for step in steps]
    assert "mypy" in keys
    assert "pytest-full" in keys, "依赖清单改动必须跑全量 pytest"
    assert "pytest" not in keys, "不要同时又排一条按路径推断的 pytest"


def test_conftest_change_escalates_to_full_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """改 `conftest.py` 要跑全量 pytest，而不是把它本身交给 pytest。

    修复前实测：`pytest apps/api/tests/conftest.py` 退出码 **5**（没有收集到用例），
    而 `quick` 把非零退出码一律判成「检查失败」——一条必然假红的命令，同时它对
    「改了测试基础设施」这件事一点验证都没有。
    """
    monkeypatch.setattr(checks, "changed_paths", lambda base: ["apps/api/tests/conftest.py"])

    steps, report, problems = checks.quick_plan("dev", None)

    assert problems == []
    keys = [step.key for step in steps]
    assert "pytest-full" in keys, keys
    assert "pytest" not in keys, "不得把 conftest.py 当普通用例目标"
    # ruff 仍然要检查这个文件（它是 .py）；这里只约束 **pytest** 步骤不得把它当目标。
    pytest_steps = [step for step in steps if step.key.startswith("pytest")]
    assert all("conftest.py" not in argument for step in pytest_steps for argument in step.argv)
    assert any("测试基础设施" in line for line in report)


def test_conftest_is_never_selected_as_a_pytest_target() -> None:
    """`pytest_files_for` 不得把 `conftest.py` / tests 包标记当成可跑的目标。"""
    tests = checks.existing_test_files()

    assert checks.pytest_files_for(["apps/api/tests/conftest.py"], tests) == []
    assert checks.pytest_files_for(["apps/api/tests/__init__.py"], tests) == []


def test_full_plan_and_ci_workflow_stay_in_sync() -> None:
    """`full` 与 `.github/workflows/ci.yml` 必须是同一组判据（改一处要检查另一处）。

    为什么写成用例：`docs/development/testing.md` §4.1 要求两者同源，但那是一句话；
    一句话不会在有人删掉 CI 里的 `alembic check` 时变红。这里按**步骤键**逐条对应，
    每步接受若干等价写法（前端 `--filter @campfire/web` 与 CI 的 `--dir apps/web`
    是同一条命令的两种表达）。
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ci = " ".join(workflow.replace('"', "").replace("'", "").split())

    #: full 步骤键 → CI 里可接受的写法（任一命中即可）。
    expected = {
        "ruff": ["uv run ruff check ."],
        "ruff-format": ["uv run ruff format --check ."],
        "mypy": ["uv run mypy apps/api/src/campfire apps/api/tests"],
        "design-docs": ["uv run python scripts/check_design_docs.py", "python scripts/check_design_docs.py"],
        "alembic-upgrade": ["uv run alembic upgrade head"],
        "alembic-check": ["uv run alembic check"],
        "pytest": ["uv run pytest -m not live_model"],
        "web-lint": ["pnpm --filter @campfire/web lint", "pnpm --dir apps/web lint"],
        "web-test": ["pnpm --filter @campfire/web test", "pnpm --dir apps/web test"],
        "web-build": ["pnpm --filter @campfire/web build", "pnpm --dir apps/web build"],
    }

    full_steps = checks.full_plan()
    assert {step.key for step in full_steps} == set(expected), "full 的步骤集合变了——先确认 CI 是否同步"

    missing = [key for key in expected if not any(candidate in ci for candidate in expected[key])]
    assert not missing, f"CI 缺少 full 计划的步骤：{missing}"

    for step in full_steps:
        argv = " ".join(step.argv).replace("'", "")
        # 前端用 `--filter`（工作空间包名），CI 用 `--dir`（目录）：两种写法都算等价。
        if step.key.startswith("web-"):
            continue
        assert argv in expected[step.key], f"full 的 {step.key} 出现了未被审阅的写法：{argv}"
