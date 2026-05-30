"""py-llm 测试共享夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# conftest 由 pytest 作为插件加载，此时 tests/ 目录尚未加入 sys.path
_sys_path_needs_fix = str(Path(__file__).resolve().parent)
if _sys_path_needs_fix not in sys.path:
    sys.path.insert(0, _sys_path_needs_fix)

from helpers import NormalClient, SpyClient


@pytest.fixture
def default_messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "Hello"}]


@pytest.fixture
def client() -> NormalClient:
    return NormalClient()


@pytest.fixture
def spy_client() -> SpyClient:
    return SpyClient()
