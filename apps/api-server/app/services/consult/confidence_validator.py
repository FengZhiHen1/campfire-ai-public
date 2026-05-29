"""CSLT-05 置信度后校验 — 主校验入口。

对 CSLT-03 生成的应急方案执行两阶段串行校验流水线：
  阶段一：关键词安检（AC 自动机 O(n) 零 LLM 调用）
  阶段二：置信度复合评分（LLM 自评估 50% + 规则校验 50%）

8 步骤严格串行执行。LLM 自评估失败不重试，直接降级纯规则评分。
整体超时（3s）按安全兜底策略处理。

Usage:
    from starlette.background import BackgroundTasks
    output = await validate_confidence(input, background_tasks)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from py_logger import logger
from py_llm.client import LLMClient, LLMClientError
from py_schemas.consult.confidence import (
    ConfidenceValidationInput,
    ConfidenceValidationOutput,
    LLMAssessmentResult,
    ValidationVerdict,
)

from .keyword_scanner import KeywordScanner
from .rule_validator import compute_rule_score
from .ticket_trigger import trigger_ticket_with_retry

# ===========================================================================
# 常量
# ===========================================================================

_SERVICE: str = "consult.confidence"

# 置信度阈值常量（意图文档 AC-02 约束）
_CONFIDENCE_THRESHOLD: float = 0.7

# 校验总耗时上限（意图文档 AC-03 约束）
_VALIDATION_TIMEOUT_MS: float = 3000.0

# LLM 自评估超时秒数
_LLM_ASSESSMENT_TIMEOUT_S: float = 5.0

# 降级原因标签
_DEGRADATION_LLM_UNAVAILABLE: str = "llm_unavailable"
_DEGRADATION_TIMEOUT_FALLBACK: str = "timeout_fallback"

# LLM 自评估 System Prompt（模块级常量，非硬编码在函数中）
_LLM_ASSESSMENT_SYSTEM_PROMPT: str = (
    "你是一个应急方案质量评估专家。请评估以下应急方案的内容质量，"
    "返回 JSON 格式的评估结果。评估维度："
    "1) citation_adequacy=来源引用充分度（0-1）；"
    "2) logical_coherence=逻辑连贯性（0-1）；"
    "3) unsourced_claim_risk=无来源声明风险（0-1，越低越好）。"
    "仅返回 JSON，不要其他内容。"
)

# 默认追加免责提示（可通过环境变量 LOW_CONFIDENCE_DISCLAIMER 自定义）
_DEFAULT_WARNING_TEXT: str = (
    "\n\n---\n"
    "**重要提示**：本方案由 AI 辅助生成，置信度偏低。"
    "建议结合实际情况判断，必要时联系专业医生或行为分析师进行人工评估。"
    "本建议不构成医疗诊断。"
)

# 默认高危阻断替换文本（可通过环境变量 HIGH_RISK_BLOCK_MESSAGE 自定义）
_DEFAULT_BLOCK_MESSAGE: str = (
    "根据您描述的情况，系统检测到可能存在较高风险。"
    "出于安全考虑，AI 无法直接提供建议。"
    "请立即联系专业医生、行为分析师或拨打紧急求助电话。"
    "如情况紧急，请拨打 120 或前往最近医院的急诊科。"
)

# ticket 创建成功状态
_TICKET_STATUS_OPEN: str = "open"

# 工单上下文脱敏字段（仅保留行为描述和危机等级）
_TICKET_CONTEXT_FIELDS: tuple[str, str, str] = (
    "behavior_description",
    "crisis_level",
    "request_id",
)


# ===========================================================================
# 配置读取
# ===========================================================================


def _get_config(key: str, default: str) -> str:
    """读取配置项。

    从环境变量读取，若不存在返回默认值。
    环境变量通过 pydantic-settings 的 .env 文件加载。

    Args:
        key: 环境变量名。
        default: 默认值。

    Returns:
        str: 配置值。
    """
    return os.getenv(key, default)


# ===========================================================================
# 工单创建
# ===========================================================================


async def _persist_validation_result(
    request_id: str,
    confidence_score: float,
    verdict: str,
    validation_detail: dict[str, Any],
) -> None:
    """异步持久化校验结果到 consultations 表。

    通过 background_tasks 异步调用，失败不阻塞主流程。

    Args:
        request_id: 咨询追踪 ID。
        confidence_score: 置信度分数。
        verdict: 判定结论字符串。
        validation_detail: 校验详情字典（含 llm_score、rule_score、degradation_note 等）。
    """
    try:
        logger.info(
            service=_SERVICE,
            message="validation_persist_started",
            extra={
                "request_id": request_id,
                "confidence_score": confidence_score,
                "verdict": verdict,
            },
        )
        # ===== 占位实现 =====
        # 实际应通过 py-db 的 async_session 执行：
        #
        # async with async_session() as session:
        #     await session.execute(
        #         text(
        #             "UPDATE consultations SET "
        #             "confidence_score = :score, "
        #             "validation_detail = :detail::jsonb "
        #             "WHERE request_id = :request_id"
        #         ),
        #         {
        #             "score": confidence_score,
        #             "detail": json.dumps(validation_detail),
        #             "request_id": request_id,
        #         },
        #     )
        #     await session.commit()
        pass
    except Exception as exc:
        logger.warning(
            service=_SERVICE,
            message="validation_persist_failed",
            extra={
                "request_id": request_id,
                "error": str(exc),
            },
        )


# ===========================================================================
# 主校验流程
# ===========================================================================


async def validate_confidence(
    input: ConfidenceValidationInput,
    background_tasks: Any,
) -> ConfidenceValidationOutput:
    """对 CSLT-03 生成的应急方案进行置信度后校验。

    校验流程分两阶段 8 步骤：
    阶段一：关键词安检（检查用户原文和方案全文是否命中高危关键词）
    阶段二：置信度复合评分（LLM 自评估 50% + 规则校验 50%）

    Args:
        input: 校验输入，包含方案全文、来源清单、危机等级等。
        background_tasks: FastAPI BackgroundTasks 实例，用于异步持久化（持久化失败不影响主流程）。

    Returns:
        ConfidenceValidationOutput: 校验结果。

    Raises:
        ValidationError: 输入校验失败（Pydantic Schema 校验不通过）。

    Side Effects:
        - 通过 inline await 调用 POST /api/v1/tickets 创建工单（失败时设置 ticket_creation_failed=True）
        - 通过 background_tasks 异步写入 consultations 表
        - 记录结构化日志（含 request_id）

    Performance:
        目标 P95 <= 3s（含 LLM 自评估 + 规则校验）。
        LLM 自评估超时 5s 后降级纯规则评分，纯规则评分 < 100ms。

    Degradation:
        - LLM 自评估不可用 → 降级纯规则评分（degradation_note='llm_unavailable'）
        - LLM 自评估超时（5s）→ 降级纯规则评分
        - LLM 输出格式异常 → 降级纯规则评分
        - 整体超时（3s）且原本 PASS → 降级为 APPEND_WARNING（degradation_note='timeout_fallback'）
    """
    start_time: float = time.perf_counter()
    request_id: str = input.request_id

    logger.info(
        service=_SERVICE,
        message="confidence_validation_started",
        extra={
            "request_id": request_id,
            "crisis_level": input.crisis_level,
            "block_deep_response": input.block_deep_response,
            "high_risk_keyword_hit": input.high_risk_keyword_hit,
            "source_count": len(input.source_list),
            "plan_text_len": len(input.plan_text),
        },
    )

    # ==== 步骤 1：前置检查 ====

    if input.block_deep_response:
        logger.info(
            service=_SERVICE,
            message="block_deep_response_active",
            extra={"request_id": request_id},
        )
        return ConfidenceValidationOutput(
            confidence_score=0.0,
            verdict=ValidationVerdict.PASS,
            modified_plan_text=input.plan_text,
            ticket_triggered=False,
            ticket_creation_failed=False,
            degradation_note=None,
            validation_time_ms=0.0,
        )

    # 初始化状态变量
    degradation_note: str | None = None
    llm_score: float | None = None
    rule_score: float = 0.0
    confidence_score: float = 0.0
    verdict: ValidationVerdict
    modified_plan_text: str
    ticket_triggered: bool = False
    ticket_creation_failed: bool = False
    ticket_priority: str = "normal"

    # ==== 步骤 2：高危关键词检测 ====

    scanner: KeywordScanner = await KeywordScanner.get_instance()
    keyword_hit: bool = False

    # 检查 CSLT-01 标记的高危关键词命中
    if input.high_risk_keyword_hit:
        logger.warning(
            service=_SERVICE,
            message="keyword_hit_from_cslt01",
            extra={"request_id": request_id},
        )
        keyword_hit = True
    else:
        # 独立扫描方案全文
        # 注意：对方案正文的关键词扫描不应用否定词过滤。
        # CSLT-01 的否定词过滤用于分析用户原文（如"我不想自伤"），
        # 但若 LLM 生成的方案正文包含高危关键词，无论否定语境如何，
        # 均属不安全输出，必须进入 FORCE_BLOCK 路径。
        hits = scanner.scan_keywords(input.plan_text)
        if hits:
            logger.warning(
                service=_SERVICE,
                message="keyword_hit_in_plan_text",
                extra={
                    "request_id": request_id,
                    "hit_keywords": [h["keyword"] for h in hits],
                    "hit_count": len(hits),
                },
            )
            keyword_hit = True
        else:
            logger.info(
                service=_SERVICE,
                message="keyword_scan_clean",
                extra={"request_id": request_id},
            )

    # 命中高危词 → FORCE_BLOCK
    if keyword_hit:
        block_message: str = _get_config(
            "HIGH_RISK_BLOCK_MESSAGE", _DEFAULT_BLOCK_MESSAGE
        )
        ticket_priority = "critical"
        ticket_triggered = True

        # 工单创建（inline await 以捕获 RetryError 并设置 ticket_creation_failed）
        try:
            await trigger_ticket_with_retry(
                request_id=request_id,
                behavior_description=input.behavior_description,
                crisis_level=input.crisis_level,
                priority=ticket_priority,
            )
        except Exception as exc:
            logger.error(
                service=_SERVICE,
                message="ticket_creation_exhausted",
                extra={
                    "request_id": request_id,
                    "last_error": str(exc),
                },
            )
            ticket_creation_failed = True

        validation_time_ms: float = (time.perf_counter() - start_time) * 1000

        logger.info(
            service=_SERVICE,
            message="confidence_validation_complete",
            extra={
                "request_id": request_id,
                "verdict": ValidationVerdict.FORCE_BLOCK.value,
                "score": 0.0,
                "elapsed_ms": validation_time_ms,
                "degraded": False,
            },
        )

        return ConfidenceValidationOutput(
            confidence_score=0.0,
            verdict=ValidationVerdict.FORCE_BLOCK,
            modified_plan_text=block_message,
            ticket_triggered=ticket_triggered,
            ticket_creation_failed=ticket_creation_failed,
            degradation_note=None,
            validation_time_ms=validation_time_ms,
        )

    # ==== 步骤 3：LLM 自评估调用 ====

    try:
        llm_client = LLMClient()
        assessment_messages: list[dict[str, str]] = [
            {"role": "system", "content": _LLM_ASSESSMENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"方案全文：\n{input.plan_text}\n\n"
                    f"患者行为描述：{input.behavior_description}\n"
                    f"来源引用清单：{json.dumps(input.source_list, ensure_ascii=False)}"
                ),
            },
        ]

        response_text: str = await llm_client.async_chat(
            messages=assessment_messages,
            timeout=_LLM_ASSESSMENT_TIMEOUT_S,
            response_format={"type": "json_object"},
        )

        # 解析 LLM 返回的 JSON
        assessment_result: LLMAssessmentResult = (
            LLMAssessmentResult.model_validate_json(response_text)
        )

        # 计算 LLM 自评估得分
        llm_score = (
            assessment_result.citation_adequacy
            + assessment_result.logical_coherence
            + (1.0 - assessment_result.unsourced_claim_risk)
        ) / 3.0

        logger.info(
            service=_SERVICE,
            message="llm_assessment_success",
            extra={
                "request_id": request_id,
                "llm_score": round(llm_score, 4),
                "citation_adequacy": assessment_result.citation_adequacy,
                "logical_coherence": assessment_result.logical_coherence,
                "unsourced_claim_risk": assessment_result.unsourced_claim_risk,
            },
        )

    except LLMClientError as exc:
        logger.warning(
            service=_SERVICE,
            message="llm_assessment_unavailable",
            extra={
                "request_id": request_id,
                "error": str(exc),
            },
        )
        degradation_note = _DEGRADATION_LLM_UNAVAILABLE

    except asyncio.TimeoutError:
        logger.warning(
            service=_SERVICE,
            message="llm_assessment_timeout",
            extra={"request_id": request_id},
        )
        degradation_note = _DEGRADATION_LLM_UNAVAILABLE

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            service=_SERVICE,
            message="llm_assessment_parse_failed",
            extra={
                "request_id": request_id,
                "error": str(exc),
            },
        )
        degradation_note = _DEGRADATION_LLM_UNAVAILABLE

    except Exception as exc:
        logger.warning(
            service=_SERVICE,
            message="llm_assessment_unexpected_error",
            extra={
                "request_id": request_id,
                "error": str(exc),
            },
        )
        degradation_note = _DEGRADATION_LLM_UNAVAILABLE

    # ==== 步骤 4/5：规则校验与复合评分 ====

    rule_score = compute_rule_score(input.plan_text, input.source_list)

    logger.info(
        service=_SERVICE,
        message="rule_score_computed",
        extra={
            "request_id": request_id,
            "rule_score": round(rule_score, 4),
        },
    )

    if degradation_note == _DEGRADATION_LLM_UNAVAILABLE:
        # 步骤 4：降级纯规则评分
        confidence_score = rule_score
    else:
        # 步骤 5：复合评分
        assert llm_score is not None, "llm_score must be set when LLM assessment succeeds"

        llm_weight: float = float(
            _get_config("CONFIDENCE_LLM_WEIGHT", "0.5")
        )
        rule_weight: float = float(
            _get_config("CONFIDENCE_RULE_WEIGHT", "0.5")
        )

        if llm_weight == 0.0 and rule_weight == 0.0:
            logger.warning(
                service=_SERVICE,
                message="config_fallback",
                extra={"key": "CONFIDENCE_LLM_WEIGHT/CONFIDENCE_RULE_WEIGHT"},
            )
            llm_weight = 0.5
            rule_weight = 0.5

        confidence_score = llm_score * llm_weight + rule_score * rule_weight

    # Clamp to [0.0, 1.0]
    confidence_score = max(0.0, min(1.0, confidence_score))
    confidence_score = round(confidence_score, 4)

    # ==== 步骤 7：判定分支 ====

    if confidence_score >= _CONFIDENCE_THRESHOLD:
        verdict = ValidationVerdict.PASS
        modified_plan_text = input.plan_text
        ticket_triggered = False
    else:
        # 追加警告提示
        warning_text: str = _get_config(
            "LOW_CONFIDENCE_DISCLAIMER", _DEFAULT_WARNING_TEXT
        )
        modified_plan_text = input.plan_text + warning_text
        verdict = ValidationVerdict.APPEND_WARNING
        ticket_triggered = True

    # 工单创建（置信度不足时，inline await 以捕获失败状态）
    if ticket_triggered:
        try:
            await trigger_ticket_with_retry(
                request_id=request_id,
                behavior_description=input.behavior_description,
                crisis_level=input.crisis_level,
                priority=ticket_priority,
            )
        except Exception as exc:
            logger.error(
                service=_SERVICE,
                message="ticket_creation_exhausted",
                extra={
                    "request_id": request_id,
                    "last_error": str(exc),
                },
            )
            ticket_creation_failed = True

    # ==== 步骤 8：超时安全检查与持久化 ====

    validation_time_ms = (time.perf_counter() - start_time) * 1000

    # 超时安全兜底：若原本 PASS 但总耗时 > 3s，降级为 APPEND_WARNING
    if validation_time_ms > _VALIDATION_TIMEOUT_MS and verdict == ValidationVerdict.PASS:
        logger.warning(
            service=_SERVICE,
            message="validation_timeout_fallback",
            extra={
                "request_id": request_id,
                "elapsed_ms": validation_time_ms,
                "original_verdict": "PASS",
            },
        )
        verdict = ValidationVerdict.APPEND_WARNING
        warning_text = _get_config(
            "LOW_CONFIDENCE_DISCLAIMER", _DEFAULT_WARNING_TEXT
        )
        modified_plan_text = input.plan_text + warning_text
        ticket_triggered = True
        degradation_note = _DEGRADATION_TIMEOUT_FALLBACK

        try:
            await trigger_ticket_with_retry(
                request_id=request_id,
                behavior_description=input.behavior_description,
                crisis_level=input.crisis_level,
                priority=ticket_priority,
            )
        except Exception as exc:
            logger.error(
                service=_SERVICE,
                message="ticket_creation_exhausted",
                extra={
                    "request_id": request_id,
                    "last_error": str(exc),
                },
            )
            ticket_creation_failed = True

    # 异步持久化
    validation_detail: dict[str, Any] = {
        "llm_score": round(llm_score, 4) if llm_score is not None else None,
        "rule_score": round(rule_score, 4),
        "degradation_note": degradation_note,
        "verdict": verdict.value,
        "source_count": len(input.source_list),
        "keyword_hit": keyword_hit,
    }
    background_tasks.add_task(
        _persist_validation_result,
        request_id=request_id,
        confidence_score=confidence_score,
        verdict=verdict.value,
        validation_detail=validation_detail,
    )

    logger.info(
        service=_SERVICE,
        message="confidence_validation_complete",
        extra={
            "request_id": request_id,
            "verdict": verdict.value,
            "score": confidence_score,
            "elapsed_ms": validation_time_ms,
            "degraded": degradation_note is not None,
        },
    )

    return ConfidenceValidationOutput(
        confidence_score=confidence_score,
        verdict=verdict,
        modified_plan_text=modified_plan_text,
        ticket_triggered=ticket_triggered,
        ticket_creation_failed=ticket_creation_failed,
        degradation_note=degradation_note,
        validation_time_ms=validation_time_ms,
    )


__all__ = [
    "validate_confidence",
]
