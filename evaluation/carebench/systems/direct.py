"""A 组：同一底座模型的直接问答（无检索、无档案、无 skill、无工具）。

职责：只做「共同任务边界 + 使用者文本 → 一次完成调用」。

边界：不 import 产品检索链、工具池、skill 注册表与运行时——A 组的价值就在于它是一个
**诚实的下界**：如果它自己偷偷用了产品能力，A/B/C 的差异就不再能归因到检索或工作流。

协议依据：01 第 4 节「同一底座模型 + 精简的共同任务说明 + 当前输入；无检索、无档案、
无特制领域 Skills」；05 第 4 节「不额外调用检索/业务 Tools」。
"""

from __future__ import annotations

from .chat import ChatSystem


class DirectLLM(ChatSystem):
    """A 组适配器。"""

    system_id = "A"

    @property
    def assembly_note(self) -> str:
        """装配说明（进 manifest）。"""
        return "单次 chat.completions：产品模型网关客户端与模型 id；无检索、无工具、无 skill、无档案"
