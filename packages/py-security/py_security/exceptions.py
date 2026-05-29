"""py-security 异常层次定义。

模块: py_security.exceptions
职责: 定义 PII 检测模块的自定义异常，支持调用方精确捕获和处理。
数据来源:
  - 无外部数据来源（纯异常定义层）
边界:
  - 依赖: 仅 Python 标准库
  - 被依赖: pii_contract.py（前置/后置校验抛出）、pii_detector.py（实现中抛出）
禁止行为:
  - 禁止在业务代码中返回错误字典或 None 替代抛出异常
  - 禁止裸捕获异常后静默吞掉（必须记录日志或重新抛出）
"""

from __future__ import annotations


class PiiDetectionError(Exception):
    """PII 检测异常基类。

    所有与 PII 检测流程相关的错误均从此基类派生。
    调用方可通过捕获此类型统一处理所有检测异常。
    """

    def __init__(self, message: str, *, pii_type: str | None = None) -> None:
        """
        前置: message 必须是非空字符串
        后置: self.pii_type 记录关联的 PII 类型（如有）
        """
        super().__init__(message)
        self.pii_type: str | None = pii_type


class PiiPatternCompileError(PiiDetectionError):
    """PII 正则模式编译失败。

    前置: pattern_str 是导致编译失败的正则字符串
    后置: 异常消息包含原始编译错误信息
    当某个 PII 类型的正则模式无法编译时抛出。
    调用方可根据安全策略决定是否降级（跳过该模式）或向上传播。
    """

    def __init__(self, pattern_str: str, original_error: str) -> None:
        """
        前置: pattern_str 是导致编译失败的原始正则字符串
        前置: original_error 是 re.error 的错误消息
        """
        super().__init__(
            f"PII 正则模式编译失败: {original_error}",
            pii_type=None,
        )
        self.pattern_str: str = pattern_str
        self.original_error: str = original_error


class PiiInputValidationError(PiiDetectionError):
    """PII 检测输入校验失败。

    前置: reason 必须是非空字符串，描述具体的校验失败原因
    当输入文本不满足检测前置条件时抛出（如 None、非字符串类型）。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"PII 检测输入校验失败: {reason}")


__all__ = [
    "PiiDetectionError",
    "PiiPatternCompileError",
    "PiiInputValidationError",
]
