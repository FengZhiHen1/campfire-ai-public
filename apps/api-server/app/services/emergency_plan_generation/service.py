"""CSLT-03 应急方案生成 — generate_emergency_plan() 公共服务入口。

对外暴露 generate_emergency_plan() 异步函数，作为模块的唯一公共接口。
CSLT-08（咨询编排逻辑）通过此接口触发应急方案生成流程。

执行流程：
1. 输入校验 — Pydantic 自动校验（失败 → GenerationInputError）
2. 阻断检查 — block_deep_response=True → 直接返回安全提示文本
3. Prompt 构建 — 组装 System Prompt + User Message
4. LLM 流式调用 — 调用 DeepSeek API 生成文本
5. 流式收尾 — 引用反查、免责声明检查、结果组装
6. 指标记录 — Prometheus 埋点 + 结构化日志

Usage:
    from app.services.emergency_plan_generation import generate_emergency_plan

    result = await generate_emergency_plan(input_data)
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError
from py_logger import logger

from ._metrics import GENERATION_DURATION, GENERATION_REQUESTS, GENERATION_TTFT
from .blocked_outputs import BLOCKED_PROMPT_TEMPLATES, DEFAULT_BLOCKED_TEXT, DISCLAIMER_TEXT
from .enums import BlockVariant, GenerationStatus
from .exceptions import GenerationInputError, GenerationTimeoutError, LLMUnavailableError
from .models import EmergencyPlanInput, GenerationResult
from .prompt_builder import PromptBuilder
from .streaming import (
    _REFERENCE_TAG_PATTERN,
    _SECTION_HEADER_PATTERN,
    _SOURCE_LINE_PATTERN,
    build_generation_result,
    stream_generate,
)


async def generate_emergency_plan(
    input_data: EmergencyPlanInput,
    config: Any | None = None,
) -> GenerationResult:
    """接收应急咨询的上游结果，组装 Prompt 并调用大模型生成四段式应急方案。

    阻断场景下（crisis_result.block_deep_response=True）完全跳过 LLM 调用，
    直接返回硬编码安全提示文本。

    Args:
        input_data: 完整的生成输入，由 CSLT-08 编排层组装后传入。
                    包含 CSLT-01 的危机判定结果、CSLT-02 的检索结果、患者档案摘要和行为描述。
        config: 可选配置注入（用于测试时注入 mock 配置）。
                若为 None 则使用默认配置值。
                支持字段：DEEPSEEK_MODEL, GENERATION_TEMPERATURE,
                        GENERATION_MAX_TOKENS, GENERATION_TIMEOUT_S。

    Returns:
        GenerationResult: 生成结果，包含完整文本、来源引用清单、免责声明、耗时、状态等。

    Raises:
        GenerationInputError: Pydantic 输入校验失败（必填字段缺失、类型错误等）。
        LLMUnavailableError: DeepSeek API 不可用或返回非 200（不重试）。
        GenerationTimeoutError: 全流程超时 15s 且无任何文本产出。

    Side Effects:
        - 记录生成全流程的结构化日志（INFO/WARNING/ERROR 级别）
        - 暴露 Prometheus 指标：请求计数、生成耗时 Histogram、TTFT Histogram
        - 不持久化任何生成结果——持久化由调用方（CSLT-06）负责

    Idempotency:
        本函数为无状态生成，不维护跨调用状态，不检查幂等 Key。
        同一输入参数的重复调用产生独立的全新生成结果。

    Thread Safety:
        本函数为 async 协程，内部无共享可变状态。线程安全。
    """
    t_start: float = time.monotonic()
    request_id: str = input_data.request_id

    log_extra: dict[str, Any] = {
        "request_id": request_id,
        "trace_id": request_id,
    }

    logger.info(
        service="emergency_plan_generation",
        message="Starting emergency plan generation",
        op_type="generate",
        extra={
            **log_extra,
            "block_deep_response": input_data.crisis_result.block_deep_response,
            "final_level": (
                input_data.crisis_result.final_level.value
                if hasattr(input_data.crisis_result.final_level, "value")
                else str(input_data.crisis_result.final_level)
            ),
            "slices_count": len(input_data.search_result.results),
            "behavior_length": len(input_data.behavior_description),
        },
    )

    # ==========================================================================
    # 步骤 1：输入校验
    # Pydantic 模型在构造时自动校验。若外部未校验，此处兜底校验。
    # ==========================================================================
    # EmergencyPlanInput 的 Pydantic 校验在上游调用时已完成。
    # 若直接传入 dict，此处构造会触发校验。
    if not isinstance(input_data, EmergencyPlanInput):
        try:
            input_data = EmergencyPlanInput(**input_data)  # type: ignore[arg-type]
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(loc) for loc in first["loc"])
            logger.warning(
                service="emergency_plan_generation",
                message="Generation input validation failed",
                op_type="input_validation",
                extra={**log_extra, "field": field, "msg": first["msg"]},
            )
            raise GenerationInputError(
                detail={"field": field, "msg": first["msg"], "received": str(first.get("input", ""))},
                message="输入数据校验失败",
                original_error=exc,
            ) from exc
        except Exception as exc:
            logger.warning(
                service="emergency_plan_generation",
                message="Generation input validation failed",
                op_type="input_validation",
                extra={**log_extra, "error": str(exc)},
            )
            raise GenerationInputError(
                detail={"field": "input_data", "msg": str(exc)},
                message="输入数据校验失败",
                original_error=exc,
            ) from exc

    # ==========================================================================
    # 步骤 2：阻断检查与短路
    # crisis_result.block_deep_response=True → 跳过 LLM，直接返回安全提示
    # ==========================================================================
    if input_data.crisis_result.block_deep_response:
        elapsed_ms: float = (time.monotonic() - t_start) * 1000

        # 确定阻断变体
        block_variant = input_data.block_variant or _infer_block_variant(input_data)

        # 获取对应安全提示文本
        if block_variant and block_variant in BLOCKED_PROMPT_TEMPLATES:
            blocked_text: str = BLOCKED_PROMPT_TEMPLATES[block_variant]
        else:
            # 映射失败 → 使用默认通用文本，记录 WARNING
            blocked_text = DEFAULT_BLOCKED_TEXT
            logger.warning(
                service="emergency_plan_generation",
                message="Block variant mapping failed, using default blocked text",
                op_type="block_fallback",
                extra={
                    **log_extra,
                    "block_variant": str(block_variant) if block_variant else "null",
                    "elapsed_ms": elapsed_ms,
                },
            )

        result = GenerationResult(
            text="",
            source_list=[],
            disclaimer=blocked_text,  # blocked_text 替代免责声明作为安全提示
            generation_time_ms=elapsed_ms,
            is_partial=False,
            referenced_slice_ids=[],
            finish_reason=GenerationStatus.BLOCKED,
            ttft_ms=0.0,
        )

        logger.warning(
            service="emergency_plan_generation",
            message="Emergency plan blocked — skip LLM call",
            op_type="blocked",
            extra={
                **log_extra,
                "block_variant": str(block_variant) if block_variant else "default",
                "elapsed_ms": elapsed_ms,
            },
        )

        GENERATION_REQUESTS.labels(status="blocked").inc()
        return result

    # ==========================================================================
    # 步骤 3：Prompt 构建
    # ==========================================================================
    builder = PromptBuilder()
    messages, ctx = builder.build(input_data)

    logger.info(
        service="emergency_plan_generation",
        message="Prompt built successfully",
        op_type="prompt_build",
        extra={
            **log_extra,
            "has_cases": ctx.has_cases,
            "slices_precount": len(ctx.prenumbered_slices),
            "system_prompt_len": len(messages[0]["content"]) if messages else 0,
            "user_message_len": len(messages[1]["content"]) if len(messages) > 1 else 0,
        },
    )

    # ==========================================================================
    # 步骤 4-5：LLM 流式调用 + 流式 chunk 生产
    # TTFT 在 service 层追踪（stream_generate 不负责 TTFT）
    # ==========================================================================
    accumulated_text: str = ""
    ttft_ms: float | None = None
    finish_reason: GenerationStatus = GenerationStatus.COMPLETE

    try:
        # 收集所有流式 chunk
        async for chunk in stream_generate(
            input_data=input_data,
            messages=messages,
            prenumbered_slices=ctx.prenumbered_slices,
            config=config,
        ):
            if chunk.is_final:
                # 最后一个 chunk 的 finish_reason 指示完成状态
                if chunk.finish_reason == "timeout":
                    # 检查 accumulated_text 是否包含完整段落来判断 PARTIAL/TIMEOUT
                    if accumulated_text and _SECTION_HEADER_PATTERN.search(accumulated_text):
                        finish_reason = GenerationStatus.PARTIAL
                    else:
                        finish_reason = GenerationStatus.TIMEOUT
                # 不 break —— 让迭代正常结束，异常才能从 stream_generate() 的
                # finally 块中正常传播，否则 break 会触发 aclose() 吞没异常
            else:
                accumulated_text += chunk.text

                # 追踪 TTFT（首个非空 chunk）
                if ttft_ms is None and accumulated_text:
                    ttft_ms = (time.monotonic() - t_start) * 1000

    except GenerationTimeoutError:
        # 完全超时（无任何有效文本）
        finish_reason = GenerationStatus.TIMEOUT
        logger.error(
            service="emergency_plan_generation",
            message="Generation completely timed out",
            op_type="generation_timeout",
            extra={**log_extra},
        )
        GENERATION_REQUESTS.labels(status="timeout").inc()
        raise

    except LLMUnavailableError:
        # 已在 streaming 层包装，直接传播
        logger.critical(
            service="emergency_plan_generation",
            message="LLM API unavailable",
            op_type="llm_error",
            extra={**log_extra},
        )
        GENERATION_REQUESTS.labels(status="error").inc()
        raise

    except Exception as exc:
        # 未预期的异常 → 统一包装为 LLMUnavailableError
        logger.critical(
            service="emergency_plan_generation",
            message="Unexpected error during generation",
            op_type="unexpected_error",
            extra={**log_extra, "error": str(exc)},
        )
        GENERATION_REQUESTS.labels(status="error").inc()
        raise LLMUnavailableError(
            detail="LLM 生成服务暂时不可用，请稍后重试",
            original_error=exc,
        ) from exc

    # ==========================================================================
    # 步骤 6：流式完成收尾
    # ==========================================================================
    is_partial: bool = finish_reason == GenerationStatus.PARTIAL

    generation_result = build_generation_result(
        input_data=input_data,
        accumulated_text=accumulated_text,
        ttft_ms=ttft_ms,
        t_start=t_start,
        prenumbered_slices=ctx.prenumbered_slices,
        is_partial=is_partial,
        finish_reason=finish_reason,
    )

    # ==========================================================================
    # 步骤 7：指标记录与日志
    # ==========================================================================
    elapsed_ms = generation_result.generation_time_ms

    # Prometheus 指标
    status_label: str = generation_result.finish_reason.value.lower()
    GENERATION_REQUESTS.labels(status=status_label).inc()
    GENERATION_DURATION.observe(elapsed_ms / 1000.0)
    if ttft_ms is not None:
        GENERATION_TTFT.observe(ttft_ms / 1000.0)

    # 结构化日志
    logger.info(
        service="emergency_plan_generation",
        message="Generation completed",
        op_type="generation_complete",
        extra={
            **log_extra,
            "finish_reason": generation_result.finish_reason.value,
            "elapsed_ms": elapsed_ms,
            "ttft_ms": generation_result.ttft_ms,
            "slices_count": len(ctx.prenumbered_slices),
            "referenced_count": len(generation_result.referenced_slice_ids),
            "text_length": len(generation_result.text),
            "is_partial": generation_result.is_partial,
        },
    )

    return generation_result


# ============================================================================
# 辅助函数
# ============================================================================


def _infer_block_variant(input_data: EmergencyPlanInput) -> BlockVariant | None:
    """从 crisis_result.judgment_sources 中推断阻断变体。

    遍历判断源，查找 PreSelectionLayer 输出的 checked_types，
    匹配首个高危行为类型作为 BlockVariant。

    Args:
        input_data: EmergencyPlanInput 实例。

    Returns:
        推断出的 BlockVariant，若无法推断则返回 None。
    """
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
