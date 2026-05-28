"""AUTH-01 用户注册 — FastAPI 路由注册。

POST /api/v1/auth/register — 用户注册端点。
接受 RegisterRequest JSON 请求体，经 Pydantic 校验（路由层）、
密码复杂度校验（Service 层）和唯一性检查（Repository 层）后
创建用户账号，返回 201 Created。

Pydantic 校验失败由 SEC-05 自定义异常处理器拦截，
返回 ValidationErrorResponse 格式的 422 响应。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth_dependencies import (
    AuditLogger,
    PasswordHasher,
    get_audit_logger,
    get_db_session,
    get_password_hasher,
    get_user_repository,
)
from app.services.auth_service import register_user
from py_db.repositories.user_repository import UserRepository
from py_schemas.auth import RegisterRequest, RegisterResponse
from py_schemas.security.validation_schemas import ValidationErrorResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    user_repo: UserRepository = Depends(get_user_repository),
    password_hasher: PasswordHasher = Depends(get_password_hasher),
    audit_logger: AuditLogger = Depends(get_audit_logger),
) -> RegisterResponse:
    """用户注册端点。

    依赖注入链：
    1. RegisterRequest — FastAPI Body 依赖，自动触发 Pydantic 校验
    2. AsyncSession — 数据库异步会话，请求结束时自动关闭
    3. UserRepository — users 表 CRUD 操作
    4. PasswordHasher — bcrypt 密码哈希适配器
    5. AuditLogger — 审计日志写入适配器
    """
    return await register_user(
        request=request,
        session=session,
        user_repo=user_repo,
        password_hasher=password_hasher,
        audit_logger=audit_logger,
    )


__all__ = ["router"]
