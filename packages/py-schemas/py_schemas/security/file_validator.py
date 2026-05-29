"""SEC-05 文件上传安全校验（已迁移至 py_schemas.utils.files）。

原 validate_file 实现及私有辅助函数已迁移至 py_schemas.utils.files。
本模块保留仅用于向后兼容，新代码请直接导入 py_schemas.utils。
"""

from __future__ import annotations

import warnings
from typing import Any

from py_schemas.security.validation_schemas import FileValidationResult, FileValidationRule

# 模块级 re-export：私有辅助函数供测试使用
# 延迟导入以避免与 security/__init__.py 循环依赖


def __getattr__(name: str):
    """延迟导入私有辅助函数以打破循环依赖。"""
    if name in ("_detect_mime_type", "_extract_extension"):
        from py_schemas.utils import files as _files_mod

        return getattr(_files_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def validate_file(
    file: Any,
    rules: FileValidationRule,
) -> FileValidationResult:
    """已弃用：请使用 py_schemas.utils.files.validate_file。"""
    from py_schemas.utils.files import validate_file as _validate_file

    warnings.warn(
        "py_schemas.security.file_validator.validate_file is deprecated. "
        "Import from py_schemas.utils.files instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return await _validate_file(file, rules)
