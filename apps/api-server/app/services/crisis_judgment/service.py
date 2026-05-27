"""CSLT-01 危机分级判定 — judge_crisis() 公共服务入口。

对外暴露 judge_crisis() 异步函数，作为模块的唯一公共接口。
CSLT-08（咨询编排逻辑）通过此接口触发三层递进危机等级判定。

Usage:
    from app.services.crisis_judgment import judge_crisis

    request = CrisisJudgmentRequest(...)
    result = await judge_crisis(request)
"""

from __future__ import annotations

from typing import Any

from .exceptions import CrisisJudgmentError, KeywordDictLoadError
from .models import CrisisJudgmentRequest, CrisisJudgmentResult
from .pipeline import JudgmentPipeline
from py_logger import logger


async def judge_crisis(
    request: CrisisJudgmentRequest,
    config: Any | None = None,
) -> CrisisJudgmentResult:
    """执行三层递进危机分级判定。

    判定流程：前置行为类型选择 -> 规则引擎关键词匹配 -> LLM 精调复审。
    前置选择命中高危时跳过后续两层；规则引擎命中重度时跳过 LLM 复审。
    LLM 超时时降级为规则引擎结果。

    Args:
        request: 危机分级判定请求，含患者档案快照、行为类型勾选、行为描述文本。
        config: 可选配置注入（用于测试时注入 mock 配置）。
                若为 None 则从 packages/py-config 加载。
                当前支持：judgment_llm_timeout_ms (int) 字段。

    Returns:
        CrisisJudgmentResult: 最终判定结果，含危机等级、阻断标记、复核标记、各层详细结论。

    Raises:
        CrisisJudgmentError: 所有判定层面的不可恢复错误基类。
        KeywordDictLoadError: 关键词词库加载失败，规则引擎层级不可用。

    Side Effects:
        - 记录各判定层的结构化日志（INFO 级别）
        - 规则引擎命中重度时记录 WARNING 级别安全事件日志
        - LLM 超时时记录 WARNING 级别事件并写入超时详情
        - 不持久化任何判定结果——仅返回内存对象，持久化由调用方（CSLT-08）负责

    Idempotency:
        本函数为无状态判定，每次调用独立执行。同一请求的重复调用产生相同的判定结果
        （假设外部依赖 LLM API 返回一致）。不维护跨调用的缓存或幂等 Key。

    Thread Safety:
        本函数为 async 协程，内部通过 JudgmentContext 隔离各次调用的状态。
        AC 自动机实例为模块级单例，读操作线程安全，热加载时通过 copy-on-write 保证读写不互斥。
    """
    # 步骤 1：输入校验 —— Pydantic 在校验失败时自动抛出 ValidationError
    # CrisisJudgmentRequest validation happens at call site

    # 步骤 2：构建 Pipeline 并执行
    pipeline = JudgmentPipeline()

    logger.info(
        service="crisis_judgment",
        message="Starting crisis judgment pipeline",
        op_type=None,
        extra={
            "behavior_types": [t.value for t in request.behavior_type_selection],
            "description_length": len(request.behavior_description),
            "has_profile": request.patient_profile is not None,
        },
    )

    try:
        result: CrisisJudgmentResult = await pipeline.run(request)
    except KeywordDictLoadError:
        # 关键词词库加载失败 —— 日志已在 Pipeline 中记录
        raise
    except CrisisJudgmentError:
        # 不可恢复的判定错误
        raise

    # 记录判定完成日志
    logger.info(
        service="crisis_judgment",
        message="Crisis judgment completed",
        op_type=None,
        extra={
            "final_level": result.final_level.value,
            "block_deep_response": result.block_deep_response,
            "manual_review_flag": result.manual_review_flag,
            "degradation_note": result.degradation_note,
            "sources_count": len(result.judgment_sources),
        },
    )

    return result
