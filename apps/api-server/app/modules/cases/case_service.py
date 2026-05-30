"""CASE-01 案例录入管理 — 核心业务编排（契约驱动实现）。

按落地规范 §1.5 的 6 个流程顺序实现案例 CRUD、状态转换、
四段式校验、PII 检测和 EBP 一致性检测。

CaseManagementService 继承 CaseManagementContract 契约 ABC：
- @final 公共入口不可覆写，前置/后置校验由契约模板保障
- _do_ 前缀钩子为业务逻辑唯一落点，不重复前置校验
- 校验器重写为 HTTPException 版本以兼容 FastAPI 路由层

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
    PiiWarning,
)
from py_schemas.enums.case_enums import CaseStatus
from py_security import RegexPiiDetector
from py_security.types import PiiWarning as PiiWarningInternal

from app.modules.cases.case_contract import CaseManagementContract
from app.modules.cases.ebp_validator import check_ebp_consistency
from app.modules.cases.types import CaseId

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内部辅助函数（模块级，供 Hook 和旧代码复用）
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
        evidence_level=case.evidence_level,
        age_range=_format_age_range(case.age_range_min, case.age_range_max),
        citation_count=case.citation_count,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _format_age_range(min_val: int, max_val: int) -> str:
    """将年龄区间整数转换为展示字符串。"""
    if max_val >= 18:
        return f"{min_val}岁以上"
    return f"{min_val}-{max_val}岁"


def _convert_pii_warnings(
    internal_warnings: tuple[PiiWarningInternal, ...] | list[PiiWarningInternal],
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


# ---------------------------------------------------------------------------
# 服务实现类（继承契约 ABC）
# ---------------------------------------------------------------------------


class CaseManagementService(CaseManagementContract):
    """案例管理服务实现。

    继承 CaseManagementContract 契约 ABC，覆写 _do_ 钩子方法承载业务逻辑。
    校验器重写为 HTTPException 版本以兼容 FastAPI 路由层。
    """

    def __init__(self) -> None:
        """初始化服务实例，创建 PII 检测器。"""
        self._pii_detector = RegexPiiDetector()

    # -----------------------------------------------------------------------
    # 校验器重写（HTTPException 版本，兼容 FastAPI 路由层）
    # -----------------------------------------------------------------------

    def _validate_create_request(self, request: CaseCreateRequest) -> None:
        """基线创建前置校验：四段式字段完整性（HTTPException 版本）。"""
        _validate_four_stage_fields(request)

    def _validate_update_preconditions(
        self, case_id: str, update: CaseUpdate
    ) -> None:
        """基线更新前置校验（HTTPException 版本）。"""
        if not case_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="case_id 不能为空",
            )
        if update.updated_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="updated_at 不能为空（乐观锁版本号）",
            )

    def _validate_case_id(self, case_id: str) -> None:
        """校验 case_id 非空（HTTPException 版本）。"""
        if not case_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="case_id 不能为空",
            )

    def _validate_list_params(self, page: int, page_size: int) -> None:
        """基线列表查询参数校验（HTTPException 版本）。"""
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="page 必须 >= 1",
            )
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="page_size 必须在 1-100 之间",
            )

    # -----------------------------------------------------------------------
    # _do_ 钩子实现（唯一覆写点）
    # -----------------------------------------------------------------------

    async def _do_create_case(
        self,
        request: CaseCreateRequest,
        current_user: Dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """创建案例草稿的核心逻辑。

        不需要关心: 四段式字段校验（上游 _validate_create_request 已处理）。
        实现: PII 检测 → 构建 ORM → 生成 case_id → 写入数据库 → 审计日志。

        Args:
            request: Pydantic 校验通过的案例创建请求。
            current_user: 当前用户 JWT payload（含 sub、roles 等）。
            session: 活动数据库异步会话。
            case_repo: CaseRepository 实例。

        Returns:
            CaseResponse: 创建成功的案例详情（含 PII 警告）。

        Raises:
            HTTPException(503): 数据库写入失败。
        """
        # --- PII 检测（MVP 简化：narrative 为空时跳过） ---
        narrative_text: str = request.narrative or ""
        pii_result = self._pii_detector.detect(narrative_text)
        pii_warnings: list[PiiWarning] = _convert_pii_warnings(pii_result.warnings)

        # --- 构建 ORM、生成 case_id、写入数据库 ---
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

    async def _do_update_case(
        self,
        case_id: CaseId,
        update: CaseUpdate,
        current_user: Dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """更新案例的核心逻辑（乐观锁）。

        不需要关心: case_id/updated_at 非空校验（上游已处理）。
        实现: 乐观锁冲突检测 → 编辑重置检查 → 字段映射 → CAS 写入 → 刷新读取。

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

        # --- 乐观锁冲突检测 ---
        # FIXME: 当前区分"案例不存在"和"版本不匹配"需要两次 DB 查询
        # （先 find_by_id_with_version，若返回 None 再 find_by_case_id）。
        # 优化方向：为 CaseRepository 增加 get_case_with_version() 方法，
        # 单次查询同时返回案例和版本信息，或返回 Result[T, NotFound|Conflict] 联合类型。
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

        # --- 编辑即重置状态检查 ---
        _check_edit_reset(case)

        # --- 字段更新与原子写入（乐观锁） ---
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

    async def _do_submit_case(
        self,
        case_id: CaseId,
        current_user: Dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
        pii_confirmed: bool,
    ) -> CaseResponse:
        """提交审核的核心逻辑。

        不需要关心: case_id 非空校验（上游 _validate_submit_preconditions 已处理）。
        实现: 案例存在性检查 → 状态校验 → 四段式校验 → PII 检测 → EBP 一致性检测
              → 状态更新 → 审计日志。

        Args:
            case_id: 案例唯一标识。
            current_user: 当前用户 JWT payload。
            session: 活动数据库异步会话。
            case_repo: CaseRepository 实例。
            pii_confirmed: 用户是否确认已处理 PII 警告。

        Returns:
            CaseResponse: 提交后的案例详情。

        Raises:
            HTTPException(404): 案例不存在。
            HTTPException(409): 状态不是 draft。
            HTTPException(422): 四段式字段缺失。
        """
        user_id: str = current_user.get("sub", "")

        # --- 案例存在性与状态校验 ---
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

        # --- 提交前完整性校验 ---
        # 四段式校验（契约上游未做，此处需单独查询 case 后校验）
        _validate_four_stage_fields(case)

        # PII 检测
        pii_result = self._pii_detector.detect(case.narrative)
        pii_warnings: list[PiiWarning] = _convert_pii_warnings(pii_result.warnings)

        # 若检测到疑似 PII 且用户未确认，阻断提交
        if pii_result.has_pii and not pii_confirmed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "检测到疑似 PII（个人身份信息），请确认已脱敏后设置 pii_confirmed=true 重新提交",
                    "pii_warnings": [w.model_dump() for w in pii_warnings],
                },
            )

        # EBP 一致性检测
        ebp_warning: str | None = check_ebp_consistency(
            case.evidence_level,
            list(case.ebp_labels) if isinstance(case.ebp_labels, list) else [],
        )

        # --- 状态转换为 pending_review ---
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

        # --- 审计日志 ---
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

    async def _do_get_case(
        self,
        case_id: CaseId,
        current_user: Dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """获取案例详情的核心逻辑（含所有权检查）。

        不需要关心: case_id 非空校验（上游 _validate_case_id 已处理）。
        实现: 数据库查询 → 所有权判断 → ORM 转 Response。

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

    async def _do_list_cases(
        self,
        status_filter: str | None,
        behavior_type_filter: str | None,
        evidence_level: str | None,
        sort_by: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
        scope: str | None,
        current_user: Dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> PaginatedResponse[CaseListItem]:
        """案例列表查询的核心逻辑。

        不需要关心: 分页参数校验（上游 _validate_list_params 已处理）。
        实现: scope 解析 → 条件查询 → ORM 转 ListItem → 分页组装。

        Args:
            status_filter: 可选状态筛选（draft/pending_review/rejected）。
            behavior_type_filter: 可选行为类型筛选。
            evidence_level: 可选循证等级筛选（A/B/C/D）。
            sort_by: 排序方式（latest/evidence/cited/updated）。
            keyword: 搜索关键词（模糊匹配标题/行为类型/场景）。
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
            evidence_level=evidence_level,
            keyword=keyword,
            sort_by=sort_by,
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


__all__ = [
    "CaseManagementService",
]
