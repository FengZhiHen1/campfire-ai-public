"""SEC-05 输入校验防护 — sanitize_html 单元测试。
"""

from __future__ import annotations

import pytest

from py_schemas.utils.html import sanitize_html


class TestSanitizeHtml:
    def test_plain_text_passthrough(self):
        assert sanitize_html("普通文本") == "普通文本"

    def test_escape_script_tag(self):
        result = sanitize_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_escape_ampersand(self):
        assert sanitize_html("a & b") == "a &amp; b"

    def test_escape_double_quote(self):
        assert "&quot;" in sanitize_html('hello"world')

    def test_escape_single_quote(self):
        result = sanitize_html("it's")
        assert "&#x27;" in result

    def test_idempotent(self):
        text = "<script>alert('xss')</script>"
        once = sanitize_html(text)
        twice = sanitize_html(once)
        assert once == twice

    def test_empty_string(self):
        assert sanitize_html("") == ""

    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError):
            sanitize_html(123)

    def test_type_error_on_none(self):
        with pytest.raises(TypeError):
            sanitize_html(None)

    def test_type_error_on_list(self):
        with pytest.raises(TypeError):
            sanitize_html(["a", "b"])

    def test_chinese_text_preserved(self):
        result = sanitize_html("你好世界")
        assert result == "你好世界"

    def test_mixed_content(self):
        result = sanitize_html("用户<b>张三</b>提交了数据")
        assert "&lt;b&gt;" in result
        assert "&lt;/b&gt;" in result
        assert "张三" in result
