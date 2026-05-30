"""CSLT-01 危机分级判定管线实现（管线步骤 4-6）。

继承 CrisisJudgmentPipeline 契约 ABC，填写 4 个 _do_ 钩子。
复用 PreSelectionLayer、RuleEngineLayer、LLMReviewLayer 三层判定组件，
以及 merge_matrix "宁升勿降"合并策略。

负责将三层递进判定结果合并为最终 CrisisJudgmentResult。
"""

from __future__ import annotations

from typing import Any

from . import merge_matrix
from .crisis_contract import CrisisJudgmentPipeline
from .enums import CrisisLevel
from .exceptions import CrisisJudgmentError, KeywordDictLoadError
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


class CrisisJudgmentPipelineImpl(CrisisJudgmentPipeline):
    """危机分级判定管线实现。

    继承 CrisisJudgmentPipeline 契约 ABC，实现全部 4 个 _do_ 钩子。
    外部调用者通过 @final run() 进入，无法绕过前置校验和后置处理。

    Usage:
        pipeline = CrisisJudgmentPipelineImpl()
        result = await pipeline.run(request)
    """

    def __init__(
        self,
        llm_client: Any = None,
        keyword_loader: Any = None,
    ) -> None:
        """初始化管线实现。

        创建三层判定组件实例。LLM 复审层接收注入的 llm_client。

        Args:
            llm_client: LLM 客户端实例（py_llm），传递给 LLMReviewLayer。
            keyword_loader: 关键词加载可调用对象（保留接口，当前未使用）。
        """
        super().__init__(llm_client=llm_client, keyword_loader=keyword_loader)
        self._pre_selection = PreSelectionLayer()
        self._rule_engine = RuleEngineLayer()
        self._llm_review = LLMReviewLayer(llm_client=self._llm_client)

    # ======================================================================
    # _do_ 钩子实现
    # ======================================================================

    async def _do_pre_select(self, context: JudgmentContext) -> None:
        """执行前置行为类型判定。

        调用 PreSelectionLayer.judge() 检查 behavior_type_selection 中
        是否包含高危类型。命中高危时设置 context.skip_remaining=True
        以触发 @final run() 的短路逻辑。

        Args:
            context: Pipeline 运行时上下文。

        Raises:
            CrisisJudgmentError: 前置选择层内部不可恢复错误。
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
                original_error=exc,
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

    async def _do_rule_engine_match(self, context: JudgmentContext) -> None:
        """执行规则引擎关键词匹配。

        调用 RuleEngineLayer.judge() 完成 AC 自动机扫描 + 否定词过滤 +
        档案叠加规则。关键词词库加载失败时降级为 degraded 结果。
        命中 severe 时设置 context.skip_remaining=True 以跳过 LLM 复审。

        Args:
            context: Pipeline 运行时上下文。

        Raises:
            CrisisJudgmentError: 规则引擎内部不可恢复错误。
        """
        try:
            result: JudgmentLayerResult = await self._rule_engine.judge(
                context.request,
            )
        except KeywordDictLoadError:
            # 关键词词库加载失败 —— 降级，不阻断流程
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

        # 传播 manual_review_flag
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

    async def _do_llm_review(self, context: JudgmentContext) -> None:
        """执行 LLM 精调复审。

        调用 LLMReviewLayer.judge() 发送 DeepSeek API 请求进行精调复审。
        超时和解析失败均不抛异常（fail-open 策略），降级为无 LLM 判定结果。

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
            # fail-open: LLM 异常不阻断流程
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

    def _do_merge(self, context: JudgmentContext) -> CrisisJudgmentResult:
        """执行"宁升勿降"合并策略。

        按优先级合并各层判定结果：
          1. 前置选择 severe → 直接输出 severe
          2. LLM 超时 → 采用规则引擎等级
          3. 规则引擎 severe → 直接输出 severe
          4. 正常合并 → merge_matrix 二维查找表取最大值

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

        # 情况 1：前置选择命中 severe → 直接输出
        if pre_result and pre_result.level == CrisisLevel.SEVERE:
            return CrisisJudgmentResult(
                final_level=CrisisLevel.SEVERE,
                block_deep_response=True,
                manual_review_flag=False,
                review_confidence=None,
                judgment_sources=list(context.sources),
                degradation_note=context.degradation_note,
            )

        # 情况 2：LLM 超时 → 采用规则引擎结果
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
                judgment_sources=list(context.sources),
                degradation_note=context.degradation_note,
            )

        # 情况 3：规则引擎命中 severe → 直接输出
        if rule_result and rule_result.level == CrisisLevel.SEVERE:
            return CrisisJudgmentResult(
                final_level=CrisisLevel.SEVERE,
                block_deep_response=True,
                manual_review_flag=context.manual_review_flag,
                review_confidence=None,
                judgment_sources=list(context.sources),
                degradation_note=context.degradation_note,
            )

        # 情况 4：正常合并（使用 MERGE_MATRIX 二维查找表）
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
            judgment_sources=list(context.sources),
            degradation_note=context.degradation_note,
        )


# ============================================================================
# 内部辅助函数
# ============================================================================


def _max_level(a: CrisisLevel | None, b: CrisisLevel | None) -> CrisisLevel:
    """取两个等级中较高的一个（severe > moderate > mild）。

    merge_matrix.lookup() 回退策略：当二维查找表无法处理该组合时使用。

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
