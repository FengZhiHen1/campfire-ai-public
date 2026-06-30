"""auth 模块 — 正式测试套件。

三部分：
  A. 契约对抗测试（保留自 adversarial/）—— 匿名子类验证 @final 方法边界
  B. AuthServiceImpl 集成测试 —— 真实实现 + mock 依赖链
  C. 路由冒烟测试 —— FastAPI TestClient 端到端
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.modules.auth.auth_contract import AuthService
from app.modules.auth.auth_service import AuthServiceImpl
from app.modules.auth.exceptions import (
    AuthInternalError,
    DuplicateUserError,
    InvalidCredentialsError,
    PasswordComplexityError,
    RealNameRequiredError,
    TokenInvalidError,
)
from fastapi.testclient import TestClient
from py_auth.exceptions import HashingError, TokenCreationError
from py_schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserRole,
)

# =============================================================================
# 工具函数
# =============================================================================


def _make_jwt(payload: dict[str, Any]) -> str:
    """构造三段式 JWT 字符串（无签名）。"""
    header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header_b64}.{payload_b64}.fake_sig"


def _make_user(**overrides: Any) -> MagicMock:
    """构造 mock User ORM 实例。"""
    defaults: dict[str, Any] = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "username": "testuser",
        "password_hash": "$2b$12$LJ3m4ys3GZfnYMz8kVsKaOS7XxBt2NkPOdSqQHsVxVAYfGvN5HXEu",
    }
    defaults.update(overrides)
    user = MagicMock()
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_hasher() -> MagicMock:
    h = MagicMock()
    h.hash_password.return_value = "$2b$12$LJ3m4ys3GZfnYMz8kVsKaOS7XxBt2NkPOdSqQHsVxVAYfGvN5HXEu"
    h.verify_password.return_value = True
    return h


@pytest.fixture
def mock_tokens() -> MagicMock:
    tm = MagicMock()
    tm.create_access_token.return_value = "eyJ...access.fake"
    tm.create_refresh_token.return_value = "eyJ...refresh.fake"
    tm.verify_refresh_token.return_value = {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "roles": ["family"],
        "jti": "jti-refresh-001",
        "type": "refresh",
    }
    return tm


@pytest.fixture
def mock_blacklist() -> MagicMock:
    tb = MagicMock()
    tb.is_refresh_used = AsyncMock(return_value=False)
    tb.add_to_blacklist = AsyncMock()
    tb.mark_refresh_used = AsyncMock()
    return tb


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_username_lower = AsyncMock(return_value=None)
    repo.find_by_phone = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock()


# =============================================================================
# A. 契约对抗测试 — 匿名子类验证 @final 方法
# =============================================================================


class _TestAuthService(AuthService):
    """测试用最小化子类，委托所有 _do_ 钩子给注入的 mock。"""

    def _do_hash_password(self, plain_password: str) -> str:
        return self._password_hasher.hash_password(plain_password)

    async def _do_register(self, request, hashed_password, session) -> RegisterResponse:
        return RegisterResponse(
            result="success",
            user_id="550e8400-e29b-41d4-a716-446655440000",
        )

    async def _fetch_user(self, username, session):
        return await self._user_repo.find_by_username_lower(session, username)

    def _do_login(self, user) -> TokenResponse:
        data = {
            "sub": str(user.id),
            "roles": [getattr(user.role, "value", str(user.role))],
        }
        return TokenResponse(
            access_token=str(self._token_manager.create_access_token(data)),
            refresh_token=str(self._token_manager.create_refresh_token(data)),
        )

    async def _do_refresh(self, payload, old_refresh_token) -> TokenResponse:
        await self._token_blacklist.mark_refresh_used(payload["jti"])
        new_data = {"sub": payload["sub"], "roles": payload.get("roles", [])}
        return TokenResponse(
            access_token=str(self._token_manager.create_access_token(new_data)),
            refresh_token=str(self._token_manager.create_refresh_token(new_data)),
        )

    async def _do_logout(self, access_jti, refresh_jti) -> None:
        if access_jti:
            await self._token_blacklist.add_to_blacklist(access_jti)
        if refresh_jti:
            await self._token_blacklist.mark_refresh_used(refresh_jti)


@pytest.fixture
def svc(mock_hasher, mock_tokens, mock_blacklist, mock_repo) -> _TestAuthService:
    return _TestAuthService(
        password_hasher=mock_hasher,
        token_manager=mock_tokens,
        token_blacklist=mock_blacklist,
        user_repo=mock_repo,
    )


class TestContractPasswordComplexity:
    """P0-1: 密码复杂度边界。"""

    @pytest.mark.parametrize(
        "password,bypass",
        [
            ("abcdefgh", False),
            ("ABCDEFGH", False),
            ("12345678", False),
            ("Abc1234", True),
            ("!@#$%^&*", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_rejected(self, svc, mock_session, password, bypass):
        if bypass:
            request = RegisterRequest.model_construct(
                username="testuser",
                password=password,
                role=UserRole.FAMILY,
                phone="13800138000",
            )
        else:
            request = RegisterRequest(
                username="testuser",
                password=password,
                role=UserRole.FAMILY,
                phone="13800138000",
            )
        with pytest.raises(PasswordComplexityError):
            await svc.register(request, mock_session)


class TestContractExpertRealName:
    """P0-2: 专家 real_name 必填。"""

    @pytest.mark.parametrize("real_name,bypass", [(None, False), ("", True)])
    @pytest.mark.asyncio
    async def test_required(self, svc, mock_session, real_name, bypass):
        if bypass:
            request = RegisterRequest.model_construct(
                username="expert1",
                password="Abc12345",
                role=UserRole.EXPERT,
                phone="13800138001",
                real_name="",
            )
        else:
            request = RegisterRequest(
                username="expert1",
                password="Abc12345",
                role=UserRole.EXPERT,
                phone="13800138001",
                real_name=None,
            )
        with pytest.raises(RealNameRequiredError):
            await svc.register(request, mock_session)


class TestContractUniqueness:
    """P0-3/4: 用户名和手机号唯一性。"""

    @pytest.mark.asyncio
    async def test_username_duplicate(self, svc, mock_repo, mock_session):
        mock_repo.find_by_username_lower.return_value = MagicMock()
        request = RegisterRequest(
            username="existing",
            password="Abc12345",
            role=UserRole.FAMILY,
            phone="13800138000",
        )
        with pytest.raises(DuplicateUserError) as exc:
            await svc.register(request, mock_session)
        assert exc.value.code == "DUPLICATE_USERNAME"

    @pytest.mark.asyncio
    async def test_phone_duplicate(self, svc, mock_repo, mock_session):
        mock_repo.find_by_phone.return_value = MagicMock()
        request = RegisterRequest(
            username="newuser",
            password="Abc12345",
            role=UserRole.FAMILY,
            phone="13800138000",
        )
        with pytest.raises(DuplicateUserError) as exc:
            await svc.register(request, mock_session)
        assert exc.value.code == "DUPLICATE_PHONE"


class TestContractLoginAntiEnumeration:
    """P0-5: 登录防枚举攻击。"""

    @pytest.mark.asyncio
    async def test_user_not_exist(self, svc, mock_repo, mock_session):
        mock_repo.find_by_username_lower.return_value = None
        request = LoginRequest(username="nonexistent", password="Abc12345")
        with pytest.raises(InvalidCredentialsError):
            await svc.login(request, mock_session)

    @pytest.mark.asyncio
    async def test_wrong_password(self, svc, mock_hasher, mock_repo, mock_session):
        mock_repo.find_by_username_lower.return_value = _make_user()
        mock_hasher.verify_password.return_value = False
        request = LoginRequest(username="testuser", password="WrongPass1")
        with pytest.raises(InvalidCredentialsError):
            await svc.login(request, mock_session)

    @pytest.mark.asyncio
    async def test_same_error_message(self, svc, mock_hasher, mock_repo, mock_session):
        mock_repo.find_by_username_lower.return_value = None
        with pytest.raises(InvalidCredentialsError) as exc1:
            await svc.login(LoginRequest(username="noexist", password="Abc12345"), mock_session)

        mock_repo.find_by_username_lower.return_value = _make_user()
        mock_hasher.verify_password.return_value = False
        with pytest.raises(InvalidCredentialsError) as exc2:
            await svc.login(LoginRequest(username="testuser", password="WrongPass1"), mock_session)

        assert exc1.value.message == exc2.value.message
        assert exc1.value.code == exc2.value.code == "INVALID_CREDENTIALS"


class TestContractRefreshToken:
    """P0-6/7: refresh token 校验与重放防护。"""

    @pytest.mark.asyncio
    async def test_wrong_token_type(self, svc, mock_tokens, mock_session):
        mock_tokens.verify_refresh_token.return_value = None
        request = RefreshRequest(refresh_token="some.access.token")
        with pytest.raises(TokenInvalidError) as exc:
            await svc.refresh_token(request, mock_session)
        assert exc.value.detail.get("reason") == "token_invalid"

    @pytest.mark.asyncio
    async def test_replay_attack(self, svc, mock_tokens, mock_blacklist, mock_session):
        mock_tokens.verify_refresh_token.return_value = {
            "sub": "user-1",
            "roles": ["family"],
            "jti": "jti-reused",
            "type": "refresh",
        }
        mock_blacklist.is_refresh_used.return_value = True
        request = RefreshRequest(refresh_token="some.token")
        with pytest.raises(TokenInvalidError) as exc:
            await svc.refresh_token(request, mock_session)
        assert exc.value.detail.get("reason") == "token_reused"


class TestContractNormalPaths:
    """P0-8/9/10: 正常路径。"""

    @pytest.mark.asyncio
    async def test_register_success(self, svc, mock_session):
        request = RegisterRequest(
            username="newuser",
            password="Abc12345",
            role=UserRole.FAMILY,
            phone="13800138000",
        )
        result = await svc.register(request, mock_session)
        assert result.result == "success"
        assert result.user_id

    @pytest.mark.asyncio
    async def test_login_success(self, svc, mock_hasher, mock_repo, mock_session):
        mock_repo.find_by_username_lower.return_value = _make_user()
        mock_hasher.verify_password.return_value = True
        request = LoginRequest(username="testuser", password="Abc12345")
        result = await svc.login(request, mock_session)
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_logout_invalid_token_no_error(self, svc):
        try:
            await svc.logout("garbage", "garbage")
        except Exception as exc:
            pytest.fail(f"登出对无效 token 抛异常: {exc}")


class TestContractExceptionInjection:
    """P1: 内部异常注入。"""

    @pytest.mark.asyncio
    async def test_hash_failure_propagates(self, svc, mock_session):
        with patch.object(svc, "_do_hash_password", side_effect=HashingError("bcrypt 引擎错误")):
            request = RegisterRequest(
                username="newuser",
                password="Abc12345",
                role=UserRole.FAMILY,
                phone="13800138000",
            )
            with pytest.raises(HashingError):
                await svc.register(request, mock_session)

    @pytest.mark.asyncio
    async def test_jwt_failure_propagates(self, svc, mock_hasher, mock_repo, mock_session):
        mock_repo.find_by_username_lower.return_value = _make_user()
        mock_hasher.verify_password.return_value = True
        with patch.object(svc, "_do_login", side_effect=TokenCreationError("JWT 签发异常")):
            request = LoginRequest(username="testuser", password="Abc12345")
            with pytest.raises(TokenCreationError):
                await svc.login(request, mock_session)

    @pytest.mark.asyncio
    async def test_empty_user_id_rejected(self, svc, mock_session):
        with patch.object(
            svc,
            "_do_register",
            return_value=RegisterResponse(
                result="success",
                user_id="",
            ),
        ):
            request = RegisterRequest(
                username="newuser",
                password="Abc12345",
                role=UserRole.FAMILY,
                phone="13800138000",
            )
            with pytest.raises(AuthInternalError):
                await svc.register(request, mock_session)


class TestContractConcurrency:
    """P2: 并发竞态。"""

    @pytest.mark.asyncio
    async def test_concurrent_same_username(self, svc, mock_repo, mock_session):
        mock_repo.find_by_phone.return_value = None
        mock_repo.find_by_username_lower.return_value = None

        calls = 0

        async def race_register(request, hashed, session):
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.sleep(0.05)
                return RegisterResponse(user_id="uuid-aaa")
            raise DuplicateUserError(code="DUPLICATE_USERNAME", message="该用户名已被注册")

        with patch.object(svc, "_do_register", side_effect=race_register):
            req1 = RegisterRequest(
                username="same",
                password="Abc12345",
                role=UserRole.FAMILY,
                phone="13800138001",
            )
            req2 = RegisterRequest(
                username="same",
                password="Xyz98765",
                role=UserRole.FAMILY,
                phone="13800138002",
            )
            results = await asyncio.gather(
                svc.register(req1, mock_session),
                svc.register(req2, mock_session),
                return_exceptions=True,
            )

        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) >= 1


class TestContractFuzz:
    """P3: 模糊测试。"""

    @pytest.mark.parametrize(
        "username,password,phone",
        [
            ("abcd", "Abc12345", "13800138000"),
            ("a" * 32, "Abc12345", "13800138001"),
            ("user8pwd", "Xy9aaaaa", "13800138002"),
            ("userphone", "Abc12345", "13900139000"),
        ],
    )
    @pytest.mark.asyncio
    async def test_boundary_inputs(self, svc, mock_session, username, password, phone):
        request = RegisterRequest(username=username, password=password, role=UserRole.FAMILY, phone=phone)
        result = await svc.register(request, mock_session)
        assert result.result == "success"

    def test_empty_password_rejected_by_pydantic(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LoginRequest(username="testuser", password="")


# =============================================================================
# B. AuthServiceImpl 集成测试 — 真实实现 + mock 依赖链
# =============================================================================


@pytest.fixture
def impl_svc(mock_hasher, mock_tokens, mock_blacklist, mock_repo) -> AuthServiceImpl:
    """构建 AuthServiceImpl，验证真实实现与契约的一致性。"""
    return AuthServiceImpl(
        password_hasher=mock_hasher,
        token_manager=mock_tokens,
        token_blacklist=mock_blacklist,
        user_repo=mock_repo,
    )


class TestAuthServiceImplRegister:
    """AuthServiceImpl._do_register 真实实现测试。"""

    @pytest.mark.asyncio
    async def test_creates_user_and_returns_response(self, impl_svc, mock_repo, mock_session):
        created_user = _make_user()
        mock_repo.create = AsyncMock(return_value=created_user)

        request = RegisterRequest(
            username="newuser",
            password="Abc12345",
            role=UserRole.FAMILY,
            phone="13800138000",
        )
        result = await impl_svc._do_register(request, "$2b$12$hash", mock_session)

        assert result.result == "success"
        assert result.user_id == "550e8400-e29b-41d4-a716-446655440000"
        mock_repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_integrity_error_mapped_to_duplicate(self, impl_svc, mock_repo, mock_session):
        from sqlalchemy.exc import IntegrityError

        orig = Exception()
        setattr(orig, "pgcode", "23505")
        setattr(orig, "diag", MagicMock(constraint_name="unique_username"))
        mock_repo.create = AsyncMock(side_effect=IntegrityError("dup", {}, orig))

        request = RegisterRequest(
            username="existing",
            password="Abc12345",
            role=UserRole.FAMILY,
            phone="13800138000",
        )
        with pytest.raises(DuplicateUserError) as exc:
            await impl_svc._do_register(request, "$2b$12$hash", mock_session)
        assert exc.value.code == "DUPLICATE_USERNAME"

    @pytest.mark.asyncio
    async def test_db_error_mapped_to_internal(self, impl_svc, mock_repo, mock_session):
        from sqlalchemy.exc import SQLAlchemyError

        mock_repo.create = AsyncMock(side_effect=SQLAlchemyError("connection lost"))

        request = RegisterRequest(
            username="newuser",
            password="Abc12345",
            role=UserRole.FAMILY,
            phone="13800138000",
        )
        with pytest.raises(AuthInternalError):
            await impl_svc._do_register(request, "$2b$12$hash", mock_session)


class TestAuthServiceImplHashPassword:
    """AuthServiceImpl._do_hash_password 真实实现测试。"""

    def test_hashes_and_returns_string(self, impl_svc, mock_hasher):
        result = impl_svc._do_hash_password("Abc12345")
        assert result == "$2b$12$LJ3m4ys3GZfnYMz8kVsKaOS7XxBt2NkPOdSqQHsVxVAYfGvN5HXEu"
        mock_hasher.hash_password.assert_called_once_with("Abc12345")

    def test_hashing_error_mapped_to_internal(self, impl_svc, mock_hasher):
        mock_hasher.hash_password.side_effect = HashingError("bcrypt 故障")
        with pytest.raises(AuthInternalError, match="密码哈希失败"):
            impl_svc._do_hash_password("Abc12345")


class TestAuthServiceImplLogin:
    """AuthServiceImpl._do_login 真实实现测试。"""

    def test_issues_token_pair(self, impl_svc, mock_tokens):
        user = _make_user()
        user.role = MagicMock(value="family")
        result = impl_svc._do_login(user)
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "Bearer"
        mock_tokens.create_access_token.assert_called_once()
        mock_tokens.create_refresh_token.assert_called_once()

    def test_token_creation_error_mapped(self, impl_svc, mock_tokens):
        mock_tokens.create_access_token.side_effect = TokenCreationError("JWT 故障")
        user = _make_user()
        user.role = MagicMock(value="family")
        with pytest.raises(AuthInternalError, match="Token 签发失败"):
            impl_svc._do_login(user)


class TestAuthServiceImplRefresh:
    """AuthServiceImpl._do_refresh 真实实现测试。"""

    @pytest.mark.asyncio
    async def test_marks_old_and_issues_new(self, impl_svc, mock_blacklist, mock_tokens):
        payload = {"sub": "user-1", "roles": ["family"], "jti": "jti-old"}
        result = await impl_svc._do_refresh(payload, "old.token")
        mock_blacklist.mark_refresh_used.assert_awaited_once_with("jti-old")
        assert result.access_token
        assert result.refresh_token

    @pytest.mark.asyncio
    async def test_token_creation_error_mapped(self, impl_svc, mock_tokens):
        mock_tokens.create_access_token.side_effect = TokenCreationError("JWT 故障")
        payload = {"sub": "user-1", "roles": ["family"], "jti": "jti-old"}
        with pytest.raises(AuthInternalError, match="Token 续期失败"):
            await impl_svc._do_refresh(payload, "old.token")


class TestAuthServiceImplLogout:
    """AuthServiceImpl._do_logout 真实实现测试。"""

    @pytest.mark.asyncio
    async def test_blacklists_both_tokens(self, impl_svc, mock_blacklist):
        await impl_svc._do_logout("jti-access", "jti-refresh")
        mock_blacklist.add_to_blacklist.assert_awaited_once_with("jti-access")
        mock_blacklist.mark_refresh_used.assert_awaited_once_with("jti-refresh")

    @pytest.mark.asyncio
    async def test_skips_none_jti(self, impl_svc, mock_blacklist):
        await impl_svc._do_logout(None, None)
        mock_blacklist.add_to_blacklist.assert_not_called()
        mock_blacklist.mark_refresh_used.assert_not_called()


class TestAuthServiceImplFetchUser:
    """AuthServiceImpl._fetch_user 真实实现测试。"""

    @pytest.mark.asyncio
    async def test_delegates_to_repo(self, impl_svc, mock_repo, mock_session):
        mock_user = _make_user()
        mock_repo.find_by_username_lower.return_value = mock_user
        result = await impl_svc._fetch_user("testuser", mock_session)
        assert result is mock_user
        mock_repo.find_by_username_lower.assert_awaited_once_with(mock_session, "testuser")


# =============================================================================
# C. 路由冒烟测试 — FastAPI TestClient
# =============================================================================


@pytest.fixture
def client() -> TestClient:
    """构建 TestClient，用 mock AuthService 替换依赖。"""
    from app.core.dependencies import auth_dependencies
    from app.modules.auth.routes import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    # 覆盖依赖：注入 mock AuthService
    mock_svc = MagicMock(spec=AuthService)
    mock_svc.register = AsyncMock()
    mock_svc.login = AsyncMock()
    mock_svc.refresh_token = AsyncMock()
    mock_svc.logout = AsyncMock()

    app.dependency_overrides[auth_dependencies.get_auth_service] = lambda: mock_svc
    app.dependency_overrides[auth_dependencies.get_db_session] = lambda: MagicMock()

    # 保存 mock 引用供测试断言
    client = TestClient(app)
    client._mock_auth_service = mock_svc  # type: ignore[attr-defined]
    return client


class TestRegisterRoute:
    """POST /api/v1/auth/register 路由测试。"""

    def test_201_success(self, client):
        client._mock_auth_service.register.return_value = RegisterResponse(  # type: ignore[attr-defined]
            result="success",
            user_id="uuid-1234",
        )
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "password": "Abc12345",
                "role": "family",
                "phone": "13800138000",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["result"] == "success"

    def test_422_pydantic_validation(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": "ab",
                "password": "short",
                "role": "family",
                "phone": "13800138000",
            },
        )
        assert resp.status_code == 422

    def test_409_duplicate(self, client):
        client._mock_auth_service.register.side_effect = DuplicateUserError(  # type: ignore[attr-defined]
            code="DUPLICATE_USERNAME",
            message="该用户名已被注册",
        )
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": "existing",
                "password": "Abc12345",
                "role": "family",
                "phone": "13800138000",
            },
        )
        assert resp.status_code == 409

    def test_422_password_complexity(self, client):
        client._mock_auth_service.register.side_effect = PasswordComplexityError()  # type: ignore[attr-defined]
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "password": "abcdefgh",
                "role": "family",
                "phone": "13800138000",
            },
        )
        assert resp.status_code == 422


class TestLoginRoute:
    """POST /api/v1/auth/login 路由测试。"""

    def test_200_success(self, client):
        client._mock_auth_service.login.return_value = TokenResponse(  # type: ignore[attr-defined]
            access_token="tok_access",
            refresh_token="tok_refresh",
        )
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": "testuser",
                "password": "Abc12345",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["access_token"] == "tok_access"

    def test_401_invalid_credentials(self, client):
        client._mock_auth_service.login.side_effect = InvalidCredentialsError()  # type: ignore[attr-defined]
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": "testuser",
                "password": "WrongPass1",
            },
        )
        assert resp.status_code == 401


class TestRefreshRoute:
    """POST /api/v1/auth/refresh 路由测试。"""

    def test_200_success(self, client):
        client._mock_auth_service.refresh_token.return_value = TokenResponse(  # type: ignore[attr-defined]
            access_token="new_access",
            refresh_token="new_refresh",
        )
        resp = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "valid.refresh.token",
            },
        )
        assert resp.status_code == 200

    def test_401_token_invalid(self, client):
        client._mock_auth_service.refresh_token.side_effect = TokenInvalidError()  # type: ignore[attr-defined]
        resp = client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "expired.token",
            },
        )
        assert resp.status_code == 401


class TestLogoutRoute:
    """POST /api/v1/auth/logout 路由测试。"""

    def test_204_success(self, client):
        client._mock_auth_service.logout.return_value = None  # type: ignore[attr-defined]
        resp = client.post(
            "/api/v1/auth/logout",
            json={
                "refresh_token": "some.refresh.token",
            },
        )
        assert resp.status_code == 204

    def test_204_with_authorization_header(self, client):
        client._mock_auth_service.logout.return_value = None  # type: ignore[attr-defined]
        resp = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "some.refresh.token"},
            headers={"Authorization": "Bearer some.access.token"},
        )
        assert resp.status_code == 204
