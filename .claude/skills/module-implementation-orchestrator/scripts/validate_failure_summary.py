#!/usr/bin/env python3
"""
验证 failure-summary-round-N.md 是否符合格式规范和信息隔离要求。
由 orchestrator Phase 4 输出后、Phase 5 使用前调用。

用法:
    python validate_failure_summary.py <path/to/failure-summary-round-N.md>

检查项:
    1. 结构合规性（必填字段、表格格式）
    2. 信息隔离合规性（未泄露测试代码、输入值、文件路径）
    3. case ID 连续性
    4. 修复建议的可操作性

退出码:
    0 - 验证通过
    1 - 验证失败
"""

import json
import re
import sys
from pathlib import Path


def load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def validate_structure(text: str) -> list:
    """结构级验证。"""
    errors = []

    # 标题
    if not re.search(r"^## 盲测失败摘要（第 \d+ 轮）", text, re.MULTILINE):
        errors.append("缺少标准标题 '## 盲测失败摘要（第 N 轮）'")

    # 元信息字段
    required_fields = ["测试轮次", "总用例数", "通过数", "失败数"]
    for field in required_fields:
        if field not in text:
            errors.append(f"缺少元信息字段: {field}")

    # 必须包含的章节
    required_sections = ["失败用例摘要", "分类统计", "涉及的契约条款", "修复方向建议"]
    for sec in required_sections:
        pattern = rf"### {re.escape(sec)}"
        if not re.search(pattern, text):
            errors.append(f"缺少标准章节: ### {sec}")

    return errors


def validate_information_isolation(text: str) -> list:
    """
    信息隔离验证：确保未向修复者泄露不应看到的信息。

    禁止出现的内容:
    - 完整测试代码块（``` 包裹的多行代码）
    - 测试文件路径（如 test_*.py, *.test.ts）
    - 具体的输入值（除非值本身就是类型名如 None, ""）
    - 其他测试的通过情况细节
    """
    errors = []

    # 禁止泄露测试代码
    code_blocks = re.findall(r"```[\s\S]*?```", text)
    for block in code_blocks:
        # 允许少量内联代码（如 `raise ValueError(...)`）
        if block.count("\n") > 3:
            errors.append(
                f"信息隔离违规：发现多行代码块（{block.count(chr(10))} 行），"
                "可能泄露测试代码。只允许单行内联代码。"
            )

    # 禁止泄露测试文件路径
    test_file_patterns = [
        r"test_[\w/\\_.-]+\.(py|ts|js|go)",
        r"[\w/\\_.-]+\.(test|spec)\.(ts|js|tsx|jsx)",
        r"[\w/\\_.-]+_test\.go",
    ]
    for pattern in test_file_patterns:
        matches = re.findall(pattern, text)
        if matches:
            errors.append(
                f"信息隔离违规：发现测试文件路径引用（如 {matches[0]}），"
                "不得向修复者暴露测试文件位置。"
            )

    # 禁止泄露隔离目录路径
    if ".tmp/adversarial-tests/" in text:
        errors.append(
            "信息隔离违规：发现对抗性测试目录路径 '.tmp/adversarial-tests/'，"
            "不得向修复者暴露测试存储位置。"
        )

    # 检查是否包含 pytest/jest 原始输出
    if "pytest " in text and ("PASSED" in text or "FAILED" in text):
        errors.append(
            "信息隔离违规：文本包含 pytest 原始输出痕迹（PASSED/FAILED 标记），"
            "失败摘要必须经过提炼，不能直接复制测试框架输出。"
        )

    return errors


def validate_cases(text: str) -> list:
    """验证 case 条目的质量。"""
    errors = []

    case_blocks = re.findall(
        r"#### \[(case-\d+)\]\s*(.+?)(?=\n#### |\n### |\Z)",
        text,
        re.DOTALL,
    )

    if not case_blocks:
        # 可能是全部通过的情况，不需要 case
        return errors

    seen_ids = []
    for case_id, body in case_blocks:
        seen_ids.append(case_id)
        prefix = f"[{case_id}]"

        # 必须字段
        if "涉及函数" not in body:
            errors.append(f"{prefix} 缺少 '涉及函数'")
        if "契约条款" not in body:
            errors.append(f"{prefix} 缺少 '契约条款'")
        if "失败原因" not in body:
            errors.append(f"{prefix} 缺少 '失败原因'")
        if "修复建议" not in body:
            errors.append(f"{prefix} 缺少 '修复建议'")

        # 修复建议质量
        fix = re.search(r"修复建议\s*[:：]\s*(.+?)(?:\n|$)", body)
        if fix:
            suggestion = fix.group(1).strip()
            if len(suggestion) < 10:
                errors.append(f"{prefix} 修复建议过短（{len(suggestion)} 字符），不够具体")
            vague_words = ["检查", "看看", "可能", "大概", "似乎"]
            if any(w in suggestion for w in vague_words):
                errors.append(
                    f"{prefix} 修复建议包含模糊词汇（{', '.join(w for w in vague_words if w in suggestion)}），"
                    "应给出明确的动作（如'添加...'、'修改...'）"
                )

        # 契约条款格式
        clause = re.search(r"契约条款\s*[:：]\s*(.+?)(?:\n|$)", body)
        if clause:
            clause_text = clause.group(1).strip()
            if not re.search(r"§\d+(\.\d+)*", clause_text):
                errors.append(
                    f"{prefix} 契约条款 '{clause_text}' 未包含 §N.N 格式引用"
                )

    # 检查连续性
    if seen_ids:
        expected = [f"case-{i:03d}" for i in range(1, len(seen_ids) + 1)]
        if seen_ids != expected:
            errors.append(
                f"case ID 不连续: 实际 {seen_ids}, 期望 {expected}"
            )

    return errors


def validate_fix_suggestions_actionable(text: str) -> list:
    """验证修复建议是否可操作（不依赖看到测试代码）。"""
    errors = []

    # 提取所有修复建议
    suggestions = re.findall(r"修复建议\s*[:：]\s*(.+?)(?:\n|$)", text)
    for sug in suggestions:
        sug = sug.strip()
        # 修复建议不应引用测试中的具体值
        if re.search(r"输入值?\s*[:=]\s*['\"\d]", sug):
            errors.append(
                f"修复建议泄露了具体输入值: '{sug[:80]}...'。"
                "修复建议只能描述校验类型，不能写出测试使用的具体值。"
            )
        # 修复建议不应要求"参照测试"
        if "测试" in sug and ("参照" in sug or "按照" in sug or "根据" in sug):
            errors.append(
                f"修复建议暗示修复者应查看测试: '{sug[:80]}...'。"
                "修复者看不到测试，建议必须基于契约条款独立可执行。"
            )

    return errors


def main():
    if sys.version_info < (3, 8):
        print("错误: 需要 Python 3.8+", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print("用法: python validate_failure_summary.py <path/to/failure-summary.md>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    if not Path(path).exists():
        print(json.dumps({"valid": False, "errors": [f"文件不存在: {path}"]}, ensure_ascii=False, indent=2))
        sys.exit(1)

    text = load_text(path)

    errors = []
    errors.extend(validate_structure(text))
    errors.extend(validate_information_isolation(text))
    errors.extend(validate_cases(text))
    errors.extend(validate_fix_suggestions_actionable(text))

    report = {
        "valid": len(errors) == 0,
        "file": path,
        "errors": errors,
        "checks": {
            "structure": True,
            "information_isolation": True,
            "case_quality": True,
            "fix_actionability": True,
        }
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
