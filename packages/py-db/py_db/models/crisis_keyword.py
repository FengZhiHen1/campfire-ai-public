"""CSLT-01 危机分级判定 — CrisisKeyword ORM 模型。

映射 crisis_keywords 表，存储危机判定的关键词词库。
关键词通过 AC 自动机编译为 goto/failure/output 三表用于高效匹配。

字段说明：
    keyword:          关键词原文（如"撞墙"、"自伤"）
    category:         关键词分类（severe / moderate / mild）
    trigger_rule_id:  触发规则编号（如 KW_SELF_HARM_001）
    is_active:        是否启用（软删除支持，仅加载 is_active=true 的记录）
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CrisisKeyword(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """危机判定关键词 ORM 模型。

    映射 PostgreSQL crisis_keywords 表，关键词词库的持久化存储。
    管理员通过通用 CRUD API 管理此表，变更后通过 Redis Pub/Sub 通知热加载。

    Attributes:
        id: UUID v4 主键（由 UUIDPrimaryKeyMixin 提供）。
        keyword: 关键词原文，长度不超过 100 字符。
        category: 关键词分类（severe / moderate / mild）。
        trigger_rule_id: 触发规则编号（如 KW_SELF_HARM_001）。
        is_active: 是否启用。词库加载时仅查询 is_active=true 的记录。
        created_at: 记录创建时间（由 TimestampMixin 提供）。
        updated_at: 记录最后更新时间（由 TimestampMixin 提供）。
    """

    __tablename__ = "crisis_keywords"

    keyword: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="关键词原文，长度不超过 100 字符",
    )
    category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="关键词分类（severe / moderate / mild）",
    )
    trigger_rule_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="触发规则编号，如 KW_SELF_HARM_001",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否启用。仅加载 is_active=true 的记录",
    )

    def __repr__(self) -> str:
        return (
            f"<CrisisKeyword(id={self.id!r}, keyword={self.keyword!r}, "
            f"category={self.category!r}, trigger_rule_id={self.trigger_rule_id!r})>"
        )


__all__ = ["CrisisKeyword"]
