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
（`test_accounts_session_items.py` 的 `test_text_part_types_agree_across_the_two_parsers`）；
引用注解的判别键与形状同理，对 `agent/runtime/session_annotations.py` 的写侧
（`test_citation_annotation_constants_agree_across_the_two_parsers`）。
两侧不能合并成一份：`modules/*` 不得 import `agent/*`（同上），故相等关系只能由用例守。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias, TypedDict, TypeGuard

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
    # 当前时间（2026-10-06 随 T27 加入，产出口是
    # `agent/runtime/runner.py` 的 `_render_current_time`）。不登记它会被当成使用者
    # 消息：会话标题会静默变成一段时间戳。产出口与清单的一致性由
    # `tests/test_agent_runtime.py` 的用例机械核对。
    "<current_time>",
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
# 提问（`ask_user`）的重建
# ---------------------------------------------------------------------------

#: 提问工具名。与 `agent/runtime/ask_user_tool.ASK_USER_TOOL_NAME` 同值：
#: `modules/*` 不得 import `agent/*`（项目结构设计第 7 节），故只能是字面量；
#: 两处相等由 `tests/test_accounts_session_items.py` 机械核对。
ASK_USER_TOOL_NAME = "ask_user"

#: `ask_user` 成功时的工具产出原文。与 `ask_user_tool.handler` 返回的 `text` 逐字相同。
#:
#: 为什么用它当「这次提问真的产出了」的判据（而不是只看参数能不能解析出题）：
#: `AskUserArgs` 的校验发生在工具层，一次**参数不合法**的调用会得到
#: `<tool_error code="tool_invalid_arguments">…</tool_error>`，而基座的 `QuestionGate`
#: 刻意不因这种调用结束运行、也不发 `question` 事件（见 `agent/runtime/assembly.py`
#: 的 `QuestionGate` 说明）。若只看参数形状，水合会给一张「当时从未呈现给使用者」的
#: 提问卡——那正是本模块禁止的伪造。因此判据必须取自产出侧。
#:
#: 边界（如实写明）：这句原文若被改写，判据会失效（提问在水合里再次消失）。两处
#: 相等由 `tests/test_accounts_session_items.py` 直接比对常量与 handler 的返回值守住
#: ——它比「记一句注释」强：改文案的人会立刻看到一条红。
ASK_USER_SUCCESS_OUTPUT = "已向使用者发出提问，本次运行到此结束；回答会作为下一条消息到达。"

#: 应急行动卡的工具名。与 `tools/emergency_card.py` 注册的名字同值；理由同上
#: （`modules/*` 不得 import `tools/*`）。台账（`NOT_REBUILT_PARTS`）用它陈述
#: 「载荷其实可重建、只是本包未做」——这个名字一旦写错，那份说明就成了新的过期断言，
#: 因此它的存在由 `tests/test_accounts_session_items.py` 与注册清单核对。
EMERGENCY_ACTION_CARD_TOOL_NAME = "emit_emergency_action_card"

# ---------------------------------------------------------------------------
# 「这一组题被作答了吗」的判据（2026-10-06 随 T31 加入）
# ---------------------------------------------------------------------------

#: 一组回答渲染出的正文表头。与 `surfaces/consult/answers.ANSWERS_HEADER` 逐字相同。
#:
#: 为什么在这里再写一份字面量：`modules/*` 不得 import `surfaces/*`（项目结构设计第 7 节），
#: 因此那一处是**产出**、这一处是**判据的输入端**（水合要认出「这条消息是对提问的作答」）。
#: 两处相等由 `tests/test_accounts_session_items.py` 直接比对常量守住——改文案的人会立刻
#: 看到一条红，而不是让「已作答」静默变成「从未作答」（那会让使用者重复作答）。
ANSWERS_HEADER = "以下是对提问的作答"

#: 压缩检查点的开头标签。与 `agent/context/window.COMPACTED_SUMMARY_TAG` 同值；理由同上
#: （`modules/*` 不得 import `agent/*`）。两处相等由用例机械核对。
COMPACTED_SUMMARY_TAG = "<compacted-summary>"

#: 压缩检查点的结尾标签。与 `agent/context/window.COMPACTED_SUMMARY_CLOSE_TAG` 同值；
#: 理由同上。**判据要求两端都在**（见 `_is_compaction_checkpoint`）：只看开头会把
#: 一句使用者写的、以该标签开头的普通消息误当成复述块。
_COMPACTED_SUMMARY_CLOSE_TAG = "</compacted-summary>"

#: 水合侧专有的提问 part 类型（契约第 7 节的第七行）。
#:
#: 为什么**不**复用 `question`（2026-10-06，T31 裁决）：`question` 是**事件**载荷的 part 类型
#: （通用基座 7.2 节），它按定义描述「刚刚向使用者发出的、尚未作答的提问」——发出即结束运行，
#: 因此它的载荷里**不可能有**「已作答」。而「已作答」是**回看时**的事实，只对水合路径有意义。
#: 把回看侧的字段塞进流出侧载荷，是把两个时刻的事实挤进一个结构（且会撞上三条逐字断死
#: 字段集合的守卫）。用两个线格式 part 类型分开之后：`question` 的载荷一字未动，
#: `answered` 只出现在水合响应里。
#:
#: ⚠ 类型必须是 `Final[QuestionRecordType]`（而不是裸 `str`，也不能在 `Literal[...]` 里
#: 引用它）。这不是风格问题，两者都会**静默**破坏 `MessagePart` 判别联合的收窄：
#:
#: - 裸 `str`：`part["type"] == PART_TYPE_QUESTION_RECORD` 无法把联合收窄到
#:   `QuestionRecordPart`，于是**所有**既有用例里「先断言 type、再取该 part 独有的键」
#:   都报 `TypedDict "TextPart" has no key ...`（实测 26 条）；
#: - `Literal[PART_TYPE_QUESTION_RECORD]`：mypy 直接报 `valid-type`，后果同上（实测 55 条）。
#:
#: 两种写法都能跑通运行时、都是「看起来更 DRY」的写法，因此这个坑只有 mypy 看得见。
QuestionRecordType: TypeAlias = Literal["question-record"]
PART_TYPE_QUESTION_RECORD: Final[QuestionRecordType] = "question-record"

#: 水合提问的 `batch_id` 前缀。`batch_id` 由工具侧生成、**不落库**，因此水合不能取回
#: 原值；用调用标识派生一个稳定值。
#:
#: 为什么用前缀而不是裸 `call_id`：`batch_id` 是回答回传时的关联键（契约 4.1），
#: 一个可见来源的前缀让「这个批次是水合重建的」在排障时可辨——原值不会以
#: `hydrated-` 开头，两者不会混淆。前缀同时保证与任何真实 `batch_id`
#: （`uuid4().hex`）都不相等。
QUESTION_BATCH_ID_PREFIX = "hydrated-"

#: 提问 part 里 `options` 的元素形状。选项与题面字段名取自通用基座第 7.2 节。
_QUESTION_ITEM_ID_KEY = "id"
_QUESTION_ITEM_PROMPT_KEY = "prompt"
_QUESTION_ITEM_OPTIONS_KEY = "options"
_QUESTION_ITEM_ALLOW_SKIP_KEY = "allow_skip"
_QUESTION_OPTION_DESCRIPTION_KEY = "description"

#: 水合提问时的题数上界（CORE-11）。工具侧一次问出的题数是小规模（`ask_user` 的描述
#: 要求「一次问完」），这里兜的是**落库条目被替换成超大载荷**的情形——一次水合不该
#: 因为一条历史调用把响应体撑大。超界的调用整体跳过并记警告，不截断成「少几道题的
#: 提问卡」：一张缺题的卡会让使用者以为自己漏看了什么。
QUESTION_ITEMS_MAX = 32

#: 题干与选项文案的长度上界（同上）。逐字段截断而不是整体跳过：一条超长的题干仍然
#: 是一道能作答的题，而丢掉整组提问的代价更大。
QUESTION_TEXT_MAX_CHARS = 500
QUESTION_OPTION_LABEL_MAX_CHARS = 200
QUESTION_OPTION_DESCRIPTION_MAX_CHARS = 500

# ---------------------------------------------------------------------------
# 应急行动卡（`action_card`）的重建（2026-10-06 随 T32 加入）
#
# 载荷与提问同源：`emit_emergency_action_card` 的参数逐字保存在
# `function_call.arguments` 里，配对 `function_call_output.output` 是它的回执。
# 但**两处与提问不同**，它们决定了本节的实现形状，也都是实测读数（见报告 §2.4）：
#
# 1. **`card_id` 不需要派生**（原件说它「需要与 batch_id 同样的派生处理」——
#    那句前提是错的）：`tools/emergency_card.py` 的成功回执**本身**是
#    `{"card_id": "<uuid4().hex>", "state": "emitted"}`，即**真值就在回执里**
#    并逐字落库（同库旁证：`create_support_object` 的 `{"support_object_id": …}`
#    等 7 个工具的回执都是逐字 JSON 落库）。因此这里**取回真值**，而不是另造一个：
#    派生值会让**同一张卡**在流出侧与回看侧拿到两个不同的 id，于是
#    「刷新前后是不是同一张卡」失去答案（前端的旧卡失效判定正是比 `card_id`）。
# 2. **`title` 不在参数里**：`EmitEmergencyActionCardArgs` 只有 `sections` /
#    `states` / `annotations` 三个字段，标题由工具侧的常量给。`modules/*` 不得
#    import `tools/*`（项目结构设计第 7 节），因此这里是字面量；两处相等由
#    `tests/test_accounts_session_items.py` 直接比对常量守住（与
#    `ASK_USER_SUCCESS_OUTPUT`、`COMPACTED_SUMMARY_TAG` 同法）。
# 3. **`annotations` 的形状不对称**：落库的参数是 `{line_ref, source, confidence}`，
#    线格式是 `{target, kind}`（`kind = "来源:置信"`）。水合必须做与工具侧
#    `_encode_annotation_kind` 同一个转换，否则前端读到的是两个不存在的字段。
#    详见 :func:`_card_annotations` 的说明（含为什么只需分隔约定、不需词表）。
#
# ⚠ **`annotations` 的 `kind` 要在这里**编**出来**（不是解码，也不能原样搬运）——
# 这是本包唯一一处「编码约定必须在 `modules/*` 里再写一份」的地方，而它有一处
# **实测纠正**：我第一版按「原样搬运即同形」实现，探针立刻证明**产不出任何卡片**
# （见报告 §4.2）。原因是落库的 `arguments` 是**输入形状**、线格式是**信封形状**：
#
#     参数（落库）                    线格式（事件与水合 part）
#     {line_ref: int,                  {target: str,
#      source: str, confidence: str}    kind: str}   # kind = f"{source}:{confidence}"
#
# 工具侧 handler 用 `_encode_annotation_kind` 做这个转换，因此水合要做同一个。
# ★ **但它只需要分隔约定，不需要产品侧词表**——这是与原件那个
# 「要么在装配处注入解码器，要么把编码规则下沉」不同的第三条路：编码是**纯语法拼接**，
# `source`/`confidence` 的合法值域**不在这里复述**（越界取值由消费侧可见地丢弃：
# 前端 `decodeAnnotation` 查不到显示名就返回 `null`，该条标注计入 `droppedAnnotations`）。
# 复述词表会让产出侧将来扩词表时**水合静默停止产出卡片**——正是本包要修的缺陷换张脸回来。
#
# `title` 不在参数里（`EmitEmergencyActionCardArgs` 只有 sections/states/annotations
# 三个字段），由工具侧常量给 ⇒ 这里只能是字面量 + 用例绑定（同 `ASK_USER_SUCCESS_OUTPUT`）。
# ---------------------------------------------------------------------------

