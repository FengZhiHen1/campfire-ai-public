"""发消息请求的形状与「一组提问的回答」的渲染。

职责：校验两种请求形态（普通消息 / 一组回答），并把一组回答渲染成一条使用者消息。
边界：不管运行、不管幂等、不管落库（那些归 `runbus` 与 `routes`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 4.1、7 节；编排器 T07 裁决 4、11。

渲染格式的两条约束（契约 4.1）：

跳过必须是服务端可判定的事实。契约明文要求「跳过必须是服务端可判定的事实，
不能靠前端措辞或模型推断」——应急场景的「跳过即未排除」由此成立。因此渲染出的
每一行都有一个固定的机器可判形式，且判定函数（:func:`skipped_answer_ids`）
与渲染函数（:func:`render_answers`）在同一个模块里，改一处忘另一处会立刻被
本模块的用例抓到。

整组一次提交。一次请求里的回答是提交单位（契约 4.1：一组的回答一次发完，
不接受逐题分次提交），因此校验的粒度是整组：任一项不合法则整组 422，
不做「部分收下」。

为什么渲染进正文，而不是作为消息元数据：编排器裁决 4 给的两案要求先探测
SDK 的能力。实测（本包证据）：使用者消息由基座写入，形状固定为
`{"role": "user", "content": <str>}`（`agent/runtime/runner.py` 里
`new_items.append({"role": "user", "content": request.user_input})`），而
`RunRequest.user_input` 的类型是 `str | None`、`RunRequest` 没有任何承载
消息级元数据的字段；面层也无法自行写 SDK 会话（T07 约束：面层不得直接访问
数据库表）。因此选了裁决 4 的第二案：渲染进正文的固定格式，并让「跳过」可判定。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

#: 一条使用者消息的正文长度上界（CORE-11：进入系统的文本必须有显式上界）。
#:
#: 取 8000：远大于一次粘贴的咨询描述，又不会让一次运行的首条消息把上下文预算
#: 一口吃掉。超界是 422（载荷不合法），不是截断——截断会让使用者以为自己说的话
#: 已经被完整读到了。
MAX_CONTENT_CHARS = 8000

#: 一组回答的题数上界（同上）。提问工具侧的题组本身就是小规模（一次性可提出的
#: 题数受工具参数模型约束），这里兜的是伪造载荷。
MAX_ANSWERS = 32

#: 幂等键的长度上界。前端生成的标识，只用来做键，不需要长。
MAX_CLIENT_MESSAGE_ID_CHARS = 128

#: 技能名的长度上界（与 skill 注册表的名字规模相称）。
MAX_SKILL_NAME_CHARS = 128

#: 渲染出的回答消息的固定表头（编排器裁决 4）。
ANSWERS_HEADER = "以下是对提问的作答"

#: 跳过的固定标记（编排器裁决 4）。写成常量而不是内联字面量：它是判定依据，
#: 出现两处字面量时其中一处改名会让跳过静默变成一句自由文本。
SKIPPED_MARK = "（跳过）"

#: 题标识与作答之间的分隔符（全角冒号，与中文正文一致）。
ANSWER_SEPARATOR = "："

#: 渲染出的作答正文里「本组批次标识」那一行的开头（2026-10-06 随 C-2 加入）。
#:
#: 为什么声明要落进正文（而不只是请求载荷里）：归属判定发生在**回看侧**（水合时判
#: 「这组题被作答了吗」），而回看侧唯一的真源是会话存储里的条目。声明若只停留在载荷里，
#: 刷新之后「这条作答属于哪一组」就永久丢失，判据只能退回位置窗口——那正是本包要修的旧行为。
#: 与「跳过必须是服务端可判定的事实」同一种做法：可判定的东西必须落在正文里。
#:
#: 为什么追加在**最后一行**：前 n 行必须与不带 `batch_id` 时逐字同形——既有判据依赖
#: `splitlines()[0] == ANSWERS_HEADER`（`session_items._window_verdict`、集成用例），
#: 且每题一行。追加在尾部让带/不带的差别只多一行，不改任何既有行的语义。
ANSWERS_BATCH_ID_MARK_PREFIX = "（本组批次标识："

#: 上面那一行的结尾。
ANSWERS_BATCH_ID_MARK_SUFFIX = "）"

#: 水合侧批次标识的前缀。与 `modules/accounts/session_items.QUESTION_BATCH_ID_PREFIX` 逐字相同：
#: `modules/*` 不得 import `surfaces/*`（项目结构设计第 7 节），因此两处各写一份字面量，
#: 相等关系由 `tests/test_accounts_session_items.py` 机械核对。
QUESTION_BATCH_ID_PREFIX = "hydrated-"

#: 批次标识的长度上界。它是**外部输入**（前端回传的关联键），因此必须有显式上界（CORE-11）
#: ——不接受无界字符串进服务端。128 与题标识、`client_message_id` 同量级。
MAX_BATCH_ID_CHARS = 128


class AnswerItem(BaseModel):
    """一道题的回答：给值，或显式跳过；二者必居其一。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    """题标识（由提问事件给出）。"""

    value: str | None = None
    """选项 label 或自由文本；跳过时为 `None`。"""

    skipped: bool = False
    """是否显式跳过。跳过是服务端可判定的事实，不是「值为空」。"""

    batch_id: str | None = None
    """本组作答的批次标识（**可选**；契约 4.1 四项见模块文档与契约）。

    顶层与逐题两处都放行（见 :func:`resolve_batch_id` 的合并规则）：契约把它的位置定在
    **顶层**（一组的批次标识，整组同属一个批次），逐题位置是为了兼容按题携带的客户端，
    两处都写时必须逐字一致。

    **空串不是缺省**：空串/全空白是 422。缺省（`None`）的语义是「本次作答不声明批次」
    ⇒ 退回位置窗口判定；而空串是「声明了一个空批次」，服务端无法据此判定任何归属。
    把两者折成同一件事会让一条伪造/损坏的载荷静默获得缺省的宽松处置。
    """

    @field_validator("id")
    @classmethod
    def _require_id(cls, value: str) -> str:
        """题标识不能为空或全空白。

        空标识会让「跳过」在渲染后失去题与行的对应关系——服务端再也说不清
        跳过的是哪一道题，而「跳过即未排除」正是靠这条对应成立的。
        """
        if not value.strip():
            raise ValueError("题标识不能为空")
        return value

    @field_validator("batch_id")
    @classmethod
    def _check_batch_id(cls, value: str | None) -> str | None:
        """批次标识非空且不超上界；`None`（未声明）原样放行。

        与 `_require_id` 同一风格（去空白后判空 + 显式上界），但**空串不能折成缺省**：
        两者语义不同（见字段说明），静默折算会让不可判定的载荷冒充「不声明」。
        """
        if value is None:
            return None
        if not value.strip():
            raise ValueError("批次标识不能为空")
        if len(value) > MAX_BATCH_ID_CHARS:
            raise ValueError(f"批次标识超过 {MAX_BATCH_ID_CHARS} 字符上界")
        return value

    @model_validator(mode="after")
    def _require_exactly_one_form(self) -> AnswerItem:
        """`value` 与 `skipped: true` 互斥且必居其一。"""
        if self.skipped and self.value is not None:
            raise ValueError("跳过时不得同时给值")
        if not self.skipped and (self.value is None or not self.value.strip()):
            raise ValueError("未跳过时必须给一个非空的值")
        return self


