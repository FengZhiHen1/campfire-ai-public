"""装配处的工具注册清单（`surfaces/consult/registry.py`）。

钉住的是「池里有什么」这一份清单，以及它与设计文档的对应关系。工具实现本身由
`test_memory_tools.py` / `test_library_tools.py` / `test_profile_tools.py` /
`test_emergency_card.py` / `test_onboarding_tools.py` 覆盖，本文件不重复。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from campfire.agent.tools import RESERVED_TOOL_NAMES, ToolPool, ToolRegistrationError, ToolSpec
from campfire.surfaces.consult.registry import (
    build_product_tools,
    register_base_tools,
    register_product_tools,
)

#: 一期十个模型可见工具的清单（技能设计第 3 节）。逐字列出而不是从实现派生：
#: 从实现派生会让「实现少了一个」这类缺陷在测试里也少一个，测试就永远通过。
EXPECTED_TOOL_NAMES = [
    "create_support_object",
    "emit_emergency_action_card",
    "finish_onboarding",
    "propose_profile_item",
    "read_memory",
    "read_profile_items",
    "read_profile_summary",
    "search_cases",
    "search_knowledge",
    "write_memory",
]


def test_registers_all_ten_phase_one_tools() -> None:
    """注册清单恰好是技能设计第 3 节的十个工具（2026-09-30 全量齐备）。

    判别性：少注册任一个，本用例失败——而少注册的表现是「模型看不到它」，
    在真实对话里只是一个能力静默缺失。
    """
    names = [tool.name for tool in build_product_tools()]
    assert names == EXPECTED_TOOL_NAMES
    assert len(names) == 10


def test_does_not_register_a_delete_memory_tool() -> None:
    """不得有 `delete_memory`（决策记录：记忆删除走用户确认入口，不是模型工具）。

    判别性：谁将来顺手加一个 `delete_memory`，本用例会拦下——那会绕过使用者的确认。
    """
    names = [tool.name for tool in build_product_tools()]
    assert "delete_memory" not in names
    assert not any("delete" in name for name in names), "模型不得有删除类工具"


def test_does_not_register_base_reserved_names() -> None:
    """产品清单里没有基座保留名（`skill` / `read_skill_resource` / `ask_user`）。

    它们走 `register_base` 通道（恒可用、不进 `allowed-tools` 的并集）。
    判别性：把 `ask_user` 混进产品清单，本用例失败——它会变成受 skill 范围控制的工具，
    而「提问是运行的中止方式之一，不是某个 skill 的特权」这条语义随之失效。
    """
    names = [tool.name for tool in build_product_tools()]
    assert not (set(names) & RESERVED_TOOL_NAMES)


def test_register_base_tools_registers_ask_user() -> None:
    """`register_base_tools` 把 `ask_user` 放进池（走 `register_base` 通道）。

    判别性：去掉这个函数或把 `ask_user` 挪进产品清单，`register_product_tools`
    会因保留名被拒（池校验），本用例失败。
    """
    pool = ToolPool()
    register_base_tools(pool)
    assert pool.names() == ("ask_user",)

    # 反向：产品通道不能注册保留名（池会拒）。
    # 取一个真实工具只改名成保留名——用 `replace` 而不是重新构造：后者要逐字段抄
    # `args_model` / `handler`，抄漏任何一个都变成「测另一个形状」而不是「测保留名」。
    spec = build_product_tools()[0]
    assert isinstance(spec, ToolSpec), "产品清单的元素必须是 ToolSpec，本用例靠它改名复用其余字段"
    with pytest.raises(ToolRegistrationError):
        ToolPool().register(replace(spec, name="ask_user"))


def test_every_tool_has_a_usable_description() -> None:
    """每个工具的说明非空——它是模型选工具的唯一依据（池同此校验）。"""
    for tool in build_product_tools():
        assert tool.description.strip(), f"{tool.name} 的说明为空"


def test_descriptions_stay_within_the_pool_limit() -> None:
    """说明不超过池的 1024 字符上界（`ToolSpec` 构造时会拒，这里给出可读的失败）。

    判别性：某个说明写超了，本用例给出「哪个工具、多长」，而不是让它以
    `ToolSpecError` 的形式在构造时炸掉整个清单。
    """
    for tool in build_product_tools():
        assert len(tool.description) <= 1024, f"{tool.name} 的说明长 {len(tool.description)} 字符，超过上界"


def test_every_tool_exposes_a_json_schema() -> None:
    """每个工具都能给出 JSON Schema 且含 `properties`——否则模型看不到参数。"""
    for tool in build_product_tools():
        assert isinstance(tool.parameters, dict)
        assert "properties" in tool.parameters, f"{tool.name} 的 schema 没有 properties"


def test_every_tool_schema_declares_its_arguments() -> None:
    """每个工具的 schema 里都有参数（没有无参工具）。

    判别性：一期十个工具都有参数；若出现一个 `properties == {}` 的工具，
    说明它的 `args_model` 忘了声明字段——那会让模型的参数无处可放。
    """
    for tool in build_product_tools():
        assert tool.parameters["properties"], f"{tool.name} 的 schema 里没有任何参数"


def test_registration_puts_all_tools_in_the_pool() -> None:
    """`register_product_tools` 真的把十个都放进了池。"""
    pool = ToolPool()
    register_product_tools(pool)
    assert pool.names() == tuple(EXPECTED_TOOL_NAMES)
    assert [t.name for t in pool.declared()] == EXPECTED_TOOL_NAMES


def test_double_registration_is_rejected_not_silently_ignored() -> None:
    """重复注册抛错——不得静默覆盖：重名会让权限判定面对含义不明的名字。

    （池自己有此纪律，本用例确认装配处走的是会被校验的那条通道。）
    """
    pool = ToolPool()
    register_product_tools(pool)
    with pytest.raises(ToolRegistrationError):
        register_product_tools(pool)


def test_build_is_stable_across_calls() -> None:
    """清单顺序稳定（按名排）——装配处与测试据此比对，不必排序。"""
    names = [t.name for t in build_product_tools()]
    assert names == [t.name for t in build_product_tools()]
    assert names == sorted(names), "清单顺序按工具名排列（既有约定）"


def test_every_tool_name_matches_its_contract_file() -> None:
    """每个工具名都有一份同名契约文档（`docs/技术设计/面/consult/tools/<name>.md`）。

    判别性：新增一个工具却忘了写契约，本用例失败——契约是「这个工具该做什么」的
    唯一真源，实现先于契约会让行为无处可核。
    """
    from pathlib import Path

    contract_root = Path(__file__).resolve().parents[3] / "docs" / "技术设计" / "面" / "consult" / "tools"
    for name in EXPECTED_TOOL_NAMES:
        assert (contract_root / f"{name}.md").is_file(), f"{name} 缺少契约文档"