#: 「来源:置信」编码的分隔符。与 `tools/emergency_card.py` 的 `_encode_annotation_kind`
#: 同值（`f"{source}:{confidence}"`）；两处相等由用例跑真实工具守住。
_ANNOTATION_KIND_SEPARATOR = ":"

#: 行动卡 part 类型（契约第 7 节的 `action_card` 行）。
#:
#: ⚠ 与 `PART_TYPE_QUESTION_RECORD` 同一条理由：必须是 `Final[ActionCardType]`
#: （而不是裸 `str`，也不能在 `Literal[...]` 里引用它），否则会**静默**破坏
#: `MessagePart` 判别联合的收窄（裸 `str` 实测 26 条报红，`Literal[常量]` 是
#: mypy 的 `valid-type`、实测 55 条）。
ActionCardType: TypeAlias = Literal["action_card"]
PART_TYPE_ACTION_CARD: Final[ActionCardType] = "action_card"

#: 引用 part 类型（契约第 7 节的 `citation` 行）。同一条 `Final[...]` 纪律，理由同上。
CitationType: TypeAlias = Literal["citation"]
PART_TYPE_CITATION: Final[CitationType] = "citation"

#: 引用载荷所在的键：助手正文分片（`output_text`）的 `annotations` 数组。
#: 与 `agent/runtime/session_annotations.py` 的写侧同义——载荷是**消息 content 的一部分**
#: （设计《咨询对话界面》第 5 节），因此它住的正是 `content` 里那个分片自己的注解字段，
#: 而不是另造的条目或外挂索引。
_ANNOTATIONS_KEY = "annotations"

#: 引用注解的判别键取值。`annotations` 数组是**共用**的：真实的辅助注解
#: （例如 `url_citation`）也住在里面，因此必须按判别键取值，不能把整个数组当引用。
#: 与 `agent/runtime/session_annotations.py` 的 `CITATION_ANNOTATION_TYPE` 同值，
#: 两处相等由用例直接比对常量守住（同 `_TEXT_PART_TYPES` 那条纪律）。
_CITATION_ANNOTATION_TYPE = "citation"

#: 一次最多读回多少条引用。**必须与写侧
#: （`agent/runtime/session_annotations.py` 的 `CITATION_ANNOTATION_MAX`）相等**，
#: 且那个值由**写侧主动执行**（写侧先裁）——
#: 这是本模块上一版的一处真实缺陷的修法：当时读侧有 20 条硬截断、写侧**无上界**，
#: 于是「一次运行多次检索、累计 > 20 条」时读侧会**静默丢掉**第 21 条起
#: （复查者实测端到端：写 45 → 水合 20，丢 25 条、零日志）。
#:
#: 读侧保留这个上界是为了兜住**外部写入**（伪造的条目、迁移来的旧数据）——
#: 正常路径上写侧已经裁过，因此这里**不该**再裁到任何东西；
#: 真裁到了就说明写侧的上界失效，故这里**必须留日志**（静默截断正是本缺陷的形态）。
_CITATION_ANNOTATION_MAX = 200

#: 引用载荷里承载「指向的业务标识」的键。与
#: `agent/runtime/session_annotations.py` 的 `ANNOTATION_REFERENCE_KEY` 逐字相同——
#: 两处相等由用例直接比对常量守住（`modules/*` 不得 import `agent/*`，故为字面量；
#: 此处刻意不 import 是为了让本模块的解析只依赖已读出的条目形状，
#: 与它对 SDK 持久化格式的其它解析同一取向）。
CITATION_REFERENCE_KEY = "reference"

#: 卡片的标题。与 `tools/emergency_card.py` 的 `CARD_TITLE` 逐字相同；理由见上
#: （`modules/*` 不得 import `tools/*`）。它**不在参数里**，因此水合只能取这份
#: 字面量——两处相等由用例直接比对常量守住。
ACTION_CARD_TITLE = "现场行动卡"

#: 工具**成功**回执里的状态标记。取自 `tools/emergency_card.py` 的
#: `json.dumps({"card_id": …, "state": "emitted"})`。
#:
#: 为什么它是判据的一半（而不是只看「参数能不能解析出卡片」）：参数不合法的调用
#: 得到 `<tool_error code="tool_invalid_arguments">…`，**它从未向使用者呈现过任何
#: 东西**（`ToolSpec._parse` 在解析期就把它变成失败，`ToolResult` 从不构造）。
#: 只看参数形状会让水合造出一张「当时从未呈现给使用者的卡」——那是伪造。
#: 判据的另一半是参数本身（见 :func:`action_card_part`），**两条缺一不可**。
#: 两处相等由用例跑**真实工具**并断言其回执通过本判据守住（同 T31 的
#: `test_ask_user_success_output_matches_the_tool_handler`）。
ACTION_CARD_EMITTED_STATE = "emitted"

#: 卡片的七个分节键，顺序即呈现顺序。与 `tools/emergency_card.py` 的 `SECTION_KEYS`
#: 逐字相同（含顺序）；`modules/*` 不得 import `tools/*`，故为字面量，两处相等由用例守住。
#:
#: 为什么必须知道顺序、且必须按它重排：工具侧 handler 在发卡前按这七个键
#: **规范化顺序**（`sorted(..., key=SECTION_KEYS.index)`），因此流向事件的载荷是这个
#: 顺序；水合要不产出「与事件不同形」的 part，就必须同样重排。顺序同时是
#: `annotations[].target`（「按七节顺序摊平后的 1 起序号」）的解释依据——前端
#: `domain/actionCard.ts` 的 `SECTION_ORDER` 与它同源。
#:
#: 它同时承担「七节齐全」的检查：缺节或重复键 ⇒ **不产出 part**（见 §边界）。
ACTION_CARD_SECTION_KEYS: tuple[str, ...] = (
    "status",
    "communicate",
    "do_now",
    "avoid",
    "medical_checks",
    "safety",
    "when_to_escalate",
)

#: 卡片载荷的长度/条数上界（CORE-11：进入响应的文本必须有界）。
#:
#: 与提问路径的取法**相反**：提问对超长题干是**逐字段截断**（一条被截断的题干仍然
#: 是一道能作答的题），这里一律**整体跳过并记警告**。理由是这张卡的语义与题干不同：
#: 「不要突然触碰」截成「不要突然触」会把一条安全动作说反；而一张缺行/少字的行动卡
#: 比「历史里没有这张卡」更危险。**宁可不产出，也不产出半截卡片**（见
#: :data:`NOT_REBUILT_PARTS` 沿用的同一条纪律）。
#:
#: 它们同时兜住「落库条目被替换成超大载荷」：一次水合不该因为一条历史调用把响应体撑大。
ACTION_CARD_TEXT_MAX_CHARS = 500
ACTION_CARD_LINES_TOTAL_MAX = 128
#: 状态与标注的条数上界。**刻意大于产出侧的词表规模**（状态至多四个键、标注无上限）：
#: 这里的判据只兜「形状/规模异常」，不复述产品侧词表——复述会让产出侧扩词表时
#: 水合静默停止产出卡片（那正是本包要修的那个缺陷换了张脸回来）。未知的键与取值
#: **原样搬运**（前端对未知键的处置是忽略，对未知取值是丢弃该条并计数，都可见）。
ACTION_CARD_STATES_MAX = 16
ACTION_CARD_ANNOTATIONS_MAX = 256


# ---------------------------------------------------------------------------
# parts 形状（HTTP 与 SSE 契约第 7 节的四个可重建 part）
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


class QuestionOptionPart(TypedDict, total=False):
    """提问选项 part。形状归通用基座第 7.2 节 `options` 的元素。"""

    label: str
    description: str


class QuestionItemPart(TypedDict):
    """提问里的一道题。形状归通用基座第 7.2 节 `items` 的元素。"""

    id: str
    prompt: str
    options: list[QuestionOptionPart]
    allow_skip: bool


class QuestionPart(TypedDict):
    """提问**事件**的 part 形状（归通用基座第 7.2 节；水合不产出它）。

    保留它而不是删掉：本模块的**读数**要能说清「事件侧的形状是什么」，
    并由用例逐字断死（`test_question_event_part_shape_stays_wire_exact`）。
    **⚠ 它不在 `MessagePart` 联合里**（水合产出的是 `QuestionRecordPart`）——
    一个没有生产者的联合成员正是本模块专门防的「过期断言」形态。
    """

    type: Literal["question"]
    batch_id: str
    items: list[QuestionItemPart]


class QuestionRecordPart(TypedDict):
    """水合侧专有的提问记录 part（契约第 7 节的 `question-record` 行）。

    ★ 与 :class:`QuestionPart` 的唯一差别是多一个 `answered`（三态）。

    为什么分两个线格式 part 类型（2026-10-06，T31）：
    `question` 是**流出侧**的载荷——它按定义描述「刚向使用者发出、尚未作答」的提问
    （基座 7.2 节：发出即结束运行），因此它的载荷里**不可能**有「已作答」；
    而「已作答」是**回看侧**的时间点事实，只对水合路径有意义。把回看侧的字段塞进
    流出侧载荷，等于把两个时刻的事实挤进一个结构 —— 且会撞上三条逐字断死字段集合
    的守卫。分成两个类型之后：`question` 的载荷一字未动，`answered` 只出现在水合响应里。

    `answered` 是**三态**而不是 bool：

    - `True`  ⇒ 已作答（只读记录，禁止再次提交）；
    - `False` ⇒ 未作答（可作答，这正是本包修的那条：刷新后仍能补答）；
    - `None`  ⇒ **无法判定** ⇒ 前端按只读呈现（**fail-closed**）。

    为什么要 `None`（而不是把无法判定的一律归成 `False`）：猜成「可作答」会让使用者
    对同一组题作答两次（新的「看起来像成功」）；猜成「只读」最多少修一点。
    **失败方向要选安全的那边。**

    `batch_id` 的派生规则与 T27 一致（`hydrated-<call_id>`），本包不动。
    """

    # ⚠ 这里必须引用 `QuestionRecordType`（那个 `TypeAlias`）而不是内联字面量：
    # 它保证「常量」与「TypedDict 的 type 字段」是**同一个**字面量类型，
    # 两边的一致性由 mypy 机械保证（内联字面量写错一个字符时
    # `question_record_part` 的构造会被 mypy 判红）。
    type: QuestionRecordType
    batch_id: str
    items: list[QuestionItemPart]
    answered: bool | None


