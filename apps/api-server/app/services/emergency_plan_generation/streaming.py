"""CSLT-03 应急方案生成 — 流式生成器。

提供 stream_generate() 异步生成器函数，接收已构建的 messages 列表，
调用 LLMClient.async_chat_stream() 并逐 chunk yield GenerationChunk。

核心流程：
1. 读取配置（model, temperature, max_tokens, timeout）
2. 调用 LLMClient.async_chat_stream() 获取 LLM 流式迭代器
3. 使用 asyncio.timeout_at() 全流程超时保护
4. 逐 chunk yield GenerationChunk
5. 免责声明存在性检查（finally 块）
6. 最后一个 chunk 标记 is_final=True

TTFT（首字延迟）由调用方在 service 层追踪，本函数不负责。

超时降级策略：
- 已有至少一个完整段落（含 ## 标题）→ finish_reason="timeout", 不抛异常
- 有文本但不含完整段落 → 视为无有效内容, finish_reason="timeout", accumulated_text 置空
- 无文本 → 抛出 GenerationTimeoutError

注意：finish_reason 为 "timeout" 时，调用方需根据 accumulated_text 是否含有
完整段落标题来判断 PARTIAL 或 TIMEOUT。
"""

from __future__ import annotations

import asyncio
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

# 完整段落标题的正则检测 — 匹配四段式结构中的标题行
_SECTION_HEADER_PATTERN: re.Pattern[str] = re.compile(r"^##\s[一二三四]、")

# 来源引用行正则 — 用于提取 source_list
_SOURCE_LINE_PATTERN: re.Pattern[str] = re.compile(
    r"^\[(\d+)\] CASE-(\d{3}) .+（(\d{4}-\d{2}-\d{2})）$", re.MULTILINE
)

# 免责声明检测正则（末尾 200 字符）
_DISCLAIMER_CHECK_PATTERN: re.Pattern[str] = re.compile(r"不构成医疗诊断|以上建议由 AI 生成")

# 引用标记提取正则
_REFERENCE_TAG_PATTERN: re.Pattern[str] = re.compile(r"\[(\d+)\]")

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
            # 检查是否包含至少一个完整段落标题
            if _SECTION_HEADER_PATTERN.search(accumulated_text):
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
                # 有文本但不含完整段落 → 视为无有效内容，抛出异常
                accumulated_text = ""
                logger.warning(
                    service="emergency_plan_generation",
                    message="Generation timed out with no complete section",
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
# 辅助函数：从 accumulated_text 构建 GenerationResult
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
    1. 免责声明存在性检查（缺失时强制追加）
    2. 引用反查（从 LLM 文本提取 [N] 并匹配 prenumbered_slices）
    3. source_list 格式化

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

    # === 构建 source_list ===
    formatted_sources: list[str] = []
    for match in _SOURCE_LINE_PATTERN.finditer(accumulated_text):
        formatted_sources.append(match.group(0))

    return GenerationResult(
        text=accumulated_text,
        source_list=formatted_sources,
        disclaimer=DISCLAIMER_TEXT,
        generation_time_ms=generation_time_ms,
        is_partial=is_partial,
        referenced_slice_ids=referenced_slice_ids,
        finish_reason=finish_reason,
        ttft_ms=ttft_ms or 0.0,
    )
