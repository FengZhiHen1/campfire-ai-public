"""PROF-05 档案隐私控制 + PROF-01 个人档案管理 — ORM 模型定义。

PROF-05 部分：teacher_links 表（家属-老师关联关系表）。
PROF-01 部分：profiles 表（个人档案主表）。

teacher_links 表用于存储家属（profile owner）与老师/专家之间的
关联关系。每次档案访问请求到达时，PrivacyGuard 通过实时查询此表
（WHERE unlinked_at IS NULL）判定请求人是否与目标档案存在有效关联。

profiles 表是 PROF-01 的核心数据表，存储每个患者的个人档案信息。
使用 JSONB 存储多选标签字段（sensory_features、triggers），
利用 GIN 索引支持下游 PROF-02 的标签过滤查询。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ===========================================================================
# PROF-01 — Profile ORM 模型
# ===========================================================================


class Profile(Base):
    """个人档案 ORM 模型。

    映射 profiles 表，存储患者的个人档案信息。
    每个档案属于一个家属用户（caregiver_id），
    患者数据严格按 caregiver_id 物理隔离。

    Attributes:
        profile_id: UUID v4 主键，由服务端 uuid.uuid4() 生成。
        caregiver_id: 所属家属用户 UUID，建立索引支持按用户查询。
        nickname: 档案昵称，可选，最长 10 字符。
        birth_date: 患者出生日期，用于实时计算年龄区间。
        diagnosis_type: 诊断类型枚举值（ASD/疑似ASD/其他发育障碍）。
        primary_behavior: 主要行为类型枚举值。
        language_level: 语言水平枚举值，可选。
        sensory_features: 感官特征列表，JSONB 数组存储。
        triggers: 已知触发因素列表，JSONB 数组存储。
        medication_notes: 用药备注，可选，最长 200 字符。
        is_default: 是否为当前家属账号的默认档案。
        created_at: 记录创建时间（由 TimestampMixin 语义提供）。
        updated_at: 记录最后更新时间，用作乐观锁版本。
    """

    __tablename__ = "profiles"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID v4 主键",
    )
    caregiver_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        index=True,
        comment="所属家属用户 UUID",
    )
    nickname: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        default=None,
        comment="档案昵称，最长 10 字符",
    )
    birth_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="患者出生日期",
    )
    diagnosis_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="诊断类型（ASD/疑似ASD/其他发育障碍）",
    )
    primary_behavior: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="主要行为类型",
    )
    language_level: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        comment="语言水平",
    )
    sensory_features: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="感官特征列表（JSONB 数组）",
    )
    triggers: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="已知触发因素列表（JSONB 数组）",
    )
    medication_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="用药备注",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否为当前家属账号的默认档案",
    )
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
        comment="记录最后更新时间（乐观锁版本）",
    )

    def __repr__(self) -> str:
        return (
            f"<Profile(profile_id={self.profile_id!r}, "
            f"caregiver_id={self.caregiver_id!r}, "
            f"nickname={self.nickname!r}, "
            f"is_default={self.is_default!r})>"
        )


# ===========================================================================
# PROF-05 — TeacherLink ORM 模型（保持不变）
# ===========================================================================


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
    "Profile",
    "TeacherLink",
]
