"""py-storage 测试夹具 — 注入 mock 模块解决 Windows 环境下 python-magic DLL 缺失问题。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_native_deps(monkeypatch):
    """全局 fixture：在测试期间用 mock 替代 python-magic 和 py_config.security。

    python-magic 在 Windows 上依赖 libmagic DLL（通常不可用），
    py_config.security 依赖 .env 环境变量（测试环境可能未配置）。
    在模块首次导入后通过 monkeypatch 覆盖已缓存的模块属性，
    同时处理 DefaultFileValidator 方法内部的惰性 import（会命中 sys.modules）。
    """
    # Mock magic 模块（必须包含 from_buffer 方法）
    fake_magic = MagicMock(name="magic")
    fake_magic.from_buffer.return_value = "image/png"

    # Mock py_config.security 模块
    fake_security = MagicMock(name="py_config.security")
    fake_get_config = MagicMock(name="get_security_config")
    fake_get_config.return_value.ALLOWED_FILE_EXTENSIONS = [
        "png",
        "jpg",
        "jpeg",
        "pdf",
        "docx",
    ]
    fake_security.get_security_config = fake_get_config

    # 注入到 sys.modules（惰性 import 会在 sys.modules 中查找）
    sys.modules["magic"] = fake_magic
    _prev_security = sys.modules.get("py_config.security")
    sys.modules["py_config.security"] = fake_security

    yield

    # 恢复原始模块，避免污染其他测试模块
    del sys.modules["magic"]
    if _prev_security is not None:
        sys.modules["py_config.security"] = _prev_security
    else:
        del sys.modules["py_config.security"]
