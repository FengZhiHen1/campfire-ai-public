"""红线安全门（ADR-008 二元判定，代码层零 LLM）。

判定规则链（红线安全门与兜底策略 §三，按序短路）：
1. 桶分流：自伤/攻击/走失/用药 → 直接命中（BUCKET_{桶名}）
2. 关键词硬拦截 + 否定词过滤（没有/不会/以前 → 排除窗口内命中）
3. 档案叠加：历史自伤/攻击记录 + 又/再次/还是 → PROFILE_RECURRENCE
4. 以上未命中 → pass

安全底线：本模块纯确定性规则，禁止引入任何模型调用（两条底线之一）。
"""

from __future__ import annotations

from py_schemas.crisis import RedlineGateRequest, RedlineGateResult
from py_schemas.enums import REDLINE_BUCKETS, GateResult

# 复发触发词（档案叠加规则，机制 §3.4）
_RECURRENCE_TRIGGERS = ("又", "再次", "还是")

# 否定词覆盖窗口：否定词后 N 字内的高危词命中被排除
_NEGATION_WINDOW = 6


class RedlineGate:
    """红线安全门——二元判定器。

    构造注入词库（由 keywords.py 从 DB 加载 + 内置默认兜底），
    判定过程零 I/O、零 LLM，0ms 完成。
    """

    def __init__(
        self,
        keywords: list[tuple[str, str]],
        negations: list[str] | None = None,
    ) -> None:
        """
        Args:
            keywords: [(关键词原文, 触发规则 ID)] 词库。
            negations: 否定词表（默认 没有/不会/以前）。
        """
        self._keywords = [(kw, rule) for kw, rule in keywords if kw]
        self._negations = negations or ["没有", "不会", "以前"]

    async def evaluate(
        self,
        request: RedlineGateRequest,
        profile_has_harm_history: bool | None,
    ) -> RedlineGateResult:
        """执行红线判定。

        Args:
            request: 判定请求（桶 + 可选文字）。
            profile_has_harm_history: 档案是否有自伤/攻击历史事件；
                None/False 时档案叠加规则自动跳过（机制 §3.4 冷启动）。

        Returns:
            RedlineGateResult（gate_result + gate_trigger）。
        """
        # 规则 1：桶分流（红线桶直接命中）
        if request.bucket is not None and request.bucket in REDLINE_BUCKETS:
            return RedlineGateResult(
                gate_result=GateResult.REDLINE,
                gate_trigger=f"BUCKET_{request.bucket.name}",
                detail=f"红线桶点选：{request.bucket.ui_label}",
            )

        text = (request.text or "").strip()
        if text:
            # 规则 2：关键词硬拦截（否定过滤）
            keyword_hit = self._match_keyword(text)
            if keyword_hit is not None:
                keyword, rule_id = keyword_hit
                return RedlineGateResult(
                    gate_result=GateResult.REDLINE,
                    gate_trigger=rule_id,
                    detail=f"命中关键词：{keyword}",
                )

            # 规则 3：档案叠加（历史自伤/攻击 + 复发词）
            if profile_has_harm_history and any(t in text for t in _RECURRENCE_TRIGGERS):
                return RedlineGateResult(
                    gate_result=GateResult.REDLINE,
                    gate_trigger="PROFILE_RECURRENCE",
                    detail="档案自伤/攻击史叠加复发表述",
                )

        return RedlineGateResult(gate_result=GateResult.PASS)

    # ------------------------------------------------------------------
    # 关键词匹配（否定窗口过滤）
    # ------------------------------------------------------------------

    def _match_keyword(self, text: str) -> tuple[str, str] | None:
        """关键词匹配——命中位置在否定窗口内则排除。

        窗口语义：否定词出现位置后 _NEGATION_WINDOW 字内的高危词命中排除
        （「没有撞头」「以前撞墙」不命中；窗口外的命中仍然生效）。
        """
        for keyword, rule_id in self._keywords:
            start = 0
            while True:
                idx = text.find(keyword, start)
                if idx == -1:
                    break
                if not self._is_negated(text, idx):
                    return (keyword, rule_id)
                start = idx + 1
        return None

    def _is_negated(self, text: str, keyword_idx: int) -> bool:
        """判定关键词命中位置是否处于否定窗口内。"""
        for negation in self._negations:
            neg_idx = 0
            while True:
                neg_idx = text.find(negation, neg_idx)
                if neg_idx == -1:
                    break
                # 否定词起点在高危词之前，且距离在窗口内
                if neg_idx < keyword_idx and keyword_idx - (neg_idx + len(negation)) <= _NEGATION_WINDOW:
                    return True
                neg_idx += 1
        return False


__all__ = ["RedlineGate"]