class SendMessageRequest(BaseModel):
    """`POST /consult/sessions/{id}/messages` 的请求体（契约 4.1）。

    `extra="forbid"`：多给的字段是 422 而不是被忽略。前端传错字段名（例如把
    `client_message_id` 写成 `clientMessageId`）时，静默忽略会让每一次重发都
    变成一次新运行——使用者看到自己的消息被重复回答，而没有任何地方报错。
    """

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    answers: list[AnswerItem] | None = None
    batch_id: str | None = None
    """本组作答的批次标识（**可选**）——契约 4.1 的**正位**。

    位置说明：`batch_id` 描述的是「这**一组**题」的批次（通用基座第 7.2 节：批次是回答
    回传时的关联键），整组同属一个批次，因此它天然属于载荷顶层。逐题位置
    （:class:`AnswerItem.batch_id`）为兼容按题携带的客户端而一并放行，两处都写时
    必须逐字一致（合并规则见 :func:`resolve_batch_id`）。

    缺省（`None`）= 本次作答不声明批次 ⇒ 服务端退回位置窗口判定（契约 4.1 第 3 条），
    旧客户端因此不被拒。空串与缺省不同：空串 422（第 1 条）。
    """

    skill: str | None = None
    client_message_id: str

    @field_validator("batch_id")
    @classmethod
    def _check_batch_id(cls, value: str | None) -> str | None:
        """批次标识非空且不超上界；`None`（未声明）原样放行。理由同 `AnswerItem`。"""
        if value is None:
            return None
        if not value.strip():
            raise ValueError("批次标识不能为空")
        if len(value) > MAX_BATCH_ID_CHARS:
            raise ValueError(f"批次标识超过 {MAX_BATCH_ID_CHARS} 字符上界")
        return value

    @field_validator("content")
    @classmethod
    def _check_content(cls, value: str | None) -> str | None:
        """正文非空且不超上界。"""
        if value is None:
            return None
        if not value.strip():
            raise ValueError("消息正文不能为空")
        if len(value) > MAX_CONTENT_CHARS:
            raise ValueError(f"消息正文超过 {MAX_CONTENT_CHARS} 字符上界")
        return value

    @field_validator("skill")
    @classmethod
    def _check_skill(cls, value: str | None) -> str | None:
        """技能名非空且不超上界（是否为已注册技能由端点按注册表判定）。"""
        if value is None:
            return None
        if not value.strip():
            raise ValueError("技能名不能为空")
        if len(value) > MAX_SKILL_NAME_CHARS:
            raise ValueError(f"技能名超过 {MAX_SKILL_NAME_CHARS} 字符上界")
        return value

    @field_validator("client_message_id")
    @classmethod
    def _check_client_message_id(cls, value: str) -> str:
        """幂等键非空且不超上界。"""
        if not value.strip():
            raise ValueError("client_message_id 不能为空")
        if len(value) > MAX_CLIENT_MESSAGE_ID_CHARS:
            raise ValueError(f"client_message_id 超过 {MAX_CLIENT_MESSAGE_ID_CHARS} 字符上界")
        return value

    @model_validator(mode="after")
    def _require_exactly_one_shape(self) -> SendMessageRequest:
        """两种形态二选一，服务端按字段判别（契约 4.1）。

        空数组与「没有这个字段」必须分开：`answers: []` 是一次「一组零道题的
        提交」，没有任何可落的内容，按载荷不合法拒绝（它多半意味着前端的题组
        状态丢了）；而两个字段都不给则是「什么都没说」，同样拒绝。
        """
        has_content = self.content is not None
        has_answers = self.answers is not None
        if has_content and has_answers:
            raise ValueError("content 与 answers 只能给一个")
        if not has_content and not has_answers:
            raise ValueError("必须给 content 或 answers 之一")
        if self.answers is not None:
            if not self.answers:
                raise ValueError("answers 不能是空数组")
            if len(self.answers) > MAX_ANSWERS:
                raise ValueError(f"answers 超过 {MAX_ANSWERS} 道上界")
            ids = [item.id for item in self.answers]
            if len(set(ids)) != len(ids):
                raise ValueError("answers 里有重复的题标识")
        return self

    def resolve_batch_id(self) -> str | None:
        """把顶层与逐题的 `batch_id` 合并成**唯一**声明；无声明时返回 `None`。

        两处都放行的代价是「同一载荷可能有两种读法」，因此必须有唯一解释，否则归属会
        取决于「谁先读」。合并规则（三支，各自可区分）：

        - 只有顶层声明 ⇒ 用它；
        - 只有逐题声明 ⇒ 用**逐题里唯一的那个值**；
        - 两处都声明 ⇒ 用顶层（一致性已由 :meth:`_require_consistent_batch_id` 在
          解析期校验，两处必逐字相等，因此取哪个都一样）。

        **校验不在这里做**（这里只读）：`batch_id` 两处位置的不一致是**载荷不合法**，
        必须由 pydantic 校验器在解析期抛出 ⇒ 端点回 **422** 而不是 500。
        把校验写在访问器里会让它逃过 `RequestValidationError` 的处理路径。
        """
        if self.answers is None or self.batch_id is not None:
            return self.batch_id
        declared = {item.batch_id for item in self.answers if item.batch_id is not None}
        return next(iter(declared)) if len(declared) == 1 else None

    @model_validator(mode="after")
    def _require_consistent_batch_id(self) -> SendMessageRequest:
        """`batch_id` 的两处位置必须给出**同一个**声明，且只能出现在作答形态上。

        三条判据（各自可区分；不一致是**载荷不合法** ⇒ 422，不是「取一个」）：

        1. 普通消息形态（`content`）不得携带 `batch_id`——它描述的是**一组题**的批次，
           普通消息没有批次可言。静默忽略会让前端的映射错误永远看不见；
        2. 逐题之间的 `batch_id` 必须一致——一组作答不可能同时属于两个批次；
        3. 逐题与顶层都写了时必须逐字相等（同理：矛盾胜于猜测）。

        **为什么放在这里而不是访问器里**：`ValueError` 从 pydantic 的 `model_validator`
        抛出会被 FastAPI 收成 422（`RequestValidationError`）；从端点代码里抛却是 500。
        校验点必须落在能产出 422 的那一侧。
        """
        if self.answers is None:
            if self.batch_id is not None:
                raise ValueError("普通消息形态不得携带 batch_id（它只属于一组作答）")
            return self
        declared = {item.batch_id for item in self.answers if item.batch_id is not None}
        if len(declared) > 1:
            raise ValueError("逐题 batch_id 不一致：一组作答只能属于一个批次")
        if self.batch_id is not None and declared and self.batch_id not in declared:
            raise ValueError("顶层 batch_id 与逐题 batch_id 不一致：一组作答只能属于一个批次")
        return self


