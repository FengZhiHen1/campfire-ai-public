"""工具产出里两种结构化载荷的形状：提问批次与卡片信封。

职责：定义工具经 :class:`~campfire.agent.tools.ToolResult` 交回、由运行编排翻成事件的载荷。
边界：只承载与领域无关的形状，不含任何领域词表（基座第 1 节不变量）；词表与其校验归产品侧。
参考：docs/技术设计/technical-details/通用基座.md 第 7.2、7.3 节。
"""

# 为什么载荷形状放在 `tools/` 而不是 `runtime/events.py`：
#
# 事件类与工具结果两边都要用它们，而 `agent.runtime` 已经 import `agent.tools`
# （事件类用 `Candidate`、`ToolErrorCode`），反过来 import 就是环。两个形状的归属地
# 因此只能是 tools 一侧——与 :class:`~campfire.agent.tools.results.Candidate` 同一种安排。
#
# 字段名逐字对齐基座第 7.2、7.3 节，一个字都不改：面侧 HTTP/SSE 契约
# （docs/技术设计/面/consult/HTTP与SSE契约.md）第 4.2 节把事件的 `data` 定义成
# 「该事件对象的 JSON」（恒等映射），所以这些键名就是线上契约。改名、缩写与
# 「更顺手的聚合」都会把契约改掉。
#
# 为什么这里不做字段级校验、而把校验放在 __post_init__ 里：载荷是工具与运行编排之间的值
# 对象，进入事件有两条路径——模型给的载荷过工具的参数模型（`ask_user` 的 args），运行编排
# 发出的载荷直接构造事件类。把约束写在 `__post_init__` 里，两条路径共用同一份定义：
# pydantic 会把 dataclass 抛出的 ValueError 收成正常的校验错误（实测 loc 落在 `items.0`
# 这样的路径上），事件构造点则直接得到 ValueError。若改成在工具 args 上重写一遍约束，
# 同一形状就有了两处定义，迟早漂移——而漂移方向恰好是最坏的：事件侧放行了工具侧拒绝的载荷。

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuestionOption:
    """一道题的一个选项；基座 7.2 节 `options` 的元素。"""

    label: str
    """选项文案。使用者看到的就是它，回答也以它或自由文本回传（契约第 4.1 节）。"""

    description: str | None = None
    """选项说明；可为空（基座写 `string?`）。"""

    def __post_init__(self) -> None:
        """选项文案必须有值：没有文案的选项在界面上是一个点不动的空按钮。

        Raises:
            ValueError: `label` 为空或只有空白。
        """
        if not self.label.strip():
            raise ValueError("选项文案 label 不能为空")


@dataclass(frozen=True, slots=True)
class QuestionItem:
    """一组题里的一道题；基座 7.2 节 `items` 的元素。"""

    id: str
    """题标识：批次内唯一，回答回传时凭它关联（基座 7.2 节）。"""

    prompt: str
    """题干。"""

    options: tuple[QuestionOption, ...] = ()
    """可为空：空元组的含义是纯自由回答的题（基座 7.2 节）。"""

    allow_skip: bool = False
    """该题是否允许跳过（基座 7.2 节）。"""

    def __post_init__(self) -> None:
        """核实题标识与题干有值。

        Raises:
            ValueError: `id` 或 `prompt` 为空/只有空白。题标识为空会让回答无从关联；
                题干为空则使用者看到的是一张没有问题的卡片。
        """
        if not self.id.strip():
            raise ValueError("题标识 id 不能为空")
        if not self.prompt.strip():
            raise ValueError("题干 prompt 不能为空")


@dataclass(frozen=True, slots=True)
class Question:
    """一组提问的载荷；基座 7.2 节的 `batch_id` 加 `items`。

    单独成形而不是直接摊在事件类上，是因为工具（`tools`）不能 import 事件类
    （`runtime`），而事件类必须与线上契约逐字一致——两者之间需要这个值对象中转。
    """

    batch_id: str
    """本次提问批次的标识，运行内唯一；由工具侧生成，不接受模型传入（基座 7.2 节）。"""

    items: tuple[QuestionItem, ...]
    """一组题，按数组顺序呈现。"""

    def __post_init__(self) -> None:
        """核实批次有标识、且至少有一道题。

        Raises:
            ValueError: `batch_id` 为空，或 `items` 为空。空组不是一次提问——它既不能
                呈现给使用者，也没有可提交的对象（第 7.2 节：组是提交单位）；放行它会让
                运行结束于一张空卡片，而使用者无从作答。
        """
        if not self.batch_id.strip():
            raise ValueError("批次标识 batch_id 不能为空")
        if not self.items:
            raise ValueError("一组提问至少要有一道题（items 不能为空）")


@dataclass(frozen=True, slots=True)
class ActionCardSection:
    """卡片的一个分节；基座 7.3 节 `sections` 的元素。"""

    key: str
    """分节键。取值词表属产品侧（基座不含领域词），基座只要求它有值。"""

    heading: str
    """分节小标题。"""

    lines: tuple[str, ...]
    """该节的文本行，逐行呈现。"""


@dataclass(frozen=True, slots=True)
class ActionCardState:
    """卡片的一个键值状态；基座 7.3 节 `states` 的元素。"""

    key: str
    """状态键。词表属产品侧。"""

    value: str
    """状态值。词表与取值枚举属产品侧——「模型编不出第四种」由产品侧参数模型保证。"""


@dataclass(frozen=True, slots=True)
class ActionCardAnnotation:
    """卡片的一条标注；基座 7.3 节 `annotations` 的元素。"""

    target: str
    """指向某条 `line` 的序号。"""

    kind: str
    """标注的种类。词表属产品侧。"""


@dataclass(frozen=True, slots=True)
class ActionCard:
    """一次结构化的卡片段输出；基座 7.3 节的通用信封。

    为什么是通用信封：基座不得出现领域术语（第 1 节不变量），而卡片的取值词表是领域事实。
    因此基座只承载「分节文本 + 键值状态 + 逐条标注」这三种与领域无关的形状，领域词汇与
    词表由产品侧定义并在工具的参数模型上校验（决策记录见
    docs/技术设计/decisions/应急卡片由产品侧工具产出.md）。

    由产品侧工具产出，不是基座保留工具：卡片不需要「结束本次运行」这一运行编排行为，
    工具返回后运行自然继续（基座 7.3 节）。
    """

    card_id: str
    """本次卡片的标识；前端凭它区分新旧卡。"""

    title: str
    """卡片标题。"""

    sections: tuple[ActionCardSection, ...]
    """分节，按呈现顺序。"""

    states: tuple[ActionCardState, ...] = ()
    """键值状态；可为空（基座 7.3 节）。"""

    annotations: tuple[ActionCardAnnotation, ...] = ()
    """逐条标注；可为空（基座 7.3 节）。"""


__all__ = [
    "ActionCard",
    "ActionCardAnnotation",
    "ActionCardSection",
    "ActionCardState",
    "Question",
    "QuestionItem",
    "QuestionOption",
]
