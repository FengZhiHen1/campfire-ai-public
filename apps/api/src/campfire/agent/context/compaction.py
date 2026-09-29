"""压缩机制：把最旧的一段历史摘要成**一条追加的检查点消息**。

依据 docs/技术设计/technical-details/压缩策略.md（该文档是本机制的真源）。三条硬约束决定了
这里的形状：

1. **前缀缓存要求前缀逐字不变** → 压缩**低频、成段**发生，落地方式是「在末尾追加」，
   **不改写、不删除任何已存消息**（第 5 节）。
2. **对话是唯一真源** → 摘要进入对话本身就是一条消息；检查点之后「窗口 = [系统提示] +
   [最后一条摘要起的全部历史]」可完全从会话推导，不需要另存窗口配方（第 5 节）。
3. **压缩失败不得让对话不可用** → 写摘要失败、摘要被截断、没有可安全压缩的范围，一律
   **不改动窗口**并如实报告，不留假成功（第 7 节）。

## 落地形状（第 5、6、8 节三条要求同时成立的唯一形状）

第 5 节要求窗口从摘要处开始取（前缀裁剪），第 6 节要求保留的尾部「原样跟在摘要之后」，
第 8 节第 1 条又禁止在中间插入（插入等于移动前缀，每轮缓存全量击穿）。三条合起来只有一个
形状：**在末尾追加「检查点 + 尾部原文」**。于是压缩后：

```text
历史：… [旧尾部] [检查点] [尾部原文]        ← 只追加，前缀一字未动（缓存可复用）
窗口：[系统提示] [检查点] [尾部原文]        ← derive_window 从最后一条检查点起取
```

代价必须写明：被保留的尾部在历史里存在**两份**，摘要之前那一份成为死重量（不再进窗口，
也不删除——第 5 节禁止删除）。这与基座文档「会话存储会持续增长」那条已知偏差同源；
清理属会话级压缩重写，第 10 节明确一期不做。

## 三条实现决定（文档未写死，这里写明理由）

- **触发用估算、计量用提供方数字**。第 9 节要求「用提供方返回的 usage 计量，不用字符数折算」，
  那是**计量**；而「这次要不要压缩」必须在调用之前决定，此时只有估算可用。因此阈值判定用
  :func:`~campfire.agent.skill_runtime.catalog.estimate_tokens`（其 docstring 已声明它是估算、
  不是上界），记录里用摘要调用返回的真实 usage。
- **工具配对靠「边界安全」而非「整轮切分」**。第 3 节要求「工具调用与结果成对，但不要求整轮」，
  所以判定的是**边界**：保留尾部的第一项不能是「调用在被压缩段里的结果」，被压缩段的最后一项
  不能是「结果在保留尾部里的调用」。不安全就把边界往前移（多留一点），必要时退化为「没有可
  安全压缩的范围」。
- **事务靠端口表达**。第 7 节要求「有开始/结束记录的事务，中途崩溃留下可检测的未闭合标记」。
  表归装配处（Alembic 迁移与 ``core/db`` 同批），基座因此只声明 :class:`CompactionJournal`
  端口，并把「先记开始、再动手、最后记结束」的调用顺序固定在本模块里——崩溃时留下的就是
  一条没有结束记录的标记。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from campfire.agent.skill_runtime import estimate_tokens

from .errors import ContextError
from .window import (
    COMPACTED_SUMMARY_CLOSE_TAG,
    COMPACTED_SUMMARY_TAG,
    derive_window,
    is_compacted_summary,
    last_checkpoint_index,
    leading_system_count,
    message_text,
)

if TYPE_CHECKING:
    from campfire.core.config import Settings

Item = Mapping[str, object]
"""会话历史里的一项。

**刻意不引入 SDK 类型**：本模块只依赖「像消息的映射」这一鸭子类型契约（与 ``window`` 相同），
实测 SDK 落库的项就是这种形状（含 ``function_call`` / ``function_call_output`` 这类无 role 项）。
"""


class CompactionError(ContextError):
    """压缩参数不合法。"""


SkipReason = Literal[
    "auto_disabled",
    "below_threshold",
    "no_safe_range",
    "summary_failed",
    "summary_truncated",
    "commit_failed",
]
"""没有做压缩的原因。每一个都必须能被如实报告（第 3、7 节：不留假成功）。

