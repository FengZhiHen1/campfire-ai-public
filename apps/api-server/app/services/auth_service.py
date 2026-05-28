"""AUTH-01 用户注册 — register_user() 核心编排。

本模块是用户注册流程的唯一业务编排入口，按落地规范 §1.5 的 7 步流程
顺序执行：Pydantic 校验 → 密码复杂度 → 专家 real_name 必填 →
用户名唯一性 → 手机号唯一性 → 密码哈希 → 数据写入与审计日志。

每步失败即中断流程，返回对应 HTTP 错误响应，不进入后续步骤。
"""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from py_auth.exceptions import HashingError
from py_db.models.auth import User
from py_db.repositories.user_repository import UserRepository
from py_schemas.auth import RegisterRequest, RegisterResponse, UserRole

if TYPE_CHECKING:
    from app.dependencies.auth_dependencies import (
        AuditLogger,
        PasswordHasher,
    )

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_PASSWORD_COMPLEXITY_REGEX: re.Pattern = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$"
)
r"""密码复杂度正则：至少包含一个小写字母、一个大写字母、一个数字，且至少 8 位。

使用正向前瞻断言实现：
- (?=.*[a-z]) — 至少一个小写字母
- (?=.*[A-Z]) — 至少一个大写字母
- (?=.*\d) — 至少一个数字
- .{8,} — 至少 8 个字符
"""

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _audit_log_task(
    user_id: str,
    username: str,
    role: str,
    audit_logger: "AuditLogger",
) -> None:
    """异步审计日志写入任务。

    由 asyncio.create_task() 投递到事件循环执行。
    日志写入失败不阻塞注册流程，但会在回调中记录 warning。

    Args:
        user_id: 新创建用户的 UUID 字符串。
        username: 注册用户名。
        role: 注册角色值。
        audit_logger: AuditLogger 适配器实例。
    """
    try:
        audit_logger.log_user_register(
            user_id=user_id,
            username=username,
            role=role,
        )
    except Exception:
        _logger.warning(
            "audit_log_write_failed",
            extra={
                "user_id": user_id,
                "username": username,
                "role": role,
            },
        )


def _parse_integrity_error(exc: IntegrityError) -> tuple[str, str]:
    """解析 IntegrityError 的 PostgreSQL 约束名，映射为精确错误码。

    仅处理 pgcode == "23505"（唯一约束违反），其他 pgcode 返回通用错误码。
    提取 diag.constraint_name 区分 unique_username 和 unique_phone。

    Args:
        exc: SQLAlchemy IntegrityError 异常。

    Returns:
        (code, message) 元组：
        - ("DUPLICATE_USERNAME", "该用户名已被注册")
        - ("DUPLICATE_PHONE", "该手机号已被注册")
        - ("DUPLICATE_FIELD", "用户名或手机号已被注册")  # 回退
    """
    try:
        orig = exc.orig
        if orig is not None and getattr(orig, "pgcode", None) == "23505":
            constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", "")
            if "username" in constraint_name:
                return ("DUPLICATE_USERNAME", "该用户名已被注册")
            if "phone" in constraint_name:
                return ("DUPLICATE_PHONE", "该手机号已被注册")
        # 无法精确区分时返回通用错误码
        return ("DUPLICATE_FIELD", "用户名或手机号已被注册")
    except Exception as parse_exc:
        _logger.warning(
            "integrity_error_parse_failed",
            extra={"parse_error": str(parse_exc), "original_error": str(exc)},
        )
        return ("DUPLICATE_FIELD", "用户名或手机号已被注册")


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------


async def register_user(
    request: RegisterRequest,
    session: AsyncSession,
    user_repo: UserRepository,
    password_hasher: "PasswordHasher",
    audit_logger: "AuditLogger",
) -> RegisterResponse:
    """用户注册核心编排。

    按落地规范 §1.5 的 7 步流程顺序执行注册逻辑。
    步骤 1（Pydantic 输入校验）由 FastAPI Depends() 在路由层完成，
    本函数从步骤 2 开始执行。

    Args:
        request: Pydantic 校验通过的注册请求。
        session: 活动数据库异步会话。
        user_repo: UserRepository 实例，封装 users 表 CRUD 操作。
        password_hasher: PasswordHasher 适配器，封装 bcrypt 哈希调用。
        audit_logger: AuditLogger 适配器，封装审计日志写入。

    Returns:
        RegisterResponse: 注册成功响应（result="success", user_id=str).

    Raises:
        HTTPException(422): 密码复杂度不足或专家角色缺少 real_name。
        HTTPException(409): 用户名或手机号已被注册。
        HTTPException(500): 密码哈希失败、数据库操作失败或其他内部错误。
    """
    # --- 步骤 2：密码强度校验 ---
    if not _PASSWORD_COMPLEXITY_REGEX.match(request.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "errors": [
                    {
                        "field": "password",
                        "reason": "密码必须同时包含大写字母、小写字母和数字",
                        "constraint": "password_complexity",
                    }
                ]
            },
        )

    # --- 步骤 3：真实姓名条件必填校验 ---
    if request.role == UserRole.EXPERT and request.real_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "errors": [
                    {
                        "field": "real_name",
                        "reason": "专家角色必须填写真实姓名",
                        "constraint": "required_for_expert",
                    }
                ]
            },
        )

    # --- 步骤 4：用户名唯一性检查 ---
    existing_user = await user_repo.find_by_username_lower(
        session, request.username
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_USERNAME",
                "message": "该用户名已被注册",
            },
        )

    # --- 步骤 5：手机号唯一性检查 ---
    existing_phone = await user_repo.find_by_phone(session, request.phone)
    if existing_phone is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_PHONE",
                "message": "该手机号已被注册",
            },
        )

    # --- 步骤 6：密码哈希 ---
    try:
        hashed: str = password_hasher.hash(request.password)
    except HashingError as exc:
        _logger.error(
            "hash_password_failed",
            extra={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="系统繁忙，请稍后重试",
        ) from exc

    # --- 步骤 7：数据写入与审计日志 ---
    user = User(
        username=request.username,
        password_hash=hashed,
        role=request.role,
        phone=request.phone,
        real_name=request.real_name,
    )

    try:
        created_user = await user_repo.create(session, user)
    except IntegrityError as exc:
        code, message = _parse_integrity_error(exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": code,
                "message": message,
            },
        ) from exc
    except Exception as exc:
        _logger.critical(
            "database_insert_failed",
            extra={
                "username": request.username,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="系统繁忙，请稍后重试",
        ) from exc

    # 异步投递审计日志
    user_id_str: str = str(created_user.id)
    asyncio.create_task(
        asyncio.to_thread(
            _audit_log_task,
            user_id_str,
            created_user.username,
            created_user.role.value,
            audit_logger,
        )
    )

    return RegisterResponse(
        result="success",
        user_id=user_id_str,
        message="注册成功",
    )


__all__ = [
    "register_user",
]
