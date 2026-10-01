"""咨询面的生产组合根：把零件装成一个可用的 `AgentRunner`。

职责：构造并持有长生命周期的协作者（模型网关），按配置把工具池、技能注册表、
引用索引与会话工厂装进 `AgentRunner`；`install()` 把它注入 `assembly` 的注入点。
边界：不做 HTTP（`routes`）、不实现零件（各自模块）；只负责「谁与谁组合」。
参考：docs/项目结构设计.md 第 7 节（依赖白名单）；docs/技术设计/technical-details/通用基座.md。

为什么需要这个模块（2026-10-01）：此前 `assembly.set_runner_factory` 只有测试调用点，
生产的 `main.py` 只记一条「尚未装配」的 warning，因此发消息端点在生产路径上必然回 503。
零件早就齐了（模型网关、工具池与 10 个产品工具、4 个 skill、SDK 会话、引用索引），
缺的正是这一处组合——本模块补的是它，不是任何新零件。

四条装配决定与理由：

1. 模型网关在这里构造并持有，不在每次请求里新建。`ModelGateway` 的 docstring 明写
   每次新建 `AsyncOpenAI` 会新建连接池与 TLS 握手，那份代价直接落在首字时延上。
   因此它是长生命周期对象：本模块持有，`aclose()` 在进程收尾时调用。
2. 工具池按请求重造（很便宜：只是赋值与集合运算，无 I/O），而技能注册表复用
   `assembly.get_skill_registry` 的按路径缓存——`AgentRunner.__init__` 会校验
   `allowed-tools` 全部已注册，喂给它和 `build_skill_tool` 的必须是同一个注册表
   实例，否则那条校验验的不是实际生效的那个池。
3. `skill` 与 `read_skill_resource` 两个保留名工具在池里注册：项目里有 `autoload=true`
   的 skill（`daily-consulting`、`profile-curation`），因此 `AgentRunner` 会强制要求池里
   有 `skill` 工具，否则装配期直接抛 `RuntimeAssemblyError`。这一条是组合根最容易踩的坑。
4. 压缩暂不接线（`compaction=None`）：它的记账端口 `CompactionJournal` 与引用索引一样
   没有持久化实现。不接线的后果是窗口退化为全量历史——这是安全方向（不丢内容），
   代价是上下文压力没有自动缓解。接线它属另一主题（需要一张记账表），本轮不做，
   已登记在册。这不会让运行失败：`compaction=None` 时运行编排跳过压缩分支。
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncEngine

from campfire.agent.model import ModelGateway
from campfire.agent.runtime import AgentRunner, build_sqlalchemy_session
from campfire.agent.runtime.resource_tool import build_read_skill_resource_tool
from campfire.agent.runtime.skill_tool import build_skill_tool
from campfire.agent.skill_runtime import SkillRegistry
from campfire.agent.tools import ToolPool
from campfire.core.config import Settings
from campfire.core.db import get_engine
from campfire.surfaces.consult.assembly import get_skill_registry, set_runner_factory
from campfire.surfaces.consult.citations import SqlCitationIndex
from campfire.surfaces.consult.registry import register_base_tools, register_product_tools

logger = logging.getLogger(__name__)

#: 进程内持有的模型网关。长生命周期：构造一次，按次取 `binding`，收尾时 `aclose()`。
#:
#: 为什么不缓存进 `Settings` 或模块级常量：它持有 HTTP 连接池，必须在事件循环存活期间
#: 构造与释放；缓存成不可变配置的一部分会让「什么时候关」失去所有者。
_gateway: ModelGateway | None = None


def build_tool_pool(skills: SkillRegistry) -> ToolPool:
    """构造完整的工具池：10 个产品工具 + `ask_user` + `skill` + `read_skill_resource`。

    两个保留名工具（`skill` / `read_skill_resource`）在这里注册而不在
    `registry.register_base_tools` 里：它们需要技能注册表，属运行装配的细节
    （`registry.py` 的 `register_base_tools` docstring 已写明这个分工）。
    """
    pool = ToolPool()
    register_product_tools(pool)
    register_base_tools(pool)
    # `skill`：存在 autoload skill 时装配期强制要求它，缺了直接抛 RuntimeAssemblyError。
    pool.register_base(build_skill_tool(skills))
    # `read_skill_resource`：缺了不拒绝启动，只让渐进披露退化为「资源读不到」。
    # 仍然注册它——项目的 4 个 skill 都带 references/，缺了就等于三层披露的第三层永远不可达。
    pool.register_base(build_read_skill_resource_tool(skills))
    return pool


def build_runner_factory(
    *,
    engine: AsyncEngine,
    gateway: ModelGateway,
) -> Callable[[Settings], AgentRunner]:
    """造一个「按配置造运行器」的工厂，供 `assembly.set_runner_factory` 注入。

    每次调用造一个新的 `AgentRunner`：它只持有引用（注入项、工具池、会话工厂），
    `__init__` 里没有 I/O。会话工厂按 `engine` 部分应用——引擎是进程级共享的
    （`core/db.get_engine`），不随请求新建连接池。
    """

    def factory(settings: Settings) -> AgentRunner:
        """按配置造一个运行器（工厂交给 `assembly` 持有）。"""
        skills = get_skill_registry(settings)
        return AgentRunner(
            binding=gateway.binding,
            tools=build_tool_pool(skills),
            skills=skills,
            citations=SqlCitationIndex(settings),
            sessions=functools.partial(build_sqlalchemy_session, engine=engine),
        )

    return factory


# quality-floor: ignore docstring-promise 异常由 ModelGateway/SkillRegistry/AgentRunner 构造期抛出并原样传播
def install(settings: Settings, *, gateway: ModelGateway | None = None) -> None:
    """装配生产运行器并把工厂注入 `assembly`（进程启动时调用一次）。

    `gateway` 是测试缝：不传时按配置构造真网关（生产路径）；传入时用它——
    端到端测试据此走完全相同的装配代码，只把外部模型供应商换掉。这与
    「测试里自己拼一个 `AgentRunner`」有本质区别：后者会让测试通过而生产路径仍旧
    缺失，那正是本次要修的缺陷形状（`set_runner_factory` 曾经只有测试调用点）。

    失败即抛：调用方（`lifespan`）决定「装配失败要不要让进程起不来」。当前的取舍是
    不让整个进程起不来——`/health`、档案面、记忆面、资料库面都不跑 Agent，
    它们照常可用；而咨询面据注入点是否就绪回 503（`assembly.runner_is_wired`），
    `/readyz` 也会如实报 `agent_assembly` 不可用（见 `main.py` 的 `check_agent_assembly`）。

    Raises:
        ModelConfigurationError: 未配置凭据或重试预算越界（`ModelGateway` 构造期）。
        ConsultAssemblyError: 技能内容根目录不可用。
        RuntimeAssemblyError: 工具池与 skill 的 `allowed-tools` 不一致。
        ToolRegistrationError: 工具重名或名字/描述不合规。
    """
    global _gateway

    if gateway is None:
        gateway = ModelGateway(settings)
    _gateway = gateway
    engine = get_engine(settings)
    set_runner_factory(build_runner_factory(engine=engine, gateway=gateway))
    skills = get_skill_registry(settings)
    logger.info(
        "咨询面运行器已装配：模型=%s，工具池=%d 项，skill=%d 个",
        gateway.model_name,
        len(build_tool_pool(skills).names()),
        len(skills.names()),
    )


def gateway_is_wired() -> bool:
    """模型网关是否已构造。排障用：区分「没接线」与「接线后运行失败」。"""
    return _gateway is not None


async def aclose() -> None:
    """释放模型网关的 HTTP 连接池（进程收尾时调用）。

    幂等：未装配时是空操作，重复调用不会二次关闭（`aclose` 后置 `None`）。
    """
    global _gateway
    if _gateway is not None:
        await _gateway.aclose()
        _gateway = None


def reset() -> None:
    """清除注入点与网关引用（测试夹具用；不关闭连接池）。

    生产路径不调用它。测试需要它是因为 `assembly` 的注入点是模块级全局：
    用例之间不清会互相看到对方的运行器，而「装配了但没装对」这类失败会被前一个
    用例的状态掩盖。
    """
    global _gateway
    _gateway = None
    set_runner_factory(None)


__all__ = [
    "aclose",
    "build_runner_factory",
    "build_tool_pool",
    "gateway_is_wired",
    "install",
    "reset",
]
