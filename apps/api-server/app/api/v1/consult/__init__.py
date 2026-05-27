"""CSLT-02 RAG语义检索 — FastAPI 路由注册。

POST /api/v1/consult/search — 语义检索端点。
接受 SemanticSearchInput JSON 请求体，经 Pydantic 校验（路由层）、
Service 编排（检索执行）后返回排序后的案例切片列表。

端点定位：
  本端点是应急咨询流程中的检索增强节点，供上游 CSLT-01/CSLT-08 调用。
  下游 CSLT-03 接收检索结果用于 Prompt 组装。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from py_schemas.consult import SemanticSearchInput, SemanticSearchResult
from py_schemas.security.validation_schemas import ValidationErrorResponse

router = APIRouter(prefix="/api/v1/consult", tags=["consult"])


@router.post(
    "/search",
    response_model=SemanticSearchResult,
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "检索成功，返回排序后的案例切片列表及检索状态",
            "model": SemanticSearchResult,
        },
        422: {
            "description": "输入校验失败（query_text 长度/为空、tag_filters 缺少必填字段等），"
            "复用 SEC-05 ValidationErrorResponse 格式",
            "model": ValidationErrorResponse,
        },
        503: {
            "description": "服务暂不可用（DashScope 嵌入 API 不可达 / PostgreSQL 连接失败）",
        },
        504: {
            "description": "检索超时且无任何结果",
        },
    },
    summary="语义检索",
    description=(
        "接收用户行为描述文本和档案标签过滤条件，执行混合检索——"
        "先按标签精确过滤候选集，再按语义相似度 + 时效衰减 + 循证加权排序。\n\n"
        "**典型输入**：query_text='儿子在商场突然捂耳朵蹲下尖叫'，"
        "tag_filters={age_range:'学龄儿童(6-12岁)', behavior_type:'EMOTIONAL_MELTDOWN', emotion_level:'重'}\n\n"
        "**返回说明**：\n"
        "- is_complete=true → 检索完整完成\n"
        "- is_complete=false, reason='timeout' → 检索超时无结果\n"
        "- is_complete=false, reason='embedding_unavailable' → 编码服务不可用\n"
        "- is_complete=true, total_count=0, reason='case_library_empty' → 案例库为空"
    ),
)
async def search(
    request: SemanticSearchInput = Depends(),
) -> SemanticSearchResult:
    """语义检索端点。

    依赖注入链：
    1. SemanticSearchInput — FastAPI Body 依赖，自动触发 Pydantic 校验

    Args:
        request: Pydantic 校验通过的语义检索请求。

    Returns:
        SemanticSearchResult: 排序后的案例切片列表及检索状态。
    """
    from app.dependencies.auth_dependencies import get_db_session
    from app.services.consult_service import search_cases

    async for session in get_db_session():
        return await search_cases(
            request=request,
            db=session,
        )


__all__ = ["router"]
