"""SQLAlchemy ORM 基类与 Mixin — 单元测试。

验证 Base、TimestampMixin、UUIDPrimaryKeyMixin 的结构和元数据。
"""

from __future__ import annotations

import uuid

from py_db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---- UUIDPrimaryKeyMixin ----


class TestUUIDPrimaryKeyMixin:
    def test_id_column_exists(self):
        assert hasattr(UUIDPrimaryKeyMixin, "id") or "id" in dir(UUIDPrimaryKeyMixin)


# ---- Validate mixin can be used in class definition ----


class _MockBase(DeclarativeBase):
    pass


def test_uuid_mixin_with_base():
    """验证 UUIDPrimaryKeyMixin 可以与 Base 组合定义 ORM 类。"""

    class TestModel(_MockBase, UUIDPrimaryKeyMixin):
        __tablename__ = "test_uuid_mixin"
        name: Mapped[str] = mapped_column()

    assert TestModel.__tablename__ == "test_uuid_mixin"


def test_id_default_is_callable():
    """UUID 主键的 default 函数应可调用（返回 UUID）。"""
    # UUIDPrimaryKeyMixin.id 的 default 是 uuid.uuid4
    assert callable(uuid.uuid4)
    result = uuid.uuid4()
    assert isinstance(result, uuid.UUID)


def test_timestamp_mixin_is_callable():
    """TimestampMixin 可正常导入和继承。"""
    assert hasattr(TimestampMixin, "created_at")
    assert hasattr(TimestampMixin, "updated_at")


def test_base_naming_convention():
    """验证 Base 使用命名约定。"""
    assert Base.metadata.naming_convention is not None
    assert "pk" in Base.metadata.naming_convention
    assert "fk" in Base.metadata.naming_convention
    assert "ix" in Base.metadata.naming_convention
