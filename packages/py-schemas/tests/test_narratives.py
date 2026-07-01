"""L1 原始叙事层 — Pydantic Schema 单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from py_schemas.enums.case_enums import CaseStatus
from py_schemas.narratives import (
    NarrativeCreateRequest,
    NarrativeListItem,
    NarrativeResponse,
    NarrativeUpdate,
)
from pydantic import ValidationError


class TestNarrativeCreateRequest:
    def test_valid(self):
        req = NarrativeCreateRequest(
            title="测试叙事",
            narrative="这是一个详细的干预故事" * 10,
            source_type="专家撰写",
        )
        assert req.title == "测试叙事"

    def test_empty_title(self):
        with pytest.raises(ValidationError):
            NarrativeCreateRequest(title="", narrative="内容", source_type="专家撰写")

    def test_narrative_too_long(self):
        with pytest.raises(ValidationError):
            NarrativeCreateRequest(title="测试", narrative="x" * 5001, source_type="专家撰写")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            NarrativeCreateRequest(
                title="测试",
                narrative="内容",
                source_type="专家撰写",
                extra="bad",
            )


class TestNarrativeResponse:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        resp = NarrativeResponse(
            narrative_id="NAR-001",
            title="叙事",
            narrative="内容",
            source_type="专家撰写",
            author_id="user-1",
            status=CaseStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        assert resp.narrative_id == "NAR-001"


class TestNarrativeListItem:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        item = NarrativeListItem(
            narrative_id="NAR-001",
            title="叙事",
            source_type="专家撰写",
            author_id="user-1",
            status="draft",
            card_count=3,
            created_at=now,
        )
        assert item.card_count == 3


class TestNarrativeUpdate:
    def test_partial_update(self):
        req = NarrativeUpdate(title="新标题")
        assert req.title == "新标题"
        assert req.narrative is None

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            NarrativeUpdate(extra="bad")