class ActionCardSectionPart(TypedDict):
    """行动卡的一个分节。形状归通用基座第 7.3 节（`{key, heading, lines}`）。"""

    key: str
    heading: str
    lines: list[str]


class ActionCardStatePart(TypedDict):
    """行动卡的一个键值状态。形状归通用基座第 7.3 节（`{key, value}`）。"""

    key: str
    value: str


class ActionCardAnnotationPart(TypedDict):
    """行动卡的一条逐条标注。形状归通用基座第 7.3 节（`{target, kind}`）。

    `target` 是「按七节顺序摊平后的 1 起序号」的**字符串**（不是 int：基座信封把它
    定成 `str`，`tools/emergency_card.py` 用 `str(annotation.line_ref)` 产出）。
    `kind` 是「来源:置信」的编码串（同处 `_encode_annotation_kind`）。

    ⚠ 这两个字段在**落库的参数里并不存在**（那里是 `{line_ref, source, confidence}`）
    —— 转换由 :func:`_card_annotations` 做，理由见该函数。
    """

    target: str
    kind: str


class ActionCardPart(TypedDict):
    """行动卡 part（契约第 7 节的 `action_card` 行 + 通用基座第 7.3 节的通用信封）。

    ★ 与**事件侧**的 `action_card` 载荷**逐字同形**（五个字段：`card_id` /
    `title` / `sections` / `states` / `annotations`）—— 与提问那一对
    （`question` / `question-record`）**刻意不同**。

    为什么不另立一个「水合侧专有」的 part 类型（T31 对提问的做法）：

    - 提问分两个类型，是因为「已作答」是**回看侧**才有的第三个时刻事实，
      流出侧载荷里不可能有它（基座 7.2 节），硬塞进去会撞上逐字断死字段集合的守卫；
    - 卡片**没有**这样的不对称：回看侧要说的事实与流出侧完全一样（同一张卡、同五个
      字段）。同一个形状在两个时刻是同一个形状，就是同一个线格式 part 类型——
      另立一个只会让前端多一条 `case`（`history.ts` 与 `partAccumulator.ts` 的
      `action_card` 分支必须产出**同一个**视图 part，否则刷新前后同一张卡会变成两种）。

    ⇒ 契约第 7 节的 `action_card` 行是**两个路径共用的**；本包因此只把
    `action_card` 加进 `MessagePart` 联合（水合的取值域），而**不改动**它的字段集合。

    ⚠ 最后一句「逐字同形」是指 **part 的五个字段与线格式逐个对上**，
    **不是**指参数可以原样搬到 part 上：`annotations` 在参数里的形状与线格式不同
    （`{line_ref, source, confidence}` → `{target, kind}`），转换由
    :func:`_card_annotations` 做。sections / states / card_id / title 四项确实同形。
    """

    type: ActionCardType
    card_id: str
    title: str
    sections: list[ActionCardSectionPart]
    states: list[ActionCardStatePart]
    annotations: list[ActionCardAnnotationPart]


class CitationRecordPart(TypedDict):
    """引用载荷（**与事件侧 `CitationEvent.citation` 逐字同形**）。

    六个字段与基座 `agent/context/citations.py` 的 `CitationRecord`、与前端
    `apps/web/src/shared/types/sse.ts` 的 `CitationRecord` 都一致。
    `recorded_at` 是 ISO 8601 字符串（它在会话里就是字符串——
    见 `agent/runtime/session_annotations.py` 的 `citation_annotation`）。

    `summary` 可为 `None`（`TypedDict` 的 `total=True` 只要求键存在，不要求值非空）：
    发凭据时若条目没有标题，摘要就是 `None`，前端按
    `CitationPart.tsx:74` 的 `citation.summary === null ? null : …` 处置。
    """

    citation_id: str
    run_id: str
    source: str
    reference: str
    recorded_at: str
    summary: str | None


class CitationPart(TypedDict):
    """引用 part（契约第 7 节的 `citation` 行 + 通用基座第 4 节）。

    ★ 与**事件侧**的 `CitationEvent.citation` 载荷**逐字同形**——与 `action_card`
    同一种做法（`question`/`question-record` 那一对是相反的例子，理由见
    `ActionCardPart` 的说明）。载荷就是 `CitationRecord` 的六个字段：
    `citation_id` / `run_id` / `source` / `reference` / `recorded_at` / `summary`，
    与前端 `apps/web/src/shared/types/sse.ts` 的 `CitationRecord` 逐字段一致——
    因此刷新前后同一批引用是同一个形状，前端不需要两条分支。

    **真源在哪**（这是本包的核心结论，别按注释猜）：引用载荷由**产出它的那次运行**带进会话
    ——它是助手消息正文分片（`output_text`）自己的 `annotations`（写侧形状归
    `agent/runtime/session_annotations.py`），因此本 part 的**水合真源就是会话条目本身**，
    与设计《咨询对话界面》第 5 节「citation part 与所属消息同生命周期……因为它是消息
    content 的一部分，**不是外部索引**」一致。

    ⚠ **`campfire_citation` 表仍然保留**、仍按《通用基座》第 4 节的不变量写入
    （每条可引用依据都有一行索引记录）。该表与这里的 part **各司其职**：表是
    「回指与审计」的索引，会话条目是「刷新后重建」的真源；两者不是同一份数据的两个副本
    ——表里有 `recorded_at` 与 `source`（审计需要），注解里有重建界面所需的同一批字段。
    **判据是消融**：删掉表里该 run 的行，刷新后 part 必须仍在（那时读的是注解）。

    **为什么载荷不再多带 `item_id` / `library` / `status` 等字段**：前端
    `CitationPart.tsx` 的 `citationDeepLink` 对 `item_id` 做**前向兼容读取**
    （存在才给 deep-link，缺失返回 `null` 且**不猜目标**）。契约 `HTTP与SSE契约.md:204`
    把 citation 的 data 指向《资料与案例检索》第 3 节的八个字段，而实现（含事件侧
    `CitationEvent`）用的是这六个——**这处契约与实现的不一致，本包【未处理】**
    （改事件侧载荷要同时改前端类型与 `CitationPart.tsx`，会扩大范围）。

    ⚠ **如实说明**：上一版这里写着「**已在交付报告登记**」，而那句话是**悬空的**——
    交付报告里并没有这一条（复查者 grep `八个`/`item_id`/`未处理` **全部 0 命中**）。
    本包**没有**把它登记进任何权威清单（`docs/TODO.md` 不在本包的授权改动范围内）。
    ⇒ 因此这里改成**如实的当场陈述**：它是一处**已知未决项**，位置就在本注释；
    谁要处理它，依据是这句话本身，而不是一个指向"某处登记"的悬空指针。
    这里取与事件侧、与前端类型**都一致**的六个字段，好处是刷新前后的载荷同一个形状。
    """

    type: CitationType
    citation: CitationRecordPart


