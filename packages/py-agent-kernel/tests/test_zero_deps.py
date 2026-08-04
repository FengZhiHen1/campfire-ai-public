"""内核零依赖断言——内核不得 import 任何 Campfire 包（T2.8 CI 化）。

Agent内核框架 §二禁令：内核不得 import 任何宿主/领域包。
本测试扫描全部内核源码，断言无 Campfire 包 import。
"""

from __future__ import annotations

import re
from pathlib import Path

_FORBIDDEN_PATTERNS = [
    r"from\s+py_schemas",
    r"import\s+py_schemas",
    r"from\s+py_db",
    r"import\s+py_db",
    r"from\s+py_rag",
    r"import\s+py_rag",
    r"from\s+py_auth",
    r"import\s+py_auth",
    r"from\s+py_cache",
    r"import\s+py_cache",
    r"from\s+py_storage",
    r"import\s+py_storage",
    r"from\s+py_security",
    r"import\s+py_security",
    r"from\s+py_config",
    r"import\s+py_config",
    r"from\s+py_logger",
    r"import\s+py_logger",
    r"from\s+py_health",
    r"import\s+py_health",
    r"from\s+app\b",
    r"import\s+app\b",
    r"from\s+campfire",
    r"import\s+campfire",
]

_KERNEL_SRC = Path(__file__).resolve().parents[1] / "py_agent_kernel"


def test_kernel_has_no_campfire_imports():
    violations: list[str] = []
    for py_file in sorted(_KERNEL_SRC.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8").lower()
        for pattern in _FORBIDDEN_PATTERNS:
            if re.search(pattern, content):
                violations.append(f"{py_file.name}: {pattern}")
    assert violations == [], f"内核存在 Campfire 依赖: {violations}"


def test_kernel_importable():
    import py_agent_kernel

    assert py_agent_kernel.__version__
