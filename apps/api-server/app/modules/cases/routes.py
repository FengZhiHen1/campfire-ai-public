"""CASE-01 案例录入管理 — MVP Phase 1 简化版路由。

去除角色准入校验（MVP 不区分角色），保留核心 CRUD。
路由层仅做依赖注入和委托——所有业务逻辑在 CaseManagementService 中。

- POST /api/v1/cases — 创建案例草稿
- PUT /api/v1/cases/{case_id} — 更新案例
- POST /api/v1/cases/{case_id}/submit — 提交审核
- GET /api/v1/cases/{case_id} — 获取案例详情
- GET /api/v1/cases — 案例列表查询
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import (
    get_case_repository,
    get_db_session,
)
from app.modules.cases.case_service import CaseManagementService
from py_db.repositories.case_repository import CaseRepository
from py_schemas.cases import (
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseUpdate,
    PaginatedResponse,
)
from py_schemas.security.validation_schemas import ValidationErrorResponse

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])

# 服务实例（单例，无状态，所有状态通过 session/repo 参数传入）
_case_service = CaseManagementService()


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "案例草稿创建成功（status=draft）"},
        422: {
            "description": "输入校验失败（字段格式/四段式缺失）",
            "model": ValidationErrorResponse,
        },
        503: {"description": "服务暂时不可用（数据库写入失败）"},
    },
    summary="创建案例草稿",
    description="创建案例草稿，初始状态为 draft。MVP 阶段任何用户均可创建。",
)
async def create_case_endpoint(
    request: CaseCreateRequest,
    anonymous_user: Dict[str, Any] = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """创建案例草稿端点。"""
    return await _case_service.create_case(
        request=request,
        current_user=anonymous_user,
        session=session,
        case_repo=case_repo,
    )


@router.put(
    "/{case_id}",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "案例更新成功"},
        404: {"description": "案例不存在"},
        409: {"description": "乐观锁冲突（updated_at 不匹配）"},
        422: {"description": "输入校验失败"},
    },
    summary="更新案例",
    description="更新案例字段，采用乐观锁防止并发冲突。",
)
async def update_case_endpoint(
    case_id: str,
    update: CaseUpdate,
    anonymous_user: Dict[str, Any] = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """更新案例端点。"""
    return await _case_service.update_case(
        case_id=case_id,
        update=update,
        current_user=anonymous_user,
        session=session,
        case_repo=case_repo,
    )


@router.post(
    "/{case_id}/submit",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "案例提交审核成功（status=pending_review）"},
        404: {"description": "案例不存在"},
        409: {"description": "状态不是 draft，不允许提交"},
        422: {"description": "四段式字段缺失或 PII 未确认"},
        503: {"description": "服务暂时不可用"},
    },
    summary="提交审核",
    description="将草稿状态的案例提交进入审核流程（draft -> pending_review）。",
)
async def submit_case_endpoint(
    case_id: str,
    pii_confirmed: bool = Query(
        default=False,
        description="用户是否确认已处理 PII 警告",
    ),
    anonymous_user: Dict[str, Any] = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """提交审核端点。"""
    return await _case_service.submit_case(
        case_id=case_id,
        pii_confirmed=pii_confirmed,
        current_user=anonymous_user,
        session=session,
        case_repo=case_repo,
    )


@router.get(
    "/{case_id}",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "返回案例完整详情"},
        404: {"description": "案例不存在"},
    },
    summary="获取案例详情",
    description="获取案例完整详情，返回全部 L1+L2 字段及系统字段。",
)
async def get_case_endpoint(
    case_id: str,
    anonymous_user: Dict[str, Any] = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """获取案例详情端点。"""
    return await _case_service.get_case(
        case_id=case_id,
        current_user=anonymous_user,
        session=session,
        case_repo=case_repo,
    )


@router.get(
    "",
    response_model=PaginatedResponse[CaseListItem],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "返回案例列表（分页）"},
    },
    summary="案例列表查询",
    description=(
        "按状态查询案例列表，支持分页。"
        "默认返回所有案例，按 created_at 倒序排列。"
    ),
)
async def list_cases_endpoint(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="状态筛选（draft/pending_review/approved/rejected）",
    ),
    behavior_type_filter: Optional[str] = Query(
        default=None,
        alias="behavior_type",
        description="行为类型筛选（自伤/攻击/刻板/逃跑/情绪崩溃/其他）",
    ),
    evidence_level: Optional[str] = Query(
        default=None,
        description="循证等级筛选（A/B/C/D）",
    ),
    sort_by: Optional[str] = Query(
        default="latest",
        description="排序方式：latest/evidence/cited/updated",
    ),
    keyword: Optional[str] = Query(
        default=None,
        description="搜索关键词（模糊匹配标题/行为类型/场景）",
    ),
    scope: Optional[str] = Query(
        default="public",
        description="查询范围：public=仅已审核案例，my=当前用户的全部案例",
    ),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=15, ge=1, le=100, description="每页条数"),
    anonymous_user: Dict[str, Any] = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> PaginatedResponse[CaseListItem]:
    """案例列表查询端点。"""
    return await _case_service.list_cases(
        status_filter=status_filter,
        behavior_type_filter=behavior_type_filter,
        evidence_level=evidence_level,
        sort_by=sort_by,
        keyword=keyword,
        page=page,
        page_size=page_size,
        scope=scope,
        current_user=anonymous_user,
        session=session,
        case_repo=case_repo,
    )


__all__ = ["router"]
