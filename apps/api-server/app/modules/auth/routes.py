"""api-server 认证模块 — FastAPI 路由注册。

提供 4 个认证端点：
- POST /api/v1/auth/register — 用户注册
- POST /api/v1/auth/login    — 用户登录
- POST /api/v1/auth/refresh  — Token 续期
- POST /api/v1/auth/logout   — 登出

路由层仅负责请求解析、依赖注入和业务异常 → HTTP 状态码映射，
所有业务逻辑由 AuthService 契约实现处理。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, Response, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import (
    get_auth_service,
    get_db_session,
)
from app.modules.auth.auth_contract import AuthService
from app.modules.auth.exceptions import (
    AuthInternalError,
    DuplicateUserError,
    InvalidCredentialsError,
    PasswordComplexityError,
    RealNameRequiredError,
    TokenInvalidError,
)
from py_schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from py_schemas.security.validation_schemas import ValidationErrorResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ============================================================================
# POST /api/v1/auth/register — 用户注册
# ============================================================================


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "注册成功，返回 user_id"},
        422: {
            "description": "输入校验失败（字段格式/密码复杂度/专家角色必填），"
            "复用 SEC-05 ValidationErrorResponse 格式",
            "model": ValidationErrorResponse,
        },
        409: {
            "description": "用户名或手机号已被注册，"
            "detail.code 精确区分 DUPLICATE_USERNAME / DUPLICATE_PHONE",
        },
        500: {"description": "系统内部错误（密码哈希失败/数据库连接异常等）"},
    },
    summary="用户注册",
    description=(
        "接收用户提交的用户名、密码、角色、手机号和真实姓名，"
        "经三层校验（格式→唯一性→持久化）后创建用户账号。\n\n"
        "**注册成功后不返回 JWT Token**——JWT 签发由 AUTH-02（用户登录）负责。\n"
        "前端收到 201 后应引导用户进入登录页面。"
    ),
)
async def register(
    request: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> RegisterResponse:
    """用户注册端点。

    依赖注入链：
    1. RegisterRequest — FastAPI Body 依赖，自动触发 Pydantic 校验
    2. AsyncSession — 数据库异步会话，请求结束时自动关闭
    3. AuthService — 认证服务契约实现，注入所有子依赖
    """
    try:
        return await auth_service.register(request, session)
    except PasswordComplexityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc
    except RealNameRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except AuthInternalError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.message,
        ) from exc


# ============================================================================
# POST /api/v1/auth/login — 用户登录
# ============================================================================


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "登录成功，返回 TokenResponse"},
        401: {"description": "用户名或密码错误（不区分具体原因）"},
        500: {"description": "系统内部错误（JWT 签发失败等）"},
    },
    summary="用户登录",
    description=(
        "校验用户名和密码，签发 access_token（15 分钟有效）和 "
        "refresh_token（7 天有效）。\n\n"
        "安全约束：不区分\"用户不存在\"和\"密码错误\"——统一返回 401，"
        "防止攻击者通过错误消息差异枚举有效用户名。"
    ),
)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """用户登录端点。

    依赖注入链：
    1. LoginRequest — FastAPI Body 依赖，自动触发 Pydantic 校验
    2. AsyncSession — 数据库异步会话
    3. AuthService — 认证服务契约实现
    """
    try:
        return await auth_service.login(request, session)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except AuthInternalError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.message,
        ) from exc


# ============================================================================
# POST /api/v1/auth/refresh — Token 续期
# ============================================================================


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "续期成功，返回新的 TokenResponse"},
        401: {"description": "Refresh token 无效、过期或已被使用"},
        500: {"description": "系统内部错误（JWT 签发失败等）"},
    },
    summary="Token 续期",
    description=(
        "使用 refresh token 换取新的 access_token + refresh_token 对。\n\n"
        "安全约束：旧 refresh token 的单次使用标记（防重放攻击）"
        "由 Service 层自动完成，路由层无感知。"
    ),
)
async def refresh_token_endpoint(
    request: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Token 续期端点。

    依赖注入链：
    1. RefreshRequest — FastAPI Body 依赖
    2. AsyncSession — 数据库异步会话
    3. AuthService — 认证服务契约实现
    """
    try:
        return await auth_service.refresh_token(request, session)
    except TokenInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except AuthInternalError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.message,
        ) from exc


# ============================================================================
# POST /api/v1/auth/logout — 登出
# ============================================================================


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "登出成功，无响应体"},
    },
    summary="登出",
    description=(
        "使当前 access token 和 refresh token 失效。\n\n"
        "access token 从 Authorization header 提取（Bearer 前缀），"
        "refresh token 从请求体提取。\n"
        "黑名单写入采用 fail-open 降级策略——即使 Redis 不可用也返回 204。"
    ),
)
async def logout(
    authorization: str | None = Header(
        default=None,
        description="Bearer <access_token>",
    ),
    refresh_token: str = Body(
        default="",
        embed=True,
        description="需要失效的 refresh token",
    ),
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    """登出端点。

    接受 Authorization header 中的 access token 和请求体中的 refresh token，
    将两者的 jti 写入黑名单 / 标记已使用。
    采用 fail-open 策略——即使提取 jti 失败或 Redis 写入失败也返回 204。

    Args:
        authorization: Authorization header 值（Bearer <token> 格式）。
        refresh_token: 请求体中的 refresh_token 字段。
        auth_service: 认证服务契约实现。

    Returns:
        204 No Content 空响应。
    """
    # 提取 access token（去除 Bearer 前缀）
    access_token = ""
    if authorization and authorization.startswith("Bearer "):
        access_token = authorization.replace("Bearer ", "", 1)

    await auth_service.logout(access_token, refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
