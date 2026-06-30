"""CSLT-01 危机分级判定管线实现。

继承 CrisisJudgmentPipeline 契约 ABC，实现两层判定：
  - PreSelectionLayer（前置行为类型判定）
  - RuleEngineLayer（关键词 + 否定词过滤 + 档案叠加规则）

LLMReviewLayer 已从默认阻塞链路中移除，以降低咨询首字节延迟。
如需后台审计，可单独调用 LLMReviewLayer，但不再影响当前回复。
"""

from __future__ import annotations

from typing import Any

from py_logger import logger

from .crisis_contract import CrisisJudgmentPipeline
from .enums import CrisisLevel
from .exceptions import CrisisJudgmentError, KeywordDictLoadError
from .merge_matrix import merge
from .models import (
    CrisisJudgmentResult,
    JudgmentContext,
    JudgmentLayerResult,
)
from .pre_selection_layer import PreSelectionLayer
from .rule_engine_layer import RuleEngineLayer


class CrisisJudgmentPipelineImpl(CrisisJudgmentPipeline):
    """危机分级判定管线实现。

    继承 CrisisJudgmentPipeline 契约 ABC，实现 _do_ 钩子。
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

        Args:
            llm_client: 保留参数，当前不再使用（LLMReviewLayer 已从阻塞链路移除）。
            keyword_loader: 关键词加载可调用对象（保留接口，当前未使用）。
        """
        super().__init__(llm_client=llm_client, keyword_loader=keyword_loader)
        self._pre_selection = PreSelectionLayer()
        self._rule_engine = RuleEngineLayer()

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
        命中 severe 时设置 context.skip_remaining=True。

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
        if result.details.get("manual_review_recommended") or result.details.get("profile_overlap_triggered"):
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

    def _do_merge(self, context: JudgmentContext) -> CrisisJudgmentResult:
        """合并两层判定结果。

        任意一层判 severe 即为 severe；否则取 RuleEngine 非空等级；
        都未命中则返回 mild。

        Args:
            context: Pipeline 运行时上下文。

        Returns:
            合并后的最终判定结果。
        """
        merged_level = merge(context)

        return CrisisJudgmentResult(
            final_level=merged_level,
            block_deep_response=(merged_level == CrisisLevel.SEVERE),
            manual_review_flag=context.manual_review_flag,
            review_confidence=None,
            judgment_sources=list(context.sources),
            degradation_note=context.degradation_note,
        )
