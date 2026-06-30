"""应急方案生成模块 (CSLT-03).

为 CSLT-08（咨询编排逻辑）提供应急方案生成服务。
核心模式：单次 LLM 调用 + AsyncGenerator 流式输出。

核心类：
  - PlanGeneratorImpl: 实现 BasePlanGenerator 契约，方案生成

外部接口：
  - generate_emergency_plan(input, config) -> GenerationResult

子模块：
    generation_contract.py — BasePlanGenerator ABC 契约
    enums.py              — GenerationStatus, BlockVariant 枚举
    exceptions.py         — GenerationInputError, LLMUnavailableError, GenerationTimeoutError
    models.py             — EmergencyPlanInput, GenerationResult, GenerationChunk, PromptBuildContext
    blocked_outputs.py    — BLOCKED_PROMPT_TEMPLATES 字典 + DISCLAIMER_TEXT
    prompt_builder.py     — PromptBuilder (组装 System Prompt + User Message)
    streaming.py          — stream_generate() AsyncGenerator + JsonSectionTracker
    service.py            — generate_emergency_plan() 主入口
    _metrics.py           — Prometheus 指标
"""

from __future__ import annotations

from .enums import BlockVariant, GenerationStatus
from .exceptions import (
    GenerationInputError,
    GenerationTimeoutError,
    LLMUnavailableError,
)
from .generation_contract import BasePlanGenerator
from .models import EmergencyPlanInput, GenerationChunk, GenerationResult
from .prompt_builder import PromptBuilder
from .service import PlanGeneratorImpl, generate_emergency_plan
from .streaming import (
    JsonSectionTracker,
    build_generation_result,
    parse_json_sections,
    stream_generate,
)

__all__ = [
    # 契约
    "BasePlanGenerator",
    # 主接口
    "generate_emergency_plan",
    "PlanGeneratorImpl",
    # 输入/输出模型
    "EmergencyPlanInput",
    "GenerationResult",
    "GenerationChunk",
    # 枚举
    "GenerationStatus",
    "BlockVariant",
    # 异常
    "GenerationInputError",
    "LLMUnavailableError",
    "GenerationTimeoutError",
    # Prompt 构建
    "PromptBuilder",
    # 流式生成
    "stream_generate",
    "JsonSectionTracker",
    "build_generation_result",
    "parse_json_sections",
]
