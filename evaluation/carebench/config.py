"""运行配置：一次评测批次的可复现条件，以及它的规范 hash。

职责：定义 :class:`RunConfig`（组别、轮换顺序、超时与重试策略、推理参数、评审种子），
并给出规范字典与其 SHA-256；支持从 JSON 覆盖。

边界：**不含凭据、不含数据库连接串、不含模型密钥**——那些只留在 `Settings`（运行时解析）。
模型精确 id、端点主机名会记进 manifest（协议 01 第 4 节要求），但那是路由事实，不是秘密。

三种 hash 的分工（不要混用）：

- `config_sha256`：本模块的有效配置（含提示词 hash 与故障注入注册表版本）；
- `dataset_sha256`：冻结案例文件的字节 hash（:mod:`evaluation.carebench.cases`）；
- `batch_id`：上面两者 + 代码提交三者的联合指纹（:func:`evaluation.carebench.hashing.batch_fingerprint`）。

轮换顺序（协议 04 第 3 节）：同一 case 的 A/B/C 顺序按 case 序号轮换
`ABC → BCA → CAB`，避免「总是 A 先跑」带来的时间与平台负载偏差。轮换**从索引
派生**而不是命令行传入：一条可传参的轮换顺序等于允许事后挑对自己有利的顺序。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import prompts
from .faults import REGISTRY_VERSION
from .hashing import sha256_value

#: 正式批次的标签。`label=test` 意味着「这是正式成绩」：必须在干净代码（tracked 与未跟踪
#: 代码都算）与冻结案例上跑，否则冻结/批次绑定的 commit 并不包含实际跑的代码。
FORMAL_LABEL = "test"

#: 三个组别标识。取值即全包的主键：案例 × 组别 = case-group，分母按它算。
SYSTEM_IDS: tuple[str, str, str] = ("A", "B", "C")

#: 轮换顺序（协议 04 第 3 节）。按 case 序号取模，第 i 个 case 用 `ROTATION[i % 3]`。
ROTATION: tuple[str, ...] = ("ABC", "BCA", "CAB")

#: 组别的书面定义。写进 manifest，让报告里的 A/B/C 可被他人复核。
SYSTEM_LABELS: dict[str, str] = {
    "A": "direct_llm",
    "B": "rag_baseline",
    "C": "v3_agent",
}

#: 组别的实现说明（进 manifest 的 `systems[].assembly`）。
SYSTEM_ASSEMBLY: dict[str, str] = {
    "A": "单次 chat.completions 调用（产品模型网关的客户端与模型 id，无检索、无工具、无 skill）",
    "B": "同一客户端 + 产品检索链（modules/library.search，两路检索+RRF）+ 基本引用提示，无业务编排",
    "C": "产品生产装配（composition.install/get_runner）：真 AgentRunner、真工具池、真 skill、真会话",
}


@dataclass(frozen=True)
class RunConfig:
    """一次批次的全部可复现条件。冻结后不得因此次运行结果而改动。"""

    # --- 版本 ---
    protocol_version: str = "0.1"
    rubric_version: str = "0.1"
    tool_version: str = "0.1.0"

    # --- 组别与顺序 ---
    systems: tuple[str, ...] = SYSTEM_IDS
    rotation: tuple[str, ...] = ROTATION
    #: 第二轮策略：`fixed_followup` = 案例自带 followup 才跑第二轮，且文本固定。
    turn_policy: str = "fixed_followup"
    #: 每个 case-group 新建会话（协议 05 第 4 节「每题使用隔离新会话」）。
    #:
    #: 该字段进配置 hash，但本工具**没有**「共享会话」这条代码路径。因此 `False` 不是
    #: 「暂不支持的功能」，而是一个会让人以为跑过共享会话的错误配置：`__post_init__`
    #: 直接拒绝，不静默按 True 跑（否则报告里会写着 `false`、行为却是每题新会话）。
    conversation_reset_each_case: bool = True

    # --- 超时与重试 ---
    #: 单轮墙钟超时（秒）。产品的运行上限是 300 秒（`agent.limits`），这里不再缩短它：
    #: 缩短会把「产品自己会结束的运行」记成评测超时，那是评测工具制造的假失败。
    turn_timeout_seconds: float = 300.0
    #: 外层重试次数（协议 04 第 3 节：推荐最多 1 次）。
    max_outer_retries: int = 1
    #: 只对这些终局重试。`completed` 与 `no_output` 不重试：
    #: 前者无需重试；后者是模型的真实产出（空回复），重试等于替被测系统挑答案。
    retry_on: tuple[str, ...] = ("error", "timeout")

    # --- 推理参数 ---
    #: 三项为 None 表示「不显式传参、用供应商默认值」。协议要求记录的就是这个事实，
    #: 而不是替供应商编一个 temperature。
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    seed: int | None = None

    # --- B 组检索参数 ---
    retrieval_top_k: int = 5

    # --- 评审 ---
    #: 盲化随机种子。在批次开始前定，导出评审包时只用它——不可因结果而改。
    review_seed: int = 20261029
    #: 每个 case-group 计划的独立评分数（协议 03 第 5 节：至少两人）。
    raters_per_case: int = 2

    # --- 批次标签 ---
    #: `calibration` / `pilot` / `test`。只影响报告措辞与是否允许并入正式成绩，
    #: 不影响运行逻辑；混用标签会被 verify 当成批次污染。
    label: str = "pilot"

    # --- 知识快照 ---
    #: 知识快照清单文件（相对包目录）。快照 id 与实际条目在运行时从库里核对。
    knowledge_snapshot: str = "knowledge/snapshot.json"

    # --- 故障注入 ---
    #: 故障注入注册表版本；随注册表内容变化，进 config hash（见 faults.py）。
    fault_registry_version: str = REGISTRY_VERSION

    extra: dict[str, Any] = field(default_factory=dict)

    def order_for(self, index: int) -> tuple[str, ...]:
        """第 `index` 个 case 的组别执行顺序。

        从索引派生（不传参）是刻意的：协议 04 第 3 节点名要求「下一用例交替」，
        而这种要求只有做成函数才不会被某次运行悄悄绕过。
        """
        if not self.rotation:
            return tuple(self.systems)
        order = self.rotation[index % len(self.rotation)]
        unknown = [name for name in order if name not in self.systems]
        if unknown:
            raise ValueError(f"轮换顺序含未启用的组别：{unknown}")
        missing = [name for name in self.systems if name not in order]
        if missing:
            raise ValueError(f"轮换顺序缺组别：{missing}（每个 case 必须跑满 {self.systems}）")
        return tuple(order)

    def __post_init__(self) -> None:
        """校验「进 hash 就必须有消费者」的字段。

        Raises:
            ValueError: `conversation_reset_each_case` 为 False——本工具不实现共享会话。
        """
        if not self.conversation_reset_each_case:
            raise ValueError(
                "conversation_reset_each_case=False 不受支持：本工具没有共享会话的代码路径，"
                "协议也要求每个 case-group 使用隔离新会话。请删掉这个覆盖项，而不是让配置与行为不一致。"
            )

    def to_dict(self) -> dict[str, Any]:
        """规范字典：进 manifest、算 hash 的都是它（不允许两处各拼一次）。"""
        payload: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "rubric_version": self.rubric_version,
            "tool_version": self.tool_version,
            "systems": list(self.systems),
            "system_labels": {name: SYSTEM_LABELS[name] for name in self.systems},
            "system_assembly": {name: SYSTEM_ASSEMBLY[name] for name in self.systems},
            "rotation": list(self.rotation),
            "turn_policy": self.turn_policy,
            "conversation_reset_each_case": self.conversation_reset_each_case,
            "turn_timeout_seconds": self.turn_timeout_seconds,
            "max_outer_retries": self.max_outer_retries,
            "retry_on": list(self.retry_on),
            "inference": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "max_output_tokens": self.max_output_tokens,
                "seed": self.seed,
            },
            "retrieval_top_k": self.retrieval_top_k,
            "review": {
                "review_seed": self.review_seed,
                "raters_per_case": self.raters_per_case,
                "rubric_version": self.rubric_version,
            },
            "label": self.label,
            "knowledge_snapshot": self.knowledge_snapshot,
            "fault_registry_version": self.fault_registry_version,
            "prompt_sha256": {
                # A/B 的提示是评测工具的一部分，C 的提示来自产品（只记来源与 hash）。
                "common_task_instructions": prompts.sha256_text(prompts.COMMON_TASK_INSTRUCTIONS),
                "rag_evidence_instructions": prompts.sha256_text(prompts.RAG_EVIDENCE_INSTRUCTIONS),
                "product_instructions_source": prompts.PRODUCT_INSTRUCTIONS_SOURCE,
            },
        }
        if self.extra:
            payload["extra"] = self.extra
        return payload

    @property
    def sha256(self) -> str:
        """有效配置的规范 hash（进 manifest 与批次指纹）。"""
        return sha256_value(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunConfig:
        """从 manifest 里那份配置重建（续跑时不必再传 `--config`）。

        只读回 `to_dict()` 写出的字段；`system_labels` / `system_assembly` / `prompt_sha256`
        是派生展示项，不参与重建（它们由代码常量重新计算，读回来反而可能骗过 hash）。

        Raises:
            ValueError: 缺必需字段或取值非法。
        """
        inference = payload.get("inference") or {}
        review = payload.get("review") or {}
        return cls(
            protocol_version=str(payload.get("protocol_version") or "0.1"),
            rubric_version=str(payload.get("rubric_version") or review.get("rubric_version") or "0.1"),
            tool_version=str(payload.get("tool_version") or "0.1.0"),
            systems=tuple(payload.get("systems") or SYSTEM_IDS),
            rotation=tuple(payload.get("rotation") or ROTATION),
            turn_policy=str(payload.get("turn_policy") or "fixed_followup"),
            conversation_reset_each_case=bool(payload.get("conversation_reset_each_case", True)),
            turn_timeout_seconds=float(payload.get("turn_timeout_seconds") or 300.0),
            max_outer_retries=int(payload.get("max_outer_retries") or 0),
            retry_on=tuple(payload.get("retry_on") or ("error", "timeout")),
            temperature=inference.get("temperature"),
            top_p=inference.get("top_p"),
            max_output_tokens=inference.get("max_output_tokens"),
            seed=inference.get("seed"),
            retrieval_top_k=int(payload.get("retrieval_top_k") or 5),
            review_seed=int(review.get("review_seed") or 20261029),
            raters_per_case=int(review.get("raters_per_case") or 1),
            label=str(payload.get("label") or "pilot"),
            knowledge_snapshot=str(payload.get("knowledge_snapshot") or "knowledge/snapshot.json"),
            fault_registry_version=str(payload.get("fault_registry_version") or REGISTRY_VERSION),
            extra=dict(payload.get("extra") or {}),
        )


#: 允许从 JSON 覆盖的字段。白名单而不是 `**payload`：一份陌生 JSON 不应能改写
#: 未列出的字段（例如把 `systems` 悄悄扩成 A/B/C/D 会让分母与统计口径一起漂）。
_OVERRIDABLE = {
    "protocol_version",
    "rubric_version",
    "systems",
    "rotation",
    "turn_policy",
    "conversation_reset_each_case",
    "turn_timeout_seconds",
    "max_outer_retries",
    "retry_on",
    "temperature",
    "top_p",
    "max_output_tokens",
    "seed",
    "retrieval_top_k",
    "review_seed",
    "raters_per_case",
    "label",
    "knowledge_snapshot",
    "fault_registry_version",
    "extra",
}


def load_config(path: Path | None) -> RunConfig:
    """读取覆盖文件并返回有效配置；不传路径时返回默认配置。

    Raises:
        ValueError: 覆盖文件含未知字段、结构不是对象，或取值越界。
    """
    config = RunConfig()
    if path is None:
        return config
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置覆盖文件必须是 JSON 对象：{path}")
    unknown = set(raw) - _OVERRIDABLE
    if unknown:
        raise ValueError(f"配置覆盖文件含未知字段：{sorted(unknown)}")
    changes: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "systems":
            value = tuple(value)
        if key == "rotation":
            value = tuple(value)
        if key == "retry_on":
            value = tuple(value)
        changes[key] = value
    config = replace(config, **changes)
    _validate(config)
    return config


def _validate(config: RunConfig) -> None:
    """校验配置自洽（不合法就直接拒绝，而不是带着坏配置跑一批）。

    Raises:
        ValueError: 组别集合/轮换不覆盖、重试策略越界、超时非正。
    """
    if sorted(config.systems) != sorted(SYSTEM_IDS):
        raise ValueError(f"组别必须是 {SYSTEM_IDS} 的排列（当前 {config.systems}）")
    for name in config.systems:
        if name not in SYSTEM_LABELS:
            raise ValueError(f"未知组别 {name!r}")
    if config.max_outer_retries < 0 or config.max_outer_retries > 1:
        raise ValueError("外层重试只允许 0 或 1 次（协议 04 第 3 节：推荐最多 1 次）")
    bad = [outcome for outcome in config.retry_on if outcome not in {"error", "timeout"}]
    if bad:
        raise ValueError(f"retry_on 只允许 error/timeout（当前多了 {bad}）：拒答与空回复不得重试")
    if config.turn_timeout_seconds <= 0:
        raise ValueError("turn_timeout_seconds 必须为正")
    if config.retrieval_top_k < 1:
        raise ValueError("retrieval_top_k 必须为正")
    if config.raters_per_case < 1:
        raise ValueError("raters_per_case 至少为 1")
    if config.label not in {"calibration", "pilot", "test"}:
        raise ValueError(f"未知批次标签 {config.label!r}：只允许 calibration/pilot/test")
    # 轮换必须能覆盖全部组别——否则某些 case 的三组会被同顺序跑完。
    for order in config.rotation:
        if sorted(order) != sorted(config.systems):
            raise ValueError(f"轮换顺序 {order!r} 没有覆盖全部组别 {config.systems}")


__all__ = [
    "FORMAL_LABEL",
    "ROTATION",
    "SYSTEM_ASSEMBLY",
    "SYSTEM_IDS",
    "SYSTEM_LABELS",
    "RunConfig",
    "load_config",
]
