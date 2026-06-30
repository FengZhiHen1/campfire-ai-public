"""CASE-01 案例录入管理 — 行为契约（ABC 模板方法）。

定义案例 CRUD 和状态转换的契约骨架：
- @final 公共入口 = 唯一外部入口，校验逻辑不可绕过
- @abstractmethod 钩子（_do_ 前缀）= 实现者唯一能覆写的地方
- 校验器方法 = 模板提供基线校验，子类通过 super() 叠加

实现者只能覆写 _do_ 前缀的钩子方法。
调用者只能使用 @final 公共方法。

数据来源:
  - CaseRepository (py_db): MUST — 案例持久化（CRUD + 乐观锁 + ID 生成）
  - RegexPiiDetector (py_security): MUST — 叙事文本 PII 检测
  - check_ebp_consistency (本模块): MUST — EBP 标签一致性校验
  - PySchemas (py_schemas): MUST — CaseCreateRequest / CaseResponse 等数据模型
边界:
  - 依赖: py_db, py_security, py_schemas
  - 被依赖: routes.py（路由层委托）
  - 不负责: 审核流程（归属 CASE-03）、向量化入库（归属 CASE-04）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final

from py_db.repositories.case_repository import CaseRepository
from py_schemas.cases import (
    CaseCreateRequest,
    CaseListItem,
    CaseResponse,
    CaseUpdate,
    PaginatedResponse,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..types import CaseId


class CaseManagementContract(ABC):
    """案例管理服务契约。实现者只能覆写 _do_ 前缀的钩子方法。

    异常策略: 契约基类校验器抛出域异常（从 exceptions.py 导入）。
    Service 实现通过重写校验器抛出 HTTPException 以适配 FastAPI 路由层。
    契约层（框架无关）与服务层（框架适配）的异常体系是有意分离的。
    """

    # ---------------------------------------------------------------------------
    # @final 公共入口
    # ---------------------------------------------------------------------------

    @final
    async def create_case(
        self,
        request: CaseCreateRequest,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """创建案例草稿。

        前置校验 → 调用钩子 → 后置校验。
        此方法不可覆写（@final）。

        前置:
          - request.title 非空
          - request.behavior_type 为合法枚举值
          - request.immediate_action / comforting_phrase /
            observation_metrics / medical_criteria 全部非空
        后置:
          - 案例已写入数据库，status=draft
          - case_id 格式为 CASE-YYYY-NNNN
          - 返回的 CaseResponse 含 PII 警告（若有）
        异常:
          - FourStageValidationError: 四段式字段不完整
          - CaseStatusError: 数据库写入失败
        Side Effects:
          - 写入 cases 表
          - 记录结构化审计日志（case_created）
        """
        self._validate_create_request(request)
        result = await self._do_create_case(request, current_user, session, case_repo)
        self._validate_create_result(result)
        return result

    @final
    async def update_case(
        self,
        case_id: CaseId,
        update: CaseUpdate,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """更新案例字段（乐观锁）。

        前置校验 → 调用钩子 → 后置校验。

        前置:
          - case_id 非空
          - update.updated_at 非空（乐观锁版本号）
          - 案例存在且 updated_at 匹配（否则 OptimisticLockError）
        后置:
          - 案例字段已更新
          - 若原状态为 pending_review 或 rejected，已重置为 draft
        异常:
          - CaseNotFoundError: 案例不存在
          - OptimisticLockError: 乐观锁冲突
        Side Effects:
          - 更新 cases 表
          - 可能触发 edit_reset_status 审计日志
        """
        self._validate_update_preconditions(case_id, update)
        result = await self._do_update_case(case_id, update, current_user, session, case_repo)
        self._validate_update_result(result, case_id)
        return result

    @final
    async def submit_case(
        self,
        case_id: CaseId,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
        pii_confirmed: bool = False,
    ) -> CaseResponse:
        """提交案例审核（draft → pending_review）。

        前置校验 → 调用钩子 → 后置校验。

        前置:
          - 案例存在
          - 案例当前状态为 draft
          - 四段式字段全部非空
        后置:
          - 案例状态已变更为 pending_review
          - 已执行 PII 检测和 EBP 一致性检测
          - pii_confirmed=True 时已记录审计日志
        异常:
          - CaseNotFoundError: 案例不存在
          - CaseStatusError: 当前状态不是 draft
          - FourStageValidationError: 四段式字段不完整
        Side Effects:
          - 更新 cases.status
          - 记录结构化审计日志（case_submitted）
        """
        self._validate_submit_preconditions(case_id, current_user, session, case_repo)
        result = await self._do_submit_case(case_id, current_user, session, case_repo, pii_confirmed)
        self._validate_submit_result(result, case_id)
        return result

    @final
    async def get_case(
        self,
        case_id: CaseId,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """获取案例详情（含所有权检查）。

        前置:
          - case_id 非空
        后置:
          - 返回案例完整详情
          - 非 approved 案例仅作者可见（其他用户返回 404）
        异常:
          - CaseNotFoundError: 案例不存在或无权限
        """
        self._validate_case_id(case_id)
        result = await self._do_get_case(case_id, current_user, session, case_repo)
        self._validate_get_result(result, case_id)
        return result

    @final
    async def list_cases(
        self,
        status_filter: str | None,
        behavior_type_filter: str | None,
        evidence_level: str | None,
        sort_by: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
        scope: str | None,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> PaginatedResponse[CaseListItem]:
        """案例列表查询（分页 + 筛选）。

        前置:
          - page >= 1, page_size 在 1-100 之间
        后置:
          - 返回分页结果，含 total / page / page_size / total_pages
        """
        self._validate_list_params(page, page_size)
        return await self._do_list_cases(
            status_filter,
            behavior_type_filter,
            evidence_level,
            sort_by,
            keyword,
            page,
            page_size,
            scope,
            current_user,
            session,
            case_repo,
        )

    # ---------------------------------------------------------------------------
    # @abstractmethod 钩子（实现者必填）
    # ---------------------------------------------------------------------------

    @abstractmethod
    async def _do_create_case(
        self,
        request: CaseCreateRequest,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """创建案例草稿的核心逻辑。

        不需要关心: 四段式字段校验（上游 _validate_create_request 已处理）。
        实现者在此: PII 检测 → 构建 ORM → 生成 case_id → 写入数据库。
        """
        ...

    @abstractmethod
    async def _do_update_case(
        self,
        case_id: CaseId,
        update: CaseUpdate,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """更新案例的核心逻辑。

        不需要关心: 乐观锁冲突检测、案例存在性校验（上游已处理）。
        实现者在此: edit-reset 检查 → 字段映射 → CAS 写入 → 刷新读取。
        """
        ...

    @abstractmethod
    async def _do_submit_case(
        self,
        case_id: CaseId,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
        pii_confirmed: bool,
    ) -> CaseResponse:
        """提交审核的核心逻辑。

        不需要关心: 案例存在性、状态校验、四段式校验（上游已处理）。
        实现者在此: PII 检测 → EBP 一致性检测 → 状态更新 → 审计日志。
        """
        ...

    @abstractmethod
    async def _do_get_case(
        self,
        case_id: CaseId,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> CaseResponse:
        """获取案例详情的核心逻辑。

        不需要关心: case_id 非空校验（上游已处理）。
        实现者在此: 数据库查询 → 所有权判断 → ORM 转 Response。
        """
        ...

    @abstractmethod
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
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> PaginatedResponse[CaseListItem]:
        """案例列表查询的核心逻辑。

        不需要关心: 分页参数校验（上游已处理）。
        实现者在此: scope 解析 → 条件查询 → ORM 转 ListItem → 分页组装。
        """
        ...

    # ---------------------------------------------------------------------------
    # 校验器（模板提供基线校验，子类可通过 super() 叠加）
    # ---------------------------------------------------------------------------

    def _validate_create_request(self, request: CaseCreateRequest) -> None:
        """基线创建前置校验：四段式字段完整性。

        子类必须覆写此方法以提供具体的四段式字段校验逻辑
        （如 CaseManagementService 委托给模块级 _validate_four_stage_fields）。
        """
        pass

    def _validate_create_result(self, result: CaseResponse) -> None:
        """基线创建后置校验。"""
        if result is None:
            raise RuntimeError("CaseManagementContract.create_case 返回了 None")
        if not result.case_id:
            raise RuntimeError("创建的案例缺少 case_id")

    def _validate_update_preconditions(self, case_id: str, update: CaseUpdate) -> None:
        """基线更新前置校验。"""
        if not case_id:
            raise ValueError("case_id 不能为空")
        if update.updated_at is None:
            raise ValueError("updated_at 不能为空（乐观锁版本号）")

    def _validate_update_result(self, result: CaseResponse, case_id: str) -> None:
        """基线更新后置校验。"""
        if result is None:
            raise RuntimeError(f"CaseManagementContract.update_case({case_id}) 返回了 None")

    def _validate_submit_preconditions(
        self,
        case_id: CaseId,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
    ) -> None:
        """基线提交前置校验：case_id 非空。

        案例存在性、状态和四段式完整性由 _do_submit_case 内部处理
        （需要先查询数据库才能校验，无法在契约基类的前置校验阶段完成）。
        """
        self._validate_case_id(case_id)

    def _validate_submit_result(self, result: CaseResponse, case_id: str) -> None:
        """基线提交后置校验。"""
        if result is None:
            raise RuntimeError(f"CaseManagementContract.submit_case({case_id}) 返回了 None")

    def _validate_case_id(self, case_id: str) -> None:
        """校验 case_id 非空。"""
        if not case_id:
            raise ValueError("case_id 不能为空")

    def _validate_get_result(self, result: CaseResponse, case_id: str) -> None:
        """基线获取后置校验。"""
        if result is None:
            raise RuntimeError(f"CaseManagementContract.get_case({case_id}) 返回了 None")

    def _validate_list_params(self, page: int, page_size: int) -> None:
        """基线列表查询参数校验。"""
        if page < 1:
            raise ValueError("page 必须 >= 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size 必须在 1-100 之间")
