# @contract
"""api-server 危机分级判定管线行为契约 — ABC 模板方法骨架。

模块: app.modules.crisis.crisis_contract
职责: 定义两层危机分级判定的业务编排契约。覆盖 CSLT-01 流程：
      PreSelection → RuleEngine → Merge。
      LLMReviewLayer 已从默认阻塞链路中移除，以降低咨询首字节延迟。
      每个 @final 公共入口强制执行前置校验 → _do_ 钩子 → 后置校验三步流程，
      实现者只能覆写 _do_ 钩子。

数据来源:
  - py_db.models.crisis_keyword.CrisisKeyword: MUST — AC 自动机关键词词库，不可绕过
  - py_config.get_settings: SHOULD — 读取配置
  - py_logger: SHOULD — 结构化判定日志

边界:
  - 依赖: py_db, py_config, py_logger, pyahocorasick
  - 被依赖: app.modules.crisis.service (judge_crisis 入口)

禁止行为:
  - 禁止实现者覆写 @final run() 方法
  - 禁止在 _do_ 钩子中直接操作 JudgmentContext.skip_remaining（由 @final 控制短路逻辑）
  - 禁止规则引擎直接判 severe 时不记录 WARNING 级别安全事件日志
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final

from .exceptions import CrisisJudgmentError
from .models import (
    CrisisJudgmentRequest,
    CrisisJudgmentResult,
    JudgmentContext,
    JudgmentLayerResult,
)

# ============================================================================
# CrisisJudgmentPipeline — 危机分级判定管线契约
# ============================================================================


class CrisisJudgmentPipeline(ABC):
    """危机分级判定管线契约 — 业务编排层 ABC。

    实现者只能覆写 _do_ 前缀的钩子。
    外部调用者通过 @final run() 进入，无法绕过前置校验和后置处理。

    依赖注入（通过 __init__ 传入）:
      - llm_client: 保留参数，当前不再使用。
      - keyword_loader: 关键词加载可调用对象，返回 list[tuple[str, int, str, str]]
    """

    def __init__(
        self,
        llm_client: Any = None,
        keyword_loader: Any = None,
    ) -> None:
        self._llm_client = llm_client
        self._keyword_loader = keyword_loader

    # =======================================================================
    # CSLT-01 危机分级判定主流程
    # =======================================================================

    @final
    async def run(self, request: CrisisJudgmentRequest) -> CrisisJudgmentResult:
        """执行两层危机分级判定。

        前置:
          - request 已通过 Pydantic Field 级校验（调用方 Depends 完成）
          - behavior_type_selection 至少包含 1 个非重复元素
          - behavior_description 长度 ≤ 2000 字符
        后置:
          - 成功: 返回 CrisisJudgmentResult，含 final_level + 各层判定记录
          - 失败: 抛出 CrisisJudgmentError 子类异常
        输入约束:
          - request: CrisisJudgmentRequest Pydantic 模型实例
        输出约束:
          - CrisisJudgmentResult: final_level ∈ {mild, moderate, severe}
          - judgment_sources 列表长度 ≥ 1
        异常:
          - CrisisJudgmentError: 不可恢复的判定错误（前置选择层崩溃）
          - KeywordDictLoadError: 关键词词库加载失败（降级继续）
        Side Effects:
          - 记录各判定层的结构化日志（INFO 级别）
          - 规则引擎命中 severe 时记录 WARNING 级别安全事件日志
          - 不持久化判定结果——仅返回内存对象
        """
        # 步骤 1: 前置校验 + 初始化上下文
        self._validate_run_input(request)
        context = JudgmentContext(request=request)

        # 步骤 2: 前置行为类型判定
        await self._do_pre_select(context)
        self._validate_pre_select_output(context)

        # 步骤 3: 患者档案缺失检查
        if request.patient_profile is None:
            context.degradation_note = "profile_missing"

        # 步骤 4: 条件执行 — 规则引擎关键词匹配
        if not context.skip_remaining:
            await self._do_rule_engine_match(context)

        # 步骤 5: 合并输出
        result = self._do_merge(context)
        self._validate_merge_output(result)
        return result

    # =======================================================================
    # @abstractmethod 钩子 — 实现者填以下方法
    # =======================================================================

    @abstractmethod
    async def _do_pre_select(self, context: JudgmentContext) -> None:
        """执行前置行为类型判定。

        实现者在此检查 behavior_type_selection 中是否包含高危类型。
        不需要关心短路逻辑——@final run() 通过 context.skip_remaining 控制。
        不需要关心 context 初始化——@final run() 已创建。

        输入约束:
          - context.request.behavior_type_selection 已通过 Pydantic 校验（非空、无重复）
        输出约束:
          - 向 context.sources 追加 PreSelectionLayer 的判定结果
          - 若命中高危 → context.level = severe, context.block_deep = True, context.skip_remaining = True
        Side Effects:
          - 无外部依赖调用（纯内存判定，不涉及 IO）
        异常:
          - CrisisJudgmentError: 判定逻辑内部不可恢复错误
        """
        ...

    @abstractmethod
    async def _do_rule_engine_match(self, context: JudgmentContext) -> None:
        """执行规则引擎关键词匹配。

        实现者在此完成: AC 自动机扫描 → 否定词过滤 → 等级判定 → 档案叠加规则。
        不需要关心 keyword_loader 的注入——__init__ 已处理。
        不需要关心短路逻辑——@final run() 控制是否进入此步骤。

        输入约束:
          - context.request.behavior_description 为非空字符串（≤ 2000 字符）
          - context.skip_remaining = False（@final run() 保证）
        输出约束:
          - 向 context.sources 追加 RuleEngineLayer 的判定结果
          - 关键词词库不可用时设置 degraded=True 降级标记
          - 档案叠加规则触发时设置 manual_review_recommended=True
          - 命中 severe 关键词时 context.skip_remaining = True
        Side Effects:
          - AC 自动机首次加载时从 PostgreSQL 读取关键词词库
          - 命中 severe 时记录 WARNING 级别安全事件日志
        异常:
          - 关键词词库加载失败时降级（返回 degraded 结果），不抛异常
          - CrisisJudgmentError: 规则引擎内部不可恢复错误
        """
        ...

    @abstractmethod
    def _do_merge(self, context: JudgmentContext) -> CrisisJudgmentResult:
        """合并两层判定结果。

        实现者在此按优先级合并各层判定结果:
          - 前置选择 severe → 直接输出 severe
          - 规则引擎 severe → 直接输出 severe
          - 其余 → 取 RuleEngine 非空等级，否则 mild

        不需要关心 context 的完整性——@final run() 保证各层已追加结果到 context.sources。
        不需要关心 degradation_note 的设置——@final run() 和各 _do_ 钩子已设置。

        输入约束:
          - context.sources 至少含 PreSelectionLayer 的判定结果
        输出约束:
          - CrisisJudgmentResult: final_level 非 None
          - judgment_sources = context.sources 的副本
        异常:
          - 不应抛出异常（纯数据合并，无 IO）
        """
        ...

    # =======================================================================
    # 校验器 — 子类可通过 super() 叠加业务级校验
    # =======================================================================

    def _validate_run_input(self, request: CrisisJudgmentRequest) -> None:
        """前置校验——确保判定请求的必填字段非空。

        Pydantic 已在调用方完成 Field 级校验（类型、长度、唯一性），
        此处做契约级兜底校验——防御绕过 Pydantic 的直接调用场景。

        Raises:
            CrisisJudgmentError: behavior_type_selection 为空或 behavior_description 为空。
        """
        if not request.behavior_type_selection:
            raise CrisisJudgmentError("behavior_type_selection 不能为空")
        if not request.behavior_description:
            raise CrisisJudgmentError("behavior_description 不能为空")

    def _validate_pre_select_output(self, context: JudgmentContext) -> None:
        """后置校验——确保前置选择层已向 context.sources 追加结果。

        Raises:
            CrisisJudgmentError: 前置选择层未产出判定结果。
        """
        pre_result = next(
            (s for s in context.sources if s.layer_name == "PreSelectionLayer"),
            None,
        )
        if pre_result is None:
            raise CrisisJudgmentError(
                "PreSelectionLayer 未产出判定结果",
            )

    def _validate_merge_output(self, result: CrisisJudgmentResult) -> None:
        """后置校验——确保合并输出结果含 final_level 且 judgment_sources 非空。

        Raises:
            CrisisJudgmentError: 合并结果异常。
        """
        if result.final_level is None:
            raise CrisisJudgmentError("合并结果缺少 final_level")
        if not result.judgment_sources:
            raise CrisisJudgmentError("合并结果的 judgment_sources 为空")


# ============================================================================
# JudgmentLayer — 单层判定契约（Protocol，非 ABC 模板方法）
# ============================================================================


class JudgmentLayer(ABC):
    """判定层接口契约。

    定义单层判定的统一接口。与 CrisisJudgmentPipeline 的区别：
    JudgmentLayer 用于可替换的判定层组件（Protocol 风格），
    CrisisJudgmentPipeline 用于需要强制模板方法的核心流程编排。

    各层实现者继承此类，覆写 judge() 方法。
    """

    @abstractmethod
    async def judge(self, request: CrisisJudgmentRequest) -> JudgmentLayerResult:
        """执行本层的判定逻辑。

        前置:
          - request 已通过 Pydantic 校验
        后置:
          - 返回 JudgmentLayerResult，layer_name 标识本层
          - 降级/异常场景返回 level=None，不抛异常
        输入约束:
          - request: CrisisJudgmentRequest 实例
        输出约束:
          - JudgmentLayerResult: layer_name 非空，匹配层标识
        Side Effects:
          - 取决于具体层实现
        """
        ...


__all__ = ["CrisisJudgmentPipeline", "JudgmentLayer"]
