"""SDK 会话条目 → 会话消息与摘要的解析（纯函数，不碰数据库）。

职责：把 SDK 会话存储里的 JSON 条目翻成面层要的 `parts` 形状、标题摘要与末条预览。
边界：只解析已读出的条目；读取归 `session_repository`，越权判定归 `sessions`。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.2、3.3、7 节；
docs/技术设计/technical-details/通用基座.md 第 2 节；
`agent/context/window.py` 的 `message_text`（同类解析的基座侧实现）。

为什么单立一个模块：这里承载的是「SDK 的持久化格式」这一外部契约的唯一解析点。
基座的 `agent/context/window.py` 也解析同一批条目，但两者的判据不同——那边为压缩
判定服务，必须保守（遇到不认识的部件就返回 `None`，宁可不裁剪历史）；这边为呈现
服务，要尽量取出可读文本（逐部件取，认不出的部件单独丢掉）。判据不同故不合并，
而依赖白名单也不允许 `modules/*` import `agent/*`（项目结构设计第 7 节）。

两处常量的漂移风险由测试机械守住：本模块的 `_TEXT_PART_TYPES` 与
`agent/context/window.py` 的同名集合都必须等于同一个字面量
（`test_accounts_session_items.py` 的 `test_text_part_types_agree_across_the_two_parsers`）。
两侧不能合并成一份：`modules/*` 不得 import `agent/*`（同上），故相等关系只能由用例守。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK 条目的判别字段取值
# ---------------------------------------------------------------------------

#: 普通消息条目的类型（`role` 区分使用者与助手）。
ITEM_TYPE_MESSAGE = "message"

#: 思考条目的类型（DeepSeek 思考模式的思考段，独立成条）。
ITEM_TYPE_REASONING = "reasoning"

#: 工具调用条目的类型。
ITEM_TYPE_FUNCTION_CALL = "function_call"

#: 工具结果条目的类型。
ITEM_TYPE_FUNCTION_CALL_OUTPUT = "function_call_output"

#: 算作文本的部件类型。必须与 `agent/context/window.py` 的同名集合一致：
#: 两处解析同一种持久化格式，集合不一致会让同一条消息在一侧被认作文本、另一侧不被认作。
_TEXT_PART_TYPES: frozenset[str] = frozenset({"text", "input_text", "output_text"})

#: 使用者与助手两个角色。契约（HTTP 与 SSE 契约第 3.3 节）只承认这两个。
_ROLE_USER = "user"
_ROLE_ASSISTANT = "assistant"

#: 思考条目的摘要部件里承载文本的键。
_REASONING_SUMMARY_KEY = "summary"
_REASONING_TEXT_KEY = "text"

# ---------------------------------------------------------------------------
# 应用注入消息的信封前缀
# ---------------------------------------------------------------------------

#: 应用自己注入的消息的开头标签。这些消息在 SDK 存储里的角色也是 `user`
#: （实测：注入项经 `runner._as_input_item` 一律渲染为 `role: "user"`），
#: 因此只能靠内容前缀与真实使用者消息区分。
#:
#: 五个基座信封取自 `agent/markup.py` 的说明（该处是信封的权威清单）；
#: `<compacted-summary>` 取自 `agent/context/window.py` 的 `COMPACTED_SUMMARY_TAG`
#: （压缩检查点同样以 `role: "user"` 落库）。
#:
#: 两个产品侧信封（2026-10-02 随 T07b 补齐）：`<emergency_profile` 与
#: `<emergency_memory` 由 `surfaces/consult/injections.py` 产出（应急入口的档案与记忆
#: 预注入）。它们此前不在清单里，后果正是这份说明原先预告的那一条——产品侧注入会被
#: 当成使用者消息，会话标题静默变成摘要片段。`modules/*` 不得 import `surfaces/*`
#: （项目结构设计第 7 节），因此这里是字面量；产出口与清单的一致性由
#: `tests/test_consult_emergency_render.py` 的用例机械核对（两份字面量不许漂移）。
#:
#: 判据的边界（仍然不完整，如实写明）：档案摘要与检索结果这两个产品侧信封尚未定形
#: （归后续任务），它们进对话时同样要在这里补一行，否则上述后果会在那两处重现。
INJECTED_MESSAGE_PREFIXES: tuple[str, ...] = (
    "<available_skills>",
    "<skill_content",
    "<skill_resources>",
    "<unavailable_sources>",
    "<tool_availability>",
    "<compacted-summary>",
    "<emergency_profile",
    "<emergency_memory",
)

# ---------------------------------------------------------------------------
# 工具结果信封
# ---------------------------------------------------------------------------

#: 工具失败信封的开头（`agent/tools/results.py` 的 `ToolFailure.as_model_text`）。
_TOOL_ERROR_OPEN = '<tool_error code="'
#: 错误码与说明之间的分隔。
_TOOL_ERROR_CODE_END = '">'
#: 工具失败信封的结尾。
_TOOL_ERROR_CLOSE = "</tool_error>"

#: 工具调用没有结果时（运行被取消或触顶打断）的说明。
#:
#: 取自基座收尾路径的原文（`agent/runtime/runner.py` 给被打断的调用补的说明），
#: 让水合出来的 tool_call part 与当时的事件流说的是同一句话。
INTERRUPTED_TOOL_SUMMARY = "运行结束，工具调用没有结果"

#: 工具名读不出来时的占位。用具名常量而不是空串：空串会让「工具叫空名字」与
#: 「名字没读出来」在界面上无法区分。
UNKNOWN_TOOL_NAME = "unknown_tool"

#: 水合 `tool_call` part 的 `summary` 上界（CORE-11：进入响应的文本必须有界）。
#: 与事件流的取法一致——`agent/runtime/assembly.py` 用基座的 `SUMMARY_LIMIT`
#: 截断工具说明，这里取同一个数，让水合与流式的摘要长度相同。
TOOL_SUMMARY_MAX_CHARS = 200

# ---------------------------------------------------------------------------
# parts 形状（HTTP 与 SSE 契约第 7 节的三个可重建 part）
# ---------------------------------------------------------------------------


class TextPart(TypedDict):
    """文本 part。形状归 HTTP 与 SSE 契约第 7 节。"""

    type: Literal["text"]
    text: str


class ReasoningPart(TypedDict):
    """思考 part。

    形状归通用基座第 7.1 节（`delta` 是流式期间的增量）。水合只能给出落库的
    整段思考文本，因此这里把整段放进 `delta`——该 part 形状只有一个文本字段，
    没有第二个可用的落点。前端侧无需区分（两者都是累加到同一个思考段）。
    """

    type: Literal["reasoning"]
    delta: str


class ToolCallPart(TypedDict):
    """工具调用 part。形状归 HTTP 与 SSE 契约第 7 节。"""

    type: Literal["tool_call"]
    tool_name: str
    ok: bool
    summary: str


MessagePart = TextPart | ReasoningPart | ToolCallPart
"""能被重建的 part 类型。

