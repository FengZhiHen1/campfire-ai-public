#!/usr/bin/env python3
"""
趋绿静态扫描器（Green-Seeking Detector）v3.2

模块测试编写器的自检工具。通过 AST 分析检测测试文件中的趋绿模式，
输出 JSON 报告供 Step 5.6 毒性评分使用。

v3.2 改进：
- 新增 G11: 空测试检测（函数体无 assert / pytest.raises / fail）
- 新增 G12: 内部函数导入检测（从被测模块导入 _ 前缀函数）
- G9 毒性权重提升：pass 分支从 2 提升至 3（与 return 同级）
- 前置条件检查：py_compile、__init__.py 完整性

v3.1 改进：
- 新增 G10: 核心接口偏离检测（Evil Stub 对抗测试未调用声称的核心接口）

v3 改进（对抗 Agent 自我欺骗）：
- 新增 G8: 恒真式欺骗检测（or True / and False 等绕过断言）
- 新增 G9: 防御性跳过检测（if condition: return / pass 跳过核心断言）

v2 改进：
- 增加 import 追踪，支持 from module import func 导入模式
- G1 区分裸 except 和防御性异常处理（NotImplementedError 等）
- G2/G5 增加对 self.xxx() 测试辅助方法的一级穿透
- G4 增加上下文感知：跳过 pytest.raises / 防御性 try-except 模式
- G5 增加上下文感知：有被测模块调用的测试中，标准库调用视为辅助性

用法:
    python detect_green_seeking.py <test_file.py> [--sut-module <module_prefix>]

示例:
    python detect_green_seeking.py tests/test_pipeline.py --sut-module ai_pipeline

输出格式（JSON）:
    {
        "file": "tests/test_pipeline.py",
        "total_suspects": 3,
        "suspects": [
            {"id": "G1", "line": 42, "func": "test_graph_invoke", "message": "...", "toxicity": 1},
            ...
        ],
        "toxicity_score": 6,
        "passed": false
    }
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# 扫描规则定义
# ─────────────────────────────────────────────────────────────────────────────

SUSPECTS: list[dict[str, Any]] = []


def report(rule_id: str, line: int, func: str, message: str, toxicity: int) -> None:
    SUSPECTS.append({
        "id": rule_id,
        "line": line,
        "func": func,
        "message": message,
        "toxicity": toxicity,
    })


# ─── Import 追踪 ────────────────────────────────────────────────────────────

STDLIB_MODULES = {
    "asyncio", "json", "datetime", "time", "re", "math", "random",
    "collections", "itertools", "functools", "statistics", "decimal",
    "fractions", "hashlib", "base64", "urllib", "http", "email",
    "pathlib", "os", "sys", "typing", "inspect", "types", "string",
    "numbers", "abc", "copy", "pickle", "csv", "xml", "html",
}

# 防御性测试中常见的"预期未实现"异常
DEFENSIVE_EXCEPTIONS = {
    "NotImplementedError", "AttributeError", "KeyError", "TypeError",
}

# 第三方库的控制流异常（设计意图就是被捕获的）
CONTROL_FLOW_EXCEPTIONS = {
    "DropEvent",  # structlog: processor 通过抛出 DropEvent 表示丢弃事件
}

# HTTP 测试客户端方法（FastAPI TestClient / httpx / requests 等）
HTTP_CLIENT_METHODS = {"post", "get", "put", "delete", "patch", "head", "options"}
HTTP_CLIENT_NAMES = {"client", "api_client", "test_client", "testclient", "async_client"}


def extract_sut_imports(tree: ast.AST, sut_prefixes: list[str]) -> dict[str, str]:
    """
    从 AST 中提取从被测模块导入的名称映射。

    返回 {本地名称: 完整模块路径}。
    支持:
        import ai_pipeline
        import ai_pipeline.graph.workflows as workflows
        from ai_pipeline.graph.workflows import build_graph
        from ai_pipeline.graph.workflows import build_graph as bg
    """
    imports: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                asname = alias.asname or alias.name
                if any(name.startswith(p) for p in sut_prefixes):
                    imports[asname] = name

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            is_sut_module = any(
                module.startswith(p) or module.startswith(p + ".")
                for p in sut_prefixes
            )
            if is_sut_module:
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    full_path = f"{module}.{alias.name}" if module else alias.name
                    imports[local_name] = full_path

    return imports


# ─── AST 辅助函数 ───────────────────────────────────────────────────────────

def _find_first(node: ast.AST, cls: type) -> ast.AST | None:
    """在节点子树中按行号查找第一个匹配类型的节点。"""
    found: list[ast.AST] = []
    for child in ast.walk(node):
        if isinstance(child, cls) and hasattr(child, "lineno"):
            found.append(child)
    if not found:
        return None
    return min(found, key=lambda x: x.lineno)  # type: ignore[arg-type, return-value]


def _resolve_call_name(node: ast.Call) -> list[str]:
    """解析 Call 节点的完整名称链。"""
    func = node.func
    name_parts: list[str] = []

    if isinstance(func, ast.Name):
        name_parts = [func.id]
    elif isinstance(func, ast.Attribute):
        current: ast.AST = func
        while isinstance(current, ast.Attribute):
            name_parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            name_parts.append(current.id)
        name_parts.reverse()
    elif isinstance(func, ast.Subscript):
        return []

    return name_parts


def _find_parent_class(tree: ast.AST, func_node: ast.FunctionDef) -> ast.ClassDef | None:
    """在 AST 中查找包含给定函数定义的类。"""
    for child in ast.walk(tree):
        if isinstance(child, ast.ClassDef):
            for item in child.body:
                if item is func_node:
                    return child
    return None


def _is_direct_sut_call(node: ast.Call, sut_prefixes: list[str], sut_imports: dict[str, str]) -> bool:
    """不穿透 self.xxx() 的直接被测调用检查。"""
    name_parts = _resolve_call_name(node)
    if not name_parts:
        return False

    full_name = ".".join(name_parts)
    if any(full_name.startswith(prefix) for prefix in sut_prefixes):
        return True

    base_name = name_parts[0]
    if base_name in sut_imports:
        return True

    return False


def _is_sut_call(
    node: ast.Call,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
    func_node: ast.FunctionDef | None = None,
) -> bool:
    """判断一个 Call 是否来自被测模块（含测试辅助方法一级穿透）。"""
    name_parts = _resolve_call_name(node)
    if not name_parts:
        return False

    # 情况 1: 直接模块路径调用，如 ai_pipeline.build_graph()
    full_name = ".".join(name_parts)
    if any(full_name.startswith(prefix) for prefix in sut_prefixes):
        return True

    # 情况 2: from ai_pipeline import build_graph; build_graph()
    base_name = name_parts[0]
    if base_name in sut_imports:
        return True

    # 情况 3: self.xxx() / cls.xxx() — 测试辅助方法一级穿透
    if len(name_parts) >= 2 and name_parts[0] in ("self", "cls"):
        method_name = name_parts[1]
        if tree and func_node and not method_name.startswith("test_"):
            parent_class = _find_parent_class(tree, func_node)
            if parent_class:
                for item in parent_class.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        for sub_child in ast.walk(item):
                            if isinstance(sub_child, ast.Call):
                                if _is_direct_sut_call(sub_child, sut_prefixes, sut_imports):
                                    return True

    # 情况 4: API 测试客户端调用，如 api_client.post("/pipeline/run")
    if len(name_parts) >= 2:
        obj_name = name_parts[0].lower()
        method_name = name_parts[1].lower()
        if obj_name in HTTP_CLIENT_NAMES and method_name in HTTP_CLIENT_METHODS:
            return True

    return False


def _has_sut_call(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> bool:
    """检查函数体内是否有任何被测模块调用。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if _is_sut_call(child, sut_prefixes, sut_imports, tree, node):
                return True
    return False


