"""PROF-05 档案隐私控制 — ORM 模型定义。

新增 teacher_links 表（家属-老师关联关系表）。
同时为已有 ProfessionalNote 模型添加 visible_after_unlink 字段。

teacher_links 表用于存储家属（profile owner）与老师/专家之间的
关联关系。每次档案访问请求到达时，PrivacyGuard 通过实时查询此表
（WHERE unlinked_at IS NULL）判定请求人是否与目标档案存在有效关联。

关联关系生命周期：
  关联活跃 ──unlink──▶ 关联断裂（unlinked_at 设为非 NULL）

乐观锁通过 version 字段实现，在解除关联的 UPDATE 操作中校验版本一致性。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TeacherLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """家属-老师关联关系 ORM 模型。

    映射 teacher_links 表，记录家属（档案拥有者）与老师/专家之间的
    关联关系。有效关联（unlinked_at IS NULL）是该老师/专家访问对应
    档案的权限基础。

    Attributes:
        link_id: UUID v4 主键（由 UUIDPrimaryKeyMixin 提供）。
        profile_id: 目标个人档案 UUID（FK 到 profiles 表，未直接定义外键约束）。
        teacher_id: 关联老师/专家的用户 UUID（FK 到 users 表，未直接定义外键约束）。
        role: 关联角色（teacher / expert），表示被关联用户在档案中的身份。
        unlinked_at: 解除关联的时间戳。NULL 表示关联有效，非 NULL 表示已解除。
        version: 乐观锁版本号，用于并发控制。
        created_at: 记录创建时间（由 TimestampMixin 提供）。
        updated_at: 记录最后更新时间（由 TimestampMixin 提供）。
    """

    __tablename__ = "teacher_links"

    link_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        index=True,
        comment="目标个人档案 UUID",
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        index=True,
        comment="关联老师/专家的用户 UUID",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="关联角色（teacher / expert）",
    )
    unlinked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="解除关联时间戳，NULL 表示关联有效",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="乐观锁版本号",
    )

    def __repr__(self) -> str:
        return (
            f"<TeacherLink(link_id={self.link_id!r}, "
            f"profile_id={self.profile_id!r}, "
            f"teacher_id={self.teacher_id!r}, "
            f"role={self.role!r}, "
            f"unlinked_at={self.unlinked_at!r}, "
            f"version={self.version!r})>"
        )


__all__ = [
    "TeacherLink",
]
