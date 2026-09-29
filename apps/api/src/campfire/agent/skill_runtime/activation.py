"""技能激活：渲染 ``<skill_content>`` 载荷。

依据 docs/技术设计/technical-details/通用基座.md 第 3 节，激活有两种落地形态：

- **模型侧**：模型调用 ``skill({ name })`` 工具，工具结果消息携带本模块渲染的载荷；
- **应用侧**：应用读取同一份 ``SKILL.md``，把同形内容作为消息放进本轮 ``input``。

两种形态**必须同形**，差别只在发起者。因此这里只有一个渲染函数，两侧都调用它；
「同形」由同一份实现保证，而不是靠两处各写一遍再对齐。
"""

from __future__ import annotations

from .resources import list_resources
from .skill import Skill


def render_activation(skill: Skill) -> str:
    """渲染激活载荷：正文 + 资源指引。

    资源指引只列 ``references/`` 与 ``assets/``（一层深）。``scripts/`` 刻意不列：
    一期不提供脚本执行（基座文档第 10 节只保留端口），列出可执行路径会诱导模型
    调用一个不存在的能力。
    """
    resources = list_resources(skill)
    lines = [f'<skill_content name="{skill.name}">', skill.body, "</skill_content>"]

    if resources:
        lines.append("<skill_resources>")
        lines.extend(f"  {resource.relative_path}" for resource in resources)
        lines.append("</skill_resources>")
    return "\n".join(lines)
