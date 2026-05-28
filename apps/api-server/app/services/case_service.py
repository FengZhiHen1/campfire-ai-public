"""CASE-01 案例录入管理 — 核心业务编排。

按落地规范 §1.5 的 6 个流程顺序实现案例 CRUD、状态转换、
四段式校验、PII 检测和 EBP 一致性检测。

所有业务逻辑集中在 Service 层，路由层仅做依赖注入和委托。
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.case_model import Case
from py_db.repositories.case_repository import CaseRepository
from py_schemas.cases import (
    AttachmentRef,
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseUpdate,
    PaginatedResponse,
    PiiDetectionResult,
    PiiWarning,
)
from py_schemas.enums.case_enums import CaseStatus
from py_security.pii_detector import (
    PiiWarning as PiiWarningInternal,
)
from py_security.pii_detector import (
    detect_pii as pii_detect,
)

from app.services.ebp_validator import check_ebp_consistency

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _validate_four_stage_fields(obj: Any) -> None:
    """四段式字段完整性校验。

    检查 immediate_action、comforting_phrase、observation_metrics、
    medical_criteria 四个字段是否全部非空（非 None 且非空字符串）。

    Args:
        obj: 包含四个字段的对象（CaseCreateRequest 或 Case ORM）。

    Raises:
        HTTPException(422): 任一字段为空或仅含空白字符。
    """
    fields: list[tuple[str, str]] = [
        ("immediate_action", "即时安全干预动作"),
        ("comforting_phrase", "情绪安抚话术"),
        ("observation_metrics", "后续观察指标"),
        ("medical_criteria", "就医判断标准"),
    ]

    missing: list[str] = []
    for field_name, display_name in fields:
        value = getattr(obj, field_name, None)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(display_name)

    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "四段式字段不完整",
                "missing_fields": missing,
            },
        )


def _orm_to_case_response(
    case: Case,
    pii_warnings: Optional[List[PiiWarning]] = None,
    ebp_inconsistency_warning: Optional[str] = None,
) -> CaseResponse:
    """将 Case ORM 模型转换为 CaseResponse。

    Args:
        case: Case ORM 实例。
        pii_warnings: 可选的 PII 警告列表。
        ebp_inconsistency_warning: 可选的 EBP 一致性警告。

    Returns:
        转换后的 CaseResponse。
    """
    # 处理附件引用
    attachment_refs: Optional[List[AttachmentRef]] = None
    raw_refs = case.attachment_refs
    if raw_refs and isinstance(raw_refs, list):
        attachment_refs = []
        for ref in raw_refs:
            if isinstance(ref, dict):
                attachment_refs.append(AttachmentRef(**ref))

    # 处理 ebp_labels
    ebp_labels: list[str] = []
    if case.ebp_labels and isinstance(case.ebp_labels, list):
        ebp_labels = list(case.ebp_labels)

    return CaseResponse(
        case_id=case.case_id,
        status=case.status,
        title=case.title,
        narrative=case.narrative,
        source_type=case.source_type,
        author_id=case.author_id,
        behavior_type=case.behavior_type,
        age_range=[case.age_range_min, case.age_range_max],
        severity=case.severity,
        scene=case.scene,
        ebp_labels=ebp_labels,
        family_category=case.family_category,
        immediate_action=case.immediate_action,
        comforting_phrase=case.comforting_phrase,
        observation_metrics=case.observation_metrics,
        medical_criteria=case.medical_criteria,
        evidence_level=case.evidence_level,
        contraindications=case.contraindications,
        is_template=case.is_template,
        excluded_population=case.excluded_population if isinstance(case.excluded_population, str) else None,
        attachment_refs=attachment_refs,
        review_comment=case.review_comment if isinstance(case.review_comment, str) else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        pii_warnings=pii_warnings,
        ebp_inconsistency_warning=ebp_inconsistency_warning,
    )


def _orm_to_case_list_item(case: Case) -> CaseListItem:
    """将 Case ORM 模型转换为 CaseListItem。

    Args:
        case: Case ORM 实例。

    Returns:
        转换后的 CaseListItem。
    """
    return CaseListItem(
        case_id=case.case_id,
        title=case.title,
        status=case.status.value if hasattr(case.status, "value") else str(case.status),
        source_type=case.source_type,
        behavior_type=case.behavior_type,
        severity=case.severity,
        scene=case.scene,
        author_id=case.author_id,
        is_template=case.is_template,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _convert_pii_warnings(
    internal_warnings: list[PiiWarningInternal],
) -> list[PiiWarning]:
    """将内部 PiiWarning 转换为 Pydantic PiiWarning。

    Args:
        internal_warnings: py_security 内部 PiiWarning 列表。

    Returns:
        转换后的 Pydantic PiiWarning 列表。
    """
    return [
        PiiWarning(
            pii_type=w.pii_type,
            detected_text=w.detected_text,
            position_start=w.position_start,
            position_end=w.position_end,
        )
        for w in internal_warnings
    ]


def _build_pii_detection_result(
    internal_result: Any,
) -> PiiDetectionResult:
    """将内部 PII 检测结果转换为 Pydantic PiiDetectionResult。

    Args:
        internal_result: py_security 的 PiiDetectionResult 实例。

    Returns:
        Pydantic PiiDetectionResult 实例。
    """
    return PiiDetectionResult(
        has_pii=internal_result.has_pii,
        warnings=_convert_pii_warnings(internal_result.warnings),
    )


def _apply_update_fields(case: Case, update: CaseUpdate) -> None:
    """将 CaseUpdate 的非 None 字段应用到 Case ORM 实例。

    特殊处理：
    - age_range 拆分为 age_range_min 和 age_range_max
    - updated_at 不写入 ORM（用于乐观锁，不存储）

    Args:
        case: 待更新的 Case ORM 实例。
        update: 部分更新数据。
    """
    # 每个字段的映射关系
    field_mappings: list[tuple[str, str]] = [
        ("title", "title"),
        ("narrative", "narrative"),
        ("source_type", "source_type"),
        ("behavior_type", "behavior_type"),
        ("severity", "severity"),
        ("scene", "scene"),
        ("family_category", "family_category"),
        ("immediate_action", "immediate_action"),
        ("comforting_phrase", "comforting_phrase"),
        ("observation_metrics", "observation_metrics"),
        ("medical_criteria", "medical_criteria"),
        ("evidence_level", "evidence_level"),
        ("contraindications", "contraindications"),
        ("is_template", "is_template"),
        ("excluded_population", "excluded_population"),
    ]

    for attr_name, field_name in field_mappings:
        value = getattr(update, field_name, None)
        if value is not None:
            setattr(case, attr_name, value)

    # 特殊处理 ebp_labels
    if update.ebp_labels is not None:
        case.ebp_labels = list(update.ebp_labels)

    # 特殊处理 attachment_refs
    if update.attachment_refs is not None:
        case.attachment_refs = [ref.model_dump() for ref in update.attachment_refs]

    # 特殊处理 age_range -> age_range_min / age_range_max
    if update.age_range is not None:
        case.age_range_min = update.age_range[0]
        case.age_range_max = update.age_range[1]


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


async def create_case(
    request: CaseCreateRequest,
    current_user: Dict[str, Any],
    session: AsyncSession,
    case_repo: CaseRepository,
) -> CaseResponse:
    """创建案例草稿。

    按以下步骤执行：
    1. （路由层已执行）角色准入校验 + Schema 校验
    2. 四段式字段完整性校验
    3. PII 检测
    4. 构建 Case ORM 并写入数据库
    5. 生成 case_id

    Args:
        request: Pydantic 校验通过的案例创建请求。
        current_user: 当前用户 JWT payload（含 sub、roles 等）。
        session: 活动数据库异步会话。
        case_repo: CaseRepository 实例。

    Returns:
        CaseResponse: 创建成功的案例详情（含 PII 警告）。

    Raises:
        HTTPException(422): 四段式字段缺失。
        HTTPException(503): 数据库写入失败。
    """
    # --- 步骤 A3：四段式字段完整性校验 ---
    _validate_four_stage_fields(request)

    # --- 步骤 A4：PII 检测（MVP 简化：narrative 为空时跳过） ---
    narrative_text: str = request.narrative or ""
    pii_result = pii_detect(narrative_text)
    pii_warnings: list[PiiWarning] = _convert_pii_warnings(pii_result.warnings)

    # --- 步骤 A5 + A6：构建 ORM、生成 case_id、写入数据库 ---
    # MVP 默认值填充
    age_range_val: list[int] = request.age_range or [0, 18]
    age_range_min: int = age_range_val[0]
    age_range_max: int = age_range_val[1]

    author_id: str = request.author_id or current_user.get("sub", "")
    source_type_val: str = request.source_type.value if request.source_type else "专家撰写"
    ebp_labels_val: list[str] = list(request.ebp_labels) if request.ebp_labels else []
    family_category_val: str = request.family_category.value if request.family_category else "危机安全"
    contraindications_val: str = request.contraindications or "暂无"

    # 处理附件引用
    attachment_refs_data: list[dict[str, Any]] = []
    if request.attachment_refs:
        attachment_refs_data = [ref.model_dump() for ref in request.attachment_refs]

    case = Case(
        case_id="__PENDING__",  # 临时占位，case_id 在下面生成
        title=request.title,
        narrative=narrative_text or "待补充",
        source_type=source_type_val,
        author_id=author_id,
        behavior_type=request.behavior_type.value,
        age_range_min=age_range_min,
        age_range_max=age_range_max,
        severity=request.severity.value,
        scene=request.scene.value,
        ebp_labels=ebp_labels_val,
        family_category=family_category_val,
        immediate_action=request.immediate_action,
        comforting_phrase=request.comforting_phrase,
        observation_metrics=request.observation_metrics,
        medical_criteria=request.medical_criteria,
        evidence_level=request.evidence_level.value,
        contraindications=contraindications_val,
        is_template=request.is_template,
        excluded_population=request.excluded_population,
        attachment_refs=attachment_refs_data if attachment_refs_data else None,
        status=CaseStatus.DRAFT,
    )

    # 生成 case_id
    generated_case_id: str = await case_repo.generate_case_id(session)
    case.case_id = generated_case_id

    try:
        created_case: Case = await case_repo.create(session, case)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        _logger.error(
            "case_create_failed",
            extra={
                "case_id": generated_case_id,
                "author_id": author_id,
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务暂时不可用，请稍后重试",
        ) from exc

    _logger.info(
        "case_created",
        extra={
            "case_id": created_case.case_id,
            "author_id": author_id,
            "has_pii": pii_result.has_pii,
        },
    )

    return _orm_to_case_response(
        created_case,
        pii_warnings=pii_warnings if pii_warnings else None,
    )


async def update_case(
    case_id: str,
    update: CaseUpdate,
    current_user: Dict[str, Any],
    session: AsyncSession,
    case_repo: CaseRepository,
) -> CaseResponse:
    """更新案例字段。

    采用乐观锁（updated_at 比对）防止并发冲突。
    编辑 pending_review 或 rejected 状态的案例时自动重置为 draft。

    Args:
        case_id: 案例唯一标识。
        update: 部分更新数据。
        current_user: 当前用户 JWT payload。
        session: 活动数据库异步会话。
        case_repo: CaseRepository 实例。

    Returns:
        CaseResponse: 更新后的案例详情。

    Raises:
        HTTPException(404): 案例不存在。
        HTTPException(409): 乐观锁冲突（updated_at 不匹配）。
        HTTPException(422): 输入校验失败。
    """
    user_id: str = current_user.get("sub", "")

    # --- 步骤 B3：乐观锁冲突检测 ---
    case: Case | None = await case_repo.find_by_id_with_version(
        session, case_id, update.updated_at
    )

    if case is None:
        # 先检查案例是否存在（区分"不存在"和"版本不匹配"）
        existing_case: Case | None = await case_repo.find_by_case_id(
            session, case_id
        )
        if existing_case is None:
            _logger.warning(
                "case_not_found",
                extra={"case_id": case_id, "user_id": user_id},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"案例 {case_id} 不存在",
            )

        # 乐观锁冲突
        _logger.warning(
            "optimistic_lock_conflict",
            extra={
                "case_id": case_id,
                "expected_ts": update.updated_at.isoformat(),
                "actual_ts": existing_case.updated_at.isoformat(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "编辑冲突：案例已被其他用户修改。请刷新后重试。",
                "current_updated_at": existing_case.updated_at.isoformat(),
            },
        )

    # --- 步骤 B4：编辑即重置状态检查 ---
    _check_edit_reset(case)

    # --- 步骤 B5：字段更新与原子写入（乐观锁） ---
    _apply_update_fields(case, update)

    try:
        updated_case: Case = await case_repo.update_case_with_version(
            session, case, update.updated_at
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        await session.rollback()
        _logger.error(
            "case_update_failed",
            extra={"case_id": case_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务暂时不可用，请稍后重试",
        ) from exc

    # 获取更新后的最新状态
    final_case: Case | None = await case_repo.find_by_case_id(session, case_id)
    if final_case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"案例 {case_id} 不存在",
        )

    return _orm_to_case_response(final_case)


def _check_edit_reset(case: Case) -> bool:
    """编辑即重置状态检查。

    如果当前状态是 pending_review 或 rejected，将 status 置为 draft。
    此逻辑在字段更新之前的同一事务内执行。

    Args:
        case: 待更新的 Case ORM 实例。

    Returns:
        bool: 是否触发了状态重置。
    """
    if case.status in (CaseStatus.PENDING_REVIEW, CaseStatus.REJECTED):
        old_status: str = case.status.value if hasattr(case.status, "value") else str(case.status)
        case.status = CaseStatus.DRAFT
        _logger.info(
            "edit_reset_status",
            extra={
                "case_id": case.case_id,
                "old_status": old_status,
                "new_status": "draft",
            },
        )
        return True
    return False


async def submit_case(
    case_id: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
    case_repo: CaseRepository,
    pii_confirmed: bool = False,
) -> CaseResponse:
    """提交案例审核。

    将草稿状态的案例提交进入审核流程（draft -> pending_review）。
    提交前执行完整性校验、PII 检测和 EBP 一致性检测。

    Args:
        case_id: 案例唯一标识。
        pii_confirmed: 用户是否确认已处理 PII 警告。
        current_user: 当前用户 JWT payload。
        session: 活动数据库异步会话。
        case_repo: CaseRepository 实例。

    Returns:
        CaseResponse: 提交后的案例详情。

    Raises:
        HTTPException(404): 案例不存在。
        HTTPException(409): 状态不是 draft。
        HTTPException(422): 四段式字段缺失。
    """
    user_id: str = current_user.get("sub", "")

    # --- 步骤 C3：案例存在性与状态校验 ---
    case: Case | None = await case_repo.find_by_case_id(session, case_id)
    if case is None:
        _logger.warning(
            "case_not_found",
            extra={"case_id": case_id, "user_id": user_id},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"案例 {case_id} 不存在",
        )

    if case.status != CaseStatus.DRAFT:
        _logger.warning(
            "submit_invalid_status",
            extra={
                "case_id": case_id,
                "current_status": case.status.value if hasattr(case.status, "value") else str(case.status),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"当前状态为{case.status.value if hasattr(case.status, 'value') else case.status}，"
                    "仅 draft 状态可提交审核"
                ),
                "allowed_transition": "draft -> pending_review",
            },
        )

    # --- 步骤 C4：提交前完整性校验 ---
    # 四段式校验
    _validate_four_stage_fields(case)

    # PII 检测（MVP：仅生成警告提示，不阻断提交）
    pii_result = pii_detect(case.narrative)
    pii_warnings: list[PiiWarning] = _convert_pii_warnings(pii_result.warnings)

    # EBP 一致性检测
    ebp_warning: str | None = check_ebp_consistency(
        case.evidence_level,
        list(case.ebp_labels) if isinstance(case.ebp_labels, list) else [],
    )

    # --- 步骤 C5：状态转换为 pending_review ---
    try:
        updated_case: Case = await case_repo.update_status(
            session, case_id, CaseStatus.PENDING_REVIEW
        )
        await session.commit()
        await session.refresh(updated_case)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        await session.rollback()
        _logger.error(
            "case_submit_failed",
            extra={"case_id": case_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务暂时不可用，请稍后重试",
        ) from exc

    # --- 步骤 C6：审计日志 ---
    _logger.info(
        "case_submitted",
        extra={
            "case_id": case_id,
            "submitted_by": user_id,
            "has_pii": pii_result.has_pii,
            "pii_confirmed": pii_confirmed,
            "ebp_warning": ebp_warning is not None,
        },
    )

    if pii_confirmed:
        _logger.info(
            "pii_confirmed",
            extra={
                "case_id": case_id,
                "confirmed_by": user_id,
                "pii_findings": [w.to_dict() for w in pii_result.warnings],
            },
        )

    return _orm_to_case_response(
        updated_case,
        pii_warnings=pii_warnings if pii_warnings else None,
        ebp_inconsistency_warning=ebp_warning,
    )


async def get_case(
    case_id: str,
    current_user: Dict[str, Any],
    session: AsyncSession,
    case_repo: CaseRepository,
) -> CaseResponse:
    """获取案例完整详情，含所有权检查。

    Args:
        case_id: 案例唯一标识。
        current_user: 当前用户 payload。
        session: 活动数据库异步会话。
        case_repo: CaseRepository 实例。

    Returns:
        CaseResponse: 案例完整详情（含 is_owner 标记）。

    Raises:
        HTTPException(404): 案例不存在或无权限访问。
    """
    case: Case | None = await case_repo.find_by_case_id(session, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"案例 {case_id} 不存在",
        )

    author_id = str(case.author_id) if case.author_id else ""
    current_id = current_user.get("sub", "")
    is_owner = author_id == current_id

    if case.status != CaseStatus.APPROVED and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"案例 {case_id} 不存在",
        )

    response = _orm_to_case_response(case)
    response.is_owner = is_owner
    return response


async def list_cases(
    status_filter: Optional[str],
    behavior_type_filter: Optional[str],
    page: int,
    page_size: int,
    scope: Optional[str],
    current_user: Dict[str, Any],
    session: AsyncSession,
    case_repo: CaseRepository,
) -> PaginatedResponse[CaseListItem]:
    """按状态和行为类型查询案例列表。

    Args:
        status_filter: 可选状态筛选（draft/pending_review/rejected）。
        behavior_type_filter: 可选行为类型筛选。
        page: 页码，从 1 开始。
        page_size: 每页条数。
        scope: 查询范围，public=仅已审核，my=当前用户案例。
        current_user: 当前用户 payload。
        session: 活动数据库异步会话。
        case_repo: CaseRepository 实例。

    Returns:
        PaginatedResponse[CaseListItem]: 分页列表响应。
    """
    status_enum: CaseStatus | None = None
    author_id: str | None = None

    if scope == "public":
        status_enum = CaseStatus.APPROVED
    elif scope == "my":
        author_id = current_user.get("sub", "")
        if status_filter:
            try:
                status_enum = CaseStatus(status_filter)
            except ValueError:
                pass
    elif status_filter:
        try:
            status_enum = CaseStatus(status_filter)
        except ValueError:
            pass

    cases, total_count = await case_repo.find_by_filters(
        session,
        status=status_enum,
        author_id=author_id,
        behavior_type=behavior_type_filter,
        page=page,
        page_size=page_size,
    )

    items: list[CaseListItem] = [_orm_to_case_list_item(c) for c in cases]
    total_pages: int = math.ceil(total_count / page_size) if total_count > 0 else 0

    return PaginatedResponse[CaseListItem](  # type:ignore[valid-type]
        items=items,
        total=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


async def detect_pii_endpoint(
    narrative: str,
) -> PiiDetectionResult:
    """对叙事文本执行 PII 检测。

    独立检测端点，供前端实时检测使用。

    Args:
        narrative: 待检测的叙事文本。

    Returns:
        PiiDetectionResult: 检测结果。
    """
    internal_result = pii_detect(narrative)
    return _build_pii_detection_result(internal_result)


async def get_case_raw(
    case_id: str,
    session: AsyncSession,
    case_repo: CaseRepository,
) -> Case | None:
    """获取 Case ORM 原始实例（供内部使用）。

    此函数绕过 CaseResponse 包装，直接返回 ORM 实例。
    仅限 Service 层内部调用，不对外暴露。

    Args:
        case_id: 案例唯一标识。
        session: 活动数据库异步会话。
        case_repo: CaseRepository 实例。

    Returns:
        Case ORM 实例，不存在时返回 None。
    """
    return await case_repo.find_by_case_id(session, case_id)


__all__ = [
    "create_case",
    "update_case",
    "submit_case",
    "get_case",
    "list_cases",
    "detect_pii_endpoint",
    "get_case_raw",
]
