"""CSLT-03 应急方案生成 — 流式生成器。

提供 stream_generate() 异步生成器函数，接收已构建的 messages 列表，
调用 LLMClient.async_chat_stream() 并逐 chunk yield GenerationChunk。

核心流程：
1. 读取配置（model, temperature, max_tokens, timeout）
2. 调用 LLMClient.async_chat_stream() 获取 LLM 流式迭代器（JSON mode）
3. JsonSectionTracker 状态机逐字符解析 JSON，剥离语法字符，标注 section
4. 逐 chunk yield GenerationChunk（含 section 标记）
5. 免责声明存在性检查（finally 块）
6. 最后一个 chunk 标记 is_final=True

TTFT（首字延迟）由调用方在 service 层追踪，本函数不负责。

无全流程硬超时——生成时长取决于 LLM 自身，由 SSE 层的首 chunk 软超时和全流程硬超时负责保护。
"""

from __future__ import annotations

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

_SECTION_KEY_SET: frozenset[str] = frozenset(_SECTION_KEYS)

# ============================================================================
# JsonSectionTracker — 流式 JSON 解析状态机
# ============================================================================


class JsonSectionTracker:
    """流式 JSON 解析状态机。

    逐字符处理 LLM 的 JSON 输出，剥离 JSON 语法字符（花括号、引号、冒号等），
    仅保留段落内容文本，并为每段文本标注所属的 section。

    状态转换::

        OUTSIDE → (看到引号) → IN_KEY → (key 完成) → AWAITING_VALUE
            → (看到 [) → BETWEEN_VALUES → (看到引号) → IN_VALUE
            → (值结束) → BETWEEN_VALUES → ...
            → (看到 ]) → OUTSIDE → (看到下一个引号) → IN_KEY → ...

    Usage:
        tracker = JsonSectionTracker()
        for chunk in llm_stream:
            for section, text in tracker.feed(chunk.delta.content):
                yield GenerationChunk(text=text, section=section, ...)
    """

    # 状态常量
    _LOOKING_FOR_KEY: int = 0
    _IN_KEY: int = 1
    _AWAITING_VALUE: int = 2
    _BETWEEN_VALUES: int = 3
    _IN_VALUE: int = 4

    def __init__(self) -> None:
        self._state: int = self._LOOKING_FOR_KEY
        self._key_buffer: str = ""
        self._current_section: str | None = None
        self._content_buffer: str = ""

    def feed(self, text: str) -> list[tuple[str | None, str]]:
        """喂入一段文本，返回 [(section, content_text), ...] 列表。

        section 为 None 表示 JSON 语法字符（前端忽略）。
        连续同 section 的字符会被合并为单个元组。
        """
        chunks: list[tuple[str | None, str]] = []
        pending_section: str | None = None
        pending_text: str = ""

        def _flush() -> None:
            nonlocal pending_section, pending_text
            if pending_text:
                chunks.append((pending_section, pending_text))
                pending_text = ""
                pending_section = None

        def _emit(section: str | None, content: str) -> None:
            nonlocal pending_section, pending_text
            if section == pending_section:
                pending_text += content
            else:
                _flush()
                pending_section = section
                pending_text = content

        idx = 0
        while idx < len(text):
            ch = text[idx]

            if self._state == self._LOOKING_FOR_KEY:
                if ch == '"':
                    self._state = self._IN_KEY
                    self._key_buffer = ""

            elif self._state == self._IN_KEY:
                if ch == '"':
                    if self._key_buffer in _SECTION_KEY_SET:
                        self._current_section = self._key_buffer
                    self._state = self._AWAITING_VALUE
                elif ch == '\\':
                    if idx + 1 < len(text):
                        self._key_buffer += text[idx + 1]
                        idx += 1
                else:
                    self._key_buffer += ch

            elif self._state == self._AWAITING_VALUE:
                if ch == '[':
                    self._state = self._BETWEEN_VALUES

            elif self._state == self._BETWEEN_VALUES:
                if ch == '"':
                    self._state = self._IN_VALUE
                    self._content_buffer = ""
                elif ch == ']':
                    self._state = self._LOOKING_FOR_KEY
                    self._current_section = None

            elif self._state == self._IN_VALUE:
                if ch == '\\':
                    if idx + 1 < len(text):
                        self._content_buffer += text[idx + 1]
                        idx += 1
                elif ch == '"':
                    self._state = self._BETWEEN_VALUES
                else:
                    self._content_buffer += ch
                    _emit(self._current_section, ch)

            idx += 1

        _flush()
        return chunks


# ============================================================================
# parse_json_sections —— 从 JSON 文本提取四段式结构化数据
# ============================================================================