def render_answers(answers: list[AnswerItem], *, batch_id: str | None = None) -> str:
    """把一组回答渲染成一条使用者消息的正文（编排器裁决 4）。

    形状是固定的四要素：一句表头 + 每题一行「题标识：值」或「题标识：（跳过）」。
    用题标识而不是题干，**理由是【契约形状】而不是"题干不可得"**（2026-10-06 订正）：

    - 契约 4.1 的作答回传形状就是 `{ "id": …, "value": … }`（题标识 + 值），
      本文正文因此逐行照它的形状渲染 —— 一行一题，`id` 在前、值在后；
    - **⚠ 不要把它读成"题干在服务端拿不到"**：那是本函数订正掉的旧说法，**它不成立**——
      `question` 事件载荷里**有** `prompt`（通用基座 7.2 节），
      且 T27 已让提问可从 `agent_messages` 的 `function_call.arguments` 重建
      （见 `modules/accounts/session_items.py`）。
    - 本函数**只是没有拿到题干**（签名只收 `answers`，全是"回答值"这一类数据），
      **不是服务端没有这个数据**。要在这里写出题干，就得再查一次会话真源 ——
      那是**改变本文形状**的改动（会让作答正文与契约 4.1 不再同形），**故不做**；
      编一个题干出来同样是伪造。

    ★ `batch_id`（2026-10-06 随 C-2）作为**最后一行**追加，形状是
    `（本组批次标识：<值>）`；未声明时不追加任何行。理由见
    :data:`ANSWERS_BATCH_ID_MARK_PREFIX`：前 n 行与不带它时逐字同形（既有判据依赖
    `splitlines()[0]` 与「每题一行」），而声明**必须落进正文**，否则回看侧
    （水合判定）拿不到归属依据。

    Args:
        answers: 一组回答。
        batch_id: 本组的批次标识；`None`（未声明）时不追加声明行。

    Returns:
        渲染后的正文。
    """
    lines = [ANSWERS_HEADER]
    for answer in answers:
        body = SKIPPED_MARK if answer.skipped else (answer.value or "")
        lines.append(f"{answer.id}{ANSWER_SEPARATOR}{body}")
    if batch_id is not None:
        lines.append(f"{ANSWERS_BATCH_ID_MARK_PREFIX}{batch_id}{ANSWERS_BATCH_ID_MARK_SUFFIX}")
    return "\n".join(lines)


