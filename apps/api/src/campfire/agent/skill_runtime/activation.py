"""技能激活：渲染 `<skill_content>` 载荷。

依据 docs/技术设计/technical-details/通用基座.md 第 3 节，激活有两种落地形态：

- 模型侧：模型调用 `skill({ name })` 工具，工具结果消息携带本模块渲染的载荷；
- 应用侧：应用读取同一份 `SKILL.md`，把同形内容作为消息放进本轮 `input`。

两种形态必须同形，差别只在发起者。因此这里只有一个渲染函数，两侧都调用它；
「同形」由同一份实现保证，而不是靠两处各写一遍再对齐。
"""

from __future__ import annotations

from campfire.agent.markup import escape_attribute

from .resources import list_resources
from .skill import Skill


def render_activation(skill: Skill) -> str:
    """渲染激活载荷：正文 + 资源指引。

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
