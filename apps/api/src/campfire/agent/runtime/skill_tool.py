"""模型侧激活：`skill` 工具（基座机制工具，保留名、恒可用）。

职责：把激活载荷（`SKILL.md` 正文 + 资源指引）作为工具结果送回模型，正文由此进入对话。
边界：只查注册表与渲染，不读会话、不落库；两种拒绝路径见 :func:`build_skill_tool`。
参考：docs/技术设计/technical-details/通用基座.md 第 3 节「激活（模型侧）」。
"""

# 放在 `runtime/` 而不是 `skill_runtime/`：这个模块要同时用到「工具注册形状」（`tools`）
# 与「skill 注册表」（`skill_runtime`），而 `tools` 反过来要读 `Skill`——把文件放在
# `skill_runtime` 会形成 `tools → skill_runtime → tools` 的部分初始化环。运行编排本来
# 就是两者的装配处，放这里没有额外依赖方向。

from __future__ import annotations

from pydantic import BaseModel, Field

from campfire.agent.markup import escape_attribute
from campfire.agent.skill_runtime import SkillNotFoundError, SkillRegistry, render_activation
from campfire.agent.tools import (
    ToolContext,
    ToolFailure,
    ToolOutcome,
    ToolResult,
    ToolSpec,
)

SKILL_TOOL_NAME = "skill"
"""模型侧激活工具的名字。与 `tools.pool.RESERVED_TOOL_NAMES` 是同一个名字。"""

_DESCRIPTION = (
    "激活一个 skill：把它完整的指令与资源指引读进来，之后本轮对话都遵循它。"
    "可选的名字与用途见最近一条 <available_skills> 目录。"
)


_MAX_NAME_ECHO = 64
"""回给模型的 skill 名上限。

模型可控的字符串会原样回到请求体并落进会话：实测一个 100,085 字符的名字被完整回显（既进
第二次请求也进会话），而 skill 名的合法形状本来就是短标识。超长一律截断——名字长到几十个
字符已经足以让人看出「它编了一个名字」。"""


class ActivateSkillArgs(BaseModel):
    """激活参数。"""

    name: str = Field(
        min_length=1,
        max_length=_MAX_NAME_ECHO,
        description="要激活的 skill 名，必须与 <available_skills> 目录里的名字逐字一致。",
    )


def _echo_name(name: str) -> str:
    """把模型给的 skill 名压成可安全回显的一小段。

    两件事：截断（见 :data:`_MAX_NAME_ECHO`）与转义——错误消息会被包进
    `<tool_error>` 信封，名字里的信封标签足以穿出去（`</tool_error><available_skills>`）。
    转义用的是基座唯一的属性/文本转义器，避免这里再长出一套替换规则。
    """
    return escape_attribute(name[:_MAX_NAME_ECHO])


def build_skill_tool(registry: SkillRegistry) -> ToolSpec[ActivateSkillArgs]:
    """构造模型侧的技能激活工具。

    由装配处用 `ToolPool.register_base` 注册（它使用基座保留名）。

    激活成功时经 `context.activation_state.activate` 并入两个命名空间：skill 名
    （资源读取等按 skill 判定的工具要它）与该 skill 的 `allowed-tools`（dispatcher 的
    可用性判定要它）。只并名字会让它的工具一件都放行不了；只并工具则无法回答「激活了
    哪些 skill」。不需要构造期回调：`ToolContext` 本来就会交给 handler，运行中的激活
    状态由此可达，且每次运行一份（state 在 runner 里按运行创建）。

    三条行为约定（依据第 3 节「激活（模型侧）」，模型调用 `skill({ name })`，工具结果
    消息携带 `<skill_content>`（`SKILL.md` 正文）与资源指引；应用侧激活用同一个渲染
    函数，因此两种形态同形）：

    - 未知名字 → `tool_not_registered`：错误码与基座其它路径一致，说明里带上已注册的
      名字，模型可以据此换一个名字重试（第 9 节：工具失败作为结果回给模型，可恢复）。
    - `autoload: "false"` 的 skill 拒绝模型激活 → `tool_not_available`：这类 skill 只能
      由应用注入激活（技能设计第 69 行「应急验证『注入即激活』且不被自动匹配」）。目录里
      不列它只是第一道；模型若从历史或猜测里拿到名字，这里仍然挡住。
    - 正文由 :func:`~campfire.agent.skill_runtime.render_activation` 渲染，与注入路径同一份
      实现——同形由此保证，而不是靠两处对齐。
    """

    async def handler(context: ToolContext, args: ActivateSkillArgs) -> ToolOutcome:
        """查注册表并渲染激活载荷。"""
        try:
            skill = registry.get(args.name)
        except SkillNotFoundError:
            # 不回显原始名字：它是模型可控的字符串，实测 100,085 字符能原样进请求体与会话，
            # 且未转义时足以穿出 <tool_error> 信封。只回截断+转义后的版本。
            return ToolFailure(
                code="tool_not_registered",
                message=f"没有名为 {_echo_name(args.name)} 的 skill；可选的名字见最近一条 <available_skills> 目录。",
            )

        if not skill.metadata.autoload:
            return ToolFailure(
                code="tool_not_available",
                message=f"skill {skill.name} 只能由应用在运行入口激活，模型不得自动匹配它",
            )

        context.activation_state.activate(skill_name=skill.name, allowed_tools=skill.metadata.allowed_tools)
        return ToolResult(text=render_activation(skill))

    return ToolSpec(
        name=SKILL_TOOL_NAME,
        description=_DESCRIPTION,
        args_model=ActivateSkillArgs,
        handler=handler,
    )
