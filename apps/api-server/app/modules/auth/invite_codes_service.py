"""api-server 认证模块 — 邀请码管理服务（admin）。

机制事实源：docs/技术设计/机制/认证与访问.md §4.1。
- 8-12 位可读码（字母数字，剔除易混淆字符）
- channel 约束可注册角色；max_uses 默认 1；机构批量按人数生成单次码
- 生成/列表/停用（revoke）
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any

from py_db.models.auth import InviteCode
from py_logger import logger
from py_schemas.auth import (
    InviteCodeCreateRequest,
    InviteCodeCreateResponse,
    InviteCodeItem,
    InviteCodeListResponse,
)
from py_schemas.enums import InviteCodeStatus

from app.modules.auth.exceptions import AuthInternalError, InviteCodeNotFoundError

# 可读码字符集：剔除易混淆字符 0/O/1/I/L（认证与访问 §4.1）
_INVITE_CODE_ALPHABET: str = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LENGTH: int = 8
_MAX_GENERATE_ATTEMPTS: int = 10


def _generate_code() -> str:
    """生成 8 位可读邀请码（密码学安全随机）。"""
    return "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_INVITE_CODE_LENGTH))


def _to_item(code: InviteCode) -> InviteCodeItem:
    """ORM → DTO 映射。"""
    return InviteCodeItem(
        code=code.code,
        channel=code.channel,
        max_uses=code.max_uses,
        used_count=code.used_count,
        expires_at=code.expires_at.isoformat(),
        status=code.status,
        created_by=str(code.created_by),
        created_at=code.created_at.isoformat(),
    )


class InviteCodeService:
    """邀请码管理服务（admin 平台管理能力域）。

    依赖注入：InviteCodeRepository（py_db）。
    事务边界：本服务内方法显式 commit/rollback。
    """

    def __init__(self, invite_code_repo: Any) -> None:
        self._invite_code_repo = invite_code_repo

    async def generate(
        self,
        request: InviteCodeCreateRequest,
        admin_user_id: str,
        session: Any,
    ) -> InviteCodeCreateResponse:
        """生成邀请码（支持批量——机构邀请按人数生成单次码）。

        码冲突时重新生成（8 位码空间 32^8，冲突概率极低，重试上限 10 次）。
        """
        try:
            expires_at = datetime.fromisoformat(request.expires_at)
        except ValueError as exc:
            raise AuthInternalError("过期时间格式非法") from exc

        created: list[str] = []
        try:
            for _ in range(request.count):
                code_value = await self._generate_unique_code(session)
                invite = InviteCode(
                    code=code_value,
                    channel=request.channel,
                    max_uses=request.max_uses,
                    used_count=0,
                    expires_at=expires_at,
                    status=InviteCodeStatus.ACTIVE,
                    created_by=uuid.UUID(admin_user_id),
                )
                await self._invite_code_repo.create(session, invite)
                created.append(code_value)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(
                service="api-server",
                message="invite_code_generate_failed",
                extra={"error": str(exc)},
            )
            raise AuthInternalError("邀请码生成失败") from exc

        logger.critical(
            service="api-server",
            message="邀请码生成",
            op_type="INVITE_CODE_GENERATE",
            extra={
                "admin_user_id": admin_user_id,
                "channel": request.channel.value,
                "count": len(created),
                "max_uses": request.max_uses,
            },
        )
        return InviteCodeCreateResponse(codes=created)

    async def list_codes(self, session: Any) -> InviteCodeListResponse:
        """邀请码列表（按生成时间倒序）。"""
        codes = await self._invite_code_repo.list_all(session)
        items = [_to_item(c) for c in codes]
        return InviteCodeListResponse(items=items, total=len(items))

    async def revoke(self, code: str, session: Any) -> InviteCodeItem:
        """停用邀请码（active → revoked）。不存在时抛 InviteCodeNotFoundError。"""
        revoked = await self._invite_code_repo.revoke(session, code)
        if revoked is None:
            raise InviteCodeNotFoundError()
        await session.commit()
        logger.critical(
            service="api-server",
            message="邀请码停用",
            op_type="INVITE_CODE_REVOKE",
            extra={"code": code},
        )
        return _to_item(revoked)

    async def _generate_unique_code(self, session: Any) -> str:
        """生成不重复的邀请码（冲突重试，上限 10 次）。"""
        for _ in range(_MAX_GENERATE_ATTEMPTS):
            candidate = _generate_code()
            if await self._invite_code_repo.find_by_code(session, candidate) is None:
                return candidate
        raise AuthInternalError("邀请码生成冲突超限")


__all__ = ["InviteCodeService"]