``commit_failed`` 是「摘要写好了，但检查点没写进会话」：窗口因此**未改动**，必须与
「压缩完成」区分开（第 7 节禁止假装压缩完成的记录）。
"""


class CompactionCommit(Protocol):
    """把追加内容落库的端口（第 7 节事务的落库步骤）。

    单独成端口是为了让「记结束」发生在落库**之后**：由机制决定顺序，调用方只提供实现。

    **超时语义（实现方必须遵守）**：实现必须自带超时上界（本层的 180 秒运行预算是最后
    一道，不该由它承担单次写入的等待）。超时抛出的异常会被 ``compact`` 记成
    ``commit_failed``，而**超时其实是「结果未知」**——会话可能已经写入。因此实现方要么
    让写入**幂等**（同一批追加内容重放不产生重复），要么在超时后自行核实落库结果；
    只把超时当「确定没写」会得到一份与真源不一致的窗口判断。
    """

    async def __call__(self, appended: Sequence[Item]) -> None:
        """把追加内容写进会话；写不进去必须抛异常（超时必须与「确定失败」区分，见类说明）。"""
        ...


# --- 参数（第 10 节） -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompactionSettings:
    """压缩参数（第 10 节）。构造即校验，非法配置直接失败（「加载时校验」）。

    ``context_window_tokens`` 是 ``W``（模型上下文上限），``output_reserve_tokens`` 是 ``O``
    （为输出预留的额度；基座第 2 节不设 token 上限，因此它是**预算假设**而不是请求上的截断值）。
    """

    context_window_tokens: int
    output_reserve_tokens: int = 8192
    threshold_ratio: float = 0.8
    headroom_tokens: int = 65_536
    retain_ratio: float | None = 0.16
    retain_tokens: int | None = None
    max_tokens: int | None = None
    compaction_retries: int = 1
    max_overflow_retries: int = 1
    auto: bool = True

    # quality-floor: ignore docstring-promise 异常由 _validate_* 抛出，本函数体只做编排
    def __post_init__(self) -> None:
        """校验第 10 节的加载期规则。

        Raises:
            CompactionError: 两种保留形式并存或都缺、保留比例不小于阈值比例、保留 token
                不低于阈值、非正数或非法比例、解析出的阈值非正。
        """
        self._validate_sizes()
        self._validate_ratio()
        self._validate_retention()
        self._validate_budget()

    def _validate_sizes(self) -> None:
        """校验窗口与余量的规模。

        Raises:
            CompactionError: 窗口非正、余量为负、阈值比例越界或重试次数为负。
        """
        if self.context_window_tokens <= 0:
            raise CompactionError("context_window_tokens（W）必须为正整数")
        if self.output_reserve_tokens < 0:
            raise CompactionError("output_reserve_tokens（O）不能为负")
        if self.headroom_tokens < 0:
            raise CompactionError("headroom_tokens 不能为负")
        if self.compaction_retries < 0 or self.max_overflow_retries < 0:
            raise CompactionError("重试次数不能为负")

    def _validate_ratio(self) -> None:
        """校验阈值比例。

        Raises:
            CompactionError: 比例不在 (0, 1]，或解析出的阈值非正。
        """
        if not 0 < self.threshold_ratio <= 1:
            raise CompactionError("threshold_ratio 必须落在 (0, 1]")
        if self.threshold_tokens <= 0:
            raise CompactionError("解析出的阈值为非正数：W − O − headroom 必须为正")

    def _validate_retention(self) -> None:
        """校验两种保留形式互斥、取值合法且低于阈值。

        Raises:
            CompactionError: 两种形式并存或都缺、取值为负、比例不小于阈值比例、
                绝对 token 不低于阈值。
        """
        if self.retain_ratio is None and self.retain_tokens is None:
            raise CompactionError("retain_ratio 与 retain_tokens 必须给出一个")
        if self.retain_ratio is not None and self.retain_tokens is not None:
            raise CompactionError("retain_ratio 与 retain_tokens 互斥，不能同时给出")
        if self.retain_ratio is not None:
            if self.retain_ratio < 0:
                raise CompactionError("retain_ratio 不能为负")
            if self.retain_ratio >= self.threshold_ratio:
                raise CompactionError("保留比例必须小于阈值比例，否则压缩永远无法把窗口降到阈值以下")
        if self.retain_tokens is not None:
            if self.retain_tokens < 0:
                raise CompactionError("retain_tokens 不能为负")
            if self.retain_tokens >= self.threshold_tokens:
                raise CompactionError("retain_tokens 必须低于解析出的阈值")

    def _validate_budget(self) -> None:
        """校验摘要输出上限。

        Raises:
            CompactionError: ``max_tokens`` 非正。
        """
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise CompactionError("max_tokens 必须为正整数")

    @property
    def threshold_tokens(self) -> int:
        """触发阈值：``floor(min(W × thresholdRatio, W − O − headroomTokens))``（第 2 节）。"""
        return math.floor(
            min(
                self.context_window_tokens * self.threshold_ratio,
                self.context_window_tokens - self.output_reserve_tokens - self.headroom_tokens,
            )
        )

    @property
    def retain_budget_tokens(self) -> int:
        """逐字保留的尾部预算（第 6 节）：``(W − O) × retainRatio`` 或绝对 ``retainTokens``。"""
        if self.retain_tokens is not None:
            return self.retain_tokens
        assert self.retain_ratio is not None  # 由 __post_init__ 保证
        return math.floor((self.context_window_tokens - self.output_reserve_tokens) * self.retain_ratio)

    @property
    def summary_max_tokens(self) -> int:
        """摘要输出上限（第 10 节：默认取 ``headroomTokens``）。"""
        return self.max_tokens if self.max_tokens is not None else self.headroom_tokens


def settings_from_config(settings: "Settings") -> CompactionSettings:
    """按配置构造压缩参数：``W``/``O`` 来自 ``core/config``，其余取第 10 节默认值。

    存在的理由是「配置唯一入口」（项目结构设计第 10 节）：装配处不该自己把
    ``model_context_window_tokens`` / ``model_output_reserve_tokens`` 两个字段名再抄一遍，
    抄一遍就多一个会漂移的第二真相。
    """
    return CompactionSettings(
        context_window_tokens=settings.model_context_window_tokens,
        output_reserve_tokens=settings.model_output_reserve_tokens,
    )


# --- 历史项的形状判定与计数 -------------------------------------------------


def _field(item: object, key: str) -> object:
    """取一个字段；不是映射就返回 ``None``。"""
    getter = getattr(item, "get", None)
    return getter(key, None) if callable(getter) else None


def _string_field(item: object, key: str) -> str | None:
    """取一个字符串字段。"""
    value = _field(item, key)
    return value if isinstance(value, str) else None


def item_text(item: object) -> str:
    """把一项折算成用于**估算**的文本。

    覆盖实测出现的三种形状：带 ``content`` 的消息、``function_call``（名字 + 参数）、
    ``function_call_output``（输出）。认不出的形状返回空串——这会让估算偏低，因此它是估算、
    不是上界（与 ``estimate_tokens`` 的声明一致）。
    """
    parts: list[str] = []
    content = message_text(item)
    if content:
        parts.append(content)
    for key in ("name", "arguments", "output"):
        value = _string_field(item, key)
        if value:
            parts.append(value)
    raw_output = _field(item, "output")
    if isinstance(raw_output, list):
        parts.extend(_text_of(part) for part in raw_output)
    # Chat Completions 形态的工具调用：参数在 tool_calls[*].function 里。第一版没读它，
    # 于是一条 arguments 上千字的助手消息被计成 0 token——估算偏低到失真。
    calls = _field(item, "tool_calls")
    if isinstance(calls, list):
        for call in calls:
            function = _field(call, "function")
            for key in ("name", "arguments"):
                value = _string_field(function, key)
                if value:
                    parts.append(value)
    # 推理摘要（若提供方落这类项）：同样要计入，否则低估。
    reasoning = _field(item, "reasoning")
    if isinstance(reasoning, dict):
        summary = reasoning.get("summary")
        if isinstance(summary, list):
            parts.extend(_text_of(part) for part in summary)
    return "\n".join(part for part in parts if part)


def _text_of(part: object) -> str:
    """从分片里取文本：``{"text": ...}``，或直接是字符串/其他标量。"""
    text = _string_field(part, "text")
    if text is not None:
        return text
    return part if isinstance(part, str) else str(part)


def estimate_window_tokens(items: Sequence[object], *, extra_text: str = "") -> int:
    """估算**这批项**占用的 token（``extra_text`` 用于把静态系统提示计入）。

    **刻意不计工具声明**：一期工具数量固定且声明在一条对话内不变（基座第 5 节），增长的是
    历史本身；把 JSON Schema 折算进来只会让这个估算更难解释。要算**窗口**占用请用
    :func:`window_tokens`。
    """
    total = estimate_tokens(extra_text) if extra_text else 0
    return total + sum(estimate_tokens(item_text(item)) for item in items)


def window_tokens(items: Sequence[object], *, extra_text: str = "") -> int:
    """**窗口**占用的 token——真正会发出去的那一部分。

    窗口 = ``[前导 system 消息] + [最后一条检查点起的全部历史]``（第 5 节），因此先经
    :func:`~campfire.agent.context.window.derive_window` 裁剪再计数。用整段历史会高估，
    并让「压缩后仍高于阈值」永远成立。
    """
    return estimate_window_tokens(derive_window(items), extra_text=extra_text)


def is_tool_call(item: object) -> bool:
    """是不是一次工具调用项（``function_call``，或带 ``tool_calls`` 的助手消息）。"""
    if _string_field(item, "type") == "function_call":
        return True
    value = _field(item, "tool_calls")
    return bool(value)


def is_tool_output(item: object) -> bool:
    """是不是一次工具结果项（``function_call_output``，或 role 为 ``tool`` 的消息）。"""
    if _string_field(item, "type") == "function_call_output":
        return True
    return _string_field(item, "role") == "tool"


def _call_ids(item: object) -> frozenset[str]:
    """取一项携带的**全部**工具配对键。

    必须取全部而不是一个：助手消息可以一次发起多个工具调用（``tool_calls`` 形态），
    只取第一个会让边界检查漏掉其余配对——实测在 Chat Completions 形态下会把调用与结果
    切开（Responses 形态一次一个 ``call_id``，所以此前没有暴露）。两种形态都要认：

    - Responses：``{"type": "function_call", "call_id": ...}`` / ``{"type": "function_call_output", ...}``
    - Chat Completions：``{"tool_calls": [{"id": ...}, ...]}`` / ``{"role": "tool", "tool_call_id": ...}``
    """
    ids: set[str] = set()
    for key in ("call_id", "tool_call_id"):
        value = _string_field(item, key)
        if value:
            ids.add(value)
    calls = _field(item, "tool_calls")
    if isinstance(calls, list):
        for call in calls:
            for key in ("id", "tool_call_id"):
                value = _string_field(call, key)
                if value:
                    ids.add(value)
    return frozenset(ids)


# --- 范围选择（第 3、6 节） -------------------------------------------------


@dataclass(frozen=True, slots=True)
class RangeSelection:
    """范围选择的结果（历史下标）。"""

    start: int
    """被压缩范围的起点（含）；永远不越过前导 system 消息。"""

    end: int
    """保留尾部的起点（= 被压缩范围的终点，不含）。"""

    @property
    def compacted_items(self) -> int:
        """被压缩的项数。"""
        return max(0, self.end - self.start)

    @property
    def is_empty(self) -> bool:
        """是否没有可压缩的内容。"""
        return self.compacted_items == 0


def _boundary_is_safe(items: Sequence[object], end: int) -> bool:
    """保留尾部从 ``end`` 开始是否不切断工具配对。

    两条判据：尾部第一项不能是「调用在被压缩段里」的结果；被压缩段最后一项不能是
    「结果在尾部里」的调用。任一被切断就把边界往前移（多留一点），而不是硬切。
    """
    if end <= 0 or end > len(items):
        return True

    if end < len(items) and is_tool_output(items[end]):
        wanted = _call_ids(items[end])
        if wanted and any(_call_ids(item) & wanted for item in items[:end]):
            return False

    if is_tool_call(items[end - 1]):
        wanted = _call_ids(items[end - 1])
        if wanted and any(_call_ids(item) & wanted for item in items[end:]):
            return False

    return True


def select_range(
    items: Sequence[object],
    settings: CompactionSettings,
    *,
    force_max_reduction: bool = False,
    retain_scale: float = 1.0,
) -> RangeSelection:
    """选出要压缩的最旧范围（第 3、6 节）。返回的是**历史下标**。

    - 起点 = 最后一条检查点的下标；没有检查点时是第一个非 system 项。这样上一份摘要必然
      进入被压缩范围（第 4 节要求合并它），而系统提示永不被遮蔽；
    - 终点由保留预算从**历史末尾**往前累计得出（越界的那一项整项保留），且不越过起点；
    - 终点再按工具配对边界往前修正；
    - ``force_max_reduction``（**只给溢出恢复路径**）绕过保留预算，取最大头部缩减；
    - ``retain_scale``（**给常规重试**）按比例缩小保留预算，而不是把尾部整段丢掉：
      「绕过保留策略」在第 2 节是溢出行的专属手段，常规重试不该动用它——实测第一版在重试时
      丢掉了整段逐字尾部，代价付了、窗口却仍在阈值之上。
    """
    checkpoint = last_checkpoint_index(items)
    start = checkpoint if checkpoint is not None else leading_system_count(items)
    if start >= len(items):
        return RangeSelection(start=len(items), end=len(items))

    if force_max_reduction:
        return RangeSelection(start=start, end=len(items))

    budget = max(0, int(settings.retain_budget_tokens * retain_scale))
    kept = 0
    end = len(items)
    for index in range(len(items) - 1, start - 1, -1):
        kept += estimate_tokens(item_text(items[index]))
        end = index
        if kept >= budget:
            break

    while end > start and not _boundary_is_safe(items, end):
        end -= 1

    return RangeSelection(start=start, end=end)


# --- 检查点与窗口读取 -------------------------------------------------------


def build_checkpoint(summary_text: str) -> Item:
    """把摘要正文包成检查点消息（第 5 节：一条消息，标签框定）。

    角色取 ``user``：注入项一律不使用 ``system``（系统提示必须静态，第 8 节第 2 条），
    而检查点属于「尾部消息」。
    """
    body = summary_text.strip()
    return {
        "role": "user",
        "content": f"{COMPACTED_SUMMARY_TAG}\n{body}\n{COMPACTED_SUMMARY_CLOSE_TAG}",
    }


def previous_summary_text(items: Sequence[object]) -> str | None:
    """取最后一份检查点的正文；没有返回 ``None``。"""
    found: str | None = None
    for item in items:
        if is_compacted_summary(item):
            found = message_text(item)
    if found is None:
        return None
    body = found.strip()
    body = body.removeprefix(COMPACTED_SUMMARY_TAG).removesuffix(COMPACTED_SUMMARY_CLOSE_TAG)
    return body.strip()


def retained_after_last_checkpoint(items: Sequence[Item]) -> tuple[Item, ...]:
    """取「最后一条检查点之后」的项——压缩后逐字保留、仍在窗口里的那一段。"""
    checkpoint = last_checkpoint_index(items)
    if checkpoint is None:
        return tuple(items)
    return tuple(items[checkpoint + 1 :])


def appended_items(history: Sequence[Item], selection: RangeSelection, summary_text: str) -> tuple[Item, ...]:
    """压缩要追加的内容：**检查点 + 尾部原文**（见模块 docstring 的落地形状）。"""
    return (build_checkpoint(summary_text), *history[selection.end :])


def _with_merge_clause(instruction: str, has_previous: bool) -> str:
    """已有摘要时追加合并要求（第 4 节）。

    由基座追加而不是指望指令作者记得：这一段是机制的一部分，漏了就会退化成「照抄旧摘要」。
    """
    if not has_previous:
        return instruction
    return (
        f"{instruction}\n\n"
        "注意：上面已有一份旧的摘要。必须把其中**仍然成立**的事实合并进本次输出，"
        "丢掉已过时的内容，并沿用同一结构；不要照抄旧摘要，也不要丢弃它。"
    )


# --- 摘要端口与结果 ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    """一次摘要调用的输入。

    ``prefix`` 是**逐字回放的热前缀**：被压缩范围的消息（含上一份检查点，若在范围内）。
    系统提示与工具声明由实现方拼在最前面（第 4 节：压缩调用必须与主调用同一模型与路由，
    否则不共享前缀缓存）。
    """

    prefix: tuple[Item, ...]
    system_prompt: str
    """**主运行**的静态系统提示，必须逐字回放为第一条消息（第 4 节）。

    第一版把这个位置留给了摘要器自己的提示，于是接口**无法承载**主运行的系统提示——
    真实一致性只能靠装配处「碰巧传同一个字符串」。前缀缓存要求「完整匹配一个已持久化的
    前缀单元」，第 0 条就不同的话整个前缀都不命中（第 8 节：违反缓存纪律视为缺陷）。
    """

    instruction: str
    """压缩指令；内容由产品侧拥有（第 4 节的六节结构属领域约定），基座只负责追加到末尾。"""

    previous_summary: str | None
    """上一份摘要的正文；非空时基座已要求合并它而不是丢掉或照抄（第 4 节）。"""

    max_tokens: int


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """摘要调用的产出。**只有文本进入检查点**（第 4 节：推理与工具调用一律排除）。"""

    text: str
    truncated: bool = False
    """是否疑似被 ``max_tokens`` 截断。截断的摘要**不落检查点**（第 7 节）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    prompt_cache_hit_tokens: int = 0
    """缓存命中 token（第 9 节要求记录、第 12 节要求用它断言缓存仍有效）。取不到时为 0。"""

    prompt_cache_miss_tokens: int = 0
    """缓存未命中 token（同上）。"""


