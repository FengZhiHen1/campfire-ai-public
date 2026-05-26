#!/usr/bin/env python3
"""
流水线就绪检查：在进入 Phase 1 之前验证所有前置条件。
由 orchestrator 在前置步骤中调用。

用法:
    python scripts/preflight_check.py [--module-id M01] [--check-sub-skills]

检查项:
    1. Python 版本 >= 3.8
    2. scripts/ 下所有必需脚本存在且语法正确
    3. (--module-id 指定时) docs/contracts/{module_id}/ 目录存在
    4. (--check-sub-skills 指定时) 依赖的 SubAgent skill 存在

退出码:
    0 - 全部通过
    1 - 存在警告（可继续但建议修复）
    2 - 存在阻断性错误
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════════════

MIN_PYTHON = (3, 8)

REQUIRED_SCRIPTS = [
    "validate_function_signatures.py",
    "validate_contract_expectations.py",
    "generate_failure_summary.py",
    "validate_failure_summary.py",
    "validate_contract_consistency.py",
    "preflight_check.py",
]

REQUIRED_SUB_SKILLS = [
    "adversarial-implementation-executor",
    "adversarial-test-generator",
]

# ═══════════════════════════════════════════════════════════════════════════════
# 检查函数
# ═══════════════════════════════════════════════════════════════════════════════


class CheckResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.passes: list[str] = []

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def check_python_version(result: CheckResult) -> None:
    """检查 Python 版本。"""
    current = sys.version_info[:2]
    if current >= MIN_PYTHON:
        result.passes.append(f"Python {'.'.join(map(str, current))} >= {'.'.join(map(str, MIN_PYTHON))}")
    else:
        result.errors.append(
            f"Python 版本过低: {'.'.join(map(str, current))} < {'.'.join(map(str, MIN_PYTHON))}。"
            "请升级 Python。"
        )


def check_scripts(scripts_dir: Path, result: CheckResult) -> None:
    """检查所有必需脚本是否存在且语法正确。"""
    missing: list[str] = []
    syntax_errors: list[str] = []

    for script_name in REQUIRED_SCRIPTS:
        script_path = scripts_dir / script_name
        if not script_path.exists():
            missing.append(script_name)
            continue

        # 语法检查：尝试编译
        try:
            source = script_path.read_text(encoding="utf-8")
            compile(source, str(script_path), "exec")
        except SyntaxError as e:
            syntax_errors.append(f"{script_name}: {e}")

    if missing:
        result.errors.append(f"缺少脚本: {', '.join(missing)}")
    if syntax_errors:
        result.errors.append(f"脚本语法错误: {'; '.join(syntax_errors)}")

    if not missing and not syntax_errors:
        result.passes.append(f"全部 {len(REQUIRED_SCRIPTS)} 个脚本就绪")


def check_contract_dir(module_id: str, result: CheckResult) -> None:
    """检查契约目录是否存在。"""
    # 从项目根目录查找
    contract_path = Path(f"docs/contracts/{module_id}")
    if contract_path.exists() and contract_path.is_dir():
        json_files = list(contract_path.glob("*.json"))
        if json_files:
            result.passes.append(f"契约目录存在: {contract_path} ({len(json_files)} 个契约文件)")
        else:
            result.warnings.append(f"契约目录存在但无 .json 文件: {contract_path}")
    else:
        result.warnings.append(
            f"契约目录不存在: {contract_path}。"
            "如果本模块无外部契约文件，可忽略。"
        )


def check_sub_skills(skills_base: Path, result: CheckResult) -> None:
    """检查依赖的 SubAgent skill 是否存在。"""
    missing: list[str] = []
    for skill_name in REQUIRED_SUB_SKILLS:
        skill_path = skills_base / skill_name / "SKILL.md"
        if skill_path.exists():
            result.passes.append(f"SubAgent skill 就绪: {skill_name}")
        else:
            missing.append(skill_name)

    if missing:
        result.errors.append(
            f"缺少 SubAgent skill: {', '.join(missing)}。"
            f"预期路径: {skills_base}"
        )


def check_git_repo(result: CheckResult) -> None:
    """检查是否在 git 仓库中（非强制，但建议）。"""
    git_dir = Path(".git")
    if git_dir.exists():
        result.passes.append("检测到 git 仓库")
    else:
        result.warnings.append("未检测到 .git 目录，环境同步步骤可能无法执行")


def check_docs_dir(result: CheckResult) -> None:
    """检查 docs/ 目录是否存在。"""
    docs = Path("docs")
    if docs.exists() and docs.is_dir():
        result.passes.append("docs/ 目录存在")
    else:
        result.warnings.append("docs/ 目录不存在，设计文档可能缺失")


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="流水线就绪检查 — 验证模块实现编排器的所有前置条件"
    )
    parser.add_argument(
        "--module-id",
        help="模块编号（如 M01），用于检查契约目录",
        default=None,
    )
    parser.add_argument(
        "--check-sub-skills",
        action="store_true",
        help="检查依赖的 SubAgent skill 是否存在",
    )
    args = parser.parse_args()

    result = CheckResult()

    # 定位关键目录
    scripts_dir = Path(__file__).resolve().parent
    # skills_base 是本 skill 目录的父目录（所有 skill 平级存放）
    skills_base = scripts_dir.parent.parent

    # 执行检查
    check_python_version(result)
    check_scripts(scripts_dir, result)
    check_git_repo(result)
    check_docs_dir(result)

    if args.module_id:
        check_contract_dir(args.module_id, result)

    if args.check_sub_skills:
        check_sub_skills(skills_base, result)

    # 输出报告
    print("=" * 60)
    print("  模块实现编排器 — 就绪检查")
    print("=" * 60)
    print()

    if result.passes:
        print("✅ 通过的检查:")
        for p in result.passes:
            print(f"   ✓ {p}")
        print()

    if result.warnings:
        print("⚠️  警告:")
        for w in result.warnings:
            print(f"   ! {w}")
        print()

    if result.errors:
        print("❌ 阻断性错误:")
        for e in result.errors:
            print(f"   ✗ {e}")
        print()

    # 摘要
    print("-" * 60)
    print(f"通过: {len(result.passes)} | 警告: {len(result.warnings)} | 错误: {len(result.errors)}")

    if result.has_errors:
        print("结论: ❌ 未就绪 — 请修复上述错误后重试")
        return 2
    elif result.has_warnings:
        print("结论: ⚠️  可继续，但建议修复警告")
        return 1
    else:
        print("结论: ✅ 全部就绪")
        return 0


if __name__ == "__main__":
    sys.exit(main())
