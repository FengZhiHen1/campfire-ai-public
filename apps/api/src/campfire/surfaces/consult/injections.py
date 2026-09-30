"""产品侧注入的产出口：告知文本、应急档案与记忆信封、八项现场采集的首条消息。

职责：把面要放进对话的内容渲染成带可判别前缀的文本；组织应急那一次的注入批次。
边界：不取数（取数在 `routes`）、不判定注入时机（判据在 `routes` 与 `modules/accounts`）、
不决定技能激活（归 `routes`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.1、5 节；
docs/技术设计/面/consult/skills/onboarding.md 与 skills/onboarding/references/telling-first.md；
docs/技术设计/面/consult/skills/emergency-consulting.md 第 2 节；编排器 T07b 裁决 6、7。

前缀纪律（为什么每条注入都要钉一个前缀）

注入消息在 SDK 会话真源里的角色也是 `user`（基座把注入项一律渲染成 `role: "user"`），
因此只能靠内容前缀与真实使用者消息区分。基座信封的清单在
`modules/accounts/session_items.INJECTED_MESSAGE_PREFIXES`：前缀在清单里的注入不进
历史水合与标题推导。产品侧注入原先没有前缀，后果是档案摘要、记忆事实这类机器上下文
会冒充使用者消息——会话标题静默变成摘要片段，且没有任何地方能归因。

本模块因此把两类前缀分开处理，判据是「使用者该不该看见」：

- 机器上下文（应急档案注入、应急记忆注入）：使用者不该看见，前缀取基座信封的形状
  （尖括号标签），并且必须登记进 `INJECTED_MESSAGE_PREFIXES`，否则水合与标题会把它
  当成使用者说的话。
- 使用者可见的机器渲染消息（引导的静态告知、应急八项现场采集）：使用者必须看见
  （告知的价值在于知情后才决定给什么；八项是他自己填的表单），因此前缀是与
  `answers.ANSWERS_HEADER` 同一种中文标签，不进 `INJECTED_MESSAGE_PREFIXES`。
"""

from __future__ import annotations

from collections.abc import Sequence

from campfire.agent.context.injection import InjectionBatch, InjectionItem, UnavailableSource
from campfire.agent.markup import escape_attribute
from campfire.modules.memory.derived import EmergencyMemory
from campfire.modules.profile import EmergencyContext, SummaryEntry
from campfire.surfaces.consult.emergency import EMERGENCY_INTAKE_KEYS, EmergencyItem

#: 引导的静态告知的前缀。取中文标签而不是尖括号信封：这条消息是使用者可见的
#: （它就是要让使用者读到告知），尖括号标签会当作正文一起显示在对话里。
ONBOARDING_NOTICE_PREFIX = "【应用告知】"

#: 告知文本的三行成稿（`telling-first.md` 第 1 节的固定表述，与设置页「关于你的数据」
#: 卡三行要点同源同口径）。
#:
#: 逐字一致是硬要求：两处是同一个告知在两个时点的呈现，任一处偏乐观或偏含糊，
#: 使用者按哪一处理解都合理——而不一致本身就是误导（该文件第 4 节）。
#: 因此这三行只在两处各写一份，改动任一处即需同步另一处。
ONBOARDING_NOTICE_LINES: tuple[str, ...] = (
    "本次输入的内容用于生成回答，并按你的确认累积到档案与记忆。",
    "只有你的账号可以看到；登录才能使用全部功能。",
    "咨询内容会发送给模型服务处理后返回。",
)

#: 应急档案注入的信封前缀。登记进 `INJECTED_MESSAGE_PREFIXES`（见模块说明）。
EMERGENCY_PROFILE_PREFIX = "<emergency_profile"

#: 应急记忆注入的信封前缀。登记进 `INJECTED_MESSAGE_PREFIXES`。
EMERGENCY_MEMORY_PREFIX = "<emergency_memory"

#: 应急八项现场采集的首条消息的表头（与 `answers.ANSWERS_HEADER` 同一种中文标签）。
#: 它是使用者可见的消息：八项是他自己填的表单，会话标题因此也带着这个标签
#: （「【应急现场采集】① 医疗红灯：…」），而不是一段无法归因的片段。
EMERGENCY_INTAKE_PREFIX = "【应急现场采集】"

