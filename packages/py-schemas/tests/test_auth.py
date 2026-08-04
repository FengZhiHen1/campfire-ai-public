"""认证体系重构（ADR-013）— Pydantic Schema 契约单元测试。

覆盖目标态认证契约：
- UserRole 六角色枚举（补 volunteer，废除 level 数值继承）
- 注册/登录/刷新/登出/me DTO（手机号登录、邀请码、角色、real_name 条件必填）
- 准入审核 DTO（审核列表/通过/驳回含原因/补交材料）
- 邀请码管理 DTO（生成/列表/停用）
- 认证相关枚举（账号状态/邀请码状态/邀请码渠道/凭证类型）
"""

from __future__ import annotations

import pytest
from py_schemas.auth import (
    CHANNEL_ALLOWED_ROLES,
    InviteCodeCreateRequest,
    InviteCodeCreateResponse,
    InviteCodeItem,
    InviteCodeListResponse,
    LoginRequest,
    MeResponse,
    PermissionDeniedResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ReviewApproveResponse,
    ReviewListItem,
    ReviewListResponse,
    ReviewRejectRequest,
    ReviewResubmitRequest,
    TokenResponse,
    UserRole,
)
from py_schemas.enums import (
    AccountStatus,
    CredentialType,
    InviteChannel,
    InviteCodeStatus,
)
from pydantic import ValidationError

# ===========================================================================
# UserRole — 六角色枚举
# ===========================================================================


class TestUserRole:
    def test_all_six_roles_exist(self):
        assert UserRole.FAMILY == "family"
        assert UserRole.VOLUNTEER == "volunteer"
        assert UserRole.TEACHER == "teacher"
        assert UserRole.EXPERT == "expert"
        assert UserRole.ADMIN == "admin"
        assert UserRole.MAINTAINER == "maintainer"

    def test_member_count(self):
        assert len(UserRole) == 6

    def test_no_level_attribute(self):
        """数值层级继承已废除（ADR-013），角色不再有 level 属性。"""
        assert not hasattr(UserRole.FAMILY, "level")

    def test_display_names(self):
        assert UserRole.FAMILY.display_name == "家属"
        assert UserRole.VOLUNTEER.display_name == "志愿者"
        assert UserRole.TEACHER.display_name == "老师"
        assert UserRole.EXPERT.display_name == "专家"
        assert UserRole.ADMIN.display_name == "管理员"
        assert UserRole.MAINTAINER.display_name == "维护人员"


# ===========================================================================
# 认证枚举
# ===========================================================================


class TestAuthEnums:
    def test_account_status_values(self):
        assert AccountStatus.ACTIVE == "active"
        assert AccountStatus.PENDING_REVIEW == "pending_review"
        assert AccountStatus.REJECTED == "rejected"
        assert AccountStatus.DISABLED == "disabled"
        assert len(AccountStatus) == 4

    def test_invite_code_status_values(self):
        assert InviteCodeStatus.ACTIVE == "active"
        assert InviteCodeStatus.REVOKED == "revoked"
        assert len(InviteCodeStatus) == 2

    def test_invite_channel_values(self):
        assert InviteChannel.DEMAND == "demand"
        assert InviteChannel.SUPPLY == "supply"
        assert len(InviteChannel) == 2

    def test_credential_type_values(self):
        assert CredentialType.PASSWORD == "password"
        assert CredentialType.WECHAT == "wechat"


class TestChannelAllowedRoles:
    """邀请码 channel → 可注册角色的约束映射（认证与访问 §4.1）。"""

    def test_demand_channel_allows_family_and_volunteer(self):
        assert CHANNEL_ALLOWED_ROLES[InviteChannel.DEMAND] == frozenset({UserRole.FAMILY, UserRole.VOLUNTEER})

    def test_supply_channel_allows_teacher_and_expert(self):
        assert CHANNEL_ALLOWED_ROLES[InviteChannel.SUPPLY] == frozenset({UserRole.TEACHER, UserRole.EXPERT})


