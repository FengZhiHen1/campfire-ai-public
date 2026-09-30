"""运行编排：一次运行的全部行为与失败语义。

职责：把零件装成一次运行（读历史 → 注入 → 渲染 → 窗口 → SDK → 翻译事件 → 结束）。
边界：六条刻意写清楚的边界与已知缺口见 :class:`AgentRunner`。
参考：docs/技术设计/technical-details/通用基座.md 第 2、3、4、5、7、9 节。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field

from agents import Agent, RunConfig, Runner
from agents.items import TResponseInputItem
from agents.memory.session import Session
from agents.result import RunResultStreaming
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent

from campfire.agent.context import (
    CitationIndex,
    CitationRecorder,
    CompactionJournal,
    CompactionOutcome,
    CompactionSettings,
    CompactionSummarizer,
    InjectionBatch,
    InjectionItem,
    InjectionMessage,
    InjectionPriority,
    InjectionRenderError,
    Item,
    compact,
    derive_window,
    is_context_overflow,
    message_text,
)
from campfire.agent.limits import AGENT_RUN_TIMEOUT_SECONDS
from campfire.agent.model import ModelBinding, ModelFailureReason, classify_model_failure
from campfire.agent.skill_runtime import Skill, SkillRegistry, render_activation
from campfire.agent.tools import ActivationState, ToolContext, ToolDispatcher, ToolPool, ToolScope, resolve_scope

from .ask_user_tool import ASK_USER_TOOL_NAME
from .assembly import QuestionGate, ToolBridge, WindowCallback, build_agent, build_run_config, stop_after_question
from .errors import RuntimeAssemblyError
from .events import (
    SUMMARY_LIMIT,
    CitationEvent,
    CompactionFacts,
    ProgressEvent,
    ReasoningDeltaEvent,
    RunEndReason,
    RunEvent,
    RunFailedEvent,
    RunFailureCode,
    RunFinishedEvent,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)
from .resource_tool import READ_SKILL_RESOURCE_TOOL_NAME
from .session import SessionFactory
from .skill_tool import SKILL_TOOL_NAME

logger = logging.getLogger("campfire.agent.runtime")

_CATALOG_PREFIX = "<available_skills>"
_ACTIVATION_PREFIX_TEMPLATE = '<skill_content name="{name}">'
_AVAILABILITY_PREFIX = "<tool_availability>"

SESSION_IO_DETAIL = "对话真源不可用（读取或写入会话失败）"
"""会话读写失败的说明。表名沿用设计里的「会话写入失败」：读写同属一类——对话真源不可用。"""


@dataclass(frozen=True, slots=True)
class RunRequest:
    """一次运行的输入：由面构造（见基座第 2 节「入口」行）。"""

    session_id: str
    """对话标识；与 SDK 会话一一对应。"""

    surface: str | None
    """当前面，用于按面收窄技能目录。"""

    instructions: str
    """静态系统提示（压缩策略第 8 节第 2 条）。"""

    injections: InjectionBatch = field(default_factory=InjectionBatch)
    """本轮的业务注入项（档案摘要、检索结果…）与取数失败的来源。"""

    activated: tuple[Skill, ...] = ()
    """程序注入的激活集合（例如应急卡片直接激活指定 skill）。"""

    default_active_tools: tuple[str, ...] = ()
    """未激活任何 skill 时面配置的默认可用工具集（一期只含只读类）。"""

    user_input: str | None = None
    """本轮使用者输入；纯注入（无用户消息）时可为 `None`。"""

    context_payload: object | None = None
    """透传给产品侧工具的领域事实；基座不解读。"""

    def __post_init__(self) -> None:
        """校验形状。

        Raises:
            RuntimeAssemblyError: 会话标识为空，或静态提示为空。
        """
        if not self.session_id.strip():
            raise RuntimeAssemblyError("RunRequest.session_id 不能为空（纯空白同样不能定位对话）")
        if not self.instructions.strip():
            raise RuntimeAssemblyError("RunRequest.instructions 不能为空：模型需要静态系统提示")


class CompactionWiring:
    """压缩的协作者与参数（装配处提供）。

    单独成包而不是四个平铺参数，是为了让「压缩要不要接线」在构造点一眼可见：不传它，
    运行编排就不做压缩（窗口退化为全量历史——安全方向，但压缩策略第 2 节的触发不存在）。
    """

    def __init__(
        self,
        *,
        settings: CompactionSettings,
        summarizer: CompactionSummarizer,
        journal: CompactionJournal,
        instruction: str,
        manual: bool = False,
    ) -> None:
        """绑定参数、摘要实现、记账端口与指令。

        `instruction` 的内容由产品侧拥有（压缩策略第 4 节的六节结构属领域约定）。
        `manual` 对应第 2 节的手动触发：仅供运维与调试，不暴露给使用者。
        """
        self.settings = settings
        self.summarizer = summarizer
        self.journal = journal
        self.instruction = instruction
        self.manual = manual


class _ContextOverflow(Exception):
    """提供方明确报了上下文溢出（内部信号，用于触发一次最大头部缩减后重试）。"""

    def __init__(self, detail: str, usage: RunUsage) -> None:
        """带上到溢出为止已经产生的用量：重试不能让那部分 token 从记录里消失。"""
        self.detail = detail
        self.usage = usage
        super().__init__(detail)


class AgentRunner:
    """把一次运行跑完，并只产出基座事件。

    依据第 2、3、4、5、7、9 节。这个模块把前面几步的零件装成一次运行，形状如下
    （text 代码块）：

        读历史 ──► 决定要追加哪些注入消息（目录/激活/可用性：与历史里最后一条同名消息不同才追加）
                ──► 渲染注入项（写引用索引）──► 派生本轮模型窗口 ──► 交给 SDK 流式运行
                ──► 把 SDK 事件翻译成基座事件 ──► 结束（含原因与引用清单）

    六条刻意写清楚的边界：

    1. 注入项就是消息，而且只加在末尾（压缩策略第 8 节第 1 条：只在末尾追加）。目录、
       激活内容、工具可用性都在「与历史里最后一条同名消息不同」时才追加——这条判断只依赖
       会话历史本身，因此不需要另存「窗口配方」或「上次注入集合」这类第二真相。
    2. 注入失败分两类，处置相反：取数失败由面用 `UnavailableSource` 表达，基座标注该
       来源不可用并继续（第 9 节）；而渲染或引用索引写入失败是持久化失败，基座以
       `injection_failed` 结束本次运行——索引里可能已有记录而窗口里没有，继续下去会让
       `run_finished` 报出模型从未看到的依据。
    3. 窗口只裁模型输入，不动落库：裁剪经 `RunConfig.session_input_callback` 表达，
       会话里仍是完整历史（第 2 节）。
    4. 上界只有 180 秒（第 2 节）：用每次拉取流事件的剩余预算实现，而不是给整个
       生成器套一层超时——后者的定时器会在生成器把事件交给消费方（例如慢速 SSE 客户端）时
       继续走，最后取消的是消费方的任务，那是错误的处置对象。触顶按第 9 节以
       `run_finished(reason="timeout")` 结束并保留已产生的引用。
    5. 取消不发事件：消费者取消自己的任务后收不到任何后续事件，发了也是空的。取消路径
       只做两件事——停掉 SDK 侧的运行、把 `CancelledError` 继续抛出去（第 9 节：
       运行被取消 → 立即停止调用）。
    6. 模型失败与内部失败分开报码：模型侧的异常（超时、限流、供应商错误、认证）归
       `model_unavailable` 并带上细分原因；其余归 `internal`。分类器在
       :mod:`campfire.agent.model`，判定顺序在那里有说明。

    为什么不调用 SDK 的压缩能力：

    第 2 节明确不使用 `OpenAIResponsesCompactionSession`：它会清空并重写历史，在单真源下
    等于改写用户可见的历史。上下文压力只由窗口与（尚未实现的）压缩机制处理。
    """

    def __init__(
        self,
        *,
        binding: ModelBinding,
        tools: ToolPool,
        skills: SkillRegistry,
        citations: CitationIndex,
        sessions: SessionFactory,
        timeout_seconds: float = AGENT_RUN_TIMEOUT_SECONDS,
        agent_name: str = "campfire",
        compaction: CompactionWiring | None = None,
    ) -> None:
        """绑定协作者。会话工厂与引用索引由装配处提供（基座不拥有连接池与表）。

        Raises:
            RuntimeAssemblyError: 配置自相矛盾——存在可按 `description` 自动匹配的 skill，
                但工具池里没有模型侧激活工具（`skill`），模型将无法激活任何 skill。
        """
        self._binding = binding
        self._tools = tools
        self._skills = skills
        self._citations = citations
        self._sessions = sessions
        self._timeout_seconds = timeout_seconds
        self._agent_name = agent_name
        self._compaction = compaction

        has_candidates = bool(skills.activation_candidates())
        has_activation_tool = SKILL_TOOL_NAME in tools.names()
        if has_candidates and not has_activation_tool:
            raise RuntimeAssemblyError(
                f"工具池缺少模型侧激活工具 {SKILL_TOOL_NAME}：存在可选 skill 时模型将无法激活它们。"
                "请在装配处用 build_skill_tool(skill_registry) 注册（ToolPool.register_base）"
            )
        # 激活工具、资源读取工具与提问工具都是机制本身，必须恒可用；不参与 allowed-tools
        # 的并集。资源工具未注册不构成装配错误：它的缺失只让渐进披露退化为「清单读不到」，
        # 而激活工具缺失会让模型侧激活整个失效——两者的严重度不同，只有后者值得拒绝启动。
        # 提问工具同理不拒绝启动：未注册时模型问不了使用者（能力缺失），而运行本身照常。
        always: list[str] = [SKILL_TOOL_NAME] if has_activation_tool else []
        if READ_SKILL_RESOURCE_TOOL_NAME in tools.names():
            always.append(READ_SKILL_RESOURCE_TOOL_NAME)
        if ASK_USER_TOOL_NAME in tools.names():
            always.append(ASK_USER_TOOL_NAME)
        self._always_active: tuple[str, ...] = tuple(always)

    def _resolve_scope(self, request: RunRequest) -> ToolScope:
        """按请求解析工具范围（唯一入口，避免两处各算一次而分叉）。"""
        return resolve_scope(
            self._tools,
            activated=request.activated,
            default_active=request.default_active_tools,
            always_active=self._always_active,
        )

    async def run(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """执行一次运行，逐个产出事件。

        生成器结束即运行结束；正常情况下最后一个事件是 `run_finished` 或 `run_failed`。
        消费者取消自己的任务时不会收到结束事件（取消以 `CancelledError` 表达）。
        """
        started = time.monotonic()
        run_id = uuid.uuid4().hex
        session = self._sessions(request.session_id)
        recorder = CitationRecorder(self._citations, run_id=run_id)

        try:
            history = await session.get_items()
        except Exception as exc:  # noqa: BLE001 —— 会话不可用必须以明确失败结束
            logger.warning("读取会话失败 run=%s error=%s", run_id, type(exc).__name__)
            yield _failure("session_write_failed", SESSION_IO_DETAIL, recorder, RunUsage(), started, None)
            return

        compactions: list[CompactionFacts] = []
        try:
            history, facts = await self._compact_before_run(session, history, request)
        except Exception as exc:  # noqa: BLE001 —— 压缩事务失败不是「压缩没发生」
            logger.warning("压缩事务失败 run=%s error=%s", run_id, type(exc).__name__)
            yield _compaction_failed(exc, recorder, RunUsage(), started)
            return
        if facts is not None:
            compactions.append(facts)

        try:
            scope = self._resolve_scope(request)
            batch = InjectionBatch(
                [*self._pending_injections(history, request, scope), *request.injections.items],
                request.injections.unavailable,
            )
            rendered = await batch.render(recorder)
        except InjectionRenderError as exc:
            # 索引里可能已有记录而窗口里没有：不得当作「没有注入」继续。
            logger.warning("注入渲染失败 run=%s error=%s", run_id, type(exc).__name__)
            yield _failure(
                "injection_failed",
                f"注入渲染失败（{type(exc).__name__}）",
                recorder,
                RunUsage(),
                started,
                None,
            )
            return
        except Exception as exc:  # noqa: BLE001 —— 注入侧的准备失败也是「本次运行明确失败」
            # 实测：技能目录超预算（`SkillCatalogOverflowError`）会从这里裸冒出去——0 次模型
            # 请求、没有 `run_failed`，调用方只能看到异常。注入侧的一切准备失败都归
            # `injection_failed`（基座第 4 节：注入是基座的职责，失败要说清是它）。
            logger.warning("注入准备失败 run=%s error=%s", run_id, type(exc).__name__)
            yield _failure(
                "injection_failed",
                f"注入准备失败（{type(exc).__name__}）",
                recorder,
                RunUsage(),
                started,
                None,
            )
            return

        new_items: list[TResponseInputItem] = [_as_input_item(message) for message in rendered]
        if request.user_input is not None:
            new_items.append({"role": "user", "content": request.user_input})

        yield RunStartedEvent(
            run_id=run_id,
            session_id=request.session_id,
            surface=request.surface,
            model=self._binding.name,
            activated_skills=tuple(skill.name for skill in request.activated),
            injection_sources=tuple(item.source for item in batch.ordered()),
            appended_messages=len(new_items),
        )
        for record in recorder.issued:
            yield CitationEvent(citation=record)
        if facts is not None and facts.performed:
            # 放在 run_started 之后：事件流以 run_started 为首项是第 7 节的形状约定，
            # 压缩提示不该抢在它前面（实测第一版就是 ProgressEvent 排第一）。
            yield ProgressEvent(message="上下文压力偏高，已压缩较早的历史。")

        buffer: list[RunEvent] = []
        # 运行时激活状态：初始 = 请求携带的激活 skill 名；模型侧激活（skill 工具）在运行中
        # 并入（连同它的 allowed-tools）。dispatcher 读工具名并集，ToolContext 读 skill 名。
        activation_state = ActivationState()
        activation_state.seed(scope.activated_skills)
        dispatcher = ToolDispatcher(
            self._tools,
            scope,
            context=ToolContext(
                run_id=run_id,
                session_id=request.session_id,
                surface=request.surface,
                activation_state=activation_state,
                citations=recorder,
                payload=request.context_payload,
            ),
            activation_state=activation_state,
        )
        # 提问闸门按运行创建：它记的是「本次运行问出问题了没有」，跨运行共享会让上一次的
        # 提问把下一次的运行提前结束。桥与 agent 共用同一个闸门，因此
        # 「发出 question 事件」与「运行结束在提问处」由同一件事触发，不会只有其一发生。
        gate = QuestionGate()
        bridge = ToolBridge(dispatcher, sink=buffer.append, gate=gate)
        agent = build_agent(
            name=self._agent_name,
            instructions=request.instructions,
            model=self._binding.model,
            tools=bridge.function_tools(),
            tool_use_behavior=stop_after_question(gate),
        )
        run_config = build_run_config(binding=self._binding, window=_window_callback())

        async for event in self._execute(
            session=session,
            agent=agent,
            run_config=run_config,
            new_items=new_items,
            history=history,
            request=request,
            recorder=recorder,
            buffer=buffer,
            started=started,
            compactions=compactions,
        ):
            yield event

    async def _execute(
        self,
        *,
        session: Session,
        agent: Agent,
        run_config: RunConfig,
        new_items: list[TResponseInputItem],
        history: list[TResponseInputItem],
        request: RunRequest,
        recorder: CitationRecorder,
        buffer: list[RunEvent],
        started: float,
        compactions: list[CompactionFacts],
    ) -> AsyncIterator[RunEvent]:
        """跑 SDK 并按第 7 节处理上下文溢出恢复，直到结束或明确失败。

        单独成方法有两个理由：一是让 :meth:`run` 只剩「准备 → 交付」两步；二是溢出恢复需要
        「重跑整次 SDK 调用」，那是一个循环，混在准备逻辑里会让人看不出这个循环的边界。

        已知代价（写清楚，不藏）：重试会把本轮新增项（注入 + 使用者消息）再交给 SDK 一次；
        若首次尝试已经把这批项部分落库，会话里可能出现重复消息。要彻底消除需要会话事务，
        而会话级重写是压缩策略第 10 节明确一期不做的范围。溢出是一期几乎不会走的路径
        （阈值约 80 万 token），因此接受这个代价并在此标注。

        已知缺口（登记于 docs/TODO.md）：

        - 基座不做工具级重试：第 9 节写「工具失败 → 作为结果回给模型；重试耗尽则以明确失败
          结束本次运行」，但一期没有任何工具级重试策略——重试的循环是模型自己（它会看到
          `tool_failed` 再决定要不要换个参数重试）。真的反复失败会一直走到 180 秒上限，
          以 `timeout` 结束。接入真实工具后再评估是否要加重试策略。
        - 会话写入失败靠异常检出：SDK 会 `await` 会话写入，写入抛错即本次运行失败；但一个
          「不抛错也不写」的会话实现不会被发现。这条已登记为待验证事实（TECH-16）。
        """
        overflow_attempts = 0
        # 跨尝试累加的用量：第一次尝试的 token 不能因为溢出重试就消失。
        # 基座第 8 节要记 token。
        carried = RunUsage()
        while True:
            # max_turns=None：基座第 2 节不设步数上限。
            # SDK 默认的 10 轮就是一条步数上限。
            result = Runner.run_streamed(
                agent,
                input=new_items,
                session=session,
                max_turns=None,
                run_config=run_config,
            )
            try:
                async for event in self._stream(
                    result=result,
                    recorder=recorder,
                    buffer=buffer,
                    started=started,
                    compactions=tuple(compactions),
                    carried=carried,
                ):
                    yield event
                return
            except _ContextOverflow as overflow:
                carried = carried + overflow.usage
                wiring = self._compaction
                if wiring is None or overflow_attempts >= wiring.settings.max_overflow_retries:
                    yield _failure(
                        "context_overflow",
                        overflow.detail,
                        recorder,
                        carried,
                        started,
                        None,
                        compactions=tuple(compactions),
                    )
                    return

                overflow_attempts += 1
                try:
                    history, facts = await self._compact_before_run(
                        session, history, request, force_max_reduction=True
                    )
                except Exception as exc:  # noqa: BLE001 —— 压缩事务失败不是「压缩没发生」
                    logger.warning("压缩事务失败 run=%s error=%s", recorder.run_id, type(exc).__name__)
                    yield _compaction_failed(exc, recorder, carried, started, compactions=tuple(compactions))
                    return
                if facts is not None:
                    compactions.append(facts)
                if facts is None or not facts.performed:
                    # 第 7 节：只有在替换确实推进了之后才重试；推不动就明确失败并提示，
                    # 不静默截断（不可分单元超预算的情形）。
                    reason = facts.detail if facts is not None else "压缩未接线"
                    yield _failure(
                        "context_overflow",
                        f"{overflow.detail}；最大头部缩减未能降低窗口（{reason}）",
                        recorder,
                        carried,
                        started,
                        None,
                        compactions=tuple(compactions),
                    )
                    return
                yield ProgressEvent(message="提供方报了上下文溢出，已做最大头部缩减，重试本次运行。")

    async def _compact_before_run(
        self,
        session: Session,
        history: list[TResponseInputItem],
        request: RunRequest,
        *,
        force_max_reduction: bool = False,
    ) -> tuple[list[TResponseInputItem], CompactionFacts | None]:
        """运行前压缩。这里不问结果——可降级的失败在 `compact` 内部已经变成降级事实。

        这里**不再兜住异常**。`compact` 只把两类失败转成 `CompactionOutcome`（摘要失败 →
        `summary_failed`、会话追加写失败 → `commit_failed`），因此能逃出 `compact` 的异常
        只剩压缩事务的记账失败与程序错误，两者都该让本次运行明确失败。记账失败按端口契约
        原样冒泡（见 `compaction.py` 的 `CompactionJournal` 与 `compact` 的 Raises：记账失败
        不得被当成「压缩没发生」）。

        为什么记账失败必须让运行失败，而不是降级成一次未压缩的运行：`_attempt` 的顺序是
        「落库 → 记结束」，`record_finished` 失败时检查点已经写进会话、SDK 侧窗口也按新检查点
        派生——此时「窗口未改动」与真源相反；而运行记录是审计依据，记不上账的运行不该以
        `run_finished` 收场。代价是账本不可用时整次运行失败，接受它：端口说明要求实现自带
        超时上界，因此失败不会挂住运行，契约要的正是把这种不一致暴露出来。

        与基座第 9 节「会话写入失败 → 本次运行明确失败」的关系：那一条针对对话本身没落库
        （SDK 的会话写入异常照旧转成 `session_write_failed`）；压缩的追加写失败仍按
        `commit_failed` 降级处理，两者不冲突。
        """
        return await self._compact_if_needed(session, history, request, force_max_reduction=force_max_reduction)

    async def _compact_if_needed(
        self,
        session: Session,
        history: list[TResponseInputItem],
        request: RunRequest,
        *,
        force_max_reduction: bool = False,
    ) -> tuple[list[TResponseInputItem], CompactionFacts | None]:
        """按需压缩；追加内容由机制通过 `commit` 端口在本事务内写回会话。

        压缩发生在派生窗口之前（压缩策略第 2 节的触发时机）。落库交给机制而不是这里，
        是为了让「记结束」排在落库之后（第 7 节：不留假装压缩完成的结束记录）。
        """
        wiring = self._compaction
        if wiring is None:
            return history, None

        async def commit(appended: Sequence[Item]) -> None:
            """把检查点 + 尾部原文写回会话（写不进去就抛，由机制记成 commit_failed）。"""
            await session.add_items(_as_items(appended))

        updated, outcome = await compact(
            history_from(history),
            settings=wiring.settings,
            summarizer=wiring.summarizer,
            instruction=wiring.instruction,
            journal=wiring.journal,
            system_prompt=request.instructions,
            commit=commit,
            manual=wiring.manual,
            force_max_reduction=force_max_reduction,
        )
        facts = compaction_facts(outcome)
        if outcome.reason in ("below_threshold", "auto_disabled"):
            # 触发条件没到：这不构成一次「压缩」，不该进记录（否则每一次运行都会留下一条
            # below_threshold，`compactions` 的长度就不再表示「压缩发生过几次」）。
            return history, None
        if not outcome.performed:
            # 触发条件到了却没能压缩：这是需要被看见的降级，不能静默。
            logger.warning(
                "压缩未执行 session=%s reason=%s detail=%s",
                request.session_id,
                outcome.reason,
                outcome.detail,
            )
            return history, facts
        appended = _as_items(updated[len(history) :])
        return [*history, *appended], facts

    async def _stream(
        self,
        *,
        result: RunResultStreaming,
        recorder: CitationRecorder,
        buffer: list[RunEvent],
        started: float,
        compactions: tuple[CompactionFacts, ...] = (),
        carried: RunUsage | None = None,
    ) -> AsyncIterator[RunEvent]:
        """消费 SDK 的事件流，翻译成基座事件，直到结束、触顶或失败。

        与 :meth:`run` 分开是为了让「准备」和「流式消费」各自可读：前者是装配与注入，
        后者是事件循环与失败处置，混在一个函数里既难读也难改。

        `carried` 是上一次尝试（溢出重试前）已产生的用量，最终用量是两者之和。

        Raises:
            asyncio.CancelledError: 消费者取消时原样抛出（第 9 节：立即停止调用）；
                此时不产出结束事件，因为取消自己的消费者收不到任何后续事件。
            _ContextOverflow: 提供方明确报上下文溢出——交给 :meth:`run` 做一次最大头部缩减后
                重试（压缩策略第 7 节），因此不在这里变成 `run_failed`。
        """
        run_id = recorder.run_id
        usage = carried if carried is not None else RunUsage()
        budget = _Budget(deadline=started + self._timeout_seconds)
        tracker = _ToolCallTracker()

        try:
            async for event in _drain(result, budget):
                # 交付给消费方的耗时不算运行预算：慢速 SSE 客户端挂起时，模型与工具并没有在跑
                # （本函数 docstring 的承诺）。第一版把这段算进去，实测一个 0 次模型调用的运行
                # 也会被判成 timeout 并丢弃已产出的文本。
                handed_off = time.monotonic()
                if isinstance(event, _SdkEvent):
                    mapped, delta = _translate(event.value)
                    usage = usage + delta
                    for item in mapped:
                        tracker.note_started(item)
                        yield item
                else:  # _TimedOut
                    _cancel_quietly(result, run_id)
                    for item in self._finalize(
                        tracker=tracker,
                        buffer=buffer,
                        recorder=recorder,
                        usage=usage,
                        started=started,
                        compactions=compactions,
                        reason="timeout",
                        interrupted="运行触顶，工具调用被中断",
                    ):
                        yield item
                    return

                for item in tracker.flush(buffer):
                    yield item

                orphan = tracker.orphan_finish(event.value) if isinstance(event, _SdkEvent) else None
                if orphan is not None:
                    yield orphan
                # 把「交付给消费方」的挂起时间还给预算：慢客户端不该把运行逼成 timeout。
                budget.credit(time.monotonic() - handed_off)
        except asyncio.CancelledError:
            _cancel_quietly(result, run_id)
            raise
        except _ContextOverflow:
            _cancel_quietly(result, run_id)
            raise
        except Exception as exc:  # noqa: BLE001 —— 任何未归类异常都要变成带码的失败
            if is_context_overflow(exc):
                # 溢出恢复的入口：先停掉这次运行，再交给 run() 决定能否压缩后重试。
                _cancel_quietly(result, run_id)
                raise _ContextOverflow(f"提供方报了上下文溢出（{type(exc).__name__}）", usage) from exc
            logger.warning("运行失败 run=%s error=%s", run_id, type(exc).__name__)
            for item in tracker.flush(buffer):
                yield item
            for finish in tracker.interrupted_finishes(reason="运行失败，工具调用被中断"):
                yield finish
            yield _failed_from_exception(exc, recorder, usage, started, compactions=compactions)
            return
        finally:
            # 消费者放弃这个流（`aclose()` / `break` + GC）时也要停掉 SDK 侧的运行：
            # 否则它会继续调模型、继续写会话（实测 aclose 后 1.2 秒又发了一次请求、
            # 会话从 2 条涨到 5 条）。第 9 节：取消要立即停止调用。
            if not getattr(result, "is_complete", False):
                _cancel_quietly(result, run_id)

        for item in self._finalize(
            tracker=tracker,
            buffer=buffer,
            recorder=recorder,
            usage=usage,
            started=started,
            compactions=compactions,
            reason="completed",
            interrupted="运行结束，工具调用没有结果",
        ):
            yield item

    def _finalize(
        self,
        *,
        tracker: _ToolCallTracker,
        buffer: list[RunEvent],
        recorder: CitationRecorder,
        usage: RunUsage,
        started: float,
        compactions: tuple[CompactionFacts, ...],
        reason: RunEndReason,
        interrupted: str,
    ) -> Iterator[RunEvent]:
        """正常收尾：交出缓冲的事件 → 给被打断的调用补结束事件 → 产终态事件。

        单独成方法是为了让 :meth:`_stream` 的三条出口（触顶、完成、失败）各自一眼可读——
        并且让「触顶」与「完成」走同一段收尾代码，避免两条路径慢慢分叉。
        """
        yield from tracker.flush(buffer)
        yield from tracker.interrupted_finishes(reason=interrupted)
        yield RunFinishedEvent(
            reason=reason,
            citations=recorder.issued,
            usage=usage,
            elapsed_seconds=time.monotonic() - started,
            compactions=compactions,
        )

    def _pending_injections(
        self,
        history: Sequence[object],
        request: RunRequest,
        scope: ToolScope,
    ) -> list[InjectionItem]:
        """决定本轮要追加哪些基座自己生成的注入消息。

        只追加「与历史里最后一条同名消息不同」的那些（压缩策略第 8 节第 1 条：只在末尾追加，
        不原地替换）。判断完全由会话历史推导，不依赖进程内记忆。

        判据只看窗口，不看整段历史：压缩之后，目录/可用性/激活内容都可能落在被摘要覆盖的
        那一段里——那里已经不进窗口了。若继续按整段历史判断，模型会在压缩后丢掉技能目录，
        而基座还以为「已经注入过」。
        """
        window = derive_window(history)
        pending: list[InjectionItem] = []

        if self._skills.activation_candidates():  # 没有任何可选 skill 时，空目录是噪音
            catalog = self._skills.catalog(surface=request.surface)
            if _last_content(window, _CATALOG_PREFIX) != catalog:
                pending.append(
                    InjectionItem(
                        source="skill-catalog",
                        content=catalog,
                        priority=InjectionPriority.SKILL_CATALOG,
                    )
                )

        for skill in request.activated:
            payload = render_activation(skill)
            prefix = _ACTIVATION_PREFIX_TEMPLATE.format(name=skill.name)
            if _last_content(window, prefix) != payload:
                pending.append(
                    InjectionItem(
                        source=f"skill-activation:{skill.name}",
                        content=payload,
                        priority=InjectionPriority.SKILL_ACTIVATION,
                    )
                )

        if scope.declared:  # 没有任何已声明工具时，可用性告知是噪音
            availability = scope.availability_item()
            if _last_content(window, _AVAILABILITY_PREFIX) != availability.content:
                pending.append(availability)

        return pending


# --- SDK 事件翻译 -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SdkEvent:
    """包一层，避免把 SDK 的事件类型与 `_TimedOut` 混在一起判断。"""

    value: object


@dataclass(frozen=True, slots=True)
class _TimedOut:
    """到达时间上限。"""


@dataclass(slots=True)
class _Budget:
    """运行预算：模型与工具侧耗时的上限。

    刻意做成可变对象而不是传一个 float：交付事件给消费方的挂起时间要从预算里还回来
    （第 2 节的上限针对的是模型与工具，不是慢速 SSE 客户端）。传 float 的话 `_drain`
    拿到的是当时那个值，还回来的时间它看不见。
    """

    deadline: float

    def remaining(self) -> float:
        """剩余预算（秒）；可能为负。"""
        return self.deadline - time.monotonic()

    def credit(self, seconds: float) -> None:
        """把交付给消费方花掉的时间还回预算。"""
        if seconds > 0:
            self.deadline += seconds


async def _drain(result: RunResultStreaming, budget: _Budget) -> AsyncIterator[_SdkEvent | _TimedOut]:
    """按剩余预算逐次拉取 SDK 事件。

    每次拉取单独设超时，而不是把整个循环套进一个超时上下文：生成器把事件交给消费方时可能
    长时间挂起（慢速 SSE 客户端），那不是模型或工具在耗时，不该计入运行预算，更不该因此
    取消消费方的任务。
    """
    stream = result.stream_events()
    while True:
        remaining = budget.remaining()
        if remaining <= 0:
            yield _TimedOut()
            return
        try:
            event = await asyncio.wait_for(anext(stream), timeout=remaining)
        except StopAsyncIteration:
            return
        except TimeoutError:
            yield _TimedOut()
            return
        yield _SdkEvent(event)


def _translate(event: object) -> tuple[list[RunEvent], RunUsage]:
    """把一个 SDK 事件翻译成零个或多个基座事件（外加可能的用量增量）。

    思考增量的两条来路（基座 7.1 节的「待验证」项，实测结论写在这里）：

    `chatcmpl_converter` 把 Chat Completions 的思考字段捕获成 `ReasoningItem`，流式阶段
    经 `chatcmpl_stream_handler` 发出两种原始事件——`reasoning_content` 走
    `response.reasoning_summary_text.delta`（SDK 视为「思考摘要」），第三方平台的
    `reasoning` 字段走 `response.reasoning_text.delta`（SDK 视为「思考正文」）。两条都携带
    增量文本，因此都在这里翻译成 `reasoning_delta`。

    仍保留「取不到就不产出」这条兜底：任何别的 `raw.type`（含 SDK 未来改名或本提供方
    不返回思考字段的情形）都返回空列表。绝不用 `response.output_text.delta`（正文增量）
    冒充思考增量——基座 7.1 节明确禁止，思考区是「中间态、非结论」，混入正文会让使用者
    把推理过程当成正式回答。这条兜底有单测钉住（`test_agent_runtime` 的思考增量用例），
    构造方式是让提供方只返回正文而不返回任何思考字段。
    """
    if isinstance(event, RawResponsesStreamEvent):
        raw = event.data
        kind = getattr(raw, "type", "")
        if kind == "response.output_text.delta":
            delta = getattr(raw, "delta", "")
            return ([TextDeltaEvent(delta=str(delta))] if delta else []), RunUsage()
        if kind in _REASONING_DELTA_KINDS:
            delta = getattr(raw, "delta", "")
            return ([ReasoningDeltaEvent(delta=str(delta))] if delta else []), RunUsage()
        if kind == "response.completed":
            return [], _usage_of(raw)
        return [], RunUsage()

    if isinstance(event, RunItemStreamEvent) and event.name == "tool_called":
        name, call_id = _tool_call_identity(event.item)
        return [ToolCallStartedEvent(tool_name=name, call_id=call_id)], RunUsage()

    return [], RunUsage()


_REASONING_DELTA_KINDS = frozenset(
    {
        # DeepSeek 的 `reasoning_content`：SDK 捕获为思考摘要（ReasoningItem.summary）。
        # 实测 SDK 0.22.3 + chatcmpl_stream_handler。
        "response.reasoning_summary_text.delta",
        # 第三方平台的 `reasoning` 字段：SDK 捕获为思考正文（ReasoningItem.content）。
        "response.reasoning_text.delta",
    }
)
"""承载思考增量的原始事件类型。

