"""CSLT-03 应急方案生成 — service。

模块: app.modules.consultation.plan_generation.service
职责: 应急方案生成实现。PlanGeneratorImpl 继承 BasePlanGenerator ABC，
      @final generate_emergency_plan 强制执行 前置校验→阻断检查→Prompt构建→LLM流式调用→结果组装 流程。
      模块级便捷函数委托给单例实例。
数据来源:
  - py_llm.LLMClient: MUST — DeepSeek API 流式调用
  - .prompt_builder.PromptBuilder: MUST — System/User Prompt 组装
  - .streaming.stream_generate: MUST — 流式生成器
边界:
  - 依赖: py_llm, py_logger, py_config, 子模块 streaming/prompt_builder/models
  - 被依赖: consult_service.py（编排层）
禁止行为:
  - 禁止在阻断场景下仍调用 LLM
  - 禁止在 _do_ 钩子中调用 super()
"""

from __future__ import annotations

import time
from typing import Any

from py_logger import logger
from pydantic import ValidationError

from ._metrics import GENERATION_DURATION, GENERATION_REQUESTS, GENERATION_TTFT
from .blocked_outputs import BLOCKED_PROMPT_TEMPLATES, DEFAULT_BLOCKED_TEXT
from .enums import BlockVariant, GenerationStatus
from .exceptions import (
    GenerationInputError,
    GenerationTimeoutError,
    LLMUnavailableError,
)
from .generation_contract import BasePlanGenerator
from .models import EmergencyPlanInput, GenerationResult
from .prompt_builder import PromptBuilder
from .streaming import build_generation_result, stream_generate

_MIN_JSON_CONTENT_LENGTH: int = 100


# ============================================================================
# PlanGeneratorImpl — 实现 BasePlanGenerator ABC
# ============================================================================


class PlanGeneratorImpl(BasePlanGenerator):
    """应急方案生成实现。继承 BasePlanGenerator ABC，仅覆写 _do_ 钩子。"""

    def _do_build_prompt(
        self,
        input_data: Any,
    ) -> tuple[list[dict[str, str]], Any]:
        builder = PromptBuilder()
        return builder.build(input_data)

    async def _do_stream_generate(
        self,
        input_data: Any,
        messages: list[dict[str, str]],
        ctx: Any,
        config: Any | None,
    ) -> tuple[str, float | None, Any]:
        t_start: float = time.monotonic()
        accumulated_text: str = ""
        ttft_ms: float | None = None
        finish_reason: GenerationStatus = GenerationStatus.COMPLETE
        request_id: str = input_data.request_id

        try:
            async for chunk in stream_generate(
                input_data=input_data,
                messages=messages,
                prenumbered_slices=ctx.prenumbered_slices,
                config=config,
            ):
                if chunk.is_final:
                    if chunk.finish_reason == "timeout":
                        if accumulated_text and len(accumulated_text) >= _MIN_JSON_CONTENT_LENGTH:
                            finish_reason = GenerationStatus.PARTIAL
                        else:
                            finish_reason = GenerationStatus.TIMEOUT
                else:
                    accumulated_text += chunk.text
                    if ttft_ms is None and accumulated_text:
                        ttft_ms = (time.monotonic() - t_start) * 1000

        except GenerationTimeoutError:
            finish_reason = GenerationStatus.TIMEOUT
            logger.error(
                service="emergency_plan_generation",
                message="Generation completely timed out",
                op_type="generation_timeout",
                extra={"request_id": request_id},
            )
            GENERATION_REQUESTS.labels(status="timeout").inc()
            raise

        except LLMUnavailableError:
            logger.critical(
                service="emergency_plan_generation",
                message="LLM API unavailable",
                op_type="llm_error",
                extra={"request_id": request_id},
            )
            GENERATION_REQUESTS.labels(status="error").inc()
            raise

        except Exception as exc:
            logger.critical(
                service="emergency_plan_generation",
                message="Unexpected error during generation",
                op_type="unexpected_error",
                extra={"request_id": request_id, "error": str(exc)},
            )
            GENERATION_REQUESTS.labels(status="error").inc()
            raise LLMUnavailableError(
                detail="LLM 生成服务暂时不可用，请稍后重试",
                original_error=exc,
            ) from exc

        return accumulated_text, ttft_ms, finish_reason

    def _do_build_blocked_result(self, input_data: Any) -> Any:
        block_variant = input_data.block_variant or _infer_block_variant(input_data)

        if block_variant and block_variant in BLOCKED_PROMPT_TEMPLATES:
            blocked_text: str = BLOCKED_PROMPT_TEMPLATES[block_variant]
        else:
            blocked_text = DEFAULT_BLOCKED_TEXT
            logger.warning(
                service="emergency_plan_generation",
                message="Block variant mapping failed, using default blocked text",
                op_type="block_fallback",
                extra={"request_id": input_data.request_id},
            )

        logger.warning(
            service="emergency_plan_generation",
            message="Emergency plan blocked — skip LLM call",
            op_type="blocked",
            extra={"request_id": input_data.request_id},
        )
        GENERATION_REQUESTS.labels(status="blocked").inc()

        return GenerationResult(
            text="",
            source_list=[],
            disclaimer=blocked_text,
            generation_time_ms=0.0,
            is_partial=False,
            referenced_slice_ids=[],
            finish_reason=GenerationStatus.BLOCKED,
            ttft_ms=0.0,
        )

    def _do_build_result(
        self,
        input_data: Any,
        accumulated_text: str,
        ttft_ms: float | None,
        finish_reason: Any,
        ctx: Any,
    ) -> Any:
        t_start = time.monotonic()
        is_partial = finish_reason == GenerationStatus.PARTIAL

        result = build_generation_result(
            input_data=input_data,
            accumulated_text=accumulated_text,
            ttft_ms=ttft_ms,
            t_start=t_start,
            prenumbered_slices=ctx.prenumbered_slices,
            is_partial=is_partial,
            finish_reason=finish_reason,
        )

        # Prometheus 指标
        status_label: str = result.finish_reason.value.lower()
        GENERATION_REQUESTS.labels(status=status_label).inc()
        GENERATION_DURATION.observe(result.generation_time_ms / 1000.0)
        if ttft_ms is not None:
            GENERATION_TTFT.observe(ttft_ms / 1000.0)

        # 结构化日志
        logger.info(
            service="emergency_plan_generation",
            message="Generation completed",
            op_type="generation_complete",
            extra={
                "request_id": input_data.request_id,
                "finish_reason": result.finish_reason.value,
                "elapsed_ms": result.generation_time_ms,
                "ttft_ms": result.ttft_ms,
                "slices_count": len(ctx.prenumbered_slices),
                "referenced_count": len(result.referenced_slice_ids),
                "text_length": len(result.text),
                "is_partial": result.is_partial,
            },
        )

        return result


