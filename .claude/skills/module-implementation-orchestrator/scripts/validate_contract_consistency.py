#!/usr/bin/env python3
"""
验证模块实现代码中的外部接口类型与契约文件的一致性。

本脚本执行"软约束"验证：实现代码自己定义类型，但外部接口签名必须与
docs/contracts/ 下的 JSON Schema 契约一致。

支持从 Python 源码提取 Pydantic 模型和函数签名进行比对。
未来可扩展支持 TypeScript（通过 ts-json-schema-generator）和 Go。

用法:
    python validate_contract_consistency.py \
        --contract-dir docs/contracts/M02 \
        --source-dir src/services/world_builder \
        --module-id M02

退出码:
    0 - 一致
    1 - 发现不一致
    2 - 参数错误或文件缺失
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


def load_contracts(contract_dir: Path) -> dict[str, dict]:
    """加载契约目录下所有 .json 契约文件，返回 {title: schema} 映射。"""
    contracts: dict[str, dict] = {}
    if not contract_dir.exists():
        print(f"❌ 契约目录不存在: {contract_dir}")
        sys.exit(2)

    for p in sorted(contract_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            schema = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"❌ 契约文件 JSON 解析失败: {p} — {e}")
            sys.exit(2)

        title = schema.get("title")
        if not title:
            print(f"⚠️ 契约文件缺少 title 字段: {p}")
            continue
        contracts[title] = schema

    return contracts


def pydantic_field_to_json_schema(node: ast.AnnAssign | ast.expr) -> dict[str, Any]:
    """将 Python 类型注解近似转换为 JSON Schema 类型描述（简化版）。"""
    # 简化处理：仅覆盖最常见的 Pydantic 类型
    type_map = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
        "List": "array",
        "Dict": "object",
        "Optional": None,  # 特殊处理
        "Union": None,
    }

    def _unwrap(node: ast.expr) -> tuple[str, bool, ast.expr | None]:
        """返回 (json_type, required, inner_element)。"""
        if isinstance(node, ast.Constant) and node.value is None:
            return "null", True, None

        if isinstance(node, ast.Subscript):
            # List[str], Optional[str], Union[str, int]
            value = node.value
            if isinstance(value, ast.Name):
                name = value.id
                if name in ("Optional", "Union"):
                    # Optional[X] → X, required=False
                    slice_node = node.slice
                    if isinstance(slice_node, ast.Tuple) and slice_node.elts:
                        # Union[X, Y, None]
                        non_none = [e for e in slice_node.elts if not (isinstance(e, ast.Constant) and e.value is None)]
                        if len(non_none) == 1:
                            t, _, inner = _unwrap(non_none[0])
                            return t, False, inner
                        return "anyOf", False, slice_node
                    else:
                        t, _, inner = _unwrap(slice_node)
                        return t, False, inner
                elif name in ("list", "List"):
                    t, _, inner = _unwrap(node.slice)
                    return "array", True, node.slice
                elif name in ("dict", "Dict"):
                    return "object", True, node.slice
            elif isinstance(value, ast.Attribute):
                # e.g. typing.List[str]
                if value.attr in ("List", "list"):
                    return "array", True, node.slice
                if value.attr in ("Dict", "dict"):
                    return "object", True, node.slice
                if value.attr in ("Optional", "Union"):
                    return _unwrap(node.slice)

        if isinstance(node, ast.Name):
            return type_map.get(node.id, "unknown"), True, None

        if isinstance(node, ast.Constant):
            return type(node.value).__name__, True, None

        return "unknown", True, None

    jtype, required, _ = _unwrap(node)
    return {"type": jtype, "required": required}


class PydanticModelExtractor(ast.NodeVisitor):
    """从 Python AST 中提取 Pydantic BaseModel 定义和函数签名。"""

    def __init__(self) -> None:
        self.models: dict[str, dict[str, Any]] = {}
        self.functions: list[dict[str, Any]] = []

    def _is_pydantic_base(self, bases: list[ast.expr]) -> bool:
        for base in bases:
            if isinstance(base, ast.Name) and base.id in ("BaseModel", " pydantic.BaseModel"):
                return True
            if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                return True
        return False

    def _extract_field(self, node: ast.AnnAssign) -> dict[str, Any] | None:
        """提取一个类型注解字段的信息。"""
        if not isinstance(node.target, ast.Name):
            return None

        field_name = node.target.id
        schema_info = pydantic_field_to_json_schema(node.annotation)

        # 尝试从 Field(...) 或默认值判断是否 required
        required = schema_info.get("required", True)
        has_default = node.value is not None

        # 处理 Field(default=..., ...) 和 Field(default_factory=...)
        if has_default and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "Field":
                # Field(default=...) → 有默认值
                required = False
            elif isinstance(func, ast.Attribute) and func.attr == "Field":
                required = False

        if has_default and not required:
            # 尝试提取默认值字面量
            default_val = None
            if isinstance(node.value, ast.Constant):
                default_val = node.value.value
            elif isinstance(node.value, ast.List):
                default_val = []
            elif isinstance(node.value, ast.Dict):
                default_val = {}
            schema_info["default"] = default_val

        schema_info["name"] = field_name
        return schema_info

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        if not self._is_pydantic_base(node.bases):
            return

        fields: dict[str, dict] = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                field_info = self._extract_field(item)
                if field_info:
                    fields[field_info["name"]] = {
                        "type": field_info.get("type", "unknown"),
                        "required": field_info.get("required", True),
                    }
                    if "default" in field_info:
                        fields[field_info["name"]]["default"] = field_info["default"]

        self.models[node.name] = {
            "kind": "model",
            "fields": fields,
        }

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:  # noqa: N802
        # 只提取公开函数
        if node.name.startswith("_"):
            return

        params: list[dict] = []
        # 简单处理：提取参数名和类型注解
        args = node.args
        defaults_offset = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            if arg.arg == "self":
                continue
            param: dict[str, Any] = {"name": arg.arg, "required": True}
            if arg.annotation:
                info = pydantic_field_to_json_schema(arg.annotation)
                param["type"] = info.get("type", "unknown")
                param["required"] = info.get("required", True)
            # 有默认值 → 非必填
            if i >= defaults_offset and args.defaults[i - defaults_offset] is not None:
                param["required"] = False
            params.append(param)

        return_info: dict[str, Any] = {"type": "unknown"}
        if node.returns:
            info = pydantic_field_to_json_schema(node.returns)
            return_info["type"] = info.get("type", "unknown")

        self.functions.append({
            "name": node.name,
            "parameters": params,
            "return_type": return_info["type"],
        })


    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.visit_FunctionDef(node)


def extract_from_python(source_dir: Path) -> tuple[dict[str, dict], list[dict]]:
    """从 Python 源码目录提取 Pydantic 模型和函数签名。"""
    extractor = PydanticModelExtractor()
    for py_file in sorted(source_dir.rglob("*.py")):
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            extractor.visit(tree)
        except SyntaxError as e:
            print(f"⚠️ 语法错误，跳过: {py_file} — {e}")
            continue
    return extractor.models, extractor.functions


def compare_model_to_contract(model_name: str, model: dict, contract: dict) -> list[dict]:
    """比对提取的模型与契约 Schema，返回差异列表。"""
    diffs: list[dict] = []
    contract_props = contract.get("properties", {})
    contract_required = set(contract.get("required", []))
    model_fields = model.get("fields", {})

    # 检查字段是否存在差异
    all_fields = set(model_fields.keys()) | set(contract_props.keys())
    for field_name in sorted(all_fields):
        model_field = model_fields.get(field_name)
        contract_field = contract_props.get(field_name)

        if model_field and not contract_field:
            diffs.append({
                "field": field_name,
                "issue": "模型中存在但契约中未定义",
                "severity": "medium",
            })
            continue

        if contract_field and not model_field:
            diffs.append({
                "field": field_name,
                "issue": "契约要求但模型中未定义",
                "severity": "high",
            })
            continue

        # 两者都存在，比对类型
        model_type = model_field.get("type", "unknown")
        contract_type = contract_field.get("type", "unknown")

        # 简单的类型兼容性映射
        compatible = {
            ("string", "str"), ("integer", "int"), ("number", "float"),
            ("boolean", "bool"), ("array", "list"), ("object", "dict"),
        }

        if (contract_type, model_type) not in compatible and contract_type != model_type:
            diffs.append({
                "field": field_name,
                "issue": f"类型不一致：模型中为 {model_type}，契约要求 {contract_type}",
                "severity": "high",
            })

        # 检查必填性
        model_required = model_field.get("required", True)
        contract_required = field_name in contract_required
        if model_required != contract_required:
            diffs.append({
                "field": field_name,
                "issue": f"必填性不一致：模型 required={model_required}，契约 required={contract_required}",
                "severity": "high" if contract_required and not model_required else "medium",
            })

    return diffs


def validate(
    contract_dir: Path,
    source_dir: Path,
    module_id: str,
) -> bool:
    """执行验证，返回是否全部通过。"""
    print(f"🔍 验证模块 {module_id} 的接口一致性")
    print(f"   契约目录: {contract_dir}")
    print(f"   源码目录: {source_dir}")
    print()

    contracts = load_contracts(contract_dir)
    if not contracts:
        print("⚠️ 未找到任何契约文件，跳过验证")
        return True

    print(f"📄 加载了 {len(contracts)} 个契约定义: {', '.join(contracts.keys())}")

    models, functions = extract_from_python(source_dir)
    print(f"🐍 从源码提取了 {len(models)} 个 Pydantic 模型，{len(functions)} 个函数")
    print()

    all_passed = True

    # 1. 验证模型与契约的一致性
    for model_name, model in models.items():
        contract = contracts.get(model_name)
        if not contract:
            # 本模块自己定义的内部模型，不强制要求对应契约
            continue

        print(f"🧪 比对模型: {model_name}")
        diffs = compare_model_to_contract(model_name, model, contract)
        if diffs:
            all_passed = False
            for d in diffs:
                icon = "🔴" if d["severity"] == "high" else "🟡"
                print(f"   {icon} [{d['severity']}] {d['field']}: {d['issue']}")
        else:
            print(f"   ✅ 完全一致")

    # 2. 检查是否有契约要求但源码中未实现的模型
    for contract_name in contracts:
        ct = contracts[contract_name]
        ct_type = ct.get("x-contract-type", "")
        if ct_type not in ("input", "output", "shared-model"):
            continue
        if contract_name not in models:
            # 可能通过函数参数直接使用，不一定是模型定义
            # 这里放宽：只警告不阻断
            print(f"⚠️ 契约 {contract_name} 在源码中未找到对应的 Pydantic Model 定义")

    print()
    if all_passed:
        print("✅ 全部通过：实现代码的外部接口与契约一致")
    else:
        print("❌ 验证失败：发现实现代码与契约不一致的项")

    return all_passed


def main() -> int:
    if sys.version_info < (3, 8):
        print("错误: 需要 Python 3.8+", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(
        description="验证实现代码的外部接口类型与契约文件的一致性"
    )
    parser.add_argument(
        "--contract-dir",
        type=Path,
        required=True,
        help="契约文件所在目录，如 docs/contracts/M02",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="模块源码目录，如 src/services/world_builder",
    )
    parser.add_argument(
        "--module-id",
        type=str,
        required=True,
        help="模块编号，如 M02",
    )
    args = parser.parse_args()

    passed = validate(args.contract_dir, args.source_dir, args.module_id)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
