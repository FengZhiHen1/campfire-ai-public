"""PROF-01 个人档案管理 + PROF-03 事件记录管理 — Service 层编排。

PROF-01 部分：档案 CRUD、默认档案管理、乐观锁并发控制、年龄区间实时计算。
PROF-03 部分：事件记录 CRUD、30 天追溯期校验、容量管控、标签归一化、
级联删除编排。

三层鉴权流水线：
1. 路由层角色校验 — require_role(["family"]) Depends
2. Service 层权限校验 — PrivacyGuard.check_access()
3. 业务层规则校验 — 数量上限、事件容量上限、追溯期、Pydantic 输入校验

依赖 Prof-05（PrivacyGuard）、AUTH-04（角色校验）、
PROF-03/PROF-04（级联删除，待实现后对接）。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from py_auth.rbac import PrivacyGuard
from py_config.exceptions import (
    EventLimitExceededError,
    ForbiddenAccess,
    ProfileConflictError,
    ProfileLimitExceededError,
)
from py_db.repositories.event_repository import EventRepository
from py_db.repositories.profile_repository import ProfileRepository
from py_logger import logger
from py_schemas.profiles import (
    AccessDecision,
    AccessOperation,
    AccessRequest,
    EventCreate,
    EventListItem,
    EventResponse,
    EventUpdate,
    ProfileCreate,
    ProfileListItem,
    ProfileResponse,
    ProfileUpdate,
    calculate_age_range,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MAX_PROFILES_PER_USER: int = 5
"""单个家属账号下允许的最大档案数量。"""

MAX_EVENTS_PER_PROFILE: int = 500
"""单个档案下允许的最大事件记录数量。"""

EVENT_RECENCY_DAYS: int = 30
"""事件记录可追溯的最大天数。"""

_TAG_STRIP_PATTERN: re.Pattern[str] = re.compile(r"[^\w一-鿿]")
"""标签归一化正则：保留字母/数字/下划线/中文字符，去除特殊符号。"""


# ===========================================================================
# ProfileService
# ===========================================================================


class ProfileService:
    """个人档案管理的核心业务编排层。

    每个方法的第一步（除 list_profiles 外）都是 PrivacyGuard 权限校验。
    所有写操作在同一事务中完成，确保数据一致性。

    Service 层不直接操作数据库，所有查询委托给 ProfileRepository。
    Service 层不持有 session 状态，session 由调用方传入。
    """

    def __init__(
        self,
        repository: ProfileRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        """初始化 ProfileService。

        Args:
            repository: ProfileRepository 实例。未传入时自动创建。
            event_repository: EventRepository 实例。未传入时自动创建。
        """
        self._repository = repository or ProfileRepository(session_factory=None)
        self._event_repository = event_repository or EventRepository(session_factory=None)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    async def create_profile(
        self,
        caregiver_id: UUID,
        input_data: ProfileCreate,
        session: AsyncSession,
    ) -> ProfileResponse:
        """为指定家属创建新患者档案。

        执行顺序：
        1. PII 检测预留扩展点（当前 No-op）
        2. 档案数量上限校验（>= MAX_PROFILES_PER_USER 时拒绝）
        3. 生成 profile_id
        4. 创建档案（若为第一份档案自动设 is_default=true）
        5. 返回含实时 age_range 的完整响应

        Args:
            caregiver_id: 家属用户标识（来自 JWT payload）。
            input_data: 档案创建请求体（已通过 Pydantic 校验）。
            session: 异步数据库会话。

        Returns:
            ProfileResponse: 创建成功的档案完整数据。

        Raises:
            ProfileLimitExceededError: 当前账号已有上限数量档案。
        """
        # ---- 步骤 1: PII 检测预留扩展点 ----
        self._pii_check(
            nickname=input_data.nickname,
            medication_notes=input_data.medication_notes,
        )

        # ---- 步骤 2: 档案数量上限校验 ----
        current_count = await self._repository.count_active_by_caregiver(
            session=session,
            caregiver_id=caregiver_id,
        )
        if current_count >= MAX_PROFILES_PER_USER:
            logger.warning(
                "api-server",
                "profile_limit_exceeded",
                extra={
                    "event_type": "profile_limit_exceeded",
                    "caregiver_id": str(caregiver_id),
                    "current_count": current_count,
                    "max_allowed": MAX_PROFILES_PER_USER,
                },
            )
            raise ProfileLimitExceededError(
                current_count=current_count,
                max_allowed=MAX_PROFILES_PER_USER,
            )

        # ---- 步骤 3: 判断是否自动设为默认 ----
        is_first_profile = current_count == 0

        # ---- 步骤 4: 创建档案 ----
        from py_db.models.profiles import Profile

        profile = Profile(
            profile_id=uuid.uuid4(),
            caregiver_id=caregiver_id,
            nickname=input_data.nickname,
            birth_date=input_data.birth_date,
            diagnosis_type=input_data.diagnosis_type.value,
            primary_behavior=input_data.primary_behavior.value,
            language_level=input_data.language_level.value if input_data.language_level else None,
            sensory_features=[sf.value for sf in input_data.sensory_features],
            triggers=[t.value for t in input_data.triggers],
            medication_notes=input_data.medication_notes,
            is_default=is_first_profile,
        )
        created = await self._repository.create(session=session, profile=profile)

        # ---- 步骤 5: 结构化日志 ----
        age_range = calculate_age_range(created.birth_date)
        logger.info(
            "api-server",
            "profile_created",
            extra={
                "event_type": "profile_created",
                "profile_id": str(created.profile_id),
                "caregiver_id": str(caregiver_id),
                "is_default": created.is_default,
                "age_range": age_range.value,
            },
        )

        return self._to_profile_response(created)

    async def list_profiles(
        self,
        caregiver_id: UUID,
        page: int = 1,
        page_size: int = 10,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """获取指定家属账号下所有档案的分页列表。

        列表操作不调用 PrivacyGuard——查询范围已限定为当前 caregiver 的数据，
        无需逐档案权限校验。

        Args:
            caregiver_id: 家属用户标识。
            page: 页码（从 1 开始）。
            page_size: 每页条数（默认 10，上限 100）。
            session: 异步数据库会话。

        Returns:
            dict: 分页列表，包含 items（ProfileListItem 列表）、
                  total、page、page_size、total_pages。
        """
        if page_size > 100:
            page_size = 100
        if page < 1:
            page = 1

        profiles, total = await self._repository.list_by_caregiver(
            session=session,
            caregiver_id=caregiver_id,
            page=page,
            page_size=page_size,
        )

        items = [
            ProfileListItem(
                profile_id=p.profile_id,
                nickname=p.nickname,
                age_range=calculate_age_range(p.birth_date),
                diagnosis_type=p.diagnosis_type,
                primary_behavior=p.primary_behavior,
                is_default=p.is_default,
            )
            for p in profiles
        ]

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        logger.info(
            "api-server",
            "profile_listed",
            extra={
                "event_type": "profile_listed",
                "caregiver_id": str(caregiver_id),
                "total": total,
                "page": page,
            },
        )

        return {
            "items": [item.model_dump() for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    async def get_profile(
        self,
        caregiver_id: UUID,
        profile_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse:
        """获取单个档案的完整详情。

        Args:
            caregiver_id: 请求人家属标识。
            profile_id: 目标档案标识。
            session: 异步数据库会话。

        Returns:
            ProfileResponse: 档案完整详情。

        Raises:
            ForbiddenAccess: 权限校验不通过（403）。
            Exception: 档案不存在（404）。
        """
        # ---- 步骤 1: PrivacyGuard 权限校验 ----
        await self._check_access(
            operation=AccessOperation.VIEW,
            target_profile_id=profile_id,
            requester_id=caregiver_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 2: 查询档案 ----
        profile = await self._repository.get_by_id(
            session=session,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
        )
        if profile is None:
            logger.warning(
                "api-server",
                "profile_not_found",
                extra={
                    "event_type": "profile_not_found",
                    "profile_id": str(profile_id),
                    "caregiver_id": str(caregiver_id),
                },
            )
            raise Exception("档案不存在")

        logger.info(
            "api-server",
            "profile_read",
            extra={
                "event_type": "profile_read",
                "profile_id": str(profile_id),
                "caregiver_id": str(caregiver_id),
            },
        )

        return self._to_profile_response(profile)

    async def update_profile(
        self,
        caregiver_id: UUID,
        profile_id: UUID,
        input_data: ProfileUpdate,
        session: AsyncSession,
    ) -> ProfileResponse:
        """更新已有档案的部分字段。使用乐观锁防止并发冲突。

        Args:
            caregiver_id: 请求人家属标识。
            profile_id: 目标档案标识。
            input_data: 需要更新的字段（全部可选）。
            session: 异步数据库会话。

        Returns:
            ProfileResponse: 更新后的完整档案数据。

        Raises:
            ForbiddenAccess: 权限校验不通过。
            ProfileConflictError: 乐观锁冲突（409）。
        """
        # ---- 步骤 1: PrivacyGuard 权限校验 ----
        await self._check_access(
            operation=AccessOperation.UPDATE,
            target_profile_id=profile_id,
            requester_id=caregiver_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 2: 读取当前档案（获取 updated_at） ----
        profile = await self._repository.get_by_id(
            session=session,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
        )
        if profile is None:
            raise Exception("档案不存在")

        previous_updated_at = profile.updated_at

        # ---- 步骤 3: PII 检测预留扩展点 ----
        self._pii_check(
            nickname=input_data.nickname,
            medication_notes=input_data.medication_notes,
        )

        # ---- 步骤 4: 构建更新字段字典 ----
        update_data: dict[str, Any] = {}
        if input_data.nickname is not None:
            update_data["nickname"] = input_data.nickname
        if input_data.birth_date is not None:
            update_data["birth_date"] = input_data.birth_date
        if input_data.diagnosis_type is not None:
            update_data["diagnosis_type"] = input_data.diagnosis_type.value
        if input_data.primary_behavior is not None:
            update_data["primary_behavior"] = input_data.primary_behavior.value
        if input_data.language_level is not None:
            update_data["language_level"] = input_data.language_level.value
        if input_data.sensory_features is not None:
            update_data["sensory_features"] = [sf.value for sf in input_data.sensory_features]
        if input_data.triggers is not None:
            update_data["triggers"] = [t.value for t in input_data.triggers]
        if input_data.medication_notes is not None:
            update_data["medication_notes"] = input_data.medication_notes

        if not update_data:
            # 无字段更新，直接返回当前数据
            return self._to_profile_response(profile)

        # ---- 步骤 5: 乐观锁更新 ----
        updated = await self._repository.update_with_optimistic_lock(
            session=session,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            previous_updated_at=previous_updated_at,
            update_data=update_data,
        )

        if updated is None:
            # 乐观锁冲突：updated_at 已被其他请求修改
            # 读取当前 updated_at 用于日志
            current_profile = await self._repository.get_by_id(
                session=session,
                profile_id=profile_id,
                caregiver_id=caregiver_id,
            )
            current_updated_at = current_profile.updated_at if current_profile else "unknown"
            logger.warning(
                "api-server",
                "profile_conflict",
                extra={
                    "event_type": "profile_conflict",
                    "profile_id": str(profile_id),
                    "caregiver_id": str(caregiver_id),
                    "previous_updated_at": previous_updated_at.isoformat(),
                    "current_updated_at": (
                        current_updated_at.isoformat()
                        if isinstance(current_updated_at, datetime)
                        else str(current_updated_at)
                    ),
                },
            )
            raise ProfileConflictError()

        # ---- 步骤 6: 结构化日志 ----
        logger.info(
            "api-server",
            "profile_updated",
            extra={
                "event_type": "profile_updated",
                "profile_id": str(profile_id),
                "caregiver_id": str(caregiver_id),
                "updated_fields": list(update_data.keys()),
            },
        )

        return self._to_profile_response(updated)

    async def delete_profile(
        self,
        caregiver_id: UUID,
        profile_id: UUID,
        session: AsyncSession,
    ) -> None:
        """删除档案及关联数据。硬删除，不可恢复。

        执行顺序：
        1. PrivacyGuard 权限校验
        2. 检查是否为默认档案
        3. 级联清理 PROF-03 事件记录（待实现）
        4. 级联清理 PROF-04 评估记录（待实现）
        5. 若为默认档案，提升另一档案为默认
        6. 硬删除本行
        以上全部在同一事务中，任一步失败则全部回滚。

        Args:
            caregiver_id: 请求人家属标识。
            profile_id: 目标档案标识。
            session: 异步数据库会话。

        Raises:
            ForbiddenAccess: 权限校验不通过。
        """
        # ---- 步骤 1: PrivacyGuard 权限校验 ----
        await self._check_access(
            operation=AccessOperation.DELETE,
            target_profile_id=profile_id,
            requester_id=caregiver_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 2: 读取当前档案 ----
        profile = await self._repository.get_by_id(
            session=session,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
        )
        if profile is None:
            raise Exception("档案不存在")

        was_default = profile.is_default

        # ---- 步骤 3: 级联清理 PROF-03 事件记录（待实现） ----
        await self._cascade_delete_events(profile_id=profile_id, session=session)

        # ---- 步骤 4: 级联清理 PROF-04 评估记录（待实现） ----
        await self._cascade_delete_assessments(profile_id=profile_id, session=session)

        # ---- 步骤 5: 若为默认档案，提升另一档案 ----
        if was_default:
            next_profile = await self._repository.find_next_default_candidate(
                session=session,
                caregiver_id=caregiver_id,
                exclude_profile_id=profile_id,
            )

            if next_profile is not None:
                await self._repository.set_default(
                    session=session,
                    profile_id=next_profile.profile_id,
                    caregiver_id=caregiver_id,
                )

        # ---- 步骤 6: 硬删除本行 ----
        deleted = await self._repository.delete(
            session=session,
            profile_id=profile_id,
            caregiver_id=caregiver_id,
        )

        if not deleted:
            raise Exception("档案不存在")

        # ---- 步骤 7: 结构化日志 ----
        logger.info(
            "api-server",
            "profile_deleted",
            extra={
                "event_type": "profile_deleted",
                "profile_id": str(profile_id),
                "caregiver_id": str(caregiver_id),
                "was_default": was_default,
            },
        )

    async def get_default_profile(
        self,
        caregiver_id: UUID,
        session: AsyncSession,
    ) -> ProfileResponse:
        """获取当前账号的默认档案。

        Args:
            caregiver_id: 家属用户标识。
            session: 异步数据库会话。

        Returns:
            ProfileResponse: 默认档案完整详情。

        Raises:
            Exception: 账号下无档案（冷启动状态）。
        """
        profile = await self._repository.get_default(
            session=session,
            caregiver_id=caregiver_id,
        )
        if profile is None:
            raise Exception("未找到默认档案")

        logger.info(
            "api-server",
            "default_profile_read",
            extra={
                "event_type": "default_profile_read",
                "profile_id": str(profile.profile_id),
                "caregiver_id": str(caregiver_id),
            },
        )

        return self._to_profile_response(profile)

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    async def _check_access(
        self,
        operation: AccessOperation,
        target_profile_id: UUID,
        requester_id: UUID,
        requester_role: str,
        db_session: AsyncSession,
    ) -> None:
        """调用 PrivacyGuard 进行档案级权限校验。

        Args:
            operation: 请求的操作类型。
            target_profile_id: 目标档案 UUID。
            requester_id: 请求人 UUID。
            requester_role: 请求人角色。
            db_session: 异步数据库会话。

        Raises:
            ForbiddenAccess: 权限校验不通过。
        """
        request = AccessRequest(
            operation=operation,
            target_profile_id=target_profile_id,
            requester_id=requester_id,
            requester_role=requester_role,
        )
        decision: AccessDecision = await PrivacyGuard.check_access(
            request=request,
            db_session=db_session,
        )
        if not decision.allowed:
            raise ForbiddenAccess(detail="数据不存在")

    def _pii_check(
        self,
        nickname: str | None,
        medication_notes: str | None,
    ) -> None:
        """PII 检测预留扩展点。

        当前为 No-op 空实现。待 SEC-03 PII 检测接口就绪后，
        替换为实际 SEC-03 调用逻辑。

        Args:
            nickname: 档案昵称（可为 None）。
            medication_notes: 用药备注（可为 None）。
        """
        pass

    async def _cascade_delete_events(
        self,
        profile_id: UUID,
        session: AsyncSession,
    ) -> None:
        """级联删除档案关联的事件记录。

        委托给 EventRepository.delete_by_profile() 在同一事务中执行。
        本方法不执行权限校验——调用方（delete_profile）已在调用前完成权限校验。

        Args:
            profile_id: 目标档案 UUID。
            session: 异步数据库会话（与 delete_profile 共享）。
        """
        deleted_count = await self._event_repository.delete_by_profile(
            session=session,
            profile_id=profile_id,
        )
        if deleted_count > 0:
            logger.info(
                "api-server",
                "events_cascade_deleted",
                extra={
                    "event_type": "events_cascade_deleted",
                    "profile_id": str(profile_id),
                    "deleted_count": deleted_count,
                },
            )

    async def _cascade_delete_assessments(
        self,
        profile_id: UUID,
        session: AsyncSession,
    ) -> None:
        """级联删除档案关联的评估记录。

        当前为 No-op 空实现。待 PROF-04 专业评估补充模块就绪后，
        替换为实际的 assessment_service.delete_by_profile() 调用。

        Args:
            profile_id: 目标档案 UUID。
            session: 异步数据库会话。
        """
        pass

    def _to_profile_response(self, profile: Any) -> ProfileResponse:
        """将 Profile ORM 实体转换为 ProfileResponse DTO。

        实时计算 age_range 字段（不持久化）。

        Args:
            profile: Profile ORM 实例。

        Returns:
            ProfileResponse: 档案响应 DTO。
        """
        return ProfileResponse(
            profile_id=profile.profile_id,
            nickname=profile.nickname,
            birth_date=profile.birth_date,
            age_range=calculate_age_range(profile.birth_date),
            diagnosis_type=profile.diagnosis_type,
            primary_behavior=profile.primary_behavior,
            language_level=profile.language_level,
            sensory_features=profile.sensory_features or [],
            triggers=profile.triggers or [],
            medication_notes=profile.medication_notes,
            is_default=profile.is_default,
            caregiver_id=profile.caregiver_id,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


    # ------------------------------------------------------------------
    # PROF-03 — 事件记录管理
    # ------------------------------------------------------------------

    async def create_event(
        self,
        profile_id: UUID,
        user_id: UUID,
        data: EventCreate,
        session: AsyncSession,
    ) -> EventResponse:
        """为指定档案创建一条新的事件记录。

        执行顺序：
        1. 档案存在性校验
        2. 档案级权限校验
        3. 事件时间 30 天追溯期校验
        4. 事件容量上限校验（>= 500 拒绝）
        5. 标签归一化
        6. 入库并返回完整响应

        Args:
            profile_id: 目标档案标识（URL 路径参数）。
            user_id: 当前请求人标识（来自 JWT payload）。
            data: 事件创建请求体（已通过 Pydantic 校验）。
            session: 异步数据库会话。

        Returns:
            EventResponse: 创建成功的事件完整详情（16 字段）。

        Raises:
            ForbiddenAccess: 权限校验不通过（403）。
            EventLimitExceededError: 事件记录数已达上限（409）。
            Exception: 档案不存在（404）、事件时间超追溯期（422）。
        """
        # ---- 步骤 1: 档案存在性校验 ----
        profile_exists = await self._repository.exists(
            session=session,
            profile_id=profile_id,
        )
        if not profile_exists:
            raise Exception("数据不存在")

        # ---- 步骤 2: 档案级权限校验 ----
        await self._check_access(
            operation=AccessOperation.CREATE,
            target_profile_id=profile_id,
            requester_id=user_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 3: 事件时间 30 天追溯期校验 ----
        now = datetime.now(timezone.utc)
        earliest_allowed = now - timedelta(days=EVENT_RECENCY_DAYS)
        if data.event_time < earliest_allowed:
            raise Exception(
                f"事件时间超出可追溯范围，最早允许日期为 "
                f"{earliest_allowed.strftime('%Y-%m-%d')}"
            )

        # ---- 步骤 4: 容量上限校验 ----
        current_count = await self._event_repository.count_active_by_profile(
            session=session,
            profile_id=profile_id,
        )
        if current_count >= MAX_EVENTS_PER_PROFILE:
            logger.warning(
                "api-server",
                "event_limit_exceeded",
                extra={
                    "event_type": "event_limit_exceeded",
                    "profile_id": str(profile_id),
                    "current_count": current_count,
                    "max_allowed": MAX_EVENTS_PER_PROFILE,
                },
            )
            raise EventLimitExceededError(
                current_count=current_count,
                max_allowed=MAX_EVENTS_PER_PROFILE,
            )

        # ---- 步骤 5: 标签归一化 ----
        normalized_tags = self._normalize_tags(data.tags)

        # ---- 步骤 6: 入库 ----
        from py_db.models.profiles import EventLog

        event = EventLog(
            event_id=uuid.uuid4(),
            profile_id=profile_id,
            recorded_by=user_id,
            recorded_by_role="parent",
            event_time=data.event_time,
            behavior_type=data.behavior_type.value,
            severity_level=data.severity_level.value,
            setting=data.setting.value if data.setting else None,
            trigger_description=data.trigger_description,
            manifestation=data.manifestation,
            intervention_tried=data.intervention_tried,
            intervention_result=data.intervention_result,
            is_professional=False,
            tags=normalized_tags,
        )
        created = await self._event_repository.create(session=session, event=event)

        # ---- 步骤 7: 结构化日志 ----
        logger.info(
            "api-server",
            "event_created",
            extra={
                "event_type": "event_created",
                "event_id": str(created.event_id),
                "profile_id": str(profile_id),
                "user_id": str(user_id),
                "behavior_type": created.behavior_type,
            },
        )

        return self._to_event_response(created)

    async def update_event(
        self,
        profile_id: UUID,
        event_id: UUID,
        user_id: UUID,
        data: EventUpdate,
        session: AsyncSession,
    ) -> EventResponse:
        """更新指定事件的字段（Merge Patch 语义）。

        仅更新 data 中非 None 的字段。setting 传入显式 None
        表示清除已设置的发生场景。

        执行顺序：
        1. 档案存在性校验
        2. 档案级权限校验
        3. 事件存在性 + 创建者校验
        4. 追溯期校验（如提供新 event_time）
        5. 合并更新

        Args:
            profile_id: 目标档案标识。
            event_id: 目标事件标识。
            user_id: 当前请求人标识。
            data: 事件更新请求体（所有字段可选）。
            session: 异步数据库会话。

        Returns:
            EventResponse: 更新后的事件完整详情。

        Raises:
            ForbiddenAccess: 权限校验不通过（403）。
            Exception: 事件不存在（404）、非创建者（403）、
                      事件时间超追溯期（422）。
        """
        # ---- 步骤 1: 档案存在性校验 ----
        profile_exists = await self._repository.exists(
            session=session,
            profile_id=profile_id,
        )
        if not profile_exists:
            raise Exception("数据不存在")

        # ---- 步骤 2: 档案级权限校验 ----
        await self._check_access(
            operation=AccessOperation.UPDATE,
            target_profile_id=profile_id,
            requester_id=user_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 3: 事件存在性 + 创建者校验 ----
        existing = await self._event_repository.get_by_id(
            session=session,
            event_id=event_id,
            profile_id=profile_id,
        )
        if existing is None:
            raise Exception("数据不存在")

        if existing.recorded_by != user_id:
            logger.warning(
                "api-server",
                "event_ownership_mismatch",
                extra={
                    "event_type": "event_ownership_mismatch",
                    "event_id": str(event_id),
                    "recorded_by": str(existing.recorded_by),
                    "attempted_by": str(user_id),
                },
            )
            raise ForbiddenAccess(detail="数据不存在")

        # ---- 步骤 4: 追溯期校验（如提供新 event_time） ----
        if data.event_time is not None:
            now = datetime.now(timezone.utc)
            earliest_allowed = now - timedelta(days=EVENT_RECENCY_DAYS)
            if data.event_time < earliest_allowed:
                raise Exception(
                    f"事件时间超出可追溯范围，最早允许日期为 "
                    f"{earliest_allowed.strftime('%Y-%m-%d')}"
                )

        # ---- 步骤 5: 合并更新 ----
        update_data: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

        if data.event_time is not None:
            update_data["event_time"] = data.event_time
        if data.behavior_type is not None:
            update_data["behavior_type"] = data.behavior_type.value
        if data.severity_level is not None:
            update_data["severity_level"] = data.severity_level.value
        # setting: 显式 None 表示清除
        if "setting" in data.model_fields_set:
            update_data["setting"] = data.setting.value if data.setting else None
        if data.trigger_description is not None:
            update_data["trigger_description"] = data.trigger_description
        if data.manifestation is not None:
            update_data["manifestation"] = data.manifestation
        if data.intervention_tried is not None:
            update_data["intervention_tried"] = data.intervention_tried
        if data.intervention_result is not None:
            update_data["intervention_result"] = data.intervention_result
        if data.tags is not None:
            update_data["tags"] = self._normalize_tags(data.tags)

        updated = await self._event_repository.update(
            session=session,
            event_id=event_id,
            profile_id=profile_id,
            update_data=update_data,
        )

        if updated is None:
            raise Exception("数据不存在")

        # ---- 结构化日志 ----
        logger.info(
            "api-server",
            "event_updated",
            extra={
                "event_type": "event_updated",
                "event_id": str(event_id),
                "profile_id": str(profile_id),
                "updated_fields": list(update_data.keys()),
            },
        )

        return self._to_event_response(updated)

    async def get_event(
        self,
        profile_id: UUID,
        event_id: UUID,
        user_id: UUID,
        session: AsyncSession,
    ) -> EventResponse:
        """获取单个事件的完整详情。

        Args:
            profile_id: 目标档案标识。
            event_id: 目标事件标识。
            user_id: 当前请求人标识。
            session: 异步数据库会话。

        Returns:
            EventResponse: 事件完整详情。

        Raises:
            ForbiddenAccess: 权限校验不通过（403）。
            Exception: 事件不存在（404）。
        """
        # ---- 步骤 1: 档案存在性校验 ----
        profile_exists = await self._repository.exists(
            session=session,
            profile_id=profile_id,
        )
        if not profile_exists:
            raise Exception("数据不存在")

        # ---- 步骤 2: 档案级权限校验 ----
        await self._check_access(
            operation=AccessOperation.VIEW,
            target_profile_id=profile_id,
            requester_id=user_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 3: 查询事件 ----
        event = await self._event_repository.get_by_id(
            session=session,
            event_id=event_id,
            profile_id=profile_id,
        )
        if event is None:
            raise Exception("数据不存在")

        return self._to_event_response(event)

    async def delete_event(
        self,
        profile_id: UUID,
        event_id: UUID,
        user_id: UUID,
        session: AsyncSession,
    ) -> None:
        """硬删除指定事件记录。删除后不可恢复。

        执行顺序：
        1. 档案存在性校验
        2. 档案级权限校验
        3. 事件存在性 + 创建者校验
        4. 硬删除

        Args:
            profile_id: 目标档案标识。
            event_id: 目标事件标识。
            user_id: 当前请求人标识。
            session: 异步数据库会话。

        Raises:
            ForbiddenAccess: 权限校验不通过（403）。
            Exception: 事件不存在（404）、非创建者（403）。
        """
        # ---- 步骤 1: 档案存在性校验 ----
        profile_exists = await self._repository.exists(
            session=session,
            profile_id=profile_id,
        )
        if not profile_exists:
            raise Exception("数据不存在")

        # ---- 步骤 2: 档案级权限校验 ----
        await self._check_access(
            operation=AccessOperation.DELETE,
            target_profile_id=profile_id,
            requester_id=user_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 3: 事件存在性 + 创建者校验 ----
        existing = await self._event_repository.get_by_id(
            session=session,
            event_id=event_id,
            profile_id=profile_id,
        )
        if existing is None:
            raise Exception("数据不存在")

        if existing.recorded_by != user_id:
            logger.warning(
                "api-server",
                "event_ownership_mismatch",
                extra={
                    "event_type": "event_ownership_mismatch",
                    "event_id": str(event_id),
                    "recorded_by": str(existing.recorded_by),
                    "attempted_by": str(user_id),
                },
            )
            raise ForbiddenAccess(detail="数据不存在")

        # ---- 步骤 4: 硬删除 ----
        deleted = await self._event_repository.delete(
            session=session,
            event_id=event_id,
            profile_id=profile_id,
        )

        if not deleted:
            raise Exception("数据不存在")

        # ---- 结构化日志 ----
        logger.info(
            "api-server",
            "event_deleted",
            extra={
                "event_type": "event_deleted",
                "event_id": str(event_id),
                "profile_id": str(profile_id),
            },
        )

    async def list_events(
        self,
        profile_id: UUID,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
        behavior_type: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """查询指定档案下的事件记录列表。

        支持按行为类型筛选和分页。按 event_time DESC 排序。

        Args:
            profile_id: 目标档案标识。
            user_id: 当前请求人标识。
            page: 页码（从 1 开始，默认 1）。
            page_size: 每页条数（默认 20，最大 100）。
            behavior_type: 可选行为类型筛选。
            session: 异步数据库会话。

        Returns:
            dict: 分页列表，包含 items（EventListItem 列表）、
                  total、page、page_size、total_pages。
        """
        if page_size > 100:
            page_size = 100
        if page < 1:
            page = 1

        # ---- 步骤 1: 档案存在性校验 ----
        profile_exists = await self._repository.exists(
            session=session,
            profile_id=profile_id,
        )
        if not profile_exists:
            raise Exception("数据不存在")

        # ---- 步骤 2: 档案级权限校验 ----
        await self._check_access(
            operation=AccessOperation.VIEW,
            target_profile_id=profile_id,
            requester_id=user_id,
            requester_role="family",
            db_session=session,
        )

        # ---- 步骤 3: 分页查询 ----
        events, total = await self._event_repository.list_by_profile(
            session=session,
            profile_id=profile_id,
            page=page,
            page_size=page_size,
            behavior_type=behavior_type,
        )

        items = [
            EventListItem(
                event_id=e.event_id,
                event_time=e.event_time,
                behavior_type=e.behavior_type,
                severity_level=e.severity_level,
                has_professional_note=e.is_professional,
                created_at=e.created_at,
            )
            for e in events
        ]

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        return {
            "items": [item.model_dump() for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    async def delete_by_profile(
        self,
        profile_id: UUID,
        session: AsyncSession,
    ) -> int:
        """级联删除指定档案下所有事件记录（供 PROF-01 调用）。

        本方法不执行权限校验——调用方 PROF-01 已在调用前完成权限校验。
        本方法不提交事务——由调用方统一提交或回滚。

        Args:
            profile_id: 目标档案标识。
            session: 异步数据库会话（与 PROF-01 共享）。

        Returns:
            int: 被删除的事件记录数。
        """
        return await self._event_repository.delete_by_profile(
            session=session,
            profile_id=profile_id,
        )

    # ------------------------------------------------------------------
    # PROF-03 — 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str] | None:
        """对标签列表执行归一化处理。

        每个标签依次执行：
        1. strip() 去首尾空格
        2. re.sub(r'[^\\w一-鿿]', '', tag) 去特殊符号
        3. 截断至 10 字
        4. 归一后为空的标签被丢弃

        Args:
            tags: 原始标签列表，可为 None。

        Returns:
            归一化后的标签列表。若全部归一后为空，返回 None。
        """
        if tags is None:
            return None

        result: list[str] = []
        for tag in tags:
            cleaned = tag.strip()
            cleaned = _TAG_STRIP_PATTERN.sub("", cleaned)
            cleaned = cleaned[:10]
            if cleaned:
                result.append(cleaned)

        return result if result else None

    def _to_event_response(self, event: Any) -> EventResponse:
        """将 EventLog ORM 实体转换为 EventResponse DTO。

        Args:
            event: EventLog ORM 实例。

        Returns:
            EventResponse: 事件响应 DTO。
        """
        return EventResponse(
            event_id=event.event_id,
            profile_id=event.profile_id,
            recorded_by=event.recorded_by,
            recorded_by_role=event.recorded_by_role,
            event_time=event.event_time,
            behavior_type=event.behavior_type,
            severity_level=event.severity_level,
            setting=event.setting,
            trigger_description=event.trigger_description,
            manifestation=event.manifestation,
            intervention_tried=event.intervention_tried,
            intervention_result=event.intervention_result,
            is_professional=event.is_professional,
            tags=event.tags,
            created_at=event.created_at,
            updated_at=event.updated_at,
        )


__all__ = [
    "ProfileService",
]
