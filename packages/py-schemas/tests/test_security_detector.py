"""SEC-05 输入校验防护 — detect_security_threat 单元测试。
"""

from __future__ import annotations

from py_schemas.utils.security import detect_security_threat
from py_schemas.security.validation_schemas import SecurityDetectionType


class TestDetectSecurityThreat:
    def test_clean_input(self):
        assert detect_security_threat({"name": "张三", "age": "25"}) is None

    def test_sql_injection_union_select(self):
        result = detect_security_threat({"query": "UNION SELECT * FROM users"})
        assert result == SecurityDetectionType.sql_injection

    def test_sql_injection_drop_table(self):
        result = detect_security_threat({"query": "DROP TABLE users"})
        assert result == SecurityDetectionType.sql_injection

    def test_sql_injection_1_equals_1(self):
        result = detect_security_threat({"query": "1=1"})
        assert result == SecurityDetectionType.sql_injection

    def test_sql_injection_comment(self):
        result = detect_security_threat({"query": "admin'--"})
        assert result == SecurityDetectionType.sql_injection

    def test_xss_script_tag(self):
        result = detect_security_threat({"content": "<script>alert(1)</script>"})
        assert result == SecurityDetectionType.xss_payload

    def test_xss_javascript_url(self):
        result = detect_security_threat({"content": "javascript:void(0)"})
        assert result == SecurityDetectionType.xss_payload

    def test_xss_onerror(self):
        result = detect_security_threat({"content": '<img onerror="alert(1)">'})
        assert result == SecurityDetectionType.xss_payload

    def test_xss_iframe(self):
        result = detect_security_threat({"content": '<iframe src="http://evil.com"></iframe>'})
        assert result == SecurityDetectionType.xss_payload

    def test_xss_eval(self):
        result = detect_security_threat({"content": "eval('alert(1)')"})
        assert result == SecurityDetectionType.xss_payload

    def test_xss_document_cookie(self):
        result = detect_security_threat({"content": "document.cookie"})
        assert result == SecurityDetectionType.xss_payload

    def test_malformed_field_name(self):
        result = detect_security_threat({'<script': "value"})
        assert result == SecurityDetectionType.malformed_request

    def test_nested_dict_clean(self):
        result = detect_security_threat({"user": {"name": "张三", "data": {"key": "value"}}})
        assert result is None

    def test_nested_dict_threat(self):
        result = detect_security_threat({"user": {"name": "<script>alert(1)</script>"}})
        assert result == SecurityDetectionType.xss_payload

    def test_nested_list_threat(self):
        result = detect_security_threat({"items": ["safe", "DROP TABLE users"]})
        assert result == SecurityDetectionType.sql_injection

    def test_non_string_values_ignored(self):
        result = detect_security_threat({"count": 42, "flag": True, "ratio": 3.14})
        assert result is None

    def test_empty_dict(self):
        assert detect_security_threat({}) is None

    def test_deeply_nested_exceeds_max(self):
        deeply_nested = {}
        current = deeply_nested
        for _ in range(10):
            current["next"] = {}
            current = current["next"]
        result = detect_security_threat(deeply_nested)
        assert result == SecurityDetectionType.malformed_request

    def test_sql_injection_case_insensitive(self):
        result = detect_security_threat({"query": "drop table users"})
        assert result == SecurityDetectionType.sql_injection
