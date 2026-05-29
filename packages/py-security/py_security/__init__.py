"""py-security — PII 检测与安全工具包。

模块: py_security
职责: 提供 PII 检测核心功能，支持 5 类中文 PII 匹配：
      真实姓名、手机号码、身份证号、家庭住址、学校名称。
      通过 ABC 模板方法将检测策略与具体实现解耦，
      调用方依赖契约而非具体检测器。
数据来源:
  - PII_PATTERNS (py_security.pii_patterns): 静态正则模式字典
边界:
  - 依赖: 仅 Python 标准库（零外部依赖）
  - 被依赖: api-server 的 PII 检测中间件、案例审核的脱敏检测
"""

from py_security.exceptions import (
    PiiDetectionError,
    PiiInputValidationError,
    PiiPatternCompileError,
)
from py_security.pii_contract import BasePiiDetector
from py_security.pii_detector import RegexPiiDetector
from py_security.pii_patterns import PII_PATTERNS
from py_security.types import (
    DetectedText,
    PiiDetectionResult,
    PiiType,
    PiiWarning,
    PositionIndex,
)

__all__ = [
    # 契约
    "BasePiiDetector",
    # 实现
    "RegexPiiDetector",
    # 类型
    "PiiType",
    "DetectedText",
    "PositionIndex",
    "PiiWarning",
    "PiiDetectionResult",
    # 异常
    "PiiDetectionError",
    "PiiPatternCompileError",
    "PiiInputValidationError",
    # 模式
    "PII_PATTERNS",
]
