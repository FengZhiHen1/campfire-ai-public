"""CSLT-06 咨询历史管理 — FastAPI 路由注册。

三个端点：
- POST /api/v1/consultations         — 归档写入（幂等）
- GET  /api/v1/consultations         — 历史列表（分页）
- GET  /api/v1/consultations/{id}    — 详情查询

路由设计原则：
- 路由层仅处理请求解析、校验分发与响应封装
- 所有业务逻辑委托给 consultation_history/service.py
- user_id 从 JWT Token 提取，不接受前端传入
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth_dependencies import get_db_session
from app.services.consultation_history.service import (
    ConsultationHistoryIncompleteDataError,
    archive_consultation,
    get_detail,
    list_history,
)
from py_auth.dependencies import get_current_user
from py_schemas.consultation_history import ConsultationHistoryCreate

router = APIRouter(prefix="/api/v1/consultations", tags=["consultations"])


# ===========================================================================
# POST / — 归档写入（201 Created / 200 OK 幂等）
# ===========================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="归档应急咨询历史记录",
    description=(
        "将一次应急咨询的完整上下文数据归档存储为一条历史记录。"
        "基于 request_id 实现幂等——重复提交返回已有记录（HTTP 200）。"
        "consultation_time 以服务端时间为准。"
    ),
    responses={
        201: {"description": "归档成功，新记录已创建"},
        200: {"description": "重复归档，返回已有记录"},
        422: {"description": "必填字段缺失或 disclaimer 等值校验失败"},
    },
)
async def create_consultation(
    data: ConsultationHistoryCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """归档写入端点。

    Args:
        data: 归档数据（Pydantic 自动校验）。
        current_user: 当前用户 JWT payload。
        db: 异步数据库会话。

    Returns:
        ConsultationHistoryDetail 字典。
    """
    try:
        result = await archive_consultation(
            data=data,
            current_user=current_user,
            db=db,
        )
        return result.model_dump(mode="json")
    except ConsultationHistoryIncompleteDataError as exc:
        detail = [{"field": exc.field, "msg": exc.detail}] if exc.field else exc.detail
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


# ===========================================================================
# GET / — 历史列表（分页）
# ===========================================================================


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="查询咨询历史列表",
    description=(
        "查询当前用户的所有咨询历史记录摘要列表。"
        "按 consultation_time 降序排列。"
        "每页最多 page_size 条（默认 20，上限 100）。"
    ),
    responses={
        200: {"description": "成功返回分页列表"},
        422: {"description": "查询参数格式错误"},
    },
)
async def list_consultations(
    page: int = Query(default=1, ge=1, description="页码（1-based）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页记录数"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """历史列表查询端点。

    Args:
        page: 页码（从 1 开始）。
        page_size: 每页条数。
        current_user: 当前用户 JWT payload。
        db: 异步数据库会话。

    Returns:
        PaginatedResponse 字典。
    """
    result = await list_history(
        page=page,
        page_size=page_size,
        current_user=current_user,
        db=db,
    )
    return result.model_dump(mode="json")


# ===========================================================================
# GET /{consultation_id} — 详情查询
# ===========================================================================


@router.get(
    "/{consultation_id}",
    status_code=status.HTTP_200_OK,
    summary="查询咨询详情",
    description=(
        "查询单次咨询的完整详情。"
        "仅返回当前用户本人的记录。"
        "不存在或无权访问时统一返回 404。"
    ),
    responses={
        200: {"description": "成功返回咨询完整详情"},
        404: {"description": "该咨询记录不存在或无权查看"},
    },
)
async def get_consultation(
    consultation_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """详情查询端点。

    Args:
        consultation_id: 咨询记录 UUID（路径参数）。
        current_user: 当前用户 JWT payload。
        db: 异步数据库会话。

    Returns:
        ConsultationHistoryDetail 字典。
    """
    result = await get_detail(
        consultation_id=consultation_id,
        current_user=current_user,
        db=db,
    )
    return result.model_dump(mode="json")


__all__ = ["router"]
