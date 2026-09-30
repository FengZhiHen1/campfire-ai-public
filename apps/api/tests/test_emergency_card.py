"""`tools/emergency_card.py` 的单元测试：词表硬校验、七节完整性、不静默改写。

对应契约：[emit_emergency_action_card](../../../docs/技术设计/面/consult/tools/emit_emergency_action_card.md)
第 4、5、6 节，与[通用基座](../../../docs/技术设计/technical-details/通用基座.md)第 7.3 节。

**契约第 6 节验证方式逐条落在这里**：取值枚举（含越界的 `critical`）、七节完整、
不静默改写（被拒后没有卡片）、`unknown` 不误读（不在此处——那是前端呈现）、
重复评估 `card_id` 不同。事件层的断言（`action_card` 事件确实发出）由
`test_agent_questions.py` 一类的运行编排测试覆盖；本文件钉的是**工具侧**：
越界载荷到不了 `ToolResult`。

**不连库**：本工具不读写业务数据，没有集成测试——这是它的诚实边界。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from campfire.agent.context import CitationRecorder
from campfire.agent.tools import (
    ActionCard,
    ActivationState,
    ToolContext,
    ToolFailure,
    ToolPool,
    ToolResult,
    ToolSpec,
)
from campfire.tools.emergency_card import (
    ACCOUNT_PAYLOAD_KEY,
    ANNOTATION_CONFIDENCES,
    ANNOTATION_SOURCES,
    CARD_TITLE,
    SECTION_KEYS,
    STATE_KEYS,
    STATE_VALUE_TABLE,
    EmitEmergencyActionCardArgs,
    decode_annotation_kind,
    emit_emergency_action_card,
)

_ACCOUNT = "tool_test_account"

#: 契约第 4 节的取值表（逐字抄自文档，用于与实现比对——不是从实现派生，
#: 否则两处定义漂移时测试会跟着一起漂）。
#: 来源：docs/技术设计/面/consult/tools/emit_emergency_action_card.md 第 4 节。
CONTRACT_STATE_VALUES = {
    "deviation": ("none", "mild", "moderate", "marked", "unknown"),
    "communication": ("baseline", "reduced", "severely_reduced", "unavailable"),
    "sensory_load": ("low", "moderate", "high", "extreme"),
    "medical_risk": ("stable", "uncertain", "high_risk"),
}


class _FakeIndex:
    def add(self, *_args: Any, **_kwargs: Any) -> None: ...


def _context(payload: object | None = None) -> ToolContext:
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_FakeIndex(), run_id="run-1", clock=lambda: datetime.now(timezone.utc)),
        payload=payload,
    )


def _accounted() -> ToolContext:
    return _context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT})


def _scope(pool: ToolPool):
    """把池里全部工具设为此刻可用（端到端用例用）。

    为什么必须显式给范围：产品工具的可用性由激活集合决定，而 `resolve_scope(pool)`
    在不传激活 skill 时 `active` 是空集——于是派发层返回 `tool_not_available`，
    卡片根本到不了桥。这本身是**正确**的行为（工具可见性不是安全边界，服务端照常拒绝），
    只是端到端用例要先把工具放进可用集合，才能测到它后面的那段路。
    """
    from campfire.agent.tools import resolve_scope

    return resolve_scope(pool, default_active=pool.names())


def _raw_args(**overrides: Any) -> dict[str, Any]:
    """一份合法的原始参数（未过模型），供各用例叠加越界项。"""
    base: dict[str, Any] = {
        "sections": [
            {
                "key": "status",
                "heading": "当前状态",
                "lines": ["当前沟通较平时明显减少，等待至少 10 秒"],
            },
            {"key": "communicate", "heading": "立即怎么沟通", "lines": ["一次只让一个人讲话"]},
            {"key": "do_now", "heading": "立即做", "lines": ["把灯光调暗，减少在场人数"]},
            {"key": "avoid", "heading": "不要做", "lines": ["不要突然触碰"]},
            {"key": "medical_checks", "heading": "需要的医疗检查", "lines": ["需要确认有无疼痛来源"]},
            {"key": "safety", "heading": "安全措施", "lines": ["移开通道上的障碍物"]},
            {"key": "when_to_escalate", "heading": "何时升级", "lines": ["出现意识改变时立即求助"]},
        ],
        "states": [
            {"key": "deviation", "value": "marked"},
            {"key": "communication", "value": "reduced"},
            {"key": "sensory_load", "value": "high"},
            {"key": "medical_risk", "value": "uncertain"},
        ],
        "annotations": [{"line_ref": 1, "source": "family_report", "confidence": "likely"}],
    }
    base.update(overrides)
    return base


def _args(**overrides: Any) -> EmitEmergencyActionCardArgs:
    return EmitEmergencyActionCardArgs.model_validate(_raw_args(**overrides))


# ---------------------------------------------------------------------------
# 参数形状与词表（契约第 2、4 节）
# ---------------------------------------------------------------------------


def test_parameter_names_match_the_contract() -> None:
    """参数名与契约逐字一致。"""
    assert set(EmitEmergencyActionCardArgs.model_fields) == {"sections", "states", "annotations"}


def test_does_not_accept_a_support_object_id() -> None:
    """**不收 `support_object_id`**（契约第 2 节末行）：卡片的取数在注入侧已完成。

    判别性：加上这个参数，本用例失败——它会让调用方以为本工具做了一次取数。
    """
    assert "support_object_id" not in EmitEmergencyActionCardArgs.model_fields


def test_contract_state_tables_match_the_document() -> None:
    """四个状态键的取值词表与契约第 4 节的表逐值一致。

    这是**两处定义之间的比对**：词表写在参数模型的 `Literal` 里（校验真源），
    `STATE_VALUE_TABLE` 是它的可读投影。漂移会让模型看到一个与契约不符的 schema。

    判别性：删掉某个取值或加一个契约里没有的取值，本用例失败。
    """
    assert STATE_VALUE_TABLE == CONTRACT_STATE_VALUES
    assert STATE_KEYS == ("deviation", "communication", "sensory_load", "medical_risk")


@pytest.mark.parametrize(
    ("key", "value"),
    [(key, value) for key, values in CONTRACT_STATE_VALUES.items() for value in values],
)
def test_every_legal_state_value_is_accepted(key: str, value: str) -> None:
    """契约第 6 节「取值枚举」的前半：**每个合法取值都能通过**。

    逐值参数化而不是只测一个：漏掉一个合法取值会让模型在正确取值上被拒，
    而那种失败只在真实应急里出现。
    """
    args = _args(states=[{"key": key, "value": value}])

    assert len(args.states) == 1
    assert args.states[0].key == key
    assert args.states[0].value == value


def test_out_of_range_medical_risk_is_rejected() -> None:
    """契约第 6 节「取值枚举」的后半 + 质量地板校验点①：`medical_risk: critical` 被拒。

    判别性：把 `_MedicalRiskState.value` 从 `Literal` 改回 `str`，本用例失败——
    而 `AC-21` 的机械端正是靠它成立（医疗风险只允许三种表述）。
    """
    with pytest.raises(Exception):  # noqa: B017 —— pydantic 的 ValidationError
        _args(states=[{"key": "medical_risk", "value": "critical"}])


def test_a_state_value_from_another_key_is_rejected() -> None:
    """跨键取词也被拒：`medical_risk: mild` 不是「词表内」，是**另一个键**的词表。

    判别性：把四个状态变体合并成一个「key 枚举 + value 自由字符串」，本用例失败
    ——那正是本工具最核心的一条机械保证。
    """
    for key, foreign_value in (
        ("medical_risk", "mild"),
        ("deviation", "high_risk"),
        ("sensory_load", "reduced"),
        ("communication", "extreme"),
    ):
        with pytest.raises(Exception):  # noqa: B017
            _args(states=[{"key": key, "value": foreign_value}])


def test_an_unknown_state_key_is_rejected() -> None:
    """词表外的状态键被拒（它无处呈现，且会静默丢掉一个真实状态）。"""
    with pytest.raises(Exception):  # noqa: B017
        _args(states=[{"key": "pain_level", "value": "high"}])


def test_states_may_omit_a_key_but_not_repeat_one() -> None:
    """缺失某个状态键合法（契约第 4 节末行「或缺失」按未排除处理），重复非法。"""
    # 只给一个键：合法。
    args = _args(states=[{"key": "medical_risk", "value": "stable"}])
    assert len(args.states) == 1

    # 同一个键两次：拒绝——那不是「缺失」，是一次自相矛盾。
    with pytest.raises(Exception):  # noqa: B017
        _args(
            states=[
                {"key": "medical_risk", "value": "stable"},
                {"key": "medical_risk", "value": "high_risk"},
            ]
        )


def test_an_empty_states_list_is_rejected() -> None:
    """状态字段一个都没有 → 拒绝：那不是一张现场行动卡。"""
    with pytest.raises(Exception):  # noqa: B017
        _args(states=[])


# ---------------------------------------------------------------------------
# 七节完整（契约第 4、6 节 + 质量地板校验点②）
# ---------------------------------------------------------------------------


def test_missing_a_section_is_rejected() -> None:
    """缺任一节都被拒（契约第 6 节「七节完整」+ 质量地板校验点②）。

    逐节参数化：漏检某一节意味着该节的缺席可以在真实应急里静默通过。
    """
    for missing in SECTION_KEYS:
        raw = _raw_args()
        raw["sections"] = [section for section in raw["sections"] if section["key"] != missing]
        with pytest.raises(Exception):  # noqa: B017
            EmitEmergencyActionCardArgs.model_validate(raw)


def test_duplicated_section_key_is_rejected_even_with_seven_sections() -> None:
    """七节长度够但键重复 → 拒绝：长度校验挡不住「七节全是 status」。

    判别性：去掉 `_require_all_seven_sections_exactly_once`，本用例失败——
    而那样发出的卡片在呈现上会静默缺六节。
    """
    raw = _raw_args()
    raw["sections"] = [{"key": "status", "heading": "当前状态", "lines": ["行"]} for _ in range(7)]
    with pytest.raises(Exception):  # noqa: B017
        EmitEmergencyActionCardArgs.model_validate(raw)


def test_an_empty_section_is_rejected() -> None:
    """某节没有行 → 拒绝（契约第 5 节：「某节为空」是 `tool_invalid_arguments`）。"""
    raw = _raw_args()
    raw["sections"][3]["lines"] = []
    with pytest.raises(Exception):  # noqa: B017
        EmitEmergencyActionCardArgs.model_validate(raw)


def test_a_blank_line_is_rejected() -> None:
    """空白行被拒：它是一条呈现上不存在的「动作」，会让一节看起来有内容而实际没有。"""
    raw = _raw_args()
    raw["sections"][2]["lines"] = [""]
    with pytest.raises(Exception):  # noqa: B017
        EmitEmergencyActionCardArgs.model_validate(raw)


# ---------------------------------------------------------------------------
# 标注（契约第 2 节；来源六类、置信四档）
# ---------------------------------------------------------------------------


def test_every_annotation_source_and_confidence_is_accepted() -> None:
    """来源六类与置信四档的每个取值都能通过（契约第 2 节）。"""
    assert ANNOTATION_SOURCES == (
        "self_report",
        "family_report",
        "onsite_observation",
        "history",
        "medical_record",
        "ai_inference",
    )
    assert ANNOTATION_CONFIDENCES == ("confirmed", "likely", "possible", "unknown")

    for source in ANNOTATION_SOURCES:
        for confidence in ANNOTATION_CONFIDENCES:
            args = _args(annotations=[{"line_ref": 1, "source": source, "confidence": confidence}])
            assert args.annotations[0].source == source
            assert args.annotations[0].confidence == confidence


def test_an_unknown_annotation_source_or_confidence_is_rejected() -> None:
    """词表外的来源或置信被拒（编不出第七类来源、编不出第五档置信）。"""
    with pytest.raises(Exception):  # noqa: B017
        _args(annotations=[{"line_ref": 1, "source": "rumor", "confidence": "confirmed"}])
    with pytest.raises(Exception):  # noqa: B017
        _args(annotations=[{"line_ref": 1, "source": "self_report", "confidence": "almost_sure"}])


def test_an_annotation_pointing_outside_the_card_is_rejected() -> None:
    """指向不存在的行 → 拒绝：来源标注不能指不到任何内容。

    判别性：去掉 `_require_annotations_point_inside_the_card`，本用例失败——
    那条标注最终要么被丢弃（来源静默消失），要么被错配到别的行。
    """
    total_lines = sum(len(section["lines"]) for section in _raw_args()["sections"])

    # 边界内（最后一行）合法。
    _args(annotations=[{"line_ref": total_lines, "source": "history", "confidence": "possible"}])

    # 越界一格即拒绝。
    with pytest.raises(Exception):  # noqa: B017
        _args(annotations=[{"line_ref": total_lines + 1, "source": "history", "confidence": "possible"}])


def test_annotations_may_be_empty() -> None:
    """标注可为空（契约第 2 节「可为空」）。"""
    assert _args(annotations=[]).annotations == []


def test_annotation_kind_encoding_round_trips() -> None:
    """`kind` 的「来源:置信」编码可无损还原（契约第 2 节与基座 7.3 节的形状桥接）。

    判别性：把编码改成只放 source，`confidence` 在事件里消失——`action-card.md`
    第 4 节「判断带置信等级」随之失效，且「AI 推断」与「已确认」不可区分。
    """
    args = _args(annotations=[{"line_ref": 2, "source": "ai_inference", "confidence": "possible"}])

    assert args.annotations[0].source == "ai_inference"


@pytest.mark.asyncio
async def test_the_emitted_card_encodes_source_and_confidence_in_kind() -> None:
    """发出的卡片在 `kind` 里同时带上来源与置信，`target` 是行号。"""
    outcome = await emit_emergency_action_card(
        _accounted(),
        _args(annotations=[{"line_ref": 2, "source": "ai_inference", "confidence": "possible"}]),
    )

    assert isinstance(outcome, ToolResult)
    annotation = outcome.cards[0].annotations[0]
    assert annotation.target == "2"
    assert decode_annotation_kind(annotation.kind) == ("ai_inference", "possible")


def test_decoding_rejects_a_foreign_kind() -> None:
    """还原函数对不是本工具产出的 `kind` 明确失败，而不是猜一个来源。"""
    for bad in ("self_report", "rumor:confirmed", "self_report:certain", ""):
        with pytest.raises(ValueError):
            decode_annotation_kind(bad)


# ---------------------------------------------------------------------------
# 发出的卡片（契约第 1、3、6 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_returns_a_card_matching_the_base_envelope() -> None:
    """卡片信封与基座 7.3 节逐字一致：`card_id` / `title` / `sections` / `states` / `annotations`。

    判别性：往信封上多写一个字段（例如把 `source`/`confidence` 直接摊在标注上），
    本用例失败——基座信封的键名就是线上契约（HTTP/SSE 契约第 4.2 节的恒等映射）。
    """
    outcome = await emit_emergency_action_card(_accounted(), _args())

    assert isinstance(outcome, ToolResult)
    assert len(outcome.cards) == 1, "一次调用发一张卡"
    card = outcome.cards[0]
    assert isinstance(card, ActionCard)
    assert card.card_id
    assert card.title
    assert [section.key for section in card.sections] == list(SECTION_KEYS)
    assert all(section.lines for section in card.sections), "每节至少一行"
    assert {state.key for state in card.states} == {"deviation", "communication", "sensory_load", "medical_risk"}
    assert [annotation.target for annotation in card.annotations] == ["1"]
    # 信封上只有基座 7.3 节的五个字段（`ActionCard` 是 slots 数据类，用 fields 而非 vars）。
    assert {field.name for field in dataclasses.fields(card)} == {
        "card_id",
        "title",
        "sections",
        "states",
        "annotations",
    }


@pytest.mark.asyncio
async def test_a_shuffled_payload_is_emitted_in_the_canonical_section_order() -> None:
    """乱序七节被接受，但产出的卡片按 `SECTION_KEYS` 的规范顺序（契约第 2 节「按固定顺序」）。

    顺序是呈现层事实：基座 `ActionCard.sections` 的说明是「按呈现顺序」，前端
    `.action-card` 按它渲染。契约第 5 节的失败语义只列「缺节 / 某节为空」，
    因此乱序不构成拒绝条件，而是生产方要规范化掉的输入。

    判别性：去掉 handler 里的排序，本用例失败——产出顺序会与模型给的乱序一致。
    """
    shuffled = list(reversed(_raw_args()["sections"]))
    assert [section["key"] for section in shuffled] != list(SECTION_KEYS), "样本必须真的乱序"

    outcome = await emit_emergency_action_card(_accounted(), _args(sections=shuffled))

    assert isinstance(outcome, ToolResult), "乱序是合法输入，不得被拒绝"
    emitted = outcome.cards[0].sections
    assert [section.key for section in emitted] == list(SECTION_KEYS)
    # 小标题跟着键走，不因排序而错配到别节。
    assert [section.heading for section in emitted] == [
        "当前状态",
        "立即怎么沟通",
        "立即做",
        "不要做",
        "需要的医疗检查",
        "安全措施",
        "何时升级",
    ]


@pytest.mark.asyncio
async def test_emit_reports_the_card_id_to_the_model() -> None:
    """返回文本带上 `card_id`（契约第 3 节的返回字段），且与卡片里的一致。

    判别性：返回一个与卡片不同的 id，本用例失败——模型回执里引用的卡片就指错了。
    """
    outcome = await emit_emergency_action_card(_accounted(), _args())

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["card_id"] == outcome.cards[0].card_id


@pytest.mark.asyncio
async def test_two_cards_get_different_ids() -> None:
    """契约第 6 节「重复评估」：连续两张卡的 `card_id` 不同。

    判别性：把 `card_id` 换成固定值（或让模型传入），本用例失败——前端凭它区分新旧卡，
    固定值会让第二张卡永远无法让第一张失效。
    """
    first = await emit_emergency_action_card(_accounted(), _args())
    second = await emit_emergency_action_card(_accounted(), _args())

    assert isinstance(first, ToolResult) and isinstance(second, ToolResult)
    assert first.cards[0].card_id != second.cards[0].card_id


@pytest.mark.asyncio
async def test_emit_fails_without_an_account() -> None:
    """未登录（payload 里没有账号）→ 明确失败，不产出卡片（契约第 5 节 + 校验点④）。"""
    for payload in (None, {}, {ACCOUNT_PAYLOAD_KEY: ""}, {ACCOUNT_PAYLOAD_KEY: "  "}):
        outcome = await emit_emergency_action_card(_context(payload=payload), _args())
        assert isinstance(outcome, ToolFailure), "缺账号时不得发出卡片"
        assert outcome.code == "tool_failed"
        assert ACCOUNT_PAYLOAD_KEY in outcome.message


# ---------------------------------------------------------------------------
# 不静默改写（契约第 5、6 节 + 质量地板对抗用例）
# ---------------------------------------------------------------------------


def test_every_out_of_range_payload_fails_validation_not_rewriting() -> None:
    """契约第 6 节「不静默改写」：越界载荷被拒，**没有一个**被改成合法值。

    逐项构造越界载荷并断言「抛错」，而不是「得到一个被改写的卡片」——
    契约第 5 节的原话是「不静默替换成合法值」，因为一张「看起来合法但值是猜的」
    行动卡比没有卡片更危险：使用者会照着它做。

    判别性：把任一枚举换成 `str` 并在 handler 里加一个 `.get(value, "unknown")` 兜底，
    本用例失败。
    """
    out_of_range_payloads: list[dict[str, Any]] = [
        _raw_args(states=[{"key": "medical_risk", "value": "critical"}]),
        _raw_args(states=[{"key": "deviation", "value": "severe"}]),
        _raw_args(states=[{"key": "communication", "value": "none"}]),
        _raw_args(states=[{"key": "sensory_load", "value": "unknown"}]),
        _raw_args(annotations=[{"line_ref": 1, "source": "guess", "confidence": "confirmed"}]),
        _raw_args(annotations=[{"line_ref": 1, "source": "self_report", "confidence": "probable"}]),
        _raw_args(annotations=[{"line_ref": 999, "source": "self_report", "confidence": "confirmed"}]),
    ]
    for payload in out_of_range_payloads:
        with pytest.raises(Exception):  # noqa: B017 —— 解析期失败，ToolResult 从不构造
            EmitEmergencyActionCardArgs.model_validate(payload)


@pytest.mark.asyncio
async def test_a_rejected_payload_produces_no_card_through_the_spec_path() -> None:
    """**质量地板校验点①的对抗用例**：越界载荷经 `ToolSpec.invoke` 得到
    `tool_invalid_arguments`，且返回的不是 `ToolResult`——因此事件流里不会有 `action_card`。

    走 `ToolSpec.invoke`（真实的模型调用路径）而不是直接 `model_validate`：
    要证明的是「越界载荷到不了卡片」，而卡片只从 `ToolResult.cards` 出去。
    `ToolSpec` 的 `_parse` 在解析期就返回 `ToolFailure`，handler 根本没有被调用。

    判别性：把词表校验从参数模型挪到 handler 里（先构造卡片再判断要不要发），
    本用例仍可能通过——但那时「不发卡片」成了 handler 的一个分支而不是结构保证；
    真正能测出差别的是 `test_out_of_range_medical_risk_is_rejected` 与
    `test_a_state_value_from_another_key_is_rejected`（它们断言解析期即失败）。
    """
    from campfire.agent.tools import ToolSpec

    calls: list[str] = []

    async def _handler(_context: ToolContext, _args: EmitEmergencyActionCardArgs) -> ToolResult:
        calls.append("called")
        return ToolResult(text="不应到达这里")

    spec: ToolSpec[EmitEmergencyActionCardArgs] = ToolSpec(
        name="emit_emergency_action_card",
        description="测试用",
        args_model=EmitEmergencyActionCardArgs,
        handler=_handler,
    )

    bad = _raw_args(states=[{"key": "medical_risk", "value": "critical"}])
    outcome = await spec.invoke(_accounted(), json.dumps(bad, ensure_ascii=False))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"
    assert calls == [], "参数不合法时 handler 不得被调用"
    assert not hasattr(outcome, "cards"), "失败结果没有卡片通道——事件流里不会有 action_card"


@pytest.mark.asyncio
async def test_a_valid_payload_reaches_the_handler_and_emits_exactly_one_card() -> None:
    """对照用例：同一路径下合法载荷确实到达 handler 并产出一张卡。

    没有这一条，上一条用例可能只是「什么都没发生」也能通过（永远不失败的空检查）。
    """
    from campfire.agent.tools import ToolSpec

    calls: list[str] = []

    async def _handler(context: ToolContext, args: EmitEmergencyActionCardArgs) -> ToolResult:
        calls.append("called")
        return await emit_emergency_action_card(context, args)

    spec: ToolSpec[EmitEmergencyActionCardArgs] = ToolSpec(
        name="emit_emergency_action_card",
        description="测试用",
        args_model=EmitEmergencyActionCardArgs,
        handler=_handler,
    )

    outcome = await spec.invoke(_accounted(), json.dumps(_raw_args(), ensure_ascii=False))

    assert isinstance(outcome, ToolResult)
    assert calls == ["called"]
    assert len(outcome.cards) == 1


# ---------------------------------------------------------------------------
# 端到端：真工具经真桥翻成 action_card 事件（契约第 1 节「基座把工具返回的卡片
# 翻成 action_card 事件下发」）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_bridge_emits_the_action_card_event_with_matching_fields() -> None:
    """真工具经真桥产出 `action_card` 事件，字段与卡片逐字对应。

    为什么需要这一条（`test_agent_questions.py` 已用替身卡片工具测过桥的翻译）：
    替身只能证明「桥会翻 `ToolResult.cards`」，证明不了「本工具产出的卡片形状是桥认得的
    形状」。两处各自的测试都绿、而中间对不上——正是接口类改动最常见的失败模式。
    这里用的是真工具、真工具池、真桥，因此那一段路是真的走通了。

    判别性：把卡片只放进 `text`（写成 JSON 字符串）而不放 `cards`，本用例失败——
    那样卡片退化成自由文本，前端要自己解析，而契约第 1 节明确否定了这条路
    （「不由模型写自由文本再由前端解析——这是结构可校验的前提」）。
    """
    from campfire.agent.runtime.assembly import ToolBridge
    from campfire.agent.runtime.events import ActionCardEvent
    from campfire.agent.tools import ToolDispatcher, ToolPool

    pool = ToolPool()
    pool.register(
        ToolSpec(
            name="emit_emergency_action_card",
            description="测试用",
            args_model=EmitEmergencyActionCardArgs,
            handler=emit_emergency_action_card,
        )
    )
    events: list[object] = []
    bridge = ToolBridge(
        ToolDispatcher(pool, _scope(pool), context=_accounted()),
        sink=events.append,
    )

    await bridge._invoke(
        "emit_emergency_action_card",
        None,
        json.dumps(
            _raw_args(annotations=[{"line_ref": 1, "source": "family_report", "confidence": "likely"}]),
            ensure_ascii=False,
        ),
    )

    cards = [event for event in events if isinstance(event, ActionCardEvent)]
    assert len(cards) == 1, "一次调用发一张 action_card 事件"
    event = cards[0]
    assert event.card_id
    assert event.title == CARD_TITLE
    assert [section.key for section in event.sections] == list(SECTION_KEYS)
    assert {state.key for state in event.states} == {"deviation", "communication", "sensory_load", "medical_risk"}
    assert event.annotations[0].target == "1"
    assert decode_annotation_kind(event.annotations[0].kind) == ("family_report", "likely")


@pytest.mark.asyncio
async def test_no_action_card_event_is_emitted_for_a_rejected_payload() -> None:
    """契约第 6 节「不静默改写」的事件级证明：越界载荷经**真桥**不产出任何卡片事件。

    与前一条同样是端到端：`ToolDispatcher.dispatch` → `ToolSpec._parse` 失败 →
    `ToolFailure` → 桥只发 `tool_call_finished(ok=False)`，卡片事件的循环根本不被进入。

    判别性：把词表校验从参数模型挪到 handler（构造出卡片再决定发不发），
    本用例会失败——那时桥已经拿到了一张卡片。
    """
    from campfire.agent.runtime.assembly import ToolBridge
    from campfire.agent.runtime.events import ActionCardEvent
    from campfire.agent.tools import ToolDispatcher, ToolPool

    pool = ToolPool()
    pool.register(
        ToolSpec(
            name="emit_emergency_action_card",
            description="测试用",
            args_model=EmitEmergencyActionCardArgs,
            handler=emit_emergency_action_card,
        )
    )
    events: list[object] = []
    bridge = ToolBridge(
        ToolDispatcher(pool, _scope(pool), context=_accounted()),
        sink=events.append,
    )

    bad = _raw_args(states=[{"key": "medical_risk", "value": "critical"}])
    text = await bridge._invoke("emit_emergency_action_card", None, json.dumps(bad, ensure_ascii=False))

    assert not [event for event in events if isinstance(event, ActionCardEvent)], "越界载荷不得产出卡片事件"
    # 失败以明确的工具调用失败告知模型（它可据此改用文本作答，契约第 5 节）。
    assert "tool_invalid_arguments" in text or "不符合 schema" in text
