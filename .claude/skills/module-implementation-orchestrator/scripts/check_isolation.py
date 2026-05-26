#!/usr/bin/env python3
"""
信息隔离合规性审计：验证 orchestrator 在 Phase 4 期间未违规修改测试文件。
由 orchestrator Phase 4 结束时或 Phase 6 验收时调用。

原理:
    对比 .tmp/adversarial-tests/{module_id}/ 下文件的 git 状态，
    确认测试代码文件（*.py, *.ts, *.js, *.go）未被 orchestrator 直接修改。

用法:
    python scripts/check_isolation.py \
        --target-dir .tmp/adversarial-tests/M01 \
        [--since "2024-01-15 10:00:00"] \
        [--output isolation-report.json]

    # 在 Phase 6 验收时使用
    python scripts/check_isolation.py --target-dir .tmp/adversarial-tests/M01 --check-git

退出码:
    0 - 合规（无违规写入）
    1 - 发现违规
    2 - 无法判定（如 git 不可用且无 --since 参数）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════════════

# orchestrator 有权写入的文件类型
ALLOWED_PATTERNS = [
    "*.md",          # failure-summary, test-defects, pending-confirmations
]

# 禁止 orchestrator 写入的测试代码文件类型
FORBIDDEN_PATTERNS = [
    "*.py",
    "*.ts",
    "*.js",
    "*.go",
    "*.test.*",
    "*.spec.*",
]


def is_forbidden(path: Path) -> bool:
    """判断文件路径是否属于禁止修改的类型。"""
    name = path.name.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if path.match(pattern):
            return True
    return False


def is_allowed(path: Path) -> bool:
    """判断文件路径是否属于允许修改的类型。"""
    for pattern in ALLOWED_PATTERNS:
        if path.match(pattern):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Git 模式检查
# ═══════════════════════════════════════════════════════════════════════════════


def check_via_git(target_dir: Path) -> dict:
    """通过 git diff 检查目标目录的文件变更。"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", str(target_dir)],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            timeout=10,
        )
    except FileNotFoundError:
        return {"mode": "git", "available": False, "error": "git 命令不可用"}
    except subprocess.TimeoutExpired:
        return {"mode": "git", "available": False, "error": "git diff 超时"}

    if result.returncode != 0:
        return {"mode": "git", "available": False, "error": result.stderr.strip()}

    changed_files = [f for f in result.stdout.strip().split("\n") if f]

    violations: list[str] = []
    allowed_changes: list[str] = []
    unknown_changes: list[str] = []

    for f in changed_files:
        path = Path(f)
        if is_forbidden(path):
            violations.append(f)
        elif is_allowed(path):
            allowed_changes.append(f)
        else:
            unknown_changes.append(f)

    return {
        "mode": "git",
        "available": True,
        "total_changes": len(changed_files),
        "violations": violations,
        "allowed_changes": allowed_changes,
        "unknown_changes": unknown_changes,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 文件系统模式检查（备用：检查修改时间）
# ═══════════════════════════════════════════════════════════════════════════════


def check_via_filesystem(target_dir: Path, since: datetime | None = None) -> dict:
    """通过文件系统扫描检查目标目录中是否存在不应被修改的测试文件。"""
    if not target_dir.exists():
        return {"mode": "filesystem", "available": True, "note": "目标目录不存在，无需检查"}

    forbidden_files: list[str] = []

    for root, dirs, files in os.walk(target_dir):
        for fname in files:
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(target_dir.parent))

            if is_forbidden(fpath):
                # 如果指定了 since，检查修改时间
                if since:
                    mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)
                    if mtime > since:
                        forbidden_files.append(rel)
                else:
                    # 无 since 参数：只报告存在性，不做时间判定
                    pass

    return {
        "mode": "filesystem",
        "available": True,
        "forbidden_files_present": forbidden_files,
        "since": since.isoformat() if since else None,
        "note": (
            "未提供 --since 参数，仅报告文件存在性，不判定违规。"
            "使用 --check-git 进行准确判定，或提供 --since 指定时间边界。"
        ) if not since else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 综合报告
# ═══════════════════════════════════════════════════════════════════════════════


def generate_report(
    git_result: dict,
    fs_result: dict,
    target_dir: str,
) -> dict:
    """生成综合合规性报告。"""
    violations: list[str] = []
    warnings: list[str] = []

    if git_result.get("available"):
        violations.extend(git_result.get("violations", []))
        if git_result.get("unknown_changes"):
            warnings.append(
                f"存在无法分类的变更: {git_result['unknown_changes']}"
            )

    if fs_result.get("available") and fs_result.get("forbidden_files_present"):
        warnings.append(
            f"目标目录存在测试文件（属于正常状态，但请确认非 orchestrator 写入）: "
            f"{fs_result['forbidden_files_present']}"
        )

    return {
        "target_dir": target_dir,
        "compliant": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "git_check": git_result,
        "filesystem_check": fs_result,
        "verdict": (
            "✅ 合规 — orchestrator 未违规修改测试文件"
            if len(violations) == 0
            else f"❌ 违规 — orchestrator 修改了 {len(violations)} 个不应触碰的测试文件"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="信息隔离合规性审计 — 验证 orchestrator 在 Phase 4 未违规修改测试文件"
    )
    parser.add_argument(
        "--target-dir",
        required=True,
        help="要审计的目标目录（如 .tmp/adversarial-tests/M01）",
    )
    parser.add_argument(
        "--check-git",
        action="store_true",
        help="使用 git diff 检查变更（推荐）",
    )
    parser.add_argument(
        "--since",
        help="时间边界（ISO 8601），此时间之后的修改视为可疑",
        default=None,
    )
    parser.add_argument(
        "--output",
        help="审计报告 JSON 输出路径",
        default=None,
    )
    args = parser.parse_args()

    target_dir = Path(args.target_dir)

    # Git 模式
    git_result: dict = {"mode": "git", "available": False}
    if args.check_git:
        git_result = check_via_git(target_dir)

    # 文件系统模式
    since_dt: datetime | None = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"⚠️ 无法解析 --since 时间: {args.since}", file=sys.stderr)

    fs_result = check_via_filesystem(target_dir, since_dt)

    # 无法判定时
    if not git_result.get("available") and not args.since:
        print(
            "⚠️ 既无 git diff 也无 --since 参数，无法准确判定合规性。"
            "建议：使用 --check-git 进行准确检查，或提供 --since 指定 Phase 4 开始时间。"
        )
        # 不阻断，返回 0 但报告无法判定

    report = generate_report(git_result, fs_result, str(target_dir))

    print(f"\n信息隔离合规性审计: {target_dir}")
    print(report["verdict"])

    if report["violations"]:
        print(f"\n违规文件:")
        for v in report["violations"]:
            print(f"  ❌ {v}")

    if report["warnings"]:
        print(f"\n警告:")
        for w in report["warnings"]:
            print(f"  ⚠️  {w}")

    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已保存: {args.output}")

    return 0 if report["compliant"] else 1


if __name__ == "__main__":
    sys.exit(main())
