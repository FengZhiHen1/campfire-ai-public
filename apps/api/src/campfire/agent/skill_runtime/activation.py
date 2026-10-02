"""技能激活：渲染 `<skill_content>` 载荷与合成激活记录。

职责：渲染激活载荷（正文 + 资源指引），以及构造应用侧激活的合成工具调用记录对；
模型侧与应用侧共用同一渲染，保证两种形态同形。
边界：只渲染与构造，不执行脚本；不落库（记录由面放进本轮 input，随运行写入会话）。
参考：docs/技术设计/technical-details/通用基座.md 第 3 节「激活」与第 5 节
「本次运行的可用集」。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence

from campfire.agent.markup import escape_attribute

from .resources import list_resources
from .skill import Skill

_ACTIVATION_OUTPUT_PREFIX = "<skill_content"
"""激活成功载荷的信封前缀；配对判定用它区分成功激活与被拒绝的调用。"""

_SKILL_TOOL_RECORD_NAME = "skill"
"""激活记录对里 function_call 的工具名；与 `runtime.skill_tool` 的保留名同值。

两处各写一份字面量（`skill_runtime` 不得 import `runtime`，依赖方向见
`skill_tool` 模块头）；一致性由 `test_skills_content.py` 之外的专项用例钉住。
"""


def render_activation(skill: Skill) -> str:
    """渲染激活载荷：正文 + 资源指引。

    依据 docs/技术设计/technical-details/通用基座.md 第 3 节，激活有两种落地形态：

    - 模型侧：模型调用 `skill({ name })` 工具，工具结果消息携带本模块渲染的载荷；
    - 应用侧：应用读取同一份 `SKILL.md`，把同形内容作为消息放进本轮 `input`。

    两种形态必须同形，差别只在发起者。因此这里只有一个渲染函数，两侧都调用它；
    「同形」由同一份实现保证，而不是靠两处各写一遍再对齐。

    资源指引只列 `references/` 与 `assets/`（一层深）。`scripts/` 刻意不列：
    一期不提供脚本执行（基座文档第 10 节只保留端口），列出可执行路径会诱导模型
    调用一个不存在的能力。

    存在但读不了的资源照样列出并带 `reason`：让模型知道「有这份东西但读不到」，
    比让它从清单里消失更接近事实（第 4 节：注入失败必须显式标注该来源不可用）。
    """
    resources = list_resources(skill)
    lines = [f'<skill_content name="{escape_attribute(skill.name)}">', skill.body, "</skill_content>"]

    if resources:
        lines.append("<skill_resources>")
        for resource in resources:
            path = escape_attribute(resource.relative_path)
            if resource.issue is None:
                lines.append(f'  <resource path="{path}" />')
            else:
                lines.append(f'  <resource path="{path}" reason="{escape_attribute(resource.issue)}" />')
        lines.append("</skill_resources>")
    return "\n".join(lines)


def build_activation_record(skill: Skill, *, call_id: str | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """构造应用侧激活的合成工具调用记录对：`(function_call, function_call_output)`。

    依据通用基座第 3 节：激活记录是授权真源——三种发起方式（模型匹配、使用者手选、
    程序注入）落库形态统一为会话历史里的 skill 工具调用记录。模型侧由 SDK 真实调用
    产生这对记录；应用侧由本函数合成同形记录，放进本轮 `input`，随运行写入会话。

    同形的三层含义，全部由「与 `skill` 工具共用 `render_activation`」保证：

    - 载荷同形：结果消息的正文就是激活载荷，与模型侧工具结果逐字一致；
    - 通道同形：记录经 SDK 会话落库，水合与窗口派生对两者一视同仁；
    - 判定同形：授权推导只认这对记录的名字，不区分发起者。

    与模型侧的唯一差别是把关者：模型侧受 `autoload` 门拒绝（`autoload: "false"`
    的 skill 模型激活不了），应用侧由业务触发条件把关——本函数不判定任何一边，
    调用方（面）必须先确认触发条件成立。

    Args:
        skill: 要激活的 skill（触发条件由调用方判定）。
        call_id: 记录对的调用标识；缺省生成一个不透明的 uuid。同一轮 input 里
            多条合成记录时由调用方传入稳定值，便于排查时对应。

    Returns:
        `(function_call, function_call_output)` 两项，形状与 SDK 落库的条目一致
        （`type` / `call_id` / `name` / `arguments` 与 `output`）。
    """
    resolved_call_id = call_id if call_id is not None else f"app-{uuid.uuid4().hex}"
    call: dict[str, str] = {
        "type": "function_call",
        "call_id": resolved_call_id,
        "name": _SKILL_TOOL_RECORD_NAME,
        "arguments": json.dumps({"name": skill.name}),
    }
    output: dict[str, str] = {
        "type": "function_call_output",
        "call_id": resolved_call_id,
        "output": render_activation(skill),
    }
    return call, output


def activation_names_from_history(history: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """从会话历史里读出全部激活记录的 skill 名（按首次出现顺序，去重）。

    授权真源的读取端（通用基座第 3、5 节）：每次运行开始时扫全量历史，把 `skill`
    工具调用记录的名字并集进本次可用工具集。

    判据与边界：

    - 只认工具名为 `skill` 的 `function_call` 条目，且必须配对到成功结果：
      没有配对结果（运行被打断）或结果是失败信封（`autoload` 门拒绝的调用）的，
      不构成激活记录——授权不得来自半截记录或被拒绝的调用。
    - `arguments` 是模型或应用写入的 JSON 文本，解析失败或顶层不是对象时该记录
      作废（跳过等于无授权，方向安全：宁可漏授权被服务端拒绝，不可凭坏记录放行）。
    - 扫全量历史而非模型窗口：激活记录可能被窗口裁掉，但授权不得随窗口丢失
      ——否则会话中途被权限拒绝打断，恰是该裁决要修复的缺陷形状。

    Args:
        history: 会话历史条目（SDK 读回形状；普通消息没有 `type` 字段）。

    Returns:
        已激活的 skill 名元组，按首次出现顺序；没有激活记录时为空元组。
    """
    succeeded_call_ids: set[str] = set()
    for item in history:
        if item.get("type") != "function_call_output":
            continue
        call_id = item.get("call_id")
        output = item.get("output")
        if isinstance(call_id, str) and isinstance(output, str) and output.startswith(_ACTIVATION_OUTPUT_PREFIX):
            succeeded_call_ids.add(call_id)

    names: list[str] = []
    for item in history:
        if item.get("type") != "function_call" or item.get("name") != _SKILL_TOOL_RECORD_NAME:
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or call_id not in succeeded_call_ids:
            continue
        arguments = item.get("arguments")
        if not isinstance(arguments, str):
            continue
        try:
            parsed = json.loads(arguments)
        except ValueError:
            continue
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return tuple(names)