# ===========================================================================
# RegisterRequest — 注册（手机号 + 邀请码 + 角色）
# ===========================================================================


def _valid_register_data(**overrides):
    data = {
        "phone": "13800138000",
        "password": "Abc12345",
        "invite_code": "ABCD2345",
        "role": "family",
    }
    data.update(overrides)
    return data


class TestRegisterRequest:
    def test_valid_family(self):
        req = RegisterRequest(**_valid_register_data())
        assert req.phone == "13800138000"
        assert req.role == UserRole.FAMILY
        assert req.real_name is None

    def test_valid_volunteer(self):
        req = RegisterRequest(**_valid_register_data(role="volunteer", invite_code="DEMAND1234"))
        assert req.role == UserRole.VOLUNTEER

    def test_valid_teacher_with_real_name(self):
        req = RegisterRequest(**_valid_register_data(role="teacher", real_name="张老师"))
        assert req.role == UserRole.TEACHER
        assert req.real_name == "张老师"

    def test_valid_expert_with_real_name(self):
        req = RegisterRequest(**_valid_register_data(role="expert", real_name="王专家"))
        assert req.role == UserRole.EXPERT

    def test_admin_not_registrable(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(role="admin"))

    def test_maintainer_not_registrable(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(role="maintainer"))

    def test_username_field_abolished(self):
        """username 字段已废除——extra='forbid' 拒绝携带。"""
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(username="legacy_user"))

    def test_invite_code_required(self):
        data = _valid_register_data()
        del data["invite_code"]
        with pytest.raises(ValidationError):
            RegisterRequest(**data)

    def test_phone_pattern(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(phone="12345678901"))
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(phone="1380013800"))

    def test_password_min_length(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(password="Ab1"))

    def test_real_name_length_bound(self):
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(role="teacher", real_name="张"))
        with pytest.raises(ValidationError):
            RegisterRequest(**_valid_register_data(role="teacher", real_name="张" * 21))


class TestRegisterResponse:
    def test_success_payload(self):
        resp = RegisterResponse(user_id="550e8400-e29b-41d4-a716-446655440000")
        assert resp.result == "success"
        assert resp.status == AccountStatus.ACTIVE

    def test_pending_review_status_for_expert(self):
        resp = RegisterResponse(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            status=AccountStatus.PENDING_REVIEW,
            message="注册成功，等待管理员审核",
        )
        assert resp.status == AccountStatus.PENDING_REVIEW


# ===========================================================================
# Login / Token / Refresh
# ===========================================================================


class TestLoginRequest:
    def test_valid(self):
        req = LoginRequest(phone="13800138000", password="Abc12345")
        assert req.phone == "13800138000"

    def test_username_abolished(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="testuser", password="Abc12345")

    def test_phone_pattern_enforced(self):
        with pytest.raises(ValidationError):
            LoginRequest(phone="not-a-phone", password="Abc12345")


class TestTokenResponse:
    def test_defaults(self):
        resp = TokenResponse(access_token="a", refresh_token="r")
        assert resp.token_type == "Bearer"


class TestRefreshRequest:
    def test_valid(self):
        req = RefreshRequest(refresh_token="token")
        assert req.refresh_token == "token"


class TestMeResponse:
    def test_payload(self):
        resp = MeResponse(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            phone="13800138000",
            real_name="张老师",
            role=UserRole.TEACHER,
            status=AccountStatus.ACTIVE,
        )
        assert resp.role == UserRole.TEACHER
        assert resp.status == AccountStatus.ACTIVE

    def test_real_name_optional(self):
        resp = MeResponse(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            phone="13800138000",
            real_name=None,
            role=UserRole.FAMILY,
            status=AccountStatus.ACTIVE,
        )
        assert resp.real_name is None

    def test_reject_reason_default_none(self):
        resp = MeResponse(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            phone="13800138000",
            real_name="张老师",
            role=UserRole.TEACHER,
            status=AccountStatus.ACTIVE,
        )
        assert resp.reject_reason is None

    def test_rejected_with_reason(self):
        resp = MeResponse(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            phone="13800138000",
            real_name="张老师",
            role=UserRole.TEACHER,
            status=AccountStatus.REJECTED,
            reject_reason="资质材料不清晰",
        )
        assert resp.reject_reason == "资质材料不清晰"


