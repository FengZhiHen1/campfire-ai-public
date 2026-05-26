"""AUTH-01 用户注册 — User ORM 模型。

定义 users 表的 SQLAlchemy 2.0 声明式映射模型。
User 模型作为 AUTH-01（用户注册）、AUTH-02（用户登录）、AUTH-04（RBAC 鉴权）
等多个认证子模块的共享数据模型。

UUID 主键由 PostgreSQL gen_random_uuid() 在数据库层面生成——
当前 Mixin 使用 Python uuid.uuid4 作为应用层后备，
实际部署时通过 Alembic 迁移覆盖 server_default。
"""

from __future__ import annotations

from sqlalchemy import Enum as sa_Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from py_schemas.auth import UserRole


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """用户账号 ORM 模型。

    映射 PostgreSQL users 表，存储用户身份标识、认证凭证和角色信息。
    用户名和手机号分别通过大小写不敏感唯一索引和精确唯一索引保证全局唯一性。

    Attributes:
        id: UUID v4 主键（由 UUIDPrimaryKeyMixin 提供）。
        username: 登录名称，全局唯一（大小写不敏感）。
        password_hash: bcrypt 密码哈希值，以 $2b$ 或 $2a$ 开头，长度 >= 60。
        role: 用户角色（family/teacher/expert/admin/maintainer）。
        phone: 中国大陆 11 位手机号，全局唯一。
        real_name: 真实姓名，家属和老师可选。
        created_at: 记录创建时间（由 TimestampMixin 提供）。
        updated_at: 记录最后更新时间（由 TimestampMixin 提供）。
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
        comment="登录名称，全局唯一（大小写不敏感唯一性由 Repository 层 LOWER() 查询保证）",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt 哈希值，以 $2b$ 或 $2a$ 开头",
    )
    role: Mapped[UserRole] = mapped_column(
        sa_Enum(UserRole, name="user_role"),
        nullable=False,
        comment="用户角色（family/teacher/expert/admin/maintainer）",
    )
    phone: Mapped[str] = mapped_column(
        String(11),
        unique=True,
        index=True,
        nullable=False,
        comment="中国大陆 11 位手机号",
    )
    real_name: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="真实姓名，家属和老师可选填",
    )

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id!r}, username={self.username!r}, "
            f"role={self.role.value!r})>"
        )


__all__ = ["User"]
