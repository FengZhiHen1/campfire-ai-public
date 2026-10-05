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


class AnswerItem(BaseModel):
    """一道题的回答：给值，或显式跳过；二者必居其一。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    """题标识（由提问事件给出）。"""

    value: str | None = None
    """选项 label 或自由文本；跳过时为 `None`。"""

    skipped: bool = False
    """是否显式跳过。跳过是服务端可判定的事实，不是「值为空」。"""

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
    skill: str | None = None
    client_message_id: str

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


def render_answers(answers: list[AnswerItem]) -> str:
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
    """
    lines = [ANSWERS_HEADER]
    for answer in answers:
        body = SKIPPED_MARK if answer.skipped else (answer.value or "")
        lines.append(f"{answer.id}{ANSWER_SEPARATOR}{body}")
    return "\n".join(lines)


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
    "ANSWERS_HEADER",
    "MAX_ANSWERS",
    "MAX_CLIENT_MESSAGE_ID_CHARS",
    "MAX_CONTENT_CHARS",
    "MAX_SKILL_NAME_CHARS",
    "SKIPPED_MARK",
    "AnswerItem",
    "SendMessageRequest",
    "render_answers",
    "skipped_answer_ids",
]
