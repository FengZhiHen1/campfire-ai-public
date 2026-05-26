"""SEC-05 输入校验防护 — 安全威胁检测。

提供 detect_security_threat() 纯函数，对 Pydantic 校验通过的数据
执行 SQL 注入/XSS 载荷/格式异常检测。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from py_schemas.security.validation_schemas import SecurityDetectionType

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 预编译正则模式（不区分大小写）
# ---------------------------------------------------------------------------

_SQL_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"UNION\s+SELECT", re.IGNORECASE),
    re.compile(r"DROP\s+TABLE", re.IGNORECASE),
    re.compile(r"ALTER\s+TABLE", re.IGNORECASE),
    re.compile(r"INSERT\s+INTO", re.IGNORECASE),
    re.compile(r"DELETE\s+FROM", re.IGNORECASE),
    re.compile(r"\b1\s*=\s*1\b", re.IGNORECASE),
    re.compile(r"OR\s+'1'\s*=\s*'1'?", re.IGNORECASE),
    re.compile(r"--"),          # SQL 注释注入
    re.compile(r";"),           # 语句终止符
]

_XSS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"onerror\s*=", re.IGNORECASE),
    re.compile(r"onload\s*=", re.IGNORECASE),
    re.compile(r"onclick\s*=", re.IGNORECASE),
    re.compile(r"<iframe", re.IGNORECASE),
    re.compile(r"<img[^>]*src\s*=\s*.*javascript:", re.IGNORECASE | re.DOTALL),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"document\.cookie", re.IGNORECASE),
]

# 字段名含非法字符的模式
_MALFORMED_FIELD_NAME_PATTERN = re.compile(r"[<>\"';&|]")


def _check_string_for_threats(value: str) -> SecurityDetectionType | None:
    """对单个字符串值执行 SQL 注入和 XSS 载荷模式匹配。

    Args:
        value: 待检测的字符串值。

    Returns:
        检测到的威胁类型，无威胁时返回 None。
    """
    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(value):
            return SecurityDetectionType.sql_injection
    for pattern in _XSS_PATTERNS:
        if pattern.search(value):
            return SecurityDetectionType.xss_payload
    return None


def _traverse_and_detect(
    data: Any, depth: int = 0, max_depth: int = 5
) -> SecurityDetectionType | None:
    """递归遍历字典/列表，检测安全威胁。

    Args:
        data: 待遍历的数据（dict、list、str 或其他类型）。
        depth: 当前递归深度。
        max_depth: 允许的最大嵌套深度。

    Returns:
        检测到的威胁类型，无威胁时返回 None。
    """
    if depth > max_depth:
        return SecurityDetectionType.malformed_request

    if isinstance(data, dict):
        for key, value in data.items():
            # 检查字段名是否含非法字符
            if isinstance(key, str) and _MALFORMED_FIELD_NAME_PATTERN.search(key):
                return SecurityDetectionType.malformed_request
            # 递归检查值
            result = _traverse_and_detect(value, depth + 1, max_depth)
            if result is not None:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _traverse_and_detect(item, depth + 1, max_depth)
            if result is not None:
                return result

    elif isinstance(data, str):
        return _check_string_for_threats(data)

    return None


def detect_security_threat(
    validated_data: dict[str, object],
) -> SecurityDetectionType | None:
    """对 Pydantic 校验通过的数据执行 SQL 注入/XSS 载荷/格式异常检测。

    检测规则（不区分大小写，正则匹配）：
      - sql_injection: UNION SELECT, DROP TABLE, ALTER TABLE, INSERT INTO,
        DELETE FROM, 1=1, OR '1'='1', --（注释注入）, ;（语句终止）
      - xss_payload: <script, javascript:, onerror=, onload=, onclick=,
        <iframe, <img.*src=javascript, eval(, document.cookie
      - malformed_request: 字段名含字符 <>\"';&| 或嵌套深度超过 5 层

    Args:
        validated_data: Pydantic 校验通过后的字典数据。

    Returns:
        SecurityDetectionType | None: 检测到的威胁类型，无威胁时返回 None。

    Side Effects:
        无。本函数为纯函数，不记录日志（日志由调用方在检测到威胁后写入）。

    Thread Safety:
        本函数内部不维护可变状态，线程安全。
    """
    try:
        return _traverse_and_detect(validated_data)
    except Exception:
        _logger.warning(
            "security_detection_internal_error",
            exc_info=True,
        )
        return None
