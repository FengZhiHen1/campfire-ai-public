"""py-security — PII 检测与安全工具包。

提供 PII 检测核心功能，支持 5 类中文 PII 正则匹配：
真实姓名、手机号码、身份证号、家庭住址、学校名称。
"""

from py_security.pii_detector import detect_pii
from py_security.pii_patterns import PII_PATTERNS, PiiType

__all__ = [
    "detect_pii",
    "PII_PATTERNS",
    "PiiType",
]
