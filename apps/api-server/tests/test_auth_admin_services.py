"""准入审核与邀请码管理服务 — 单元测试（ADR-013 目标态）。

覆盖：
- 准入状态机流转：pending_review → active（通过）/ rejected（驳回含原因）；
  rejected → pending_review（补交重提）；非法流转拒绝
- 邀请码生成（批量/冲突重试）、停用
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.modules.auth.exceptions import (
    InviteCodeNotFoundError,
    ReviewNotFoundError,
    ReviewStateError,
)
from app.modules.auth.invite_codes_service import InviteCodeService
from app.modules.auth.review_service import ReviewService
from py_schemas.auth import InviteCodeCreateRequest, UserRole
from py_schemas.enums import AccountStatus, InviteChannel, InviteCodeStatus

# =============================================================================
# Fixtures
# =============================================================================


def _make_user(**overrides: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "id": uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        "phone": "13800138000",
        "real_name": "张老师",
        "role": UserRole.TEACHER,
        "status": AccountStatus.PENDING_REVIEW,
        "reject_reason": None,
        "created_at": datetime(2026, 8, 4, tzinfo=timezone(timedelta(hours=8))),
    }
    defaults.update(overrides)
    user = MagicMock()
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


@pytest.fixture
def mock_user_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_id = AsyncMock()
    repo.list_by_status_and_roles = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def review_svc(mock_user_repo) -> ReviewService:
    return ReviewService(user_repo=mock_user_repo)


ADMIN_ID = str(uuid.uuid4())
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


# =============================================================================
# 准入审核 — 状态机流转
# =============================================================================


class TestReviewStateMachine:
    @pytest.mark.asyncio
    async def test_approve_pending_to_active(self, review_svc, mock_user_repo, mock_session):
        user = _make_user()
        mock_user_repo.find_by_id.return_value = user
        result = await review_svc.approve(USER_ID, ADMIN_ID, mock_session)
        assert result.status == AccountStatus.ACTIVE
        assert user.status == AccountStatus.ACTIVE
        assert user.reject_reason is None
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_pending_to_rejected_with_reason(self, review_svc, mock_user_repo, mock_session):
        user = _make_user()
        mock_user_repo.find_by_id.return_value = user
        result = await review_svc.reject(USER_ID, "资质材料不清晰", ADMIN_ID, mock_session)
        assert result.status == AccountStatus.REJECTED
        assert user.status == AccountStatus.REJECTED
        assert user.reject_reason == "资质材料不清晰"

    @pytest.mark.asyncio
    async def test_resubmit_rejected_to_pending(self, review_svc, mock_user_repo, mock_session):
        user = _make_user(status=AccountStatus.REJECTED, reject_reason="材料不全")
        mock_user_repo.find_by_id.return_value = user
        result = await review_svc.resubmit(USER_ID, "张老师（更正）", mock_session)
        assert result.status == AccountStatus.PENDING_REVIEW
        assert user.status == AccountStatus.PENDING_REVIEW
        assert user.reject_reason is None
        assert user.real_name == "张老师（更正）"

    @pytest.mark.asyncio
    async def test_approve_active_user_rejected(self, review_svc, mock_user_repo, mock_session):
        """非法流转：active 账号不可再审核。"""
        mock_user_repo.find_by_id.return_value = _make_user(status=AccountStatus.ACTIVE)
        with pytest.raises(ReviewStateError):
            await review_svc.approve(USER_ID, ADMIN_ID, mock_session)

    @pytest.mark.asyncio
    async def test_resubmit_pending_rejected(self, review_svc, mock_user_repo, mock_session):
        """非法流转：pending_review 不可补交重提。"""
        mock_user_repo.find_by_id.return_value = _make_user(status=AccountStatus.PENDING_REVIEW)
        with pytest.raises(ReviewStateError):
            await review_svc.resubmit(USER_ID, None, mock_session)

    @pytest.mark.asyncio
    async def test_target_not_found(self, review_svc, mock_user_repo, mock_session):
        mock_user_repo.find_by_id.return_value = None
        with pytest.raises(ReviewNotFoundError):
            await review_svc.approve(USER_ID, ADMIN_ID, mock_session)

    @pytest.mark.asyncio
    async def test_family_user_not_review_target(self, review_svc, mock_user_repo, mock_session):
        """family 账号不是准入审核目标。"""
        mock_user_repo.find_by_id.return_value = _make_user(role=UserRole.FAMILY)
        with pytest.raises(ReviewNotFoundError):
            await review_svc.approve(USER_ID, ADMIN_ID, mock_session)


class TestReviewList:
    @pytest.mark.asyncio
    async def test_list_pending(self, review_svc, mock_user_repo, mock_session):
        mock_user_repo.list_by_status_and_roles.return_value = [_make_user()]
        result = await review_svc.list_pending(mock_session)
        assert result.total == 1
        assert result.items[0].phone == "13800138000"  # 管理员可见完整手机号
        mock_user_repo.list_by_status_and_roles.assert_awaited_once()


# =============================================================================
# 邀请码管理
# =============================================================================


@pytest.fixture
def mock_invite_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_code = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda s, c: c)
    repo.list_all = AsyncMock(return_value=[])
    repo.revoke = AsyncMock()
    return repo


class TestInviteCodeGenerate:
    @pytest.mark.asyncio
    async def test_generate_single(self, mock_invite_repo, mock_session):
        svc = InviteCodeService(invite_code_repo=mock_invite_repo)
        req = InviteCodeCreateRequest(
            channel=InviteChannel.DEMAND,
            expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        )
        result = await svc.generate(req, ADMIN_ID, mock_session)
        assert len(result.codes) == 1
        code = result.codes[0]
        assert len(code) == 8
        # 剔除易混淆字符
        assert not (set(code) & set("0O1IL"))
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_batch(self, mock_invite_repo, mock_session):
        svc = InviteCodeService(invite_code_repo=mock_invite_repo)
        req = InviteCodeCreateRequest(
            channel=InviteChannel.SUPPLY,
            count=5,
            expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        )
        result = await svc.generate(req, ADMIN_ID, mock_session)
        assert len(result.codes) == 5
        assert len(set(result.codes)) == 5  # 批量生成互不重复

    @pytest.mark.asyncio
    async def test_generate_retry_on_collision(self, mock_invite_repo, mock_session):
        """码冲突时重试生成（首次 find_by_code 命中已有码）。"""
        mock_invite_repo.find_by_code.side_effect = [MagicMock(), None]
        svc = InviteCodeService(invite_code_repo=mock_invite_repo)
        req = InviteCodeCreateRequest(
            channel=InviteChannel.DEMAND,
            expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        )
        result = await svc.generate(req, ADMIN_ID, mock_session)
        assert len(result.codes) == 1
        assert mock_invite_repo.find_by_code.await_count == 2


class TestInviteCodeRevoke:
    @pytest.mark.asyncio
    async def test_revoke_success(self, mock_invite_repo, mock_session):
        mock_invite_repo.revoke.return_value = MagicMock(
            code="ABCD2345",
            channel=InviteChannel.DEMAND,
            max_uses=1,
            used_count=0,
            expires_at=datetime.now(timezone.utc),
            status=InviteCodeStatus.REVOKED,
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
        )
        svc = InviteCodeService(invite_code_repo=mock_invite_repo)
        item = await svc.revoke("ABCD2345", mock_session)
        assert item.status == InviteCodeStatus.REVOKED

    @pytest.mark.asyncio
    async def test_revoke_not_found(self, mock_invite_repo, mock_session):
        mock_invite_repo.revoke.return_value = None
        svc = InviteCodeService(invite_code_repo=mock_invite_repo)
        with pytest.raises(InviteCodeNotFoundError):
            await svc.revoke("MISSING99", mock_session)
