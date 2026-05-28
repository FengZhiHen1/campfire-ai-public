"""CSLT-03 应急方案生成 — 流式生成器。

提供 stream_generate() 异步生成器函数，接收已构建的 messages 列表，
调用 LLMClient.async_chat_stream() 并逐 chunk yield GenerationChunk。

核心流程：
1. 读取配置（model, temperature, max_tokens, timeout）
2. 调用 LLMClient.async_chat_stream() 获取 LLM 流式迭代器（JSON mode）
3. 使用 asyncio.timeout_at() 全流程超时保护
4. 逐 chunk yield GenerationChunk
5. 免责声明存在性检查（finally 块）
6. 最后一个 chunk 标记 is_final=True

TTFT（首字延迟）由调用方在 service 层追踪，本函数不负责。

超时降级策略：
- 已产出 >= MIN_JSON_CONTENT_LENGTH 字符文本 → finish_reason="timeout", 不抛异常
- 有文本但不足最低长度 → 视为无有效内容, finish_reason="timeout", accumulated_text 置空
- 无文本 → 抛出 GenerationTimeoutError
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, AsyncGenerator

from py_logger import logger

from py_llm import LLMClient
from py_llm.client import LLMClientError

from .blocked_outputs import DISCLAIMER_TEXT
from .enums import GenerationStatus
from .exceptions import GenerationTimeoutError, LLMUnavailableError
from .models import EmergencyPlanInput, GenerationChunk, GenerationResult

# ============================================================================
# 常量
# ============================================================================

# JSON 模式下判定为"有效内容"的最低字符数
_MIN_JSON_CONTENT_LENGTH: int = 100

# 免责声明检测正则（末尾 200 字符）
_DISCLAIMER_CHECK_PATTERN: re.Pattern[str] = re.compile(r"不构成医疗诊断|以上建议由 AI 生成")

# 引用标记提取正则
_REFERENCE_TAG_PATTERN: re.Pattern[str] = re.compile(r"\[(\d+)\]")

# JSON 四段式 section key 列表
_SECTION_KEYS: list[str] = [
    "即时安全干预动作",
    "情绪安抚话术",
    "后续观察指标",
    "就医判断标准",
]

# ============================================================================
# parse_json_sections —— 从 JSON 文本提取四段式结构化数据
# ============================================================================


def parse_json_sections(text: str) -> dict[str, list[str]]:
    """从 LLM JSON 输出中提取四个 section 的内容。

    Args:
        text: LLM 输出的完整 JSON 文本。

    Returns:
        dict[str, list[str]]: section 标题 → 内容列表的映射。
        解析失败时返回全空列表的 dict。
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            service="emergency_plan_generation",
            message="Failed to parse JSON from LLM output",
            op_type="json_parse",
            extra={"text_preview": text[:200]},
        )
        return {key: [] for key in _SECTION_KEYS}

    if not isinstance(data, dict):
        return {key: [] for key in _SECTION_KEYS}

    sections: dict[str, list[str]] = {}
    for key in _SECTION_KEYS:
        value = data.get(key, [])
        if isinstance(value, list):
            sections[key] = [str(item) for item in value]
        else:
            sections[key] = []

    return sections


# ============================================================================
# stream_generate — 流式生成主协程
# ============================================================================


