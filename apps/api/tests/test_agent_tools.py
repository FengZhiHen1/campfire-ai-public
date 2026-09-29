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
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activated_skills=frozenset({"emergency"}),
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
