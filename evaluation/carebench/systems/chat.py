"""A/B 共用的单次对话调用：同一模型客户端、同一提示边界、同一输入文本。

职责：把「一次 chat.completions 调用」封装成 :class:`SystemAdapter` 的一半，供
:mod:`evaluation.carebench.systems.direct`（A）与 :mod:`evaluation.carebench.systems.rag`（B）
继承；差异只在 B 会先跑产品检索并追加证据块。

边界：不实现检索、不实现工具、不做任何 Agent 编排——A 组按协议必须是「直接问答」，
B 组是「受控 RAG」。两者都不触碰产品的 skill / 工具池 / 运行时。

为什么复用产品的 `ModelGateway` 而不是自己 new 一个 `AsyncOpenAI`：协议 01 第 4 节要求
「同一底座模型」。模型 id、base_url、超时与凭据解析的唯一真源是 `core/config` +
`agent/model`；自己再拼一份就有两个真源，而两份真源漂移的表现恰好是「看起来跑了同一模型，
其实不是」。这里只取 `gateway.client` 与 `gateway.model_name`，不越过它。

重试归属（进 manifest）：A/B 这一层不带自己的重试（`AsyncOpenAI(max_retries=0)`），
所有重试由评测工具的外层策略统一负责（至多一次，保留首错）。C 组则用产品自己的
runner-managed retry（`MODEL_MAX_RETRIES`），两者都写进 manifest，不互相冒充。
"""

from __future__ import annotations

import time
from typing import Any

from campfire.agent.model import ModelGateway
from campfire.core.config import Settings

from .. import prompts
from ..cases import Case
from ..config import RunConfig
from .base import STATUS_COMPLETED, STATUS_ERROR, STATUS_NO_OUTPUT, SystemMeta, TurnInput, TurnOutcome


class ChatSystem:
    """A/B 的公共基类：一条 system 消息 + 累积的对话历史 + 一次完成调用。"""

    system_id = ""

    def __init__(self, *, settings: Settings, config: RunConfig, gateway: ModelGateway) -> None:
        """绑定配置与共享网关。"""
        self._settings = settings
        self._config = config
        self._gateway = gateway
        # 每个 case-group 一段历史：键是会话 id，`open_case` 负责清空。
        self._history: dict[str, list[dict[str, str]]] = {}

    # --- SystemAdapter ---
    async def prepare(self) -> SystemMeta:
        """返回装配事实（模型 id、提示 hash、端点主机）。"""
        from ..knowledge import endpoint_host

        return SystemMeta(
            system_id=self.system_id,
            label="direct_llm" if self.system_id == "A" else "rag_baseline",
            assembly=self.assembly_note,
            model_id=self._gateway.model_name,
            prompt_sha256=prompts.sha256_text(self.system_prompt(evidence=None)),
            notes={
                "chat_endpoint_host": endpoint_host(self._settings.tokenhub_base_url),
                "sdk_client_max_retries": 0,
                "outer_retry_owner": "carebench",
                "tools": "none",
                "skills": "none",
            },
        )

    async def open_case(
        self,
        *,
        case: Case,
        session_id: str,
        account_id: str,
        prior_turns: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """新会话：清空历史；续跑时用已落盘的轮次重建（见 `SystemAdapter.open_case`）。"""
        history: list[dict[str, str]] = []
        for user_text, assistant_text in prior_turns:
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": assistant_text})
        self._history[session_id] = history

    async def run_turn(self, request: TurnInput) -> TurnOutcome:
        """跑一轮：渲染文本 → （B 组先检索）→ 调用 → 返回原始产出。

        计时口径（协议 03 第 3 节：完整用户感知端到端时延）：`started` 必须取在
        **任何工作之前**。此前它取在 `build_evidence` 之后，于是 B 组的检索耗时被
        排除在 `latency_ms` 之外——B 组看起来比 A 组还快，而差别恰恰来自检索。
        现在检索耗时单独记进 `retrieval_ms`，`latency_ms` 含它。
        """
        started = time.monotonic()
        user_text = prompts.render_user_turn(
            shared_context=request.case.shared_context,
            message=request.case.message_for_turn(request.turn),
            is_followup=request.turn > 1,
        )
        evidence_block, retrieval_trace = await self.build_evidence(request)
        retrieval_ms = int((time.monotonic() - started) * 1000)
        system_prompt = self.system_prompt(evidence=evidence_block)

        history = self._history.setdefault(request.session_id, [])
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        try:
            text, usage = await self.complete(messages)
        except Exception as exc:  # noqa: BLE001 —— 只留类型，原始消息可能含端点细节
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return TurnOutcome(
                status=STATUS_ERROR,
                latency_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_detail=f"chat 调用失败（{type(exc).__name__}）",
                trace={
                    "system_id": self.system_id,
                    "turn": request.turn,
                    "messages_sent": messages,
                    "error_type": type(exc).__name__,
                    "retrieval": retrieval_trace,
                },
                meta={"model_id": self._gateway.model_name, "retrieval_ms": retrieval_ms},
            )
        latency_ms = int((time.monotonic() - started) * 1000)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": text})

        return TurnOutcome(
            status=STATUS_COMPLETED if text.strip() else STATUS_NO_OUTPUT,
            raw_output=text,
            output_text=text,
            latency_ms=latency_ms,
            usage=usage,
            citations=list(retrieval_trace.get("citations", [])),
            trace={
                "system_id": self.system_id,
                "turn": request.turn,
                "messages_sent": messages,
                "response_text": text,
                "usage": usage,
                "retrieval": retrieval_trace,
            },
            meta={"model_id": self._gateway.model_name, "retrieval_ms": retrieval_ms},
        )

    async def aclose(self) -> None:
        """A/B 不持有额外资源（网关的所有者是 runner）。"""
        return None

    # --- 子类可覆盖 ---
    @property
    def assembly_note(self) -> str:
        """装配说明（进 manifest）。"""
        return ""

    def system_prompt(self, *, evidence: str | None) -> str:
        """本轮的 system 提示：共同任务边界 + （B 的）证据使用纪律与证据块。"""
        return prompts.COMMON_TASK_INSTRUCTIONS

    async def build_evidence(self, request: TurnInput) -> tuple[str | None, dict[str, Any]]:
        """检索材料（A 组恒为空）。"""
        return None, {}

    # --- 调用本身 ---
    async def complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        """发一次 chat.completions 调用，返回正文与 usage。

        Raises:
            Exception: 任何传输/协议错误原样抛出（由调用方转成 `error` 状态）。
        """
        params: dict[str, Any] = {}
        if self._config.temperature is not None:
            params["temperature"] = self._config.temperature
        if self._config.top_p is not None:
            params["top_p"] = self._config.top_p
        if self._config.max_output_tokens is not None:
            params["max_tokens"] = self._config.max_output_tokens
        response = await self._gateway.client.chat.completions.create(
            model=self._gateway.model_name,
            messages=messages,  # type: ignore[arg-type]  # SDK 接受 dict 消息列表
            **params,
        )
        choice = response.choices[0] if response.choices else None
        text = (choice.message.content if choice and choice.message else None) or ""
        usage_payload = getattr(response, "usage", None)
        usage = {
            "requests": 1,
            "input_tokens": int(getattr(usage_payload, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage_payload, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage_payload, "total_tokens", 0) or 0),
        }
        return text, usage


__all__ = ["ChatSystem"]