async def stream_generate(
    input_data: EmergencyPlanInput,
    messages: list[dict[str, str]],
    prenumbered_slices: list[tuple[str, str]],
    llm_client: LLMClient | None = None,
    config: Any | None = None,
) -> AsyncGenerator[GenerationChunk, None]:
    """流式生成应急方案 —— 将 LLM 返回的每个 Token 增量通过 AsyncGenerator 实时产出。

    LLM 使用 JSON mode (response_format={"type": "json_object"})，
    输出为结构化 JSON 文本。流结束后由下游解析 sections。

    调用方使用 async for chunk in stream_generate(...) 消费。
    最后一个 chunk 的 is_final=True 表示流式输出结束。

    Args:
        input_data: 校验通过的 EmergencyPlanInput。
        messages: 由 PromptBuilder.build() 产出的 messages 列表。
        prenumbered_slices: 预编号切片映射表 [(编号, slice_id), ...]。
        llm_client: LLMClient 实例。为 None 时创建默认实例。
        config: 可选 AppSettings 配置实例。为 None 时从 py_config 加载默认值。

    Yields:
        GenerationChunk: 每个 LLM Token 增量块。

    Raises:
        LLMUnavailableError: LLM API 不可用（在 yield 前抛出）。
        GenerationTimeoutError: 全流程超时且无任何文本产出（在 yield 前抛出）。
    """
    # === 读取配置 ===
    model: str = config.DEEPSEEK_MODEL if config else "deepseek-v4-pro"
    temperature: float = config.GENERATION_TEMPERATURE if config else 0.3
    max_tokens: int = config.GENERATION_MAX_TOKENS if config else 8192
    timeout_s: float = config.GENERATION_TIMEOUT_S if config else 15.0

    # === 初始化 LLM 客户端 ===
    client = llm_client or LLMClient()

    # === 流式调用 ===
    t_start: float = time.monotonic()
    accumulated_text: str = ""
    finish_reason: str = "stop"

    llm_stream = client.async_chat_stream(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout_s,
        response_format={"type": "json_object"},
    )

    deadline: float = t_start + timeout_s

    try:
        async with asyncio.timeout_at(deadline):
            async for chunk in llm_stream:
                # 提取 delta text
                delta_text: str = ""
                if chunk.choices and len(chunk.choices) > 0:
                    delta_text = chunk.choices[0].delta.content or ""

                accumulated_text += delta_text

                yield GenerationChunk(
                    text=delta_text,
                    is_final=False,
                    finish_reason=None,
                )

    except asyncio.TimeoutError:
        # 全流程超时
        elapsed_ms: float = (time.monotonic() - t_start) * 1000

        if accumulated_text:
            if len(accumulated_text) >= _MIN_JSON_CONTENT_LENGTH:
                finish_reason = "timeout"
                logger.warning(
                    service="emergency_plan_generation",
                    message="Generation timed out with partial content",
                    op_type="stream_timeout",
                    extra={
                        "request_id": input_data.request_id,
                        "elapsed_ms": elapsed_ms,
                        "partial_text_len": len(accumulated_text),
                        "trace_id": input_data.request_id,
                    },
                )
            else:
                # 文本不足最低长度 → 视为无有效内容
                accumulated_text = ""
                logger.warning(
                    service="emergency_plan_generation",
                    message="Generation timed out with insufficient content",
                    op_type="stream_timeout",
                    extra={
                        "request_id": input_data.request_id,
                        "elapsed_ms": elapsed_ms,
                        "trace_id": input_data.request_id,
                    },
                )
                raise GenerationTimeoutError(
                    detail="应急方案生成超时，请稍后重试（30秒冷却期）",
                    elapsed_ms=elapsed_ms,
                    accumulated_text="",
                )
        else:
            # 无任何文本产出
            logger.error(
                service="emergency_plan_generation",
                message="Generation timed out with no text output",
                op_type="stream_timeout",
                extra={
                    "request_id": input_data.request_id,
                    "elapsed_ms": elapsed_ms,
                    "trace_id": input_data.request_id,
                },
            )
            raise GenerationTimeoutError(
                detail="应急方案生成超时，请稍后重试（30秒冷却期）",
                elapsed_ms=elapsed_ms,
                accumulated_text="",
            )

    except LLMClientError as exc:
        # LLM API 不可用（含重试耗尽）— 包装为模块异常后传播
        raise LLMUnavailableError(detail="LLM 生成服务暂时不可用，请稍后重试", original_error=exc) from exc

    except Exception as exc:
        # 非预期异常（网络中断、JSON 解析失败等）— 包装为模块异常
        raise LLMUnavailableError(detail="LLM 生成服务暂时不可用，请稍后重试", original_error=exc) from exc

    else:
        # 正常完成
        finish_reason = "stop"

    finally:
        yield GenerationChunk(
            text="",
            is_final=True,
            finish_reason=finish_reason,
        )


# ============================================================================
# build_generation_result —— 从 accumulated_text 构建 GenerationResult
# ============================================================================


def build_generation_result(
    input_data: EmergencyPlanInput,
    accumulated_text: str,
    ttft_ms: float | None,
    t_start: float,
    prenumbered_slices: list[tuple[str, str]],
    is_partial: bool,
    finish_reason: GenerationStatus,
) -> GenerationResult:
    """从流式生成的累积文本构建完整的 GenerationResult。

    负责：
    1. JSON 解析提取四段式 sections
    2. 免责声明存在性检查（缺失时强制追加）
    3. 引用反查（从 LLM 文本提取 [N] 并匹配 prenumbered_slices）
    4. source_list 格式化

    Args:
        input_data: EmergencyPlanInput 实例。
        accumulated_text: 流式生成累积的完整文本。
        ttft_ms: 首字延迟（毫秒），None 表示无有效 TTFT。
        t_start: time.monotonic() 起始时间戳。
        prenumbered_slices: 预编号切片映射表 [(编号, slice_id), ...]。
        is_partial: 是否为部分生成。
        finish_reason: 生成结束原因。

    Returns:
        组装后的 GenerationResult 实例。
    """
    generation_time_ms: float = (time.monotonic() - t_start) * 1000

    # === 解析 JSON sections ===
    sections = parse_json_sections(accumulated_text) if accumulated_text else {}

    # === 免责声明存在性检查 ===
    if accumulated_text:
        if not _DISCLAIMER_CHECK_PATTERN.search(accumulated_text[-200:]):
            accumulated_text += f"\n\n---\n\n{DISCLAIMER_TEXT}"
            logger.warning(
                service="emergency_plan_generation",
                message="Disclaimer missing from LLM output, appended forcibly",
                op_type="disclaimer_fix",
                extra={
                    "request_id": input_data.request_id,
                    "trace_id": input_data.request_id,
                },
            )

    # === 构建 referenced_slice_ids ===
    referenced_slice_ids: list[str] = []
    tag_matches = _REFERENCE_TAG_PATTERN.findall(accumulated_text)
    number_to_slice: dict[str, str] = {num: sid for num, sid in prenumbered_slices}

    for tag in tag_matches:
        if tag in number_to_slice:
            referenced_slice_ids.append(number_to_slice[tag])
        else:
            logger.warning(
                service="emergency_plan_generation",
                message="LLM output references out-of-range slice number",
                op_type="reference_scan",
                extra={
                    "request_id": input_data.request_id,
                    "invalid_tag": f"[{tag}]",
                    "valid_range": f"[1..{len(prenumbered_slices)}]",
                    "trace_id": input_data.request_id,
                },
            )

    return GenerationResult(
        text=accumulated_text,
        sections=sections,
        source_list=[],
        disclaimer=DISCLAIMER_TEXT,
        generation_time_ms=generation_time_ms,
        is_partial=is_partial,
        referenced_slice_ids=referenced_slice_ids,
        finish_reason=finish_reason,
        ttft_ms=ttft_ms or 0.0,
    )