两种都收，是因为它们对应提供方两个不同的思考字段（`reasoning_content` 与 `reasoning`），
而对使用者来说都是「模型的思考过程」——只收一种会让另一种提供方的思考区永远空白。
增量的正文语义（摘要还是正文）不影响本事件的形状：基座 7.1 节只有一个 `delta` 字段。
"""


def _tool_call_identity(item: object) -> tuple[str, str]:
    """取工具调用的名字与调用标识；SDK 可能给对象也可能给映射。"""
    raw = getattr(item, "raw_item", None)
    if isinstance(raw, dict):
        return str(raw.get("name", "")), str(raw.get("call_id", ""))
    return str(getattr(raw, "name", "")), str(getattr(raw, "call_id", ""))


def _usage_of(raw: object) -> RunUsage:
    """从 `response.completed` 事件里取提供方返回的用量（不折算字符）。"""
    usage = getattr(getattr(raw, "response", None), "usage", None)
    if usage is None:
        return RunUsage(requests=1)
    return RunUsage(
        requests=1,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


class _ToolCallTracker:
    """跟踪工具调用的开始与结束，保证事件成对。

    单独成类是因为它是一份跨事件的状态：`tool_call_started` 来自 SDK 的事件流，
    `tool_call_finished` 来自工具桥的缓冲；两者要在运行编排里对齐，而模型编出不存在的
    工具名时 SDK 会自己处置那次调用（不经过基座的权限门），需要补一条失败结束事件。
    """

    def __init__(self) -> None:
        """初始状态：没有进行中的调用，也没有已结束的调用。"""
        self._pending: dict[str, str] = {}
        self._finished: set[str] = set()

    def note_started(self, event: RunEvent) -> None:
        """记下一次已发出的工具调用开始。"""
        if isinstance(event, ToolCallStartedEvent):
            self._pending[event.call_id] = event.tool_name

    def flush(self, buffer: list[RunEvent]) -> Iterator[RunEvent]:
        """交出工具桥缓冲的事件，并记下哪些调用已经结束。"""
        while buffer:
            item = buffer.pop(0)
            if isinstance(item, ToolCallFinishedEvent):
                self._finished.add(item.call_id)
                self._pending.pop(item.call_id, None)
            yield item

    def orphan_finish(self, event: object) -> ToolCallFinishedEvent | None:
        """为「SDK 自己处置、没经过基座权限门」的调用补一条失败结束事件。

        目前唯一的来路是模型编出不存在的工具名：`RunConfig.tool_not_found_behavior`
        设成 `return_error_to_model`，SDK 直接把错误交回模型继续跑。若不补，面会看到
        一次只有开始没有结束的调用。
        """
        call_id = _tool_output_call_id(event)
        if call_id is None or call_id not in self._pending or call_id in self._finished:
            return None
        self._finished.add(call_id)
        output = getattr(getattr(event, "item", None), "output", "")
        return ToolCallFinishedEvent(
            tool_name=self._pending.pop(call_id),
            call_id=call_id,
            ok=False,
            # 错误码与基座自己的 tool_not_registered 对齐。
            # 面看到的词汇只有一套。
            error_code="tool_not_registered",
            summary=str(output)[:SUMMARY_LIMIT],
        )

    def interrupted_finishes(self, *, reason: str) -> Iterator[ToolCallFinishedEvent]:
        """为所有「已开始但永远不会结束」的调用补结束事件。

        为什么必须有：SDK 在执行工具之前就发出 `tool_called`，因此工具执行到一半触顶时
        事件序列是 `run_started → tool_call_started → run_finished`（实测）。不补的话面会看到
        一个永远转圈的工具指示器，而「事件成对」是第 7 节的形状要求（本类 docstring 也这么承诺）。
        合成事件带 `ok=False` 与 `tool_interrupted`，让消费方能一眼看出是中断而非失败。
        """
        for call_id, tool_name in list(self._pending.items()):
            self._finished.add(call_id)
            self._pending.pop(call_id, None)
            yield ToolCallFinishedEvent(
                tool_name=tool_name,
                call_id=call_id,
                ok=False,
                error_code="tool_interrupted",
                summary=reason[:SUMMARY_LIMIT],
            )


def _tool_output_call_id(event: object) -> str | None:
    """取 `tool_output` 事件对应的调用标识；不是这类事件时返回 `None`。"""
    if not isinstance(event, RunItemStreamEvent) or event.name != "tool_output":
        return None
    raw = getattr(event.item, "raw_item", None)
    call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
    return str(call_id) if call_id else None


# --- 小工具 -----------------------------------------------------------------


def _window_callback() -> WindowCallback:
    """构造 `session_input_callback`：窗口 = 由会话历史派生的裁剪 + 本轮新增项。"""

    def window(history: list[TResponseInputItem], new_items: list[TResponseInputItem]) -> list[TResponseInputItem]:
        """把 SDK 给的历史与本轮新增项按窗口策略合成模型输入。"""
        return derive_window(history, appended=new_items)

    return window


def history_from(items: Sequence[TResponseInputItem]) -> list[Item]:
    """把 SDK 的输入项交给压缩机制。

    运行时两者都是普通 dict；这里显式转一次，是因为 `TypedDict` 在静态类型上并不是
    `Mapping[str, object]` 的子类型——用一个明确的转换代替类型逃逸。
    """
    return [dict(item) for item in items]


def _as_items(items: Sequence[Item]) -> list[TResponseInputItem]:
    """把基座项形状交回 SDK（写入会话时用）。

    `Item` 是 `Mapping[str, object]`，SDK 的输入项是 TypedDict 联合——静态类型看不穿
    这层「运行时形状一致」，故此处豁免（实测错误码是 `misc`，不是 `list-item`）。
    """
    return [dict(item) for item in items]  # type: ignore[misc]  # 运行时形状一致，TypedDict 无法从 Mapping 静态推导


def compaction_facts(outcome: CompactionOutcome) -> CompactionFacts:
    """把压缩结果压成事件里的计量（不带摘要正文，见 :class:`CompactionFacts`）。"""
    summary = outcome.summary
    return CompactionFacts(
        performed=outcome.performed,
        window_tokens_before=outcome.window_tokens_before,
        window_tokens_after=outcome.window_tokens_after,
        released_tokens=outcome.released_tokens,
        compacted_items=outcome.compacted_items,
        retained_items=outcome.retained_items,
        attempts=outcome.attempts,
        failed_attempts=outcome.failed_attempts,
        previous_summary_merged=outcome.previous_summary_merged,
        summary_input_tokens=summary.input_tokens if summary is not None else 0,
        summary_output_tokens=summary.output_tokens if summary is not None else 0,
        summary_elapsed_seconds=outcome.summary_elapsed_seconds,
        prompt_cache_hit_tokens=summary.prompt_cache_hit_tokens if summary is not None else 0,
        prompt_cache_miss_tokens=summary.prompt_cache_miss_tokens if summary is not None else 0,
        reason=outcome.reason,
        detail=outcome.detail,
    )


def _as_input_item(message: InjectionMessage) -> TResponseInputItem:
    """把注入消息转成 SDK 的输入项（形状一致，只是补齐 SDK 的联合类型）。"""
    if message["role"] == "assistant":
        return {"role": "assistant", "content": message["content"]}
    return {"role": "user", "content": message["content"]}


def _last_content(history: Sequence[object], prefix: str) -> str | None:
    """取历史里最后一条以 `prefix` 开头的消息内容；没有返回 `None`。

    靠内容而不是靠位置：SDK 未把 `limit=None` 的读回顺序写成硬保证（基座文档「已知偏差」）。
    """
    found: str | None = None
    for item in history:
        content = message_text(item)
        if content is not None and content.lstrip().startswith(prefix):
            found = content
    return found


def _cancel_quietly(result: RunResultStreaming, run_id: str) -> None:
    """停掉 SDK 侧的运行；取消失败只记日志，不得掩盖触顶/取消本身的原因。"""
    try:
        result.cancel()
    except Exception as exc:  # noqa: BLE001 —— 见 docstring
        logger.warning("取消运行结果失败 run=%s error=%s", run_id, type(exc).__name__)


def _failed_from_exception(
    error: BaseException,
    recorder: CitationRecorder,
    usage: RunUsage,
    started: float,
    *,
    compactions: tuple[CompactionFacts, ...] = (),
) -> RunFailedEvent:
    """把一次未捕获的异常变成 `run_failed`：模型侧问题与内部问题分开报码。"""
    reason = classify_model_failure(error)
    if reason == "unknown":
        return _failure(
            "internal",
            f"运行内部错误（{type(error).__name__}）",
            recorder,
            usage,
            started,
            None,
            compactions=compactions,
        )
    return _failure(
        "model_unavailable",
        f"模型调用失败（{type(error).__name__}）",
        recorder,
        usage,
        started,
        error,
        compactions=compactions,
    )


def _compaction_failed(
    error: BaseException,
    recorder: CitationRecorder,
    usage: RunUsage,
    started: float,
    *,
    compactions: tuple[CompactionFacts, ...] = (),
) -> RunFailedEvent:
    """把压缩事务的异常变成 `run_failed`（端口契约：记账失败不得被当成「压缩没发生」）。

    用 `internal` 而不新增失败码：`RunFailureCode` 与 `apps/web` 的 TS 联合类型是同一份对外
    契约，加一个码会造出只有后端认识的值；`internal` 已覆盖「其余未归类内部错误」。失败码
    分不出记账与其它内部错误，说明文字与 warning 日志补上——detail 不写「窗口未改动」，
    因为 `record_finished` 失败时检查点已经落库，真源变了。
    """
    return _failure(
        "internal",
        f"压缩事务失败（{type(error).__name__}）：记账未闭合或压缩准备出错，运行记录与对话真源可能不一致",
        recorder,
        usage,
        started,
        None,
        compactions=compactions,
    )


def _failure(
    code: RunFailureCode,
    detail: str,
    recorder: CitationRecorder,
    usage: RunUsage,
    started: float,
    cause: BaseException | None,
    *,
    compactions: tuple[CompactionFacts, ...] = (),
) -> RunFailedEvent:
    """造一个 `run_failed` 事件；模型失败额外带上细分原因。"""
    reason: ModelFailureReason | None = None
    if code == "model_unavailable" and cause is not None:
        reason = classify_model_failure(cause)
    return RunFailedEvent(
        code=code,
        detail=detail,
        citations=recorder.issued,
        usage=usage,
        elapsed_seconds=time.monotonic() - started,
        model_reason=reason,
        compactions=compactions,
    )


__all__ = ["SESSION_IO_DETAIL", "AgentRunner", "RunRequest"]
