"""产品侧工具的注册清单：把 `tools/*` 的实现包成 `ToolSpec` 注册进池。

职责：声明池里有哪些产品侧工具，供各装配处共同取用。
边界：只负责「池里有什么」，不决定模型实际可见范围；不实现面的路由。
参考：docs/项目结构设计.md 第 7 节；通用基座第 5 节；
docs/技术设计/technical-details/技能设计.md 第 3 节（十个工具的清单）。
"""

from __future__ import annotations

from campfire.agent.runtime.ask_user_tool import build_ask_user_tool
from campfire.agent.tools import Tool, ToolPool, ToolSpec
from campfire.tools.emergency_card import EmitEmergencyActionCardArgs, emit_emergency_action_card
from campfire.tools.library import SearchCasesArgs, SearchKnowledgeArgs, search_cases, search_knowledge
from campfire.tools.memory import ReadMemoryArgs, WriteMemoryArgs, read_memory, write_memory
from campfire.tools.onboarding import FinishOnboardingArgs, finish_onboarding
from campfire.tools.profile import (
    CreateSupportObjectArgs,
    ProposeProfileItemArgs,
    ReadProfileItemsArgs,
    ReadProfileSummaryArgs,
    create_support_object,
    propose_profile_item,
    read_profile_items,
    read_profile_summary,
)

#: `read_memory` 的工具说明。写成模型选工具的唯一依据（`ToolPool` 会校验非空）：
#: 必须说清「什么时候用」——按时间回看使用者说过的事。
_READ_MEMORY_DESCRIPTION = (
    "按时间回看你记得的、这位使用者说过或经历过的事。"
    "当你需要引用他之前提过的情况、症状、偏好或事件时使用。"
    "返回按发生时间排列的条目；不等于使用者档案，需要稳定的画像请用档案类工具。"
)

#: `write_memory` 的工具说明。强调它是异步提交，避免模型以为写完就能立刻读到。
_WRITE_MEMORY_DESCRIPTION = (
    "提交一条值得记住的事（使用者陈述、观察、第三方转述等）。"
    "这是异步提交：调用成功只表示已受理，不会立刻出现在回看结果里。"
    "不要用它记录临时寒暄或与长期陪伴无关的内容。"
    "关于支持对象本身的事实**不要**写这里——那要走档案工具。"
)

#: `search_knowledge` 的工具说明。
_SEARCH_KNOWLEDGE_DESCRIPTION = (
    "在本项目的专业资料库（研究、指南、机构材料）里检索，为你的建议找依据。"
    "只查专业资料，不含案例。返回条目带出处与适用范围——"
    "引用时必须说明适用条件；检索为空时不等于该做法不存在或没有风险。"
)

#: `search_cases` 的工具说明。与 `search_knowledge` 的分工要说清，否则模型会二选一乱用。
_SEARCH_CASES_DESCRIPTION = (
    "在案例库里检索相似情形，供使用者参考「别人遇到过什么、试过什么」。"
    "只查案例，不含专业资料。与专业资料检索的分工：要依据用专业资料，要同类经验用案例。"
    "案例带授权状态、循证等级与审阅状态——引用时必须说明案例性质，"
    "不得把虚构样例包装成真实经验；检索为空时不等于没有这种情形。"
)

#: `read_profile_summary` 的工具说明。它是最常用的只读工具（契约第 1 节）。
_READ_PROFILE_SUMMARY_DESCRIPTION = (
    "取某个支持对象的一页档案摘要（概览），用于个性化你的回应。"
    "当你需要知道「这个人是谁、怎么沟通、什么对他重要」时优先用它。"
    "只含已被使用者确认或直接陈述的稳定内容，不含未确认的推断；"
    "没有档案时返回明确的「无档案」标记，此时要在输出里标注本次未使用个性化档案。"
    "需要条目级细节（比较几种支持方式、核对某条记录）时改用条目读取工具。"
)

#: `read_profile_items` 的工具说明。与摘要的分工：概览用摘要，细节用本工具。
_READ_PROFILE_ITEMS_DESCRIPTION = (
    "按条件读取具体档案条目（细节），用于比较几种支持方式、核对某条记录或整理去重。"
    "每条都带生成方式与确认状态：标为候选（candidate）的是未经使用者确认的推断，"
    "**不得**当作事实陈述或作为建议依据。查已否定的内容不会有结果——使用者否定过的不再返回。"
)

