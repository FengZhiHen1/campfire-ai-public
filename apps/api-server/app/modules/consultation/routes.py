"""CSLT-02/08 应急咨询 — FastAPI 路由注册。

MVP Phase 1：
- POST /api/v1/consult/search — 语义检索端点（保留）
- POST /api/v1/consult — 应急咨询触发端点（新增）
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import get_db_session
from app.modules.consultation.consult_service import search_cases, start_consultation
from py_schemas.consult import SemanticSearchInput, SemanticSearchResult
from py_schemas.consult_start import ConsultStartRequest, ConsultStartResponse
from py_schemas.security.validation_schemas import ValidationErrorResponse

router = APIRouter(prefix="/api/v1/consult", tags=["consult"])


# ===========================================================================
# POST /api/v1/consult — 应急咨询触发
# ===========================================================================


@router.post(
    "",
    response_model=ConsultStartResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "咨询已启动，返回 SSE 会话 ID",
            "model": ConsultStartResponse,
        },
        422: {
            "description": "输入校验失败",
            "model": ValidationErrorResponse,
        },
        503: {
            "description": "服务暂不可用（检索引擎或 LLM 不可达）",
        },
    },
    summary="启动应急咨询",
    description=(
        "提交行为描述，后端执行档案标签读取 → RAG 检索 → LLM 流式生成编排，"
        "返回 session_id。客户端随后连接 SSE 流式端点接收生成结果。"
    ),
)
async def start_consult(
    request: ConsultStartRequest,
    anonymous_user: dict = Depends(get_anonymous_user),
    db: AsyncSession = Depends(get_db_session),
) -> ConsultStartResponse:
    """启动应急咨询端点。

    Args:
        request: 咨询请求体（行为描述 + 可选档案 ID + 可选标签）。
        anonymous_user: 匿名用户字典（由 X-Device-Id 提取/创建）。
        db: 数据库异步会话。

    Returns:
        ConsultStartResponse: 含 session_id，用于后续 SSE 连接。
    """
    session_id = await start_consultation(
        behavior_description=request.behavior_description,
        profile_id=str(request.profile_id) if request.profile_id else None,
        behavior_type=cast(list[str], request.behavior_type),
        emotion_level=request.emotion_level,
        user_id=anonymous_user.get("sub", ""),
        db=db,
    )
    return ConsultStartResponse(session_id=session_id)


# ===========================================================================
# POST /api/v1/consult/search — 语义检索
# ===========================================================================


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
    request: SemanticSearchInput,
    db: AsyncSession = Depends(get_db_session),
) -> SemanticSearchResult:
    """语义检索端点。

    Args:
        request: Pydantic 校验通过的语义检索请求。
        db: 数据库异步会话。

    Returns:
        SemanticSearchResult: 排序后的案例切片列表及检索状态。
    """
    return await search_cases(
        request=request,
        db=db,
    )


__all__ = ["router"]
