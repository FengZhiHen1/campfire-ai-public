"""api-server 认证模块 — FastAPI 路由（ADR-013 目标态）。

公开端点：
- POST /api/v1/auth/register — 用户注册（邀请码 + 准入落态）
- POST /api/v1/auth/login    — 用户登录（手机号 + 密码）
- POST /api/v1/auth/refresh  — Token 续期（轮换 + 家族语义）
- POST /api/v1/auth/logout   — 登出（access 黑名单 + 家族吊销）

认证端点：
- GET  /api/v1/auth/me       — 当前用户信息
- POST /api/v1/auth/reviews/{user_id}/resubmit — 驳回后补交材料重提（本人）

管理端点（admin）：
- POST /api/v1/auth/invite-codes             — 生成邀请码（支持批量）
- GET  /api/v1/auth/invite-codes             — 邀请码列表
- POST /api/v1/auth/invite-codes/{code}/revoke — 停用邀请码
- GET  /api/v1/auth/reviews                  — 待审列表
- POST /api/v1/auth/reviews/{user_id}/approve — 审核通过
- POST /api/v1/auth/reviews/{user_id}/reject  — 审核驳回（含原因）

路由层仅负责请求解析、依赖注入和业务异常 → HTTP 状态码映射。
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Body, Depends, Header, Response, status
from fastapi.exceptions import HTTPException
from py_schemas.auth import (
    InviteCodeCreateRequest,
    InviteCodeCreateResponse,
    InviteCodeItem,
    InviteCodeListResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ReviewApproveResponse,
    ReviewListResponse,
    ReviewRejectRequest,
    ReviewResubmitRequest,
    TokenResponse,
    UserRole,
)
from py_schemas.security.validation_schemas import ValidationErrorResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import (
    CurrentUser,
    get_auth_service,
    get_current_user,
    get_db_session,
    get_invite_code_service,
    get_review_service,
    require_roles,
)
from app.modules.auth.auth_contract import AuthService
from app.modules.auth.exceptions import (
    AccountDisabledError,
    AuthInternalError,
    AuthServiceError,
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidInviteCodeError,
    InviteChannelMismatchError,
    InviteCodeNotFoundError,
    PasswordComplexityError,
    RealNameRequiredError,
    ReviewNotFoundError,
    ReviewStateError,
    TokenInvalidError,
)
from app.modules.auth.invite_codes_service import InviteCodeService
from app.modules.auth.review_service import ReviewService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# 业务异常 → HTTP 状态码映射表
# ---------------------------------------------------------------------------

_EXCEPTION_STATUS_MAP: dict[type[AuthServiceError], int] = {
    PasswordComplexityError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RealNameRequiredError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidInviteCodeError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InviteChannelMismatchError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    DuplicateUserError: status.HTTP_409_CONFLICT,
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
    TokenInvalidError: status.HTTP_401_UNAUTHORIZED,
    AccountDisabledError: status.HTTP_403_FORBIDDEN,
    ReviewNotFoundError: status.HTTP_404_NOT_FOUND,
    InviteCodeNotFoundError: status.HTTP_404_NOT_FOUND,
    ReviewStateError: status.HTTP_409_CONFLICT,
    AuthInternalError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def _build_error_detail(exc: AuthServiceError) -> dict[str, object]:
    """从业务异常构建 HTTP 响应 detail 字典。"""
    result: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.detail:
        result.update(exc.detail)
    return result


def _raise_http(exc: AuthServiceError) -> NoReturn:
    """将 AuthServiceError 子类映射为 HTTPException 并抛出。"""
    http_status = _EXCEPTION_STATUS_MAP.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    raise HTTPException(status_code=http_status, detail=_build_error_detail(exc))


# ============================================================================
# POST /api/v1/auth/register — 用户注册
# ============================================================================


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "注册成功，返回 user_id 与账号落态"},
        422: {
            "description": "输入校验失败（字段格式/密码复杂度/real_name 必填/邀请码无效/渠道约束）",
            "model": ValidationErrorResponse,
        },
        409: {"description": "手机号已被注册"},
        500: {"description": "系统内部错误"},
    },
    summary="用户注册",
    description=(
        "手机号 + 密码 + 邀请码 + 角色注册。邀请码 channel 约束可注册角色"
        "（demand→家属/志愿者，supply→老师/专家）；老师/专家注册后进入"
        " pending_review 等待管理员审核。注册不自动登录，引导至登录页。"
    ),
)
async def register(
    request: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> RegisterResponse:
    try:
        return await auth_service.register(request, session)
    except AuthServiceError as exc:
        _raise_http(exc)


# ============================================================================
# POST /api/v1/auth/login — 用户登录
# ============================================================================


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "登录成功，返回 TokenResponse"},
        401: {"description": "手机号或密码错误（不区分具体原因，防枚举）"},
        403: {"description": "账号已被禁用"},
        500: {"description": "系统内部错误"},
    },
    summary="用户登录",
    description=(
        "手机号 + 密码校验，按账号状态放行（disabled 拒签），"
        "签发新 Token 家族（access 15 分钟 / refresh 7 天单次使用）。"
    ),
)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        return await auth_service.login(request, session)
    except AuthServiceError as exc:
        _raise_http(exc)


# ============================================================================
# POST /api/v1/auth/refresh — Token 续期
# ============================================================================


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "续期成功，返回新的 TokenResponse（家族内轮换）"},
        401: {"description": "Refresh token 无效/过期/已复用/家族已吊销"},
        403: {"description": "账号已被禁用"},
        500: {"description": "系统内部错误"},
    },
    summary="Token 续期",
    description=(
        "refresh token 单次使用 + 轮换：旧 token 复用触发全家族吊销；"
        "新对以 DB 最新 role/status 在同一家族内签发。"
    ),
)
async def refresh_token_endpoint(
    request: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        return await auth_service.refresh_token(request, session)
    except AuthServiceError as exc:
        _raise_http(exc)


# ============================================================================
# POST /api/v1/auth/logout — 登出
# ============================================================================


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={204: {"description": "登出成功，无响应体"}},
    summary="登出",
    description="access token jti 入黑名单 + refresh 家族吊销；Redis 故障 fail-open 返回 204。",
)
async def logout(
    authorization: str | None = Header(default=None, description="Bearer <access_token>"),
    refresh_token_body: str = Body(default="", embed=True, alias="refresh_token"),
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    access_token = ""
    if authorization and authorization.startswith("Bearer "):
        access_token = authorization.replace("Bearer ", "", 1)

    await auth_service.logout(access_token, refresh_token_body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================================
# GET /api/v1/auth/me — 当前用户信息
# ============================================================================


@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "成功返回当前用户信息"},
        401: {"description": "未登录或凭证无效"},
    },
    summary="获取当前用户信息",
    description="返回当前认证用户的 user_id/phone/real_name/role/status（本人手机号完整可见）。",
)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> MeResponse:
    try:
        return await auth_service.get_me(current_user.user_id, session)
    except AuthServiceError as exc:
        _raise_http(exc)


# ============================================================================
# 邀请码管理（admin）
# ============================================================================


@router.post(
    "/invite-codes",
    response_model=InviteCodeCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "生成成功，返回邀请码列表"},
        401: {"description": "未登录"},
        403: {"description": "非管理员"},
    },
    summary="生成邀请码（admin）",
    description="按渠道生成邀请码；count>1 时批量生成单次码（机构邀请场景）。",
)
async def create_invite_codes(
    request: InviteCodeCreateRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    invite_code_service: InviteCodeService = Depends(get_invite_code_service),
) -> InviteCodeCreateResponse:
    try:
        return await invite_code_service.generate(request, current_user.user_id, session)
    except AuthServiceError as exc:
        _raise_http(exc)


@router.get(
    "/invite-codes",
    response_model=InviteCodeListResponse,
    status_code=status.HTTP_200_OK,
    summary="邀请码列表（admin）",
)
async def list_invite_codes(
    _current_user: CurrentUser = Depends(require_roles(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    invite_code_service: InviteCodeService = Depends(get_invite_code_service),
) -> InviteCodeListResponse:
    return await invite_code_service.list_codes(session)


@router.post(
    "/invite-codes/{code}/revoke",
    response_model=InviteCodeItem,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "停用成功"},
        404: {"description": "邀请码不存在"},
    },
    summary="停用邀请码（admin）",
)
async def revoke_invite_code(
    code: str,
    _current_user: CurrentUser = Depends(require_roles(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    invite_code_service: InviteCodeService = Depends(get_invite_code_service),
) -> InviteCodeItem:
    try:
        return await invite_code_service.revoke(code, session)
    except AuthServiceError as exc:
        _raise_http(exc)


# ============================================================================
# 准入审核（admin + 本人重提）
# ============================================================================


@router.get(
    "/reviews",
    response_model=ReviewListResponse,
    status_code=status.HTTP_200_OK,
    summary="待审列表（admin）",
    description="pending_review 状态的 teacher/expert 账号，按注册时间升序。",
)
async def list_reviews(
    _current_user: CurrentUser = Depends(require_roles(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewListResponse:
    return await review_service.list_pending(session)


@router.post(
    "/reviews/{user_id}/approve",
    response_model=ReviewApproveResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "审核通过，账号置为 active"},
        404: {"description": "审核目标不存在"},
        409: {"description": "当前状态不允许审核操作"},
    },
    summary="准入审核通过（admin）",
)
async def approve_review(
    user_id: str,
    current_user: CurrentUser = Depends(require_roles(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewApproveResponse:
    try:
        return await review_service.approve(user_id, current_user.user_id, session)
    except AuthServiceError as exc:
        _raise_http(exc)


@router.post(
    "/reviews/{user_id}/reject",
    response_model=ReviewApproveResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "已驳回，账号置为 rejected 并记录原因"},
        404: {"description": "审核目标不存在"},
        409: {"description": "当前状态不允许审核操作"},
        422: {"description": "驳回原因缺失"},
    },
    summary="准入审核驳回（admin）",
)
async def reject_review(
    user_id: str,
    request: ReviewRejectRequest,
    current_user: CurrentUser = Depends(require_roles(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewApproveResponse:
    try:
        return await review_service.reject(user_id, request.reason, current_user.user_id, session)
    except AuthServiceError as exc:
        _raise_http(exc)


@router.post(
    "/reviews/{user_id}/resubmit",
    response_model=ReviewApproveResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "已重新提交，账号回到 pending_review"},
        403: {"description": "仅本人可补交材料"},
        404: {"description": "审核目标不存在"},
        409: {"description": "当前状态不允许重提"},
    },
    summary="驳回后补交材料重提（本人）",
    description="rejected 用户补交材料（可选更正 real_name）后重新进入待审队列；仅本人可操作。",
)
async def resubmit_review(
    user_id: str,
    request: ReviewResubmitRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewApproveResponse:
    if current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="仅本人可补交材料")
    try:
        return await review_service.resubmit(user_id, request.real_name, session)
    except AuthServiceError as exc:
        _raise_http(exc)


__all__ = ["router"]
