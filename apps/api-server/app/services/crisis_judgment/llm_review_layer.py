"""CSLT-01 危机分级判定 — LLMReviewLayer LLM 精调复审层。

调用 DeepSeek API 对规则引擎结果进行精调复审。
包含超时降级机制：超时后不重试，降级为规则引擎结果。

LLMClient 接口定义（因为 packages/py-llm 是 stub）：
    async_chat(messages, model, temperature, max_tokens, timeout) -> LLMResponse
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .enums import CrisisLevel
from .layer import JudgmentLayer
from .models import (
    CrisisJudgmentRequest,
    JudgmentLayerResult,
)
from py_logger import logger

# 默认 LLM 超时时间（毫秒）
_DEFAULT_LLM_TIMEOUT_MS: int = 5000

# 系统提示模板版本
_PROMPT_VERSION: str = "v1"

# LLM 复审结果中合法的 level 值
_VALID_LLM_LEVELS: frozenset[str] = frozenset({"mild", "moderate", "severe"})


class LLMClient:
    """LLM 客户端接口。

    因为 packages/py-llm 是 stub（只有 "Hello from py-llm!"），
    本模块临时定义 LLMClient 接口，允许调用方通过依赖注入传入实际实现。

    实际 DeepSeek API 调用通过 async_chat 方法实现。
    当前使用 asyncio.sleep + mock 返回值作为占位。
    """

    async def async_chat(
        self,
        messages: list[dict[str, str]],
        model: str = "deepseek-chat",
        temperature: float = 0.1,
        max_tokens: int = 512,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """执行 LLM Chat 调用（占位实现）。

        Args:
            messages: 消息列表，格式为 [{"role": "system", "content": "..."}, ...]。
            model: 模型名称。
            temperature: 温度参数。
            max_tokens: 最大输出 token 数。
            timeout: 超时时间（秒）。

        Returns:
            包含 content 字段的响应字典。

        Raises:
            asyncio.TimeoutError: 超时。
            Exception: API 调用异常。
        """
        # 占位实现：模拟 API 延迟后返回 mock 结果
        await asyncio.sleep(0.1)
        return {
            "content": json.dumps({
                "level": "mild",
                "confidence": 0.95,
                "reasoning": "Normal behavior description, no crisis detected.",
            }),
        }


class LLMReviewLayer(JudgmentLayer):
    """LLM 精调复审层。

    调用 DeepSeek API 对规则引擎的结果进行复审。
    超时时降级为规则引擎结果，不重试。
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        timeout_ms: int = _DEFAULT_LLM_TIMEOUT_MS,
    ) -> None:
        """初始化 LLM 复审层。

        Args:
            llm_client: LLM 客户端实例。为 None 时创建默认实例。
            timeout_ms: LLM 调用超时时间（毫秒）。
        """
        self._llm_client = llm_client or LLMClient()
        self._timeout_ms = timeout_ms

    async def judge(self, request: CrisisJudgmentRequest) -> JudgmentLayerResult:
        """执行 LLM 精调复审。

        Args:
            request: 危机分级判定请求。

        Returns:
            LLM 复审层的判定结果。
        """
        # 步骤 1：组装 System Prompt
        system_prompt = self._build_system_prompt(request)

        # 步骤 2：执行 LLM 调用（带超时）
        timeout_seconds: float = self._timeout_ms / 1000.0
        start_time: float = time.time()

        try:
            response = await asyncio.wait_for(
                self._llm_client.async_chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": request.behavior_description},
                    ],
                    model="deepseek-chat",
                    temperature=0.1,
                    max_tokens=512,
                    timeout=timeout_seconds,
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

        # 步骤 3：解析响应
        elapsed_ms = int((time.time() - start_time) * 1000)

        try:
            content: str = response.get("content", "")
            parsed: dict[str, Any] = json.loads(content)
            level_str: str = parsed.get("level", "")
            confidence: float | None = parsed.get("confidence")

            # 步骤 4：校验返回值
            if level_str not in _VALID_LLM_LEVELS:
                logger.error(
                    service="crisis_judgment",
                    message="LLM review returned invalid level",
                    op_type=None,
                    extra={
                        "level": level_str,
                        "raw_response": content[:500],
                    },
                )
                return JudgmentLayerResult(
                    layer_name="LLMReviewLayer",
                    level=None,
                    trigger_rule_id=None,
                    details={
                        "parse_error": True,
                        "raw_response": content[:500],
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
                    "raw_response": content[:500],
                    "prompt_version": _PROMPT_VERSION,
                    "elapsed_ms": elapsed_ms,
                },
            )

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            content_preview = response.get("content", "")[:500]
            logger.error(
                service="crisis_judgment",
                message="LLM review response parse failed",
                op_type=None,
                extra={
                    "error": str(exc),
                    "raw_response": content_preview,
                },
            )
            return JudgmentLayerResult(
                layer_name="LLMReviewLayer",
                level=None,
                trigger_rule_id=None,
                details={
                    "parse_error": True,
                    "raw_response": content_preview,
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
