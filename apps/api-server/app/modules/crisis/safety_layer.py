"""此刻安全层（代码层，零 LLM）。

链路（智能应急咨询 §三）：
0 输入通用安全卡 → 桶专属安全卡（模板 × 槽位）→ 阶段单点问题（每次一问）→
卡片按阶段替换；情绪哭闹桶内 meltdown/tantrum 两问分流；走失桶独立一键流程。

内容纪律（D7）：卡体为占位模板（标注「待专家撰写」），
阶段问题/分流两问措辞为占位（机制 §十 待明确项，待专家审校）——
本模块实现的是「机制」：卡供给回退链、阶段状态机、分流结论注入。
"""

from __future__ import annotations

from typing import Any

from py_schemas.emergency import SafetyCardDto, StageQuestionDto
from py_schemas.enums import BehaviorBucket, CrisisStage, MeltdownType
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crisis.slot_filler import ProfileSnapshot, fill_slots

# ---------------------------------------------------------------------------
# 阶段单点问题状态机（占位措辞，待专家审校——机制 §十 待明确项）
# ---------------------------------------------------------------------------

# 问题标识：question_id → 问题定义
_STAGE_QUESTIONS: dict[str, dict[str, Any]] = {
    "Q_LISTEN": {
        "question": "他现在还能听进你说话吗？",
        "options": ["能", "不能"],
    },
    "Q_HARM": {
        "question": "他有没有伤害自己或他人的动作？",
        "options": ["有", "没有"],
    },
}

# 分流两问（情绪哭闹桶，机制 §3.3）
_MELTDOWN_QUESTIONS: dict[str, dict[str, Any]] = {
    "Q_WANT": {
        "question": "他这样做，有没有明确想要的东西？",
        "options": ["有", "没有"],
    },
    "Q_STOP": {
        "question": "满足他之后，会停下来吗？",
        "options": ["会", "不会"],
    },
}


