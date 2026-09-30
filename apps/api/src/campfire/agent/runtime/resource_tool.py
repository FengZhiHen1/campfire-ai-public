"""模型侧资源读取：`read_skill_resource` 工具（基座机制工具，保留名、恒可用）。

职责：把已激活 skill 的资源文件内容作为工具结果回给模型，兑现激活载荷里的资源清单。
边界：只读已激活 skill 的资源，边界校验复用资源模块的判据（不在这里重写）；不落库。
参考：docs/技术设计/technical-details/通用基座.md 第 3 节「资源」行（2026-09-29 补）。
"""

# 依据第 3 节「资源」行（2026-09-29 补）：激活载荷里的 `<skill_resources>` 清单必须
# 有一件能读的工具与之配套，否则那就是一份「列出却读不到的清单」。DSH 的做法是让模型用
# 通用文件读取工具直接读宿主文件系统——Campfire 的模型没有、也不该有任意文件访问，因此
# 资源读取是基座机制工具，与 `skill` 激活工具同级（保留名、恒可用），而不是产品侧业务工具。
#
# 与 `skill` 工具同放 `runtime/`：同样要同时用到 `tools` 与 `skill_runtime`，
# 放 `skill_runtime` 会形成部分初始化环（见 `skill_tool` 模块头的依赖方向说明）。

from __future__ import annotations

from pydantic import BaseModel, Field

from campfire.agent.skill_runtime import SkillNotFoundError, SkillRegistry, read_resource
from campfire.agent.tools import (
    ToolContext,
    ToolFailure,
    ToolOutcome,
    ToolResult,
    ToolSpec,
)

READ_SKILL_RESOURCE_TOOL_NAME = "read_skill_resource"
"""模型侧资源读取工具的名字。与 `tools.pool.RESERVED_TOOL_NAMES` 是同一个名字。"""

_DESCRIPTION = (
    "读取一个已激活 skill 的资源文件（references/ 或 assets/ 下、一层深）。"
    "可用路径见激活时给出的 <skill_resources> 清单；未激活的 skill 需先用 skill 工具激活。"
)

_MAX_PATH_ECHO = 128
"""回给模型的资源路径上限。

路径是模型可控的字符串：与 skill 名同理，超长回显只会撑爆工具结果消息而没有信息量，
截断到这个长度已足以辨认「它编了一个路径」。转义与 `skill` 工具用同一个转义器。"""

_MAX_NAME_ECHO = 64
"""回给模型的 skill 名上限（与激活工具同值，理由见 `skill_tool` 模块）。"""


class ReadSkillResourceArgs(BaseModel):
    """读取参数。"""

    skill: str = Field(
        min_length=1,
        max_length=_MAX_NAME_ECHO,
        description="资源所属的 skill 名，必须与激活时的名字逐字一致。",
    )
    path: str = Field(
        min_length=1,
        max_length=_MAX_PATH_ECHO,
        description="资源相对路径，形如 references/xxx.md，必须是 <skill_resources> 清单里列出的路径。",
    )


def _echo(text: str, limit: int) -> str:
    """把模型可控的字符串压成可安全回显的一小段（截断 + 转义）。"""
    from campfire.agent.markup import escape_attribute

    return escape_attribute(text[:limit])


def build_read_skill_resource_tool(registry: SkillRegistry) -> ToolSpec[ReadSkillResourceArgs]:
    """构造模型侧的资源读取工具。

    由装配处用 `ToolPool.register_base` 注册（它使用基座保留名）。

    两条行为约定：

    - 只允许读已激活 skill 的资源（`ToolContext.activated_skills`）：未激活的 skill
      连正文都读不到，资源却可读会让渐进披露的第三层形同虚设——尤其 `autoload=false`
      的 skill，模型侧激活被拒，资源更不该被旁路。未激活时返回可恢复失败并提示先激活。
    - 边界校验复用资源模块的同一套判据（一层深、防越界、体积上限、UTF-8），不在这里
      重写——读取失败的原因说明已经足够具体，模型可以据此换一个路径重试或放弃。
    """

    async def handler(context: ToolContext, args: ReadSkillResourceArgs) -> ToolOutcome:
        """先查激活状态，再走资源模块的读取。"""
        if args.skill not in context.activated_skills:
            return ToolFailure(
                code="tool_not_available",
                message=(
                    f"skill {_echo(args.skill, _MAX_NAME_ECHO)} 本次运行未激活，"
                    "其资源不可读取；请先用 skill 工具激活它。"
                ),
            )

        try:
            skill = registry.get(args.skill)
        except SkillNotFoundError:
            # 已激活却查不到：注册表与激活集合不一致，属于装配错误——显式失败，
            # 不静默当作「资源不存在」。
            return ToolFailure(
                code="tool_not_registered",
                message=f"skill {_echo(args.skill, _MAX_NAME_ECHO)} 已激活但不在注册表中（装配不一致）",
            )

        try:
            content = read_resource(skill, args.path)
        except Exception as exc:  # noqa: BLE001 —— 资源模块的显式拒绝统一转成可恢复失败
            return ToolFailure(
                code="tool_failed",
                message=f"资源 {_echo(args.path, _MAX_PATH_ECHO)} 读取失败：{exc}",
            )

        return ToolResult(text=content)

    return ToolSpec(
        name=READ_SKILL_RESOURCE_TOOL_NAME,
        description=_DESCRIPTION,
        args_model=ReadSkillResourceArgs,
        handler=handler,
    )
