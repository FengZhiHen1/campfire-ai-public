"""SEC-05 HTML 内容安全清洗（已迁移至 py_schemas.utils.html）。

原 sanitize_html 实现已迁移至 py_schemas.utils.html。
本模块保留仅用于向后兼容，新代码请直接导入 py_schemas.utils。
"""

from __future__ import annotations

import warnings

from py_schemas.utils.html import sanitize_html as _sanitize_html


def sanitize_html(text: str) -> str:
    """已弃用：请使用 py_schemas.utils.html.sanitize_html。"""
    warnings.warn(
        "py_schemas.security.sanitizer.sanitize_html is deprecated. "
        "Import from py_schemas.utils.html instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _sanitize_html(text)