class SafetyLayer:
    """此刻安全层供给器。

    依赖注入：SafetyCardRepository（卡模板供给）。
    槽位填充经 slot_filler（ProfileSnapshot 为 None 时回退纯模板）。
    """

    def __init__(self, card_repo: Any) -> None:
        self._card_repo = card_repo

    # ------------------------------------------------------------------
    # 卡供给（回退链：阶段卡 → 桶卡 → 通用卡）
    # ------------------------------------------------------------------

    async def get_universal_card(self, session: AsyncSession) -> SafetyCardDto | None:
        """0 输入通用安全卡（bucket/stage 均为 NULL 的模板）。"""
        card = await self._card_repo.find_card(session, bucket=None, stage=None)
        return self._to_dto(card, personalized=False) if card else None

    async def get_bucket_card(
        self,
        session: AsyncSession,
        bucket: BehaviorBucket,
        snapshot: ProfileSnapshot | None,
        *,
        variant: str = "normal",
    ) -> SafetyCardDto | None:
        """桶专属安全卡（stage=NULL 通用桶卡；槽位填充）。"""
        card = await self._card_repo.find_card(session, bucket=bucket, stage=None)
        if card is None:
            return await self.get_universal_card(session)
        return self._to_dto(card, snapshot=snapshot, variant=variant)

    async def get_stage_card(
        self,
        session: AsyncSession,
        bucket: BehaviorBucket,
        stage: CrisisStage,
        snapshot: ProfileSnapshot | None,
    ) -> SafetyCardDto | None:
        """阶段卡（回退链：阶段卡 → 桶卡 → 通用卡）。"""
        card = await self._card_repo.find_card(session, bucket=bucket, stage=stage)
        if card is None:
            return await self.get_bucket_card(session, bucket, snapshot)
        return self._to_dto(card, snapshot=snapshot)

    async def get_redline_card(
        self,
        session: AsyncSession,
        bucket: BehaviorBucket,
        snapshot: ProfileSnapshot | None,
    ) -> SafetyCardDto | None:
        """高危桶卡（红线命中：标红置顶变体）。"""
        return await self.get_bucket_card(session, bucket, snapshot, variant="redline")

    async def get_elopement_card(
        self,
        session: AsyncSession,
        snapshot: ProfileSnapshot | None,
    ) -> SafetyCardDto | None:
        """走失一键流程卡（独立流程：报警话术 + 水体提醒 + 搜寻分工）。"""
        return await self.get_bucket_card(
            session, BehaviorBucket.ELOPEMENT, snapshot, variant="elopement"
        )

    # ------------------------------------------------------------------
    # 阶段推进状态机（代码层状态替换，零 LLM）
    # ------------------------------------------------------------------

    def next_stage_question(
        self,
        bucket: BehaviorBucket,
        current_stage: CrisisStage | None,
        meltdown_type: MeltdownType | None,
    ) -> StageQuestionDto | None:
        """阶段推进状态机：返回下一问（None = 阶段流结束，进入方案层触发）。

        流转（占位措辞，待专家审校）：
        - 情绪哭闹桶先分流两问（Q_WANT → Q_STOP）
        - 桶卡后 Q_LISTEN：「能」→ TRIGGER；「不能」→ Q_HARM
        - Q_HARM：「有」→ PEAK；「没有」→ ACCELERATION
        """
        # 走失桶：独立一键流程，无阶段问答
        if bucket == BehaviorBucket.ELOPEMENT:
            return None

        # 情绪哭闹桶：先 meltdown/tantrum 分流
        if bucket == BehaviorBucket.MELTDOWN and meltdown_type is None:
            if current_stage is None:
                q = _MELTDOWN_QUESTIONS["Q_WANT"]
                return StageQuestionDto(question_id="Q_WANT", question=q["question"], options=q["options"])

        if current_stage is None:
            q = _STAGE_QUESTIONS["Q_LISTEN"]
            return StageQuestionDto(question_id="Q_LISTEN", question=q["question"], options=q["options"])

        if current_stage == CrisisStage.AGITATION:
            # AGITATION 为「不能听进话」的中间态：继续 Q_HARM
            q = _STAGE_QUESTIONS["Q_HARM"]
            return StageQuestionDto(question_id="Q_HARM", question=q["question"], options=q["options"])

        return None

    def resolve_stage_answer(
        self,
        question_id: str,
        answer: str,
        bucket: BehaviorBucket,
    ) -> tuple[CrisisStage | None, MeltdownType | None, str | None]:
        """回答 → （新阶段, 分流结论, 下一问题 ID）状态替换。

        Returns:
            (stage, meltdown_type, next_question_id)
        """
        if question_id == "Q_WANT":
            # 有 → 继续 Q_STOP；没有 → meltdown（进入阶段问答）
            if answer == "有":
                return None, None, "Q_STOP"
            return None, MeltdownType.MELTDOWN, "Q_LISTEN"

        if question_id == "Q_STOP":
            # 会 → tantrum；不会 → meltdown
            meltdown_type = MeltdownType.TANTRUM if answer == "会" else MeltdownType.MELTDOWN
            return None, meltdown_type, "Q_LISTEN"

        if question_id == "Q_LISTEN":
            # 能 → TRIGGER；不能 → AGITATION（继续 Q_HARM）
            if answer == "能":
                return CrisisStage.TRIGGER, None, None
            return CrisisStage.AGITATION, None, "Q_HARM"

        if question_id == "Q_HARM":
            # 有 → PEAK；没有 → ACCELERATION
            if answer == "有":
                return CrisisStage.PEAK, None, None
            return CrisisStage.ACCELERATION, None, None

        return None, None, None

    # ------------------------------------------------------------------
    # DTO 组装
    # ------------------------------------------------------------------

    def _to_dto(
        self,
        card: Any,
        snapshot: ProfileSnapshot | None = None,
        personalized: bool = False,
        variant: str = "normal",
    ) -> SafetyCardDto:
        content, filled = fill_slots(card.card_template, snapshot)
        return SafetyCardDto(
            card_id=str(card.id),
            bucket=card.bucket,
            stage=card.crisis_stage,
            title=card.title,
            content=content,
            personalized=filled or personalized,
            variant=variant,
        )


__all__ = ["SafetyLayer"]
