"""L2 结构化卡片层 — Pydantic Schema 单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from py_schemas.cards import (
    CardCreateRequest,
    CardExtractionResult,
    CardResponse,
    CardUpdate,
)
from py_schemas.enums.case_enums import CaseStatus
from pydantic import ValidationError


class TestCardCreateRequest:
    def test_valid_minimal(self):
        req = CardCreateRequest(
            title="测试卡片",
            scenario="家庭场景",
            behavior_type="自伤",
            age_range=[3, 12],
            severity="重度",
            scene="家庭",
            ebp_labels=["强化"],
            family_category="危机安全",
            immediate_action="立即干预",
            comforting_phrase="安抚话术",
            observation_metrics="观察指标",
            medical_criteria="就医标准",
            evidence_level="机构经验总结",
            contraindications="注意禁忌",
        )
        assert req.title == "测试卡片"
        assert req.is_template is False

    def test_empty_title(self):
        with pytest.raises(ValidationError):
            CardCreateRequest(
                title="",
                scenario="x",
                behavior_type="自伤",
                age_range=[3, 12],
                severity="重度",
                scene="家庭",
                ebp_labels=["强化"],
                family_category="危机安全",
                immediate_action="a",
                comforting_phrase="b",
                observation_metrics="c",
                medical_criteria="d",
                evidence_level="e",
                contraindications="f",
            )

    def test_empty_immediate_action(self):
        with pytest.raises(ValidationError):
            CardCreateRequest(
                title="测试",
                scenario="x",
                behavior_type="自伤",
                age_range=[3, 12],
                severity="重度",
                scene="家庭",
                ebp_labels=["强化"],
                family_category="危机安全",
                immediate_action="",
                comforting_phrase="b",
                observation_metrics="c",
                medical_criteria="d",
                evidence_level="e",
                contraindications="f",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            CardCreateRequest(
                title="测试",
                scenario="x",
                behavior_type="自伤",
                age_range=[3, 12],
                severity="重度",
                scene="家庭",
                ebp_labels=["强化"],
                family_category="危机安全",
                immediate_action="a",
                comforting_phrase="b",
                observation_metrics="c",
                medical_criteria="d",
                evidence_level="e",
                contraindications="f",
                extra="bad",
            )


class TestCardResponse:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        resp = CardResponse(
            card_id="CARD-001",
            narrative_id="NAR-001",
            title="卡片",
            scenario="场景",
            behavior_type="自伤",
            age_range=[3, 12],
            severity="重度",
            scene="家庭",
            ebp_labels=["强化"],
            family_category="危机安全",
            immediate_action="a",
            comforting_phrase="b",
            observation_metrics="c",
            medical_criteria="d",
            evidence_level="e",
            caution_notes="",
            contraindications="f",
            is_template=False,
            review_status=CaseStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        assert resp.card_id == "CARD-001"


class TestCardUpdate:
    def test_partial_update(self):
        req = CardUpdate(title="新标题")
        assert req.title == "新标题"
        assert req.scenario is None

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            CardUpdate(extra="bad")


class TestCardExtractionResult:
    def test_valid(self):
        card = CardCreateRequest(
            title="卡片",
            scenario="场景",
            behavior_type="自伤",
            age_range=[3, 12],
            severity="重度",
            scene="家庭",
            ebp_labels=["强化"],
            family_category="危机安全",
            immediate_action="a",
            comforting_phrase="b",
            observation_metrics="c",
            medical_criteria="d",
            evidence_level="e",
            contraindications="f",
        )
        result = CardExtractionResult(cards=[card])
        assert len(result.cards) == 1

    def test_empty_cards(self):
        result = CardExtractionResult(cards=[])
        assert result.cards == []
