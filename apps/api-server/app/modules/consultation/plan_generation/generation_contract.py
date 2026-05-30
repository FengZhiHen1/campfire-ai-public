"""plan_generation 行为契约 — ABC 模板方法骨架。

模块: app.modules.consultation.plan_generation.generation_contract
职责: 定义应急方案生成服务的契约骨架。调用者走 @final generate_emergency_plan 公共入口，
      实现者只能覆写 _do_ 前缀的钩子。
数据来源:
  - py_llm.LLMClientContract: MUST — LLM API 客户端（流式 JSON 模式）
  - app.modules.consultation.plan_generation.models.EmergencyPlanInput: MUST — 输入数据契约
  - py_config.AppSettings: SHOULD — 模型/温度/max_tokens 配置
边界:
  - 依赖: py_llm, py_logger, py_config
  - 被依赖: consultation_contract.py（编排层）、service.py（实现类）
禁止行为:
  - 禁止在 @final 方法之外提供公开入口
  - 禁止在 _do_ 钩子中调用 super()
  - 禁止在契约文件中 import LLMClient 具体实现（只依赖 LLMClientContract）
  - 禁止在阻断场景下仍调用 LLM
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final


class BasePlanGenerator(ABC):
    """应急方案生成契约 — 实现者只能覆写 _do_ 前缀的钩子。"""

    # ==========================================================================
    # @final 公共入口：generate_emergency_plan
    # ==========================================================================

    @final
    async def generate_emergency_plan(
        self,
        input_data: Any,
        config: Any | None = None,
    ) -> Any:
        """接收应急咨询上游结果，组装 Prompt 并调用大模型生成四段式应急方案。

        阻断场景下（block_deep_response=True）完全跳过 LLM 调用，
        直接返回硬编码安全提示文本。

        前置校验 → 阻断检查 → Prompt 构建 → LLM 流式调用 → 结果组装 → 指标记录。
        此方法不可覆写（@final）。

        前置:
          - input_data 为 EmergencyPlanInput 实例或可构造的 dict
          - input_data.request_id 非空
        后置:
          - 返回 GenerationResult（含 text/sections/source_list/disclaimer/generation_time_ms）
          - 阻断场景返回 finish_reason=BLOCKED 的 GenerationResult
        输入约束:
          - input_data: EmergencyPlanInput 或等价 dict
        输出约束:
          - GenerationResult.text: JSON 格式方案文本（阻断场景为空字符串）
          - GenerationResult.disclaimer: 固定免责声明文本
        异常:
          - GenerationInputError: Pydantic 校验失败
          - LLMUnavailableError: DeepSeek API 不可用
          - GenerationTimeoutError: 全流程超时且无文本产出
        Side Effects:
          - 记录结构化日志（INFO/WARNING/CRITICAL 级别）
          - 暴露 Prometheus 指标（请求计数 + 耗时 + TTFT Histogram）
          - 无持久化（由调用方负责）
        """
        self._validate_generation_preconditions(input_data=input_data)

        # 阻断短路
        if self._should_block(input_data):
            return self._do_build_blocked_result(input_data=input_data)

        # Prompt 构建
        messages, ctx = self._do_build_prompt(input_data=input_data)

        # LLM 流式调用
        accumulated_text, ttft_ms, finish_reason = await self._do_stream_generate(
            input_data=input_data,
            messages=messages,
            ctx=ctx,
            config=config,
        )

        # 结果组装
        result = self._do_build_result(
            input_data=input_data,
            accumulated_text=accumulated_text,
            ttft_ms=ttft_ms,
            finish_reason=finish_reason,
            ctx=ctx,
        )

        self._validate_generation_postconditions(result=result)
        return result

    # ==========================================================================
    # @abstractmethod 钩子 —— 实现者必填
    # ==========================================================================

    @abstractmethod
    def _do_build_prompt(
        self,
        input_data: Any,
    ) -> tuple[list[dict[str, str]], Any]:
        """构建 System Prompt + User Message。

        实现者在此填写 Prompt 组装逻辑（参考案例预编号、档案格式化、PII 二次扫描）。
        不需要关心 input_data 的 Pydantic 校验——_validate_generation_preconditions 已处理。

        输入约束:
          - input_data: 已校验的 EmergencyPlanInput
        输出约束:
          - messages: [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
          - ctx: PromptBuildContext 实例（含预编号映射）
        """
        ...

    @abstractmethod
    async def _do_stream_generate(
        self,
        input_data: Any,
        messages: list[dict[str, str]],
        ctx: Any,
        config: Any | None,
    ) -> tuple[str, float | None, Any]:
        """调用 LLM 流式 API，收集完整文本。

        实现者在此填写 LLM 流式调用 + JsonSectionTracker 解析逻辑。
        不需要关心阻断场景——generate_emergency_plan 已短路处理。

        输入约束:
          - messages: 已组装的 OpenAI 格式消息列表
          - ctx: PromptBuildContext 实例
        输出约束:
          - accumulated_text: LLM 返回的完整 JSON 文本
          - ttft_ms: 首字延迟（None 表示无有效 TTFT）
          - finish_reason: GenerationStatus 枚举值
        异常:
          - LLMUnavailableError: API 不可达
          - GenerationTimeoutError: 完全超时无产出
        """
        ...

    @abstractmethod
    def _do_build_blocked_result(self, input_data: Any) -> Any:
        """构建阻断场景的短路结果。

        实现者在此填写安全提示文本选择和 GenerationResult 组装。
        不需要关心是否为阻断场景——generate_emergency_plan 已判断并调用此钩子。

        输入约束:
          - input_data.block_deep_response 为 True
        输出约束:
          - 返回 finish_reason=BLOCKED 的 GenerationResult
        """
        ...

    @abstractmethod
    def _do_build_result(
        self,
        input_data: Any,
        accumulated_text: str,
        ttft_ms: float | None,
        finish_reason: Any,
        ctx: Any,
    ) -> Any:
        """从累积文本组装最终 GenerationResult。

        实现者在此填写 JSON 解析、引用反查、免责声明检查。
        不需要关心是否有文本——accumulated_text 可能为空。

        输入约束:
          - finish_reason: GenerationStatus 枚举值
        输出约束:
          - 返回完整的 GenerationResult 实例
        """
        ...

    # ==========================================================================
    # 校验器
    # ==========================================================================

    def _validate_generation_preconditions(self, input_data: Any) -> None:
        """基线前置校验——应急方案生成。"""
        if input_data is None:
            from .exceptions import GenerationInputError
            raise GenerationInputError(
                message="输入数据不能为空",
                detail={"field": "input_data"},
            )

    def _validate_generation_postconditions(self, result: Any) -> None:
        """基线后置校验——应急方案生成。"""
        if result is None:
            raise RuntimeError("generate_emergency_plan 返回了 None")

    def _should_block(self, input_data: Any) -> bool:
        """判断是否应阻断 LLM 调用。

        子类可覆写以改变阻断条件。
        """
        return bool(getattr(input_data, 'crisis_result', None)
                    and getattr(input_data.crisis_result, 'block_deep_response', False))


__all__ = ["BasePlanGenerator"]