MessagePart = TextPart | ReasoningPart | ToolCallPart | QuestionRecordPart | ActionCardPart | CitationPart
"""水合能重建的 part 类型（**`HydratedMessage.parts` 的取值域**）。

六种 part 各有各的真源，**都能从会话真源重建**（2026-10-06 修正，2026-10-07 随 T36
加入第六种 `citation`，见下）：

- `text` / `reasoning` / `tool_call`：直接来自 SDK 落库的条目（消息 content 与
  reasoning/function_call 条目）；
- `question-record`：来自 `ask_user` 那对条目的**参数与产出**。SDK 会话存储里确实没有
  名为 `question` 的条目，但这不等于「读不出来」——提问的载荷（`items`）逐字保存在
  `function_call.arguments` 里，而「这次提问真的产出了」由 `function_call_output.output`
  的成功回执判定（判据见 :data:`ASK_USER_SUCCESS_OUTPUT`）。两者都在真源里，因此不需要
  第二种真源、也不伪造任何东西。

  `batch_id` 不在会话存储里（它由工具侧生成、不落库），因此水合时由调用标识派生：
  调用标识在同一次会话内唯一且跨刷新稳定，正是「这一组题」的稳定身份（见
  :data:`QUESTION_BATCH_ID_PREFIX`）。

  `answered` 由 :func:`question_answered_verdicts` 从**位置窗口 × 表头**判定
  （判据见该函数）——它是**服务端**的判定，前端只读（硬边界：不许让前端猜）。
- `action_card`：来自 `emit_emergency_action_card` 那对条目（2026-10-06 随 T32 加入，
  与 `question-record` 同源）。**三处与提问不同**，各自都是实测读数，详见本节上方
  「应急行动卡的重建」注释块与 :func:`action_card_part`：

  1. **`card_id` 取回真值、不派生**——成功回执本身是
     `{"card_id": "<uuid4().hex>", "state": "emitted"}`（原件写的「需要与 batch_id
     同样的派生处理」是错的）；派生会让同一张卡在两个时刻拿到两个 id；
  2. **`title` 不在参数里**，由工具侧常量给（:data:`ACTION_CARD_TITLE`，字面量 + 用例绑定）；
  3. **`annotations` 的形状在两侧不同**（参数 `{line_ref, source, confidence}` →
     线格式 `{target, kind}`），水合要做与工具侧 `_encode_annotation_kind` 同一个转换
     —— 只需分隔约定，**不需要**产品侧词表。
- `citation`：来自**助手消息正文分片自己的 `annotations`**（2026-10-07 随 T36 加入，
  同日随 T38 改为 ⑤a 载体）。载荷由写侧在 `add_items` **落库之前**挂上
  （`agent/runtime/session_annotations.py`），因此与其它 part 一样**能从会话真源重建**
  ——它此前登记在 `NOT_REBUILT_PARTS`（「真源是引用索引、不在会话条目里」），
  而那句话在本包实现生产者之后**已不再是事实**（这正是本模块 docstring 反复讲的
  「某能力尚未实现」类断言会过期的那种形状）。

  ★ **为什么换载体**：原先的载体是**工具结果文本**（`function_call_output.output` 里的
  `citations` 键）。它的锚是天然的（那次调用 1:1），但**载荷会进模型输入**——
  而依据区是给使用者看的，不是给模型读的。现在挂在正文分片的 `annotations` 上：
  字面满足第 5 节「是消息 content 的一部分」，且**对模型不可见**
  （本仓用 Chat Completions 模型，其转换器读 content 时只取 `text`）。

## 2026-10-06 订正（原文的理由已过期，这是本缺陷的成因）

本节此前写「`question` / `action_card` 的产出工具尚未实现」——**它不是事实**：
`agent/runtime/ask_user_tool.py` 与 `tools/emergency_card.py` 都已存在、都已装配
（`surfaces/consult/registry.py` 的 `register_base_tools` / `build_product_tools`），
事件也在发（`agent/runtime/assembly.py` 的 `ToolBridge._invoke`）。结论「不产出、
也不伪造」因此把一个**已实现**的能力说成了不可达，前端 `history.ts` 的
`case 'question'` 与 `parts.tsx` 的 `QuestionRecordPart` 就此等一个永不出现的数据。

**这类「某能力尚未实现」的断言必须有失效检查**——它写下的那一刻是真的，之后没人
会回来改它。

### 守法：一份能力台账 + 与事实的机械比对（而不是禁用某些字样）

守法**不是**「扫描本文件里有没有某个词」。判「某个能力存在吗」时要区分**载体**与
**使它成立的东西**：字面出现 ≠ 断言存在。一句解释「为什么旧注释是错的」的说明，
与那句旧注释本身用的是同一批字，按字面扫会把说明一并判红——那是自指误伤，而且
它会逼着后来人**把说明删掉**（把守卫绕过去的最省事办法），恰好毁掉它的目的。

因此改为**语义一致性检查**（判据在 `tests/test_accounts_session_items.py`）：
本模块声明 :data:`PART_PROVENANCE` 与 :data:`NOT_REBUILT_PARTS` 两份台账，
用例断言台账与**代码事实**一致——

1. 台账里声明「可重建」的 part 类型，必须**真的**在 `MessagePart` 联合里；
2. 台账里声明「不重建」的 part 类型，必须**不在**联合里，且必须写明理由；
3. 台账里说「由某个工具产出」的，那个工具必须**真的**在工具注册表里
   （`ask_user` 在 `RESERVED_TOOL_NAMES`、`emit_emergency_action_card` 在
   `build_product_tools()`）。

⇒ 于是「注释说 X 不存在」与「X 已装配」不可能同时为真，**无论那句话怎么措辞**。
反过来，解释性文字可以自由书写、自由引用旧句子——这正是本节能把它写出来的原因。

## 仍未重建的一种：事件侧的 `question`

**如实写明**（不是「尚未实现」，而是「结构上不在水合路径」）：

- `question`（事件侧形状）**不在水合路径上**：水合一律产出 `question-record`。
  这不是「没做」，而是 T31 的裁决——「已作答」只对回看有意义，故水合的 part 类型
  必须与事件的分开。它保留为 :class:`QuestionPart` 并由用例逐字断死。
- ~~`emit_emergency_action_card` 的载荷同样保存在 `function_call.arguments` 里，
  因此与 `question-record` 一样**可以**重建；本包只修了已被旅程实测到的提问一条路径，
  `action_card` 的 `card_id` 需要与 `batch_id` 同样的派生处理，且 `annotations`
  需要一个「来源:置信」的解码（逻辑在产品侧 `tools/emergency_card.py`，而
  `modules/*` 不得 import `tools/*`，判据见项目结构设计第 7 节）。
  登记为残余，不在本包伪造一个半截实现。~~

  **⇒ 已随 T32 关闭（2026-10-06）**，而上面这段登记里**有一句前提是错的**，
  如实订正而不是静默删掉：`card_id` **不需要**任何派生——它就在成功回执里
  （`{"card_id": …, "state": "emitted"}`，逐字落库）。`annotations` 的 `kind`
  **也不是**「解码逻辑归产品侧」那件事：真正需要搬的是**编码**，而它只是
  `f"{source}:{confidence}"` 这一处**语法拼接**（:func:`_card_annotations`），
  合法取值域由消费侧可见地处置，**产品侧词表不需要下沉**。
  **⇒ 当年「要么在装配处注入解码器，要么把编码规则下沉」这个二选一是个假两难：
  水合既不需要解码器、也不需要词表，它只需要分隔符。** 详细理由见本节上方
  「应急行动卡的重建」与 :func:`_card_annotations`。

~~`citation` 仍不在本模块：它的真源是引用索引（一个按 `run_id` 组织的端口），
不在会话条目里——这是结构事实，不是能力缺失。~~

**⇒ 已随 T36/T38 关闭（2026-10-07）**：上面这段登记里**有一句前提是错的**——
「真源是引用索引、不在会话条目里」不是结构事实，而是**当时没有生产者**的后果。
`citation` 的载荷现在就住在会话条目里（助手正文分片自己的 `annotations`），
水合从那里重建；引用索引表仍按第 4 节的不变量写入，但它是**回指与审计**的索引，
不是本 part 的重建来源。**⇒ 判据是消融**：删掉表里该 run 的行，刷新后 part 必须仍在。
"""

#: 能力台账：part 类型 → 重建它的真源与产出工具。
#:
#: **为什么需要这份台账**（而不是靠注释）：本模块曾因一句「产出工具尚未实现」的注释
#: 让 `question` 在历史水合里消失（前端等一个永不出现的数据）。那句注释写下时是真的，
#: 工具装配好之后没人回来撤销它。台账把它变成**可机械核对的事实**：
#: `tests/test_accounts_session_items.py` 断言这里的每一条与代码事实一致——
#: 声明可重建的必须在 `MessagePart` 联合里、声明由某工具产出的那个工具必须真的已注册。
#: 于是台账与事实不可能同时成立而互相矛盾，**与注释怎么写无关**。
#:
#: 加一个 part 时：先把它加进 `MessagePart`，再在这里登记一行；漏登记会有用例红。
PART_PROVENANCE: dict[str, str] = {
    "text": "SDK 助手消息的 content 分片",
    "reasoning": "SDK reasoning 条目的 summary",
    "tool_call": "SDK function_call/function_call_output 条目对",
    PART_TYPE_QUESTION_RECORD: f"{ASK_USER_TOOL_NAME} 调用的参数与成功回执（`answered` 由位置窗口×表头判定）",
    PART_TYPE_ACTION_CARD: (
        f"{EMERGENCY_ACTION_CARD_TOOL_NAME} 调用的参数与成功回执"
        "（`card_id` 取自回执、`title` 取工具侧常量、`kind` 原样搬运）"
    ),
    PART_TYPE_CITATION: (
        "助手消息正文分片（`output_text`）的 `annotations` 数组里的引用注解"
        "（写侧：`agent/runtime/session_annotations.py` 在 `add_items` 落库之前挂上）"
        "——2026-10-07 T38 落定载体：载荷是**消息 content 的一部分**（设计《咨询对话界面》"
        "第 5 节），且**对模型不可见**（Chat Completions 转换器读 content 时只取 `text`）"
    ),
}

#: 未重建的 part 类型 → 理由。**必须写明理由**，否则「不重建」与「忘了做」无法区分
#: （用例会断言每一项都有非空理由）。
#:
#: 与 `PART_PROVENANCE` 合起来构成一份完整清单：契约第 7 节的七种 part 一个不漏地
#: 出现在两张表之一。
NOT_REBUILT_PARTS: dict[str, str] = {
    "question": (
        "它是**流出侧**（事件）的 part 类型，不是水合产物：基座 7.2 节的载荷描述"
        "「刚发出、尚未作答」的提问，而水合要回答的是「回看时这组题有没有被作答」"
        "（T31 裁决）。水合一律产出 `question-record`，因此 `question` 结构上不在"
        "`MessagePart`（水合 parts 的取值域）里。它仍由 `QuestionPart` 保留为事件侧形状，"
        "并由 `test_question_event_part_shape_stays_wire_exact` 逐字断死。"
    ),
}


class HydratedMessage(TypedDict):
    """一条水合后的消息。形状归 HTTP 与 SSE 契约第 3.3 节。"""

    id: str
    role: str
    parts: list[MessagePart]


def _is_tool_call_part(part: MessagePart) -> TypeGuard[ToolCallPart]:
    """`part` 是不是工具调用 part。

    判别联合靠 `type` 字段区分，但 `part["type"] == "tool_call"` 这个写法在静态上
    并不能收窄——字典下标取出来仍是整个 `MessagePart` 联合。回填 `ok`/`summary` 时
    就会被判成「联合里另外两个成员没有这两个键」。

    写成 `TypeGuard` 而不是在调用点加断言：收窄规则只此一份，且它同时是可执行判据
    （真跑时也据此分流），不是只给检查器看的谎话。
    """
    return part["type"] == "tool_call"


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


def citation_parts(item: Mapping[str, object]) -> list[CitationRecordPart]:
    """从**助手消息条目**的正文分片注解里取回引用载荷；没有载荷时返回空列表。

    **真源就是消息 content 本身**（设计《咨询对话界面》第 5 节：「citation 是消息
    content 的一部分，不是外部索引」）：载荷住在写着正文的那个 `output_text`
    分片的 `annotations` 数组里，因此读回时把**同一个分片**的两个字段放在一起看
    （正文与依据同源同条，不会出现「有正文没依据」的错配）。

    **判据是判别键而不是整个数组**：`annotations` 是共用字段，真实的辅助注解
    （例如 `url_citation`）也住在里面。只认 `type == "citation"` 的那些；
    把它们整体当引用会让一条正文凭空多出来源不明的「依据」——比少一条严重。

    **同时要求该分片是正文分片**（`type` 在 `_TEXT_PART_TYPES` 里）：`annotations`
    属于带文本的分片，别的分片即使恰好有同名字段也不是引用载荷的落点。

    **容错方向是「少一条」而不是「抛异常」**：条目不是消息、`content` 不是数组、
    注解数组里某条不是对象或缺必填键时，都只丢弃对应部分并让历史照常呈现。
    读路径上「缺一段」比「整个历史加载失败」更接近事实，但必须留下可查的痕迹（warning）。

    ★ **按 `citation_id` 去重**（跨分片，保留首次出现）：写侧用增量式记账保证
    「每条引用恰好挂一次」，但那只覆盖**本包写出来的**条目；被伪造或迁移来的条目
    可能把同一个标识放两遍，重复项在界面上就是「依据 N 条」里两张一样的卡。
    （⚠ 这份去重是**现在实有这个行为**；上一版这里写到过「读侧就地跳过重复」，
    而当时代码里**并没有**——那是文档与实现不符，已一并修正。）

    ★ **有上界，且裁到时留日志**：`_CITATION_ANNOTATION_MAX` 与写侧同值，
    正常路径上写侧已按同一个界裁过 ⇒ 这里**不该**裁到东西；
    真裁到只有两种成因（外部伪造的超长载荷、或写侧上界失效），两者都记 warning。
    静默截断正是本模块上一版的缺陷形态（实测：写 45 → 读 20，丢 25 条、零日志）。

    **为什么在 `modules/*` 里也实现一份解析**（而不是 import
    `agent/runtime/session_annotations.py`）：本模块承载「SDK 的持久化格式」这一外部契约的
    **唯一解析点**（见模块 docstring），而它对 SDK 条目的其它解析（`message_text`、
    `reasoning_text`、`tool_failure_message`）**都不 import 基座的实现**，
    只依赖已读出的条目形状。两处的键名常量相等由用例直接比对常量守住
    （`test_citation_annotation_constants_agree_across_the_two_parsers`）。

    Args:
        item: 一条会话条目的原文（解析后的映射）。

    Returns:
        引用载荷列表（每条含六个字段）；无载荷或载荷不合法时为空列表。
    """
    if item.get("role") != _ROLE_ASSISTANT:
        return []
    content = item.get("content")
    if not isinstance(content, list):
        return []

    parts: list[CitationRecordPart] = []
    # ★ 读侧去重（按 `citation_id`，跨分片）：写侧用增量式记账保证「每条引用恰好挂一次」，
    # 但那只覆盖**本包写出来的**条目；一条被伪造/迁移来的条目完全可能把同一个
    # `citation_id` 放两遍。重复项在界面上表现为「依据 N 条」里出现两张一样的卡
    # ⇒ 这里就地跳过（**不是**它此前文档声称、而实现里没有的那份纵深防御）。
    seen: set[str] = set()
    for chunk in content:
        if not isinstance(chunk, Mapping):
            continue
        if chunk.get("type") not in _TEXT_PART_TYPES:
            continue
        raw = chunk.get(_ANNOTATIONS_KEY)
        if not isinstance(raw, list):
            continue
        if len(raw) > _CITATION_ANNOTATION_MAX:
            # ★ **不静默**：正常路径上写侧已按同一个上界裁过，因此这里裁到东西
            # 只有两种成因——外部伪造的超长载荷，或写侧上界失效。两者都该留下痕迹。
            logger.warning(
                "助手正文分片上的注解数（%d）超过读侧上界（%d），超出部分不再读回",
                len(raw),
                _CITATION_ANNOTATION_MAX,
            )
        for entry in raw[:_CITATION_ANNOTATION_MAX]:
            if not isinstance(entry, Mapping):
                logger.warning("引用注解里有不是对象的条目，跳过")
                continue
            if entry.get("type") != _CITATION_ANNOTATION_TYPE:
                # 真实的辅助注解（`url_citation` 等）住在这个数组里，按判别键跳过它们。
                continue
            part = _citation_part(entry)
            if part is None:
                continue
            if part["citation_id"] in seen:
                logger.warning("引用注解里出现重复的 citation_id，跳过后续项：%s", part["citation_id"])
                continue
            seen.add(part["citation_id"])
            parts.append(part)
    return parts


