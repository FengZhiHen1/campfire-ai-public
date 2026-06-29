"""CSLT-01 危机分级判定 — LLMReviewLayer LLM 精调复审层。

调用 DeepSeek API 对规则引擎结果进行精调复审。
包含超时降级机制：超时后不重试，降级为规则引擎结果。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from py_llm import LLMClient

from .enums import CrisisLevel
from .layer import JudgmentLayer
from .models import (
    CrisisJudgmentRequest,
    JudgmentLayerResult,
)
from py_logger import logger

# 默认 LLM 超时时间（毫秒）
_DEFAULT_LLM_TIMEOUT_MS: int = 30000

# 系统提示模板版本
_PROMPT_VERSION: str = "v1"

# LLM 复审结果中合法的 level 值
_VALID_LLM_LEVELS: frozenset[str] = frozenset({"mild", "moderate", "severe"})


class LLMReviewLayer(JudgmentLayer):
    """LLM 精调复审层。

    调用 DeepSeek API 对规则引擎的结果进行复审。
    超时时降级为规则引擎结果，不重试。
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        timeout_ms: int = _DEFAULT_LLM_TIMEOUT_MS,
        model: str | None = None,
    ) -> None:
        """初始化 LLM 复审层。

        Args:
            llm_client: LLM 客户端实例。为 None 时创建默认实例。
            timeout_ms: LLM 调用超时时间（毫秒）。
            model: 模型名称。为 None 时从 AppSettings.DEEPSEEK_MODEL 读取。
        """
        self._llm_client = llm_client or LLMClient()
        self._timeout_ms = timeout_ms
        if model is None:
            try:
                from py_config import get_settings
                model = get_settings().DEEPSEEK_MODEL
            except (ImportError, AttributeError):
                model = "deepseek-v4-pro"
        self._model = model

    async def judge(self, request: CrisisJudgmentRequest) -> JudgmentLayerResult:
        """执行 LLM 精调复审。

        Args:
            request: 危机分级判定请求。

        Returns:
            LLM 复审层的判定结果。
        """
        system_prompt = self._build_system_prompt(request)

        timeout_seconds: float = self._timeout_ms / 1000.0
        start_time: float = time.time()

        try:
            response_text: str = await asyncio.wait_for(
                self._llm_client.async_chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": request.behavior_description},
                    ],
                    model=self._model,
                    temperature=0.1,
                    max_tokens=512,
                    timeout=timeout_seconds,
                    response_format={"type": "json_object"},
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            elapsed_ms: int = int((time.time() - start_time) * 1000)
            logger.warning(
                service="crisis_judgment",
                message="LLM review timeout",
                op_type=None,
                extra={
                    "timeout_ms": self._timeout_ms,
                    "elapsed_ms": elapsed_ms,
                },
            )
            return JudgmentLayerResult(
                layer_name="LLMReviewLayer",
                level=None,
                trigger_rule_id=None,
                details={
                    "timeouts": True,
                    "elapsed_ms": elapsed_ms,
                    "prompt_version": _PROMPT_VERSION,
                },
            )

        elapsed_ms = int((time.time() - start_time) * 1000)

        try:
            parsed: dict[str, Any] = json.loads(response_text)
            level_str: str = parsed.get("level", "")
            confidence: float | None = parsed.get("confidence")

            if level_str not in _VALID_LLM_LEVELS:
                logger.error(
                    service="crisis_judgment",
                    message="LLM review returned invalid level",
                    op_type=None,
                    extra={
                        "level": level_str,
                        "raw_response": response_text[:500],
                    },
                )
                return JudgmentLayerResult(
                    layer_name="LLMReviewLayer",
                    level=None,
                    trigger_rule_id=None,
                    details={
                        "parse_error": True,
                        "raw_response": response_text[:500],
                        "prompt_version": _PROMPT_VERSION,
                    },
                )

            if confidence is not None and not (0.0 <= confidence <= 1.0):
                confidence = None

            return JudgmentLayerResult(
                layer_name="LLMReviewLayer",
                level=CrisisLevel(level_str),
                trigger_rule_id=None,
                details={
                    "raw_response": response_text[:500],
                    "prompt_version": _PROMPT_VERSION,
                    "elapsed_ms": elapsed_ms,
                    "confidence": confidence,
                },
            )

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error(
                service="crisis_judgment",
                message="LLM review response parse failed",
                op_type=None,
                extra={
                    "error": str(exc),
                    "raw_response": response_text[:500],
                },
            )
            return JudgmentLayerResult(
                layer_name="LLMReviewLayer",
                level=None,
                trigger_rule_id=None,
                details={
                    "parse_error": True,
                    "raw_response": response_text[:500],
                    "prompt_version": _PROMPT_VERSION,
                },
            )

    def _build_system_prompt(self, request: CrisisJudgmentRequest) -> str:
        """组装 LLM 复审的 System Prompt。

        Args:
            request: 危机分级判定请求，用于提取患者档案和行为描述等上下文。

        Returns:
            组装完成的 System Prompt 字符串。
        """
        # 序列化患者档案
        profile_snapshot: str = "无"
        if request.patient_profile is not None:
            profile_snapshot = (
                f"诊断类型：{request.patient_profile.diagnosis_type or '未知'}，"
                f"历史行为标签：{', '.join(request.patient_profile.historical_behavior_tags) if request.patient_profile.historical_behavior_tags else '无'}"
            )

        # 序列化行为类型
        behavior_types: str = ", ".join(
            t.value for t in request.behavior_type_selection
        )

        prompt: str = (
            "你是一名孤独症危机行为评估专家。根据以下信息判断当前场景的危机严重程度"
            "（mild/moderate/severe）。只需返回 JSON："
            '{{"level": "mild|moderate|severe", "confidence": 0.0~1.0, "reasoning": "..."}}。'
            "宁可误判为重度，不可漏判为轻度。\n\n"
            f"患者档案：{profile_snapshot}\n"
            f"行为描述：{request.behavior_description}\n"
            f"行为类型勾选：{behavior_types}\n"
        )

        return prompt
