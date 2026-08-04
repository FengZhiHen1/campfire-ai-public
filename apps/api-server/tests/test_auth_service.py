"""auth 模块 — ADR-013 目标态测试套件。

覆盖阶段 S1 任务 T1.4 的全部服务编排语义：
- 注册：邀请码预检/渠道约束/原子消费、手机号唯一、密码复杂度、
  teacher/expert real_name 必填与 pending_review 落态
- 登录：手机号+密码统一 401 防枚举、disabled 拒签、pending_review 放行
- 刷新：轮换 + 家族吊销检查 + 复用检测（命中吊销全家族）
- 登出：access 黑名单 + 家族吊销
- me：当前用户信息
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.modules.auth.auth_service import AuthServiceImpl
from app.modules.auth.exceptions import (
    AccountDisabledError,
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidInviteCodeError,
    InviteChannelMismatchError,
    PasswordComplexityError,
    RealNameRequiredError,
    TokenInvalidError,
)
from py_schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserRole,
)
from py_schemas.enums import AccountStatus, CredentialType, InviteChannel, InviteCodeStatus

# =============================================================================
# 工具与 Fixtures
# =============================================================================


def _make_jwt(payload: dict[str, Any]) -> str:
    """构造三段式 JWT 字符串（无签名）。"""
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header_b64}.{payload_b64}.fake_sig"


def _make_user(**overrides: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "id": uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        "phone": "13800138000",
        "real_name": None,
        "role": UserRole.FAMILY,
        "status": AccountStatus.ACTIVE,
        "reject_reason": None,
    }
    defaults.update(overrides)
    user = MagicMock()
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _make_credential(user_id: Any = None, **overrides: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": user_id or uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        "type": CredentialType.PASSWORD,
        "identifier": "13800138000",
        "secret": "$2b$12$LJ3m4ys3GZfnYMz8kVsKaOS7XxBt2NkPOdSqQHsVxVAYfGvN5HXEu",
    }
    defaults.update(overrides)
    cred = MagicMock()
    for k, v in defaults.items():
        setattr(cred, k, v)
    return cred


def _make_invite_code(**overrides: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "code": "ABCD2345",
        "channel": InviteChannel.DEMAND,
        "max_uses": 1,
        "used_count": 0,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "status": InviteCodeStatus.ACTIVE,
    }
    defaults.update(overrides)
    code = MagicMock()
    for k, v in defaults.items():
        setattr(code, k, v)
    return code


@pytest.fixture
def mock_hasher() -> MagicMock:
    h = MagicMock()
    h.hash_password.return_value = "$2b$12$hashed"
    h.verify_password.return_value = True
    return h


@pytest.fixture
def mock_tokens() -> MagicMock:
    tm = MagicMock()
    tm.create_access_token.side_effect = lambda data: f"access:{data['sub']}:{data['family_id']}"
    tm.create_refresh_token.side_effect = lambda data: f"refresh:{data['sub']}:{data['family_id']}"
    return tm


@pytest.fixture
def mock_blacklist() -> MagicMock:
    tb = MagicMock()
    tb.is_refresh_used = AsyncMock(return_value=False)
    tb.is_family_revoked = AsyncMock(return_value=False)
    tb.add_to_blacklist = AsyncMock()
    tb.mark_refresh_used = AsyncMock()
    tb.revoke_family = AsyncMock()
    return tb


@pytest.fixture
def mock_user_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_phone = AsyncMock(return_value=None)
    repo.find_by_id = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda s, u: u)
    return repo


@pytest.fixture
def mock_credential_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_type_and_identifier = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda s, c: c)
    return repo


@pytest.fixture
def mock_invite_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_code = AsyncMock(return_value=_make_invite_code())
    repo.consume_if_valid = AsyncMock(return_value=_make_invite_code(used_count=1))
    return repo


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def svc(mock_hasher, mock_tokens, mock_blacklist, mock_user_repo, mock_credential_repo, mock_invite_repo):
    return AuthServiceImpl(
        password_hasher=mock_hasher,
        token_manager=mock_tokens,
        token_blacklist=mock_blacklist,
        user_repo=mock_user_repo,
        credential_repo=mock_credential_repo,
        invite_code_repo=mock_invite_repo,
    )


def _register_request(**overrides: Any) -> RegisterRequest:
    data: dict[str, Any] = {
        "phone": "13800138000",
        "password": "Abc12345",
        "invite_code": "ABCD2345",
        "role": "family",
    }
    data.update(overrides)
    return RegisterRequest(**data)


# =============================================================================
# 注册
# =============================================================================


class TestRegister:
    @pytest.mark.asyncio
    async def test_family_register_active(self, svc, mock_session):
        """family 注册落态 active。"""
        result = await svc.register(_register_request(), mock_session)
        assert result.result == "success"
        assert result.status == AccountStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_volunteer_register_active(self, svc, mock_session):
        result = await svc.register(_register_request(role="volunteer"), mock_session)
        assert result.status == AccountStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_expert_register_pending_review(self, svc, mock_user_repo, mock_invite_repo, mock_session):
        """expert 注册（supply 码 + real_name）落态 pending_review。"""
        mock_invite_repo.find_by_code.return_value = _make_invite_code(channel=InviteChannel.SUPPLY)
        mock_invite_repo.consume_if_valid.return_value = _make_invite_code(channel=InviteChannel.SUPPLY)
        result = await svc.register(
            _register_request(role="expert", real_name="王专家", invite_code="SUPPLY001"),
            mock_session,
        )
        assert result.status == AccountStatus.PENDING_REVIEW

    @pytest.mark.asyncio
    async def test_teacher_real_name_required(self, svc, mock_session):
        mock_invite = _make_invite_code(channel=InviteChannel.SUPPLY)
        svc._invite_code_repo.find_by_code = AsyncMock(return_value=mock_invite)
        with pytest.raises(RealNameRequiredError):
            await svc.register(_register_request(role="teacher", real_name=None), mock_session)

    @pytest.mark.asyncio
    async def test_password_complexity(self, svc, mock_session):
        with pytest.raises(PasswordComplexityError):
            await svc.register(_register_request(password="abcdefgh"), mock_session)

    @pytest.mark.asyncio
    async def test_invite_code_not_found(self, svc, mock_invite_repo, mock_session):
        mock_invite_repo.find_by_code.return_value = None
        with pytest.raises(InvalidInviteCodeError):
            await svc.register(_register_request(), mock_session)

    @pytest.mark.asyncio
    async def test_invite_code_revoked(self, svc, mock_invite_repo, mock_session):
        mock_invite_repo.find_by_code.return_value = _make_invite_code(status=InviteCodeStatus.REVOKED)
        with pytest.raises(InvalidInviteCodeError):
            await svc.register(_register_request(), mock_session)

    @pytest.mark.asyncio
    async def test_invite_code_expired(self, svc, mock_invite_repo, mock_session):
        mock_invite_repo.find_by_code.return_value = _make_invite_code(
            expires_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        with pytest.raises(InvalidInviteCodeError):
            await svc.register(_register_request(), mock_session)

    @pytest.mark.asyncio
    async def test_invite_code_exhausted(self, svc, mock_invite_repo, mock_session):
        mock_invite_repo.find_by_code.return_value = _make_invite_code(used_count=1, max_uses=1)
        with pytest.raises(InvalidInviteCodeError):
            await svc.register(_register_request(), mock_session)

    @pytest.mark.asyncio
    async def test_channel_mismatch(self, svc, mock_invite_repo, mock_session):
        """demand 码注册 expert → 渠道约束拒绝。"""
        with pytest.raises(InviteChannelMismatchError):
            await svc.register(_register_request(role="expert", real_name="王专家"), mock_session)

    @pytest.mark.asyncio
    async def test_duplicate_phone(self, svc, mock_user_repo, mock_session):
        mock_user_repo.find_by_phone.return_value = _make_user()
        with pytest.raises(DuplicateUserError) as exc:
            await svc.register(_register_request(), mock_session)
        assert exc.value.code == "DUPLICATE_PHONE"

    @pytest.mark.asyncio
    async def test_atomic_consume_race_loser(self, svc, mock_invite_repo, mock_session):
        """并发下条件自增未命中（预检通过但消费失败）→ 邀请码已用完。"""
        mock_invite_repo.consume_if_valid.return_value = None
        with pytest.raises(InvalidInviteCodeError):
            await svc.register(_register_request(), mock_session)

    @pytest.mark.asyncio
    async def test_creates_user_and_credential_atomically(
        self, svc, mock_user_repo, mock_credential_repo, mock_invite_repo, mock_session
    ):
        """注册原子事务：消费邀请码 + 创建 User + 创建 password Credential + commit。"""
        await svc.register(_register_request(), mock_session)

        mock_invite_repo.consume_if_valid.assert_awaited_once()
        mock_user_repo.create.assert_awaited_once()
        mock_credential_repo.create.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

        # Credential 语义：type=password, identifier=phone, secret=哈希
        created_cred = mock_credential_repo.create.await_args.args[1]
        assert created_cred.type == CredentialType.PASSWORD
        assert created_cred.identifier == "13800138000"
        assert created_cred.secret == "$2b$12$hashed"


# =============================================================================
# 登录
# =============================================================================


class TestLogin:
    @pytest.mark.asyncio
    async def test_credential_not_found_401(self, svc, mock_session):
        with pytest.raises(InvalidCredentialsError):
            await svc.login(LoginRequest(phone="13800138000", password="Abc12345"), mock_session)

    @pytest.mark.asyncio
    async def test_wrong_password_same_error(self, svc, mock_credential_repo, mock_hasher, mock_user_repo, mock_session):
        """密码错误与用户不存在返回完全相同的错误（防枚举）。"""
        with pytest.raises(InvalidCredentialsError) as exc1:
            await svc.login(LoginRequest(phone="13800138000", password="Abc12345"), mock_session)

        mock_credential_repo.find_by_type_and_identifier.return_value = _make_credential()
        mock_user_repo.find_by_id.return_value = _make_user()
        mock_hasher.verify_password.return_value = False
        with pytest.raises(InvalidCredentialsError) as exc2:
            await svc.login(LoginRequest(phone="13800138000", password="WrongPass1"), mock_session)

        assert exc1.value.message == exc2.value.message
        assert exc1.value.code == exc2.value.code

    @pytest.mark.asyncio
    async def test_disabled_rejected(self, svc, mock_credential_repo, mock_user_repo, mock_session):
        """disabled 账号即签即拒（凭证校验通过后拒绝签发）。"""
        mock_credential_repo.find_by_type_and_identifier.return_value = _make_credential()
        mock_user_repo.find_by_id.return_value = _make_user(status=AccountStatus.DISABLED)
        with pytest.raises(AccountDisabledError):
            await svc.login(LoginRequest(phone="13800138000", password="Abc12345"), mock_session)

    @pytest.mark.asyncio
    async def test_pending_review_allowed(self, svc, mock_credential_repo, mock_user_repo, mock_session):
        """pending_review 可登录（仅见状态页，由 RBAC 守卫收敛能力）。"""
        mock_credential_repo.find_by_type_and_identifier.return_value = _make_credential()
        mock_user_repo.find_by_id.return_value = _make_user(status=AccountStatus.PENDING_REVIEW)
        result = await svc.login(LoginRequest(phone="13800138000", password="Abc12345"), mock_session)
        assert isinstance(result, TokenResponse)
        assert result.access_token

    @pytest.mark.asyncio
    async def test_login_creates_new_family(self, svc, mock_credential_repo, mock_user_repo, mock_tokens, mock_session):
        """每次登录创建新 Token 家族（family_id 为合法 UUID）。"""
        mock_credential_repo.find_by_type_and_identifier.return_value = _make_credential()
        mock_user_repo.find_by_id.return_value = _make_user()
        result = await svc.login(LoginRequest(phone="13800138000", password="Abc12345"), mock_session)

        family_id = result.access_token.split(":")[2]
        uuid.UUID(family_id)  # 合法 UUID 不抛异常

        # payload 携带 role/status（以 DB 最新值为准）
        token_data = mock_tokens.create_access_token.call_args.args[0]
        assert token_data["role"] == "family"
        assert token_data["status"] == "active"


# =============================================================================
# 刷新（轮换 + 家族语义）
# =============================================================================


def _refresh_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "role": "family",
        "status": "active",
        "family_id": "fam-001",
        "jti": "jti-refresh-001",
        "type": "refresh",
    }
    payload.update(overrides)
    return payload


class TestRefresh:
    @pytest.mark.asyncio
    async def test_invalid_token(self, svc, mock_tokens, mock_session):
        mock_tokens.verify_refresh_token.return_value = None
        with pytest.raises(TokenInvalidError) as exc:
            await svc.refresh_token(RefreshRequest(refresh_token="bad.token"), mock_session)
        assert exc.value.detail["reason"] == "token_invalid"

    @pytest.mark.asyncio
    async def test_family_revoked(self, svc, mock_tokens, mock_blacklist, mock_user_repo, mock_session):
        mock_tokens.verify_refresh_token.return_value = _refresh_payload()
        mock_blacklist.is_family_revoked.return_value = True
        mock_user_repo.find_by_id.return_value = _make_user()
        with pytest.raises(TokenInvalidError) as exc:
            await svc.refresh_token(RefreshRequest(refresh_token="some.token"), mock_session)
        assert exc.value.detail["reason"] == "family_revoked"

    @pytest.mark.asyncio
    async def test_reuse_triggers_family_revocation(self, svc, mock_tokens, mock_blacklist, mock_user_repo, mock_session):
        """旧 refresh 复用 → 判定泄露 → 吊销全家族 + 拒绝。"""
        mock_tokens.verify_refresh_token.return_value = _refresh_payload()
        mock_blacklist.is_refresh_used.return_value = True
        mock_user_repo.find_by_id.return_value = _make_user()
        with pytest.raises(TokenInvalidError) as exc:
            await svc.refresh_token(RefreshRequest(refresh_token="reused.token"), mock_session)
        assert exc.value.detail["reason"] == "token_reused"
        mock_blacklist.revoke_family.assert_awaited_once_with("fam-001")

    @pytest.mark.asyncio
    async def test_disabled_user_rejected(self, svc, mock_tokens, mock_user_repo, mock_session):
        """disabled 用户 refresh 拒签。"""
        mock_tokens.verify_refresh_token.return_value = _refresh_payload()
        mock_user_repo.find_by_id.return_value = _make_user(status=AccountStatus.DISABLED)
        with pytest.raises(AccountDisabledError):
            await svc.refresh_token(RefreshRequest(refresh_token="some.token"), mock_session)

    @pytest.mark.asyncio
    async def test_rotation_keeps_family(
        self, svc, mock_tokens, mock_blacklist, mock_user_repo, mock_session
    ):
        """轮换在同一家族内延续：标记旧 jti + 新对沿用旧 family_id + 最新 role/status。"""
        mock_tokens.verify_refresh_token.return_value = _refresh_payload()
        mock_user_repo.find_by_id.return_value = _make_user(role=UserRole.VOLUNTEER)
        result = await svc.refresh_token(RefreshRequest(refresh_token="old.token"), mock_session)

        mock_blacklist.mark_refresh_used.assert_awaited_once_with("jti-refresh-001")
        assert result.access_token.endswith(":fam-001")
        token_data = mock_tokens.create_access_token.call_args.args[0]
        assert token_data["role"] == "volunteer"  # 以 DB 最新角色为准


# =============================================================================
# 登出
# =============================================================================


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_blacklists_access_and_revokes_family(self, svc, mock_blacklist):
        access = _make_jwt({"jti": "jti-access", "family_id": "fam-x"})
        refresh = _make_jwt({"jti": "jti-refresh", "family_id": "fam-x"})
        await svc.logout(access, refresh)
        mock_blacklist.add_to_blacklist.assert_awaited_once_with("jti-access")
        mock_blacklist.revoke_family.assert_awaited_once_with("fam-x")

    @pytest.mark.asyncio
    async def test_logout_invalid_tokens_no_error(self, svc):
        await svc.logout("garbage", "garbage")  # fail-open，不抛异常


# =============================================================================
# me
# =============================================================================


class TestMe:
    @pytest.mark.asyncio
    async def test_me_returns_profile(self, svc, mock_user_repo, mock_session):
        mock_user_repo.find_by_id.return_value = _make_user(real_name="张老师", role=UserRole.TEACHER)
        me = await svc.get_me("550e8400-e29b-41d4-a716-446655440000", mock_session)
        assert me.phone == "13800138000"
        assert me.role == UserRole.TEACHER
        assert me.status == AccountStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_me_user_not_found(self, svc, mock_user_repo, mock_session):
        mock_user_repo.find_by_id.return_value = None
        with pytest.raises(InvalidCredentialsError):
            await svc.get_me("550e8400-e29b-41d4-a716-446655440000", mock_session)