def _citation_part(entry: Mapping[str, object]) -> CitationRecordPart | None:
    """把一条注解转成 part；缺必填键时返回 `None`（丢弃它）。

    必填三项：`citation_id`（回指键）、`source`（说不清出处就不该呈现为依据）、
    `reference`（指向的业务标识）。缺任一项的引用在界面上是一张点不动、
    也说不清从哪来的条目——丢弃它比呈现一个残缺的依据好。

    其余字段缺失时**补成空值而不是丢弃**：`run_id`/`recorded_at` 缺失只影响展示，
    `summary` 缺失本来就是合法的（`None`）。前端类型要求这些键存在
    （`sse.ts` 的 `CitationRecord` 六个字段都非可选），因此补 `""` 而不是省略键——
    省略会让前端拿到 `undefined`，而类型说的是 `string`。
    """
    # 三个必填键逐个取出并收窄：写成 `str(value)` 会把 `None` 变成 `"None"`，
    # 那是一条能显示却指不到东西的依据——比丢弃它更糟。
    required: dict[str, str] = {}
    for name in ("citation_id", "source", CITATION_REFERENCE_KEY):
        value = entry.get(name)
        if not isinstance(value, str) or not value:
            logger.warning("引用载荷里的条目缺少必填键 %s，跳过：%s", name, sorted(entry))
            return None
        required[name] = value

    run_id = entry.get("run_id")
    recorded_at = entry.get("recorded_at")
    summary = entry.get("summary")
    return CitationRecordPart(
        citation_id=required["citation_id"],
        run_id=run_id if isinstance(run_id, str) else "",
        source=required["source"],
        reference=required[CITATION_REFERENCE_KEY],
        recorded_at=recorded_at if isinstance(recorded_at, str) else "",
        summary=summary if isinstance(summary, str) else None,
    )


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
# 提问载荷的解析
# ---------------------------------------------------------------------------


def _question_options(raw: object) -> list[QuestionOptionPart]:
    """解析 `options` 数组：只保留有合法 `label` 的选项。

    没有文案的选项在界面上是一个点不动的空按钮（基座 `QuestionOption.__post_init__`
    的判据），因此这里与事件路径同一条处置：丢掉它，而不是渲染一个空按钮。
    """
    if not isinstance(raw, list):
        return []
    options: list[QuestionOptionPart] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        option: QuestionOptionPart = {"label": truncate(label, QUESTION_OPTION_LABEL_MAX_CHARS)}
        description = entry.get(_QUESTION_OPTION_DESCRIPTION_KEY)
        if isinstance(description, str) and description.strip():
            option["description"] = truncate(description, QUESTION_OPTION_DESCRIPTION_MAX_CHARS)
        options.append(option)
    return options


def question_record_part(
    call_id: str,
    arguments: object,
    output: str,
    *,
    answered: bool | None,
) -> QuestionRecordPart | None:
    """从一次 `ask_user` 调用重建水合侧的提问记录 part；重建不出来时返回 `None`。

    两个判据缺一不可（理由见 :data:`ASK_USER_SUCCESS_OUTPUT`）：

    1. **产出是成功回执**——参数不合法的那次调用没有向使用者呈现过任何东西；
    2. **参数能解析出至少一道有题干的题**——解析不出的载荷只可能是形状漂移。

    两个判据都不满足时**不产出 part，也不伪造一张空卡**：调用方（`build_messages`）
    记警告，读路径上「缺一段」比「给一张假卡」更接近事实。

    Args:
        call_id: 这次调用的标识；用作 `batch_id` 的派生来源（同一次会话内唯一且稳定）。
        arguments: `function_call.arguments` 的原文（JSON 字符串，内含 `items`）。
        output: `function_call_output.output` 的原文。
        answered: 这组题是否已被作答（三态，判据见 :func:`question_answered_verdicts`）。
            **调用方必须显式给出**，没有默认值：默认值会让「忘了判定」与「判定为无法判定」
            在代码里长得一模一样，而这两件事的后果完全不同。

    Returns:
        提问记录 part；判据不成立时 `None`。
    """
    if not call_id or output != ASK_USER_SUCCESS_OUTPUT:
        return None
    if not isinstance(arguments, str):
        return None
    try:
        decoded = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    raw_items = decoded.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return None
    if len(raw_items) > QUESTION_ITEMS_MAX:
        # 整体跳过而不是截断：一张缺题的提问卡会让使用者以为自己漏看了什么。
        logger.warning("水合跳过一组题数超上界的提问：调用=%s 题数=%s", call_id, len(raw_items))
        return None

    items: list[QuestionItemPart] = []
    for entry in raw_items:
        if not isinstance(entry, Mapping):
            continue
        item_id = entry.get(_QUESTION_ITEM_ID_KEY)
        prompt = entry.get(_QUESTION_ITEM_PROMPT_KEY)
        # 题标识为空会让回答无从关联、题干为空会让使用者看到一张没有问题的卡片
        # （基座 `QuestionItem.__post_init__` 的两条判据）。
        if not isinstance(item_id, str) or not item_id.strip():
            continue
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        items.append(
            QuestionItemPart(
                id=item_id,
                prompt=truncate(prompt, QUESTION_TEXT_MAX_CHARS),
                options=_question_options(entry.get(_QUESTION_ITEM_OPTIONS_KEY)),
                # 缺省 `False` 与基座 `QuestionItem.allow_skip` 的默认值一致：模型漏给时
                # 事件路径是「不可跳过」，水合必须给出同一个答案。
                allow_skip=entry.get(_QUESTION_ITEM_ALLOW_SKIP_KEY) is True,
            )
        )
    if not items:
        return None
    return QuestionRecordPart(
        type=PART_TYPE_QUESTION_RECORD,
        batch_id=f"{QUESTION_BATCH_ID_PREFIX}{call_id}",
        items=items,
        answered=answered,
    )


# ---------------------------------------------------------------------------
# 行动卡载荷的解析与重建
# ---------------------------------------------------------------------------


def _card_sections(raw: object) -> list[ActionCardSectionPart] | None:
    """解析 `sections`：七节齐全、各出现一次、每节都有小标题与至少一行。

    任何一条不成立就返回 `None`（**整体拒绝，不截断**）——理由见
    :data:`ACTION_CARD_TEXT_MAX_CHARS`：一张被截断的行动卡会把一条安全动作说反，
    比「历史里没有这张卡」更危险。

    为什么不复用产出侧的参数模型（`EmitEmergencyActionCardArgs`）：`modules/*` 不得
    import `tools/*`（项目结构设计第 7 节）。因此这里按**形状**判，而不是复述词表：
    分节键的合法值域与顺序取 :data:`ACTION_CARD_SECTION_KEYS`，超出七个规范键的**不**
    在此拒绝（那是前端忽略未知 key 的职责，且拒绝会让产出侧将来新增第八节时
    水合静默停止产出卡片）。**七节规范键必须齐全**这一条是强度判断：卡片按七节定义，
    缺节的卡在呈现上是「少了几节」，且缺得静默。
    """
    if not isinstance(raw, list):
        return None

    parsed: dict[str, ActionCardSectionPart] = {}
    total_lines = 0
    for entry in raw:
        if not isinstance(entry, Mapping):
            return None
        key = entry.get("key")
        heading = entry.get("heading")
        lines_raw = entry.get("lines")
        if not isinstance(key, str) or key not in ACTION_CARD_SECTION_KEYS:
            return None
        if not isinstance(heading, str) or not heading.strip():
            return None
        if not isinstance(lines_raw, list) or not lines_raw:
            return None
        lines: list[str] = []
        for line in lines_raw:
            if not isinstance(line, str) or not line.strip():
                return None
            if len(line) > ACTION_CARD_TEXT_MAX_CHARS:
                return None
            lines.append(line)
        total_lines += len(lines)
        if key in parsed:
            # 同一个键两次 ⇒ 「这一节是什么」有两个答案（产出侧对重复键也是拒绝，
            # 参数模型 `_require_all_seven_sections_exactly_once`）。
            return None
        parsed[key] = ActionCardSectionPart(key=key, heading=heading, lines=lines)

    if total_lines > ACTION_CARD_LINES_TOTAL_MAX:
        return None
    if set(parsed) != set(ACTION_CARD_SECTION_KEYS):
        return None
    # ★ 按规范顺序重排：产出侧 handler 在发卡前就这样排过（`sorted(..., key=…)`），
    # 因此事件流的载荷是这个顺序。水合必须给出同一个顺序，否则
    # `annotations[].target`（按七节摊平的 1 起序号）在两个路径上会指向不同的行。
    return [parsed[key] for key in ACTION_CARD_SECTION_KEYS]


