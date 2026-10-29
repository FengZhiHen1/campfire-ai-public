"""资料库 HTTP 查询与工具使用同一长度边界，超限不能进入检索链。"""

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from campfire.modules.library import routes


@pytest.mark.asyncio
@pytest.mark.parametrize(("length", "status", "calls"), [(500, 503, 1), (501, 422, 0)])
async def test_query_length_is_checked_before_retrieval(
    monkeypatch: pytest.MonkeyPatch, length: int, status: int, calls: int
) -> None:
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.current_account] = lambda: "synthetic-account"
    retrieve = AsyncMock(side_effect=RuntimeError("synthetic unavailability"))
    monkeypatch.setattr(routes, "_run_retrieval", retrieve)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/library/items", params={"query": "x" * length})
    assert response.status_code == status
    assert retrieve.await_count == calls