#: `propose_profile_item` 的工具说明。它是档案的唯一写入口，因此要说清「已经出现过」这一前提。
_PROPOSE_PROFILE_ITEM_DESCRIPTION = (
    "把对话中已经出现过的、关于某个支持对象的信息提成档案条目。这是档案的唯一写入口。"
    "只提「已经出现过」的内容：缺的字段留空，不推断补全，不编造未出现过的内容。"
    "提交前先用条目读取工具看现有条目，避免重复。"
    "这是异步提交：成功只表示已受理，不会立刻出现在摘要里。"
    "落层由 origin 决定（推断类只进候选层，要使用者确认才成事实），不由调用方指定。"
    "关于使用者本人（而不是支持对象）的事走记忆工具，不要写档案。"
)

#: `create_support_object` 的工具说明。
_CREATE_SUPPORT_OBJECT_DESCRIPTION = (
    "创建一个支持对象（档案的归属主体），返回它的标识与名称。"
    "引导对话里用它建立第一个对象；引导之外也可以建后续对象。"
    "对象名取使用者自己给的称呼——不要问姓名、生日或联系方式等可识别身份的信息。"
    "空名或全空白名会被拒绝，不要试图用默认名代替。"
)

#: `finish_onboarding` 的工具说明。它只在引导激活期间可用。
_FINISH_ONBOARDING_DESCRIPTION = (
    "引导收束段的最后一步：把本账号的引导状态标记为已完成，此后日常会话不再注入引导。"
    "流程走完时调用一次即可，重复调用是幂等的。"
    "即使全程跳过了各段，收束段仍要走完并调用它——跳过档案种子不等于跳过引导。"
    "只记录本次跳过了哪些段（skipped_sections），不改变状态取值。"
)

#: `emit_emergency_action_card` 的工具说明。它是应急 skill 唯一的结构化输出通道。
_EMIT_EMERGENCY_ACTION_CARD_DESCRIPTION = (
    "发出一张应急现场行动卡（应急场景唯一的结构化输出通道）。"
    "七节按固定顺序：当前状态、立即怎么沟通、立即做、不要做、需要的医疗检查、安全措施、何时升级；"
    "每节至少一行，用可执行语言而不是抽象标签。"
    "四个状态字段的取值受词表硬校验，越界会被拒绝而不是被改成合法值——"
    "因此先把判断定下来再调用，不要指望工具替你圆。"
    "调用后运行不结束，你可以继续追问或收尾；重复评估时再发一张新卡即可（卡片标识会自动区分新旧）。"
)


