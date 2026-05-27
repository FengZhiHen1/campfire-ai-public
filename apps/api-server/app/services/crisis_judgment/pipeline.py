"""CSLT-01 危机分级判定 — JudgmentPipeline Pipeline 管道。

顺序执行三层判定（PreSelectionLayer -> RuleEngineLayer -> LLMReviewLayer），
根据各层结果支持短路跳转（重度直接输出）和降级回退（LLM 超时降级规则引擎），
最终通过 merge() 合并各层结果输出 CrisisJudgmentResult。
"""

from __future__ import annotations

from typing import Any

from . import merge_matrix
from .enums import CrisisLevel
from .exceptions import CrisisJudgmentError, KeywordDictLoadError
from .layer import JudgmentLayer
from .llm_review_layer import LLMReviewLayer
from .models import (
    CrisisJudgmentRequest,
    CrisisJudgmentResult,
    JudgmentContext,
    JudgmentLayerResult,
)
from .pre_selection_layer import PreSelectionLayer
from .rule_engine_layer import RuleEngineLayer
from py_logger import logger


class JudgmentPipeline:
    """危机分级判定 Pipeline。

    顺序执行三层判定，支持短路跳转和降级回退。
    线程安全：每次调用 run() 创建独立的 JudgmentContext。

    Usage:
        pipeline = JudgmentPipeline()
        result = await pipeline.run(request)
    """

    def __init__(
        self,
        pre_selection: JudgmentLayer | None = None,
        rule_engine: JudgmentLayer | None = None,
        llm_review: JudgmentLayer | None = None,
    ) -> None:
        """初始化 Pipeline。

        Args:
            pre_selection: 前置选择层实例（默认创建 PreSelectionLayer）。
            rule_engine: 规则引擎层实例（默认创建 RuleEngineLayer）。
            llm_review: LLM 复审层实例（默认创建 LLMReviewLayer）。
        """
        self._pre_selection = pre_selection or PreSelectionLayer()
        self._rule_engine = rule_engine or RuleEngineLayer()
        self._llm_review = llm_review or LLMReviewLayer()

    async def run(self, request: CrisisJudgmentRequest) -> CrisisJudgmentResult:
        """执行完整的三层递进危机分级判定。

        Args:
            request: 危机分级判定请求。

        Returns:
            合并后的最终判定结果。

        Raises:
            CrisisJudgmentError: 不可恢复的判定错误。
        """
        # 初始化上下文
        context = JudgmentContext(request=request)

        # ===== 步骤 1：前置行为类型判定 =====
        await self._run_pre_selection(context)

        # ===== 步骤 1.5：患者档案缺失检查 =====
        # 在前置选择之后、规则引擎之前检查。若 profile_missing 与
        # rule_engine_degraded 共存，后者覆盖前者（安全性更高的降级）。
        if request.patient_profile is None:
            context.degradation_note = "profile_missing"

        # ===== 步骤 2（条件）：规则引擎关键词匹配 =====
        if not context.skip_remaining:
            await self._run_rule_engine(context)

        # ===== 步骤 3（条件）：LLM 精调复审 =====
        if not context.skip_remaining:
            await self._run_llm_review(context)

        # ===== 步骤 4：合并输出 =====
        return self._merge(context)

    # ------------------------------------------------------------------
    # 各层执行
    # ------------------------------------------------------------------

    async def _run_pre_selection(self, context: JudgmentContext) -> None:
        """执行前置行为类型判定。

        Args:
            context: Pipeline 运行时上下文。
        """
        try:
            result: JudgmentLayerResult = await self._pre_selection.judge(
                context.request,
            )
        except Exception as exc:
            logger.error(
                service="crisis_judgment",
                message="PreSelectionLayer unexpected error",
                op_type=None,
                extra={"error": str(exc)},
            )
            raise CrisisJudgmentError(
                "PreSelectionLayer failed unexpectedly",
                original_error=exc if isinstance(exc, Exception) else None,
            ) from exc

        context.sources.append(result)

        if result.level == CrisisLevel.SEVERE:
            context.level = CrisisLevel.SEVERE
            context.block_deep = True
            context.skip_remaining = True

        logger.info(
            service="crisis_judgment",
            message="PreSelectionLayer completed",
            op_type=None,
            extra={
                "level": result.level.value if result.level else None,
                "skip_remaining": context.skip_remaining,
            },
        )

    async def _run_rule_engine(self, context: JudgmentContext) -> None:
        """执行规则引擎关键词匹配。

        Args:
            context: Pipeline 运行时上下文。
        """
        try:
            result: JudgmentLayerResult = await self._rule_engine.judge(
                context.request,
            )
        except KeywordDictLoadError:
            # 关键词词库加载失败 —— 降级
            context.degradation_note = "rule_engine_degraded"
            result = JudgmentLayerResult(
                layer_name="RuleEngineLayer",
                level=None,
                trigger_rule_id=None,
                details={"degraded": True},
            )
        except Exception as exc:
            logger.error(
                service="crisis_judgment",
                message="RuleEngineLayer unexpected error",
                op_type=None,
                extra={"error": str(exc)},
            )
            raise CrisisJudgmentError(
                "RuleEngineLayer failed unexpectedly",
                original_error=exc if isinstance(exc, Exception) else None,
            ) from exc

        context.sources.append(result)

        # Bug 4b: 从规则引擎结果传播 manual_review_flag
        if result.details.get("manual_review_recommended") or result.details.get(
            "profile_overlap_triggered"
        ):
            context.manual_review_flag = True

        if result.level == CrisisLevel.SEVERE:
            context.level = CrisisLevel.SEVERE
            context.block_deep = True
            context.skip_remaining = True

        logger.info(
            service="crisis_judgment",
            message="RuleEngineLayer completed",
            op_type=None,
            extra={
                "level": result.level.value if result.level else None,
                "matched_keywords": result.details.get("matched_keywords", []),
                "skip_remaining": context.skip_remaining,
                "degraded": result.details.get("degraded", False),
            },
        )

    async def _run_llm_review(self, context: JudgmentContext) -> None:
        """执行 LLM 精调复审。

        Args:
            context: Pipeline 运行时上下文。
        """
        try:
            result: JudgmentLayerResult = await self._llm_review.judge(
                context.request,
            )
        except Exception as exc:
            logger.error(
                service="crisis_judgment",
                message="LLMReviewLayer unexpected error",
                op_type=None,
                extra={"error": str(exc)},
            )
            # LLM 异常不阻断流程 —— 降级为无 LLM 判定
            result = JudgmentLayerResult(
                layer_name="LLMReviewLayer",
                level=None,
                trigger_rule_id=None,
                details={"error": str(exc)[:200]},
            )

        context.sources.append(result)

        # 检查超时
        if result.details.get("timeouts", False):
            context.llm_timed_out = True
            logger.warning(
                service="crisis_judgment",
                message="LLM review timed out, falling back to rule engine result",
                op_type=None,
                extra={
                    "elapsed_ms": result.details.get("elapsed_ms"),
                },
            )

        # 记录 LLM 置信度
        if result.level is not None and not context.llm_timed_out:
            context.level = result.level

        logger.info(
            service="crisis_judgment",
            message="LLMReviewLayer completed",
            op_type=None,
            extra={
                "level": result.level.value if result.level else None,
                "timed_out": context.llm_timed_out,
            },
        )

    # ------------------------------------------------------------------
    # 合并策略
    # ------------------------------------------------------------------

    @staticmethod
    def _merge(context: JudgmentContext) -> CrisisJudgmentResult:
        """执行"宁升勿降"合并策略。

        使用 MERGE_MATRIX 二维查找表合并各层判定结果。

        合并规则：
            - 前置选择已判 severe -> 直接输出 severe（跳过矩阵查找）
            - severe + any = severe（宁升勿降）
            - llm_timed_out = True -> 采用规则引擎等级为 final_level
            - 未定义组合 -> 回退到 max(rule, llm)

        Args:
            context: Pipeline 运行时上下文。

        Returns:
            合并后的最终判定结果。
        """
        # 提取各层结果
        pre_result: JudgmentLayerResult | None = None
        rule_result: JudgmentLayerResult | None = None
        llm_result: JudgmentLayerResult | None = None

        for source in context.sources:
            if source.layer_name == "PreSelectionLayer":
                pre_result = source
            elif source.layer_name == "RuleEngineLayer":
                rule_result = source
            elif source.layer_name == "LLMReviewLayer":
                llm_result = source

        # 情况 1：前置选择命中 severe -> 直接输出
        if pre_result and pre_result.level == CrisisLevel.SEVERE:
            return CrisisJudgmentResult(
                final_level=CrisisLevel.SEVERE,
                block_deep_response=True,
                manual_review_flag=False,
                review_confidence=None,
                judgment_sources=context.sources,
                degradation_note=context.degradation_note,
            )

        # 情况 2：LLM 超时 -> 采用规则引擎结果
        if context.llm_timed_out:
            final_level: CrisisLevel = (
                rule_result.level if rule_result and rule_result.level
                else CrisisLevel.MILD
            )
            return CrisisJudgmentResult(
                final_level=final_level,
                block_deep_response=(final_level == CrisisLevel.SEVERE),
                manual_review_flag=context.manual_review_flag,
                review_confidence=None,
                judgment_sources=context.sources,
                degradation_note=context.degradation_note,
            )

        # 情况 3：规则引擎命中 severe -> 直接输出
        if rule_result and rule_result.level == CrisisLevel.SEVERE:
            return CrisisJudgmentResult(
                final_level=CrisisLevel.SEVERE,
                block_deep_response=True,
                manual_review_flag=context.manual_review_flag,
                review_confidence=None,
                judgment_sources=context.sources,
                degradation_note=context.degradation_note,
            )

        # 情况 4：正常合并（使用 MERGE_MATRIX）
        rule_level: CrisisLevel | None = rule_result.level if rule_result else None
        llm_level: CrisisLevel | None = llm_result.level if llm_result else None

        try:
            merged_level: CrisisLevel = merge_matrix.lookup(rule_level, llm_level)
        except KeyError:
            # 回退策略：取 max
            merged_level = _max_level(rule_level, llm_level)

        return CrisisJudgmentResult(
            final_level=merged_level,
            block_deep_response=(merged_level == CrisisLevel.SEVERE),
            manual_review_flag=context.manual_review_flag,
            review_confidence=(
                llm_result.details.get("confidence")
                if llm_result and not context.llm_timed_out
                else None
            ),
            judgment_sources=context.sources,
            degradation_note=context.degradation_note,
        )


def _max_level(a: CrisisLevel | None, b: CrisisLevel | None) -> CrisisLevel:
    """取两个等级中较高的一个（severe > moderate > mild）。

    Args:
        a: 等级 A。
        b: 等级 B。

    Returns:
        较高的等级。两个都为 None 时返回 mild。
    """
    order: list[CrisisLevel] = [
        CrisisLevel.MILD,
        CrisisLevel.MODERATE,
        CrisisLevel.SEVERE,
    ]
    a_idx: int = order.index(a) if a else 0
    b_idx: int = order.index(b) if b else 0
    return order[max(a_idx, b_idx)]
