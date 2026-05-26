"""SQLAlchemy 2.0 声明式基类与共享 Mixin。

为 Alembic autogenerate 提供 target_metadata 入口。
ORM 模型继承此 Base 以获得声明式映射能力。

Usage:
    from py_db.models.base import Base

    class User(Base):
        __tablename__ = "users"
        ...
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

# ---------------------------------------------------------------------------
# 命名约定 — Alembic autogenerate 使用此约定生成约束名称
# ---------------------------------------------------------------------------

_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# ---------------------------------------------------------------------------
# 声明式基类
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类。

    所有 ORM 模型必须继承此类。Alembic 通过 ``Base.metadata`` 获取
    完整的表结构定义用于 autogenerate 和迁移管理。

    metadata 使用统一命名约定，确保 Alembic 生成的约束名称可预测。
    """

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


# ---------------------------------------------------------------------------
# 共享 Mixin — UUID 主键 + 自动时间戳
# ---------------------------------------------------------------------------


class TimestampMixin:
    """自动管理 created_at / updated_at 时间戳的 Mixin。

    子类直接多重继承即可获得时间戳字段：
        class User(Base, TimestampMixin):
            ...
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="记录创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="记录最后更新时间",
    )


class UUIDPrimaryKeyMixin:
    """UUID v4 主键 Mixin。

    使用 Python uuid.uuid4 生成主键值，避免数据库自增序列冲突。
    """

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
