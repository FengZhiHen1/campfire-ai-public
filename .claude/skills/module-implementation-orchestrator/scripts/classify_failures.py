#!/usr/bin/env python3
"""
辅助判定测试失败类型：实现漏洞 / 测试代码缺陷 / 契约矛盾。
由 orchestrator Phase 4.2 调用，作为人工判定的辅助参考。

用法:
    python scripts/classify_failures.py \
        --test-output /tmp/pytest-output.txt \
        --framework pytest \
        --contract contract-expectations.md \
        --signatures function-signatures.json \
        --output classification.json

输出:
    JSON 格式的分类结果，每个失败用例标注:
    - classification: "implementation_bug" | "test_bug" | "contract_contradiction" | "uncertain"
    - confidence: 0.0-1.0
    - rationale: 判定依据

退出码:
    0 - 分类完成（即使存在 uncertain 项）
    1 - 输入文件缺失或解析失败
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ClassifiedFailure:
    test_name: str
    error_type: str
    error_msg: str
    classification: str  # implementation_bug | test_bug | contract_contradiction | uncertain
    confidence: float
    rationale: str


# ═══════════════════════════════════════════════════════════════════════════════
# 信号检测规则
# ═══════════════════════════════════════════════════════════════════════════════

# 强信号：几乎可以确定分类
TEST_BUG_PATTERNS = [
    (r"(?i)import\s*error", 0.95, "导入错误 — 测试代码的依赖声明或路径有问题"),
    (r"(?i)module\s*not\s*found", 0.95, "模块未找到 — 测试的导入路径不正确"),
    (r"(?i)attribute\s*error.*has\s*no\s*attribute.*test", 0.90, "测试代码引用了不存在的属性"),
    (r"(?i)syntax\s*error", 0.99, "语法错误 — 测试代码本身无法解析"),
    (r"(?i)name\s*error.*is\s*not\s*defined", 0.85, "NameError — 测试代码使用了未定义的变量"),
    (r"(?i)fixture.*not\s*found", 0.90, "Fixture 未找到 — 测试基础设施问题"),
    (r"(?i)no\s*module\s*named", 0.95, "模块导入失败 — 测试环境配置问题"),
]

CONTRACT_CONTRADICTION_PATTERNS = [
    (r"(?i)assertion\s*error.*expected.*but.*got", 0.60,
     "断言失败 — 需人工确认是契约矛盾还是实现缺陷"),
    (r"(?i)expected.*none.*but.*got", 0.50,
     "返回值期望不符 — 需对照契约确认期望是否正确"),
]

IMPLEMENTATION_BUG_PATTERNS = [
    (r"(?i)type\s*error.*none\s*type", 0.85, "参数类型校验缺失 — 实现未处理 None 值"),
    (r"(?i)value\s*error", 0.70, "值域校验缺失 — 实现未验证参数范围"),
    (r"(?i)runtime\s*error", 0.75, "运行时状态检查缺失"),
    (r"(?i)key\s*error", 0.80, "键访问缺少存在性检查"),
    (r"(?i)index\s*error", 0.80, "索引访问缺少边界检查"),
    (r"(?i)zero\s*division\s*error", 0.85, "除零未防护"),
    (r"(?i)attribute\s*error.*none", 0.80, "None 属性访问 — 空值链未处理"),
    (r"(?i)unbound\s*local\s*error", 0.85, "变量未绑定 — 代码路径遗漏"),
]


def classify_single(
    test_name: str,
    error_type: str,
    error_msg: str,
    contract_rows: list[dict],
) -> ClassifiedFailure:
    """对单个失败用例进行分类判定。"""

    combined = f"{error_type} {error_msg}"

    # 1. 检测测试代码缺陷信号
    for pattern, confidence, rationale in TEST_BUG_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return ClassifiedFailure(
                test_name=test_name,
                error_type=error_type,
                error_msg=error_msg,
                classification="test_bug",
                confidence=confidence,
                rationale=rationale,
            )

    # 2. 检测实现漏洞信号
    for pattern, confidence, rationale in IMPLEMENTATION_BUG_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return ClassifiedFailure(
                test_name=test_name,
                error_type=error_type,
                error_msg=error_msg,
                classification="implementation_bug",
                confidence=confidence,
                rationale=rationale,
            )

    # 3. 检测契约矛盾信号
    for pattern, confidence, rationale in CONTRACT_CONTRADICTION_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            # 进一步查证：错误消息中是否出现了契约中明确声明的行为
            contract_match = False
            for row in contract_rows:
                expect = row.get("期望行为", "")
                if expect and any(kw in error_msg for kw in expect.split() if len(kw) > 4):
                    contract_match = True
                    break

            if contract_match:
                return ClassifiedFailure(
                    test_name=test_name,
                    error_type=error_type,
                    error_msg=error_msg,
                    classification="contract_contradiction",
                    confidence=min(confidence + 0.15, 1.0),
                    rationale=f"{rationale}；错误消息与契约期望行为匹配",
                )

    # 4. 无法确定
    return ClassifiedFailure(
        test_name=test_name,
        error_type=error_type,
        error_msg=error_msg,
        classification="uncertain",
        confidence=0.0,
        rationale="无法自动判定，请人工审查错误消息和 traceback",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 测试输出解析（简化版，复用 generate_failure_summary.py 的解析逻辑）
# ═══════════════════════════════════════════════════════════════════════════════


def parse_pytest_failures(text: str) -> list[dict]:
    """从 pytest 输出提取失败用例列表。"""
    failures: list[dict] = []
    case_blocks = re.split(r"(?=FAILED [\w/\\_.-]+::)", text)

    for block in case_blocks:
        if "FAILED" not in block:
            continue

        test_match = re.search(r"FAILED [\w/\\_.:-]+::(\w+)", block)
        test_name = test_match.group(1) if test_match else "unknown"

        error_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*Error)\s*:\s*(.+?)(?:\n|$)", block)
        if not error_match:
            error_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*Exception)\s*:\s*(.+?)(?:\n|$)", block)
        if not error_match:
            error_match = re.search(r"AssertionError\s*:\s*(.+?)(?:\n|$)", block)
            if error_match:
                error_type = "AssertionError"
                error_msg = error_match.group(1).strip()
            else:
                error_type = "UnknownError"
                error_msg = "无法提取错误信息"
        else:
            error_type = error_match.group(1)
            error_msg = error_match.group(2).strip()

        failures.append({
            "test_name": test_name,
            "error_type": error_type,
            "error_msg": error_msg[:300],
        })

    return failures


def parse_jest_failures(text: str) -> list[dict]:
    """从 jest/vitest 输出提取失败用例列表。"""
    failures: list[dict] = []
    case_blocks = re.split(r"(?=^\s*●\s+)", text, flags=re.MULTILINE)

    for block in case_blocks:
        if not block.strip().startswith("●"):
            continue

        test_match = re.search(r"●\s*(.+?)(?:\n|$)", block)
        test_name = test_match.group(1).strip() if test_match else "unknown"

        error_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*Error)\s*:\s*(.+?)(?:\n|$)", block)
        if error_match:
            error_type = error_match.group(1)
            error_msg = error_match.group(2).strip()
        else:
            error_type = "AssertionError"
            error_msg = "断言失败（无法提取详细信息）"

        failures.append({
            "test_name": test_name,
            "error_type": error_type,
            "error_msg": error_msg[:300],
        })

    return failures


def parse_go_failures(text: str) -> list[dict]:
    """从 go test 输出提取失败用例列表。"""
    failures: list[dict] = []
    fail_blocks = re.findall(r"--- FAIL: (\S+) \([^)]+\)\n(.+?)(?=\n---|\nPASS|\nFAIL|\Z)", text, re.DOTALL)

    for test_name, block in fail_blocks:
        error_match = re.search(r"(\S+_test\.go:\d+):\s*(.+?)(?:\n|$)", block)
        error_msg = error_match.group(2).strip() if error_match else block.strip()[:200]

        error_type = "TestFailure"
        if "panic" in error_msg.lower():
            error_type = "Panic"
        elif "timeout" in error_msg.lower():
            error_type = "Timeout"

        failures.append({
            "test_name": test_name,
            "error_type": error_type,
            "error_msg": error_msg[:300],
        })

    return failures


def load_contract_rows(path: str) -> list[dict]:
    """从 contract-expectations.md 加载契约条目。"""
    text = Path(path).read_text(encoding="utf-8")
    rows: list[dict] = []
    header: list[str] | None = None
    in_table = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not in_table:
                header = cells
                in_table = True
            elif not all(re.match(r"^[-:]+$", c.replace(" ", "")) for c in cells):
                if header and len(cells) == len(header):
                    rows.append(dict(zip(header, cells)))
        else:
            in_table = False

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="辅助判定测试失败类型：实现漏洞 / 测试缺陷 / 契约矛盾"
    )
    parser.add_argument("--test-output", required=True, help="测试框架原始输出文件路径")
    parser.add_argument("--framework", required=True, choices=["pytest", "jest", "go"], help="测试框架类型")
    parser.add_argument("--contract", required=True, help="契约期望清单路径")
    parser.add_argument("--signatures", help="函数签名清单路径（可选）")
    parser.add_argument("--output", required=True, help="分类结果 JSON 输出路径")
    args = parser.parse_args()

    # 加载测试输出
    test_text = Path(args.test_output).read_text(encoding="utf-8")

    # 加载契约清单
    contract_rows = load_contract_rows(args.contract)

    # 解析失败用例
    if args.framework == "pytest":
        failures = parse_pytest_failures(test_text)
    elif args.framework == "jest":
        failures = parse_jest_failures(test_text)
    else:
        failures = parse_go_failures(test_text)

    # 分类
    classified: list[dict] = []
    for f in failures:
        result = classify_single(
            test_name=f["test_name"],
            error_type=f["error_type"],
            error_msg=f["error_msg"],
            contract_rows=contract_rows,
        )
        classified.append({
            "test_name": result.test_name,
            "error_type": result.error_type,
            "error_msg": result.error_msg[:200],
            "classification": result.classification,
            "confidence": result.confidence,
            "rationale": result.rationale,
        })

    # 统计
    counts = {"implementation_bug": 0, "test_bug": 0, "contract_contradiction": 0, "uncertain": 0}
    for c in classified:
        counts[c["classification"]] = counts.get(c["classification"], 0) + 1

    report = {
        "summary": {
            "total_failures": len(classified),
            "by_type": counts,
        },
        "failures": classified,
        "usage_note": (
            "此分类为自动判定辅助，不可替代人工审查。"
            "特别是 classification=uncertain 或 confidence<0.8 的条目，"
            "orchestrator 必须人工复核。"
        ),
    }

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"分类完成: {args.output}")
    print(f"  总计: {counts}")
    print(f"  ⚠️  uncertain 项需要人工复核" if counts["uncertain"] > 0 else "  全部自动分类完成")

    return 0


if __name__ == "__main__":
    sys.exit(main())
