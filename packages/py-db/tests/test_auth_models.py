"""认证域 ORM 模型与 Repository — 单元测试（ADR-013 目标态）。

覆盖：
- User / Credential / InviteCode 三表模型结构（身份-凭证分离）
- UserRepository 按新模型调整（手机号唯一标识，废除 username/device_id 查询）
- CredentialRepository / InviteCodeRepository 接口存在性
- InviteCode 原子消费的条件自增语义（防并发复用）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from py_db.models.auth import Credential, InviteCode, User
from py_db.repositories.credential_repository import CredentialRepository
from py_db.repositories.invite_code_repository import InviteCodeRepository
from py_db.repositories.user_repository import UserRepository
from py_schemas.auth import UserRole
from py_schemas.enums import AccountStatus, CredentialType, InviteChannel, InviteCodeStatus

# ===========================================================================
# User 模型结构
# ===========================================================================


class TestUserModel:
    def test_columns(self):
        cols = {c.name for c in User.__table__.columns}
        assert {"id", "phone", "real_name", "role", "status", "reject_reason", "created_at", "updated_at"} <= cols

    def test_abolished_columns_removed(self):
        """username/password_hash/device_id 已随匿名演示轨与旧登录标识废除。"""
        cols = {c.name for c in User.__table__.columns}
        assert "username" not in cols
        assert "password_hash" not in cols
        assert "device_id" not in cols

    def test_phone_unique(self):
        phone_col = User.__table__.c.phone
        assert phone_col.unique is True
        assert phone_col.nullable is False

    def test_status_default_pending_or_active(self):
        """status 列非空，默认 active（teacher/expert 由 Service 层置 pending_review）。"""
        status_col = User.__table__.c.status
        assert status_col.nullable is False


# ===========================================================================
# Credential 模型结构
# ===========================================================================


class TestCredentialModel:
    def test_columns(self):
        cols = {c.name for c in Credential.__table__.columns}
        assert {"id", "user_id", "type", "identifier", "secret", "created_at"} <= cols

    def test_type_identifier_unique_constraint(self):
        """(type, identifier) 全局唯一约束（认证与访问 §2.1）。"""
        constraint_names = {
            tuple(sorted(col.name for col in c.columns))
            for c in Credential.__table__.constraints
            if hasattr(c, "columns")
        }
        assert ("identifier", "type") in constraint_names

    def test_user_id_fk_cascade(self):
        fks = list(Credential.__table__.c.user_id.foreign_keys)
        assert len(fks) == 1
        assert fks[0].column.table.name == "users"
        assert fks[0].ondelete == "CASCADE"

    def test_secret_nullable(self):
        """wechat 渠道凭证 secret 为空（以 code2session 结果为准）。"""
        assert Credential.__table__.c.secret.nullable is True


# ===========================================================================
# InviteCode 模型结构
# ===========================================================================


class TestInviteCodeModel:
    def test_columns(self):
        cols = {c.name for c in InviteCode.__table__.columns}
        assert {"code", "channel", "max_uses", "used_count", "expires_at", "status", "created_by", "created_at"} <= cols

    def test_code_is_primary_key(self):
        pk_cols = {c.name for c in InviteCode.__table__.primary_key.columns}
        assert pk_cols == {"code"}

    def test_created_by_fk(self):
        fks = list(InviteCode.__table__.c.created_by.foreign_keys)
        assert len(fks) == 1
        assert fks[0].column.table.name == "users"


# ===========================================================================
# Repository 接口
# ===========================================================================


class TestUserRepository:
    def test_find_by_phone_kept(self):
        assert hasattr(UserRepository, "find_by_phone")

    def test_username_device_queries_removed(self):
        assert not hasattr(UserRepository, "find_by_username_lower")
        assert not hasattr(UserRepository, "find_by_device_id")

    def test_list_by_status_and_roles(self):
        """准入审核列表查询入口存在。"""
        assert hasattr(UserRepository, "list_by_status_and_roles")


class TestCredentialRepository:
    def test_interface(self):
        assert hasattr(CredentialRepository, "find_by_type_and_identifier")


class TestInviteCodeRepository:
    def test_interface(self):
        assert hasattr(InviteCodeRepository, "find_by_code")
        assert hasattr(InviteCodeRepository, "consume_if_valid")
        assert hasattr(InviteCodeRepository, "revoke")

    @pytest.mark.asyncio
    async def test_consume_if_valid_returns_none_when_no_row(self):
        """条件自增未命中（码无效/过期/超量/已停用）→ 返回 None。"""
        repo = InviteCodeRepository(session_factory=MagicMock())
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        consumed = await repo.consume_if_valid(session, "ABCD2345")
        assert consumed is None

    @pytest.mark.asyncio
    async def test_consume_if_valid_returns_row_on_hit(self):
        """条件自增命中 → 返回更新后的 InviteCode。"""
        repo = InviteCodeRepository(session_factory=MagicMock())
        session = AsyncMock()
        fake_code = MagicMock(spec=InviteCode)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = fake_code
        session.execute.return_value = result_mock

        consumed = await repo.consume_if_valid(session, "ABCD2345")
        assert consumed is fake_code


# ===========================================================================
# 枚举值贯通（模型列枚举与 py-schemas 一致）
# ===========================================================================


class TestEnumAlignment:
    def test_user_role_enum_uses_schema_enum(self):
        assert User.__table__.c.role.type.enum_class is UserRole

    def test_user_status_enum(self):
        assert User.__table__.c.status.type.enum_class is AccountStatus

    def test_credential_type_enum(self):
        assert Credential.__table__.c.type.type.enum_class is CredentialType

    def test_invite_code_enums(self):
        assert InviteCode.__table__.c.channel.type.enum_class is InviteChannel
        assert InviteCode.__table__.c.status.type.enum_class is InviteCodeStatus