另外三种（`citation` / `question` / `action_card`）没有持久化表示：它们的载荷在
事件流里产出，不落在 SDK 的会话存储里——`citation` 只在引用索引（一个按 `run_id`
组织的端口），`question` / `action_card` 的产出工具尚未实现。从会话真源里
读不出它们，故本模块不产出、也不伪造。
"""


class HydratedMessage(TypedDict):
    """一条水合后的消息。形状归 HTTP 与 SSE 契约第 3.3 节。"""

    id: str
    role: str
    parts: list[MessagePart]


# ---------------------------------------------------------------------------
# 读出的原始条目
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredItem:
    """从 SDK 消息表读出的一条条目：行标识 + 已解析的载荷。

    行标识来自 `agent_messages.id`（自增主键）。它被用作水合消息的 `id`：该值在
    同一会话内唯一、跨刷新稳定（同一批行必得同一批标识），且来自真源而不是
    新造——用序号或哈希另造一套标识，会让「同一条消息在两次水合里是不是同一条」
    这个问题没有答案。
    """

    row_id: int
    data: Mapping[str, object]
    """解析后的条目；无法解析时由调用方跳过，不会构造出本对象。"""


# ---------------------------------------------------------------------------
# 条目解析
# ---------------------------------------------------------------------------


def parse_item(raw: object) -> Mapping[str, object] | None:
    """把一行 `message_data` 解析成条目映射；不是合法 JSON 对象时返回 `None`。

    SDK 自己的读取路径对损坏行也是跳过（`SQLAlchemySession.get_items` 捕获
    `json.JSONDecodeError` 后 `continue`），因此这里保持同一取向。跳过不是静默：
    调用方按 `None` 记警告（`build_messages` 的说明）。

    Args:
        raw: `agent_messages.message_data` 的值，类型未知（它是数据库里的文本）。

    Returns:
        条目映射；非字符串、非法 JSON、或 JSON 顶层不是对象时返回 `None`。
    """
    if not isinstance(raw, str):
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def item_type(item: Mapping[str, object]) -> str | None:
    """取条目的判别字段；缺失或不是字符串时返回 `None`。"""
    value = item.get("type")
    return value if isinstance(value, str) else None


def _content_parts(item: Mapping[str, object]) -> list[str]:
    """取消息 content 里认得出来的文本部件（逐部件取，认不出的丢掉）。

    与 `window.message_text` 的差别在此：那边遇到认不出的部件整体返回 `None`
    （压缩判定宁可漏检也不误判），这边保留能读的部分——一段含图片的消息，
    丢掉图片也好过整条历史消失。这条差别是有意的，故不共用实现。
    """
    content = item.get("content")
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
            continue
        if not isinstance(part, Mapping):
            continue
        if part.get("type") not in _TEXT_PART_TYPES:
            continue
        text = part.get("text")
        if isinstance(text, str):
            texts.append(text)
    return texts


def message_text(item: Mapping[str, object]) -> str | None:
    """取一条消息的文本 content；取不到时返回 `None`。

    实测两种形状都会出现：使用者消息的 content 是字符串，而 SDK 落库的助手消息是
    分片数组（形如 `[{"type": "output_text", "text": "…"}]`）。两种都要认——
    只认字符串会让每一条助手消息在水合里消失。

    Returns:
        拼接后的文本；没有任何可读文本部件时返回 `None`。
    """
    texts = _content_parts(item)
    if not texts:
        return None
    return "".join(texts)


def reasoning_text(item: Mapping[str, object]) -> str | None:
    """取思考条目的思考文本；取不到时返回 `None`。

    实测形状是 `{"type": "reasoning", "summary": [{"text": "…", "type": "summary_text"}]}`
    ——文本在 `summary` 数组里，不在 `content` 里。因此不能复用 :func:`message_text`。

    Returns:
        拼接后的思考文本；`summary` 缺失或没有可读文本时返回 `None`。
    """
    summary = item.get(_REASONING_SUMMARY_KEY)
    if not isinstance(summary, list):
        return None

    texts: list[str] = []
    for entry in summary:
        if not isinstance(entry, Mapping):
            continue
        text = entry.get(_REASONING_TEXT_KEY)
        if isinstance(text, str):
            texts.append(text)
    if not texts:
        return None
    return "".join(texts)


def tool_failure_message(output: str) -> str | None:
    """从工具结果文本里取出失败说明；不是失败信封时返回 `None`。

    工具有两种结果（`agent/tools/results.py`）：成功回产出文本，失败回
    `<tool_error code="…">说明</tool_error>`。水合的 `tool_call` part 需要
    `ok` 与 `summary` 两个字段，而事件流当年的取法是：成功取产出文本，失败取
    信封内的说明（不含信封本身）。这里照同一条取法，好让水合出来的
    `summary` 与当时事件流里的那一句一致。

    判据要求开闭标签都在（而不只是开头匹配）：一个成功工具的产出完全可能以
    `<tool_error code="` 开头（例如它回的是「关于 tool_error 的说明」）。只认开头
    会把一次成功的调用误报成失败，而 `ok` 错了会让界面显示一个红色的失败标记——
    错误的失败比缺一个失败更糟，因为它把成功说成了失败。

    Args:
        output: 工具结果条目的 `output` 字段。

    Returns:
        失败说明；不是完整失败信封时返回 `None`（即调用成功）。
    """
    stripped = output.lstrip()
    if not stripped.startswith(_TOOL_ERROR_OPEN):
        return None
    if not stripped.endswith(_TOOL_ERROR_CLOSE):
        return None
    rest = stripped[len(_TOOL_ERROR_OPEN) :]
    separator = rest.find(_TOOL_ERROR_CODE_END)
    if separator < 0:
        return None
    body = rest[separator + len(_TOOL_ERROR_CODE_END) :]
    return body[: -len(_TOOL_ERROR_CLOSE)]


def is_injected_message(item: Mapping[str, object]) -> bool:
    """判断一条 `user` 消息是不是应用注入的上下文（而不是使用者写的）。

    判据是内容前缀（见 `INJECTED_MESSAGE_PREFIXES` 的边界说明）。用 `lstrip`
    与基座侧 `_last_content` 的判法一致——基座渲染的信封都从行首开始，但前置空行
    不该让判定失效。

    只对 `user` 角色成立：助手消息永远是模型的产出，没有「注入的助手消息」。
    """
    if item.get("role") != _ROLE_USER:
        return False
    content = item.get("content")
    if not isinstance(content, str):
        return False
    stripped = content.lstrip()
    return any(stripped.startswith(prefix) for prefix in INJECTED_MESSAGE_PREFIXES)


def is_displayable_user_message(item: Mapping[str, object]) -> bool:
    """这条条目是不是「使用者的消息」（会被水合、会参与标题与预览）。

    判据是角色而不是 `type`：实测使用者消息落库后是
    `{"role": "user", "content": "…"}`——没有 `type` 字段（`runner.py` 里
    `new_items.append({"role": "user", "content": request.user_input})` 就是它的来源，
    注入消息同形）。助手消息才有 `type: "message"`。

    因此以 `type` 为判据会让每一条使用者消息被当成「认不出的条目」跳过：
    会话列表的全部标题都回退成默认值、历史里只剩助手的话。这一条是实测修正
    （`test_hydration_excludes_injected_messages` 等用例第一时间抓到）。

    容忍 `type: "message"` 的写法：若将来 SDK 给使用者消息补上该字段，判定不受影响
    ——读路径在形状上宽容、在语义上严格。
    """
    if item.get("role") != _ROLE_USER:
        return False
    kind = item_type(item)
    if kind is not None and kind != ITEM_TYPE_MESSAGE:
        return False
    return not is_injected_message(item)


def is_displayable_assistant_message(item: Mapping[str, object]) -> bool:
    """这条条目是不是「助手的文本消息」。"""
    if item.get("role") != _ROLE_ASSISTANT:
        return False
    kind = item_type(item)
    return kind is None or kind == ITEM_TYPE_MESSAGE


# ---------------------------------------------------------------------------
# 水合：条目序列 → 消息序列
# ---------------------------------------------------------------------------


class _Hydration:
    """水合过程的累积状态：把条目序列折成消息序列。

    单独成类而不是一个长函数内的局部变量：一次水合要维护三个互相牵制的状态
    （当前助手消息的 parts、它的行标识、尚未配到结果的工具调用下标），而「助手侧
    条目」有四种、各自都要在收束时机上与使用者消息交互。摊在一个函数里时，
    每个分支都要记得「必要时先 flush、必要时记 first_row_id」，漏一处就是一条
    静默错误（而且只在某种条目组合下才出现）。分成方法后每个分支只管自己，
    收束与行标识由一个统一入口负责。
    """

    def __init__(self) -> None:
        """起一个空的水合过程。"""
        self.messages: list[HydratedMessage] = []
        self._parts: list[MessagePart] = []
        self._first_row_id: int | None = None
        #: 尚未配到结果的工具调用：call_id → parts 下标。工具结果总在调用之后到达，
        #: 因此 part 先占位、拿到结果再回填。
        self._pending_calls: dict[str, int] = {}

    def _start_assistant(self, row_id: int) -> None:
        """记下当前助手消息的行标识（只记第一个贡献条目——它就是这条消息的 id）。"""
        if self._first_row_id is None:
            self._first_row_id = row_id

    def flush(self) -> None:
        """收束当前助手消息；没有可呈现的 part 时不产生消息。

        被打断的调用（有调用、无结果）在这里补成失败 part，而不是让它从历史里消失
        ——依据是 `_ToolCallTracker` 在运行触顶或取消时也会给它们补一条结束事件。
        """
        for index in self._pending_calls.values():
            part = self._parts[index]
            if isinstance(part, dict) and part.get("type") == "tool_call":
                part["ok"] = False
                part["summary"] = INTERRUPTED_TOOL_SUMMARY
        if self._parts and self._first_row_id is not None:
            self.messages.append({"id": str(self._first_row_id), "role": _ROLE_ASSISTANT, "parts": self._parts})
        self._parts = []
        self._first_row_id = None
        self._pending_calls = {}

    def add_user(self, stored: StoredItem) -> None:
        """收一条使用者消息；读不出文本时记警告并跳过。"""
        text = message_text(stored.data)
        if text is None:
            # 使用者消息必然有正文（`RunRequest.user_input` 与回答渲染都写文本）。
            # 读不出文本只可能是形状漂移；记下来，不产生一条空消息。
            logger.warning("水合跳过一条读不出文本的使用者消息：行=%s", stored.row_id)
            return
        self.flush()
        self.messages.append({"id": str(stored.row_id), "role": _ROLE_USER, "parts": [{"type": "text", "text": text}]})

    def add_assistant_text(self, stored: StoredItem) -> None:
        """收一条助手文本消息（content 是分片数组，可能只有一个部件）。"""
        texts = _content_parts(stored.data)
        if not texts:
            return
        self._start_assistant(stored.row_id)
        self._parts.extend(TextPart(type="text", text=text) for text in texts)

    def add_reasoning(self, stored: StoredItem) -> None:
        """收一条思考条目。"""
        text = reasoning_text(stored.data)
        if text is None:
            return
        self._start_assistant(stored.row_id)
        self._parts.append(ReasoningPart(type="reasoning", delta=text))

    def add_tool_call(self, stored: StoredItem) -> None:
        """收一条工具调用，并登记它的 parts 下标以待结果回填。"""
        item = stored.data
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            logger.warning("水合跳过一条没有调用标识的工具调用：行=%s", stored.row_id)
            return
        name = item.get("name")
        self._start_assistant(stored.row_id)
        self._pending_calls[call_id] = len(self._parts)
        self._parts.append(
            ToolCallPart(
                type="tool_call",
                # 名字缺失时用具名占位而不是空串：空串在界面上是一个「没有名字的工具」，
                # 与「名字读不出来」无法区分。
                tool_name=name if isinstance(name, str) and name else UNKNOWN_TOOL_NAME,
                ok=True,
                summary="",
            )
        )

    def add_tool_output(self, stored: StoredItem) -> None:
        """用工具结果回填对应的调用 part（`ok` 与 `summary`）。"""
        item = stored.data
        output = item.get("output")
        if not isinstance(output, str):
            logger.warning("水合跳过一条读不出产出的工具结果：行=%s", stored.row_id)
            return
        call_id = item.get("call_id")
        index = self._pending_calls.pop(call_id, None) if isinstance(call_id, str) else None
        if index is None:
            # 没有对应调用的结果：SDK 存储里不应出现（结果由调用派生）。
            logger.warning("水合跳过一条找不到对应调用的工具结果：行=%s", stored.row_id)
            return
        part = self._parts[index]
        if isinstance(part, dict) and part.get("type") == "tool_call":
            failure = tool_failure_message(output)
            part["ok"] = failure is None
            part["summary"] = (output if failure is None else failure)[:TOOL_SUMMARY_MAX_CHARS]


def build_messages(items: Sequence[StoredItem]) -> list[HydratedMessage]:
    """把会话真源的条目序列翻成契约第 3.3 节的消息序列。

    分组规则（一次运行的产出合成一条助手消息）：助手侧的条目——思考、工具调用与
    结果、助手文本——属于同一条助手消息的 `parts`，直到下一条使用者消息出现
    才收束。依据是第 7 节把六种 part 都定义为「消息 content 的序列化，与流式事件
    同源同形」：流式期间这些 part 累加到当前这一条助手消息上，水合必须给出同一个
    形状，否则刷新前后同一段对话的消息条数会变。

    被跳过的条目（各有明确判据，都不静默）：

    - 应用注入消息（`is_injected_message`）：使用者从未见过它们，呈现它们等于把
      应用上下文冒充成对话内容；
    - 认不出的条目类型：记警告——SDK 升级新增条目类型时，历史会缺内容而不是整个
      加载失败（读路径上「缺一段」比「全空」更接近事实，但必须留下可查的痕迹）；
    - 读不出文本的助手消息（例如只有一次工具调用、没有正文）：不产生空 part。

    `candidate` 无需处理：它只在事件流里产出（`ToolResult.candidates`），
    不写进会话存储，因此结构上不可能出现在这里。

    Args:
        items: 按时间正序排列的条目（排序由 `session_repository` 负责）。

    Returns:
        水合后的消息列表，顺序即真源顺序。
    """
    hydration = _Hydration()
    for stored in items:
        item = stored.data
        kind = item_type(item)
        role = item.get("role")

        # 消息分支按角色判别，不按 `type`：使用者消息没有 `type` 字段（见
        # `is_displayable_user_message` 的说明）。放在前面是为了让「认不出的类型」
        # 只可能在既没有可识别角色、也不是已知类型时命中。
        if kind is None or kind == ITEM_TYPE_MESSAGE:
            if role == _ROLE_USER:
                if not is_injected_message(item):
                    hydration.add_user(stored)
            elif role == _ROLE_ASSISTANT:
                hydration.add_assistant_text(stored)
            else:
                logger.warning("水合跳过认不出的条目类型：类型=%s 行=%s", kind, stored.row_id)
        elif kind == ITEM_TYPE_REASONING:
            hydration.add_reasoning(stored)
        elif kind == ITEM_TYPE_FUNCTION_CALL:
            hydration.add_tool_call(stored)
        elif kind == ITEM_TYPE_FUNCTION_CALL_OUTPUT:
            hydration.add_tool_output(stored)
        else:
            logger.warning("水合跳过认不出的条目类型：类型=%s 行=%s", kind, stored.row_id)

    hydration.flush()
    return hydration.messages


# ---------------------------------------------------------------------------
# 标题与预览
# ---------------------------------------------------------------------------

#: 标题取的字符数（裁决 5：首条使用者消息取前 24 字符）。
TITLE_MAX_CHARS = 24

#: 没有任何使用者消息时的标题回退（裁决 5）。
TITLE_FALLBACK = "新对话"

#: 截断标记。用单个省略号字符而不是三个点：它在窄屏上占一个字符宽度。
TITLE_ELLIPSIS = "…"

#: 末条预览的字符数上界（CORE-11）。设计文档没有固定这个数——第 3.2 节只说
#: 「末条消息预览」，列表页把「单行截断」归给前端（`.list-row` 的一行）。
#: 因此这里取一个够长到能辨认、又不会让列表响应体膨胀的上界；前端仍按自己的
#: 单行宽度截断。
PREVIEW_MAX_CHARS = 60

#: 参与标题回退判定的空白字符。标题是单行文本，换行与制表必须折成空格，
#: 否则一条含换行的消息会把列表行撑破。
_WHITESPACE_RUN = " \t\r\n\f\v"


def normalize_inline_text(text: str) -> str:
    """把一段文本折成单行：连续空白折成一个空格，并去掉首尾空白。"""
    normalized = text
    for character in _WHITESPACE_RUN[1:]:
        normalized = normalized.replace(character, " ")
    while "  " in normalized:
        normalized = normalized.replace("  ", " ")
    return normalized.strip()


def truncate(text: str, limit: int) -> str:
    """按字符截断并加省略号；不超长时原样返回。"""
    if len(text) <= limit:
        return text
    return text[:limit] + TITLE_ELLIPSIS


def build_title(text: str | None) -> str:
    """由首条使用者消息生成会话标题（裁决 5）。

    规则：折成单行 → 取前 `TITLE_MAX_CHARS` 字符 → 超长时加省略号；没有文本
    （或全是空白）时回退 `TITLE_FALLBACK`。

    标题不落库：它是从会话真源派生的显示值。存一列标题会造出第二个可写的
    真源——消息改了标题不会跟着改，两者冲突时无法判断谁对（与「默认对象」不另存
    字段同一种取向，支持对象第 6 节）。

    Args:
        text: 首条使用者消息的文本；该会话没有使用者消息时为 `None`。

    Returns:
        可直接呈现的标题。
    """
    if text is None:
        return TITLE_FALLBACK
    inline = normalize_inline_text(text)
    if not inline:
        return TITLE_FALLBACK
    return truncate(inline, TITLE_MAX_CHARS)


def build_preview(text: str | None) -> str | None:
    """由末条消息生成预览。没有可呈现的文本时返回 `None`。

    `None` 而不是空串：契约第 3.2 节把该字段定义为「`… 或 null`」，列表页对缺失
    的处理是不渲染该行（第 36 行）。空串会让前端渲染一行空白。
    """
    if text is None:
        return None
    inline = normalize_inline_text(text)
    if not inline:
        return None
    return truncate(inline, PREVIEW_MAX_CHARS)


def first_user_message_text(items: Sequence[StoredItem]) -> str | None:
    """取首条使用者消息的文本；没有则返回 `None`。

    调用方只送来该会话的前若干条条目（`session_repository` 的扫描上界）：
    注入消息总在它之后同批落库，因此扫描范围远大于一条注入序列的长度。
    """
    for stored in items:
        if not is_displayable_user_message(stored.data):
            continue
        text = message_text(stored.data)
        if text is not None:
            return text
    return None


def last_message_text(items: Sequence[StoredItem]) -> str | None:
    """取末条可呈现消息的文本；没有则返回 `None`。

    只认使用者与助手的消息条目：思考段与工具结果不是「消息」，拿它们当预览会让
    列表显示一段思维过程或工具输出。

    入参是正序（与 `build_messages` 一致——`session_repository` 的读取一律返回
    正序），因此这里从末尾往回找。末尾那几条通常是思考段与工具结果，正是要跨过的。
    """
    for stored in reversed(items):
        item = stored.data
        if not (is_displayable_user_message(item) or is_displayable_assistant_message(item)):
            continue
        text = message_text(item)
        if text is not None:
            return text
    return None


__all__ = [
    # 条目类型词表
    "ITEM_TYPE_FUNCTION_CALL",
    "ITEM_TYPE_FUNCTION_CALL_OUTPUT",
    "ITEM_TYPE_MESSAGE",
    "ITEM_TYPE_REASONING",
    # 注入信封
    "INJECTED_MESSAGE_PREFIXES",
    # part 形状
    "MessagePart",
    "ReasoningPart",
    "TextPart",
    "ToolCallPart",
    # 消息与条目
    "HydratedMessage",
    "StoredItem",
    # 摘要与预览
    "INTERRUPTED_TOOL_SUMMARY",
    "PREVIEW_MAX_CHARS",
    "TITLE_ELLIPSIS",
    "TITLE_FALLBACK",
    "TITLE_MAX_CHARS",
    "TOOL_SUMMARY_MAX_CHARS",
    "UNKNOWN_TOOL_NAME",
    # 解析
    "build_messages",
    "build_preview",
    "build_title",
    "first_user_message_text",
    "is_displayable_assistant_message",
    "is_displayable_user_message",
    "is_injected_message",
    "item_type",
    "last_message_text",
    "message_text",
    "normalize_inline_text",
    "parse_item",
    "reasoning_text",
    "tool_failure_message",
    "truncate",
]
