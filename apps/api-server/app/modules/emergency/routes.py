"""应急咨询路由（ADR-009 时刻分层，智能应急咨询 §六 端点族）。

端点：
- GET  /api/v1/consult/safety-card/universal     — 0 输入通用安全卡（秒级，此刻安全层入口）
- POST /api/v1/consult/stream                    — 创建（桶选择）/推进（阶段回答/补充描述）
- GET  /api/v1/consult/stream/{session_id}       — SSE 事件流（Last-Event-Id 续传）
- POST /api/v1/consult/stream/{session_id}/followup   — 追问轮
- POST /api/v1/consult/stream/{session_id}/unresolved — 未解决标记（兜底信号）
- GET  /api/v1/consult/history                   — 历史列表
- GET  /api/v1/consult/{consultation_id}         — 咨询详情

角色收敛（认证与访问 §六）：应急咨询能力域 = family / volunteer。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from py_db.models.consultation import Consultation, ConsultationSession
from py_db.repositories.safety_card_repository import SafetyCardRepository
from py_schemas.auth import UserRole
from py_schemas.emergency import (
    ConsultationSessionDetailDto,
    ConsultationSessionListItem,
    ConsultationTurnDto,
    ConsultStreamCreateRequest,
    ConsultStreamCreateResponse,
    EmergencyPlan,
    FollowupRequest,
    SourceRef,
    UnresolvedMarkRequest,
)
from py_schemas.streaming import StreamErrorCode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import (
    CurrentUser,
    _get_session_factory,
    get_db_session,
    require_roles,
)
from app.modules.crisis.safety_layer import SafetyLayer
from app.modules.crisis.service import CrisisService
from app.modules.emergency.emergency_service import EmergencyService
from app.modules.emergency.stream_hub import get_stream_hub

router = APIRouter(prefix="/api/v1/consult", tags=["emergency"])

_EMERGENCY_ROLES = (UserRole.FAMILY, UserRole.VOLUNTEER)


def _get_emergency_service() -> EmergencyService:
    card_repo = SafetyCardRepository(session_factory=_get_session_factory())
    safety_layer = SafetyLayer(card_repo)
    crisis_service = CrisisService(safety_layer)
    return EmergencyService(
        crisis_service=crisis_service,
        safety_layer=safety_layer,
        session_factory=_get_session_factory,
    )


# ===========================================================================
# GET /safety-card/universal — 0 输入通用安全卡
# ===========================================================================


@router.get(
    "/safety-card/universal",
    summary="0 输入通用安全卡",
    description="打开应急咨询页即取（秒级，代码层零 LLM，无会话）。",
)
async def get_universal_card(
    _current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    card_repo = SafetyCardRepository(session_factory=_get_session_factory())
    card = await card_repo.find_card(db, bucket=None, stage=None)
    if card is None:
        return {"card": None}
    return {
        "card": {
            "card_id": str(card.id),
            "bucket": None,
            "stage": None,
            "title": card.title,
            "content": card.card_template,
            "personalized": False,
            "variant": "normal",
        }
    }


# ===========================================================================
# POST /stream — 创建 / 推进
# ===========================================================================


@router.post(
    "/stream",
    response_model=ConsultStreamCreateResponse,
    status_code=status.HTTP_200_OK,
    summary="应急咨询创建/推进",
    description="桶选择新建会话（含红线判定分流）；阶段回答/文字补充推进既有会话。",
)
async def create_or_advance_stream(
    request: ConsultStreamCreateRequest,
    current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> ConsultStreamCreateResponse:
    service = _get_emergency_service()
    try:
        if request.session_id is None:
            session_id = await service.start(current_user.user_id, request, db)
        else:
            session_id = str(request.session_id)
            await service.advance(session_id, request, db)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": StreamErrorCode.SESSION_NOT_FOUND.value, "detail": "会话不存在或已过期"},
        ) from exc
    return ConsultStreamCreateResponse(session_id=session_id)


# ===========================================================================
# GET /stream/{session_id} — SSE 事件流
# ===========================================================================


@router.get(
    "/stream/{session_id}",
    summary="应急咨询事件流",
    description="SSE 事件流（chunk/safety_card/stage_question/result/done/error + 心跳）；Last-Event-Id 续传。",
)
async def stream_events(
    session_id: str,
    request: Request,
    _current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
) -> StreamingResponse:
    hub = get_stream_hub()
    last_event_id = int(request.headers.get("Last-Event-Id", "0") or 0)

    return StreamingResponse(
        hub.stream(session_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ===========================================================================
# POST /stream/{session_id}/followup — 追问轮
# ===========================================================================


@router.post(
    "/stream/{session_id}/followup",
    status_code=status.HTTP_202_ACCEPTED,
    summary="追问轮",
    description="通用 Agent 会话（自由文本，不套四段式契约）；同一事件流继续推送。",
)
async def followup(
    session_id: str,
    request: FollowupRequest,
    _current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    service = _get_emergency_service()
    try:
        await service.followup(session_id, request.text, db)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": StreamErrorCode.SESSION_NOT_FOUND.value, "detail": "会话不存在或已过期"},
        ) from exc
    return {"session_id": session_id}


# ===========================================================================
# POST /stream/{session_id}/unresolved — 未解决标记
# ===========================================================================


@router.post(
    "/stream/{session_id}/unresolved",
    status_code=status.HTTP_202_ACCEPTED,
    summary="未解决标记（确定性兜底信号）",
)
async def mark_unresolved(
    session_id: str,
    _request: UnresolvedMarkRequest,
    _current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    service = _get_emergency_service()
    try:
        await service.mark_unresolved(session_id, db)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": StreamErrorCode.SESSION_NOT_FOUND.value, "detail": "会话不存在或已过期"},
        ) from exc
    return {"session_id": session_id}


# ===========================================================================
# GET /history — 历史列表
# ===========================================================================


@router.get(
    "/history",
    summary="咨询历史列表",
)
async def list_history(
    current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await db.execute(
        select(ConsultationSession)
        .where(ConsultationSession.user_id == uuid.UUID(current_user.user_id))
        .order_by(ConsultationSession.created_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()
    items: list[ConsultationSessionListItem] = []
    for s in sessions:
        turn_count_result = await db.execute(
            select(Consultation).where(Consultation.session_id == s.id)
        )
        turn_count = len(turn_count_result.scalars().all())
        items.append(
            ConsultationSessionListItem(
                id=str(s.id),
                bucket=s.bucket,
                crisis_stage=s.crisis_stage,
                turn_count=turn_count,
                created_at=s.created_at.isoformat(),
            )
        )
    return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}


# ===========================================================================
# GET /{consultation_id} — 咨询详情
# ===========================================================================


@router.get(
    "/{consultation_id}",
    summary="咨询详情（完整方案 + 引用来源 + 会话记录）",
)
async def get_consultation_detail(
    consultation_id: str,
    current_user: CurrentUser = Depends(require_roles(*_EMERGENCY_ROLES)),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(consultation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="会话 ID 格式非法") from exc

    result = await db.execute(
        select(ConsultationSession).where(
            ConsultationSession.id == sid,
            ConsultationSession.user_id == uuid.UUID(current_user.user_id),
        )
    )
    session_row = result.scalars().first()
    if session_row is None:
        raise HTTPException(status_code=404, detail="咨询记录不存在")

    turns_result = await db.execute(
        select(Consultation).where(Consultation.session_id == sid).order_by(Consultation.created_at.asc())
    )
    turns = []
    for t in turns_result.scalars().all():
        plan = EmergencyPlan(**t.generated_plan) if t.generated_plan else None
        turns.append(
            ConsultationTurnDto(
                id=str(t.id),
                turn_type=t.turn_type,
                behavior_description=t.behavior_description,
                generated_plan=plan,
                reply_text=t.reply_text,
                sources=[SourceRef(**s) for s in (t.sources or [])],
                disclaimer_served=t.disclaimer_served,
                created_at=t.created_at.isoformat(),
            )
        )

    detail = ConsultationSessionDetailDto(
        id=str(session_row.id),
        profile_id=str(session_row.profile_id) if session_row.profile_id else None,
        bucket=session_row.bucket,
        crisis_stage=session_row.crisis_stage,
        meltdown_type=session_row.meltdown_type,
        turns=turns,
        created_at=session_row.created_at.isoformat(),
    )
    return detail.model_dump(mode="json")


__all__ = ["router"]
