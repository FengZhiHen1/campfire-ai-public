"""确定性兜底信号（ADR-009 第 6 条——取代置信度路由）。

代码层确定性判定，零 LLM（智能应急咨询 §七）：
- 检索质量不足：相似度低于阈值 或 命中数不足
- 用户标记未解决
- 连续追问超阈值

阈值数值为待明确项（机制 §十，上线后经数据校准）——本期取占位值，
集中在此文件便于校准期调整。
"""

from __future__ import annotations

from typing import Any

from py_schemas.enums import FallbackSignal

# 占位阈值（机制 §十 待明确项——经线上数据校准）
SIMILARITY_THRESHOLD: float = 0.50
MIN_HIT_COUNT: int = 3
MAX_FOLLOWUP_TURNS: int = 5


def evaluate_retrieval(slices: list[Any]) -> FallbackSignal | None:
    """检索质量判定：命中数不足或最高相似度低于阈值 → 兜底信号。"""
    if len(slices) < MIN_HIT_COUNT:
        return FallbackSignal.RETRIEVAL_INSUFFICIENT
    best = max((float(getattr(s, "similarity_score", 0.0) or 0.0) for s in slices), default=0.0)
    if best < SIMILARITY_THRESHOLD:
        return FallbackSignal.RETRIEVAL_INSUFFICIENT
    return None


def evaluate_followup_turns(followup_count: int) -> FallbackSignal | None:
    """连续追问超阈值判定。"""
    if followup_count > MAX_FOLLOWUP_TURNS:
        return FallbackSignal.FOLLOWUP_LIMIT
    return None


def evaluate_user_unresolved(marked: bool) -> FallbackSignal | None:
    """用户标记未解决判定。"""
    return FallbackSignal.USER_UNRESOLVED if marked else None


# 兜底提示文案（强提示 + 求助指引）
FALLBACK_MESSAGES: dict[FallbackSignal, tuple[str, str]] = {
    FallbackSignal.RETRIEVAL_INSUFFICIENT: (
        "当前可用的参考案例有限，以下建议可能不完全匹配您的情况。",
        "如情况持续或加重，请尽快联系主治医生或专业机构；紧急时刻请拨打 120。",
    ),
    FallbackSignal.USER_UNRESOLVED: (
        "已收到您的反馈——当前方案未能解决您的问题。",
        "建议立即联系主治医生或专业机构获取人工支持；紧急时刻请拨打 120。",
    ),
    FallbackSignal.FOLLOWUP_LIMIT: (
        "我们已经讨论了多轮，但问题可能仍需专业人员介入。",
        "建议尽快联系主治医生或专业机构；紧急时刻请拨打 120。",
    ),
    FallbackSignal.REDLINE_HIT: (
        "检测到安全风险信号。",
        "请立即联系专业医疗机构；紧急时刻请拨打 120。",
    ),
}


__all__ = [
    "SIMILARITY_THRESHOLD",
    "MIN_HIT_COUNT",
    "MAX_FOLLOWUP_TURNS",
    "FALLBACK_MESSAGES",
    "evaluate_retrieval",
    "evaluate_followup_turns",
    "evaluate_user_unresolved",
]
