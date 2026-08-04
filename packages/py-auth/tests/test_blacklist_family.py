"""Token 家族吊销 — RedisBlacklist 家族语义单元测试（ADR-013 目标态）。

覆盖认证与访问 §5.2 会话安全增强：
- 每次登录创建 Token 家族（family_id），轮换在同一家族内延续
- 已使用的 refresh 被再次出示 → 吊销全家族
- logout / disabled / role·status 变更 → 家族吊销
- Redis 故障 fail-open（维持现状语义）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from py_auth.blacklist import RedisBlacklist


@pytest.fixture
def blacklist_with_mock_client():
    """构造注入 mock Redis 客户端的 RedisBlacklist。"""
    bl = RedisBlacklist()
    client = MagicMock()
    client.setex = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.exists = AsyncMock(return_value=0)
    bl._client = client
    return bl, client


class TestFamilyRevocation:
    @pytest.mark.asyncio
    async def test_revoke_family_writes_redis_key(self, blacklist_with_mock_client):
        """家族吊销写入 token_family_revoked:{family_id}，TTL=refresh 有效期。"""
        bl, client = blacklist_with_mock_client
        await bl.revoke_family("fam-001")
        client.setex.assert_awaited_once()
        key, ttl, _value = client.setex.await_args.args
        assert key == "token_family_revoked:fam-001"
        assert ttl == 7 * 24 * 3600

    @pytest.mark.asyncio
    async def test_is_family_revoked_hit(self, blacklist_with_mock_client):
        bl, client = blacklist_with_mock_client
        client.exists.return_value = 1
        assert await bl.is_family_revoked("fam-001") is True
        client.exists.assert_awaited_once_with("token_family_revoked:fam-001")

    @pytest.mark.asyncio
    async def test_is_family_revoked_miss(self, blacklist_with_mock_client):
        bl, _client = blacklist_with_mock_client
        assert await bl.is_family_revoked("fam-002") is False


class TestFamilyFailOpen:
    @pytest.mark.asyncio
    async def test_revoke_family_fail_open(self):
        """Redis 不可用时吊销静默降级（fail-open），不抛异常。"""
        bl = RedisBlacklist()
        client = MagicMock()
        client.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        bl._client = client
        await bl.revoke_family("fam-003")  # 不抛异常

    @pytest.mark.asyncio
    async def test_is_family_revoked_fail_open_returns_false(self):
        """Redis 不可用时查询降级返回 False（放行，可用性优先）。"""
        bl = RedisBlacklist()
        client = MagicMock()
        client.exists = AsyncMock(side_effect=ConnectionError("redis down"))
        bl._client = client
        assert await bl.is_family_revoked("fam-003") is False

    @pytest.mark.asyncio
    async def test_empty_family_id_noop(self, blacklist_with_mock_client):
        bl, client = blacklist_with_mock_client
        await bl.revoke_family("")
        client.setex.assert_not_awaited()
        assert await bl.is_family_revoked("") is False


class TestExistingBlacklistSemanticsKept:
    """既有黑名单/refresh 单次使用语义保留（回归防护）。"""

    @pytest.mark.asyncio
    async def test_add_to_blacklist_key_semantics(self, blacklist_with_mock_client):
        bl, client = blacklist_with_mock_client
        await bl.add_to_blacklist("jti-001")
        key, ttl, _ = client.setex.await_args.args
        assert key == "token_blacklist:jti-001"
        assert ttl == 900

    @pytest.mark.asyncio
    async def test_mark_refresh_used_key_semantics(self, blacklist_with_mock_client):
        bl, client = blacklist_with_mock_client
        await bl.mark_refresh_used("jti-002")
        key, ttl, _ = client.setex.await_args.args
        assert key == "refresh_used:jti-002"
        assert ttl == 7 * 24 * 3600
