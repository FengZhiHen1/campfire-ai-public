"""CASE-04 CaseChunk ORM 模型 — case_chunks 表映射。

存储已向量化的案例文本切片和嵌入向量，供 CSLT-02 RAG 语义检索消费。

注意：embedding 列（vector(1024)）是 pgvector 自定义类型，不在 ORM 层映射。
SQL 层面的类型转换和读写均通过原生 SQL 完成：
  - 写入：raw INSERT 使用 ::vector(1024) 类型转换（见 index_writer.py）
  - 建表：Alembic 迁移脚本通过原生 SQL 创建 vector 列和 HNSW 索引
  - 读取：由 CSLT-02 模块通过原生 SQL 或自定义 TypeDecorator 处理
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """案例向量切片 ORM 模型。

    映射 PostgreSQL case_chunks 表，存储案例卡片向量化后的文本切片、
    1024 维嵌入向量（pgvector）和结构化元数据。

    embedding 列（vector(1024)）是 pgvector 自定义类型，不在 ORM 层映射。
    CSLT-02 RAG 语义检索引擎通过原生 SQL 和 pgvector <=> 操作符访问嵌入向量。

    Attributes:
        id: UUID v4 主键。
        case_id: 关联的案例标识（FK → cases.id）。
        chunk_text: 完整四要素拼接文本。
        chunk_type: 切片所属的案例四要素类型（scene/behavior/intervention/result）。
        metadata: JSONB 结构化元数据（behavior_type, age_range, severity, evidence_level, status, vectorized, case_title, case_created_at, source, applicable_tags）。
        created_at: 记录创建时间（由 TimestampMixin 提供）。
        updated_at: 记录最后更新时间（由 TimestampMixin 提供）。
    """

    __tablename__ = "case_chunks"

    case_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的案例标识，FK → cases.case_id",
    )
    chunk_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="四要素拼接文本（场景 + 行为 + 干预 + 结果）",
    )
    chunk_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="切片所属的案例四要素类型：scene / behavior / intervention / result",
    )
    chunk_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment=(
            "结构化元数据：behavior_type, age_range, emotion_level, "
            "evidence_level, case_title, case_created_at, source, "
            "status, vectorized, applicable_tags"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CaseChunk(id={self.id!r}, case_id={self.case_id!r})>"
        )


__all__ = ["CaseChunk"]
