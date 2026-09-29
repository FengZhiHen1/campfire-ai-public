"""依赖白名单的机械检查。

docs/项目结构设计.md 第 7 节要求「依赖方向无环，**并用白名单显式允许，而不是靠
约定**」。本测试把那张表变成可执行断言：解析 ``apps/api/src/campfire`` 下每个模块
的 import，检查跨层引用是否落在白名单内。

**不覆盖的部分（诚实声明）**：表中「出现领域术语」「绕过用例服务直接写表」
「直接访问数据库表」「模块间不得互相依赖业务用例」里的后三项不是 import 关系，
无法由本测试证明，需要各自的用例测试或审查。
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "campfire"
SRC_MODULE_ROOT = "campfire"

LAYERS = ("agent", "surfaces", "tools", "modules", "core", "cli")

# 每层允许引用的同项目包前缀（不含该层自身，自身由 _owner_prefix 放行）。
# 依据 docs/项目结构设计.md 第 7 节的表。
ALLOWED: dict[str, set[str]] = {
    # 基座只允许 core/config（设计另列 core/logging，但该模块在目录设计中不存在）
    "agent": {"campfire.core.config"},
    "surfaces": {"campfire.agent", "campfire.tools", "campfire.modules", "campfire.core"},
    "tools": {"campfire.modules", "campfire.core"},
    "modules": {"campfire.core"},
    "core": {"campfire.core"},
    # 本地摄取入口：禁止 import surfaces、禁止暴露成服务端点
    "cli": {"campfire.core", "campfire.modules.library"},
}


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
