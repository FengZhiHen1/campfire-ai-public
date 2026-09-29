"""注入消息信封的属性转义。

基座自己渲染的信封（``<available_skills>``、``<skill_content>``、
``<skill_resources>``、``<unavailable_sources>``、``<tool_availability>``）都是
「属性携带来源数据」的形状，因此转义只有一个契约。放在基座根而不是各子包里，
是因为它有三个消费者（skill 目录、skill 激活、注入项与工具可用性），
三份拷贝必然分叉——而分叉的那一份会把伪造的 ``"`` 直接放进信封。
"""

from __future__ import annotations


def escape_attribute(value: str) -> str:
    """转义 XML 属性值里的五个危险字符。"""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