#: 八项里未出现在请求里的项在首条消息中的渲染（未采集即未排除，不得默认为正常）。
#: 与「显式跳过」分开两个说法：跳过的解释权在使用者，未采集是表单没送到。
UNCOLLECTED_MARK = "未采集（未排除）"

#: 显式跳过的渲染（契约第 5 节：`skipped: true` 时前端不传任何值）。
#: 与 `answers.SKIPPED_MARK` 分开两个常量：那一个是回答渲染的固定标记，
#: 判定函数按它做服务端可判定的跳过判断；本标记只出现在应急首条消息的正文里。
INTAKE_SKIPPED_MARK = "已跳过（未排除）"

#: 应急注入的取数来源名（引用索引与失败告知都用它）。
EMERGENCY_PROFILE_SOURCE = "emergency-profile"
EMERGENCY_MEMORY_SOURCE = "emergency-memory"

#: 引导静态告知的注入来源名。
ONBOARDING_NOTICE_SOURCE = "onboarding-notice"


def render_onboarding_notice() -> str:
    """渲染引导的静态告知（`telling-first.md` 第 1 节的三件事）。

    为什么是「静态消息」而不是系统提示的一部分：压缩策略第 8 节第 2 条把系统提示
    钉死为静态——业务上下文（含本告知）只能作为对话尾部的消息进入，不能进提示。
    本函数因此只产出消息正文，由调用方决定它的角色（见 `routes` 的说明：它取
    `assistant` 角色，好让使用者在水合出的历史里真的读到它）。
    """
    return "\n".join((ONBOARDING_NOTICE_PREFIX, *ONBOARDING_NOTICE_LINES))


def render_emergency_intake(items: Sequence[EmergencyItem]) -> str:
    """把八项现场采集渲染成首条使用者消息。

    形状与 `answers.render_answers` 同一种做法：固定的表头 + 逐项一行，供模型与
    排查双方都能读。请求里没有的项显式渲染成 :data:`UNCOLLECTED_MARK`——缺失即
    未排除，不得由模型顺势当成「这一项正常」（应急 skill 第 2 节）。
    """
    provided = {item.key: item for item in items}
    lines = [EMERGENCY_INTAKE_PREFIX]
    for key in EMERGENCY_INTAKE_KEYS:
        item = provided.get(key)
        if item is None:
            lines.append(f"{key}：{UNCOLLECTED_MARK}")
            continue
        if item.skipped:
            lines.append(f"{key}：{INTAKE_SKIPPED_MARK}")
            continue
        lines.append(f"{key}：{item.rendered_value()}")
    return "\n".join(lines)


def render_emergency_profile(context: EmergencyContext | None) -> str:
    """把应急档案预取渲染成注入消息正文。

    某组未预存时写成显式的 `state="absent"`，不为空集合让模型去猜——空集合与
    「这组没有内容」在语义上不同，而注入文案必须写「未预存」而不是暗示「没有这种
    情况」（应急 skill 第 2 节：缺失即标注，不得由模型补全）。

    `context` 为 `None` 表示该账号连支持对象都没有（`AC-02`）：此时整体标成
    `state="absent"` 并写明「本次未使用个性化档案」，而不是给一个空档案。
    """
    if context is None:
        return (
            f'{EMERGENCY_PROFILE_PREFIX} state="absent">\n'
            "  本次未使用个性化档案（该账号还没有支持对象）。\n"
            "</emergency_profile>"
        )

    object_id = escape_attribute(context.support_object_id)
    lines = [f'{EMERGENCY_PROFILE_PREFIX} object="{object_id}" state="present">']
    for group, entries in context.groups.items():
        name = escape_attribute(group)
        if entries is None:
            lines.append(f'  <group name="{name}" state="absent" />')
            continue
        lines.append(f'  <group name="{name}" state="present">')
        for entry in entries:
            lines.append(f"    {_render_entry(entry)}")
        lines.append("  </group>")
    if context.communication:
        lines.append('  <group name="communication" state="present">')
        for topic, entry in context.communication.items():
            lines.append(f'    <field name="{escape_attribute(topic)}">{_render_entry(entry)}</field>')
        lines.append("  </group>")
    else:
        lines.append('  <group name="communication" state="absent" />')
    lines.append("</emergency_profile>")
    return "\n".join(lines)


