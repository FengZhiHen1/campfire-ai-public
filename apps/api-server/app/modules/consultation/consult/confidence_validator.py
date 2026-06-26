"""CSLT-05 置信度后校验 — confidence_validator。

模块: app.modules.consultation.consult.confidence_validator
职责: 置信度后校验实现。ConfidenceValidatorImpl 继承 BaseConfidenceValidator ABC，
      执行关键词安检 → LLM 自评估 → 规则校验 两阶段流水线。
      模块级便捷函数 validate_confidence 委托给单例实例。
数据来源:
  - py_llm.LLMClient: SHOULD — LLM 自评估（不可用时降级纯规则评分）
  - .keyword_scanner.KeywordScanner: SHOULD — AC 自动机关键词扫描
边界:
  - 依赖: py_llm, py_logger, py_schemas, 子模块 keyword_scanner/rule_validator/ticket_trigger
  - 被依赖: consult_service.py（编排层）
禁止行为:
  - 禁止在 LLM 自评估失败时阻断主流程（必须降级纯规则评分）
  - 禁止在关键词扫描中对方案正文应用否定词过滤
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

from .validation_contract import BaseConfidenceValidator, DegradationNote
from .keyword_scanner import KeywordScanner
from .rule_validator import compute_rule_score
from .ticket_trigger import trigger_ticket_with_retry

# ============================================================================
# 常量
# ============================================================================

_SERVICE: str = "consult.confidence"
_CONFIDENCE_THRESHOLD: float = 0.7
_VALIDATION_TIMEOUT_MS: float = 3000.0
_LLM_ASSESSMENT_TIMEOUT_S: float = 5.0
_DEGRADATION_LLM_UNAVAILABLE: DegradationNote = "llm_unavailable"
_DEGRADATION_TIMEOUT_FALLBACK: DegradationNote = "timeout_fallback"

_LLM_ASSESSMENT_SYSTEM_PROMPT: str = (
    "你是一个应急方案质量评估专家。请评估以下应急方案的内容质量，"
    "返回 JSON 格式的评估结果。评估维度："
    "1) citation_adequacy=来源引用充分度（0-1）；"
    "2) logical_coherence=逻辑连贯性（0-1）；"
    "3) unsourced_claim_risk=无来源声明风险（0-1，越低越好）。"
    "仅返回 JSON，不要其他内容。"
)

_DEFAULT_WARNING_TEXT: str = (
    "\n\n---\n"
    "**重要提示**：本方案由 AI 辅助生成，置信度偏低。"
    "建议结合实际情况判断，必要时联系专业医生或行为分析师进行人工评估。"
    "本建议不构成医疗诊断。"
)

_DEFAULT_BLOCK_MESSAGE: str = (
    "根据您描述的情况，系统检测到可能存在较高风险。"
    "出于安全考虑，AI 无法直接提供建议。"
    "请立即联系专业医生、行为分析师或拨打紧急求助电话。"
    "如情况紧急，请拨打 120 或前往最近医院的急诊科。"
)


def _get_config(key: str, default: str) -> str:
    return os.getenv(key, default)


# ============================================================================
# ConfidenceValidatorImpl — 实现 BaseConfidenceValidator ABC
# ============================================================================


class ConfidenceValidatorImpl(BaseConfidenceValidator):
    """置信度后校验实现。继承 BaseConfidenceValidator ABC，仅覆写 _do_ 钩子。"""

    async def _do_scan_keywords(self, input: Any) -> bool:
        if input.high_risk_keyword_hit:
            logger.warning(
                service=_SERVICE,
                message="keyword_hit_from_cslt01",
                extra={"request_id": input.request_id},
            )
            return True

        scanner: KeywordScanner = await KeywordScanner.get_instance()
        hits = scanner.scan_keywords(input.plan_text)
        if hits:
            logger.warning(
                service=_SERVICE,
                message="keyword_hit_in_plan_text",
                extra={
                    "request_id": input.request_id,
                    "hit_keywords": [h["keyword"] for h in hits],
                    "hit_count": len(hits),
                },
            )
            return True

        logger.info(
            service=_SERVICE,
            message="keyword_scan_clean",
            extra={"request_id": input.request_id},
        )
        return False

    async def _do_llm_assessment(self, input: Any) -> tuple[float | None, DegradationNote | None]:
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

            assessment_result = LLMAssessmentResult.model_validate_json(response_text)
            llm_score = (
                assessment_result.citation_adequacy
                + assessment_result.logical_coherence
                + (1.0 - assessment_result.unsourced_claim_risk)
            ) / 3.0

            logger.info(
                service=_SERVICE,
                message="llm_assessment_success",
                extra={"request_id": input.request_id, "llm_score": round(llm_score, 4)},
            )
            return llm_score, None

        except (LLMClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError, Exception):
            logger.warning(
                service=_SERVICE,
                message="llm_assessment_unavailable",
                extra={"request_id": input.request_id},
            )
            return None, _DEGRADATION_LLM_UNAVAILABLE

    def _do_compute_rule_score(
        self,
        plan_text: str,
        source_list: list[str],
    ) -> float:
        return compute_rule_score(plan_text, source_list)

    def _do_compute_confidence(
        self,
        llm_score: float | None,
        rule_score: float,
        degradation_note: DegradationNote | None,
    ) -> float:
        if degradation_note == _DEGRADATION_LLM_UNAVAILABLE or llm_score is None:
            return rule_score

        llm_weight = float(_get_config("CONFIDENCE_LLM_WEIGHT", "0.5"))
        rule_weight = float(_get_config("CONFIDENCE_RULE_WEIGHT", "0.5"))

        if llm_weight == 0.0 and rule_weight == 0.0:
            llm_weight = 0.5
            rule_weight = 0.5

        return max(0.0, min(1.0, llm_score * llm_weight + rule_score * rule_weight))

    def _do_determine_verdict(
        self,
        input: Any,
        confidence_score: float,
    ) -> tuple[Any, str, bool]:
        if confidence_score >= _CONFIDENCE_THRESHOLD:
            return ValidationVerdict.PASS, input.plan_text, False

        warning_text = _get_config("LOW_CONFIDENCE_DISCLAIMER", _DEFAULT_WARNING_TEXT)
        return ValidationVerdict.APPEND_WARNING, input.plan_text + warning_text, True

    async def _do_trigger_ticket(self, input: Any, verdict: Any) -> bool:
        priority = "critical" if str(verdict) == "force_block" else "normal"
        try:
            await trigger_ticket_with_retry(
                request_id=input.request_id,
                behavior_description=input.behavior_description,
                crisis_level=input.crisis_level,
                priority=priority,
            )
            return False
        except Exception as exc:
            logger.error(
                service=_SERVICE,
                message="ticket_creation_exhausted",
                extra={"request_id": input.request_id, "last_error": str(exc)},
            )
            return True

    def _do_assemble_result(
        self,
        input: Any,
        confidence_score: float,
        verdict: Any,
        modified_plan_text: str,
        ticket_triggered: bool,
        ticket_creation_failed: bool,
        degradation_note: DegradationNote | None,
        elapsed_ms: float,
        background_tasks: Any,
    ) -> Any:
        # 超时安全兜底：若原本 PASS 但总耗时 > 3s，降级为 APPEND_WARNING
        if elapsed_ms > _VALIDATION_TIMEOUT_MS and verdict == ValidationVerdict.PASS:
            logger.warning(
                service=_SERVICE,
                message="validation_timeout_fallback",
                extra={"request_id": input.request_id, "elapsed_ms": elapsed_ms},
            )
            verdict = ValidationVerdict.APPEND_WARNING
            modified_plan_text = input.plan_text + _get_config("LOW_CONFIDENCE_DISCLAIMER", _DEFAULT_WARNING_TEXT)
            degradation_note = _DEGRADATION_TIMEOUT_FALLBACK

        validation_time_ms = round(elapsed_ms, 2)
        validation_detail: dict[str, Any] = {
            "verdict": verdict.value if hasattr(verdict, 'value') else str(verdict),
            "source_count": len(input.source_list),
            "degradation_note": degradation_note,
        }
        background_tasks.add_task(
            _persist_validation_result,
            request_id=input.request_id,
            confidence_score=confidence_score,
            verdict=verdict.value if hasattr(verdict, 'value') else str(verdict),
            validation_detail=validation_detail,
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

    def _do_build_pass_result(self, input: Any) -> Any:
        return ConfidenceValidationOutput(
            confidence_score=0.0,
            verdict=ValidationVerdict.PASS,
            modified_plan_text=input.plan_text,
            ticket_triggered=False,
            ticket_creation_failed=False,
            degradation_note=None,
            validation_time_ms=0.0,
        )

    def _do_build_blocked_result(self, input: Any) -> Any:
        block_message = _get_config("HIGH_RISK_BLOCK_MESSAGE", _DEFAULT_BLOCK_MESSAGE)
        return ConfidenceValidationOutput(
            confidence_score=0.0,
            verdict=ValidationVerdict.FORCE_BLOCK,
            modified_plan_text=block_message,
            ticket_triggered=True,
            ticket_creation_failed=False,
            degradation_note=None,
            validation_time_ms=0.0,
        )


# ============================================================================
# 模块级单例 + 便捷函数
# ============================================================================

_validator = ConfidenceValidatorImpl()


async def validate_confidence(
    input: ConfidenceValidationInput,
    background_tasks: Any,
) -> ConfidenceValidationOutput:
    """置信度后校验（委托给 ConfidenceValidatorImpl ABC 单例）。"""
    return await _validator.validate_confidence(
        input=input,
        background_tasks=background_tasks,
    )


async def _persist_validation_result(
    request_id: str,
    confidence_score: float,
    verdict: str,
    validation_detail: dict[str, Any],
) -> None:
    """异步持久化校验结果（占位实现）。"""
    try:
        logger.info(
            service=_SERVICE,
            message="validation_persist_started",
            extra={"request_id": request_id, "confidence_score": confidence_score, "verdict": verdict},
        )
    except Exception as exc:
        logger.warning(
            service=_SERVICE,
            message="validation_persist_failed",
            extra={"request_id": request_id, "error": str(exc)},
        )


__all__ = [
    "ConfidenceValidatorImpl",
    "validate_confidence",
]
