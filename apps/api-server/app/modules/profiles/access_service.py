"""专业评估与关联管理服务。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from py_db.models.profiles import ProfessionalNote, ProfileAccess
from py_db.repositories.profile_repository import (
    ProfessionalNoteRepository,
    ProfileAccessRepository,
)
from py_db.repositories.user_repository import UserRepository
from py_schemas.enums import AccessStatus
from py_schemas.profiles import (
    ProfessionalNoteCreateRequest,
    ProfessionalNoteResponse,
    ProfileAccessCreateRequest,
    ProfileAccessItem,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.exceptions import (
    AccessNotFoundError,
    DuplicateAccessError,
    EventNotFoundError,
    InviteeNotFoundError,
    ProfileForbiddenError,
)
from app.modules.profiles.guard import ProfileAccessContext


class NoteService:
    """专业评估服务（老师/专家挂载，只读家属内容）。"""

    def __init__(self, note_repo: ProfessionalNoteRepository) -> None:
        self._note_repo = note_repo

    async def create_note(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
        author_id: str,
        author_role: str,
        request: ProfessionalNoteCreateRequest,
    ) -> ProfessionalNoteResponse:
        """挂载专业评估（仅关联老师/专家；仅可挂到本档案的事件）。"""
        if not viewer.can_add_note:
            raise ProfileForbiddenError("仅关联老师/专家可提交专业评估")

        # 事件必须属于该档案（物理隔离校验）
        from py_db.models.profiles import EventLog
        from sqlalchemy import select

        try:
            eid = uuid.UUID(request.event_id)
        except ValueError:
            raise EventNotFoundError() from None
        result = await session.execute(
            select(EventLog).where(
                EventLog.event_id == eid,
                EventLog.profile_id == viewer.profile.profile_id,
            )
        )
        if result.scalars().first() is None:
            raise EventNotFoundError()

        note = ProfessionalNote(
            event_id=eid,
            author_id=uuid.UUID(author_id),
            assessment=request.assessment,
            recommended_action=request.recommended_action,
            evidence_basis=request.evidence_basis,
            function_hypothesis=request.function_hypothesis,
        )
        created = await self._note_repo.create(session, note)
        await session.commit()
        return ProfessionalNoteResponse(
            note_id=str(created.note_id),
            event_id=str(created.event_id),
            author_id=str(created.author_id),
            author_role=author_role,
            assessment=created.assessment,
            recommended_action=created.recommended_action,
            evidence_basis=created.evidence_basis,
            function_hypothesis=created.function_hypothesis,
            created_at=created.created_at.isoformat(),
        )

    async def list_notes_for_event(
        self,
        session: AsyncSession,
        event_id: str,
    ) -> list[ProfessionalNoteResponse]:
        try:
            eid = uuid.UUID(event_id)
        except ValueError:
            return []
        notes = await self._note_repo.list_by_event(session, eid)
        return [
            ProfessionalNoteResponse(
                note_id=str(n.note_id),
                event_id=str(n.event_id),
                author_id=str(n.author_id) if n.author_id else "",
                author_role="",
                assessment=n.assessment,
                recommended_action=n.recommended_action,
                evidence_basis=n.evidence_basis,
                function_hypothesis=n.function_hypothesis,
                created_at=n.created_at.isoformat(),
            )
            for n in notes
        ]


class AccessService:
    """关联管理服务（家属主控）。"""

    def __init__(
        self,
        access_repo: ProfileAccessRepository,
        user_repo: UserRepository,
    ) -> None:
        self._access_repo = access_repo
        self._user_repo = user_repo

    async def invite(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
        owner_id: str,
        request: ProfileAccessCreateRequest,
    ) -> ProfileAccessItem:
        """关联邀请（仅家属；按手机号邀请已注册的对应角色用户）。"""
        if not viewer.can_manage_access:
            raise ProfileForbiddenError("仅家属可管理关联")

        invitee = await self._user_repo.find_by_phone(session, request.invitee_phone)
        if invitee is None:
            raise InviteeNotFoundError()
        # 被邀请人角色须与关联角色一致（teacher/expert/volunteer）
        if invitee.role.value != request.role.value:
            raise InviteeNotFoundError()

        access = ProfileAccess(
            profile_id=viewer.profile.profile_id,
            user_id=invitee.id,
            role=request.role,
            status=AccessStatus.ACTIVE,
            created_by=uuid.UUID(owner_id),
        )
        try:
            created = await self._access_repo.create(session, access)
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise DuplicateAccessError() from exc

        return ProfileAccessItem(
            access_id=str(created.access_id),
            profile_id=str(created.profile_id),
            user_id=str(created.user_id),
            phone=invitee.phone,
            real_name=invitee.real_name,
            role=created.role,
            status=created.status,
            created_at=created.created_at.isoformat(),
        )

    async def list_access(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
    ) -> list[ProfileAccessItem]:
        """档案关联列表（家属视角，含已解除）。"""
        if not viewer.can_manage_access:
            raise ProfileForbiddenError("仅家属可管理关联")
        accesses = await self._access_repo.list_by_profile(session, viewer.profile.profile_id)
        items: list[ProfileAccessItem] = []
        for a in accesses:
            user = await self._user_repo.find_by_id(session, a.user_id)
            items.append(
                ProfileAccessItem(
                    access_id=str(a.access_id),
                    profile_id=str(a.profile_id),
                    user_id=str(a.user_id),
                    phone=user.phone if user else "",
                    real_name=user.real_name if user else None,
                    role=a.role,
                    status=a.status,
                    created_at=a.created_at.isoformat(),
                )
            )
        return items

    async def revoke(
        self,
        session: AsyncSession,
        viewer: ProfileAccessContext,
        access_id: str,
    ) -> None:
        """解除关联（家属单方面，立即生效——被解除方失去全部访问入口）。"""
        if not viewer.can_manage_access:
            raise ProfileForbiddenError("仅家属可管理关联")
        try:
            aid = uuid.UUID(access_id)
        except ValueError:
            raise AccessNotFoundError() from None
        access = await self._access_repo.find_by_id(session, aid)
        if access is None or access.profile_id != viewer.profile.profile_id:
            raise AccessNotFoundError()
        access.status = AccessStatus.REVOKED
        access.revoked_at = datetime.now(timezone.utc)
        await session.commit()


__all__ = ["NoteService", "AccessService"]