def _card_states(raw: object) -> list[ActionCardStatePart] | None:
    """解析 `states`：键值都是非空字符串，条数有界。

    **不复述产品侧词表**（`deviation` 取几值、`medical_risk` 只有三值之类）：
    那是产出侧参数模型的职责（`modules/*` 也不得 import `tools/*`）。这里只判
    「形状像不像一组键值」。未知的键或取值**原样搬运**——前端的处置是
    对未知键忽略、对未知取值丢弃该条并计数（`domain/actionCard.ts` 的
    `rejectReasonForStates` 会因此把整张卡判成 rejected），都可见。
    在这里按词表拒绝会让产出侧将来扩词表时**水合静默停止产出卡片**，
    正是本包要修的那个缺陷换了张脸回来。
    """
    if not isinstance(raw, list) or len(raw) > ACTION_CARD_STATES_MAX:
        return None
    states: list[ActionCardStatePart] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            return None
        key = entry.get("key")
        value = entry.get("value")
        if not isinstance(key, str) or not key.strip():
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        states.append(ActionCardStatePart(key=key, value=value))
    return states


def _card_annotations(raw: object) -> list[ActionCardAnnotationPart] | None:
    """把参数里的标注编成**线格式**的 `{target, kind}`；形状不合法时返回 `None`。

    ⚠ **这里确实是本包唯一一处「编码规则要在 `modules/*` 里再写一份」的地方**，
    如实说明它为什么不能像 `sections` / `states` 那样原样搬运（这是实测纠正的，
    我第一版写成「原样搬运」并因此**产不出任何卡片**——见报告 §4.2）：

    落库的 `function_call.arguments` 是**模型给的输入形状**，而基座 7.3 节的线格式
    是**信封形状**，两者在最关键的一处不对称（`tools/emergency_card.py` 的
    `_Annotation` 说明自己点明了这一点）：

    | 参数（落库） | 线格式（事件与水合 part） |
    |---|---|
    | `{line_ref: int, source: str, confidence: str}` | `{target: str, kind: str}` |

    工具侧 handler 用 `_encode_annotation_kind` 把两个字段编成一个 `kind`
    （`f"{source}:{confidence}"`）、把 `line_ref` 转成 `str`。**⇒ 水合要产出与事件
    同形的 part，就必须做同一个转换**，否则前端 `domain/actionCard.ts` 的
    `annotation.target` / `annotation.kind` 读到的是两个不存在的字段
    —— 那正是「让前端猜」。

    ★ **但它只需要分隔约定，不需要产品侧词表**（这是与原件那个二选一不同的第三条路）：
    编码是**纯粹的语法拼接**；`source` / `confidence` 的合法值域**不在这里复述**。
    越界取值由**消费侧**处置且可见——前端 `decodeAnnotation` 查不到显示名就返回 `null`，
    该条标注被丢弃并计入 `droppedAnnotations`（`AC-07` 的呈现纪律由那一侧承担）。
    在这里复述六类来源与四档置信，会让产出侧将来扩词表时**水合静默停止产出卡片**
    —— 本包要修的那个缺陷换了张脸回来。

    分隔符 `:` 的正确性由用例**跑真实工具**守住：断言真实产出的
    `{"line_ref": n, "source": s, "confidence": c}` 经本函数得到
    `{"target": str(n), "kind": f"{s}:{c}"}`，而那个 `kind` 又能被
    `tools/emergency_card.py` 的 `decode_annotation_kind` 解回 `(s, c)`。
    """
    if not isinstance(raw, list) or len(raw) > ACTION_CARD_ANNOTATIONS_MAX:
        return None
    annotations: list[ActionCardAnnotationPart] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            return None
        line_ref = entry.get("line_ref")
        source = entry.get("source")
        confidence = entry.get("confidence")
        # `line_ref` 是「按七节摊平后的 1 起序号」（产出侧参数模型 `Field(ge=1)`）。
        # `bool` 是 `int` 的子类，显式排除——`True` 会变成 `"True"` 这个非数字 target。
        if not isinstance(line_ref, int) or isinstance(line_ref, bool) or line_ref < 1:
            return None
        if not isinstance(source, str) or not source.strip():
            return None
        if not isinstance(confidence, str) or not confidence.strip():
            return None
        annotations.append(
            ActionCardAnnotationPart(target=str(line_ref), kind=f"{source}{_ANNOTATION_KIND_SEPARATOR}{confidence}")
        )
    return annotations


def action_card_success_card_id(output: str) -> str | None:
    """从 `emit_emergency_action_card` 的回执里取出**真实的** `card_id`；不是成功回执时返回 `None`。

    ★ 这是本包**判据的产出侧一半**（与 :func:`question_record_part` 对
    `ASK_USER_SUCCESS_OUTPUT` 的相等判定同一条纪律）。为什么必须是它：

    参数不合法的调用会得到 `<tool_error code="tool_invalid_arguments">…</tool_error>`
    （`ToolSpec._parse` 在解析期就把它变成失败，`ToolResult` 从不构造，因此事件流里
    **没有**任何卡片）。若只看「参数能不能解析出一张卡」，水合会造出一张**当时从未
    呈现给使用者的卡**——那是伪造。这一条把判据钉在**产出**上，而不是参数形状上。

    回执形状取自 `tools/emergency_card.py:406`：
    `json.dumps({"card_id": card.card_id, "state": "emitted"}, ensure_ascii=False)`。

    **为什么在这里再解析一次 JSON 而不是用工具侧的函数**：`modules/*` 不得 import
    `tools/*`（项目结构设计第 7 节，判据见 `tests/test_layer_boundaries.py`）。
    两处的一致性由用例**跑真实工具**守住——它断言真实回执能被本函数解析出同一个
    `card_id`（文案或形状漂移时立刻有红，而不是让卡片在水合里静默消失）。

    Args:
        output: `function_call_output.output` 的原文。

    Returns:
        回执里的 `card_id`；不是本工具的成功回执（工具错误、格式漂移、`card_id` 缺失
        或为空）时返回 `None`。
    """
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None
    if decoded.get("state") != ACTION_CARD_EMITTED_STATE:
        return None
    card_id = decoded.get("card_id")
    if not isinstance(card_id, str) or not card_id.strip():
        return None
    return card_id


def action_card_part(arguments: object, output: str) -> ActionCardPart | None:
    """从一次 `emit_emergency_action_card` 调用重建 `action_card` part；重建不出来时返回 `None`。

    **两个判据缺一不可**（理由见 :func:`action_card_success_card_id`）：

    1. **产出是成功回执**——回执能解析出 `state == "emitted"` 且带非空 `card_id`；
    2. **参数能解析出合法的卡片**——七节齐全且每节至少一行、状态与标注形状合法。

    任一不成立就**不产出 part、也不伪造一张半截卡**：调用方（`_Hydration`）记警告。
    读路径上「缺一张卡」比「给一张假卡」更接近事实——而一张**残缺**的卡更糟：
    它的「不要做」那一节可能整节消失，或某一行被截断成相反的意思。

    ★ **`card_id` 取自回执、不做任何派生**（这是与提问路径的一处实质差别）：
    回执里的值就是当年发出去的那个 id，逐字落库（同库旁证：`create_support_object`
    等的回执都是逐字 JSON）。**⇒ 稳定性是「取回真值」的结果，而不是「派生规则不撞车」
    的结果**：同一行数据两次水合必然得到同一个 id（输入相同、解析是纯函数），
    且它**与事件流里那个 id 相等**——派生值做不到后一点，而前端的旧卡失效判定正是
    在比 `card_id`（`ChatWorkspace.newestActionCardId` 与 `parts.tsx` 的 `expired`）。
    一张刷新后的卡若换了 id，就会去和最新卡比较 ⇒ 它可能被标成「已过期」，
    或在它才是最新卡时**不**标过期而把真正的旧卡留下的判定整个错位。

    Args:
        arguments: `function_call.arguments` 的原文（JSON 字符串，内含
            `sections` / `states` / `annotations`，形状是**工具的输入形状**）。
        output: `function_call_output.output` 的原文。

    Returns:
        行动卡 part；判据不成立时 `None`。
    """
    card_id = action_card_success_card_id(output)
    if card_id is None:
        return None
    if not isinstance(arguments, str):
        return None
    try:
        decoded = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, Mapping):
        return None

    sections = _card_sections(decoded.get("sections"))
    if sections is None:
        return None
    states = _card_states(decoded.get("states"))
    if states is None:
        return None
    # 缺省空数组（产出侧参数模型的 `default_factory=list`，契约第 2 节「可为空」）。
    annotations = _card_annotations(decoded.get("annotations", []))
    if annotations is None:
        return None

    return ActionCardPart(
        type=PART_TYPE_ACTION_CARD,
        card_id=card_id,
        # `title` 不在参数里、也不在回执里（回执只有 card_id 与 state）：
        # 它由工具侧的常量给，这里只能是字面量 + 用例绑定（同 ASK_USER_SUCCESS_OUTPUT）。
        title=ACTION_CARD_TITLE,
        sections=sections,
        states=states,
        annotations=annotations,
    )


# ---------------------------------------------------------------------------
# 「这一组题被作答了吗」——位置窗口 × 表头的合取判据
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AskUserTurn:
    """一次**真的向使用者发出过**的提问：调用行、它的成功回执行、派生的批次标识。

    只有三样东西都齐的调用才算一次「提问」：
    - 是一次 `ask_user` 的 `function_call`，且 `call_id` 非空；
    - 有同 `call_id` 的 `function_call_output`；
    - 那条产出**逐字等于** `ASK_USER_SUCCESS_OUTPUT`（参数不合法的调用从未呈现给使用者，
      基座 `QuestionGate` 也不为它结束运行——见 :data:`ASK_USER_SUCCESS_OUTPUT`）。

    **为什么按 `call_id` 配对输出，而不是取「调用行的下一行」**（T31 实测到的坑）：
    SDK 会把同一批工具调用**连排**，再连排它们的结果。真实库里 60 次 `ask_user` 有
    **23 次**的下一行不是自己的产出（而是同批其他调用的产出）。取「下一行」会把这 23 组
    的窗口起点算到别人身上——读数上恰好也能给出 31/29（因为那一批的结果紧跟在后面），
    但它是**巧合**，换一个批次形状就会错位。
    """

    call_id: str
    call_index: int
    output_index: int


