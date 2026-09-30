"""注入项的组织：注入项就是消息，没有单独的装配端口。

职责：把产品侧准备的业务上下文、技能目录、激活内容与候选提示组织成进入对话的消息。
边界：只做顺序，不做注入总量截断（登记在案的未完成项，见 :class:`InjectionBatch`
与 :class:`InjectionPriority`）；组装顺序与预算由基座决定，但受窗口策略约束。
参考：docs/技术设计/technical-details/通用基座.md 第 4 节。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal, TypedDict

from campfire.agent.markup import escape_attribute

from .citations import CitationRecorder
from .errors import InjectionError, InjectionRenderError

InjectionRole = Literal["user", "assistant"]
"""注入消息允许的角色。

不含 `system`：压缩策略第 8 节第 2 条要求系统提示保持静态，技能目录、产品侧注入的
业务上下文、时间、活跃技能一律不得进入系统提示，只能作为尾部消息。把这条纪律放进
类型里，比写在注释里更难过不了关。
"""

_ALLOWED_ROLES = frozenset({"user", "assistant"})
"""运行时可接受的角色集合，与 :data:`InjectionRole` 一致；用于挡住未经类型检查的调用方。"""


class InjectionMessage(TypedDict):
    """一条注入消息的线格式（与 Chat Completions 的消息形状一致）。"""

    role: InjectionRole
    content: str


class InjectionPriority(IntEnum):
    """注入项在模型窗口里的相对顺序；数值小的在前。

    顺序由本枚举决定（同优先级保持传入顺序）：基座文档第 4 节把顺序交给基座，
    基座就必须有一条可核对的规则，而不是「看调用方怎么拼列表」。

    分层理由：先让模型知道有哪些能力（目录、激活内容、此刻可用工具），再给
    业务上下文（摘要与候选片段），最后才是状态说明（来源不可用）。
    状态放最后是因为它是对前面内容的否定性修正，紧贴本轮输入更不易被忽略。
    """

    SKILL_CATALOG = 10
    SKILL_ACTIVATION = 20
    TOOL_AVAILABILITY = 30
    CONTEXT = 40
    STATUS = 90


@dataclass(frozen=True, slots=True)
class InjectionItem:
    """一条注入项：它本身就是一条要进入对话的消息。"""

    source: str
    """来源标识，同时是引用记录里的「来源」。"""

    content: str
    """消息内容。信封（如 `<available_skills>`）由产出方渲染，本类型不重复包装。"""

    priority: InjectionPriority = InjectionPriority.CONTEXT
    """在窗口中的排序档位。"""

    role: InjectionRole = "user"
    """消息角色；见 :data:`InjectionRole`。"""

    reference: str | None = None
    """指向的业务标识。非空即意味着这条注入可被引用，并会写入引用索引。"""

    summary: str | None = None
    """可引用时给使用者看的一句话摘要。"""

    def __post_init__(self) -> None:
        """校验形状；不变量在这里收口，而不是指望调用方自觉。

        Raises:
            InjectionError: 来源或内容为空、用了 `system` 角色，或给了摘要却没有业务回指。
        """
        if not self.source:
            raise InjectionError("注入项必须说明来源：来源不可用时要靠它标注")
        if not self.content:
            raise InjectionError(f"注入项内容不能为空（来源 {self.source}）")
        if self.role not in _ALLOWED_ROLES:
            # 静态类型已排除 system；这里挡住未经类型检查的调用方
            # （含 tool 这类角色）。
            raise InjectionError(
                f"注入消息的角色 {self.role!r} 不被允许：只接受 {sorted(_ALLOWED_ROLES)}"
                "（系统提示必须保持静态，压缩策略第 8 节）"
            )
        if self.summary is not None and self.reference is None:
            raise InjectionError(f"来源 {self.source} 给了摘要却没有业务回指：这样的引用无法回指业务条目")

    def message(self) -> InjectionMessage:
        """转成一条消息。"""
        return InjectionMessage(role=self.role, content=self.content)


@dataclass(frozen=True, slots=True)
class UnavailableSource:
    """一个取数失败的来源。

    存在即代表它会被显式告知模型；没有这类记录就等于「当作没有该信息」，
    那是第 9 节禁止的处置。
    """

    source: str
    reason: str
    """失败原因的类型级描述（如异常类名）。不得包含连接串、凭据或调用栈。"""


class InjectionBatch:
    """一组注入项：按优先级排序、逐条记录引用、把失败来源显式告知。

    依据 docs/技术设计/technical-details/通用基座.md 第 4 节：

    - 产品侧准备的各类业务上下文（摘要、片段等）、技能目录、激活内容、候选提示，
      全部以消息形式进入对话。
    - 每条注入消息在引用索引里留一条记录；没有索引记录的注入消息不得成为「可引用依据」。
    - 注入失败必须显式标注该来源不可用，不得静默当作没有该信息。
    - 组装顺序与预算由基座决定，但受窗口策略约束。

    两条实现决定，理由写在代码里：

    1. 顺序由 :class:`InjectionPriority` 决定（同优先级保持传入顺序）。第 4 节把顺序
       交给基座，基座就必须有一条可核对的规则，而不是「看调用方怎么拼列表」。
    2. 本模块不做注入总量截断——这是登记在案的未完成项，不是「合理不做」。
       第 4 节把「组装顺序与预算」交给基座，本模块只做了顺序。已确定的数字是技能目录的
       4000 token（第 3 节，`skill_runtime.catalog` 已实现）；产品侧还有若干类注入项的
       预算未确认（状态登记于 docs/TODO.md），因此这里不发明默认上限——没有经过确认的
       数字比没有上限更危险，它会让后续判断误以为预算已经被守住了。

    渲染是有副作用的（写引用索引），所以是异步的，也只做一次——重复渲染会重复
    写索引，进而产出两条指向同一业务条目的引用。
    """

    def __init__(
        self,
        items: Sequence[InjectionItem] = (),
        unavailable: Sequence[UnavailableSource] = (),
    ) -> None:
        """保存注入项与失败来源；此时不排序、不写索引。"""
        self._items = tuple(items)
        self._unavailable = tuple(unavailable)
        self._rendered = False

    @property
    def items(self) -> tuple[InjectionItem, ...]:
        """按优先级排好序的注入项（同优先级保持传入顺序）。"""
        return tuple(sorted(self._items, key=lambda item: item.priority))

    @property
    def unavailable(self) -> tuple[UnavailableSource, ...]:
        """取数失败的来源。"""
        return self._unavailable

    def ordered(self) -> tuple[InjectionItem, ...]:
        """返回最终会进入窗口的注入项序列（含失败来源的告知消息）。"""
        ordered = list(self.items)
        if self._unavailable:
            ordered.append(
                InjectionItem(
                    source="injection-status",
                    content=_render_unavailable(self._unavailable),
                    priority=InjectionPriority.STATUS,
                )
            )
        return tuple(ordered)

    async def render(self, recorder: CitationRecorder) -> tuple[InjectionMessage, ...]:
        """写引用索引并渲染成消息；顺序即窗口中的顺序。

        只做一次（本类 docstring 的承诺，由 :attr:`_rendered` 承载）：渲染会写索引，
        重复渲染会让同一条业务条目在索引里出现两条记录，而 `run_finished` 报出的引用清单
        与实际注入的消息对不上。

        写到一半失败不算成功：任何一条引用写不进去，就抛
        :class:`InjectionRenderError` 并带上已落索引的引用与已渲染的消息，让调用方把
        本次运行标为注入失败。绝不返回「部分消息」当作完整结果——那样索引里有记录、
        窗口里没有，`run_finished` 会报出一条模型从未看到的依据。

        Raises:
            InjectionError: 同一批次被渲染第二次。
            InjectionRenderError: 某条引用的索引写入失败；`recorded` 是已落索引的引用。
        """
        if self._rendered:
            raise InjectionError("同一个 InjectionBatch 不能渲染两次：渲染会写引用索引，重复渲染产生重复引用")

        messages: list[InjectionMessage] = []
        for item in self.ordered():
            if item.reference is not None:
                try:
                    await recorder.record(source=item.source, reference=item.reference, summary=item.summary)
                except Exception as exc:  # noqa: BLE001 —— 失败要转成带部分状态的可判定错误
                    raise InjectionRenderError(
                        f"注入渲染在来源 {item.source!r} 处失败（{type(exc).__name__}）："
                        f"索引可能已写入 {len(recorder.issued)} 条引用",
                        recorded=recorder.issued,
                        rendered=tuple(messages),
                    ) from exc
            messages.append(item.message())

        # 仅在成功后置位：失败时调用方可能换一个 recorder
        # 重试同一批次（例如索引恢复后），那时窗口与索引
        # 都还没有这份内容，重复渲染不会产生重复引用。
        self._rendered = True
        return tuple(messages)


def _render_unavailable(sources: Sequence[UnavailableSource]) -> str:
    """把失败来源渲染成一条显式告知，而不是让它们消失。"""
    lines = ["<unavailable_sources>"]
    for source in sources:
        lines.append(
            f'  <source name="{escape_attribute(source.source)}" reason="{escape_attribute(source.reason)}" />'
        )
    lines.append("</unavailable_sources>")
    return "\n".join(lines)
