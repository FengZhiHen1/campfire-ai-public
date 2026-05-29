"""PII 检测模块 — 单元测试。

覆盖 RegexPiiDetector.detect()：5 类 PII 检测、边界输入、类型守卫、
异常传播、后置校验。
"""

from __future__ import annotations

import pytest

from py_security.exceptions import PiiInputValidationError, PiiPatternCompileError
from py_security.pii_detector import RegexPiiDetector
from py_security.types import (
    DetectedText,
    PiiDetectionResult,
    PiiType,
    PiiWarning,
    PositionIndex,
)


class TestRegexPiiDetector:
    # ---- 真实姓名 ----

    def test_detect_chinese_name(self):
        detector = RegexPiiDetector()
        result = detector.detect("患者叫张三，今年5岁")
        assert result.has_pii is True
        types = [w.pii_type for w in result.warnings]
        assert PiiType.REAL_NAME in types

    def test_detect_multiple_names(self):
        detector = RegexPiiDetector()
        result = detector.detect("张三和李四一起参与了活动，王五在旁边观察")
        names = [w for w in result.warnings if w.pii_type == PiiType.REAL_NAME]
        assert len(names) >= 2

    # ---- 手机号码 ----

    def test_detect_phone(self):
        detector = RegexPiiDetector()
        result = detector.detect("请联系13800138000")
        assert result.has_pii is True
        types = [w.pii_type for w in result.warnings]
        assert PiiType.PHONE in types

    def test_detect_phone_with_separators(self):
        detector = RegexPiiDetector()
        result = detector.detect("电话是13800138000，微信同号")
        assert result.has_pii is True
        phones = [w for w in result.warnings if w.pii_type == PiiType.PHONE]
        assert len(phones) >= 1

    def test_no_false_phone_detection(self):
        """10位数字不应被识别为手机号。"""
        detector = RegexPiiDetector()
        result = detector.detect("编号1234567890")
        phones = [w for w in result.warnings if w.pii_type == PiiType.PHONE]
        assert len(phones) == 0

    # ---- 身份证号 ----

    def test_detect_id_card(self):
        detector = RegexPiiDetector()
        result = detector.detect("证件号 110101199003071234 已记录")
        assert result.has_pii is True
        types = [w.pii_type for w in result.warnings]
        assert PiiType.ID_CARD in types

    # ---- 家庭住址 ----

    def test_detect_address(self):
        detector = RegexPiiDetector()
        result = detector.detect("家庭住址在北京市朝阳区某某路123号")
        assert result.has_pii is True
        types = [w.pii_type for w in result.warnings]
        assert PiiType.HOME_ADDRESS in types

    # ---- 学校名称 ----

    def test_detect_school(self):
        detector = RegexPiiDetector()
        result = detector.detect("就读于北京市第一中学")
        assert result.has_pii is True
        types = [w.pii_type for w in result.warnings]
        assert PiiType.SCHOOL_NAME in types

    # ---- 无 PII 输入 ----

    def test_clean_text(self):
        detector = RegexPiiDetector()
        result = detector.detect("abc 123 !@#")
        assert result.has_pii is False
        assert result.warnings == ()

    # ---- 边界输入 ----

    def test_empty_string(self):
        detector = RegexPiiDetector()
        with pytest.raises(PiiInputValidationError):
            detector.detect("")

    def test_whitespace_only(self):
        detector = RegexPiiDetector()
        with pytest.raises(PiiInputValidationError):
            detector.detect("   \n  \t  ")

    def test_non_string_input(self):
        detector = RegexPiiDetector()
        with pytest.raises(PiiInputValidationError):
            detector.detect(12345)  # type: ignore[arg-type]

    # ---- 位置信息 ----

    def test_warning_positions(self):
        detector = RegexPiiDetector()
        result = detector.detect("我叫张三")
        assert result.has_pii is True
        for w in result.warnings:
            assert w.position_start >= 0
            assert w.position_end > w.position_start

    def test_detected_text_in_original(self):
        detector = RegexPiiDetector()
        text = "测试13800138000文本"
        result = detector.detect(text)
        phones = [w for w in result.warnings if w.pii_type == PiiType.PHONE]
        assert len(phones) >= 1
        assert phones[0].detected_text in text

    # ---- to_dict ----

    def test_pii_warning_to_dict(self):
        w = PiiWarning(
            pii_type=PiiType.REAL_NAME,
            detected_text=DetectedText("张三"),
            position_start=PositionIndex(0),
            position_end=PositionIndex(2),
        )
        d = w.to_dict()
        assert d["pii_type"] == "真实姓名"
        assert d["detected_text"] == "张三"

    def test_pii_detection_result_to_dict(self):
        w = PiiWarning(
            pii_type=PiiType.REAL_NAME,
            detected_text=DetectedText("张三"),
            position_start=PositionIndex(0),
            position_end=PositionIndex(2),
        )
        r = PiiDetectionResult(has_pii=True, warnings=(w,))
        d = r.to_dict()
        assert d["has_pii"] is True
        assert len(d["warnings"]) == 1


class TestPiiType:
    def test_values(self):
        assert PiiType.REAL_NAME == "真实姓名"
        assert PiiType.PHONE == "手机号码"
        assert PiiType.ID_CARD == "身份证号"
        assert PiiType.HOME_ADDRESS == "家庭住址"
        assert PiiType.SCHOOL_NAME == "学校名称"

    def test_all_types_have_patterns(self):
        from py_security.pii_patterns import PII_PATTERNS

        for pii_type in PiiType:
            assert pii_type in PII_PATTERNS
            assert len(PII_PATTERNS[pii_type]) > 0


class TestPiiPatternCompileError:
    def test_error_contains_pattern_info(self):
        err = PiiPatternCompileError("[invalid", "bad regex at position 0")
        assert err.pattern_str == "[invalid"
        assert "bad regex" in str(err)
