"""质量门：调用 detect_green_seeking.py 扫描所有 wfctl 测试文件。

运行方式：
    # 仅扫描变更文件（默认）
    pytest tests/quality/ -v

    # 全量扫描
    pytest tests/quality/ --scan-all

任何文件 toxicity_score > 2 视为失败。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


# __file__ = .../artifacts/scripts/wfctl/tests/quality/test_green_seeking.py
# parents[4] = .../artifacts/
SCANNER_PATH = (
    Path(__file__).resolve().parents[4]
    / "workflows"
    / "adversarial-module-implementation@2.0.0"
    / "scripts"
    / "detect_green_seeking.py"
)


def _find_test_files() -> list[Path]:
    tests_dir = Path(__file__).resolve().parents[2]
    files: list[Path] = []
    for tf in sorted(tests_dir.rglob("test_*.py")):
        if "quality" in tf.parts:
            continue
        files.append(tf.resolve())
    return files


def _ensure_init_py(test_dirs: list[Path]):
    """为测试目录创建非空 __init__.py（扫描器前置条件）。"""
    for d in test_dirs:
        init = d / "__init__.py"
        if not init.exists() or init.stat().st_size == 0:
            init.write_text("# test package\n", encoding="utf-8")


def _run_scanner(test_file: Path) -> dict:
    wfctl_root = Path(__file__).resolve().parents[2]
    (wfctl_root / ".tmp").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(SCANNER_PATH),
            str(test_file),
            "--sut-module", "core,services,cli,domain,state,runtime,infrastructure,compat,scheduler",
        ],
        cwd=str(wfctl_root),
        capture_output=True,
        text=True,
    )
    raw_output = result.stdout.strip() or result.stderr.strip()
    if not raw_output:
        return {"file": str(test_file), "error": f"No scanner output (rc={result.returncode})"}

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        return {"file": str(test_file), "error": f"Scanner crashed: {raw_output[:200]}"}


def _collect_all_findings(test_files: list[Path]) -> dict[str, dict]:
    findings: dict[str, dict] = {}
    for tf in test_files:
        result = _run_scanner(tf)
        if result.get("suspects") or result.get("error"):
            findings[str(tf)] = result
    return findings


# ─── 测试用例 ─────────────────────────────────────────────────────────


def test_green_seeking_all_files():
    """全量扫描所有测试文件，toxicity_score > 2 的文件必须为 0。"""
    wfctl_root = Path(__file__).resolve().parents[2]

    # 确保 __init__.py 非空
    test_dirs = [wfctl_root / "tests", wfctl_root / "tests" / "core",
                 wfctl_root / "tests" / "services", wfctl_root / "tests" / "cli",
                 wfctl_root / "tests" / "domain", wfctl_root / "tests" / "domain" / "dag",
                 wfctl_root / "tests" / "domain" / "transition",
                 wfctl_root / "tests" / "state", wfctl_root / "tests" / "runtime",
                 wfctl_root / "tests" / "runtime"]
    _ensure_init_py(test_dirs)

    test_files = _find_test_files()
    assert len(test_files) > 0, "No test files found"

    findings = _collect_all_findings(test_files)
    failures: list[str] = []

    for fname, result in sorted(findings.items()):
        if result.get("error"):
            failures.append(f"{fname}: ERROR — {result['error']}")
            continue
        # 计算 non-G12 的毒性分（G12=导入私有函数，对自有测试合法）
        non_g12_score = sum(
            s["toxicity"] for s in result.get("suspects", []) if s["id"] != "G12"
        )
        if non_g12_score > 2:
            suspects_desc = []
            for s in result.get("suspects", []):
                if s["id"] == "G12":
                    continue
                suspects_desc.append(f"  [{s['id']}] L{s['line']} {s['func']}: {s['message']}")
            failures.append(f"{fname}: score={non_g12_score}\n" + "\n".join(suspects_desc))

    if failures:
        pytest.fail(
            f"\n{'='*60}\n"
            f"Green-seeking scan found {len(failures)} file(s) with non-G12 issues:\n\n"
            + "\n\n".join(failures)
            + f"\n\n{'='*60}\n"
            f"Fix these issues before committing. "
            f"G12 (private import) findings are allowed for project-owned tests. "
            f"See artifacts/workflows/adversarial-module-implementation@2.0.0/scripts/detect_green_seeking.py for rule details."
        )


def test_green_seeking_no_empty_tests():
    """G11: 不得有空测试函数（无 assert/raises/fail）。"""
    wfctl_root = Path(__file__).resolve().parents[2]
    test_dirs = [wfctl_root / "tests", wfctl_root / "tests" / "core",
                 wfctl_root / "tests" / "services", wfctl_root / "tests" / "cli",
                 wfctl_root / "tests" / "domain", wfctl_root / "tests" / "domain" / "dag",
                 wfctl_root / "tests" / "domain" / "transition",
                 wfctl_root / "tests" / "state", wfctl_root / "tests" / "runtime",
                 wfctl_root / "tests" / "runtime"]
    _ensure_init_py(test_dirs)

    test_files = _find_test_files()
    g11_findings: list[str] = []

    for tf in test_files:
        result = _run_scanner(tf)
        for s in result.get("suspects", []):
            if s["id"] == "G11":
                g11_findings.append(f"{tf}: L{s['line']} {s['func']}: {s['message']}")

    if g11_findings:
        pytest.fail(
            f"G11 空测试检测到 {len(g11_findings)} 个问题:\n"
            + "\n".join(g11_findings)
        )
