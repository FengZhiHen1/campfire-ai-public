"""CASE-01 案例录入管理 — FastAPI 路由注册。

6 个端点：
- POST /api/v1/cases — 创建案例草稿
- PUT /api/v1/cases/{case_id} — 更新案例
- POST /api/v1/cases/{case_id}/submit — 提交审核
- GET /api/v1/cases/{case_id} — 获取案例详情
- GET /api/v1/cases — 案例列表查询
- POST /api/v1/cases/pii-check — PII 检测

所有端点通过 Depends 链进行角色准入校验。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth_dependencies import (
    get_case_repository,
    get_db_session,
)
from app.services.case_service import (
    create_case,
    detect_pii_endpoint,
    get_case,
    list_cases,
    submit_case,
    update_case,
)
from py_auth.dependencies import get_current_user
from py_auth.rbac import require_role
from py_db.repositories.case_repository import CaseRepository
from py_schemas.auth import UserRole
from py_schemas.cases import (
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseUpdate,
    PaginatedResponse,
    PiiDetectionResult,
)
from py_schemas.security.validation_schemas import ValidationErrorResponse

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "案例草稿创建成功（status=draft）"},
        403: {"description": "角色权限不足（仅老师/专家可创建）"},
        422: {
            "description": "输入校验失败（字段格式/四段式缺失）",
            "model": ValidationErrorResponse,
        },
        503: {"description": "服务暂时不可用（数据库写入失败）"},
    },
    summary="创建案例草稿",
    description=(
        "创建案例草稿，初始状态为 draft，仅对撰写者本人可见。\n\n"
        "新建时执行四段式字段完整性校验和 PII 检测。"
        "检测到 PII 时不阻断，在响应中返回 pii_warnings 列表供前端展示。"
    ),
)
async def create_case_endpoint(
    request: CaseCreateRequest = Depends(),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """创建案例草稿端点。

    依赖注入链：
    1. CaseCreateRequest — Pydantic 校验
    2. get_current_user — JWT 解析
    3. require_role — 角色校验（老师/专家）
    4. get_db_session — 数据库会话
    5. get_case_repository — CaseRepository 实例
    """
    return await create_case(
        request=request,
        current_user=current_user,
        session=session,
        case_repo=case_repo,
    )


@router.put(
    "/{case_id}",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "案例更新成功"},
        403: {"description": "角色权限不足"},
        404: {"description": "案例不存在"},
        409: {"description": "乐观锁冲突（updated_at 不匹配）"},
        422: {"description": "输入校验失败"},
    },
    summary="更新案例",
    description=(
        "更新案例字段，采用乐观锁（updated_at 比对）防止并发冲突。\n\n"
        "编辑 pending_review 或 rejected 状态的案例时自动重置为 draft。"
    ),
)
async def update_case_endpoint(
    case_id: str,
    update: CaseUpdate = Depends(),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """更新案例端点。"""
    return await update_case(
        case_id=case_id,
        update=update,
        current_user=current_user,
        session=session,
        case_repo=case_repo,
    )


@router.post(
    "/{case_id}/submit",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "案例提交审核成功（status=pending_review）"},
        403: {"description": "角色权限不足"},
        404: {"description": "案例不存在"},
        409: {"description": "状态不是 draft，不允许提交"},
        422: {"description": "四段式字段缺失或 PII 未确认"},
        503: {"description": "服务暂时不可用"},
    },
    summary="提交审核",
    description=(
        "将草稿状态的案例提交进入审核流程（draft -> pending_review）。\n"
        "提交前执行完整性校验、PII 检测和 EBP 一致性检测。"
    ),
)
async def submit_case_endpoint(
    case_id: str,
    pii_confirmed: bool = Query(
        default=False,
        description="用户是否确认已处理 PII 警告",
    ),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """提交审核端点。"""
    return await submit_case(
        case_id=case_id,
        pii_confirmed=pii_confirmed,
        current_user=current_user,
        session=session,
        case_repo=case_repo,
    )


@router.get(
    "/{case_id}",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "返回案例完整详情"},
        403: {"description": "角色权限不足"},
        404: {"description": "案例不存在"},
    },
    summary="获取案例详情",
    description="获取案例完整详情，返回全部 L1+L2 字段及系统字段。",
)
async def get_case_endpoint(
    case_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> CaseResponse:
    """获取案例详情端点。"""
    return await get_case(
        case_id=case_id,
        session=session,
        case_repo=case_repo,
    )


@router.get(
    "",
    response_model=PaginatedResponse[CaseListItem],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "返回案例列表（分页）"},
        403: {"description": "角色权限不足"},
    },
    summary="案例列表查询",
    description=(
        "按状态和作者查询案例列表，支持分页。\n"
        "默认返回当前用户的所有案例，按 created_at 倒序排列。"
    ),
)
async def list_cases_endpoint(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="状态筛选（draft/pending_review/rejected）",
    ),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=15, ge=1, le=100, description="每页条数"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
) -> PaginatedResponse[CaseListItem]:
    """案例列表查询端点。"""
    return await list_cases(
        status_filter=status_filter,
        page=page,
        page_size=page_size,
        current_user=current_user,
        session=session,
        case_repo=case_repo,
    )


@router.post(
    "/pii-check",
    response_model=PiiDetectionResult,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "PII 检测完成"},
        403: {"description": "角色权限不足"},
    },
    summary="PII 检测",
    description=(
        "对叙事文本执行 PII 检测。检测范围：真实姓名、手机号码、"
        "身份证号、家庭住址、学校名称。\n"
        "此端点为提示性辅助功能，不强制阻断。"
    ),
)
async def detect_pii_endpoint_route(
    narrative: str = Body(
        ..., embed=True, description="待检测的叙事文本"
    ),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.TEACHER)),
) -> PiiDetectionResult:
    """PII 检测端点。"""
    return await detect_pii_endpoint(narrative=narrative)


__all__ = ["router"]