def declared_batch_id(text: str) -> str | None:
    """从渲染出的正文里读回本组声明的批次标识；未声明时返回 `None`。

    **必须与 :func:`render_answers` 同源**：写侧的格式改了而这里没改，后果是**静默**的
    ——声明读不回来 ⇒ 归属退回位置窗口 ⇒ 本包修掉的「B 被误判 `True`」原样回来，
    而没有任何地方报错。因此两处共用同一对常量，并由「渲染 → 读回」的往返用例钉住
    （见 `tests/test_consult_transport.py`）。

    判据是**整行**逐字等于 `（本组批次标识：<值>）`（前缀在行首、后缀在行尾），
    不是「含有该字样」：后者会被使用者的自由文本误命中——他完全可能在一行作答里
    写出这句话（同 :func:`skipped_answer_ids` 的边界，那里踩过同一个坑）。

    为什么取**最后**一个匹配：写侧只追加一行，正常载荷里至多一行；若复述/异常载荷里
    出现多行，取最后一个才是「最近一次渲染追加的那个」。**本函数不剥 `hydrated-` 前缀**
    ——剥前缀与归属判定归 `modules/accounts`（模块边界：本模块只管载荷形状）。
    """
    found: str | None = None
    for line in text.split("\n"):
        stripped = line.strip()
        if not (stripped.startswith(ANSWERS_BATCH_ID_MARK_PREFIX) and stripped.endswith(ANSWERS_BATCH_ID_MARK_SUFFIX)):
            continue
        value = stripped[len(ANSWERS_BATCH_ID_MARK_PREFIX) : -len(ANSWERS_BATCH_ID_MARK_SUFFIX)]
        if not value.strip():
            continue
        found = value
    return found