def _ask_user_turns(items: Sequence[StoredItem]) -> list[AskUserTurn]:
    """按行序取出所有「真的发出过」的 `ask_user` 提问。"""
    output_indices: dict[str, int] = {}
    for index, stored in enumerate(items):
        item = stored.data
        if item_type(item) != ITEM_TYPE_FUNCTION_CALL_OUTPUT:
            continue
        call_id = item.get("call_id")
        # 首次出现优先（同 `call_id` 重复是压缩复述，见 `question_answered_verdicts`）。
        if isinstance(call_id, str) and call_id and call_id not in output_indices:
            output_indices[call_id] = index

    turns: list[AskUserTurn] = []
    for index, stored in enumerate(items):
        item = stored.data
        if item_type(item) != ITEM_TYPE_FUNCTION_CALL:
            continue
        if item.get("name") != ASK_USER_TOOL_NAME:
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        output_index = output_indices.get(call_id)
        if output_index is None:
            continue
        if items[output_index].data.get("output") != ASK_USER_SUCCESS_OUTPUT:
            continue
        turns.append(AskUserTurn(call_id=call_id, call_index=index, output_index=output_index))
    return turns


def _is_compaction_checkpoint(item: Mapping[str, object]) -> bool:
    """这条条目是不是压缩检查点（`<compacted-summary>…</compacted-summary>`）。

    判据取自 `agent/context/window.is_compacted_summary` 的同一条规则（开头标签 ∧ 结尾标签），
    但**不复用它的实现**：`modules/*` 不得 import `agent/*`（项目结构设计第 7 节）。
    两处的标签字面量相等由 `tests/test_accounts_session_items.py` 机械核对。

    为什么判据要求两端标签都在（而不只是开头匹配）：一句使用者写的、以
    `<compacted-summary>` 开头的普通消息不该被当成复述块——那会把一次真实提问判成
    「无法判定」，方向虽然是安全的，但它是一条凭空的误判。
    """
    if item.get("role") != _ROLE_USER:
        return False
    content = item.get("content")
    if not isinstance(content, str):
        return False
    stripped = content.strip()
    if len(stripped) < len(COMPACTED_SUMMARY_TAG) + len(_COMPACTED_SUMMARY_CLOSE_TAG):
        return False
    return stripped.startswith(COMPACTED_SUMMARY_TAG) and stripped.endswith(_COMPACTED_SUMMARY_CLOSE_TAG)


def _is_answers_message(item: Mapping[str, object]) -> bool:
    """这条条目是不是一条「对提问的作答」消息（正文以表头开头、非注入、非复述）。

    与 :func:`_window_verdict` 的判据同源，但**不复用它的窗口切片**：本函数要问的是
    「这条作答在整段历史里离哪一次提问最近」。读不出文本 / 是检查点 / 是注入的条目
    一律返回 `False`——它们不是「看上去像作答」的消息（前两者的不可判定由窗口判据负责，
    不在这里重复记一次）。
    """
    if item.get("role") != _ROLE_USER:
        return False
    if _is_compaction_checkpoint(item) or is_injected_message(item):
        return False
    text = message_text(item)
    if text is None:
        return False
    return text.lstrip().startswith(ANSWERS_HEADER)


def _nearest_turn_position(turns: Sequence[AskUserTurn], index: int) -> int | None:
    """这条条目之前**最近的**那次提问的下标；前面没有提问时返回 `None`。

    「最近」取调用行与配对输出行里更靠后的那个：一次提问占两行，作答只可能在它的
    调用行（甚至回执行）之后到达。前面没有提问 ⇒ `None`（那条作答不属于任何一组，
    因此不对任何组构成「可能是迟到的」）。
    """
    best_position: int | None = None
    best_index = -1
    for position, turn in enumerate(turns):
        for candidate in (turn.call_index, turn.output_index):
            if candidate < index and candidate > best_index:
                best_index = candidate
                best_position = position
    return best_position


def _window_verdict(window: Sequence[StoredItem]) -> bool | None:
    """在读作「某次提问之后、下一次提问之前」的窗口上判定这组题是否已被作答。

    判据（T31 裁决的合取，逐字）：**窗口里存在一条正文以 :data:`ANSWERS_HEADER` 开头的、
    既非注入也非复述的使用者消息** ⇒ `True`；窗口里根本没有这样的消息 ⇒ `False`。

    为什么是「存在」而不是「第一条」（2026-10-06，本包的一处独立判断）：
    窗口里可能先出现一条新话题、之后才出现作答（使用者先说了别的，再回头把那组题答了）。
    按「第一条」判会给出 `False` ⇒ 卡片重新变成可作答 ⇒ **使用者对同一组题作答两次**
    （§三 点名的方向）。按「存在」判给出 `True` ⇒ 只读。**失败方向选安全的那边。**
    两种读法在真实库的 60 组上给出**完全相同**的 31/29/0（本包实测）。

    两半都承重，且都只能靠构造用例证明（真实库上三个判据给出完全相同的 31/29/0）：

    - **表头**那一半排除「使用者忽略提问、直接发新话题」——那种组是未作答的，
      只按「窗口里有没有使用者消息」判会把它误判成已作答（**使用者永久失去补答能力**）；
    - **位置**那一半排除「题标识相同的另一组」/「更早某组的作答」——不取窗口、改扫整段
      历史时，A 组的作答会被算到 B 组头上（**同样是永久失去补答能力**）。

    Returns:
        `True` / `False` / `None`。`None` = **无法判定** ⇒ 前端按只读呈现（fail-closed）。
        返回 `None` 的三种情形都是「判据看不到事实」，而不是「事实是未作答」：

        1. 窗口里出现**压缩检查点**——`compaction.appended_items` 会追加
           「检查点 + 尾部原文」，被保留的尾部在历史里因此存在**两份**
           （`compaction.py:468` 自己写明这个代价）。复述块里的旧作答消息与
           「本组的作答」在形状上无法区分 ⇒ 不能选任何一边；
        2. 窗口里同一段使用者正文出现**两次**——同上的第二种表现（复述块的边界
           恰好落在窗口内部时，检查点可能不在窗口里）；
        3. 窗口里有一条使用者消息**读不出文本**——判据看不到内容，就没有依据。
    """
    bodies: list[str] = []
    for stored in window:
        item = stored.data
        if item.get("role") != _ROLE_USER:
            continue
        # ★ 检查点判在「注入」之前：`<compacted-summary>` 同时登记在
        # `INJECTED_MESSAGE_PREFIXES` 里（它确实是注入），因此先判注入的话它会
        # 被静默跳过，而复述块的存在正是本判据必须看见的东西。
        if _is_compaction_checkpoint(item):
            return None
        if is_injected_message(item):
            continue
        text = message_text(item)
        if text is None:
            return None
        bodies.append(text)

    if len(bodies) != len(set(bodies)):
        # 同一段正文两份 ⇒ 窗口跨过了一个复述块 ⇒ 复述与本组的作答不可区分。
        return None
    if not bodies:
        return False
    return any(body.lstrip().startswith(ANSWERS_HEADER) for body in bodies)


