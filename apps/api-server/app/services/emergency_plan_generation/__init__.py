"""应急方案生成模块 (CSLT-03).

为 CSLT-08（咨询编排逻辑）提供应急方案生成服务。
核心模式：单次 LLM 调用 + AsyncGenerator 流式输出。

对外暴露的公共接口：
    generate_emergency_plan(input, config) -> GenerationResult

子模块：
    enums.py            — GenerationStatus, BlockVariant 枚举
    exceptions.py       — GenerationInputError, LLMUnavailableError, GenerationTimeoutError
    models.py           — EmergencyPlanInput, GenerationResult, GenerationChunk, PromptBuildContext
    blocked_outputs.py  — BLOCKED_PROMPT_TEMPLATES 字典 + DISCLAIMER_TEXT
    prompt_builder.py   — PromptBuilder (组装 System Prompt + User Message)
    streaming.py        — stream_generate() AsyncGenerator
    service.py          — generate_emergency_plan() 主入口
"""

from __future__ import annotations

from .enums import BlockVariant, GenerationStatus
from .exceptions import GenerationInputError, GenerationTimeoutError, LLMUnavailableError
from .models import EmergencyPlanInput, GenerationChunk, GenerationResult
from .service import generate_emergency_plan

__all__ = [
    # 主接口
    "generate_emergency_plan",
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
]
