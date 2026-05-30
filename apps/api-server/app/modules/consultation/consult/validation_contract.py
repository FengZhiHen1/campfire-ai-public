"""consult 行为契约 — ABC 模板方法骨架。

模块: app.modules.consultation.consult.validation_contract
职责: 定义置信度后校验服务的契约骨架。调用者走 @final validate_confidence 公共入口，
      执行关键词安检 → LLM 自评估 → 规则校验 两阶段流水线。
      实现者只能覆写 _do_ 前缀的钩子。
数据来源:
  - py_llm.LLMClientContract: SHOULD — LLM 自评估（不可用时降级纯规则评分）
  - app.modules.crisis.AhoCorasickMatcher: SHOULD — AC 自动机关键词扫描
  - py_schemas.consult.confidence.ConfidenceValidationInput: MUST — 输入数据契约
边界:
  - 依赖: py_llm, py_logger, py_schemas, app.modules.crisis
  - 被依赖: consultation_contract.py（编排层）、confidence_validator.py（实现类）
禁止行为:
  - 禁止在 @final 方法之外提供公开入口
  - 禁止在 LLM 自评估失败时阻断主流程（必须降级纯规则评分）
  - 禁止在关键词扫描中对方案正文应用否定词过滤（与 CSLT-01 不同）
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, final


class BaseConfidenceValidator(ABC):
    """置信度后校验契约 — 实现者只能覆写 _do_ 前缀的钩子。"""

    # ==========================================================================
    # @final 公共入口：validate_confidence
    # ==========================================================================

    @final
    async def validate_confidence(
        self,
        input: Any,
        background_tasks: Any,
    ) -> Any:
        """对 CSLT-03 生成的应急方案执行置信度后校验。

        两阶段 8 步骤：
        阶段一：关键词安检（用户原文 + 方案全文）
        阶段二：置信度复合评分（LLM 自评估 + 规则校验）

        此方法不可覆写（@final）。

        前置:
          - input 为 ConfidenceValidationInput 实例
          - input.plan_text 非空
        后置:
          - 返回 ConfidenceValidationOutput（含 verdict 判定）
        输入约束:
          - input.block_deep_response 为 True 时短路返回 PASS
        输出约束:
          - verdict ∈ {PASS, APPEND_WARNING, FORCE_BLOCK}
        异常:
          - 无（所有异常内部捕获，通过 degradation_note 标记降级）
        Side Effects:
          - 通过 background_tasks 异步持久化校验结果
          - 高危场景通过 trigger_ticket_with_retry 创建工单
          - 记录结构化日志（含 request_id + verdict + elapsed_ms）
        """
        start_time = time.perf_counter()

        self._validate_confidence_preconditions(input=input)

        # 阻断场景短路
        if getattr(input, 'block_deep_response', False):
            return self._do_build_pass_result(input=input)

        # 阶段一：关键词安检
        keyword_hit = await self._do_scan_keywords(input=input)
        if keyword_hit:
            result = self._do_build_blocked_result(input=input)
            ticket_failed = await self._do_trigger_ticket(input=input, verdict=result.verdict)
            result.ticket_creation_failed = ticket_failed
            self._validate_confidence_postconditions(result=result)
            return result

        # 阶段二：LLM 自评估
        llm_score, degradation_note = await self._do_llm_assessment(input=input)

        # 规则校验
        rule_score = self._do_compute_rule_score(
            plan_text=input.plan_text,
            source_list=input.source_list,
        )

        # 复合评分
        confidence_score = self._do_compute_confidence(
            llm_score=llm_score,
            rule_score=rule_score,
            degradation_note=degradation_note,
        )

        # 判定分支
        verdict, modified_plan_text, ticket_triggered = self._do_determine_verdict(
            input=input,
            confidence_score=confidence_score,
        )

        # 工单创建
        ticket_creation_failed = False
        if ticket_triggered:
            ticket_creation_failed = await self._do_trigger_ticket(
                input=input,
                verdict=verdict,
            )

        # 超时安全兜底 + 结果组装
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        result = self._do_assemble_result(
            input=input,
            confidence_score=confidence_score,
            verdict=verdict,
            modified_plan_text=modified_plan_text,
            ticket_triggered=ticket_triggered,
            ticket_creation_failed=ticket_creation_failed,
            degradation_note=degradation_note,
            elapsed_ms=elapsed_ms,
            background_tasks=background_tasks,
        )

        self._validate_confidence_postconditions(result=result)
        return result

    # ==========================================================================
    # @abstractmethod 钩子 —— 实现者必填
    # ==========================================================================

    @abstractmethod
    async def _do_scan_keywords(self, input: Any) -> bool:
        """执行高危关键词扫描。

        实现者在此填写 AC 自动机扫描逻辑（用户原文 + 方案全文）。
        不需要关心阻断场景——validate_confidence 已短路处理。
        不需要关心否定词过滤——方案正文扫描不应用否定词过滤。

        输入约束:
          - input.plan_text: 非空方案全文
          - input.high_risk_keyword_hit: CSLT-01 的标记
        输出约束:
          - 返回 True（命中高危词）或 False（安全）
        """
        ...

    @abstractmethod
    async def _do_llm_assessment(self, input: Any) -> tuple[float | None, str | None]:
        """调用 LLM 对方案质量进行自评估。

        实现者在此填写 LLM 自评估调用逻辑。
        不需要关心失败处理——异常应内部 catch 并返回 (None, degradation_note)。

        输入约束:
          - input.plan_text: 非空方案全文
        输出约束:
          - llm_score: 0.0-1.0 或 None（评估失败时）
          - degradation_note: 失败时为 "llm_unavailable"，否则 None
        """
        ...

    @abstractmethod
    def _do_compute_rule_score(
        self,
        plan_text: str,
        source_list: list[str],
    ) -> float:
        """计算规则校验分数（结构完整性 + 来源引用覆盖率）。

        实现者在此填写纯文本分析逻辑。
        不需要关心 LLM 评估结果——_do_compute_confidence 统一加权。

        输入约束:
          - plan_text: 非空方案全文
          - source_list: 来源引用清单
        输出约束:
          - 返回 0.0-1.0 的规则分
        """
        ...

    @abstractmethod
    def _do_compute_confidence(
        self,
        llm_score: float | None,
        rule_score: float,
        degradation_note: str | None,
    ) -> float:
        """复合评分：LLM 自评估 + 规则校验加权求和。

        实现者在此填写加权求和逻辑。
        不需要关心权重配置读取——已在钩子内部处理。

        输出约束:
          - 返回 0.0-1.0 的置信度分
        """
        ...

    @abstractmethod
    def _do_determine_verdict(
        self,
        input: Any,
        confidence_score: float,
    ) -> tuple[Any, str, bool]:
        """根据置信度分判定 PASS / APPEND_WARNING。

        实现者在此填写阈值判定逻辑。
        不需要关心 FORCE_BLOCK——validate_confidence 已独立处理。

        输出约束:
          - verdict: ValidationVerdict 枚举
          - modified_plan_text: 可能追加了警告文本的方案
          - ticket_triggered: 是否需要创建工单
        """
        ...

    @abstractmethod
    async def _do_trigger_ticket(self, input: Any, verdict: Any) -> bool:
        """触发工单创建。

        实现者在此填写工单 API 调用逻辑。
        不需要关心重试策略——trigger_ticket_with_retry 内部处理。

        输出约束:
          - 返回 True（创建失败）或 False（成功）
        """
        ...

    @abstractmethod
    def _do_assemble_result(
        self,
        input: Any,
        confidence_score: float,
        verdict: Any,
        modified_plan_text: str,
        ticket_triggered: bool,
        ticket_creation_failed: bool,
        degradation_note: str | None,
        elapsed_ms: float,
        background_tasks: Any,
    ) -> Any:
        """组装校验输出 + 超时安全兜底 + 异步持久化。

        实现者在此填写结果组装和持久化调度逻辑。

        输出约束:
          - 返回 ConfidenceValidationOutput 实例
        Side Effects:
          - background_tasks.add_task() 注册异步持久化
        """
        ...

    @abstractmethod
    def _do_build_pass_result(self, input: Any) -> Any:
        """阻断场景下的短路 PASS 结果。"""
        ...

    @abstractmethod
    def _do_build_blocked_result(self, input: Any) -> Any:
        """关键词命中的 FORCE_BLOCK 结果。"""
        ...

    # ==========================================================================
    # 校验器
    # ==========================================================================

    def _validate_confidence_preconditions(self, input: Any) -> None:
        """基线前置校验——置信度后校验。"""
        if input is None:
            from app.modules.consultation.exceptions import ConsultationInputError
            raise ConsultationInputError(
                message="校验输入不能为空",
                field="input",
            )

    def _validate_confidence_postconditions(self, result: Any) -> None:
        """基线后置校验——置信度后校验。"""
        if result is None:
            raise RuntimeError("validate_confidence 返回了 None")


__all__ = ["BaseConfidenceValidator"]
