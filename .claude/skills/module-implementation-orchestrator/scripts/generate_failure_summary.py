#!/usr/bin/env python3
"""
从测试运行输出（pytest / jest / Go test）自动生成 failure-summary-round-N.md。
由 orchestrator Phase 4 调用。

用法:
    python generate_failure_summary.py \
        --test-output <path/to/test-output.txt> \
        --framework {pytest,jest,go} \
        --contract <path/to/contract-expectations.md> \
        --signatures <path/to/function-signatures.json> \
        --round <N> \
        --max-rounds <M> \
        --output <path/to/failure-summary-round-N.md>

输入:
    test-output.txt    测试框架原始输出（重定向保存的文件）
    contract           契约期望清单（用于匹配条款）
    signatures         函数签名清单（用于提取函数名和参数）

输出:
    failure-summary-round-N.md  符合 references/failure-summary-format.md 规范
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FailureCase:
    case_id: str
    error_type: str
    error_msg: str
    test_name: str
    involved_function: Optional[str] = None
    involved_param: Optional[str] = None
    contract_clause: Optional[str] = None
    fix_suggestion: Optional[str] = None
    raw_traceback: str = ""


@dataclass
class ParseResult:
    total: int = 0
    passed: int = 0
    failed: int = 0
    cases: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# 框架专用解析器
# ═══════════════════════════════════════════════════════════════════════════════


def parse_pytest_output(text: str, function_names: list, param_names: list) -> ParseResult:
    """
    解析 pytest -v --tb=short 的输出。

    pytest 输出模式:
        FAILED tests/test_module.py::test_func_name - ErrorType: message
        或
        tests/test_module.py::test_func_name FAILED
        ...
        >       result = calculate_limit(None)
        E       TypeError: unsupported operand type(s)...
    """
    result = ParseResult()

    # 提取总数
    summary_match = re.search(
        r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) error)?",
        text,
        re.IGNORECASE,
    )
    if summary_match:
        result.passed = int(summary_match.group(1))
        result.failed = int(summary_match.group(2) or 0) + int(summary_match.group(3) or 0)
        result.total = result.passed + result.failed

    # 如果 summary 未匹配，尝试统计 FAILED 行
    if result.total == 0:
        failed_lines = re.findall(r"\bFAILED\b", text)
        passed_lines = re.findall(r"\bpassed\b", text)
        result.failed = len(failed_lines)
        # passed 数量需要从 summary 获取，这里先估算

    # 逐条解析失败用例
    # pytest 的 short traceback 通常包含如下结构
    case_blocks = re.split(r"(?=FAILED [\w/\\_.-]+::)", text)

    for block in case_blocks:
        if "FAILED" not in block:
            continue

        # 提取测试名
        test_match = re.search(r"FAILED [\w/\\_.:-]+::(\w+)", block)
        test_name = test_match.group(1) if test_match else "unknown"

        # 提取错误类型和消息
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
                error_msg = "无法从输出中提取错误信息"
        else:
            error_type = error_match.group(1)
            error_msg = error_match.group(2).strip()

        # 推断涉及函数：从 traceback 的调用栈最后一行提取
        involved_function = None
        for fn_name in sorted(function_names, key=len, reverse=True):
            if fn_name in block:
                involved_function = fn_name
                break

        # 推断涉及参数：从错误消息或代码行中提取
        involved_param = None
        for p_name in sorted(param_names, key=len, reverse=True):
            if p_name in error_msg or p_name in block:
                involved_param = p_name
                break

        # 如果 traceback 中有 "def func_name(param=" 这样的行，优先提取
        def_match = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\b(\w+)\b", block)
        if def_match:
            if not involved_function:
                involved_function = def_match.group(1)
            if not involved_param:
                involved_param = def_match.group(2)

        case = FailureCase(
            case_id="",  # 稍后分配
            error_type=error_type,
            error_msg=error_msg[:200],  # 截断过长消息
            test_name=test_name,
            involved_function=involved_function,
            involved_param=involved_param,
            raw_traceback=block[:2000],
        )
        result.cases.append(case)

    return result


def parse_jest_output(text: str, function_names: list, param_names: list) -> ParseResult:
    """
    解析 jest / vitest 的输出。

    模式:
        FAIL  path/to/test.test.ts
        ● test description

          expect(received).toBe(expected)
          Error: message
            at functionName (path:line:col)
    """
    result = ParseResult()

    # 提取 summary: Tests: N failed, M passed, K total
    summary_match = re.search(
        r"Tests:\s*(\d+)\s*failed,?\s*(\d+)\s*passed,?\s*(?:of\s*)?(\d+)\s*total",
        text,
        re.IGNORECASE,
    )
    if summary_match:
        result.failed = int(summary_match.group(1))
        result.passed = int(summary_match.group(2))
        result.total = int(summary_match.group(3))
    else:
        # 备用模式
        failed_count = len(re.findall(r"^\s*●\s+", text, re.MULTILINE))
        result.failed = failed_count
        result.total = failed_count  # 需外部补充

    # 按 ● 分割测试用例
    case_blocks = re.split(r"(?=^\s*●\s+)", text, flags=re.MULTILINE)

    for block in case_blocks:
        if not block.strip().startswith("●"):
            continue

        # 提取测试名
        test_match = re.search(r"●\s*(.+?)(?:\n|$)", block)
        test_name = test_match.group(1).strip() if test_match else "unknown"

        # 提取错误类型
        error_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*Error)\s*:\s*(.+?)(?:\n|$)", block)
        if error_match:
            error_type = error_match.group(1)
            error_msg = error_match.group(2).strip()
        else:
            # 可能是 assertion 失败
            if "expect" in block or "Expected" in block:
                error_type = "AssertionError"
                exp_match = re.search(r"Expected:\s*(.+?)(?:\n|$)", block)
                error_msg = f"断言失败: {exp_match.group(1).strip() if exp_match else '期望值不符'}"
            else:
                error_type = "UnknownError"
                error_msg = "无法提取错误信息"

        # 从 stack trace 提取函数
        involved_function = None
        for fn_name in sorted(function_names, key=len, reverse=True):
            if fn_name in block:
                involved_function = fn_name
                break

        # stack trace 中的 "at functionName " 优先
        at_match = re.search(r"at\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", block)
        if at_match and at_match.group(1) not in ("describe", "it", "test", "beforeEach", "afterEach"):
            involved_function = at_match.group(1)

        involved_param = None
        for p_name in sorted(param_names, key=len, reverse=True):
            if p_name in error_msg or p_name in block:
                involved_param = p_name
                break

        case = FailureCase(
            case_id="",
            error_type=error_type,
            error_msg=error_msg[:200],
            test_name=test_name,
            involved_function=involved_function,
            involved_param=involved_param,
            raw_traceback=block[:2000],
        )
        result.cases.append(case)

    return result


def parse_go_output(text: str, function_names: list, param_names: list) -> ParseResult:
    """
    解析 go test -v 的输出。

    模式:
        --- FAIL: TestFuncName (0.00s)
            file_test.go:42: Error message
    """
    result = ParseResult()

    # 提取 summary: FAIL or PASS counts
    summary_match = re.search(r"^(FAIL|PASS)\s*$", text, re.MULTILINE)
    # go test 的 summary 较简单，失败行数直接统计
    fail_blocks = re.findall(r"--- FAIL: (\S+) \([^)]+\)\n(.+?)(?=\n---|\nPASS|\nFAIL|\Z)", text, re.DOTALL)
    result.failed = len(fail_blocks)

    for test_name, block in fail_blocks:
        # 从 block 提取错误
        error_match = re.search(r"(\S+_test\.go:\d+):\s*(.+?)(?:\n|$)", block)
        if error_match:
            error_msg = error_match.group(2).strip()
        else:
            error_msg = block.strip()[:200]

        # Go 错误通常没有显式类型，根据消息推断
        if "panic" in error_msg.lower():
            error_type = "Panic"
        elif "timeout" in error_msg.lower():
            error_type = "Timeout"
        else:
            error_type = "TestFailure"

        involved_function = None
        # 测试名通常是 TestFuncName，去除 Test 前缀
        clean_name = re.sub(r"^Test", "", test_name)
        for fn_name in sorted(function_names, key=len, reverse=True):
            if fn_name in clean_name or fn_name in block:
                involved_function = fn_name
                break

        involved_param = None
        for p_name in sorted(param_names, key=len, reverse=True):
            if p_name in error_msg or p_name in block:
                involved_param = p_name
                break

        case = FailureCase(
            case_id="",
            error_type=error_type,
            error_msg=error_msg,
            test_name=test_name,
            involved_function=involved_function,
            involved_param=involved_param,
            raw_traceback=block[:2000],
        )
        result.cases.append(case)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 契约匹配与修复建议生成
# ═══════════════════════════════════════════════════════════════════════════════


def load_contract_expectations(path: str) -> list:
    """从 contract-expectations.md 解析契约条目。"""
    text = Path(path).read_text(encoding="utf-8")
    rows = []
    in_table = False
    header = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not in_table:
                header = cells
                in_table = True
            elif all(re.match(r"^[-:]+$", c.replace(" ", "")) for c in cells):
                continue
            else:
                if len(cells) == len(header):
                    rows.append(dict(zip(header, cells)))
        else:
            in_table = False
    return rows


def match_contract_clause(case: FailureCase, contract_rows: list) -> Optional[str]:
    """
    将失败用例与契约条款匹配。

    匹配优先级（从高到低）:
    1. 涉及函数名 + 涉及参数名 同时出现在契约维度中
    2. 涉及函数名 出现在契约维度中
    3. 错误类型与契约期望行为的关键词匹配
    """
    for row in contract_rows:
        dim = row.get("契约维度", "")
        expect = row.get("期望行为", "")
        clause = row.get("来源章节", "")

        fn = case.involved_function or ""
        param = case.involved_param or ""

        # 最高优先级：函数名 + 参数名同时命中
        if fn and param and fn in dim and param in dim:
            case.contract_clause = clause
            return clause

        # 高优先级：函数名命中
        if fn and fn in dim:
            case.contract_clause = clause
            return clause

        # 中优先级：参数名命中
        if param and param in dim:
            case.contract_clause = clause
            return clause

        # 低优先级：错误类型与期望行为匹配
        error_lower = case.error_type.lower()
        if error_lower in expect.lower():
            case.contract_clause = clause
            return clause

    return None


def generate_fix_suggestion(case: FailureCase) -> str:
    """基于错误类型自动生成修复建议。"""
    et = case.error_type
    fn = case.involved_function or "相关函数"
    param = case.involved_param

    if "TypeError" in et:
        target = f"参数 '{param}'" if param else "参数"
        return f"在 {fn} 入口处添加 {target} 的类型校验和非空校验"
    if "ValueError" in et:
        target = f"参数 '{param}'" if param else "参数"
        return f"在 {fn} 入口处添加 {target} 的值域/格式校验"
    if "AssertionError" in et:
        return f"检查 {fn} 的返回值是否符合契约要求"
    if "IndexError" in et or "KeyError" in et:
        return f"在 {fn} 中添加容器访问前的边界/存在性校验"
    if "Timeout" in et or "timeout" in case.error_msg.lower():
        return f"检查 {fn} 中的外部调用是否设置了超时和重试机制"
    if "RuntimeError" in et:
        return f"检查 {fn} 中的状态校验逻辑是否完整"
    if "Panic" in et:
        return f"在 {fn} 中添加 defer/recover 或前置条件校验"

    return f"检查 {fn} 的实现，根据契约条款修复异常处理或返回值"


def deduplicate_cases(cases: list) -> list:
    """按错误类型 + 涉及函数 + 涉及参数去重。"""
    seen = set()
    unique = []
    for c in cases:
        key = (c.error_type, c.involved_function, c.involved_param)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def generate_report(result: ParseResult, contract_rows: list, round_num: int, max_rounds: int) -> str:
    """生成 failure-summary-round-N.md 内容。"""

    # 去重
    cases = deduplicate_cases(result.cases)

    # 分配 case ID
    for idx, c in enumerate(cases):
        c.case_id = f"case-{idx + 1:03d}"
        if not c.contract_clause:
            match_contract_clause(c, contract_rows)
        if not c.fix_suggestion:
            c.fix_suggestion = generate_fix_suggestion(c)

    # 分类统计
    error_type_counts = {}
    func_involvement = {}
    clause_failures = {}
    for c in cases:
        error_type_counts[c.error_type] = error_type_counts.get(c.error_type, 0) + 1
        fn = c.involved_function or "未知函数"
        func_involvement[fn] = func_involvement.get(fn, 0) + 1
        cl = c.contract_clause or "未匹配"
        clause_failures[cl] = clause_failures.get(cl, 0) + 1

    # 修复优先级建议（按影响用例数排序）
    priority_groups = {}
    for c in cases:
        key = (c.error_type, c.fix_suggestion)
        priority_groups[key] = priority_groups.get(key, 0) + 1
    sorted_priorities = sorted(priority_groups.items(), key=lambda x: -x[1])

    lines = [
        f"## 盲测失败摘要（第 {round_num} 轮）",
        "",
        f"- **测试轮次**：{round_num} / {max_rounds}",
        f"- **总用例数**：{result.total}",
        f"- **通过数**：{result.passed}",
        f"- **失败数**：{len(cases)}（去重后，原始失败 {result.failed}）",
        "",
        "---",
        "",
        "### 失败用例摘要",
        "",
    ]

    for c in cases:
        lines.append(f"#### [{c.case_id}] {c.error_type}: {c.error_msg[:80]}")
        lines.append(f"- **涉及函数**：`{c.involved_function or '未能自动推断'}`")
        if c.involved_param:
            lines.append(f"- **涉及参数**：`{c.involved_param}`")
        lines.append(f"- **契约条款**：{c.contract_clause or '未能自动匹配，需人工确认'} — \"{c.contract_clause or ''}\"")
        lines.append(f"- **失败原因**：{c.error_msg}")
        lines.append(f"- **修复建议**：{c.fix_suggestion}")
        lines.append("")

    lines.extend([
        "### 分类统计",
        "",
        "| 错误类型 | 数量 | 涉及函数 |",
        "|:---|:---|:---|",
    ])
    for et, count in sorted(error_type_counts.items(), key=lambda x: -x[1]):
        funcs = [fn for fn, cnt in func_involvement.items() if any(c.error_type == et and c.involved_function == fn for c in cases)]
        lines.append(f"| {et} | {count} | {', '.join(funcs) or '-'} |")

    lines.extend([
        "",
        "### 涉及的契约条款",
        "",
        "| 条款编号 | 失败次数 |",
        "|:---|:---|",
    ])
    for cl, count in sorted(clause_failures.items(), key=lambda x: -x[1]):
        lines.append(f"| {cl} | {count} |")

    lines.extend([
        "",
        "### 修复方向建议",
        "",
        "基于本轮失败分析，建议按以下优先级修复：",
        "",
    ])

    priority_level = ["高", "中", "低"]
    for idx, ((et, suggestion), count) in enumerate(sorted_priorities):
        level = priority_level[min(idx, 2)]
        lines.append(f"{idx + 1}. **{level}优先级** — {suggestion}（影响 {count} 个去重用例）")

    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    if sys.version_info < (3, 8):
        print("错误: 需要 Python 3.8+", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="从测试输出自动生成失败摘要")
    parser.add_argument("--test-output", required=True, help="测试框架原始输出文件路径")
    parser.add_argument("--framework", required=True, choices=["pytest", "jest", "go"], help="测试框架类型")
    parser.add_argument("--contract", required=True, help="契约期望清单路径")
    parser.add_argument("--signatures", required=True, help="函数签名清单路径")
    parser.add_argument("--round", type=int, required=True, help="当前轮次编号")
    parser.add_argument("--max-rounds", type=int, default=3, help="最大轮次（默认 3）")
    parser.add_argument("--output", required=True, help="输出文件路径")
    args = parser.parse_args()

    # 加载函数签名
    try:
        with open(args.signatures, "r", encoding="utf-8") as f:
            sig_data = json.load(f)
    except Exception as e:
        print(f"错误: 无法读取函数签名清单: {e}", file=sys.stderr)
        sys.exit(1)

    function_names = [fn["name"] for fn in sig_data.get("functions", [])]
    param_names = []
    for fn in sig_data.get("functions", []):
        for p in fn.get("parameters", []):
            param_names.append(p.get("name", ""))
    param_names = list(set(filter(None, param_names)))

    # 加载测试输出
    test_text = Path(args.test_output).read_text(encoding="utf-8")

    # 加载契约期望
    contract_rows = load_contract_expectations(args.contract)

    # 解析
    if args.framework == "pytest":
        result = parse_pytest_output(test_text, function_names, param_names)
    elif args.framework == "jest":
        result = parse_jest_output(test_text, function_names, param_names)
    else:
        result = parse_go_output(test_text, function_names, param_names)

    # 如果 summary 未解析出 total，用 case 数量估算
    if result.total == 0:
        result.total = len(result.cases)
    if result.passed == 0 and result.total > 0:
        result.passed = result.total - len(result.cases)

    # 生成报告
    report_md = generate_report(result, contract_rows, args.round, args.max_rounds)

    # 写入
    Path(args.output).write_text(report_md, encoding="utf-8")
    print(f"已生成失败摘要: {args.output}")
    print(f"  总用例: {result.total}, 通过: {result.passed}, 失败(去重): {len(result.cases)}")
    if not result.cases:
        print("  所有测试通过，无需修复。")


if __name__ == "__main__":
    main()
