"""向使用者提问：`ask_user` 工具（基座机制工具，保留名、恒可用）。

职责：把模型给的题组装成一组提问载荷（含工具侧生成的 `batch_id`）交回运行编排。
边界：只装箱与校验形状，不产出领域词表、不落库；「结束本次运行并发出事件」是运行编排的职责。
参考：docs/技术设计/technical-details/通用基座.md 第 7.2 节。
"""

# 放在 `runtime/` 而不是 `tools/`：这个模块要用到运行编排使用的载荷类型，而 `tools/`
# 是基座与产品侧共用的注册形状——提问是运行编排行为（发出即结束运行），与 `skill`、
# `read_skill_resource` 同属机制工具，三个都放 `runtime/`。
#
# 依据第 7.2 节「产生方式」：基座提供 `ask_user` 工具，参数即提问载荷；模型调用它即结束
# 本次运行并发出 `question` 事件。它经 `register_base` 注册、恒可用（不进 `allowed-tools`
# 的并集）——提问是运行的中止方式之一，不是某个 skill 的特权。不靠解析自由文本猜提问，
# 保证选项形状可校验；skill 在指令里约束何时使用与选项的措辞纪律。

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from campfire.agent.tools import Question, QuestionItem, ToolContext, ToolOutcome, ToolResult, ToolSpec

ASK_USER_TOOL_NAME = "ask_user"
"""向使用者提问的工具名。与 `tools.pool.RESERVED_TOOL_NAMES` 是同一个名字。"""

_DESCRIPTION = (
    "向使用者提出一组结构化问题，用来补齐你无法自行判断、又必须知道的信息。"
    "调用它会结束本次运行：使用者看到问题卡片，回答会作为下一条消息回到你这里，"
    "你在下一次运行里继续。"
    "一次调用就是一次批量提交：本次需要一起确认的题放进同一个 items 数组，"
    "不要为同一批信息分几次问。"
    "若流程本身分阶段推进（下一阶段要依据这一阶段的回答），按阶段每轮一题即可，"
    "这时一组只有一道题——两种用法不冲突，判据是「这批答案要不要一起去确认」。"
    "每道题都要给 options（纯自由回答的题给空数组）与 allow_skip；"
    "能给出选项的就给选项，选项措辞要中立、不要把答案写成暗示。"
    "能从已有上下文或工具读出答案的问题，不要问使用者。"
)


def _new_batch_id() -> str:
    """默认批次标识工厂：不透明且不重复。

    与引用标识同一种做法（见 `agent/context/citations.py` 的 `_new_citation_id`）：
    批次标识只用来把回答关联回这一组题，不承载业务含义，因此不发号、不落库。
    运行内唯一由机制保证——提问即结束本次运行，所以一次运行至多产出一个批次；
    而批次标识本身全局不重复。模型的输入里没有这个字段（见 :class:`AskUserArgs`），
    所以它无法提供标识，也就无法伪造或复用别人的批次。
    """
    return uuid.uuid4().hex


class AskUserArgs(BaseModel):
    """提问参数：只有 `items`。

    依据第 7.2 节的载荷形状，但刻意不含 `batch_id`：批准标识由工具侧生成，
    不信任模型传标识（模型传一个与历史批次重名的值会让回答被关联到错误的题组）。
    `extra="forbid"` 让模型多传的字段在解析期被拒（错误码 `tool_invalid_arguments`），
    而不是被静默忽略。

    严格模式的一个后果要写清楚：SDK 的 `ensure_strict_json_schema` 会把带默认值的属性
    也放进 `required`（实测 `options`、`allow_skip`、选项的 `description` 都进了必填），
    因此模型每次都要显式给出这些字段——`:data:`_DESCRIPTION` 里据此要求它「每道题都要给
    options 与 allow_skip」。本层的默认值仍然生效：模型漏给时不会报错，而是取默认值。
    """

    model_config = ConfigDict(extra="forbid")

    items: Annotated[
        list[QuestionItem],
        Field(min_length=1, description="本次一起确认的一组题；按数组顺序呈现给使用者。"),
    ]

    @model_validator(mode="after")
    def _require_unique_item_ids(self) -> "AskUserArgs":
        """题标识必须在批次内唯一。

        Raises:
            ValueError: 存在重复的题 `id`——回答回传时凭 `id` 关联，重复会让一道题的答案
                落到另一道上，且两题的回答互相覆盖而无人察觉（第 7.2 节「题标识（批次内唯一）」）。
        """
        seen: set[str] = set()
        duplicates: list[str] = []
        for item in self.items:
            if item.id in seen and item.id not in duplicates:
                duplicates.append(item.id)
            seen.add(item.id)
        if duplicates:
            raise ValueError(f"题标识在批次内重复：{'、'.join(duplicates)}")
        return self


def build_ask_user_tool() -> ToolSpec[AskUserArgs]:
    """构造向使用者提问的工具。

    由装配处用 `ToolPool.register_base` 注册（它使用基座保留名）。

    行为只有一件事：把参数装箱成 :class:`~campfire.agent.tools.payloads.Question`
    交回运行编排，`batch_id` 在这里生成。工具不自己发事件、也不结束运行——
    结束运行是 SDK 层面的行为（`tool_use_behavior`），只有运行编排能接；工具返回结果后
    由 :class:`~campfire.agent.runtime.assembly.ToolBridge` 翻成 `question` 事件。
    这样「什么是提问」与「提问如何结束一次运行」各自只有一处定义。
    """

    async def handler(_context: ToolContext, args: AskUserArgs) -> ToolOutcome:
        """把这一组题装箱；不读会话、不写库。"""
        return ToolResult(
            # 回给模型的话：它已经问完了，本次运行即将结束，不需要再输出正文。
            text="已向使用者发出提问，本次运行到此结束；回答会作为下一条消息到达。",
            question=Question(batch_id=_new_batch_id(), items=tuple(args.items)),
        )

    return ToolSpec(
        name=ASK_USER_TOOL_NAME,
        description=_DESCRIPTION,
        args_model=AskUserArgs,
        handler=handler,
    )
