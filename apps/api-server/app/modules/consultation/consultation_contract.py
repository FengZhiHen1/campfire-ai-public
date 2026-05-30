"""consultation 行为契约 — ABC 模板方法骨架。

模块: app.modules.consultation.consultation_contract
职责: 定义应急咨询编排的核心契约。覆盖 CSLT-02（语义检索）、CSLT-08（咨询编排）两个核心流程。
      每个 @final 公共入口强制执行 前置校验 → _do_ 钩子 → 后置校验 三步流程。
      实现者只能覆写 _do_ 前缀的钩子方法。
数据来源:
  - py_rag.BaseSemanticSearch: MUST — 语义检索引擎
  - py_llm.LLMClientContract: MUST — LLM API 客户端
  - py_db.ConsultHistoryRepository: MUST — 咨询历史持久化
  - app.modules.crisis: MUST — 危机分级判定
  - app.core.streaming.SseStreamingService: MUST — SSE 流式推送
  - app.modules.consultation.plan_generation.BasePlanGenerator: MUST — 应急方案生成
  - app.modules.consultation.consult.BaseConfidenceValidator: SHOULD — 置信度后校验（MVP Phase 1 轻量化）
边界:
  - 依赖: py_rag, py_llm, py_db, py_logger, app.modules.crisis, app.core.streaming
  - 被依赖: routes.py（REST 端点）、consult_service.py（实现类）
禁止行为:
  - 禁止在 @final 方法之外提供公开入口
  - 禁止在 _do_ 钩子中调用 super()
  - 禁止裸用硬编码字符串/数字——必须引用 types.py 的 NewType 和常量
  - 禁止跨层调用（路由直接调 Repository 绕过本契约）
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, final

from sqlalchemy.ext.asyncio import AsyncSession

from .types import BehaviorDescription, ProfileSummary, RequestId, SessionId


class BaseConsultationOrchestrator(ABC):
    """应急咨询编排契约 — 实现者只能覆写 _do_ 前缀的钩子。"""

    # ==========================================================================
    # @final 公共入口：POST /api/v1/consult — 启动应急咨询
    # ==========================================================================

    @final
    async def start_consultation(
        self,
        behavior_description: str,
        profile_id: str | None,
        behavior_type: list[str] | None,
        emotion_level: str | None,
        user_id: str,
        db: AsyncSession,
    ) -> SessionId:
        """启动一次完整的应急咨询流程，返回 SSE session_id。

        前置校验 → 档案加载 → RAG 检索 → 危机判定 → Prompt 构建 →
        流式生成 → SSE 注册 → 后置校验。
        此方法不可覆写（@final）。

        前置:
          - behavior_description 非空，最大 2000 字符
          - db 为有效的 AsyncSession
        后置:
          - 返回有效的 SessionId（格式 stream-{uuid4}）
          - Generator 已注册到 SseStreamingService
        输入约束:
          - behavior_description: 已通过 PII 脱敏
          - profile_id: UUID v4 字符串或 None
        输出约束:
          - SessionId: "stream-" 前缀的 UUID v4 字符串
        异常:
          - ConsultationInputError: behavior_description 为空
          - ConsultationSearchError: 检索引擎不可用
          - ConsultationGenerationError: LLM 不可用且无部分产出
        Side Effects:
          - 记录全流程结构化日志（含 request_id + session_id）
          - 注册 AsyncGenerator 到 SseStreamingService 单例
          - 存储生成元数据供 SSE DoneEvent 使用
        """
        request_id = RequestId(f"req-{uuid.uuid4()}")
        session_id_raw = f"stream-{uuid.uuid4()}"
        session_id = SessionId(session_id_raw)

        self._validate_start_preconditions(
            behavior_description=behavior_description,
            profile_id=profile_id,
            db=db,
        )

        # 步骤 1：加载档案
        profile_summary = self._do_load_profile(
            profile_id=profile_id,
            db=db,
        )

        # 步骤 2：RAG 语义检索
        search_result = await self._do_search_cases(
            query_text=behavior_description,
            behavior_type=behavior_type,
            emotion_level=emotion_level,
            request_id=request_id,
            db=db,
        )

        # 步骤 3：危机分级判定
        crisis_result = await self._do_judge_crisis(
            behavior_description=behavior_description,
            behavior_type=behavior_type,
            profile_summary=profile_summary,
        )

        # 步骤 4：构建 EmergencyPlanInput
        plan_input = self._do_build_plan_input(
            behavior_description=BehaviorDescription(behavior_description),
            profile_summary=profile_summary,
            search_result=search_result,
            crisis_result=crisis_result,
            request_id=request_id,
        )

        # 步骤 5：流式生成 + SSE 注册（共享 ctx 避免重复 PromptBuilder.build()）
        generator, prompt_ctx = self._do_generate_stream(plan_input)
        self._do_register_sse(
            session_id=session_id,
            generator=generator,
            plan_input=plan_input,
            search_result=search_result,
            crisis_result=crisis_result,
            behavior_description=behavior_description,
            request_id=request_id,
            prompt_ctx=prompt_ctx,
        )

        self._validate_start_postconditions(session_id=session_id)

        return session_id

    # ==========================================================================
    # @abstractmethod 钩子 —— 实现者必填
    # ==========================================================================

    @abstractmethod
    def _do_load_profile(
        self,
        profile_id: str | None,
        db: AsyncSession,
    ) -> ProfileSummary:
        """加载患者档案并格式化为 Markdown 摘要。

        实现者在此填写档案查询和格式化逻辑。
        不需要关心 profile_id 为 None 的情况——start_consultation 已允许 None。
        不需要关心 profile_id 格式校验——_validate_start_preconditions 已处理。
        """
        ...

    @abstractmethod
    async def _do_search_cases(
        self,
        query_text: str,
        behavior_type: list[str] | None,
        emotion_level: str | None,
        request_id: RequestId,
        db: AsyncSession,
    ) -> Any:
        """执行 RAG 语义检索。

        实现者在此填写检索引擎调用逻辑。
        不需要关心 query_text 为空的校验——_validate_start_preconditions 已处理。
        """
        ...

    @abstractmethod
    async def _do_judge_crisis(
        self,
        behavior_description: str,
        behavior_type: list[str] | None,
        profile_summary: ProfileSummary,
    ) -> Any:
        """执行危机分级判定。

        实现者在此填写危机判定调用逻辑。
        不需要关心判定失败的处理——实现者应捕获异常并 fallback 到 mild。
        """
        ...

    @abstractmethod
    def _do_build_plan_input(
        self,
        behavior_description: BehaviorDescription,
        profile_summary: ProfileSummary,
        search_result: Any,
        crisis_result: Any,
        request_id: RequestId,
    ) -> Any:
        """组装 EmergencyPlanInput 供下游生成服务消费。

        实现者在此填写数据组装逻辑。
        不需要关心各字段的必填校验——Pydantic 模型自动处理。
        """
        ...

    @abstractmethod
    def _do_generate_stream(self, plan_input: Any) -> tuple[Any, Any]:
        """调用流式生成并返回 AsyncGenerator 和 PromptBuildContext。

        实现者在此填写 generation service 调用逻辑。
        不需要关心 SSE 注册——_do_register_sse 独立处理。

        输出约束:
          - 返回 (generator, prompt_ctx) 元组，prompt_ctx 传递给 _do_register_sse 复用
        """
        ...

    @abstractmethod
    def _do_register_sse(
        self,
        session_id: SessionId,
        generator: Any,
        plan_input: Any,
        search_result: Any,
        crisis_result: Any,
        behavior_description: str,
        request_id: RequestId,
        prompt_ctx: Any,
    ) -> None:
        """注册流式生成器到 SSE 服务并存储元数据。

        实现者在此填写 SSE 注册逻辑。
        不需要关心 session_id 格式校验——start_consultation 内部生成。
        prompt_ctx 由 _do_generate_stream 产出，避免重复 PromptBuilder.build()。

        Side Effects:
          - SseStreamingService.register_generator() 写入内存缓存
          - SseStreamingService.store_generation_meta() 写入元数据
        """
        ...

    # ==========================================================================
    # @final 公共入口：POST /api/v1/consult/search — 语义检索
    # ==========================================================================

    @final
    async def search_cases(
        self,
        request: Any,
        db: AsyncSession,
    ) -> Any:
        """执行 RAG 语义检索并返回排序后的案例切片。

        前置校验 → 调用钩子 → 后置校验。
        此方法不可覆写（@final）。

        前置:
          - request 为 Pydantic 校验通过的 SemanticSearchInput
          - db 为有效的 AsyncSession
        后置:
          - 返回 SemanticSearchResult（含 is_complete 标记）
        异常:
          - ConsultationInputError: request 或 db 为 None
          - ConsultationSearchError: 检索引擎不可达
        Side Effects:
          - 记录检索耗时和结果计数的结构化日志
        """
        self._validate_search_preconditions(request=request, db=db)

        result = await self._do_execute_search(request=request, db=db)

        self._validate_search_postconditions(result=result)
        return result

    @abstractmethod
    async def _do_execute_search(self, request: Any, db: AsyncSession) -> Any:
        """执行实际的 RAG 检索调用。

        实现者在此填写 hybrid_search 调用逻辑。
        不需要关心 request/db 的 None 校验——_validate_search_preconditions 已处理。
        """
        ...

    # ==========================================================================
    # 校验器 —— 模板提供基线校验，子类通过 super() 叠加
    # ==========================================================================

    def _validate_start_preconditions(
        self,
        behavior_description: str,
        profile_id: str | None,
        db: AsyncSession,
    ) -> None:
        """基线前置校验——启动咨询。

        子类通过 super() 叠加业务级校验（如配额检查、限流）。
        """
        if not behavior_description or not behavior_description.strip():
            from .exceptions import ConsultationInputError
            raise ConsultationInputError(
                message="行为描述不能为空",
                field="behavior_description",
            )
        if db is None:
            from .exceptions import ConsultationInputError
            raise ConsultationInputError(
                message="数据库会话不能为空",
                field="db",
            )

    def _validate_start_postconditions(self, session_id: SessionId) -> None:
        """基线后置校验——启动咨询。"""
        if not session_id:
            raise RuntimeError("session_id 生成失败")

    def _validate_search_preconditions(
        self,
        request: Any,
        db: AsyncSession,
    ) -> None:
        """基线前置校验——语义检索。"""
        if request is None:
            from .exceptions import ConsultationInputError
            raise ConsultationInputError(
                message="检索请求不能为空",
                field="request",
            )
        if db is None:
            from .exceptions import ConsultationInputError
            raise ConsultationInputError(
                message="数据库会话不能为空",
                field="db",
            )

    def _validate_search_postconditions(self, result: Any) -> None:
        """基线后置校验——语义检索。"""
        if result is None:
            raise RuntimeError("search_cases 返回了 None")


__all__ = ["BaseConsultationOrchestrator"]
