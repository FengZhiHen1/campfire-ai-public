"""认证域 ORM 模型（ADR-013 目标态）— 身份-凭证分离三表。

- User: 身份主体（手机号全局唯一锚点 + 角色 + 准入状态机）
- Credential: 渠道凭证（password/wechat，(type, identifier) 全局唯一）
- InviteCode: 内测期邀请码（channel 约束可注册角色，条件自增原子消费）

事实源：docs/技术设计/机制/认证与访问.md §2.1 / §4.1。
已废除：username 登录标识、password_hash 内嵌 users 表、device_id 匿名轨。
"""

# @contract — users / credentials / invite_codes 表 Schema 契约

from __future__ import annotations

import uuid
from datetime import datetime

from py_schemas.auth import UserRole
from py_schemas.enums import AccountStatus, CredentialType, InviteChannel, InviteCodeStatus
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as sa_Enum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """用户身份主体 ORM 模型。

    映射 users 表。认证凭证迁移至 credentials 表（身份-凭证分离），
    手机号是唯一登录标识与账号合并锚点（ADR-012/013）。

    Attributes:
        id: UUID v4 主键。
        phone: 中国大陆 11 位手机号，全局唯一。
        real_name: 真实姓名；teacher/expert 必填（准入审核依据），其余可选。
        role: 六角色之一（单角色互斥）。
        status: 账号状态机（active/pending_review/rejected/disabled）。
        reject_reason: 最近一次准入审核驳回原因（rejected 时非空，面向用户展示）。
    """

    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(
        String(11),
        unique=True,
        index=True,
        nullable=False,
        comment="中国大陆 11 位手机号，全局唯一登录标识与账号合并锚点",
    )
    real_name: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="真实姓名；teacher/expert 必填（准入审核依据），其余可选",
    )
    role: Mapped[UserRole] = mapped_column(
        sa_Enum(
            UserRole,
            name="user_role",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        comment="六角色之一（family/volunteer/teacher/expert/admin/maintainer），单角色互斥",
    )
    status: Mapped[AccountStatus] = mapped_column(
        sa_Enum(
            AccountStatus,
            name="account_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=AccountStatus.ACTIVE,
        server_default=AccountStatus.ACTIVE.value,
        comment="账号状态机：active/pending_review/rejected/disabled",
    )
    reject_reason: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="最近一次准入审核驳回原因（rejected 时非空，面向用户展示）",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id!r}, phone={self.phone!r}, role={self.role.value!r}, status={self.status.value!r})>"


class Credential(Base, UUIDPrimaryKeyMixin):
    """渠道凭证 ORM 模型。

    映射 credentials 表。一个用户可挂多个渠道凭证（密码/微信），
    渠道可增删而不动身份主体（认证与访问 §2.1）。

    Attributes:
        id: UUID v4 主键。
        user_id: 所属用户（外键，级联删除）。
        type: 渠道类型：password / wechat（预留）。
        identifier: 渠道内唯一标识：password 渠道为 phone；wechat 渠道为 unionid/openid。
        secret: 凭证机密：password 渠道存 bcrypt 哈希；wechat 渠道为空。
    """

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("type", "identifier", name="uq_credentials_type_identifier"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户（级联删除）",
    )
    type: Mapped[CredentialType] = mapped_column(
        sa_Enum(
            CredentialType,
            name="credential_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        comment="渠道类型：password / wechat（预留）",
    )
    identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="渠道内唯一标识：password 渠道为 phone；wechat 渠道为 unionid/openid",
    )
    secret: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="凭证机密：password 渠道存 bcrypt 哈希；wechat 渠道为空",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="绑定时间",
    )

    def __repr__(self) -> str:
        return f"<Credential(id={self.id!r}, type={self.type.value!r}, identifier={self.identifier!r})>"


class InviteCode(Base):
    """邀请码 ORM 模型（内测期机制，认证与访问 §4.1）。

    映射 invite_codes 表。注册时原子消费（used_count 条件自增防并发复用）。

    Attributes:
        code: 8-12 位可读码（字母数字，剔除易混淆字符），主键。
        channel: demand（可注册 family/volunteer）/ supply（可注册 teacher/expert）。
        max_uses: 可用次数，默认 1。
        used_count: 已用次数。
        expires_at: 过期时间（必填）。
        status: active / revoked。
        created_by: 生成的管理员（批次追溯）。
    """

    __tablename__ = "invite_codes"

    code: Mapped[str] = mapped_column(
        String(12),
        primary_key=True,
        comment="8-12 位可读码（字母数字，剔除易混淆字符）",
    )
    channel: Mapped[InviteChannel] = mapped_column(
        sa_Enum(
            InviteChannel,
            name="invite_channel",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        comment="渠道：demand 需求侧（family/volunteer）/ supply 供给侧（teacher/expert）",
    )
    max_uses: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="可用次数，默认 1；机构批量邀请按人数批量生成单次码",
    )
    used_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="已用次数（注册时条件自增原子消费）",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="过期时间（必填，时长由运营配置）",
    )
    status: Mapped[InviteCodeStatus] = mapped_column(
        sa_Enum(
            InviteCodeStatus,
            name="invite_code_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=InviteCodeStatus.ACTIVE,
        server_default=InviteCodeStatus.ACTIVE.value,
        comment="状态：active / revoked（运营可停用）",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="生成的管理员用户 UUID（批次追溯）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="生成时间",
    )

    def __repr__(self) -> str:
        return f"<InviteCode(code={self.code!r}, channel={self.channel.value!r}, status={self.status.value!r})>"


__all__ = ["User", "Credential", "InviteCode"]