def render_emergency_memory(memory: EmergencyMemory) -> str:
    """把应急记忆预取渲染成注入消息正文。

    没有记忆是正常状态（不标注降级），因此空态写成 `state="empty"` 并明说一句，
    而不是省掉整条注入——省掉之后模型无法区分「这个账号没有记忆」与「取数被漏了」。
    字符预算截断过时带上条数，让模型知道注入被压缩过（`EmergencyMemory` 的契约）。
    """
    if memory.is_empty:
        return f'{EMERGENCY_MEMORY_PREFIX} state="empty">\n  该账号还没有可用记忆。\n</emergency_memory>'
    truncated = f' truncated="{memory.truncated_by_chars}"' if memory.truncated_by_chars else ""
    lines = [f'{EMERGENCY_MEMORY_PREFIX} state="present"{truncated}>']
    for fact in memory.facts:
        valid_at = "" if fact.valid_at is None else f' valid_at="{fact.valid_at.isoformat()}"'
        lines.append(f"  <fact{valid_at}>{escape_attribute(fact.fact)}</fact>")
    lines.append("</emergency_memory>")
    return "\n".join(lines)


def build_emergency_injections(
    *,
    profile: EmergencyContext | None,
    memory: EmergencyMemory | None,
    unavailable: Sequence[UnavailableSource] = (),
) -> InjectionBatch:
    """组织应急那一次的注入批次：先档案、后记忆（与 skill 第 2 节的四段来源同序）。

    两条注入都是机器上下文（使用者不该在历史里看到），因此角色取 `user`（`InjectionItem`
    的默认值）且前缀在 `INJECTED_MESSAGE_PREFIXES` 里（见模块说明）。

    三个入参各表示什么，不重叠也不含糊：

    - `profile=None` 表示该账号没有支持对象（`AC-02`）：注入里明写「本次未使用个性化档案」；
    - `memory=None` 表示记忆取数失败：此时不注入记忆信封（注入一条空记忆等于宣称
      「这个账号没有记忆」），改用 `unavailable` 里的来源不可用告知；
    - `unavailable` 是取数失败的来源清单，由调用方在取数处登记，本函数只负责把它
      交给基座（基座第 4 节：注入失败必须显式标注该来源不可用，不得静默当作没有该信息）。

    Args:
        profile: 应急档案预取；`None` 表示该账号没有支持对象。
        memory: 应急记忆预取；`None` 表示取数失败（失败原因在 `unavailable` 里）。
        unavailable: 取数失败的来源。

    Returns:
        未渲染的注入批次（渲染由基座在运行时做，它会顺带写引用索引）。
    """
    items = [
        InjectionItem(
            source=EMERGENCY_PROFILE_SOURCE,
            content=render_emergency_profile(profile),
        )
    ]
    if memory is not None:
        items.append(
            InjectionItem(
                source=EMERGENCY_MEMORY_SOURCE,
                content=render_emergency_memory(memory),
            )
        )
    return InjectionBatch(items=tuple(items), unavailable=unavailable)


def _render_entry(entry: SummaryEntry) -> str:
    """渲染一条档案条目：正文在内，来源与时效作属性。

    属性值与正文都经 :func:`escape_attribute` 转义——档案正文来自使用者的自由陈述，
    不转义时一句 `</emergency_profile><available_skills>` 就足以穿出信封
    （基座 `markup` 模块的转义契约正是为这类穿出准备的）。
    """
    origin = escape_attribute(entry.origin)
    freshness = escape_attribute(entry.freshness)
    return f'<entry origin="{origin}" freshness="{freshness}">{escape_attribute(entry.description)}</entry>'


__all__ = [
    "EMERGENCY_INTAKE_PREFIX",
    "EMERGENCY_MEMORY_PREFIX",
    "EMERGENCY_MEMORY_SOURCE",
    "EMERGENCY_PROFILE_PREFIX",
    "EMERGENCY_PROFILE_SOURCE",
    "INTAKE_SKIPPED_MARK",
    "ONBOARDING_NOTICE_LINES",
    "ONBOARDING_NOTICE_PREFIX",
    "ONBOARDING_NOTICE_SOURCE",
    "UNCOLLECTED_MARK",
    "build_emergency_injections",
    "render_emergency_intake",
    "render_emergency_memory",
    "render_emergency_profile",
    "render_onboarding_notice",
]