class CompactionSummarizer(Protocol):
    """写摘要的端口。实现方负责热前缀回放，以及与主调用同一模型同一路由。

    **超时与预算（实现方必须遵守）**：摘要调用是模型调用，其「超时 × 重试 + 退避」的
    最坏耗时必须自己保证落在运行上限之内（与 ``agent.model`` 对主调用的要求同源，见
    :mod:`campfire.agent.limits`）；本层不再套一层超时。摘要失败只让窗口不动（第 7 节的
    安全方向），因此**超时按失败处理是可接受的**——它没有已提交的副作用，不需要区分
    「未知」；真正的约束是不许无界等待，否则运行预算会被从中间砍断。
    """

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        """产出一段摘要文本。"""
        ...


@dataclass(frozen=True, slots=True)
class CompactionOutcome:
    """一次压缩的结果与计量（第 9 节要求记的字段全在这里）。

    ``compacted_items`` 与 ``retained_items`` 的定义刻意写死，避免两种读法：**累计**被替换掉的
    历史项数，与压缩后**窗口里逐字保留**的尾部项数。
    """

    performed: bool
    reason: SkipReason | None = None
    detail: str = ""
    window_tokens_before: int = 0
    window_tokens_after: int = 0
    compacted_items: int = 0
    retained_items: int = 0
    summary: SummaryResult | None = None
    previous_summary_merged: bool = False
    failed_attempts: int = 0
    attempts: int = 0

    @property
    def released_tokens(self) -> int:
        """释放的 token（估算口径）。未压缩时为 0。"""
        return max(0, self.window_tokens_before - self.window_tokens_after)

    @property
    def summary_elapsed_seconds(self) -> float:
        """摘要调用耗时（第 9 节）。"""
        return self.summary.elapsed_seconds if self.summary is not None else 0.0