def build_product_tools() -> list[Tool]:
    """构造产品侧工具的注册清单（顺序稳定，便于比对与测试）。

    归属（项目结构设计见 docs/项目结构设计.md 第 7 节）：
    工具注册在装配处完成，因此 `agent/*` 不需要 import `tools/*`——本模块属于
    装配处一侧，`agent/*` 不会反过来依赖它。

    为什么单独一个 `registry.py` 而不是写进 `surfaces/consult`：

    `surfaces/consult/` 是面的运行装配（HTTP 与 SSE 契约、应急表单到一次运行的装配）。
    工具注册清单与「面怎么发请求」无关：Worker 侧或 CLI 侧将来若要跑一次运行，需要的是
    同一份工具清单，而不是某一个面的路由。因此清单独立于此，由各装配处（面、Worker）
    共同取用——「工具注册在装配处完成」指的是由装配处调用本模块，而不是把清单抄在每个
    装配处里（抄两份必然漂移）。

    已注册（2026-09-30，十个齐备）；工具 → 归属模块：

    - `read_profile_summary` / `read_profile_items` / `propose_profile_item` /
      `create_support_object` → `modules/profile`
    - `read_memory` / `write_memory` → `modules/memory`
    - `search_knowledge` / `search_cases` → `modules/library`
    - `finish_onboarding` → `modules/accounts`
    - `emit_emergency_action_card` → 本清单（不读写业务数据）

    此前这里记着「只注册 3 个，未注册 6 个依赖不存在」——那段陈述的前提（案例表与字段
    不存在、`modules/profile` 是零实现占位包、引导状态表仓储未落地）已随 T02/T03 与本次
    改动全部满足，因此整段替换为当前事实，不留过期陈述。

    `emit_emergency_action_card` 的归属裁决（T04 裁决 2）：技能设计第 3 节把它列进
    十个模型可见工具，但它不属任何业务模块——不读写业务数据，只承载输出形状。
    实现放 `tools/emergency_card.py`，与 library/memory 工具同目录同风格；
    它确实一个 `modules/*` 都不 import，这是它的诚实边界而不是遗漏。

    `finish_onboarding` 的归属裁决（T04 裁决 3）：状态表的用例归
    `modules/accounts/onboarding_completion.py`（表的所有者），本清单只做契约映射。

    不注册也不该注册的 1 个：`delete_memory` 不存在——记忆的删除与纠正由记忆面的
    HTTP 契约承载（决策记录见 docs/技术设计/decisions/记忆删除走用户确认入口.md）。

    工具范围与 skill 的关系：

    注册进池不等于模型全都看得见：`allowed-tools` 与激活集合决定实际可用范围
    （通用基座见 docs/技术设计/technical-details/通用基座.md 第 5 节）。
    本模块只负责「池里有什么」。若某个工具在某个 skill 未激活时也不可用，
    拒绝由 `ToolDispatcher` 发出（`tool_not_available`），不由这里控制。

    Returns:
        `ToolSpec` 列表。顺序按工具名排列——顺序本身不承载语义，稳定即可。
    """
    return [
        ToolSpec(
            name="create_support_object",
            description=_CREATE_SUPPORT_OBJECT_DESCRIPTION,
            args_model=CreateSupportObjectArgs,
            handler=create_support_object,
        ),
        ToolSpec(
            name="emit_emergency_action_card",
            description=_EMIT_EMERGENCY_ACTION_CARD_DESCRIPTION,
            args_model=EmitEmergencyActionCardArgs,
            handler=emit_emergency_action_card,
        ),
        ToolSpec(
            name="finish_onboarding",
            description=_FINISH_ONBOARDING_DESCRIPTION,
            args_model=FinishOnboardingArgs,
            handler=finish_onboarding,
        ),
        ToolSpec(
            name="propose_profile_item",
            description=_PROPOSE_PROFILE_ITEM_DESCRIPTION,
            args_model=ProposeProfileItemArgs,
            handler=propose_profile_item,
        ),
        ToolSpec(
            name="read_memory",
            description=_READ_MEMORY_DESCRIPTION,
            args_model=ReadMemoryArgs,
            handler=read_memory,
        ),
        ToolSpec(
            name="read_profile_items",
            description=_READ_PROFILE_ITEMS_DESCRIPTION,
            args_model=ReadProfileItemsArgs,
            handler=read_profile_items,
        ),
        ToolSpec(
            name="read_profile_summary",
            description=_READ_PROFILE_SUMMARY_DESCRIPTION,
            args_model=ReadProfileSummaryArgs,
            handler=read_profile_summary,
        ),
        ToolSpec(
            name="search_cases",
            description=_SEARCH_CASES_DESCRIPTION,
            args_model=SearchCasesArgs,
            handler=search_cases,
        ),
        ToolSpec(
            name="search_knowledge",
            description=_SEARCH_KNOWLEDGE_DESCRIPTION,
            args_model=SearchKnowledgeArgs,
            handler=search_knowledge,
        ),
        ToolSpec(
            name="write_memory",
            description=_WRITE_MEMORY_DESCRIPTION,
            args_model=WriteMemoryArgs,
            handler=write_memory,
        ),
    ]


def register_product_tools(pool: ToolPool) -> None:
    """把产品侧工具注册进给定的池（装配处调用一次）。

    用 `register`（产品侧）而不是 `register_base`：后者是基座保留名的通道
    （`skill` / `read_skill_resource` / `ask_user`），产品工具占用它会被拒。

    本函数不注册 `ask_user`：它是基座保留名的工具，走 `register_base`
    （见 `register_base_tools`）。混在一起注册会掩盖这个区别——而区别是有意义的：
    保留名工具恒可用、不进 `allowed-tools` 的并集，产品工具则受 skill 范围控制。

    Raises:
        ToolRegistrationError: 重名，或名字/描述不合规（由池校验）。
    """
    for tool in build_product_tools():
        pool.register(tool)


def register_base_tools(pool: ToolPool) -> None:
    """把基座保留名的工具注册进池（`register_base` 通道）。

    目前只有 `ask_user`：提问是运行的中止方式之一，不是某个 skill 的特权，因此它
    恒可用、不进 `allowed-tools` 的并集（通用基座第 7.2 节）。

    为什么由本模块（装配处一侧）注册它：`agent/*` 不得 import `tools/*`，也不负责
    自己的装配；工具池的装配点是装配处，而本模块正是那个装配点的清单所有者。
    另外两个保留名工具（`skill` / `read_skill_resource`）由运行装配按需构造
    （它们要拿 skill 注册表，属运行编排的装配细节），因此不在这里——本函数只收
    不需要额外依赖的那一个。

    重名由池校验并拒绝（`ToolRegistrationError`），与本模块其余注册同一条纪律。
    """
    pool.register_base(build_ask_user_tool())


__all__ = ["build_product_tools", "register_base_tools", "register_product_tools"]
