"""故障注入：把「失效类案例」要的故障**真的**施加到运行里，并逐条记录实施状态。

职责：定义 fixture 注册表、按 (case, system) 解析出本轮的注入计划、给出每条的
「已实施 / 未实施」结论与实现方式。

边界：**不改案例文本、不改产品代码**。注入点只有本工具自己拥有的两处接缝：

- B 组的证据块（检索在本工具的适配器里发起，因此「检索为空/不可用」可以在源头真实发生）；
- C 组的工具池（在装配时替换单个工具的 handler，其余仍是产品真工具、真运行时）。

为什么不能用「在 prompt 里说工具坏了」代替注入（主 agent 明确要求）：那测的是模型
会不会被一句提示骗过去，而不是系统在真实故障下是否如实披露失效。两种做法的观察结果
完全不同，混在一起会让「系统不确定/失效」这一类的成绩失去意义。

未实现的 fixture 一律 `applied=False` 并写明原因：宁可报告「这一类没测成」，
也不留下一条看起来测过的记录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hashing import sha256_value

#: 注册表版本。任何实现的增删改都必须让它变化，从而改变 `config_sha256`——
#: 否则「同一配置」可能对应两套注入能力。
REGISTRY_VERSION = "0.2"

#: 已实现的 fixture：名字 → (适用组别, 实现说明)。
#:
#: 键名刻意写清实施层次（`retrieval_*` 在 B 的检索接缝，`tool_*` 在 C 的工具池），
#: 而不是一个含糊的 `search_broken`——含糊的名字正是「在 prompt 里说坏了」这类做法
#: 最容易钻进来的地方。
SUPPORTED: dict[str, tuple[tuple[str, ...], str]] = {
    "retrieval_empty": (("B",), "rag_evidence_override:empty —— 跳过检索，证据块明确写「本次检索没有返回材料」"),
    "retrieval_unavailable": (("B",), "rag_evidence_override:unavailable —— 检索抛错，证据块写「检索不可用」"),
    "tool_search_empty": (("C",), "tool_pool_override:search_knowledge -> ToolResult(空结果说明)"),
    "tool_search_unavailable": (("C",), "tool_pool_override:search_knowledge -> ToolFailure(tool_failed)"),
    "tool_search_timeout": (
        ("C",),
        "tool_pool_override:search_knowledge -> handler 挂住 420s（> 产品单轮预算 300s），"
        "由产品自己的运行预算结束（run_finished.reason=timeout），记为 timeout",
    ),
    "retrieval_timeout": (
        ("B",),
        "rag_evidence_override:hang —— 检索调用挂住到评测回合上限（B 没有产品运行预算，"
        "所以这里触发的是评测回合超时，记录里写明来源）",
    ),
}

#: 明确**未覆盖**的故障：这类场景根本不经过程序内 runner，永远测不到。
#: 与 `UNSUPPORTED` 的区别：`UNSUPPORTED` 是「我们还没做」，这里是「这个工具做不到」。
OUT_OF_HARNESS: dict[str, str] = {
    "client_render_fault": "客户端渲染故障发生在浏览器层（前端错误边界的兜底文案、SSE 断流后的"
    "渲染状态）。程序内 runner 不进入渲染层：本工具既无法注入也无法观察，按「未覆盖」记录。"
    "要测它只能走 apps/web 的 playwright e2e（`pnpm --filter @campfire/web e2e`），不在本工具边界内。",
}

#: 声明了但**未实现**的 fixture（写进注册表是为了让「这一类没测成」可被机械统计）。
UNSUPPORTED: dict[str, str] = {
    "tool_timeout": "需要让工具在运行内真实挂住到超时：当前工具池没有注入延时的公开缝，"
    "强行包装会改变运行上限语义（会把产品超时记成评测超时）",
    "stale_material": "需要库内存在过期版本条目；评测库不许可加入过期语料，改用真实库内条目无法构造",
    "prompt_injection_unrelated": "需要可控的检索结果文本；C 侧需先往评测库写入注入语料（许可与库洁癖冲突），"
    "B 侧可注入但 A/C 无对等实施，故整体标未支持",
    "partial_data_missing": "档案缺失可由空档案账号自然覆盖（作为普通运行而非注入）；不作为 fixture 单独实施",
    "location_unknown": "属案例文本层面的缺信息（写在 user_message 里），不是系统故障，无需注入",
}


@dataclass(frozen=True)
class FixtureApplication:
    """一条 fixture 在某轮的实施结论。"""

    name: str
    requested_by: str
    """来源：`case`（案例自带 field）/ `config`（fixtures 配置文件）。"""
    systems: tuple[str, ...]
    applied: bool
    impl: str | None
    note: str
    status: str = "applied"
    """`applied` / `not_applicable` / `unsupported` / `out_of_harness` / `unknown`。"""

    def to_dict(self) -> dict[str, Any]:
        """落盘形状（进 outputs 记录与 summary 的 fixture 统计）。"""
        return {
            "name": self.name,
            "requested_by": self.requested_by,
            "systems": list(self.systems),
            "applied": self.applied,
            "status": self.status,
            "impl": self.impl,
            "note": self.note,
        }


@dataclass(frozen=True)
class FaultPlan:
    """按 case 解析的注入计划。"""

    requested: dict[str, tuple[tuple[str, str], ...]]
    """case_id → ((fixture, requested_by), ...)。"""

    @property
    def registry_sha256(self) -> str:
        """注册表内容的 hash（进 manifest，证明「同配置 = 同注入能力」）。"""
        return sha256_value(
            {
                "version": REGISTRY_VERSION,
                "supported": {name: [list(systems), impl] for name, (systems, impl) in SUPPORTED.items()},
                "unsupported": UNSUPPORTED,
            }
        )

    def plan_for(self, case_id: str, system_id: str) -> tuple[FixtureApplication, ...]:
        """某案例在某组上的实施结论（未请求时为空）。

        结论按**请求**给，而不是按适用组别过滤：案例要的是「检索为空」而某组不适用时，
        必须留下一条 `applied=False` 的记录说明原因，否则统计里会看不到这条缺口。
        """
        applications: list[FixtureApplication] = []
        for name, requested_by in self.requested.get(case_id, ()):
            if name in OUT_OF_HARNESS:
                applications.append(
                    FixtureApplication(
                        name=name,
                        requested_by=requested_by,
                        systems=(),
                        applied=False,
                        impl=None,
                        note=OUT_OF_HARNESS[name],
                        status="out_of_harness",
                    )
                )
                continue
            supported_systems, impl = SUPPORTED.get(name, ((), ""))
            if not supported_systems:
                applications.append(
                    FixtureApplication(
                        name=name,
                        requested_by=requested_by,
                        systems=(),
                        applied=False,
                        impl=None,
                        note=UNSUPPORTED.get(name, "未知 fixture：注册表里没有这一项，按未实施处理"),
                        status="unsupported" if name in UNSUPPORTED else "unknown",
                    )
                )
                continue
            if system_id not in supported_systems:
                applications.append(
                    FixtureApplication(
                        name=name,
                        requested_by=requested_by,
                        systems=supported_systems,
                        applied=False,
                        impl=impl,
                        note=f"该 fixture 只在 {supported_systems} 上实施，本组 {system_id} 无对等注入点",
                        status="not_applicable",
                    )
                )
                continue
            applications.append(
                FixtureApplication(
                    name=name,
                    requested_by=requested_by,
                    systems=supported_systems,
                    applied=True,
                    impl=impl,
                    note="已实施：故障在运行的真实接缝上发生，不是提示词里的一句话",
                )
            )
        return tuple(applications)

    def active(self, case_id: str, system_id: str, name: str) -> bool:
        """某一 fixture 在某轮是否真的生效（适配器据此改变行为）。"""
        return any(item.applied and item.name == name for item in self.plan_for(case_id, system_id))

    def summary(self, system_ids: tuple[str, ...]) -> dict[str, Any]:
        """整批的注入统计：按 (案例 × 组别) 计数，让「哪一类没测成」一眼可见。

        `requested` 记「有多少个 case-group 请求了这一故障」，
        `applied` 记「其中真的实施了几个」，`not_applicable` 记「因为该组没有注入点而没做」。

        未实施的原因**按状态分开计数**：`unsupported`（还没做）、`out_of_harness`
        （工具做不到）、`unknown`（注册表里没有）。此前把 unsupported 也算进
        `not_applicable`，读起来像「该组没有注入点」，而真实原因是「这一类没测成」。
        """
        requested: dict[str, int] = {}
        applied: dict[str, int] = {}
        not_applicable: dict[str, int] = {}
        unsupported_counts: dict[str, int] = {}
        out_of_harness: dict[str, int] = {}
        unknown_counts: dict[str, int] = {}

        def _bump(bucket: dict[str, int], name: str) -> None:
            bucket[name] = bucket.get(name, 0) + 1

        for case_id in self.requested:
            for system_id in system_ids:
                for application in self.plan_for(case_id, system_id):
                    _bump(requested, application.name)
                    if application.applied:
                        _bump(applied, application.name)
                    elif application.status == "out_of_harness":
                        _bump(out_of_harness, application.name)
                    elif application.status == "unsupported":
                        _bump(unsupported_counts, application.name)
                    elif application.status == "not_applicable":
                        _bump(not_applicable, application.name)
                    else:
                        _bump(unknown_counts, application.name)
        return {
            "registry_version": REGISTRY_VERSION,
            "registry_sha256": self.registry_sha256,
            "requested_counts": requested,
            "applied_counts": applied,
            "not_applicable_counts": not_applicable,
            "unsupported_counts": unsupported_counts,
            "out_of_harness_counts": out_of_harness,
            "unknown_counts": unknown_counts,
            "unsupported": {name: UNSUPPORTED[name] for name in requested if name in UNSUPPORTED},
            "out_of_harness": {name: OUT_OF_HARNESS[name] for name in requested if name in OUT_OF_HARNESS},
            "unknown": sorted(
                name
                for name in requested
                if name not in SUPPORTED and name not in UNSUPPORTED and name not in OUT_OF_HARNESS
            ),
            "note": "applied 之外的每一条都写了原因；`out_of_harness` 表示该场景不经过程序内 "
            "runner，本工具未覆盖，不得写成「已注入」",
        }


def empty_plan() -> FaultPlan:
    """没有任何注入的批次（默认）。"""
    return FaultPlan(requested={})


def load_plan(path: Path | None) -> FaultPlan:
    """读 fixtures 配置。

    文件格式（`--fixtures`）::

        {"cases": {"CFB-T-033": ["retrieval_empty"], "CFB-T-035": ["tool_search_unavailable"]}}

    也支持 `{"cases": {"CFB-T-033": [{"name": "retrieval_empty", "requested_by": "config"}]}}`，
    便于主 agent 注明裁定来源。

    Raises:
        ValueError: 文件不是合法 JSON、结构不符，或出现空 fixture 名。
    """
    if path is None:
        return empty_plan()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"fixtures 配置不是合法 JSON：{path}（{exc.msg}）") from exc
    cases = raw.get("cases") if isinstance(raw, dict) else None
    if not isinstance(cases, dict):
        raise ValueError(f"fixtures 配置缺少 cases 对象：{path}")

    requested: dict[str, tuple[tuple[str, str], ...]] = {}
    for case_id, entries in cases.items():
        if not isinstance(entries, list):
            raise ValueError(f"fixtures 配置里 {case_id} 必须是数组")
        resolved: list[tuple[str, str]] = []
        for entry in entries:
            if isinstance(entry, str):
                name, requested_by = entry, "config"
            elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
                name, requested_by = entry["name"], str(entry.get("requested_by") or "config")
            else:
                raise ValueError(f"fixtures 配置里 {case_id} 的项形状不合法：{entry!r}")
            if not name.strip():
                raise ValueError(f"fixtures 配置里 {case_id} 有空 fixture 名")
            resolved.append((name, requested_by))
        requested[case_id] = tuple(resolved)
    return FaultPlan(requested=requested)


def plan_from_cases(cases: list[Any]) -> FaultPlan:
    """把案例自带的 `fixtures` 字段并入计划（`extra["fixtures"]`）。

    案例自带的声明一律标 `requested_by="case"`：这与配置文件区分开，便于事后判断
    「这条故障是案例设计的，还是运维在运行时加的」。
    """
    requested: dict[str, tuple[tuple[str, str], ...]] = {}
    for case in cases:
        declared = case.extra.get("fixtures")
        if not declared:
            continue
        if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
            raise ValueError(f"案例 {case.id} 的 fixtures 必须是字符串数组")
        requested[case.id] = tuple((name, "case") for name in declared)
    return FaultPlan(requested=requested)


def merge(*plans: FaultPlan) -> FaultPlan:
    """合并多份计划：同一案例的同一 fixture 只保留一次（保留先出现的来源）。

    去重按**名字**而不是（名字, 来源）：同一个 fixture 被案例与配置文件同时声明时，
    它们要施加的是同一个故障；留成两条会让统计把一次注入数成两次。
    """
    merged: dict[str, list[tuple[str, str]]] = {}
    for plan in plans:
        for case_id, entries in plan.requested.items():
            bucket = merged.setdefault(case_id, [])
            known = {name for name, _ in bucket}
            for name, requested_by in entries:
                if name not in known:
                    bucket.append((name, requested_by))
                    known.add(name)
    return FaultPlan(requested={case_id: tuple(entries) for case_id, entries in merged.items()})


__all__ = [
    "REGISTRY_VERSION",
    "OUT_OF_HARNESS",
    "SUPPORTED",
    "UNSUPPORTED",
    "FaultPlan",
    "FixtureApplication",
    "empty_plan",
    "load_plan",
    "merge",
    "plan_from_cases",
]
