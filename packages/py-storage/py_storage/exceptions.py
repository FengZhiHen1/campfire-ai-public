"""SEC-01 文件安全 — 自定义异常。

- FileTooLargeError: 文件大小超过类型上限
"""

from __future__ import annotations


class FileTooLargeError(Exception):
    """文件大小超过类型允许的上限。

    触发条件：
    - 图片类（jpg/jpeg/png）: > 5MB
    - 文档类（pdf/docx）: > 10MB
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


__all__ = [
    "FileTooLargeError",
]
