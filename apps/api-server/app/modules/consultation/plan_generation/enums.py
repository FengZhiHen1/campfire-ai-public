"""CSLT-03 应急方案生成 — 枚举类型定义。

定义 GenerationStatus 和 BlockVariant 两个 StrEnum。
枚举值必须与 docs/contracts/CSLT-03/ 下的 JSON Schema 契约严格一致。
"""

from __future__ import annotations

from enum import StrEnum


class GenerationStatus(StrEnum):
    """应急方案生成执行状态枚举。

    描述单次生成请求的最终结果状态。
    与 CSLT-02/RetrievalStatus（检索状态）语义域不同，两者不可混用。

    Values:
        COMPLETE: 正常完成 — LLM 返回完整四段式应急方案
        PARTIAL:  部分生成 — LLM 超时但已生成至少一个完整段落
        BLOCKED:  危机阻断 — block_deep_response=true, 未调用 LLM
        TIMEOUT:  完全超时 — 无任何文本产出
        ERROR:    不可恢复错误 — LLM API 不可用或 Prompt 构建异常
    """

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class BlockVariant(StrEnum):
    """危机阻断场景下的高危行为类型变体枚举。

    对应 CSLT-01 BehaviorTypeCategory 中的四种高危类型。
    每种变体对应一个不同的安全提示文本模板。

    Values:
        SELF_INJURY: 自伤行为 — 安全提示强调移除危险物品
        AGGRESSION:  攻击行为 — 安全提示强调隔离冷静
        ELOPEMENT:   逃跑/走失行为 — 安全提示强调立即报警
        MEDICATION:  误用药/过量用药 — 安全提示强调立即急救
    """

    SELF_INJURY = "SELF_INJURY"
    AGGRESSION = "AGGRESSION"
    ELOPEMENT = "ELOPEMENT"
    MEDICATION = "MEDICATION"


__all__ = [
    "GenerationStatus",
    "BlockVariant",
]
