"""红线关键词 ORM 模型（ADR-008 二元安全门目标态）。

映射 redline_keywords 表——红线硬拦截词库（命中即红线，二元语义无分级）。
词库由运营持续迭代（红线安全门 §八：周期性审查红线事件反向补充）。

字段说明：
    keyword:          关键词原文（如"撞墙"、"吞药"）
    trigger_rule_id:  触发规则编号（如 KW_SELF_HARM_001）
    is_active:        是否启用（软删除支持，仅加载 is_active=true 的记录）
"""

# @contract — redline_keywords 表 Schema 契约

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RedlineKeyword(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """红线关键词 ORM 模型（二元安全门词库）。

    与旧 crisis_keywords 的差异：无 category 三级分类——
    命中即红线（ADR-008 二元判定）。
    """

    __tablename__ = "redline_keywords"

    keyword: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="关键词原文，长度不超过 100 字符",
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
        comment="是否启用。词库加载仅查询 is_active=true 的记录",
    )

    def __repr__(self) -> str:
        return f"<RedlineKeyword(id={self.id!r}, keyword={self.keyword!r}, rule={self.trigger_rule_id!r})>"


__all__ = ["RedlineKeyword"]