class CompactionJournal(Protocol):
    """压缩事务的记账端口（第 7 节）。实现落在我们自己的表里，随 ``core/db`` 与迁移落地。

    崩在 :meth:`record_started` 与 :meth:`record_finished` 之间，留下的就是一条**没有结束
    记录的标记**——这正是「可检测的未闭合标记」，不是假装压缩完成。

    **超时语义（实现方必须遵守）**：记账是本地写，实现必须自带超时上界。超时异常的处置与
    其它异常一致——**原样冒泡**（见 :func:`compact` 的 Raises）：记账失败不得被当成
    「压缩没发生」。冒泡值得接受的前提是它不会挂住运行，因此上界由实现保证。
    """

    async def record_started(
        self,
        *,
        window_tokens_before: int,
        compacted_items: int,
        retained_items: int,
    ) -> str:
        """记下开始，返回事务标记。"""
        ...

    async def record_finished(self, marker: str, outcome: CompactionOutcome) -> None:
        """记下结束（成功与失败都要记，否则崩溃与失败无法区分）。"""
        ...


# --- 主流程 -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Attempt:
    """一次尝试的结果，外加「若成功要追加什么」。"""

    outcome: CompactionOutcome
    appended: tuple[Item, ...] = ()


# quality-floor: ignore docstring-promise 异常由 journal 端口抛出并原样传播，函数体无 raise
async def compact(
    items: Sequence[Item],
    *,
    settings: CompactionSettings,
    summarizer: CompactionSummarizer,
    instruction: str,
    journal: CompactionJournal,
    system_prompt: str = "",
    commit: CompactionCommit | None = None,
    manual: bool = False,
    force_max_reduction: bool = False,
) -> tuple[list[Item], CompactionOutcome]:
    """按需压缩：返回（新的历史, 结果）。

    返回的历史永远是原历史的**严格前缀 + 追加**（绝不改写、绝不删除），或与原历史逐项相同
    （未压缩）。

    ``system_prompt`` 会原样带进 :class:`SummaryRequest`（第 4 节要求逐字回放**主运行**的
    系统提示），同时用于窗口 token 估算里那一份静态提示。

    ``commit`` 是**事务的落库步骤**：给了它就由本函数在「记结束」之前调用，因此
    「写不进去」不会被记成「压缩完成」（第 7 节：不留假装压缩完成的结束记录）。落库失败
    不改动窗口、返回 ``performed=False, reason=commit_failed``，让调用方按降级处理——对话
    本身完好无损，把它变成一次失败运行对使用者没有好处。

    ``manual``（第 2 节：仅供运维与调试）与 ``force_max_reduction``（只给溢出恢复）都绕过
    阈值；区别是后者连保留预算也绕过，取最大头部缩减。常规重试不绕过保留预算，只是按比例
    缩小它。

    Raises:
        Exception: 记账端口自身的异常原样冒泡——压缩事务的记账失败不得被当成「压缩没发生」。
    """
    history = list(items)
    before = window_tokens(history, extra_text=system_prompt)

    skipped = _skip_reason(history, settings, manual=manual, force_max_reduction=force_max_reduction, tokens=before)
    if skipped is not None:
        reason, detail = skipped
        return history, CompactionOutcome(
            performed=False,
            reason=reason,
            detail=detail,
            window_tokens_before=before,
            window_tokens_after=before,
        )

    allowed = 1 if force_max_reduction else settings.compaction_retries + 1
    working = history
    total_compacted = 0
    failed = 0
    attempts = 0
    last_skip: tuple[SkipReason, str] | None = None
    last_summary: SummaryResult | None = None
    merged_previous = False

    for attempt in range(allowed):
        attempts = attempt + 1
        result = await _attempt(
            working,
            settings=settings,
            summarizer=summarizer,
            instruction=instruction,
            journal=journal,
            system_prompt=system_prompt,
            commit=commit,
            # 重试只按比例缩小保留预算；「绕过保留策略」是溢出恢复的专属手段（第 2 节）。
            retain_scale=1.0 if attempt == 0 else 1.0 / (attempt + 1),
            force_max_reduction=force_max_reduction,
        )
        if not result.outcome.performed:
            failed += 1
            last_skip = (result.outcome.reason or "summary_failed", result.outcome.detail)
            continue

        working = [*working, *result.appended]
        total_compacted += result.outcome.compacted_items
        last_summary = result.outcome.summary
        merged_previous = merged_previous or result.outcome.previous_summary_merged

        if window_tokens(working, extra_text=system_prompt) <= settings.threshold_tokens:
            break

    if last_summary is None:
        reason, detail = last_skip or ("no_safe_range", "没有可安全压缩的范围")
        return history, CompactionOutcome(
            performed=False,
            reason=reason,
            detail=detail,
            window_tokens_before=before,
            window_tokens_after=before,
            failed_attempts=failed,
            attempts=attempts,
        )

    after = window_tokens(working, extra_text=system_prompt)
    return working, CompactionOutcome(
        performed=True,
        detail=(
            f"压缩后窗口仍高于阈值（约 {after} > {settings.threshold_tokens} token）"
            if after > settings.threshold_tokens
            else ""
        ),
        window_tokens_before=before,
        window_tokens_after=after,
        compacted_items=total_compacted,
        retained_items=len(retained_after_last_checkpoint(working)),
        summary=last_summary,
        previous_summary_merged=merged_previous,
        failed_attempts=failed,
        attempts=attempts,
    )