def skipped_answer_ids(text: str) -> list[str]:
    """从渲染出的正文里读回被显式跳过的题标识（服务端可判定的判据）。

    判据是「某一行的作答部分逐字等于 :data:`SKIPPED_MARK`」，而不是「值为空」
    或「含有跳过的字样」：前者会把一道题的空值当成跳过，后者会被使用者的自由
    文本误命中（他完全可能写「这一题我选择（跳过）」）。这条例外是真实的——
    自由文本是可选的作答形式之一。
    """
    skipped: list[str] = []
    for line in text.split("\n")[1:]:
        identifier, separator, value = line.partition(ANSWER_SEPARATOR)
        if not separator:
            continue
        if value == SKIPPED_MARK:
            skipped.append(identifier)
    return skipped


__all__ = [
    "ANSWER_SEPARATOR",
    "ANSWERS_BATCH_ID_MARK_PREFIX",
    "ANSWERS_BATCH_ID_MARK_SUFFIX",
    "ANSWERS_HEADER",
    "MAX_ANSWERS",
    "MAX_BATCH_ID_CHARS",
    "MAX_CLIENT_MESSAGE_ID_CHARS",
    "MAX_CONTENT_CHARS",
    "MAX_SKILL_NAME_CHARS",
    "QUESTION_BATCH_ID_PREFIX",
    "SKIPPED_MARK",
    "AnswerItem",
    "SendMessageRequest",
    "declared_batch_id",
    "render_answers",
    "skipped_answer_ids",
]