# ===========================================================================
# 准入审核 DTO
# ===========================================================================


class TestReviewDtos:
    def test_review_list_item(self):
        item = ReviewListItem(
            user_id="550e8400-e29b-41d4-a716-446655440000",
            phone="13800138000",
            real_name="张老师",
            role=UserRole.TEACHER,
            status=AccountStatus.PENDING_REVIEW,
            reject_reason=None,
            created_at="2026-08-04T10:00:00+08:00",
        )
        assert item.status == AccountStatus.PENDING_REVIEW

    def test_review_list_response(self):
        resp = ReviewListResponse(items=[], total=0)
        assert resp.total == 0

    def test_reject_request_reason_required(self):
        with pytest.raises(ValidationError):
            ReviewRejectRequest()
        req = ReviewRejectRequest(reason="资质材料不清晰")
        assert req.reason == "资质材料不清晰"

    def test_resubmit_request_optional_real_name(self):
        req = ReviewResubmitRequest()
        assert req.real_name is None
        req2 = ReviewResubmitRequest(real_name="张老师")
        assert req2.real_name == "张老师"

    def test_approve_response(self):
        resp = ReviewApproveResponse(user_id="u-1", status=AccountStatus.ACTIVE)
        assert resp.status == AccountStatus.ACTIVE


# ===========================================================================
# 邀请码管理 DTO
# ===========================================================================


class TestInviteCodeDtos:
    def test_create_request_defaults(self):
        req = InviteCodeCreateRequest(
            channel=InviteChannel.DEMAND,
            expires_at="2026-09-01T00:00:00+08:00",
        )
        assert req.max_uses == 1
        assert req.count == 1

    def test_create_request_batch(self):
        req = InviteCodeCreateRequest(
            channel=InviteChannel.SUPPLY,
            max_uses=1,
            count=10,
            expires_at="2026-09-01T00:00:00+08:00",
        )
        assert req.count == 10

    def test_create_request_invalid_max_uses(self):
        with pytest.raises(ValidationError):
            InviteCodeCreateRequest(
                channel=InviteChannel.DEMAND,
                max_uses=0,
                expires_at="2026-09-01T00:00:00+08:00",
            )

    def test_create_request_invalid_count(self):
        with pytest.raises(ValidationError):
            InviteCodeCreateRequest(
                channel=InviteChannel.DEMAND,
                count=0,
                expires_at="2026-09-01T00:00:00+08:00",
            )

    def test_create_response(self):
        resp = InviteCodeCreateResponse(codes=["ABCD2345", "EFGH6789"])
        assert len(resp.codes) == 2

    def test_invite_code_item(self):
        item = InviteCodeItem(
            code="ABCD2345",
            channel=InviteChannel.DEMAND,
            max_uses=1,
            used_count=0,
            expires_at="2026-09-01T00:00:00+08:00",
            status=InviteCodeStatus.ACTIVE,
            created_by="550e8400-e29b-41d4-a716-446655440000",
            created_at="2026-08-04T10:00:00+08:00",
        )
        assert item.status == InviteCodeStatus.ACTIVE

    def test_list_response(self):
        resp = InviteCodeListResponse(items=[], total=0)
        assert resp.total == 0


# ===========================================================================
# PermissionDeniedResponse（沿用）
# ===========================================================================


class TestPermissionDeniedResponse:
    def test_detail_only(self):
        resp = PermissionDeniedResponse(detail="当前角色无权执行此操作")
        assert resp.detail
        assert set(resp.model_dump().keys()) == {"detail"}
