"""把本轮的引用凭据编成 `annotations`，挂在落库前的助手正文分片上。

职责：声明引用注解的键与形状（编解码），并提供 :class:`CitationAnnotatingSession`
——一个在 `add_items` **落库之前**给内存中待写的条目挂注解的会话包装。
边界：不写数据库、不改已落库的行、不新建会话类型；真源仍是 SDK 的会话存储。
参考：docs/技术设计/technical-details/通用基座.md 第 4 节。

**为什么需要这份载荷**（本模块存在的理由）：

设计第 5 节的不变量是「citation part 与所属消息**同生命周期**……因为它是消息 content
的一部分，**不是外部索引**」。而会话存储只认 SDK 自己那几种条目形状——实测把
`{"type": "citation", …}` 当作独立条目交给模型输入转换器会抛
`Unhandled item type or structure`。
⇒ **载荷必须搭在一次 SDK 本来就会落库的条目上**，而不能自己造一种条目。

**为什么选助手正文分片（`output_text` 的 `annotations`）**：

1. **它字面满足第 5 节**：`annotations` 是助手**消息 content 的一部分**，
   不是外挂索引，也不是另一条会话条目；
2. **它对模型不可见**：本仓用的是 Chat Completions 模型（`OpenAIChatCompletionsModel`），
   其输入转换器读 `content` 时**只取 `text`**（`chatcmpl_converter.py:746-747`），
   `annotations` 整段被忽略——实测带注解与不带注解的转换结果**逐字节相同**；
3. **锚是天然存在的**：助手正文分片本来就是 `output_text`，`annotations` 是它自己的字段，
   不需要另造对应关系。

**载荷长什么样**：一条引用一个注解对象，除六个业务字段外多一个判别键 `type`：

```json
{"type": "citation", "citation_id": "…", "run_id": "…", "source": "knowledge",
 "reference": "knowledge:…", "recorded_at": "…", "summary": null}
```

`type` 是**判别键**：真实的辅助注解（例如 `url_citation`）也住在同一个数组里，
按判别键取值才不会把别家的注解当成本项目的引用。六个业务字段与
`agent/context/citations.py` 的 `CitationRecord` 逐字相同，也与面侧
`CitationEvent.citation` 同形——这是「水合出来的载荷与事件流一致」的依据。

**为什么包装会话是可行的**（三条已实测的事实，缺任一条这条路都不成立）：

1. 会话工厂是**注入的、可替换的**（`SessionFactory = Callable[[str], Session]`）；
2. SDK 落库助手消息的唯一通路是 `session.add_items(items)`
   （`run_internal/session_persistence.py:714` → `:234`）；
3. `SQLAlchemySession.add_items` 只**逐个序列化**传进来的 items，不校验、不重写
   （`extensions/memory/sqlalchemy_session.py:370-386`），且它会 `json.dumps`
   ⇒ **到达 `add_items` 的条目是普通 dict**，就地改它不需要任何解析器。

**⇒ 因此「`Session` 协议是只追加的」逐字未破**：包装层改的是**尚未落库**的内存对象，
落库仍由 SDK 自己的 `add_items` 完成 ⇒ **没有已落库的行被包装层修改**。

⚠ **措辞精确化（这是实测纠正的一句话，别读成上一版那样）**：上一版这里写着
「**没有一条 UPDATE**」——**按字面读与实测相反**。复查者用 SQLAlchemy 的
`before_cursor_execute` 钩子在真 PG 上逐条记录语句，读数：

- **包装层自己不发出任何 SQL**；语句集合与不包装时**逐条同形同序**（这一条成立）；
- 但那组语句里**确实有一条 UPDATE**：`UPDATE agent_sessions SET updated_at=…`，
  它是 **SDK 自己**在 `add_items` 里对会话行的 touch，**基线（不包装）同样有**。

⇒ 准确说法是「**包装层不发 UPDATE；SDK 自身仍会 touch `agent_sessions.updated_at`**」。
两条读数的差别是**谁发的**，不是**有没有**——而"只追加"这条不变量约束的是
**历史条目**（`agent_messages` 只增不改），SDK 的会话元数据 touch 不属于历史条目。
（这一点可实测：本模块不 import 任何数据库设施，见文件头的 import。）

**与另一条候选通道的关系（如实订正一句曾写错的断言）**：

曾经有一份说明写着「经支持接口**唯一**可达的通道是工具结果文本」——**这句话是错的**，
本模块就是反例：包装会话工厂是另一条可达通道，且它在「字面满足第 5 节」与
「载荷对模型不可见」两点上都更强。工具结果文本那条路**仍然可用**，
但走它的理由**不是「没有别的路」**，而是**那里的锚是天然的 1:1**
（`function_call_output.call_id` 与那次调用一一对应，不需要另判「该挂到哪条消息」）。
代价是工具结果文本是**模型读得到的输入**，载荷会对模型可见——本模块换掉的正是这一点。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

from agents.items import TResponseInputItem
from agents.memory.session import Session
from agents.memory.session_settings import SessionSettings

from ..context.citations import CitationRecord, CitationRecorder

logger = logging.getLogger(__name__)

#: 一条助手正文分片上**最多**挂多少条引用注解（**写侧的强制上界**）。
#:
#: ★ **本模块上一版的一处真实缺陷就出在这里**：读侧有 20 条硬截断，而写侧
#: **没有任何上界** ⇒ 一次运行里多次取数、累计超过 20 条时，读侧会**静默丢掉**
#: 第 21 条起（复查者实测端到端：写 45 → 水合 20，丢 25 条、**零日志**）。
#: 那直接违反本载体的不变量「只凭会话条目重建出与事件流一致的引用载荷」。
#: ⇒ 现在**两侧共用同一个值，且写侧先裁**：写进去的每一条都读得回来。
#:
#: 取值理由（不是拍的）：单次取数最多发 `MAX_RESULT_LIMIT = 20` 条（产品侧的工具实现），
#: 而一次运行可以取多次。取 **200 = 10 次满额**，远高于实测到的任何一轮
#: （真实 E2E 最多 12 条）⇒ **正常路径碰不到它**；它的作用是兜住
#: 「病态运行」与「被伪造的条目」的有界性（CORE-11）。
#:
#: ⚠ **裁剪时必须留日志**（见 :meth:`CitationAnnotatingSession._pending`）：
#: 静默截断正是本缺陷的形态，换成一个更大的数字继续静默截断等于没修。
#: 与读侧 `modules/accounts/session_items.py` 的同名常量**必须相等**，
#: 由用例**真的比对这两个常量**守住——上一版那条用例只把读侧常量与字面量 `20` 比对，
#: **守错了量**（写侧当时根本没有可比的常量）。
CITATION_ANNOTATION_MAX: int = 200

#: 引用注解的判别键取值。与线格式的 `citation` part 类型同名——三处
#: （注解、part、事件）指同一批数据，用同一个词。
CITATION_ANNOTATION_TYPE: str = "citation"

#: 助手正文分片的类型。只有它带 `annotations`（`output_text` 是助手产出文本的分片类型）。
OUTPUT_TEXT_PART_TYPE: str = "output_text"

#: 一条注解里承载业务回指的键。缺它就指不到东西，读侧据此丢弃该条。
ANNOTATION_REFERENCE_KEY: str = "reference"

#: 一条注解的必填键（缺任一即丢弃该条）。与读侧
#: （`modules/accounts/session_items.py` 的引用重建）同一份必填集：
#: `citation_id` 是回指键、`source` 说不清出处就不该呈现为依据、`reference` 指向业务条目。
REQUIRED_ANNOTATION_KEYS: tuple[str, ...] = ("citation_id", "source", ANNOTATION_REFERENCE_KEY)


def citation_annotation(record: CitationRecord) -> dict[str, object]:
    """把一条引用凭据编成注解对象。

    `recorded_at` 转 ISO 8601 字符串：注解要成为 JSON 的一部分（会话条目是 JSON 文本），
    而前端 `CitationRecord.recorded_at` 本来就是字符串 ⇒ 转字符串才是与既有线格式一致的做法。
    """
    return {
        "type": CITATION_ANNOTATION_TYPE,
        "citation_id": record.citation_id,
        "run_id": record.run_id,
        "source": record.source,
        "reference": record.reference,
        "recorded_at": record.recorded_at.isoformat(),
        "summary": record.summary,
    }


def citation_annotations(records: Sequence[CitationRecord]) -> list[dict[str, object]]:
    """把若干条引用凭据编成注解数组（可直接作为 `output_text` 的 `annotations` 值）。"""
    return [citation_annotation(record) for record in records]


class CitationAnnotatingSession:
    """会话包装：落库前给助手正文分片挂上本轮尚未挂出的引用注解。

    它是一个**纯装饰器**——四个协议方法全部原样转发给被包装的会话，
    唯一多做的事是在 `add_items` 里改写**尚未落库**的那几个 dict。

    为什么改的是**副本**而不是原对象：传给 `add_items` 的 items 同时还是 SDK 侧
    运行状态里的对象（下一轮会被再次读作模型输入、并参与去重指纹）。就地改它们会让
    「落库的形状」与「运行中的形状」互相牵动；改副本则把影响面**限制在这一条落库路径内**。
    """

    def __init__(self, inner: Session, recorder: CitationRecorder) -> None:
        """绑定被包装的会话与本次运行的引用写入端。

        Args:
            inner: 真正落库的会话（由装配处的会话工厂造出）。
            recorder: 本次运行的引用写入端。`issued` 是「本轮已写入索引的凭据，按写入顺序」。
        """
        self._inner = inner
        self._recorder = recorder
        #: 会话标识与设置：按 `Session` 协议的要求作为**可写属性**存在（写成只读
        #: property 不满足协议的可写成员，mypy 会报「expected settable variable」），
        #: 值一律转发给被包装的会话。
        self.session_id: str = inner.session_id
        self.session_settings: SessionSettings | None = getattr(inner, "session_settings", None)
        #: 已经挂进某条落库助手消息的引用标识。**防重复**：一次运行会有多条助手消息
        #: （每轮一条），累计式挂载会让同一条引用出现在多条消息里 ⇒ 水合出重复的
        #: 「依据」。这里按标识去重，保证每条引用只随**第一条**产出正文的助手消息落库。
        self._attached: set[str] = set()

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        """读回会话条目（转发；读路径不需要任何加工）。"""
        return await self._inner.get_items(limit)

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        """挂注解后落库。

        ★ 「该给这条助手消息挂哪些引用？」的判据（**增量式，不是累计式**）：

        对批次里每一条助手消息的每个正文分片，挂上**此刻已经写入索引、但还没有挂出去**
        的那些引用，然后按标识记账。

        - **为什么不是「本轮全部」**：一次运行可能有多条助手消息（每轮一条正文），
          累计式会让第一轮就已挂出的引用在后续消息里**再挂一次** ⇒ 刷新后同一批依据
          出现两遍。实测库行形状里，同一会话确实存在「多轮工具调用 + 每轮都有产出」的组合。
        - **为什么增量式在时序上成立**：引用凭据在**工具执行**时产生，而 SDK 的落库发生在
          **一个回合跑完之后**（`run_loop.py` 的 `NextStepRunAgain` / `NextStepFinalOutput`
          分支调用 `save_result_to_session`）。⇒ `add_items` 被调用的那一刻，
          **该回合里工具已发出的引用一定已经在 `recorder.issued` 里**。
        - **本轮没有正文的回合**：引用不会被丢掉，而是留在「尚未挂出」里，
          随**下一次**产出正文的助手消息落库（实测：真实运行里可以出现
          「只有思考 + 工具调用、没有正文」的回合，正文在后续回合才出现）。

        **已知代价（如实写明，不藏）**：若一次运行**产生了引用却从未产出任何助手正文**，
        那批引用不会进会话（没有可挂的锚）。方向是安全的（少一条依据，不会多一条），
        但它确实是本载体的边界，见模块 docstring 与交付报告的证据边界。
        """
        used: list[str] = []
        annotated = [self._annotate(item, used) for item in items]
        # ★ 记账排在**写成功之后**：`add_items` 抛错时本次运行以 `session_write_failed`
        # 收场，而那批引用并没有落库。若提前记账，SDK 的重试路径再次提交同一批条目时
        # 就会被判成「已经挂过」 ⇒ 唯一那条本该带上依据的助手消息**永久失去**注解。
        # 排在成功之后则重试可重挂，而正常路径（写成功）行为完全不变。
        await self._inner.add_items(annotated)
        self._attached.update(used)

    async def pop_item(self) -> TResponseInputItem | None:
        """弹出最后一条条目（转发）。"""
        return await self._inner.pop_item()

    async def clear_session(self) -> None:
        """清空会话（转发）。"""
        await self._inner.clear_session()

    def _pending(self, used: Sequence[str]) -> list[CitationRecord]:
        """此刻已写入索引、但还没有挂进任何助手消息的引用（按写入顺序）。

        `used` 是**同一批次内**已经挂出去的标识：一个批次里可能有多条助手消息，
        而 `self._attached` 要等整批写成功之后才更新（见 `add_items`）——
        不看 `used` 的话，同一批里的第二条助手消息会把同一批引用再挂一遍。

        ⚠ 这里**不做上界裁剪**：上界要按「分片上已有的注解数」算（真实的辅助注解与我们
        共用那个数组、也占额度），因此裁剪发生在 :meth:`_annotate` 里。
        """
        taken = set(used)
        return [
            record
            for record in self._recorder.issued
            if record.citation_id not in self._attached and record.citation_id not in taken
        ]

    def _annotate(self, item: TResponseInputItem, used: list[str]) -> TResponseInputItem:
        """给一条条目挂注解；不需要挂时**原样返回同一个对象**（零改动）。

        挂出去的引用标识追加进 `used`（**由调用方在写成功之后才记账**，见 `add_items`）。

        判据全部按**结构**（dict 的键与值）而不是按类型断言：到达 `add_items` 的条目
        实测是普通 dict（`SQLAlchemySession` 会对它 `json.dumps`），但 SDK 的公开类型
        允许 `BaseModel` 等形状；认不出的形状一律原样放行，**不猜、不改**。
        """
        if not isinstance(item, dict):
            return item
        if item.get("role") != "assistant":
            return item
        pending = self._pending(used)
        if not pending:
            return item
        content = item.get("content")
        if not isinstance(content, list):
            return item

        # ★ 只挂到**第一个**正文分片上（不是每个）：
        # 一条助手消息若有多个 `output_text` 分片，逐片都挂会让**同一条引用出现多次**
        # （读侧会挨个分片读、没有跨分片去重）⇒ 刷新后「依据 N 条」里出现重复项。
        # 挂第一个分片既满足「载荷是消息 content 的一部分」，又让每条引用在一条消息里
        # **恰好出现一次**（与 `_attached` 的记账合起来保证全局也恰好一次）。
        target: int | None = None
        for index, candidate in enumerate(content):
            if isinstance(candidate, dict) and candidate.get("type") == OUTPUT_TEXT_PART_TYPE:
                target = index
                break
        if target is None:
            # 批次里的助手消息一个正文分片都没有（纯工具调用的回合）：不挂、不记账。
            # 引用要留到**下一次**产出正文的回合，因此这里返回原对象即可
            # （`_attached` 没变，`_pending()` 里那些引用仍然待挂）。
            return item

        # `target` 的挑选条件（`isinstance(candidate, dict)` + 类型等于 `output_text`）
        # 已保证它是一个 dict；这里显式收窄而不是断言，好让 mypy 也看得见。
        part = cast(dict[str, Any], content[target])
        existing = part.get("annotations")
        existing_list: list[Any] = list(existing) if isinstance(existing, list) else []
        # ★ 上界按**合并后**的数组算：读侧读的是整个 `annotations` 数组，
        # 而真实的辅助注解（`url_citation` 等）与我们共用它、也要占额度。
        # 只算自己那部分的话，`existing + 我们` 仍可能超过读侧上界 ⇒ 读侧照样会丢。
        room = CITATION_ANNOTATION_MAX - len(existing_list)
        if room <= 0:
            logger.warning(
                "该助手正文分片的注解数已达上界（%d 条），本批 %d 条引用挂不上；它们会留到下一次产出正文时再挂：%s",
                CITATION_ANNOTATION_MAX,
                len(pending),
                [record.citation_id for record in pending][:5],
            )
            return item
        attach = pending if len(pending) <= room else pending[:room]
        if len(attach) < len(pending):
            # ★ **不静默**：静默截断正是本模块上一版的缺陷形态。
            # 超出的那些**不记账** ⇒ 留到后续正文继续尝试（方向安全：不丢，只是延后）。
            logger.warning(
                "引用注解超出单分片上界（%d 条）：本批 %d 条中挂 %d 条，其余 %d 条延后：%s",
                CITATION_ANNOTATION_MAX,
                len(pending),
                len(attach),
                len(pending) - len(attach),
                [record.citation_id for record in pending[len(attach) :]][:5],
            )

        new_part = dict(part)
        new_part["annotations"] = [*existing_list, *citation_annotations(attach)]
        new_content: list[Any] = list(content)
        new_content[target] = new_part

        used.extend(record.citation_id for record in attach)
        # 顶层只换掉 content：其余字段（id / role / status / type / provider_data）逐字保留。
        # `cast` 的理由：`dict(item)` 会把 TypedDict 联合退化成 `dict[str, object]`，
        # 而这里改的是**同一批键**、值的类型也未变（`content` 仍是分片数组）。
        new_item = dict(item)
        new_item["content"] = new_content
        return cast(TResponseInputItem, new_item)


__all__ = [
    "ANNOTATION_REFERENCE_KEY",
    "CITATION_ANNOTATION_MAX",
    "CITATION_ANNOTATION_TYPE",
    "OUTPUT_TEXT_PART_TYPE",
    "REQUIRED_ANNOTATION_KEYS",
    "CitationAnnotatingSession",
    "citation_annotation",
    "citation_annotations",
]