# ============================================================================
# 模块级单例 + 便捷函数
# ============================================================================

_generator = PlanGeneratorImpl()


async def generate_emergency_plan(
    input_data: EmergencyPlanInput,
    config: Any | None = None,
) -> GenerationResult:
    """应急方案生成（委托给 PlanGeneratorImpl ABC 单例）。

    阻断场景下（crisis_result.block_deep_response=True）完全跳过 LLM 调用。
    """
    # 处理 dict 输入（上游可能传入原始 dict）
    if not isinstance(input_data, EmergencyPlanInput):
        try:
            input_data = EmergencyPlanInput(**input_data)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(loc) for loc in first["loc"])
            raise GenerationInputError(
                detail={
                    "field": field,
                    "msg": first["msg"],
                    "received": str(first.get("input", "")),
                },
                message="输入数据校验失败",
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise GenerationInputError(
                detail={"field": "input_data", "msg": str(exc)},
                message="输入数据校验失败",
                original_error=exc,
            ) from exc

    result = await _generator.generate_emergency_plan(
        input_data=input_data,
        config=config,
    )
    return result  # type: ignore[no-any-return]  # 契约使用 Any 跨域类型


# ============================================================================
# 辅助函数
# ============================================================================


def _infer_block_variant(input_data: EmergencyPlanInput) -> BlockVariant | None:
    """从 crisis_result.judgment_sources 中推断阻断变体。"""
    for source in input_data.crisis_result.judgment_sources:
        if source.layer_name == "PreSelectionLayer":
            details = source.details or {}
            checked_types: list[str] = details.get("checked_types", [])
            for t in checked_types:
                try:
                    return BlockVariant(t)
                except ValueError:
                    continue
            break
    return None


__all__ = [
    "PlanGeneratorImpl",
    "generate_emergency_plan",
]
