"""py-storage 异常层次定义。

模块: py_storage.exceptions
职责: 定义文件安全校验模块的自定义异常，支持调用方按校验步骤精确捕获。
数据来源:
  - 无外部数据来源（纯异常定义层）
边界:
  - 依赖: 仅 Python 标准库
  - 被依赖: file_validation_contract.py（前置/后置校验抛出）、file_security.py（实现中抛出）
禁止行为:
  - 禁止在业务代码中返回错误字典或 None 替代抛出异常
  - 禁止裸捕获异常后静默吞掉（必须记录日志或重新抛出）
"""

from __future__ import annotations


class FileValidationError(Exception):
    """文件校验异常基类。

    所有与文件安全校验相关的错误均从此基类派生。
    调用方可通过捕获此类型统一处理所有校验异常。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class FileInputValidationError(FileValidationError):
    """文件校验输入不合法。

    当输入参数不满足校验前置条件时抛出（如 filename 为空、content 非 bytes）。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"文件校验输入不合法: {reason}")


class FileExtensionNotAllowedError(FileValidationError):
    """文件扩展名不在允许白名单中。

    Attributes:
        extension: 被拒绝的扩展名
        allowed: 允许的扩展名列表
    """

    def __init__(self, extension: str, allowed: frozenset[str]) -> None:
        self.extension: str = extension
        self.allowed: frozenset[str] = allowed
        allowed_str = ", ".join(sorted(allowed))
        super().__init__(
            f"文件扩展名 .{extension} 不在允许白名单中。允许的类型：{allowed_str}"
        )


class FileTooLargeError(FileValidationError):
    """文件大小超过类型允许的上限。

    Attributes:
        actual_bytes: 文件实际字节数
        limit_bytes: 该类型允许的最大字节数
        category: 文件类别
    """

    def __init__(self, actual_bytes: int, limit_bytes: int, category: str) -> None:
        self.actual_bytes: int = actual_bytes
        self.limit_bytes: int = limit_bytes
        self.category: str = category
        actual_mb = actual_bytes / (1024 * 1024)
        limit_mb = limit_bytes / (1024 * 1024)
        super().__init__(
            f"{category}大小 {actual_mb:.1f}MB 超过上限 {limit_mb:.0f}MB"
        )


class FileMimeTypeNotAllowedError(FileValidationError):
    """文件 MIME 类型不在允许列表中。"""

    def __init__(self, detected_mime: str, allowed: frozenset[str]) -> None:
        self.detected_mime: str = detected_mime
        self.allowed: frozenset[str] = allowed
        allowed_str = ", ".join(sorted(allowed))
        super().__init__(
            f"文件类型 {detected_mime} 不在允许列表中。允许的类型：{allowed_str}"
        )


class FileMimeDetectionError(FileValidationError):
    """无法检测文件 MIME 类型。"""

    def __init__(self, original_error: str | None = None) -> None:
        msg = "无法检测文件 MIME 类型"
        if original_error:
            msg += f": {original_error}"
        super().__init__(msg)


class FileContentTooShortError(FileValidationError):
    """文件内容过短，无法校验文件头。"""

    def __init__(self, actual_bytes: int, min_required: int) -> None:
        self.actual_bytes: int = actual_bytes
        self.min_required: int = min_required
        super().__init__(
            f"文件内容仅 {actual_bytes} 字节，不足 {min_required} 字节的最小校验长度"
        )


class FileMagicSignatureMismatchError(FileValidationError):
    """文件头魔数签名不匹配。"""

    def __init__(self, extension: str, actual_hex: str) -> None:
        self.extension: str = extension
        self.actual_hex: str = actual_hex
        super().__init__(
            f".{extension} 文件头签名不匹配，实际为 {actual_hex}"
        )


__all__ = [
    "FileValidationError",
    "FileInputValidationError",
    "FileExtensionNotAllowedError",
    "FileTooLargeError",
    "FileMimeTypeNotAllowedError",
    "FileMimeDetectionError",
    "FileContentTooShortError",
    "FileMagicSignatureMismatchError",
]