def question_answered_verdicts(items: Sequence[StoredItem]) -> dict[str, bool | None]:
    """逐次提问判定「这组题被作答了吗」，按 `call_id` 给出三态结论。

    窗口定义：**某次提问的成功回执之后、下一次「真的发出过」的提问的调用行之前**。

    两个边界取法都要说清为什么：

    - **起点取「配对输出的下一行」而不是「调用行的下一行」**：见 :class:`AskUserTurn`
      （真实库里 23/60 的下一行不是自己的产出）；
    - **终点取「下一次真的发出过的提问」而不是「下一次 `ask_user` 调用」**：参数不合法的
      调用从未向使用者呈现过任何东西（它产不出 part）。若把它算作窗口终点，一次
      「先失败一次、再成功一次」的会话会把上一组的窗口切碎——上一组的真实作答就落到了
      窗口之外 ⇒ 判成未作答 ⇒ **使用者重复作答**（`§三` 明令要防的方向）。

    **同一次调用出现两次 ⇒ `None`**：压缩复述会让一个 `ask_user` 调用对在历史里出现两份。
    此时「哪一份的窗口才是本组的窗口」没有答案，两侧一起 fail-closed（只读）——
    **猜成可作答会让使用者重复作答，猜成只读最多少修一点。**

    **跨窗口的迟到作答 ⇒ 本组不得判 `False`（判 `None`）**（2026-10-06 r3 窄修）：
    使用者可能在**下一次提问之后**才回头作答上一组（实测构造：
    `call(A) → out(A) → 「换个话题」 → call(B) → out(B) → 作答`）。那条作答落在 B 的
    窗口里，A 的窗口里什么都没有 ⇒ 只按窗口判会给 `A=False` ⇒ A 的卡片重新变成可作答
    ⇒ **使用者对 A 重复作答**。而服务端**无法区分**那条作答是「A 的迟到作答」还是
    「B 的正常作答」（作答消息里只有题标识、没有 `batch_id`），因此 A 侧的正确结论是
    **无法判定** ⇒ `None`（只读）。

    判据：若某条以 :data:`ANSWERS_HEADER` 开头的使用者消息的**最近一次提问不是本组**
    （用它前面最近的调用行/配对输出行定位），则本组判 `None`。方向是**严格收窄**：
    它只把 `False` 降级成 `None`（消除重复作答），不把任何 `True` 改成别的值，
    因此不会制造新的「永久失去补答」。

    ⚠ 残余（本包**不修**，如实登记）：上例中 B 仍判 `True`，而真相是 B 未被作答
    ⇒ B 永久失去补答。这一半**不可判定**：同一条作答消息既可能是 A 的迟到作答、也可能
    是 B 的正常作答；根因是作答消息里只有题标识、没有 `batch_id`
    （`surfaces/consult/answers.py` 的渲染只写题标识），两组题标识相同时内容层面也不可区分。
    真正的修法是让作答携带 `batch_id`（改契约），超出本包范围。

    Args:
        items: 该会话的全部条目（正序）。**必须全量**：窗口要看到注入行、其他工具结果
            与检查点，只给 `ask_user` 相关的行会漏掉判据要看的东西。

    Returns:
        `call_id` → `True` / `False` / `None`。缺键等价于 `None`（调用方据此 fail-closed）。
    """
    turns = _ask_user_turns(items)
    occurrences: dict[str, int] = {}
    for turn in turns:
        occurrences[turn.call_id] = occurrences.get(turn.call_id, 0) + 1

    # 跨窗口的迟到作答：对每条「像作答」的消息，它最近的那次提问是它的**假定**主人；
    # 那次提问**之前**的每一次提问都可能才是它真正的对象（迟到作答）⇒ 那些组不得判 False。
    # 只登记「更早」的组（`range(nearest)`）：一次提问不可能被一条**早于它**的消息作答，
    # 把更晚的组也算进来会凭空制造 `None`，而 `None` 同样是永久失去补答。
    # 一次遍历算好，避免在每组上重扫整段历史（提问数 × 条目数是二次的）。
    late_answer_suspects: set[int] = set()
    for index, stored in enumerate(items):
        if not _is_answers_message(stored.data):
            continue
        nearest = _nearest_turn_position(turns, index)
        if nearest is not None:
            late_answer_suspects.update(range(nearest))

    verdicts: dict[str, bool | None] = {}
    for position, turn in enumerate(turns):
        if occurrences[turn.call_id] > 1:
            # 同一次提问在历史里出现两份（压缩复述）⇒ 无法判定。
            verdicts[turn.call_id] = None
            continue
        start = turn.output_index + 1
        end = turns[position + 1].call_index if position + 1 < len(turns) else len(items)
        if end < start:
            # 边界倒挂（下一次提问的调用行落在本次回执之前）：窗口没有定义 ⇒ 无依据。
            verdicts[turn.call_id] = None
            continue
        verdict = _window_verdict(items[start:end])
        if verdict is False and position in late_answer_suspects:
            # 有一条更晚的作答消息，而它离某次更晚的提问更近 ⇒ 它完全可能就是本组的
            # 迟到作答 ⇒ 服务端不得断言「本组未被作答」（fail-closed ⇒ 只读）。
            verdict = None
        verdicts[turn.call_id] = verdict
    return verdicts


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

    def __init__(self, answered: Mapping[str, bool | None] | None = None) -> None:
        """起一个空的水合过程。

        Args:
            answered: `call_id` → 这组题是否已被作答（三态）。由 :func:`build_messages`
                在扫描**之前**一次算好（判据要看整段历史，不能边扫边判）。
                缺键按 `None` 处置（fail-closed）——「没算到」与「无法判定」都只读。
        """
        self.messages: list[HydratedMessage] = []
        self._parts: list[MessagePart] = []
        self._first_row_id: int | None = None
        #: 尚未配到结果的工具调用：call_id → parts 下标。工具结果总在调用之后到达，
        #: 因此 part 先占位、拿到结果再回填。
        self._pending_calls: dict[str, int] = {}
        #: 尚未配到结果的工具调用的**参数原文**：call_id → `arguments`。
        #: 提问的重建需要它（`question_record_part` 读 `items`，而参数只落在**调用**条目里），
        #: 而 parts 里只留了名字与摘要——没有这张表就得从 `ToolCallPart` 反查，那是
        #: 把它当成了参数的第二个存放处。
        self._pending_arguments: dict[str, object] = {}
        self._answered: Mapping[str, bool | None] = answered if answered is not None else {}

    def _forget_call(self, stored: StoredItem) -> None:
        """把一个读不出产出的结果条目对应的待配状态清掉（不留悬挂登记）。"""
        call_id = stored.data.get("call_id")
        if isinstance(call_id, str):
            self._pending_calls.pop(call_id, None)
            self._pending_arguments.pop(call_id, None)

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
            if _is_tool_call_part(part):
                part["ok"] = False
                part["summary"] = INTERRUPTED_TOOL_SUMMARY
        if self._parts and self._first_row_id is not None:
            self.messages.append({"id": str(self._first_row_id), "role": _ROLE_ASSISTANT, "parts": self._parts})
        self._parts = []
        self._first_row_id = None
        self._pending_calls = {}
        self._pending_arguments = {}

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
        """收一条助手文本消息（content 是分片数组，可能只有一个部件）。

        ★ **引用 part 在这里产出**（2026-10-07 T38）：载荷挂在正文分片自己的
        `annotations` 上（见 `citation_parts`），因此它的重建点就是**读这条正文的那一处**
        ——正文与依据同源同条，不会出现错配。顺序是先正文、后依据：界面读法是
        「说了什么 → 依据是什么」，且前端 `history.ts` 本就把依据聚合成消息尾的一块。
        """
        texts = _content_parts(stored.data)
        citations = citation_parts(stored.data)
        if not texts and not citations:
            return
        self._start_assistant(stored.row_id)
        self._parts.extend(TextPart(type="text", text=text) for text in texts)
        self._parts.extend(CitationPart(type=PART_TYPE_CITATION, citation=citation) for citation in citations)

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
        self._pending_arguments[call_id] = item.get("arguments")
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
        """用工具结果回填对应的调用 part（`ok` 与 `summary`）。

        ★ 两个成功产出在这里**额外**各产出一个 part（`ask_user` → `question-record`，
        2026-10-06 T27；`emit_emergency_action_card` → `action_card`，2026-10-06 T32）。

        为什么落在这一支而不是新增一个条目类型：SDK 会话存储里没有「提问」「卡片」
        这几种条目——它们的真源就是这对 `function_call` / `function_call_output`。
        把它挂在这里，「一次调用」只有一处重建点，且它与那次工具调用天然同属一条助手消息。

        ⚠ **引用（`citation`）不在这里**（2026-10-07 T38 起）：它的载荷挂在**助手正文
        分片的 `annotations`** 上（设计《咨询对话界面》第 5 节：citation 是消息 content
        的一部分），因此重建点在 `add_assistant_text`。这里不再从工具结果文本里读载荷——
        那条路会让载荷落进**模型读得到**的输入，而本载体的收益正是「载荷对模型不可见」。

        顺序：先回填 `tool_call`、再追加重建出的 part。事件流里两者是反的
        （`ToolBridge._invoke` 先 sink `QuestionEvent`/`ActionCardEvent` 再 sink
        `ToolCallFinishedEvent`），这里刻意相反——水合出来的工具行是一句
        「向你提问 · 已结束」/「生成行动卡 · 已完成」的记录，让卡片排在它之后更接近
        「记录 → 结果」的读法。该差别不影响任何签名要求：两侧唯一的硬要求是
        「part 存在且载荷同形」（前端 `parts.tsx` 按 `data.by_name` 注册，与顺序无关）。
        """
        item = stored.data
        output = item.get("output")
        if not isinstance(output, str):
            self._forget_call(stored)
            logger.warning("水合跳过一条读不出产出的工具结果：行=%s", stored.row_id)
            return
        call_id = item.get("call_id")
        index = self._pending_calls.pop(call_id, None) if isinstance(call_id, str) else None
        arguments = self._pending_arguments.pop(call_id, None) if isinstance(call_id, str) else None
        if index is None:
            # 没有对应调用的结果：SDK 存储里不应出现（结果由调用派生）。
            logger.warning("水合跳过一条找不到对应调用的工具结果：行=%s", stored.row_id)
            return
        part = self._parts[index]
        if not _is_tool_call_part(part):
            return
        failure = tool_failure_message(output)
        part["ok"] = failure is None
        # 工具行摘要照旧取**原文**（含信封）：`TOOL_SUMMARY_MAX_CHARS` 是 200，而信封
        # 附在文本末尾，因此正常长度下它落不进摘要窗口。这里刻意不先切信封——切错了
        # 会让工具输出凭空少一截，而摘要是给人看的那一行，宁可多带几个字符。
        part["summary"] = (output if failure is None else failure)[:TOOL_SUMMARY_MAX_CHARS]

        if not part["ok"]:
            return

        if part["tool_name"] == ASK_USER_TOOL_NAME:
            # 参数在**调用**条目里，不在结果条目里，因此回填时要靠 add_tool_call 留下的原文
            # （`_pending_arguments`）——从 parts 下标反查会把参数再拼一遍，多一份要维护的形状。
            normalized_call_id = call_id if isinstance(call_id, str) else ""
            question = question_record_part(
                normalized_call_id,
                arguments,
                output,
                # 缺键按 None（fail-closed）：判据没算到这一组时不得猜成「可作答」。
                answered=self._answered.get(normalized_call_id),
            )
            if question is None:
                logger.warning("水合跳过一条重建不出的提问：调用=%s 行=%s", call_id, stored.row_id)
                return
            self._parts.append(question)
            return

        if part["tool_name"] == EMERGENCY_ACTION_CARD_TOOL_NAME:
            card = action_card_part(arguments, output)
            if card is None:
                logger.warning("水合跳过一条重建不出的行动卡：调用=%s 行=%s", call_id, stored.row_id)
                return
            self._parts.append(card)


def build_messages(items: Sequence[StoredItem]) -> list[HydratedMessage]:
    """把会话真源的条目序列翻成契约第 3.3 节的消息序列。

    分组规则（一次运行的产出合成一条助手消息）：助手侧的条目——思考、工具调用与
    结果、助手文本——属于同一条助手消息的 `parts`，直到下一条使用者消息出现
    才收束。依据是第 7 节把七种 part 都定义为「消息 content 的序列化，与流式事件
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

    ★ **`answered` 在扫描之前一次算好**（2026-10-06，T31）：判据要看「某次提问之后、
    下一次提问之前」的窗口，窗口横跨多条条目，因此不能边扫边判（一次单向扫描在读到
    提问的那一刻还不知道后面有没有作答）。这里先调 :func:`question_answered_verdicts`
    拿到整段历史的结论，再交给水合过程按 `call_id` 取用。

    Args:
        items: 按时间正序排列的条目（排序由 `session_repository` 负责）。

    Returns:
        水合后的消息列表，顺序即真源顺序。
    """
    answered = question_answered_verdicts(items)
    hydration = _Hydration(answered)
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
    # 提问重建
    "ASK_USER_SUCCESS_OUTPUT",
    "ASK_USER_TOOL_NAME",
    "ANSWERS_HEADER",
    "COMPACTED_SUMMARY_TAG",
    "EMERGENCY_ACTION_CARD_TOOL_NAME",
    "NOT_REBUILT_PARTS",
    "PART_PROVENANCE",
    "PART_TYPE_QUESTION_RECORD",
    "QUESTION_BATCH_ID_PREFIX",
    "QUESTION_ITEMS_MAX",
    "QUESTION_OPTION_DESCRIPTION_MAX_CHARS",
    "QUESTION_OPTION_LABEL_MAX_CHARS",
    "QUESTION_TEXT_MAX_CHARS",
    "AskUserTurn",
    # 行动卡重建
    "ACTION_CARD_ANNOTATIONS_MAX",
    "ACTION_CARD_EMITTED_STATE",
    "ACTION_CARD_LINES_TOTAL_MAX",
    "ACTION_CARD_SECTION_KEYS",
    "ACTION_CARD_STATES_MAX",
    "ACTION_CARD_TEXT_MAX_CHARS",
    "ACTION_CARD_TITLE",
    "PART_TYPE_ACTION_CARD",
    "ActionCardType",
    # 引用重建
    "CITATION_REFERENCE_KEY",
    "PART_TYPE_CITATION",
    "CitationType",
    "citation_parts",
    # 注入信封
    "INJECTED_MESSAGE_PREFIXES",
    # part 形状
    "MessagePart",
    "ActionCardAnnotationPart",
    "ActionCardPart",
    "ActionCardSectionPart",
    "ActionCardStatePart",
    "CitationPart",
    "CitationRecordPart",
    "QuestionItemPart",
    "QuestionOptionPart",
    "QuestionPart",
    "QuestionRecordPart",
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
    "action_card_part",
    "action_card_success_card_id",
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
    "question_answered_verdicts",
    "question_record_part",
    "reasoning_text",
    "tool_failure_message",
    "truncate",
]
