"""应急侧产品工具：`emit_emergency_action_card`。

职责：把模型给的七节 + 四个状态字段校验后翻成基座第 7.3 节的通用卡片信封，
经 `ToolResult.cards` 交回，由运行编排翻成 `action_card` 事件。
边界：只做形状校验与信封映射——不读不写任何业务数据，不生成卡片内容，
七节的语义与措辞归 `apps/api/skills/emergency-consulting`（本模块不含领域规则）。
参考：docs/技术设计/面/consult/tools/emit_emergency_action_card.md；
docs/技术设计/technical-details/通用基座.md 第 7.3 节；
docs/技术设计/decisions/应急卡片由产品侧工具产出.md。

归属裁决（T04 裁决 2）：实现放 `tools/` 而不是 `surfaces/consult/`——它与 library/memory
工具同形（参数模型 + handler + 错误码），且技能设计第 3 节把它列进十个模型可见工具之一。
它确实不读写业务数据（契约第 1 节：卡片的取数在注入侧已完成），因此本模块只依赖
`agent/tools` 的形状类型，一个 `modules/*` 与 `core/db` 都不 import——这是它的诚实边界，
不是遗漏。

为什么不接受 `support_object_id`（契约第 2 节末行）：卡片的取数（档案八组与近期记忆）
在注入侧已完成，本工具只承载输出形状。多一个对象参数会让它看起来有一次取数，
而那次取数并不发生。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from campfire.agent.tools import (
    ActionCard,
    ActionCardAnnotation,
    ActionCardSection,
    ActionCardState,
    ToolContext,
    ToolFailure,
    ToolResult,
)

logger = logging.getLogger(__name__)

#: 账号键（与 `tools/memory.py`、`tools/profile.py` 各自持有一份的理由见 profile.py 模块说明：
#: `tools/` 白名单不放行兄弟工具模块互相 import）。本工具不读写业务数据，取账号只是为了
#: 满足契约第 5 节末行的「未登录 → 明确失败」——卡片是账号级输出，没有账号就不该产出。
ACCOUNT_PAYLOAD_KEY = "account_id"

#: 卡片的七个分节键，顺序即呈现顺序（契约第 2 节）。
#: 顺序是有语义的：它复刻应急 skill 的六层闸门（医疗 → 基线偏离 → 沟通 → 环境 →
#: 既往策略 → 安全），因此不按字母序排——按字母序会让「不要做」排到「立即做」前面。
SECTION_KEYS: tuple[str, ...] = (
    "status",
    "communicate",
    "do_now",
    "avoid",
    "medical_checks",
    "safety",
    "when_to_escalate",
)

#: 状态字段的四个键，顺序即契约第 2 节的顺序。
STATE_KEYS: tuple[str, ...] = ("deviation", "communication", "sensory_load", "medical_risk")

#: 来源六类（契约第 2 节、`emergency-consulting` 的 `references/action-card.md` 第 4 节）。
ANNOTATION_SOURCES: tuple[str, ...] = (
    "self_report",
    "family_report",
    "onsite_observation",
    "history",
    "medical_record",
    "ai_inference",
)

#: 置信四档（同上）。刻意不含任何概率措辞（`action-card.md` 第 6 节：不给百分比）。
ANNOTATION_CONFIDENCES: tuple[str, ...] = ("confirmed", "likely", "possible", "unknown")

#: 卡片标题。契约第 3 节只规定了返回 `card_id`，标题由产品侧给（基座 7.3 节的信封里
#: `title` 是必填，而基座不含领域词，所以标题只能在这一侧定）。
CARD_TITLE = "现场行动卡"


class _Section(BaseModel):
    """卡片的一个分节（契约第 2 节）。"""

    model_config = ConfigDict(extra="forbid")

    key: Annotated[
        Literal["status", "communicate", "do_now", "avoid", "medical_checks", "safety", "when_to_escalate"],
        Field(
            description=(
                "分节键，七节各一次，依次为：当前状态/立即怎么沟通/立即做/不要做/需要的医疗检查/安全措施/何时升级"
            )
        ),
    ]
    heading: Annotated[str, Field(min_length=1, description="分节小标题")]
    lines: Annotated[
        list[Annotated[str, Field(min_length=1)]],
        Field(min_length=1, description="该节的文本行，至少一行；用可执行语言，动词开头"),
    ]


# --- 状态字段：每个键各自绑定自己的取值词表 -----------------------------------------
#
# 为什么按 `key` 分成四个模型而不是「一个 `key` 枚举 + 一个 `value` 自由字符串」：
# 后者的 `value` 必须接受任意字符串，而「`medical_risk: critical` 被拒」正是契约第 4 节
# 与 `AC-21` 要求的机械保证——自由字符串下它只能靠 handler 里的 if 事后判，判漏一次就让
# 越界值进了事件。分成四个变体后，每个键的合法取值在解析期就固定，越界在参数层失败。
#
# 判别的键是 `key`：pydantic 按它的字面量分派到对应变体，于是
# `{"key": "medical_risk", "value": "mild"}` 会被拒（`mild` 不是医疗风险的取值）。
#
# 词表写在各变体的 `Literal` 里而不是从常量表派生：pydantic 的类型判别需要静态字面量，
# 运行时拼出来的类型对静态检查与错误定位都不友好。代价是这四行与契约第 4 节的表是两处
# 定义——由 `test_emergency_card.py` 逐值断言四张词表与契约一致来钉住。


class _DeviationState(BaseModel):
    """状态 `deviation`：与平时相比的变化。"""

    model_config = ConfigDict(extra="forbid")

    key: Literal["deviation"]
    value: Literal["none", "mild", "moderate", "marked", "unknown"]


class _CommunicationState(BaseModel):
    """状态 `communication`：当前沟通能力。"""

    model_config = ConfigDict(extra="forbid")

    key: Literal["communication"]
    value: Literal["baseline", "reduced", "severely_reduced", "unavailable"]


class _SensoryLoadState(BaseModel):
    """状态 `sensory_load`：当前感觉负荷。"""

    model_config = ConfigDict(extra="forbid")

    key: Literal["sensory_load"]
    value: Literal["low", "moderate", "high", "extreme"]


class _MedicalRiskState(BaseModel):
    """状态 `medical_risk`：医疗风险。

    `AC-21` 只允许三种表述。第四种（例如 `critical`）在解析期被拒——这是一条安全边界，
    不是措辞偏好：把未排除的医疗风险说成别的措辞会让使用者低估该做的医疗评估。
    """

    model_config = ConfigDict(extra="forbid")

    key: Literal["medical_risk"]
    value: Literal["stable", "uncertain", "high_risk"]


_StateEntry = Annotated[
    _DeviationState | _CommunicationState | _SensoryLoadState | _MedicalRiskState,
    Field(discriminator="key"),
]

#: 契约第 4 节的取值表（键 → 合法取值）。只为测试与文档而存在：参数模型的枚举是
#: 校验的真源，本表是它的可读投影，供测试逐值比对「枚举 == 契约」，两处漂移会被测出来。
STATE_VALUE_TABLE: dict[str, tuple[str, ...]] = {
    "deviation": ("none", "mild", "moderate", "marked", "unknown"),
    "communication": ("baseline", "reduced", "severely_reduced", "unavailable"),
    "sensory_load": ("low", "moderate", "high", "extreme"),
    "medical_risk": ("stable", "uncertain", "high_risk"),
}


class _Annotation(BaseModel):
    """一条逐条动作的来源与置信（契约第 2 节）。

    契约第 2 节把它写成三个字段（`line_ref` / `source` / `confidence`），而基座 7.3 节的
    信封只有 `{target, kind}` 两个字段。这个不对称是本工具要桥接的核心，处置见
    `_encode_annotation_kind` 的说明。
    """

    model_config = ConfigDict(extra="forbid")

    line_ref: Annotated[
        int,
        Field(ge=1, description="指向 sections 内某条 line 的序号：按七节顺序把各行摊平后的 1 起序号"),
    ]
    source: Annotated[
        Literal[
            "self_report",
            "family_report",
            "onsite_observation",
            "history",
            "medical_record",
            "ai_inference",
        ],
        Field(description="这条动作/判断的来源：本人报告/家属报告/现场观察/历史记录/医疗记录/AI 推断"),
    ]
    confidence: Annotated[
        Literal["confirmed", "likely", "possible", "unknown"],
        Field(description="置信等级四档；不使用精确概率"),
    ]


class EmitEmergencyActionCardArgs(BaseModel):
    """`emit_emergency_action_card` 的参数（契约第 2 节）。

    词表全部落在这里的枚举上，而不是提示词里（契约第 4 节的判据）：

    `AC-21` 要求医疗风险只出现「稳定 / 未排除 / 高风险」三种表述。写在 skill 指令里是
    提示词层约束，可以绕过（`RQ-LIM-05` 已明确该层不构成安全边界）；落在参数模型的枚举上，
    越界载荷根本到不了事件——`ToolSpec._parse` 在解析期就把它变成
    `tool_invalid_arguments`，`ToolResult` 从不构造，因此不发残缺卡片。
    """

    model_config = ConfigDict(extra="forbid")

    sections: Annotated[
        list[_Section],
        Field(
            min_length=len(SECTION_KEYS),
            max_length=len(SECTION_KEYS),
            description=("七节，按固定顺序（当前状态/立即怎么沟通/立即做/不要做/需要的医疗检查/安全措施/何时升级）"),
        ),
    ]
    states: Annotated[
        list[_StateEntry],
        Field(
            min_length=1,
            max_length=len(STATE_KEYS),
            description="状态字段：deviation / communication / sensory_load / medical_risk，取值受词表硬校验",
        ),
    ]
    annotations: Annotated[
        list[_Annotation],
        Field(default_factory=list, description="逐条动作的来源与置信；可为空"),
    ]

    @model_validator(mode="after")
    def _require_all_seven_sections_exactly_once(self) -> "EmitEmergencyActionCardArgs":
        """七节必须齐全且各出现一次（契约第 4 节：七节是硬结构，缺节不发残缺卡片）。

        为什么用模型级校验而不是只靠 `Literal` 与长度：`min_length=7` 只保证「有七节」，
        不保证「是七个不同的键」——七节全填 `status` 同样能过长度校验，而那样的卡片
        在呈现上会缺六节，且缺得静默。因此这里按集合比对。

        这里不判顺序：契约第 5 节的失败语义只列「缺节 / 某节为空」，乱序是合法输入，
        由 handler 按 `SECTION_KEYS` 规范化后产出（见 `emit_emergency_action_card`）。

        Raises:
            ValueError: 分节键缺失或重复（pydantic 会收成正常的校验失败，
                最终由 `ToolSpec._parse` 变成 `tool_invalid_arguments`）。
        """
        keys = [section.key for section in self.sections]
        if len(set(keys)) != len(keys):
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            raise ValueError(f"分节键重复：{duplicates}——七节各出现一次")
        missing = [key for key in SECTION_KEYS if key not in set(keys)]
        if missing:
            raise ValueError(f"缺分节：{missing}——七节是硬结构，缺节不发残缺卡片")
        return self

    @model_validator(mode="after")
    def _require_unique_state_keys(self) -> "EmitEmergencyActionCardArgs":
        """状态键不得重复：重复的键会让「当前医疗风险是什么」有两个答案。

        允许缺失某个键：契约第 4 节末行明写「`deviation`、`communication`、`sensory_load`
        取 `unknown`（或缺失）时按『未排除』处理」。缺失是一种合法输入，由前端按未排除呈现；
        但同一个键出现两次不是一个「缺失」，是一次自相矛盾。

        Raises:
            ValueError: 状态键重复。
        """
        keys = [state.key for state in self.states]
        if len(set(keys)) != len(keys):
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            raise ValueError(f"状态键重复：{duplicates}——同一个键只能有一个取值")
        return self

    @model_validator(mode="after")
    def _require_annotations_point_inside_the_card(self) -> "EmitEmergencyActionCardArgs":
        """标注的 `line_ref` 必须落在卡片实际存在的行范围内。

        为什么必须查：指向不存在的行意味着一条指不到任何内容的来源标注——它在呈现上
        要么被丢弃（来源信息静默消失，与 `AC-07`「条目必须带来源」同一条纪律），要么被
        错配到另一行（把「家属报告」贴到一条它并不支持的动作上）。两种都不可接受，
        因此显式拒绝。

        Raises:
            ValueError: `line_ref` 超出卡片的总行数。
        """
        total = sum(len(section.lines) for section in self.sections)
        beyond = sorted({annotation.line_ref for annotation in self.annotations if annotation.line_ref > total})
        if beyond:
            raise ValueError(f"标注指向不存在的行：{beyond}——卡片共 {total} 行")
        return self


def _encode_annotation_kind(source: str, confidence: str) -> str:
    """把契约的 `source` + `confidence` 编码进基座信封的单个 `kind` 字段。

    为什么需要编码（本工具唯一一处形状不对称）：契约第 2 节给标注三个字段
    （`line_ref` / `source` / `confidence`），而基座第 7.3 节的信封只有 `{target, kind}`
    两个字段——`kind` 在基座代码里的说明是「标注的种类。词表属产品侧」，即基座留了一个
    产品侧自定义的字符串槽位，但没有留两个。

    三种可选处置与取舍：

    1. 只放 `source`，丢掉 `confidence`——`action-card.md` 第 4 节要求「判断带置信等级」，
       丢掉它会让「AI 推断」与「已确认」在卡片上不可区分，正是那条纪律要防的。
    2. 只放 `confidence`，丢掉 `source`——同样丢一条必需信息。
    3. 编码成一个复合字符串——两条信息都可还原，代价是消费方要知道分隔约定。

    取 3：它是唯一不丢信息的处置。分隔符用 `:`，因为 `source` 与 `confidence` 的取值都是
    `[a-z_]+`，两段都可机械切分且不含分隔符。这不是静默改写：契约第 5 节禁止的是
    「校验失败后把取值改成合法值」，而本函数只在两条取值都已通过枚举校验之后做无损编码
    ——越界的取值根本到不了这里。

    这里如实记一笔：该编码是 T04 的实现裁决，不是设计文档的裁决。契约第 2 节与基座
    第 7.3 节的字段数不一致，上游未给桥接方式（已作为未决问题上报）。若后续裁决要求改形状，
    改的是本函数一处，前端消费方的约定随之更新。
    """
    return f"{source}:{confidence}"


def decode_annotation_kind(kind: str) -> tuple[str, str]:
    """`_encode_annotation_kind` 的逆运算：`"source:confidence"` → `(source, confidence)`。

    提供给消费方（前端与测试）一个可判定的还原口径，而不是让各处自己 `split(":")`——
    分隔约定只有一处定义，改的时候不会漏掉某个消费方。

    Raises:
        ValueError: 字符串不含分隔符，或两段不在各自的词表内（说明该标注不是本工具产出的）。
    """
    source, separator, confidence = kind.partition(":")
    if not separator:
        raise ValueError(f"标注 kind {kind!r} 不是『来源:置信』形态")
    if source not in ANNOTATION_SOURCES:
        raise ValueError(f"标注来源 {source!r} 不在六类词表内")
    if confidence not in ANNOTATION_CONFIDENCES:
        raise ValueError(f"标注置信 {confidence!r} 不在四档词表内")
    return source, confidence


async def emit_emergency_action_card(
    context: ToolContext, args: EmitEmergencyActionCardArgs
) -> ToolResult | ToolFailure:
    """发出一张应急现场行动卡（契约第 1 节）。

    契约真源：docs/技术设计/面/consult/tools/emit_emergency_action_card.md

    事件怎么出去（契约第 1 节「基座把工具返回的卡片翻成 `action_card` 事件下发」）：
    本函数把卡片放进 `ToolResult.cards`，`agent.runtime.assembly` 的 `ToolBridge._invoke`
    在 `tool_call_finished` 之前把它翻成 `ActionCardEvent`。运行不因此结束——
    卡片之后模型可以继续输出追问或收尾文字（与 `question` 走工具即结束运行不对称，
    判据在基座 7.3 节）。

    为什么校验全在参数模型里、本函数不做二次判断（契约第 4、5 节）：

    七节完整性、状态键词表、状态取值词表、标注指向的行范围——四条都是机械判据，
    落在 `args_model` 上意味着越界载荷在 `ToolSpec._parse` 就变成 `tool_invalid_arguments`，
    本函数根本不被调用，`ToolResult` 从不构造，因此不存在「发了一张取值被改写的卡片」
    这条路径（契约第 5 节：不因校验失败而降级）。若把判据写在这里再 return 失败，
    就多了一条「先构造出卡片、再决定要不要发」的路径，而那正是要堵的。

    未登录明确失败（契约第 5 节、`RQ-ACC-01`）：卡片是账号级输出，没有账号不产出。
    它不读任何业务数据，因此这条检查是唯一的运行时前置。

    Returns:
        `ToolResult`：文本是给模型的极简回执，卡片在 `cards` 里（含 `card_id`）。
    """
    payload = context.payload
    account: object | None = None
    if isinstance(payload, dict):
        account = payload.get(ACCOUNT_PAYLOAD_KEY)
    if not isinstance(account, str) or not account.strip():
        return ToolFailure(
            code="tool_failed",
            message=f"缺少登录账号（装配处应在 payload 里提供 {ACCOUNT_PAYLOAD_KEY!r}）——无法发出行动卡",
        )

    # 七节按规范顺序产出（契约第 2 节「按固定顺序」）。参数模型只保证七节齐全各一次，
    # 顺序责任在生产方：基座 `ActionCard.sections` 的说明是「按呈现顺序」，前端的
    # `.action-card` 按它渲染，乱序会让分节渲染错位。乱序不是拒绝条件——契约第 5 节的
    # 失败语义只列「缺节 / 某节为空」，故这里排序而不是报错。
    # 已知边界：`line_ref` 的语义是「按七节顺序摊平后的序号」，模型若按自己给的乱序算它，
    # 排序后标注会指到另一行——契约未定义乱序输入下 `line_ref` 的对应关系（未决事项）。
    card = ActionCard(
        # `card_id` 由服务端生成、不接受模型传入：前端凭它区分新旧卡（重复评估时旧卡标失效，
        # 契约第 6 节）。让模型指定 id 会让两张不同的卡拿到同一个 id，前端的失效判定随之失效。
        card_id=uuid.uuid4().hex,
        title=CARD_TITLE,
        sections=tuple(
            ActionCardSection(key=section.key, heading=section.heading, lines=tuple(section.lines))
            for section in sorted(args.sections, key=lambda section: SECTION_KEYS.index(section.key))
        ),
        states=tuple(ActionCardState(key=state.key, value=state.value) for state in args.states),
        annotations=tuple(
            ActionCardAnnotation(
                target=str(annotation.line_ref),
                kind=_encode_annotation_kind(annotation.source, annotation.confidence),
            )
            for annotation in args.annotations
        ),
    )

    return ToolResult(
        text=json.dumps({"card_id": card.card_id, "state": "emitted"}, ensure_ascii=False),
        cards=(card,),
    )


__all__ = [
    "ACCOUNT_PAYLOAD_KEY",
    "ANNOTATION_CONFIDENCES",
    "ANNOTATION_SOURCES",
    "CARD_TITLE",
    "SECTION_KEYS",
    "STATE_KEYS",
    "STATE_VALUE_TABLE",
    "EmitEmergencyActionCardArgs",
    "decode_annotation_kind",
    "emit_emergency_action_card",
]
