"""应急入口的请求形状：八项现场采集的键、值的形状与整组校验。

职责：把 `POST /consult/emergency` 的请求体解析成可渲染的八项，并在边界处拒绝非法载荷。
边界：不校验取值词表（题干、选项与取值措辞归 emergency-consulting skill，本层没有
权威词表可依）、不取数、不建会话（归 `routes`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 5 节（请求形状与 422）；
docs/技术设计/面/consult/skills/emergency-consulting.md 第 2 节（八项与跳过语义）。

整组一次提交，校验粒度是整组：任一项不合法则整组 422，不做「部分收下」——收下一半
会让服务端渲染出一份看起来完整、实际缺项的现场采集，而应急场景里「缺项即未排除」
这条纪律要求缺项必须是显式的（见 `injections.render_emergency_intake`）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

#: 八项现场采集的传输键（契约第 5 节的请求示例即词表来源）。顺序即它在首条消息里的顺序。
EMERGENCY_INTAKE_KEYS: tuple[str, ...] = (
    "medical_red_flags",
    "baseline_deviation",
    "communication",
    "distress",
    "sensory_environment",
    "what_happened",
    "primary_risk",
    "possible_pain",
)

#: 多值项（请求里给 `values` 数组），其余项给单个 `value`。依据是契约第 5 节的请求示例：
#: 医疗红灯与感觉环境是勾选组，其余是单值或自由文本。
EMERGENCY_MULTI_VALUE_KEYS: frozenset[str] = frozenset({"medical_red_flags", "sensory_environment"})

#: 单项取值的长度上界（CORE-11：进入系统的文本必须有显式上界）。取 500：
#: 自由文本项（刚刚发生了什么）最多两三句话，而选项 label 远短于此。
MAX_EMERGENCY_VALUE_CHARS = 500

#: 多值项的取值个数上界（同上）。八项本身是「一只手填完」的规模，
#: 一屏勾选项不会超过这个数；越过它说明载荷是伪造的。
MAX_EMERGENCY_VALUES = 16

#: 多值项的取值之间的连接符（渲染进首条消息时用）。
VALUE_SEPARATOR = "、"


class EmergencyItem(BaseModel):
    """八项里的一项：给单值、给多值，或显式跳过；三者必居其一。"""

    model_config = ConfigDict(extra="forbid")

    key: str
    """传输键；取值必须在 :data:`EMERGENCY_INTAKE_KEYS` 内。"""

    value: str | None = None
    """单值项的取值（选项 label 或自由文本）；跳过时为 `None`。"""

    values: list[str] | None = None
    """多值项的取值；跳过时为 `None`。"""

    skipped: bool = False
    """是否显式跳过。跳过是服务端可判定的事实，不是「值为空」。"""

    @field_validator("key")
    @classmethod
    def _require_known_key(cls, value: str) -> str:
        """键必须在八项词表内（契约第 5 节：未知 `key` 是 422）。

        不静默忽略未知项：忽略会让前端以为某一项被采到了，而服务端渲染出的首条消息里
        它其实只是「未采集」——一个拼错的键就此变成一条丢掉的现场信息。
        """
        if value not in EMERGENCY_INTAKE_KEYS:
            raise ValueError(f"未知的采集项：{value}")
        return value

    @model_validator(mode="after")
    def _require_exactly_one_form(self) -> EmergencyItem:
        """形状按键的词表收口：多值项给 `values`，单值项给 `value`，跳过则两者都不给。

        为什么不接受「两种都给」或「单值项给数组」这类混合形状：渲染是逐项一行，
        形状含糊时渲染出的那一行读不出是几个取值，而现场采集的每一项都要能被
        逐条核对（`skipped` 的解释权在使用者，不在渲染的宽容度）。
        """
        if self.skipped:
            if self.value is not None or self.values is not None:
                raise ValueError(f"跳过的采集项不得同时给值：{self.key}")
            return self

        wants_values = self.key in EMERGENCY_MULTI_VALUE_KEYS
        if wants_values:
            if self.value is not None:
                raise ValueError(f"多值采集项必须用 values：{self.key}")
            if not self.values:
                raise ValueError(f"未跳过的采集项必须给至少一个取值：{self.key}")
            if len(self.values) > MAX_EMERGENCY_VALUES:
                raise ValueError(f"采集项取值个数超过 {MAX_EMERGENCY_VALUES} 上界：{self.key}")
            for item in self.values:
                if not item.strip():
                    raise ValueError(f"采集项的取值不得为空：{self.key}")
                if len(item) > MAX_EMERGENCY_VALUE_CHARS:
                    raise ValueError(f"采集项取值超过 {MAX_EMERGENCY_VALUE_CHARS} 字符上界：{self.key}")
            return self

        if self.values is not None:
            raise ValueError(f"单值采集项必须用 value：{self.key}")
        if self.value is None or not self.value.strip():
            raise ValueError(f"未跳过的采集项必须给一个非空的值：{self.key}")
        if len(self.value) > MAX_EMERGENCY_VALUE_CHARS:
            raise ValueError(f"采集项取值超过 {MAX_EMERGENCY_VALUE_CHARS} 字符上界：{self.key}")
        return self

    def rendered_value(self) -> str:
        """这一项在首条消息里的取值文本（多值按 :data:`VALUE_SEPARATOR` 连接）。

        只在未跳过且已通过校验时调用：跳过的项由渲染方写成固定标记，
        不会走到这里（`emergency_consulting` 第 2 节：跳过即未排除）。
        """
        if self.values is not None:
            return VALUE_SEPARATOR.join(self.values)
        return self.value or ""


class EmergencyConsultRequest(BaseModel):
    """`POST /consult/emergency` 的请求体（契约第 5 节）。

    `extra="forbid"`：多给的字段是 422 而不是被忽略。前端把 `supportObjectId`
    写成驼峰时，静默忽略会让这次应急落到账号的默认对象上——而使用者明确的绑定意图
    就此消失，且没有任何地方报错（与 `SendMessageRequest` 同一条纪律）。
    """

    model_config = ConfigDict(extra="forbid")

    support_object_id: str | None = None
    """要绑定的支持对象；省略时按支持对象第 6 节推导默认对象。"""

    items: list[EmergencyItem]
    """八项现场采集。可以不齐（缺项按「未采集即未排除」渲染），但不能为空、不能重键。"""

    @field_validator("support_object_id")
    @classmethod
    def _check_object_id(cls, value: str | None) -> str | None:
        """对象标识非空且不超上界（是否存在与可写由端点经 `require_writable` 判定）。"""
        if value is None:
            return None
        if not value.strip():
            raise ValueError("支持对象标识不能为空")
        if len(value) > 128:
            raise ValueError("支持对象标识超过 128 字符上界")
        return value

    @model_validator(mode="after")
    def _require_items(self) -> EmergencyConsultRequest:
        """整组校验：至少一项、不重复键、不超过八项。

        为什么允许少于八项：缺项在渲染时是显式的「未采集（未排除）」，比整组拒绝更接近
        现场事实（表单可能只有一部分填完）。而空数组是 422——一次零项的应急提交没有
        任何可注入的现场信息，它多半意味着前端的表单状态丢了，不是使用者的意图。
        """
        if not self.items:
            raise ValueError("items 不能是空数组")
        keys = [item.key for item in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("items 里有重复的采集项")
        return self


__all__ = [
    "EMERGENCY_INTAKE_KEYS",
    "EMERGENCY_MULTI_VALUE_KEYS",
    "MAX_EMERGENCY_VALUE_CHARS",
    "MAX_EMERGENCY_VALUES",
    "VALUE_SEPARATOR",
    "EmergencyConsultRequest",
    "EmergencyItem",
]