def _skip_reason(
    history: Sequence[Item],
    settings: CompactionSettings,
    *,
    manual: bool,
    force_max_reduction: bool,
    tokens: int,
) -> tuple[SkipReason, str] | None:
    """判断这次该不该压缩；不该则给出原因与说明。"""
    if not force_max_reduction and not manual and not settings.auto:
        return "auto_disabled", "auto 已关闭，且本次不是手动或溢出压缩"
    if not force_max_reduction and not manual and tokens <= settings.threshold_tokens:
        return "below_threshold", f"窗口约 {tokens} token，未越过阈值 {settings.threshold_tokens}"

    if select_range(history, settings, force_max_reduction=force_max_reduction).is_empty:
        return "no_safe_range", "没有可安全压缩的范围（整段历史都是不可分单元）"
    return None


async def _attempt(
    history: list[Item],
    *,
    settings: CompactionSettings,
    summarizer: CompactionSummarizer,
    instruction: str,
    journal: CompactionJournal,
    system_prompt: str,
    commit: CompactionCommit | None,
    retain_scale: float,
    force_max_reduction: bool,
) -> _Attempt:
    """做一次压缩尝试（一次事务：先记开始 → 动手 → **落库** → 记结束）。

    落库放在「记结束」之前是第 7 节的要求：否则写失败会留下一条「压缩完成」的闭合记录，
    而窗口其实没变——那正是「假装压缩完成」。
    """
    before = window_tokens(history, extra_text=system_prompt)
    selection = select_range(history, settings, force_max_reduction=force_max_reduction, retain_scale=retain_scale)
    if selection.is_empty:
        return _Attempt(
            CompactionOutcome(
                performed=False,
                reason="no_safe_range",
                detail="没有可安全压缩的范围",
                window_tokens_before=before,
                window_tokens_after=before,
            )
        )

    marker = await journal.record_started(
        window_tokens_before=before,
        compacted_items=selection.compacted_items,
        retained_items=len(history) - selection.end,
    )

    previous = previous_summary_text(history)
    request = SummaryRequest(
        prefix=tuple(history[selection.start : selection.end]),
        system_prompt=system_prompt,
        instruction=_with_merge_clause(instruction, previous is not None),
        previous_summary=previous,
        max_tokens=settings.summary_max_tokens,
    )

    try:
        summary = await summarizer.summarize(request)
    except Exception as exc:  # noqa: BLE001 —— 摘要失败不改动窗口（第 7 节）
        return _Attempt(
            await _finish(
                journal,
                marker,
                CompactionOutcome(
                    performed=False,
                    reason="summary_failed",
                    detail=f"摘要调用失败（{type(exc).__name__}）",
                    window_tokens_before=before,
                    window_tokens_after=before,
                ),
            )
        )

    if summary.truncated:
        return _Attempt(
            await _finish(
                journal,
                marker,
                CompactionOutcome(
                    performed=False,
                    reason="summary_truncated",
                    detail=f"摘要疑似被 max_tokens={settings.summary_max_tokens} 截断，不落检查点",
                    window_tokens_before=before,
                    window_tokens_after=before,
                    summary=summary,
                ),
            )
        )

    if not summary.text.strip():
        return _Attempt(
            await _finish(
                journal,
                marker,
                CompactionOutcome(
                    performed=False,
                    reason="summary_failed",
                    detail="摘要为空，不落检查点",
                    window_tokens_before=before,
                    window_tokens_after=before,
                    summary=summary,
                ),
            )
        )

    to_append = appended_items(history, selection, summary.text)
    if commit is not None:
        try:
            await commit(to_append)
        except Exception as exc:  # noqa: BLE001 —— 写不进去就如实记为没压缩，不当成压缩完成
            return _Attempt(
                await _finish(
                    journal,
                    marker,
                    CompactionOutcome(
                        performed=False,
                        reason="commit_failed",
                        detail=f"检查点写入会话失败（{type(exc).__name__}）：窗口未改动",
                        window_tokens_before=before,
                        window_tokens_after=before,
                        summary=summary,
                    ),
                )
            )

    after = window_tokens([*history, *to_append], extra_text=system_prompt)
    outcome = await _finish(
        journal,
        marker,
        CompactionOutcome(
            performed=True,
            window_tokens_before=before,
            window_tokens_after=after,
            compacted_items=selection.compacted_items,
            retained_items=len(history) - selection.end,
            summary=summary,
            previous_summary_merged=previous is not None,
        ),
    )
    return _Attempt(outcome, to_append)


