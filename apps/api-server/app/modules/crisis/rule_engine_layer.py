"""CSLT-01 危机分级判定 — RuleEngineLayer 规则引擎判定层。

执行 AC 自动机扫描 + 否定词过滤 + 档案叠加规则。
命中 severe 关键词时直接判定重度并跳过 LLM 复审。
"""

from __future__ import annotations

import re
from typing import Any

from .ac_matcher import AhoCorasickMatcher, _negation_filter
from .enums import CrisisLevel
from .layer import JudgmentLayer
from .models import (
    CrisisJudgmentRequest,
    JudgmentLayerResult,
)
from py_logger import logger

# 档案叠加规则触发词
_PROFILE_OVERLAP_TRIGGERS: list[str] = ["又", "再次", "还是"]

# 档案叠加规则匹配的历史行为标签
_PROFILE_OVERLAP_TAGS: list[str] = ["self_injury", "aggression"]


class RuleEngineLayer(JudgmentLayer):
    """规则引擎判定层。

    执行 AC 自动机关键词扫描，对匹配结果执行否定词过滤，
    然后执行档案叠加规则。命中 severe 关键词时输出重度。
    """

    def __init__(
        self,
        matcher: AhoCorasickMatcher | None = None,
    ) -> None:
        """初始化规则引擎层。

        Args:
            matcher: AC 自动机匹配器实例。为 None 时通过 get_instance() 获取。
        """
        self._matcher = matcher

    async def judge(self, request: CrisisJudgmentRequest) -> JudgmentLayerResult:
        """执行规则引擎判定。

        步骤：
            1. AC 自动机扫描 behavior_description
            2. 否定词过滤每条匹配
            3. 对未否定的匹配进行等级判定
            4. 执行档案叠加规则

        Args:
            request: 危机分级判定请求。

        Returns:
            规则引擎层的判定结果。
        """
        # 步骤 1：获取 AC 自动机匹配器
        if self._matcher is None:
            try:
                self._matcher = await AhoCorasickMatcher.get_instance()
            except Exception:
                # 词库加载失败 —— 标记降级
                return JudgmentLayerResult(
                    layer_name="RuleEngineLayer",
                    level=None,
                    trigger_rule_id=None,
                    details={"degraded": True},
                )

        if not self._matcher.is_loaded:
            return JudgmentLayerResult(
                layer_name="RuleEngineLayer",
                level=None,
                trigger_rule_id=None,
                details={"degraded": True},
            )

        # 步骤 2：AC 自动机扫描
        text: str = request.behavior_description
        try:
            matches = self._matcher.search(text)
        except (RuntimeError, AttributeError):
            return JudgmentLayerResult(
                layer_name="RuleEngineLayer",
                level=None,
                trigger_rule_id=None,
                details={"degraded": True},
            )

        # 步骤 3：对每条匹配执行否定词过滤
        matched_keywords: list[str] = []
        keyword_ids: list[int] = []
        trigger_rule_ids: list[str] = []
        highest_category: str = "mild"
        negation_filtered: bool = False

        for match in matches:
            # 独立执行否定词过滤：从 match 中提取 start_pos，调用 _negation_filter
            start_pos = match.get("start_pos", 0)
            if _negation_filter(match_start_pos=start_pos, text=text):
                negation_filtered = True
                continue

            matched_keywords.append(match["keyword"])
            keyword_ids.append(match["keyword_id"])
            if match.get("trigger_rule_id"):
                trigger_rule_ids.append(match["trigger_rule_id"])

            # 追踪最高分类等级
            cat = match.get("category", "mild")
            if _category_to_level(cat) > _category_to_level(highest_category):
                highest_category = cat

        # 步骤 4：判定等级
        level: CrisisLevel | None = _category_to_level(highest_category)
        trigger_rule_id: str | None = trigger_rule_ids[0] if trigger_rule_ids else None

        details: dict[str, Any] = {
            "matched_keywords": matched_keywords,
            "negation_filtered": negation_filtered,
        }

        # 步骤 5：档案叠加规则
        profile_overlap_triggered = _check_profile_overlap(request)
        if profile_overlap_triggered:
            details["profile_overlap_triggered"] = True
            details["manual_review_recommended"] = True
            # 档案叠加规则使等级提升至 moderate
            if level is None or _category_to_value(level) < 1:
                level = CrisisLevel.MODERATE
                trigger_rule_id = "PROFILE_OVERLAP_001"

        # 步骤 6：命中 severe 时记录安全日志
        if level == CrisisLevel.SEVERE:
            logger.warning(
                service="crisis_judgment",
                message="Rule engine matched severe keyword",
                op_type=None,
                extra={
                    "matched_keywords": matched_keywords,
                    "trigger_rule_id": trigger_rule_id,
                    "text_preview": text[:100],
                },
            )

        return JudgmentLayerResult(
            layer_name="RuleEngineLayer",
            level=level,
            trigger_rule_id=trigger_rule_id,
            details=details,
        )


def _category_to_level(category: str) -> CrisisLevel | None:
    """将关键词分类映射为危机等级。

    Args:
        category: 关键词分类（"severe" / "moderate" / "mild" / 其他）。

    Returns:
        对应的危机等级，无法识别时返回 None。
    """
    mapping: dict[str, CrisisLevel] = {
        "severe": CrisisLevel.SEVERE,
        "moderate": CrisisLevel.MODERATE,
        "mild": CrisisLevel.MILD,
    }
    return mapping.get(category)


def _category_to_value(level: CrisisLevel | None) -> int:
    """将危机等级转换为数值用于比较。

    Args:
        level: 危机等级。

    Returns:
        数值表示（severe=2, moderate=1, mild=0, None= -1）。
    """
    if level is None:
        return -1
    mapping: dict[CrisisLevel, int] = {
        CrisisLevel.SEVERE: 2,
        CrisisLevel.MODERATE: 1,
        CrisisLevel.MILD: 0,
    }
    return mapping.get(level, -1)


def _check_profile_overlap(request: CrisisJudgmentRequest) -> bool:
    """执行档案叠加规则检查。

    患者档案不为 None 且 historical_behavior_tags 含 "self_injury" 或 "aggression"
    且 behavior_description 含触发词 "又" / "再次" / "还是" 时触发。

    Args:
        request: 危机分级判定请求。

    Returns:
        True = 档案叠加规则触发，等级应升级至 moderate。
    """
    profile = request.patient_profile
    if profile is None:
        return False

    # 检查历史行为标签
    has_overlap_tag = any(
        tag in profile.historical_behavior_tags
        for tag in _PROFILE_OVERLAP_TAGS
    )
    if not has_overlap_tag:
        return False

    # 检查文本中是否含触发词
    text = request.behavior_description
    for trigger in _PROFILE_OVERLAP_TRIGGERS:
        if re.search(trigger, text):
            return True

    return False
