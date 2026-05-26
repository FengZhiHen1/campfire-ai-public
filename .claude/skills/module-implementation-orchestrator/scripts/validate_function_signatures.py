#!/usr/bin/env python3
"""
验证 function-signatures.json 的结构正确性和业务规则合规性。
由 orchestrator Phase 2 验证 SubAgent 输出时调用。

用法:
    python validate_function_signatures.py <path/to/function-signatures.json>

退出码:
    0 - 验证通过
    1 - 验证失败（stdout 输出 JSON 格式的错误报告）
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_structure(data: dict) -> list:
    """JSON Schema 级别的结构验证。"""
    errors = []

    # module_id
    if "module_id" not in data:
        errors.append("缺少必填字段: module_id")
    elif not re.match(r"^[A-Z]\d{2}$", str(data["module_id"])):
        errors.append(f"module_id '{data.get('module_id')}' 不符合模式 [A-Z]\\d{{2}} (如 M01)")

    # module_name
    if "module_name" not in data:
        errors.append("缺少必填字段: module_name")
    elif not data["module_name"] or len(data["module_name"]) > 100:
        errors.append("module_name 不能为空且不能超过 100 字符")

    # functions
    if "functions" not in data:
        errors.append("缺少必填字段: functions")
        return errors

    funcs = data["functions"]
    if not isinstance(funcs, list) or len(funcs) == 0:
        errors.append("functions 必须是非空数组")
        return errors

    seen_names = set()
    for idx, fn in enumerate(funcs):
        prefix = f"functions[{idx}]"
        if not isinstance(fn, dict):
            errors.append(f"{prefix} 必须是对象")
            continue

        # name
        name = fn.get("name")
        if not name:
            errors.append(f"{prefix}.name 缺失或为空")
        elif not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", str(name)):
            errors.append(f"{prefix}.name '{name}' 不是合法标识符")
        elif name in seen_names:
            errors.append(f"{prefix}.name '{name}' 重复定义")
        else:
            seen_names.add(name)

        # signature
        sig = fn.get("signature")
        if not sig:
            errors.append(f"{prefix}.signature 缺失或为空")

        # parameters
        params = fn.get("parameters")
        if not isinstance(params, list):
            errors.append(f"{prefix}.parameters 必须是数组")
            continue

        seen_param_names = set()
        for pidx, p in enumerate(params):
            p_prefix = f"{prefix}.parameters[{pidx}]"
            if not isinstance(p, dict):
                errors.append(f"{p_prefix} 必须是对象")
                continue
            pname = p.get("name")
            if not pname:
                errors.append(f"{p_prefix}.name 缺失或为空")
            elif not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", str(pname)):
                errors.append(f"{p_prefix}.name '{pname}' 不是合法标识符")
            elif pname in seen_param_names:
                errors.append(f"{p_prefix}.name '{pname}' 在同一函数内重复")
            else:
                seen_param_names.add(pname)

            if not p.get("type"):
                errors.append(f"{p_prefix}.type 缺失或为空")

            # required=false 时 default 应存在
            if p.get("required") is False and "default" not in p:
                errors.append(
                    f"{p_prefix}: required=false 但缺少 default 字段（应记录默认值表达式）"
                )

        # return_type
        if not fn.get("return_type"):
            errors.append(f"{prefix}.return_type 缺失或为空")

        # signature 与 parameters 的一致性
        if sig and params:
            for p in params:
                pname = p.get("name", "")
                if pname and pname not in str(sig):
                    errors.append(
                        f"{prefix}: 参数 '{pname}' 未出现在 signature '{sig}' 中"
                    )

        # exceptions
        exceptions = fn.get("exceptions", [])
        if isinstance(exceptions, list):
            for eidx, ex in enumerate(exceptions):
                if not isinstance(ex, dict):
                    errors.append(f"{prefix}.exceptions[{eidx}] 必须是对象")
                    continue
                cref = ex.get("contract_reference")
                if cref and not re.match(r"^§\d+\.\d+$", str(cref)):
                    errors.append(
                        f"{prefix}.exceptions[{eidx}].contract_reference '{cref}' 不符合 §N.N 格式"
                    )

    return errors


def validate_business_rules(data: dict) -> list:
    """业务规则验证：确保数据质量足以支撑后续阶段。"""
    errors = []
    funcs = data.get("functions", [])

    # 规则 1: 每个公开函数必须至少有一个参数或标记为无参数
    for fn in funcs:
        params = fn.get("parameters", [])
        if len(params) == 0 and "()" not in str(fn.get("signature", "")):
            errors.append(
                f"函数 '{fn['name']}': 无参数但 signature 不包含 '()'，请确认是否为无参函数"
            )

    # 规则 2: 如果声明了异常，每个异常必须有 trigger 或 contract_reference
    for fn in funcs:
        for ex in fn.get("exceptions", []):
            if not ex.get("trigger") and not ex.get("contract_reference"):
                errors.append(
                    f"函数 '{fn['name']}' 的异常 '{ex.get('type')}' 缺少 trigger 和 contract_reference，"
                    "测试生成器无法判断何时应触发该异常"
                )

    # 规则 3: 如果参数有 bounds，bounds 中至少有一个有效约束
    for fn in funcs:
        for p in fn.get("parameters", []):
            bounds = p.get("bounds")
            if bounds is not None:
                if not isinstance(bounds, dict):
                    errors.append(
                        f"函数 '{fn['name']}' 的参数 '{p['name']}' 的 bounds 必须是对象"
                    )
                elif not any(
                    k in bounds and bounds[k] is not None
                    for k in ("min", "max", "regex", "allowed_values")
                ):
                    errors.append(
                        f"函数 '{fn['name']}' 的参数 '{p['name']}' 的 bounds 对象没有有效约束字段"
                    )

    # 规则 4: 每个参数如果 required=true，建议有至少一个 constraint 或 bounds
    for fn in funcs:
        for p in fn.get("parameters", []):
            if p.get("required", True) is True:
                has_constraint = bool(p.get("constraints")) or bool(p.get("bounds"))
                if not has_constraint:
                    errors.append(
                        f"函数 '{fn['name']}' 的必填参数 '{p['name']}' 既无 constraints 也无 bounds，"
                        "对抗性测试将无从生成破坏性输入"
                    )

    return errors


def validate_module_id_consistency(data: dict, expected_module_id: str = None) -> list:
    """验证 module_id 与项目约定的模块编号是否一致。"""
    errors = []
    actual = data.get("module_id", "")

    if expected_module_id and actual != expected_module_id:
        errors.append(
            f"module_id '{actual}' 与设计文档或用户指令中的模块编号 '{expected_module_id}' 不一致。"
            f"请确认正确的模块编号（如 AIP-21、M01）并统一使用。"
        )

    # 额外启发式检查：常见错误模式
    if actual:
        # 检查是否使用了项目前缀但格式不对（如 P21 而不是 AIP-21）
        if re.match(r"^[A-Z]\d+$", actual) and not re.match(r"^[A-Z]\d{2}$", actual):
            errors.append(
                f"module_id '{actual}' 格式异常：使用了单字母+数字，但项目约定可能是多字母前缀（如 AIP-21）。"
                f"请检查设计文档中的模块编号定义。"
            )
        # 检查是否包含连字符但模式不匹配（如 AIP-21 应该匹配 [A-Z]\d{2} 吗？不，Schema 只允许 [A-Z]\d{2}）
        if "-" in actual:
            errors.append(
                f"module_id '{actual}' 包含连字符，但 JSON Schema 模式 [A-Z]\\d{{2}} 不允许。"
                f"如果项目约定使用连字符（如 AIP-21），需要同时更新 JSON Schema 和验证规则。"
            )

    return errors


def main():
    if sys.version_info < (3, 8):
        print("错误: 需要 Python 3.8+", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="验证函数签名清单")
    parser.add_argument("path", help="function-signatures.json 的路径")
    parser.add_argument(
        "--expected-module-id",
        help="预期的模块编号（从设计文档或用户指令中提取），如 AIP-21、M01",
        default=None,
    )
    args = parser.parse_args()

    path = args.path
    if not Path(path).exists():
        print(json.dumps({"valid": False, "errors": [f"文件不存在: {path}"]}, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        data = load_json(path)
    except json.JSONDecodeError as e:
        print(json.dumps({"valid": False, "errors": [f"JSON 解析失败: {e}"]}, ensure_ascii=False, indent=2))
        sys.exit(1)

    errors = validate_structure(data)
    errors.extend(validate_business_rules(data))
    errors.extend(validate_module_id_consistency(data, args.expected_module_id))

    report = {
        "valid": len(errors) == 0,
        "file": path,
        "module_id": data.get("module_id"),
        "function_count": len(data.get("functions", [])),
        "errors": errors,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