async def _finish(journal: CompactionJournal, marker: str, outcome: CompactionOutcome) -> CompactionOutcome:
    """记账收尾后返回结果（成功与失败都要记，否则崩溃与失败无法区分）。"""
    await journal.record_finished(marker, outcome)
    return outcome


# 指向**上下文窗口**的措辞（不是「太长」这类泛词）。第一版收了 "too long"，于是
# "Invalid 'messages[1].content': string too long" 这种与窗口无关的 400 参数错误被误判成溢出，
# 触发了破坏性的最大头部缩减。中文措辞要一并收——提供方是腾讯云，中文提示是现实可能。
_OVERFLOW_PHRASES = (
    "context length",
    "context_length",
    "context window",
    "context_window",
    "maximum context",
    "max context",
    "too many tokens",
    "maximum number of tokens",
    "exceed the maximum number of tokens",
    "reduce the length of the messages",
    "input is too long for",
    "上下文长度",
    "上下文窗口",
    "超出上下文",
    "上下文超限",
)


def is_context_overflow(error: BaseException) -> bool:
    """提供方是否**明确**报了上下文窗口溢出（第 2、7 节的溢出恢复入口）。

    触发条件是「状态码 400/413 + 措辞指向**上下文窗口**」。措辞刻意收紧到不含 "too long"
    这类泛词：第一版收了它，于是与窗口无关的 400 参数错误
    （``Invalid 'messages[1].content': string too long``）被误判成溢出，走了**绕过阈值与保留
    策略**的最大头部缩减、**永久改动了窗口**。中文措辞一并收（提供方是腾讯云）。

    **被考虑并拒绝的第二道门槛**：审查者提出「窗口估算 ≥ 上限的一半」以防假阳性。不采用，
    因为本模块的估算有**已知的系统性偏低**（刻意不计工具声明、认不出的形状计 0），拿它去否决
    提供方的明确信号，会把真实溢出变成更难排查的模型故障；而压缩策略第 7 节的原文是
    「溢出恢复**只在提供方明确分类窗口溢出时触发**」——判据在提供方的分类，不在我们的估算。
    假阳性由措辞收紧来挡，这条判定因此只认状态码与措辞。
    """
    status = getattr(error, "status_code", None)
    if status not in (400, 413):
        # 有些客户端把状态码藏在 response 上
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    if status not in (400, 413):
        return False

    text = str(error).lower()
    return any(phrase in text for phrase in _OVERFLOW_PHRASES)


__all__ = [
    "CompactionCommit",
    "CompactionError",
    "CompactionJournal",
    "CompactionOutcome",
    "CompactionSettings",
    "CompactionSummarizer",
    "Item",
    "RangeSelection",
    "SkipReason",
    "SummaryRequest",
    "SummaryResult",
    "appended_items",
    "build_checkpoint",
    "compact",
    "estimate_window_tokens",
    "is_context_overflow",
    "is_tool_call",
    "is_tool_output",
    "item_text",
    "previous_summary_text",
    "retained_after_last_checkpoint",
    "select_range",
    "settings_from_config",
    "window_tokens",
]