def parse_json_sections(text: str) -> dict[str, list[str]]:
    """从 LLM JSON 输出中提取四个 section 的内容。

    优先使用 json.loads() 严格解析；失败时回退到 JsonSectionTracker
    流式解析器（与前端渲染路径一致），仅合并连续同 section 的字符片段。

    Args:
        text: LLM 输出的完整 JSON 文本。

    Returns:
        dict[str, list[str]]: section 标题 → 内容列表的映射。
    """
    # 优先严格解析
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    else:
        if isinstance(data, dict):
            sections: dict[str, list[str]] = {}
            for key in _SECTION_KEYS:
                value = data.get(key, [])
                if isinstance(value, list):
                    sections[key] = [str(item) for item in value]
                else:
                    sections[key] = []
            return sections

    # 回退：用流式解析器（容忍未转义引号等轻微语法瑕疵）
    tracker = JsonSectionTracker()
    fragments = tracker.feed(text)

    sections = {key: [] for key in _SECTION_KEYS}
    current_section: str | None = None
    current_text: str = ""

    for section, content in fragments:
        if section is None:
            continue
        if section == current_section:
            current_text += content
        else:
            if current_section is not None and current_text.strip():
                sections[current_section].append(current_text.strip())
            current_section = section
            current_text = content

    if current_section is not None and current_text.strip():
        sections[current_section].append(current_text.strip())

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
    JsonSectionTracker 剥离 JSON 语法、标注 section，实现真正的流式分段渲染。

    调用方使用 async for chunk in stream_generate(...) 消费。
    最后一个 chunk 的 is_final=True 表示流式输出结束。

    Args:
        input_data: 校验通过的 EmergencyPlanInput。
        messages: 由 PromptBuilder.build() 产出的 messages 列表。
        prenumbered_slices: 预编号切片映射表 [(编号, slice_id), ...]。
        llm_client: LLMClient 实例。为 None 时创建默认实例。
        config: 可选 AppSettings 配置实例。为 None 时从 py_config 加载默认值。

    Yields:
        GenerationChunk: 每个 LLM Token 增量块，含 section 标记。

    Raises:
        LLMUnavailableError: LLM API 不可用（在 yield 前抛出）。
        GenerationTimeoutError: 全流程超时且无任何文本产出（在 yield 前抛出）。
    """
    # === 读取配置 ===
    model: str = config.DEEPSEEK_MODEL if config else "deepseek-v4-pro"
    temperature: float = config.GENERATION_TEMPERATURE if config else 0.3
    max_tokens: int = config.GENERATION_MAX_TOKENS if config else 8192
    timeout_s: float = config.GENERATION_TIMEOUT_S if config else 30.0

    # === 初始化 LLM 客户端 ===
    client = llm_client or LLMClient()

    # === 流式调用 ===
    t_start: float = time.monotonic()
    accumulated_text: str = ""
    finish_reason: str = "stop"
    tracker = JsonSectionTracker()
    chunk_count: int = 0

    logger.info(
        service="emergency_plan_generation",
        message="Starting LLM stream call",
        op_type="llm_stream_start",
        extra={
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout_s": timeout_s,
            "message_count": len(messages),
            "trace_id": input_data.request_id,
        },
    )

    llm_stream = client.async_chat_stream(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout_s,
        response_format={"type": "json_object"},
    )

    try:
        async for chunk in llm_stream:
            # 提取 delta text
            delta_text: str = ""
            if chunk.choices and len(chunk.choices) > 0:
                delta_text = chunk.choices[0].delta.content or ""

            accumulated_text += delta_text
            chunk_count += 1

            # 通过状态机剥离 JSON 语法，产出带 section 标记的内容文本
            for section, content_text in tracker.feed(delta_text):
                yield GenerationChunk(
                    text=content_text,
                    section=section,
                    is_final=False,
                    finish_reason=None,
                )

    except LLMClientError as exc:
        raise LLMUnavailableError(detail="LLM 生成服务暂时不可用，请稍后重试", original_error=exc) from exc

    except Exception as exc:
        raise LLMUnavailableError(detail="LLM 生成服务暂时不可用，请稍后重试", original_error=exc) from exc

    else:
        finish_reason = "stop"
        logger.info(
            service="emergency_plan_generation",
            message="LLM stream completed normally",
            op_type="llm_stream_done",
            extra={
                "chunk_count": chunk_count,
                "accumulated_len": len(accumulated_text),
                "elapsed_ms": (time.monotonic() - t_start) * 1000,
                "trace_id": input_data.request_id,
            },
        )

    finally:
        yield GenerationChunk(
            text="",
            section=None,
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
