"""FastAPI 认证依赖注入（MVP） — 单元测试。
"""

from __future__ import annotations

from unittest import mock

import pytest

from py_auth.dependencies import get_current_user


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_with_device_id(self):
        req = mock.MagicMock()
        req.headers.get.return_value = "device-abc-123"
        payload = await get_current_user(req)
        assert "sub" in payload
        assert payload["roles"] == ["family"]
        assert payload["jti"] == "anonymous"
        assert payload["type"] == "access"

    @pytest.mark.asyncio
    async def test_without_device_id_generates_one(self):
        req = mock.MagicMock()
        req.headers.get.return_value = ""
        payload = await get_current_user(req)
        assert "sub" in payload
        assert len(payload["sub"]) > 0

    @pytest.mark.asyncio
    async def test_same_device_id_produces_same_uuid(self):
        req1 = mock.MagicMock()
        req1.headers.get.return_value = "stable-device-id"
        req2 = mock.MagicMock()
        req2.headers.get.return_value = "stable-device-id"
        payload1 = await get_current_user(req1)
        payload2 = await get_current_user(req2)
        assert payload1["sub"] == payload2["sub"]

    @pytest.mark.asyncio
    async def test_return_structure(self):
        req = mock.MagicMock()
        req.headers.get.return_value = "dev-x"
        payload = await get_current_user(req)
        assert set(payload.keys()) == {"sub", "roles", "jti", "exp", "type"}
