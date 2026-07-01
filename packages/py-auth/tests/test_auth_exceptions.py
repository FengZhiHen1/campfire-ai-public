"""py-auth 异常层次 — 单元测试。"""

from __future__ import annotations

from py_auth.exceptions import HashingError, TokenCreationError, TokenDecodeError


class TestHashingError:
    def test_basic(self):
        e = HashingError("哈希失败")
        assert e.message == "哈希失败"
        assert isinstance(e, Exception)

    def test_from_exc_chain(self):
        try:
            try:
                raise ValueError("inner")
            except ValueError as inner:
                raise HashingError(f"包装: {inner}") from inner
        except HashingError as e:
            assert "包装" in str(e)
            assert e.__cause__ is not None


class TestTokenCreationError:
    def test_basic(self):
        e = TokenCreationError("签发失败")
        assert e.message == "签发失败"


class TestTokenDecodeError:
    def test_basic(self):
        e = TokenDecodeError("格式无效")
        assert e.message == "格式无效"