def _find_first_sut_call(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> ast.Call | None:
    """查找测试函数中第一个来自被测模块的调用。"""
    candidates: list[ast.Call] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if _is_sut_call(child, sut_prefixes, sut_imports, tree, node):
                candidates.append(child)
    if not candidates:
        return None
    return min(candidates, key=lambda x: x.lineno)  # type: ignore[arg-type, return-value]


def _extract_names(node: ast.AST) -> set[str]:
    """从 AST 节点中提取所有名称标识符（含属性访问的 attr）。"""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _format_exception_type(exc_type_node: ast.AST | None) -> str | None:
    """格式化异常类型节点为字符串。"""
    if exc_type_node is None:
        return None
    try:
        return ast.unparse(exc_type_node)
    except Exception:
        return str(type(exc_type_node).__name__)


def _is_defensive_exception(exc_type_node: ast.AST | None) -> bool:
    """判断异常类型是否属于防御性测试中预期的异常或控制流异常。"""
    if exc_type_node is None:
        return False

    if isinstance(exc_type_node, ast.Tuple):
        names = set()
        for elt in exc_type_node.elts:
            names.update(_extract_names(elt))
        if bool(names) and names.issubset(DEFENSIVE_EXCEPTIONS):
            return True
        if bool(names) and names.issubset(CONTROL_FLOW_EXCEPTIONS):
            return True
        return False

    names = _extract_names(exc_type_node)
    if bool(names & DEFENSIVE_EXCEPTIONS):
        return True
    if bool(names & CONTROL_FLOW_EXCEPTIONS):
        return True
    return False


# ─── G1: 异常吞咽 ───────────────────────────────────────────────────────────

def check_g1_exception_swallowing(node: ast.FunctionDef) -> None:
    """检测 try-except-pass 模式。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Try):
            for handler in child.handlers:
                body = handler.body
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    exc_type_str = _format_exception_type(handler.type)

                    if exc_type_str is None:
                        report(
                            "G1", handler.lineno or node.lineno, node.name,
                            "异常吞咽: 裸 except: pass（会吞掉所有异常）",
                            3,
                        )
                    elif _is_defensive_exception(handler.type):
                        report(
                            "G1", handler.lineno or node.lineno, node.name,
                            f"异常吞咽: try-except-pass ({exc_type_str}) — 疑似防御性测试，建议人工确认",
                            1,
                        )
                    else:
                        report(
                            "G1", handler.lineno or node.lineno, node.name,
                            f"异常吞咽: try-except-pass (异常类型: {exc_type_str})",
                            3,
                        )


# ─── G2: 构造-断言 ──────────────────────────────────────────────────────────

def _is_simple_constant_assert(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> bool:
    """检查是否是简单的模块常量/注册表/枚举断言测试。

    特征：
    - 没有被测模块的函数/方法调用
    - 有被测模块导入的名称被直接使用（读取而非构造）
    """
    # 检查是否有被测调用
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if _is_sut_call(child, sut_prefixes, sut_imports, tree, node):
                return False

    # 检查是否有被测模块导入的名称被使用
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in sut_imports:
            return True

    return False


def check_g2_construct_assert(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> None:
    """检测构造-断言模式。"""
    first_assert = _find_first(node, ast.Assert)
    first_sut_call = _find_first_sut_call(node, sut_prefixes, sut_imports, tree)

    if first_assert and first_sut_call:
        if first_assert.lineno < first_sut_call.lineno:  # type: ignore[union-attr]
            report(
                "G2", first_assert.lineno, node.name,  # type: ignore[union-attr]
                "构造-断言: assert 出现在被测模块调用之前",
                3,
            )
    elif first_assert and not first_sut_call:
        # 如果被测模块导入的常量/注册表/枚举被直接读取断言，视为合法
        if _is_simple_constant_assert(node, sut_prefixes, sut_imports, tree):
            return
        report(
            "G2", first_assert.lineno, node.name,  # type: ignore[union-attr]
            "构造-断言: 测试函数内无被测模块调用",
            3,
        )


# ─── G3: 宽泛断言 ───────────────────────────────────────────────────────────

def check_g3_broad_assertion(node: ast.FunctionDef) -> None:
    """检测 assert x in (a, b, c) 用于核心业务结果。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            test_expr = child.test
            if isinstance(test_expr, ast.Compare):
                if len(test_expr.ops) == 1 and isinstance(test_expr.ops[0], ast.In):
                    comparator = test_expr.comparators[0]
                    if isinstance(comparator, (ast.Tuple, ast.List)):
                        elts = comparator.elts
                        if len(elts) > 2:
                            report(
                                "G3", child.lineno, node.name,
                                f"宽泛断言: assert ... in ({len(elts)} 个备选值)",
                                1,
                            )


# ─── G4: 纯存在性断言 ───────────────────────────────────────────────────────

def check_g4_existence_assertion(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> None:
    """检测 assert result is not None 作为唯一或主要断言。"""
    # 有 pytest.raises 的测试通常是异常测试，跳过 G4
    has_pytest_raises = any(
        isinstance(child, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "raises"
            for item in child.items
        )
        for child in ast.walk(node)
    )

    # 防御性测试模式：有被测调用 + try-except
    has_sut_call = _has_sut_call(node, sut_prefixes, sut_imports, tree)
    has_try_except = any(
        isinstance(child, ast.Try)
        for child in ast.walk(node)
    )

    if has_pytest_raises:
        return

    if has_sut_call and has_try_except:
        return

    asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
    if not asserts:
        return

    weak_asserts: list[ast.Assert] = []
    for a in asserts:
        test = a.test
        if isinstance(test, ast.Compare):
            if len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot):
                if isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value is None:
                    weak_asserts.append(a)
            elif (
                len(test.ops) == 1
                and isinstance(test.ops[0], ast.Gt)
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == 0
                and isinstance(test.left, ast.Call)
                and isinstance(test.left.func, ast.Name)
                and test.left.func.id == "len"
            ):
                weak_asserts.append(a)

    if len(weak_asserts) == len(asserts) and len(asserts) > 0:
        for wa in weak_asserts:
            report(
                "G4", wa.lineno, node.name,
                "纯存在性断言: assert is not None 或 len > 0 单独使用",
                2,
            )


# ─── G5: 标准库测试 ─────────────────────────────────────────────────────────

def check_g5_stdlib_testing(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> None:
    """检测直接调用标准库并断言其行为。

    v2 改进：如果测试函数中有被测模块调用，标准库调用视为辅助性，跳过。
    """
    if _has_sut_call(node, sut_prefixes, sut_imports, tree):
        return

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                current: ast.AST = func
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name) and current.id in STDLIB_MODULES:
                    report(
                        "G5", child.lineno, node.name,
                        f"标准库测试: 直接调用 {current.id}.{func.attr} 并断言其行为",
                        2,
                    )
                    break


# ─── G6: 纯 Mock 验证 ───────────────────────────────────────────────────────

def check_g6_pure_mock_assertion(node: ast.FunctionDef) -> None:
    """检测 assert mock.assert_called_once() 且无业务结果断言。"""
    asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
    if not asserts:
        return

    mock_asserts: list[ast.Assert] = []
    business_asserts: list[ast.Assert] = []

    for a in asserts:
        test = a.test
        if isinstance(test, ast.Call):
            func = test.func
            if isinstance(func, ast.Attribute) and func.attr.startswith("assert_called"):
                mock_asserts.append(a)
            else:
                business_asserts.append(a)
        else:
            business_asserts.append(a)

    if mock_asserts and not business_asserts:
        for ma in mock_asserts:
            report(
                "G6", ma.lineno, node.name,
                "纯 Mock 验证: 只有 assert_called* 断言，无业务结果验证",
                2,
            )


# ─── G7: 自我赋值断言 ───────────────────────────────────────────────────────

def check_g7_self_assignment_assertion(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> None:
    """检测手动赋值后立刻断言同一变量（无被测调用介入）。"""
    assigns = [(n.lineno, n) for n in ast.walk(node) if isinstance(n, ast.Assign) and hasattr(n, "lineno")]
    asserts = [(n.lineno, n) for n in ast.walk(node) if isinstance(n, ast.Assert) and hasattr(n, "lineno")]

    for aline, a in asserts:
        prev_assigns = [(l, assign) for l, assign in assigns if l < aline]
        if not prev_assigns:
            continue

        if isinstance(a.test, ast.Name):
            var_name = a.test.id
            for _, assign in reversed(prev_assigns):
                for target in assign.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        # 检查 assign 和 assert 之间是否有被测调用
                        has_call_between = False
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call) and hasattr(child, "lineno"):
                                if assign.lineno < child.lineno < aline:
                                    if _is_sut_call(child, sut_prefixes, sut_imports, tree, node):
                                        has_call_between = True
                                        break
                        if not has_call_between:
                            report(
                                "G7", aline, node.name,
                                f"自我赋值断言: 对变量 {var_name} 赋值后立即断言",
                                3,
                            )
                        break


# ─── G8: 恒真式欺骗 ────────────────────────────────────────────────────────

def _contains_tautology(node: ast.AST) -> tuple[bool, str]:
    """检查 AST 子树中是否包含恒真/恒假表达式。

    检测模式：
    - expr or True / True or expr → 恒真
    - expr and False / False and expr → 恒假（断言中同样有害）
    - 递归检查嵌套的 BoolOp
    """
    for child in ast.walk(node):
        if isinstance(child, ast.BoolOp):
            if isinstance(child.op, ast.Or):
                # or True 在任意位置都让整体恒真
                for value in child.values:
                    if isinstance(value, ast.Constant) and value.value is True:
                        return True, "or True"
                    # 也检查嵌套
                    nested, desc = _contains_tautology(value)
                    if nested:
                        return True, desc
            elif isinstance(child.op, ast.And):
                # and False 让整体恒假（断言永失败，但同样是欺骗）
                for value in child.values:
                    if isinstance(value, ast.Constant) and value.value is False:
                        return True, "and False"
                    nested, desc = _contains_tautology(value)
                    if nested:
                        return True, desc
    return False, ""


def check_g8_tautological_assertion(node: ast.FunctionDef) -> None:
    """检测 assert 中包含 or True / and False 等恒真/恒假式。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            has_tauto, desc = _contains_tautology(child.test)
            if has_tauto:
                report(
                    "G8", child.lineno, node.name,
                    f"恒真式欺骗: assert 中包含 '{desc}'，使断言永远为真/假",
                    3,
                )


# ─── G9: 防御性跳过 ────────────────────────────────────────────────────────

def check_g9_defensive_skip(node: ast.FunctionDef) -> None:
    """检测测试函数中的 if condition: return / pass 跳过核心逻辑。

    典型反模式：
    - if api_client is None: return
    - if not HAS_DEPS: pass
    - if some_condition: return

    这些模式让测试在依赖缺失时"假装通过"，具有极强的误导性。

    合法例外：
    - pytest.skip() 调用（已被 SKILL.md 禁止，但扫描器不重复报警）
    - 循环内部的 continue（不在本检测范围内）
    """
    # 获取函数体的直接子节点（不包括嵌套函数）
    for stmt in node.body:
        _check_stmt_for_defensive_skip(stmt, node.name)


def _check_stmt_for_defensive_skip(stmt: ast.stmt, func_name: str) -> None:
    """递归检查语句及其子语句中的防御性跳过。"""
    if isinstance(stmt, ast.If):
        # 检查 body 是否是单个 return 或 pass
        if len(stmt.body) == 1:
            body_stmt = stmt.body[0]
            if isinstance(body_stmt, ast.Return):
                report(
                    "G9", stmt.lineno, func_name,
                    "防御性跳过: if condition: return — 依赖缺失时测试假装通过",
                    3,
                )
                return
            if isinstance(body_stmt, ast.Pass):
                report(
                    "G9", stmt.lineno, func_name,
                    "防御性跳过: if condition: pass — 无意义的分支跳过",
                    3,
                )
                return
        # 递归检查 if 的 body 和 orelse
        for sub in stmt.body:
            _check_stmt_for_defensive_skip(sub, func_name)
        for sub in stmt.orelse:
            _check_stmt_for_defensive_skip(sub, func_name)

    elif isinstance(stmt, (ast.For, ast.While, ast.With, ast.Try)):
        for sub in stmt.body:
            _check_stmt_for_defensive_skip(sub, func_name)
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                for sub in handler.body:
                    _check_stmt_for_defensive_skip(sub, func_name)
            for sub in stmt.orelse:
                _check_stmt_for_defensive_skip(sub, func_name)
            for sub in stmt.finalbody:
                _check_stmt_for_defensive_skip(sub, func_name)


# ─── G10: 核心接口偏离 ──────────────────────────────────────────────────────

# 辅助函数命名前缀：纯查询/构造型工具函数，不含核心业务逻辑。
# 注意：以下划线开头的核心业务函数（如 _router_validate_exit、_find_lowest_score_source）
# 不应出现在此列表中。此列表只包含"轻量级工具函数"。
_AUXILIARY_PREFIXES = (
    "_check_", "_get_", "_make_", "_extract_",
    "_generate_", "_thread_",
)


def check_g10_core_deviation(
    node: ast.FunctionDef,
    sut_prefixes: list[str],
    sut_imports: dict[str, str],
    tree: ast.AST | None = None,
) -> None:
    """
    检测 Evil Stub 对抗测试中的核心接口偏离。

    模式 A: 声称测试某核心接口，但函数体内完全没有被测模块的
            业务函数调用（只有模型构造/属性断言）。
    模式 B: 只有辅助函数调用（_check_, _get_, _find_ 等），
            没有调用任何核心业务函数。

    典型反模式：
    - TestEvilStubXxx 类中，只调用了 _check_skip_from_runplan()
      和 _get_runplan_target_ids()，未触及声称测试的 extract 节点
    - TestEvilStubXxx 类中，只构造了 PipelineCLIInput() 然后断言
      属性，未调用任何注入/路由逻辑
    """
    # 1. 判断是否是 Evil Stub 对抗测试
    is_evil_stub_test = False
    parent_class = _find_parent_class(tree, node) if tree else None

    if parent_class and "EvilStub" in parent_class.name:
        is_evil_stub_test = True
    else:
        docstring = ast.get_docstring(node)
        if docstring and ("对抗" in docstring or "Evil Stub" in docstring):
            is_evil_stub_test = True

    if not is_evil_stub_test:
        return

    # 2. 分类统计被测模块调用
    core_calls: list[str] = []      # 核心业务函数（函数调用，非辅助前缀）
    aux_calls: list[str] = []       # 辅助函数（函数调用，辅助前缀）
    construct_calls: list[str] = []  # 模型/类构造（大写开头）

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if _is_sut_call(child, sut_prefixes, sut_imports, tree, node):
                name_parts = _resolve_call_name(child)
                if name_parts:
                    func_name = name_parts[-1]
                    first_char = func_name[0] if func_name else ""
                    # Python 函数命名惯例：小写字母或下划线开头
                    # 类/模型构造：大写字母开头
                    is_function = first_char.islower() or first_char == "_"
                    if is_function:
                        if func_name.startswith(_AUXILIARY_PREFIXES):
                            aux_calls.append(func_name)
                        else:
                            core_calls.append(func_name)
                    else:
                        construct_calls.append(func_name)

    # 3. 模式 A: 完全没有业务函数/辅助函数调用（只有模型构造或纯断言）
    if not core_calls and not aux_calls:
        report(
            "G10", node.lineno, node.name,
            "核心接口偏离: Evil Stub 对抗测试未调用被测模块任何函数/方法（仅模型构造或属性断言）",
            2,
        )
        return

    # 4. 模式 B: 只有辅助函数调用，没有核心业务函数调用
    if aux_calls and not core_calls:
        report(
            "G10", node.lineno, node.name,
            f"核心接口偏离: Evil Stub 对抗测试仅调用辅助函数 {aux_calls}，未触及声称测试的核心接口",
            2,
        )


# ─── G11: 空测试 ────────────────────────────────────────────────────────────

def check_g11_empty_test(node: ast.FunctionDef) -> None:
    """检测测试函数体内无 assert、无 pytest.raises、无 fail()。

    合法元素：
    - assert 语句
    - pytest.raises(...) 上下文管理器
    - pytest.fail(...) / unittest.TestCase.fail(...)
    """
    has_assertion = False

    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            has_assertion = True
            break
        if isinstance(child, ast.With):
            for item in child.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call):
                    name = _resolve_call_name(ctx)
                    if name and name[-1] == "raises":
                        has_assertion = True
                        break
        if isinstance(child, ast.Call):
            name = _resolve_call_name(child)
            if name and name[-1] == "fail":
                has_assertion = True
                break

    if not has_assertion:
        report(
            "G11", node.lineno, node.name,
            "空测试: 函数体内无 assert、无 pytest.raises、无 fail()",
            3,
        )


# ─── G12: 内部函数导入 ───────────────────────────────────────────────────────

def check_g12_internal_imports(sut_imports: dict[str, str]) -> None:
    """检测从被测模块导入以 _ 开头的内部函数/类。"""
    for local_name, full_path in sut_imports.items():
        if local_name.startswith("_"):
            report(
                "G12", 0, "<module>",
                f"内部函数导入: 从被测模块导入 '_' 前缀名称 '{local_name}' ({full_path})",
                3,
            )


# ─────────────────────────────────────────────────────────────────────────────
# 主扫描逻辑
# ─────────────────────────────────────────────────────────────────────────────

def scan_file(file_path: Path, sut_prefixes: list[str]) -> dict[str, Any]:
    # ── 前置条件 1: py_compile ──
    try:
        import py_compile
        py_compile.compile(str(file_path), doraise=True)
    except py_compile.PyCompileError as e:
        return {
            "file": str(file_path),
            "error": f"PyCompileError: {e}",
            "total_suspects": 0,
            "suspects": [],
            "toxicity_score": 999,
            "passed": False,
            "precheck": {"py_compile": False},
        }

    # ── 前置条件 2: __init__.py 存在且非空 ──
    init_file = file_path.parent / "__init__.py"
    precheck_init = True
    if not init_file.exists():
        precheck_init = False
    elif init_file.stat().st_size == 0:
        precheck_init = False

    if not precheck_init:
        return {
            "file": str(file_path),
            "error": f"__init__.py 缺失或为空: {init_file}",
            "total_suspects": 0,
            "suspects": [],
            "toxicity_score": 999,
            "passed": False,
            "precheck": {"py_compile": True, "init_py": False},
        }

    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {
            "file": str(file_path),
            "error": f"SyntaxError: {e}",
            "total_suspects": 0,
            "suspects": [],
            "toxicity_score": 0,
            "passed": False,
            "precheck": {"py_compile": True, "init_py": True},
        }

    global SUSPECTS
    SUSPECTS = []

    # v2: 提取被测模块导入映射
    sut_imports = extract_sut_imports(tree, sut_prefixes)

    # G12: 模块级内部函数导入检测
    check_g12_internal_imports(sut_imports)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            check_g1_exception_swallowing(node)
            check_g2_construct_assert(node, sut_prefixes, sut_imports, tree)
            check_g3_broad_assertion(node)
            check_g4_existence_assertion(node, sut_prefixes, sut_imports, tree)
            check_g5_stdlib_testing(node, sut_prefixes, sut_imports, tree)
            check_g6_pure_mock_assertion(node)
            check_g7_self_assignment_assertion(node, sut_prefixes, sut_imports, tree)
            check_g8_tautological_assertion(node)
            check_g9_defensive_skip(node)
            check_g10_core_deviation(node, sut_prefixes, sut_imports, tree)
            check_g11_empty_test(node)

    toxicity_score = sum(s["toxicity"] for s in SUSPECTS)

    return {
        "file": str(file_path),
        "total_suspects": len(SUSPECTS),
        "suspects": SUSPECTS,
        "toxicity_score": toxicity_score,
        "passed": toxicity_score <= 2,
        "precheck": {"py_compile": True, "init_py": True},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="趋绿静态扫描器 v3.1")
    parser.add_argument("test_file", type=Path, help="测试文件路径")
    parser.add_argument(
        "--sut-module", default="",
        help="被测模块前缀，多个用逗号分隔，如 'ai_pipeline,my_module'",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="输出 JSON 文件路径（默认 stdout）",
    )
    args = parser.parse_args()

    sut_prefixes = [p.strip() for p in args.sut_module.split(",") if p.strip()]
    if not sut_prefixes:
        sut_prefixes = ["ai_pipeline", "src"]

    result = scan_file(args.test_file, sut_prefixes)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
