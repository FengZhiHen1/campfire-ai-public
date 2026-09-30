"""产品侧工具的注册清单：把 `tools/*` 的实现包成 `ToolSpec` 注册进池。

职责：声明池里有哪些产品侧工具，供各装配处共同取用。
边界：只负责「池里有什么」，不决定模型实际可见范围；不实现面的路由。
参考：docs/项目结构设计.md 第 7 节；通用基座第 5 节。
"""

from __future__ import annotations

from campfire.agent.tools import Tool, ToolPool, ToolSpec
from campfire.tools.library import SearchKnowledgeArgs, search_knowledge
from campfire.tools.memory import ReadMemoryArgs, WriteMemoryArgs, read_memory, write_memory

#: `read_memory` 的工具说明。写成模型选工具的唯一依据（`ToolPool` 会校验非空）：
#: 必须说清「什么时候用」——按时间回看使用者说过的事。
_READ_MEMORY_DESCRIPTION = (
    "按时间回看你记得的、这位使用者说过或经历过的事。"
    "当你需要引用他之前提过的情况、症状、偏好或事件时使用。"
    "返回按发生时间排列的条目；**不等于**使用者档案，需要稳定的画像请用档案类工具。"
)

#: `write_memory` 的工具说明。强调它是异步提交，避免模型以为写完就能立刻读到。
_WRITE_MEMORY_DESCRIPTION = (
    "提交一条值得记住的事（使用者陈述、观察、第三方转述等）。"
    "这是**异步提交**：调用成功只表示已受理，不会立刻出现在回看结果里。"
    "不要用它记录临时寒暄或与长期陪伴无关的内容。"
)

#: `search_knowledge` 的工具说明。
_SEARCH_KNOWLEDGE_DESCRIPTION = (
    "在本项目的专业资料库（研究、指南、机构材料）里检索，为你的建议找依据。"
    "只查专业资料，不含案例。返回条目带出处与适用范围——"
    "引用时必须说明适用条件；检索为空时**不等于**该做法不存在或没有风险。"
)


def build_product_tools() -> list[Tool]:
    """构造产品侧工具的注册清单（顺序稳定，便于比对与测试）。

    归属（项目结构设计见 docs/项目结构设计.md 第 7 节）：
    工具注册在装配处完成，因此 `agent/*` 不需要 import `tools/*`——本模块属于
    装配处一侧，`agent/*` 不会反过来依赖它。

    为什么单独一个 `registry.py` 而不是写进 `surfaces/consult`：

    `surfaces/consult/` 是面的运行装配（HTTP 与 SSE 契约、应急表单到一次运行的装配），
    它还没有实现。工具注册清单与「面怎么发请求」无关：Worker 侧或 CLI 侧将来若要跑一次
    运行，需要的是同一份工具清单，而不是某一个面的路由。因此清单独立于此，由各装配处
    （面、Worker）共同取用——「工具注册在装配处完成」指的是由装配处调用本模块，
    而不是把清单抄在每个装配处里（抄两份必然漂移）。

    已注册与未注册（2026-09-30 实测）：

    已实现并在此注册的只有 3 个：

    工具 → 归属 → 状态
    - `read_memory` → `modules/memory` → ✅ 注册
    - `write_memory` → `modules/memory` → ✅ 注册
    - `search_knowledge` → `modules/library` → ✅ 注册

    未注册的 6 个，依赖不存在（不是遗漏）：

    - `search_cases`：案例条目表与 7 个案例专属字段都不存在，且检索链硬编码只查资料库。
      证据与前置见 `tools/library.py` 的模块说明。
    - `read_profile_summary` / `read_profile_items` / `propose_profile_item` / `create_support_object`：
      `modules/profile` 是零实现的占位包（只有 `__init__.py` 的 docstring），
      没有任何用例函数可包装。
    - `finish_onboarding`：归属 `modules/accounts`，该表的仓储尚未落地。

    不注册也不该注册的 1 个：`delete_memory` 不存在——记忆的删除与纠正由记忆面的
    HTTP 契约承载（决策记录见 docs/技术设计/decisions/记忆删除走用户确认入口.md）。

    工具范围与 skill 的关系：

    注册进池不等于模型全都看得见：`allowed-tools` 与激活集合决定实际可用范围
    （通用基座见 docs/技术设计/technical-details/通用基座.md 第 5 节）。
    本模块只负责「池里有什么」。

    Returns:
        `ToolSpec` 列表。顺序按工具名排列——顺序本身不承载语义，稳定即可。
    """
    return [
        ToolSpec(
            name="read_memory",
            description=_READ_MEMORY_DESCRIPTION,
            args_model=ReadMemoryArgs,
            handler=read_memory,
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
    （`skill` / `read_skill_resource`），产品工具占用它会被拒。

    Raises:
        ToolRegistrationError: 重名，或名字/描述不合规（由池校验）。
    """
    for tool in build_product_tools():
        pool.register(tool)


__all__ = ["build_product_tools", "register_product_tools"]
