"""此刻安全层单元测试——卡供给回退链、槽位填充、阶段状态机、分流。

零 LLM 断言：本层为代码层组件，测试不引入任何模型依赖。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.modules.crisis.safety_layer import SafetyLayer
from app.modules.crisis.slot_filler import ProfileSnapshot, fill_slots
from py_schemas.enums import BehaviorBucket, CrisisStage, MeltdownType

# ===========================================================================
# 槽位填充
# ===========================================================================


class TestSlotFiller:
    def test_no_snapshot_returns_pure_template(self):
        """无档案 → 纯模板回退（冷启动兼容）。"""
        template = "把 {安抚物} 递给 {称呼}"
        content, personalized = fill_slots(template, None)
        assert content == template
        assert personalized is False

    def test_nickname_filled(self):
        snapshot = ProfileSnapshot(nickname="小阳")
        content, personalized = fill_slots("抱抱 {称呼}", snapshot)
        assert content == "抱抱 小阳"
        assert personalized is True

    def test_multi_slots(self):
        snapshot = ProfileSnapshot(
            nickname="小阳",
            triggers=["噪音", "强光"],
            soothing_items=["降噪耳机"],
            avoid_list=["强行拥抱"],
        )
        template = "远离 {触发物}；拿出 {安抚物}；禁忌：{禁忌}"
        content, personalized = fill_slots(template, snapshot)
        assert "噪音、强光" in content
        assert "降噪耳机" in content
        assert "强行拥抱" in content
        assert personalized is True

    def test_missing_field_keeps_placeholder(self):
        """单字段缺失只影响该槽位（其余正常填充）。"""
        snapshot = ProfileSnapshot(nickname="小阳")  # 无 triggers
        content, _ = fill_slots("{称呼} 远离 {触发物}", snapshot)
        assert "小阳" in content
        assert "{触发物}" in content  # 未填充的槽位保留占位符


# ===========================================================================
# 卡供给回退链
# ===========================================================================


def _mock_card(bucket, stage, title="卡", template="模板"):
    card = MagicMock()
    card.id = "card-id"
    card.bucket = bucket
    card.crisis_stage = stage
    card.title = title
    card.card_template = template
    return card


class TestCardFallbackChain:
    @pytest.mark.asyncio
    async def test_stage_card_hit(self):
        repo = MagicMock()
        repo.find_card = AsyncMock(return_value=_mock_card(BehaviorBucket.MELTDOWN, CrisisStage.PEAK))
        layer = SafetyLayer(repo)
        card = await layer.get_stage_card(MagicMock(), BehaviorBucket.MELTDOWN, CrisisStage.PEAK, None)
        assert card is not None
        assert card.stage == CrisisStage.PEAK

    @pytest.mark.asyncio
    async def test_stage_card_fallback_to_bucket_card(self):
        """阶段卡缺失 → 回退桶卡。"""
        repo = MagicMock()

        async def find_card(session, bucket, stage):
            if stage is None and bucket is not None:
                return _mock_card(bucket, None)
            return None

        repo.find_card = AsyncMock(side_effect=find_card)
        layer = SafetyLayer(repo)
        card = await layer.get_stage_card(MagicMock(), BehaviorBucket.MELTDOWN, CrisisStage.PEAK, None)
        assert card is not None
        assert card.stage is None  # 回退到通用桶卡

    @pytest.mark.asyncio
    async def test_bucket_card_fallback_to_universal(self):
        """桶卡缺失 → 回退通用卡。"""
        repo = MagicMock()

        async def find_card(session, bucket, stage):
            if bucket is None and stage is None:
                return _mock_card(None, None, title="通用安全卡")
            return None

        repo.find_card = AsyncMock(side_effect=find_card)
        layer = SafetyLayer(repo)
        card = await layer.get_bucket_card(MagicMock(), BehaviorBucket.OTHER, None)
        assert card is not None
        assert card.title == "通用安全卡"

    @pytest.mark.asyncio
    async def test_redline_variant(self):
        repo = MagicMock()
        repo.find_card = AsyncMock(return_value=_mock_card(BehaviorBucket.SELF_INJURY, None))
        layer = SafetyLayer(repo)
        card = await layer.get_redline_card(MagicMock(), BehaviorBucket.SELF_INJURY, None)
        assert card.variant == "redline"


# ===========================================================================
# 阶段状态机与分流
# ===========================================================================


class TestStageFlow:
    def test_meltdown_bucket_starts_with_routing_question(self):
        """情绪哭闹桶首问为分流问题。"""
        layer = SafetyLayer(MagicMock())
        q = layer.next_stage_question(BehaviorBucket.MELTDOWN, None, None)
        assert q is not None
        assert q.question_id == "Q_WANT"

    def test_stereotypy_starts_with_listen_question(self):
        layer = SafetyLayer(MagicMock())
        q = layer.next_stage_question(BehaviorBucket.STEREOTYPY, None, None)
        assert q is not None
        assert q.question_id == "Q_LISTEN"

    def test_elopement_no_questions(self):
        """走失桶独立流程，无阶段问答。"""
        layer = SafetyLayer(MagicMock())
        assert layer.next_stage_question(BehaviorBucket.ELOPEMENT, None, None) is None

    def test_meltdown_routing_tantrum(self):
        """有明确目标 + 满足后停止 → tantrum。"""
        layer = SafetyLayer(MagicMock())
        _, meltdown_type, next_q = layer.resolve_stage_answer("Q_WANT", "有", BehaviorBucket.MELTDOWN)
        assert next_q == "Q_STOP"
        _, meltdown_type, next_q = layer.resolve_stage_answer("Q_STOP", "会", BehaviorBucket.MELTDOWN)
        assert meltdown_type == MeltdownType.TANTRUM
        assert next_q == "Q_LISTEN"

    def test_meltdown_routing_meltdown(self):
        """无明确目标 → meltdown。"""
        layer = SafetyLayer(MagicMock())
        _, meltdown_type, next_q = layer.resolve_stage_answer("Q_WANT", "没有", BehaviorBucket.MELTDOWN)
        assert meltdown_type == MeltdownType.MELTDOWN
        assert next_q == "Q_LISTEN"

    def test_stage_progression(self):
        """阶段推进：能听进话 → 触发期；不能 → 躁动期 → 有伤害动作 → 高峰期。"""
        layer = SafetyLayer(MagicMock())
        stage, _, next_q = layer.resolve_stage_answer("Q_LISTEN", "能", BehaviorBucket.STEREOTYPY)
        assert stage == CrisisStage.TRIGGER
        assert next_q is None

        stage, _, next_q = layer.resolve_stage_answer("Q_LISTEN", "不能", BehaviorBucket.STEREOTYPY)
        assert stage == CrisisStage.AGITATION
        assert next_q == "Q_HARM"

        stage, _, next_q = layer.resolve_stage_answer("Q_HARM", "有", BehaviorBucket.STEREOTYPY)
        assert stage == CrisisStage.PEAK
        assert next_q is None
