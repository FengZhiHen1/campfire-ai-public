#!/usr/bin/env python3
"""
验证 contract-expectations.md 的结构正确性和完整性。
由 orchestrator Phase 1 输出后、Phase 3 使用前调用。

用法:
    python validate_contract_expectations.py <path/to/contract-expectations.md> [--function-signatures <path/to/function-signatures.json>]

退出码:
    0 - 验证通过
    1 - 验证失败
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_markdown_table(text: str) -> list:
    """
    从 Markdown 文本中提取表格数据。
    返回 list[dict]，每个 dict 对应表格一行。
    """
    lines = text.strip().splitlines()
    tables = []
    current_table = []
    in_table = False
    header = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not in_table:
                # 第一行是表头
                header = cells
                in_table = True
            elif all(re.match(r"^[-:]+$", c.replace(" ", "")) for c in cells):
                # 分隔行，跳过
                continue
            else:
                current_table.append(cells)
        else:
            if in_table and current_table:
                tables.append((header, current_table))
            in_table = False
            current_table = []
            header = None

    if in_table and current_table:
        tables.append((header, current_table))

    # 合并所有表格为一个列表
    all_rows = []
    for hdr, rows in tables:
        for row in rows:
            if len(row) == len(hdr):
                all_rows.append(dict(zip(hdr, row)))
    return all_rows


def extract_front_matter(text: str) -> dict:
    """提取文件头部的冻结信息。"""
    fm = {}
    for line in text.splitlines()[:10]:
        m = re.match(r"> 来源\s*[:：]\s*(.+)", line)
        if m:
            fm["source"] = m.group(1).strip()
        m = re.match(r"> 冻结时间\s*[:：]\s*(.+)", line)
        if m:
            fm["frozen_at"] = m.group(1).strip()
        m = re.match(r"# .+契约期望清单", line)
        if m:
            fm["has_title"] = True
    return fm


def validate_structure(text: str) -> list:
    """结构级验证。"""
    errors = []

    fm = extract_front_matter(text)
    if not fm.get("has_title"):
        errors.append("文件缺少一级标题 '# 契约期望清单'")
    if not fm.get("source"):
        errors.append("文件头部缺少来源标注（如 '> 来源: M01-落地规范.md'）")
    if not fm.get("frozen_at"):
        errors.append("文件头部缺少冻结时间标注（如 '> 冻结时间: 2024-01-15 10:30:00'）")

    rows = parse_markdown_table(text)
    if not rows:
        errors.append("文件中未找到任何有效表格数据")
        return errors

    seen_ids = set()
    for idx, row in enumerate(rows):
        prefix = f"表格第 {idx + 1} 行"

        # 编号
        cid = row.get("编号", "")
        if not cid:
            errors.append(f"{prefix}: 缺少编号")
        elif not re.match(r"^[A-Z]\d{2,3}$", str(cid)):
            errors.append(f"{prefix}: 编号 '{cid}' 不符合格式 [A-Z]\\d{{2,3}} (如 A01, B123)")
        elif cid in seen_ids:
            errors.append(f"{prefix}: 编号 '{cid}' 重复")
        else:
            seen_ids.add(cid)

        # 契约维度
        dim = row.get("契约维度", "")
        if not dim:
            errors.append(f"{prefix}: 缺少契约维度")

        # 破坏性输入
        attack = row.get("破坏性输入", "")
        if not attack:
            errors.append(f"{prefix}: 缺少破坏性输入")
        elif len(attack) < 3:
            errors.append(f"{prefix}: 破坏性输入 '{attack}' 过于简短，无法指导测试生成")

        # 期望行为
        expect = row.get("期望行为", "")
        if not expect:
            errors.append(f"{prefix}: 缺少期望行为")
        elif not any(kw in expect for kw in ["抛出", "返回", "raise", "return", "Error", "None", "[]", "{}"]):
            errors.append(
                f"{prefix}: 期望行为 '{expect}' 未明确说明结果形式（抛出/返回/值），测试生成器无法编写断言"
            )

        # 来源章节
        ref = row.get("来源章节", "")
        if not ref:
            errors.append(f"{prefix}: 缺少来源章节")
        elif not re.match(r"^§\d+(\.\d+)*$", str(ref)):
            errors.append(f"{prefix}: 来源章节 '{ref}' 不符合 §N.N 格式")

    return errors


def validate_completeness(rows: list, sig_path: str = None) -> list:
    """完整性验证：对照函数签名清单检查覆盖度。"""
    errors = []

    if not sig_path:
        return errors

    if not Path(sig_path).exists():
        errors.append(f"函数签名清单文件不存在: {sig_path}")
        return errors

    try:
        with open(sig_path, "r", encoding="utf-8") as f:
            sig_data = json.load(f)
    except Exception as e:
        errors.append(f"无法读取函数签名清单: {e}")
        return errors

    func_names = {fn["name"] for fn in sig_data.get("functions", [])}
    covered_funcs = set()

    for row in rows:
        dim = row.get("契约维度", "")
        # 尝试从契约维度中提取函数名（常见格式："函数名 参数名" 或 "函数名: ..."）
        for fn_name in func_names:
            if fn_name in dim:
                covered_funcs.add(fn_name)

    uncovered = func_names - covered_funcs
    if uncovered:
        errors.append(
            f"以下公开函数在契约期望清单中无对应条目（每个函数至少应有一个契约维度）: {', '.join(sorted(uncovered))}"
        )

    return errors


def main():
    if sys.version_info < (3, 8):
        print("错误: 需要 Python 3.8+", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="验证契约期望清单")
    parser.add_argument("path", help="contract-expectations.md 的路径")
    parser.add_argument("--function-signatures", help="function-signatures.json 的路径（可选，用于完整性检查）")
    args = parser.parse_args()

    if not Path(args.path).exists():
        print(json.dumps({"valid": False, "errors": [f"文件不存在: {args.path}"]}, ensure_ascii=False, indent=2))
        sys.exit(1)

    text = Path(args.path).read_text(encoding="utf-8")
    errors = validate_structure(text)

    rows = parse_markdown_table(text)
    if args.function_signatures:
        errors.extend(validate_completeness(rows, args.function_signatures))

    report = {
        "valid": len(errors) == 0,
        "file": args.path,
        "expectation_count": len(rows),
        "errors": errors,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
