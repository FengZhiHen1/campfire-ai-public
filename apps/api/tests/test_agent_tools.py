"""工具池与权限门：注册契约、参数边界、越界拒绝与失败语义。

对应 docs/技术设计/technical-details/通用基座.md 第 5 节与第 11 节的验证方式，以及
docs/技术设计/technical-details/技能设计.md 第 5 节「断言应急激活时写工具被服务端拒绝」。
重点在拒绝路径：权限拒绝必须返回明确错误码，且**实现根本没有被调用**。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from campfire.agent.context import CitationRecord, CitationRecorder, InjectionPriority
from campfire.agent.skill_runtime import Skill, SkillMetadata
from campfire.agent.tools import (
    AVAILABILITY_SOURCE,
    ActivationState,
    RiskLevel,
    ToolContext,
    ToolDispatcher,
    ToolFailure,
    ToolNotRegisteredError,
    ToolPool,
    ToolRegistrationError,
    ToolResult,
    ToolSpec,
    ToolSpecError,
    resolve_scope,
)

FIXED_TIME = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class FakeCitationIndex:
    """引用索引替身；本组用例只关心工具能否产出引用。"""

    def __init__(self) -> None:
        self.records: list[CitationRecord] = []

    async def add(self, record: CitationRecord) -> None:
        self.records.append(record)

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return [record for record in self.records if record.run_id == run_id]


class ReadArgs(BaseModel):
    """读类工具的参数。"""

    query: str
    limit: int = 5


class EmptyArgs(BaseModel):
    """无参工具的参数。"""


def _context(index: FakeCitationIndex | None = None) -> ToolContext:
    """构造一个绑定了运行事实与引用写入端的上下文。"""
    activation = ActivationState()
    activation.seed({"emergency"})
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=activation,
        citations=CitationRecorder(
            index or FakeCitationIndex(),
            run_id="run-1",
            clock=lambda: FIXED_TIME,
            id_factory=lambda: "cite-1",
        ),
    )


def _calls_recorder(calls: list[str], name: str) -> None:
    """把一次实现调用记进列表，用于断言「权限拒绝时实现没被调用」。"""
    calls.append(name)


def _spec(
    name: str = "read_alpha",
    *,
    description: str = "读一个东西",
    risk: RiskLevel = "low",
    requires_approval: bool = False,
    calls: list[str] | None = None,
) -> ToolSpec[ReadArgs]:
    """造一个读类工具；``calls`` 非空时记录实现被调用的次数。"""

    async def handler(_context: ToolContext, args: ReadArgs) -> ToolResult:
        if calls is not None:
            calls.append(name)
        return ToolResult(text=f"{args.query}:{args.limit}")

    return ToolSpec(
        name=name,
        description=description,
        args_model=ReadArgs,
        handler=handler,
        risk=risk,
        requires_approval=requires_approval,
    )


def _skill(name: str, allowed_tools: tuple[str, ...]) -> Skill:
    """造一个已加载形状的 skill（不起文件系统）。"""
    return Skill(
        metadata=SkillMetadata(
            name=name,
            description=f"{name} 的描述",
            license=None,
            compatibility=None,
            metadata={},
            allowed_tools=frozenset(allowed_tools),
        ),
        body="正文",
        directory=Path("."),
    )


# --- 注册形状 ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["Read_alpha", "read-alpha", "1read", "read alpha", ""])
def test_tool_name_shape_is_enforced(name: str) -> None:
    with pytest.raises(ToolSpecError, match="不合法"):
        _spec(name=name)


def test_tool_description_is_required() -> None:
    with pytest.raises(ToolSpecError, match="描述"):
        _spec(description="   ")


def test_open_object_parameters_are_rejected_at_registration() -> None:
    """参数 schema 含开放对象时，**注册期**就要失败（SDK 的严格模式不接受它）。

    实测：``ensure_strict_json_schema`` 由 SDK 在构造工具时调用，而那一刻运行已经发出
    ``run_started``——参数模型含 ``dict[str, X]`` 或 ``extra="allow"`` 时抛裸 ``UserError``，
    事件流只到 ``run_started`` 就断，调用方拿不到任何 ``run_failed``。
    """

    class OpenArgs(BaseModel):
        table: dict[str, int]

    async def handler(_context: object, _args: OpenArgs) -> ToolResult:
        return ToolResult(text="ok")

    with pytest.raises(ToolSpecError, match="严格模式"):
        ToolSpec(name="read_alpha", description="开放对象", args_model=OpenArgs, handler=handler)


def test_closed_object_parameters_are_accepted() -> None:
    """对照组：普通模型（含嵌套、枚举、可选）必须能注册——否则上一条会变成「总是失败」。"""

    class Inner(BaseModel):
        label: str

    class NestedArgs(BaseModel):
        inner: Inner
        tags: list[str] = []
        ratio: float | None = None

    async def handler(_context: object, _args: NestedArgs) -> ToolResult:
        return ToolResult(text="ok")

    spec = ToolSpec(name="read_alpha", description="嵌套模型", args_model=NestedArgs, handler=handler)

    assert spec.parameters["type"] == "object"


def test_pool_rejects_a_duck_typed_tool_with_empty_name_or_description() -> None:
    """池接受结构类型，但**校验不能靠结构**：空名字/空描述必须被拒。

    实测：一个鸭子类型对象带 ``name=""``、``description=""`` 能进池并进请求体，而名字是权限
    判定与 ``allowed-tools`` 的键、描述是模型选工具的唯一依据。
    """

    class Duck:
        def __init__(self, name: str, description: str) -> None:
            self.name = name
            self.description = description
            self.risk = "low"
            self.requires_approval = False

        @property
        def parameters(self) -> dict[str, object]:
            return {"type": "object", "properties": {}}

        async def invoke(self, _context: object, _arguments_json: str) -> ToolResult:
            return ToolResult(text="ok")

    with pytest.raises(ToolRegistrationError, match="不合法"):
        ToolPool([Duck("", "有描述")])
    with pytest.raises(ToolRegistrationError, match="描述"):
        ToolPool([Duck("read_alpha", "   ")])


def test_parameters_schema_is_derived_from_the_args_model() -> None:
    """schema 与校验同源：手写两份必然漂移，而漂移方向是最坏的方向。"""
    spec = _spec()

    schema = spec.parameters

    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {"query", "limit"}


def test_duplicate_registration_fails_instead_of_overwriting() -> None:
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(ToolRegistrationError, match="重复注册"):
        pool.register(_spec("read_alpha"))


def test_reserved_tool_name_cannot_be_squatted_by_product_code() -> None:
    """``skill`` 是模型侧激活工具的保留名：产品侧不得占用（否则激活机制被顶掉）。"""
    pool = ToolPool()

    with pytest.raises(ToolRegistrationError, match="保留名"):
        pool.register(_spec("skill"))

    # 基座自有工具走另一条注册路径
    pool.register_base(_spec("skill"))
    assert pool.names() == ("skill",)


def test_tool_pool_view_is_read_only() -> None:
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(TypeError):
        pool.tools["x"] = _spec("x")  # type: ignore[index]  # 本用例故意改只读视图：赋值被拒正是被测事实


def test_always_active_tools_do_not_depend_on_allowed_tools() -> None:
    """机制本身（激活工具）必须恒可用，否则模型连第一个 skill 都激活不了。"""
    pool = ToolPool([_spec("read_alpha"), _spec("write_beta")])

    scope = resolve_scope(
        pool,
        activated=[_skill("daily", ("read_alpha",))],
        always_active=["write_beta"],
    )

    assert scope.active == {"read_alpha", "write_beta"}


def test_always_active_tool_must_be_registered() -> None:
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(ToolNotRegisteredError, match="nope"):
        resolve_scope(pool, always_active=["nope"])


def test_empty_allowed_tools_means_no_tools_for_that_skill() -> None:
    """空集是合法形状：该 skill 一件工具都不用（纯方法论 skill），不是越权。"""
    pool = ToolPool([_spec("read_alpha")])
    scope = resolve_scope(pool, activated=[_skill("pure-method", ())], default_active=["read_alpha"])

    assert scope.active == frozenset()


def test_handler_may_return_an_explicit_recoverable_failure() -> None:
    """工具可以显式返回带码失败，而不是只能抛异常把细节丢掉。"""

    async def handler(_context: ToolContext, _args: ReadArgs) -> ToolFailure:
        return ToolFailure(code="tool_not_registered", message="没有这个条目")

    spec = ToolSpec(name="read_alpha", description="读", args_model=ReadArgs, handler=handler)

    outcome = asyncio.run(spec.invoke(_context(), json.dumps({"query": "q"})))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_not_registered"
    assert outcome.message == "没有这个条目"


def test_declared_order_is_stable_and_sorted() -> None:
    pool = ToolPool([_spec("write_beta"), _spec("read_alpha")])

    assert pool.names() == ("read_alpha", "write_beta")
    assert [tool.name for tool in pool.declared()] == ["read_alpha", "write_beta"]
    # 同一次注册顺序不同的池子，声明必须一致（缓存纪律要求前缀稳定）
    assert [tool.name for tool in ToolPool([_spec("read_alpha"), _spec("write_beta")]).declared()] == [
        "read_alpha",
        "write_beta",
    ]


def test_get_unknown_tool_reports_known_names() -> None:
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(ToolNotRegisteredError) as error:
        pool.get("nope")

    assert error.value.names == ("nope",)
    assert error.value.known == ("read_alpha",)


def test_skill_allowed_tools_must_point_at_registered_tools() -> None:
    """配置错误在启动期暴露，而不是等某个 skill 第一次被激活。"""
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(ToolNotRegisteredError) as error:
        pool.ensure_skills_are_resolvable([_skill("a", ("read_alpha", "read_missing", "write_missing"))])

    assert error.value.names == ("read_missing", "write_missing")


# --- 参数边界与失败语义 -----------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_parses_arguments_and_calls_the_handler() -> None:
    spec = _spec()

    outcome = await spec.invoke(_context(), json.dumps({"query": "问题"}))

    assert isinstance(outcome, ToolResult)
    assert outcome.text == "问题:5"


@pytest.mark.asyncio
async def test_empty_arguments_are_treated_as_an_empty_object() -> None:
    async def handler(_context: ToolContext, _args: EmptyArgs) -> ToolResult:
        return ToolResult(text="ok")

    spec = ToolSpec(name="no_args", description="无参工具", args_model=EmptyArgs, handler=handler)

    outcome = await spec.invoke(_context(), "")

    assert isinstance(outcome, ToolResult)
    assert outcome.text == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "expected_fragment"),
    [
        ("{not json", "不是合法 JSON"),
        ('["a"]', "必须是对象"),
        ('{"limit": "x"}', "不符合 schema"),
        ("{}", "不符合 schema"),
    ],
)
async def test_invalid_arguments_are_an_explicit_failure(arguments: str, expected_fragment: str) -> None:
    spec = _spec()

    outcome = await spec.invoke(_context(), arguments)

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"
    assert expected_fragment in outcome.message


@pytest.mark.asyncio
async def test_argument_failure_does_not_echo_the_input_values() -> None:
    """参数摘要不得回显使用者资料，只报字段与原因。"""
    spec = _spec()

    outcome = await spec.invoke(_context(), json.dumps({"query": "敏感内容", "limit": "x"}))

    assert isinstance(outcome, ToolFailure)
    assert "敏感内容" not in outcome.message


@pytest.mark.asyncio
async def test_handler_error_becomes_a_recoverable_failure_without_leaking_the_message() -> None:
    async def handler(_context: ToolContext, _args: ReadArgs) -> ToolResult:
        raise RuntimeError("postgresql://user:secret@host/db 连不上")

    spec = ToolSpec(name="read_alpha", description="读", args_model=ReadArgs, handler=handler)

    outcome = await spec.invoke(_context(), json.dumps({"query": "q"}))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"
    assert "RuntimeError" in outcome.message
    # 异常消息可能带连接串与凭据，不得进入对话
    assert "secret" not in outcome.message


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed() -> None:
    """取消优先于一切失败处置：CancelledError 必须继续冒泡。"""

    async def handler(_context: ToolContext, _args: ReadArgs) -> ToolResult:
        raise asyncio.CancelledError

    spec = ToolSpec(name="read_alpha", description="读", args_model=ReadArgs, handler=handler)

    with pytest.raises(asyncio.CancelledError):
        await spec.invoke(_context(), json.dumps({"query": "q"}))


def test_failure_text_carries_the_error_code() -> None:
    failure = ToolFailure(code="tool_not_available", message="此刻不可用")

    assert failure.as_model_text() == '<tool_error code="tool_not_available">此刻不可用</tool_error>'


# --- 工具范围 ---------------------------------------------------------------


def test_scope_without_activation_uses_the_default_set() -> None:
    pool = ToolPool([_spec("read_alpha"), _spec("write_beta")])

    scope = resolve_scope(pool, default_active=["read_alpha"])

    assert scope.active == {"read_alpha"}
    assert scope.unavailable() == ("write_beta",)


def test_scope_with_activation_uses_only_allowed_tools() -> None:
    """默认集是「无激活」时的兜底，不是常驻底集（第 5 节不变量）。"""
    pool = ToolPool([_spec("read_alpha"), _spec("write_beta"), _spec("read_gamma")])

    scope = resolve_scope(
        pool, activated=[_skill("daily", ("read_alpha", "read_gamma"))], default_active=["write_beta"]
    )

    assert scope.active == {"read_alpha", "read_gamma"}
    assert scope.activated_skills == {"daily"}


def test_scope_unions_multiple_activated_skills() -> None:
    pool = ToolPool([_spec("read_alpha"), _spec("write_beta")])

    scope = resolve_scope(pool, activated=[_skill("daily", ("read_alpha",)), _skill("curation", ("write_beta",))])

    assert scope.active == {"read_alpha", "write_beta"}
    assert scope.activated_skills == {"daily", "curation"}


def test_scope_rejects_allowed_tools_that_are_not_registered() -> None:
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(ToolNotRegisteredError, match="read_missing"):
        resolve_scope(pool, activated=[_skill("daily", ("read_alpha", "read_missing"))])


def test_scope_rejects_unknown_default_tools() -> None:
    pool = ToolPool([_spec("read_alpha")])

    with pytest.raises(ToolNotRegisteredError, match="nope"):
        resolve_scope(pool, default_active=["nope"])


def test_availability_item_tells_which_tools_are_usable_and_which_are_not() -> None:
    pool = ToolPool([_spec("read_alpha"), _spec("write_beta")])
    scope = resolve_scope(pool, default_active=["read_alpha"])

    item = scope.availability_item()

    assert item.source == AVAILABILITY_SOURCE
    assert item.priority == InjectionPriority.TOOL_AVAILABILITY
    assert '<tool name="read_alpha" />' in item.content
    assert "<unavailable_tools>" in item.content
    assert '<tool name="write_beta" />' in item.content


def test_availability_item_omits_the_unavailable_block_when_everything_is_active() -> None:
    pool = ToolPool([_spec("read_alpha")])
    scope = resolve_scope(pool, default_active=["read_alpha"])

    assert "<unavailable_tools>" not in scope.availability_item().content


# --- 权限门 -----------------------------------------------------------------


def _dispatcher(pool: ToolPool, *, activated: tuple[str, ...] = ("read_alpha",)) -> ToolDispatcher:
    scope = resolve_scope(pool, default_active=list(activated))
    return ToolDispatcher(pool, scope, context=_context())


def _dispatcher_with_runtime_activation(
    pool: ToolPool,
    *,
    skill_name: str,
    allowed_tools: tuple[str, ...],
    default_active: tuple[str, ...] = (),
) -> ToolDispatcher:
    """造一个「模型侧刚激活了某个 skill」的 dispatcher（复刻 runner 的接线）。"""
    activation = ActivationState()
    scope = resolve_scope(pool, default_active=list(default_active))
    activation.seed(scope.activated_skills)
    activation.activate(skill_name=skill_name, allowed_tools=allowed_tools)
    context = ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=activation,
        citations=CitationRecorder(FakeCitationIndex(), run_id="run-1"),
    )
    return ToolDispatcher(pool, scope, context=context, activation_state=activation)


@pytest.mark.asyncio
async def test_runtime_activation_makes_the_skills_allowed_tools_usable() -> None:
    """运行中激活后，该 skill 的 ``allowed-tools`` 必须真的可用（基座第 5 节）。

    第一版把 skill 名当工具名判定，于是这里会得到 ``tool_not_available``——激活成功、
    工具却用不了，是「宣称的语义没有代码承载」。
    """
    calls: list[str] = []
    pool = ToolPool([_spec("read_alpha", calls=calls)])
    dispatcher = _dispatcher_with_runtime_activation(pool, skill_name="daily-consulting", allowed_tools=("read_alpha",))

    outcome = await dispatcher.dispatch("read_alpha", json.dumps({"query": "q"}))

    assert isinstance(outcome, ToolResult)
    assert calls == ["read_alpha"]


@pytest.mark.asyncio
async def test_runtime_activation_does_not_authorize_a_same_named_tool() -> None:
    """激活一个与工具同名的 skill，**不得**因此放行那个工具（AG-02）。

    第一版只存一个名字集合，激活 skill ``search`` 会让工具 ``search`` 被无条件放行——
    等价于「激活 skill 即授权同名工具」，而该 skill 的 ``allowed-tools`` 是空的。
    """
    calls: list[str] = []
    pool = ToolPool([_spec("search", calls=calls)])
    dispatcher = _dispatcher_with_runtime_activation(pool, skill_name="search", allowed_tools=())

    outcome = await dispatcher.dispatch("search", json.dumps({"query": "q"}))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_not_available"
    assert calls == [], "同名工具被越权放行：handler 被调用了"


@pytest.mark.asyncio
async def test_runtime_activation_does_not_authorize_tools_outside_allowed_tools() -> None:
    """运行中激活只放行该 skill 声明的工具，池里的其它工具照旧被拒。"""
    calls: list[str] = []
    pool = ToolPool([_spec("read_alpha", calls=calls), _spec("write_beta", calls=calls)])
    dispatcher = _dispatcher_with_runtime_activation(pool, skill_name="daily-consulting", allowed_tools=("read_alpha",))

    outcome = await dispatcher.dispatch("write_beta", json.dumps({"query": "q"}))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_not_available"
    assert calls == []


def test_activation_state_keeps_skill_names_and_tool_names_apart() -> None:
    """两个命名空间分开维护：skill 名不得混进工具集，反之亦然。"""
    state = ActivationState()
    state.seed({"from-request"})
    state.activate(skill_name="daily-consulting", allowed_tools=("read_alpha",))

    assert state.skill_names() == {"from-request", "daily-consulting"}
    assert state.allowed_tools() == {"read_alpha"}, "请求时的激活属 scope 的职责，不在这里重复并入"


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_tool() -> None:
    outcome = await _dispatcher(ToolPool([_spec()])).dispatch("nope", "{}")

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_not_registered"


@pytest.mark.asyncio
async def test_dispatch_rejects_out_of_scope_tool_without_calling_it() -> None:
    """越界调用是硬边界；被拒绝时实现**一次都不能被调用**。"""
    calls: list[str] = []
    pool = ToolPool([_spec("read_alpha", calls=calls), _spec("write_beta", calls=calls)])

    outcome = await _dispatcher(pool, activated=("read_alpha",)).dispatch("write_beta", "{}")

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_not_available"
    assert calls == []


@pytest.mark.asyncio
async def test_dispatch_rejects_tools_that_would_need_human_approval() -> None:
    """一期不实现 HITL：需要审批的工具必须显式拒绝，而不是悄悄放行。"""
    calls: list[str] = []
    pool = ToolPool([_spec("read_alpha", calls=calls, risk="medium", requires_approval=True)])

    outcome = await _dispatcher(pool).dispatch("read_alpha", "{}")

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_requires_approval"
    assert calls == []


@pytest.mark.asyncio
async def test_dispatch_calls_the_handler_when_every_gate_passes() -> None:
    calls: list[str] = []
    pool = ToolPool([_spec("read_alpha", calls=calls)])

    outcome = await _dispatcher(pool).dispatch("read_alpha", json.dumps({"query": "q"}))

    assert isinstance(outcome, ToolResult)
    assert calls == ["read_alpha"]


@pytest.mark.asyncio
async def test_dispatch_exposes_the_stable_declaration() -> None:
    pool = ToolPool([_spec("write_beta"), _spec("read_alpha")])

    dispatcher = _dispatcher(pool, activated=("read_alpha",))

    assert [tool.name for tool in dispatcher.declared] == ["read_alpha", "write_beta"]


@pytest.mark.asyncio
async def test_emergency_activation_cannot_write() -> None:
    """技能设计第 5 节的验收：应急激活时写工具被服务端拒绝。"""
    calls: list[str] = []
    pool = ToolPool([_spec("search_knowledge", calls=calls), _spec("propose_item", calls=calls)])
    scope = resolve_scope(pool, activated=[_skill("emergency-consulting", ("search_knowledge",))], default_active=[])
    dispatcher = ToolDispatcher(pool, scope, context=_context())

    outcome = await dispatcher.dispatch("propose_item", json.dumps({"query": "q"}))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_not_available"
    assert calls == []
