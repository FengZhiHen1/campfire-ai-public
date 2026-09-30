"""装配处的工具注册清单（`surfaces/consult/registry.py`）。

钉住的是**「池里有什么」这一份清单**，以及它与设计文档的对应关系。工具实现本身由
`test_memory_tools.py` / `test_library_tools.py` 覆盖，本文件不重复。
"""

from __future__ import annotations

import pytest

from campfire.agent.tools import RESERVED_TOOL_NAMES, ToolPool, ToolRegistrationError
from campfire.surfaces.consult.registry import build_product_tools, register_product_tools


def test_registers_the_three_implemented_tools() -> None:
    """只注册**已实现**的三个工具（2026-09-30）。

    未注册的 4 个不是遗漏：`search_cases` 缺表与 7 个案例字段、3 个 profile 工具的
    模块是零实现占位包。证据见 `tools/library.py` 模块说明与 `docs/TODO.md`。
    """
    names = [tool.name for tool in build_product_tools()]
    assert sorted(names) == ["read_memory", "search_knowledge", "write_memory"]


def test_does_not_register_a_delete_memory_tool() -> None:
    """**不得**有 `delete_memory`（决策记录：记忆删除走用户确认入口，不是模型工具）。

    判别性：谁将来顺手加一个 `delete_memory`，本用例会拦下——那会绕过使用者的确认。
    """
    names = [tool.name for tool in build_product_tools()]
    assert "delete_memory" not in names
    assert not any("delete" in name for name in names), "模型不得有删除类工具"


def test_no_tool_uses_a_reserved_name() -> None:
    """产品工具不得占用基座保留名（`skill` / `read_skill_resource`）——池会拒。"""
    for tool in build_product_tools():
        assert tool.name not in RESERVED_TOOL_NAMES


def test_every_tool_has_a_usable_description() -> None:
    """每个工具的说明非空——**它是模型选工具的唯一依据**（池同此校验）。"""
    for tool in build_product_tools():
        assert tool.description.strip(), f"{tool.name} 的说明为空"


def test_every_tool_exposes_a_json_schema() -> None:
    """每个工具都能给出 JSON Schema 且含 `properties`——否则模型看不到参数。"""
    for tool in build_product_tools():
        assert isinstance(tool.parameters, dict)
        assert "properties" in tool.parameters, f"{tool.name} 的 schema 没有 properties"


def test_registration_puts_all_tools_in_the_pool() -> None:
    """`register_product_tools` 真的把三个都放进了池。"""
    pool = ToolPool()
    register_product_tools(pool)
    assert pool.names() == ("read_memory", "search_knowledge", "write_memory")
    assert [t.name for t in pool.declared()] == ["read_memory", "search_knowledge", "write_memory"]


def test_double_registration_is_rejected_not_silently_ignored() -> None:
    """重复注册抛错——**不得静默覆盖**：重名会让权限判定面对含义不明的名字。

    （池自己有此纪律，本用例确认装配处走的是会被校验的那条通道。）
    """
    pool = ToolPool()
    register_product_tools(pool)
    with pytest.raises(ToolRegistrationError):
        register_product_tools(pool)


def test_build_is_stable_across_calls() -> None:
    """清单顺序稳定——装配处与测试据此比对，不必排序。"""
    assert [t.name for t in build_product_tools()] == [t.name for t in build_product_tools()]
