"""开工前预检：把「能不能跑、跑在什么条件上」一次问清楚（协议 05 第六节 P0）。

职责：核对工作区、协议快照、案例集、知识快照与评测库、模型与嵌入端点、技能与工具池装配、
C 组运行器能否装出来；给出**阻断项**与**告警项**两类结论。

边界：**不发起生成调用**（不烧额度、不污染结果）。唯一会真实联网的检查是
`--probe-model`（`GET /models`，不消耗生成额度）与 `--probe-embedding`（一次查询嵌入），
两者都必须显式开启。

「缺一项就假装完成」是本工具最该避免的事（协议 05 第 6 节 P0 的原话）：任何一项
查不出来，就在报告里写成 `unknown/未核`，而不是给一个绿色对勾。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from campfire.core.config import Settings
from campfire.core.db import session_scope

from .cases import CaseValidationError, load_case_file
from .config import RunConfig
from .faults import plan_from_cases
from .knowledge import (
    DEFAULT_DB_PREFIX,
    REPO_ROOT,
    KnowledgeSnapshotError,
    database_name,
    endpoint_host,
    is_loopback,
    load_snapshot_manifest,
    read_database_state,
    require_isolated_database,
)
from .manifest import code_facts, environment_facts, protocol_snapshot_facts, utc_now


def _is_database_reachable(url: str | None) -> tuple[bool, str]:
    """同步 socket 探一次数据库端口（不建连接，不改数据）。"""
    import socket
    from urllib.parse import urlparse

    if not url:
        return False, "未配置 DATABASE_URL"
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True, f"{host}:{port} 可连"
    except OSError as exc:
        return False, f"{host}:{port} 不可连（{type(exc).__name__}）"


async def run_preflight(
    *,
    settings: Settings,
    config: RunConfig,
    cases_path: Path | None = None,
    knowledge_snapshot: Path | None = None,
    db_prefix: str = DEFAULT_DB_PREFIX,
    probe_model: bool = False,
    probe_embedding: bool = False,
    fixtures_path: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """执行预检并返回报告字典。

    报告结构：`ready`（无阻断项）、`blocking`、`warnings`、`facts`、`checked_at`。
    """
    blocking: list[str] = []
    warnings: list[str] = []
    facts: dict[str, Any] = {}

    # --- 1. 工作区与协议 ---
    code = code_facts(REPO_ROOT)
    facts["code"] = code
    facts["environment"] = environment_facts(REPO_ROOT)
    if code["dirty"]:
        warnings.append(f"工作区有未提交改动（{len(code['dirty_files'])} 个文件）：本批次复现性只到「本地状态」")
    protocol = protocol_snapshot_facts()
    facts["protocol_snapshot"] = protocol
    if not protocol["files"]:
        blocking.append("协议快照缺失：evaluation/carebench/protocol/ 下没有 md 文件")
    log(f"[preflight] 代码 {code['commit'][:12]}（{code['branch']}）· 协议快照 {protocol['sha256'][:12]}")

    # --- 2. 配置 ---
    facts["config_sha256"] = config.sha256
    facts["config"] = config.to_dict()
    log(f"[preflight] 配置 hash {config.sha256[:12]} · 组别 {list(config.systems)} · 轮换 {list(config.rotation)}")

    # --- 3. 案例集 ---
    if cases_path is not None:
        try:
            case_set = load_case_file(cases_path)
        except (CaseValidationError, FileNotFoundError) as exc:
            blocking.append(f"案例集不可用：{exc}")
            case_set = None
        if case_set is not None:
            plan = plan_from_cases(list(case_set.cases))
            facts["cases"] = {
                "path": str(cases_path),
                "sha256": case_set.sha256,
                "count": len(case_set.cases),
                "split": case_set.split,
                "review_status_counts": case_set.review_status_counts,
                "formal_ready": all(case.approved for case in case_set.cases),
                "turns": {case.id: case.turns for case in case_set.cases},
                "two_turn_cases": sum(1 for case in case_set.cases if case.turns == 2),
                "case_fixtures": {
                    case_id: [name for name, _ in entries] for case_id, entries in plan.requested.items()
                },
                "case_groups": len(case_set.cases) * len(config.systems),
            }
            if not all(case.approved for case in case_set.cases):
                warnings.append(
                    f"案例 review_status={case_set.review_status_counts}：结果只能作为原始观察，"
                    "任何专业结论必须标 needs_review"
                )
            log(
                f"[preflight] 案例 {len(case_set.cases)} 个 · 双轮 {facts['cases']['two_turn_cases']} 个 · "
                f"case-group {facts['cases']['case_groups']} 个"
            )

    # --- 4. 知识快照与评测库 ---
    try:
        name = require_isolated_database(settings.database_url, prefix=db_prefix)
        facts["database"] = {"name": name, "isolated": True}
        log(f"[preflight] 评测库 {name}（隔离校验通过）")
    except KnowledgeSnapshotError as exc:
        blocking.append(str(exc))
        facts["database"] = {"name": database_name(settings.database_url), "isolated": False}

    reachable, detail = _is_database_reachable(settings.database_url)
    facts["database_reachable"] = {"ok": reachable, "detail": detail}
    if not reachable:
        blocking.append(f"数据库不可达：{detail}")

    if reachable:
        try:
            snapshot, _paths = load_snapshot_manifest(knowledge_snapshot)
            async with session_scope(settings) as session:
                db_snapshot = await read_database_state(
                    session,
                    snapshot=snapshot,
                    database=database_name(settings.database_url),
                )
        except Exception as exc:  # noqa: BLE001 —— 预检失败要如实报，不抛栈
            blocking.append(f"知识快照核对失败：{type(exc).__name__}: {exc}")
        else:
            facts["knowledge_snapshot"] = {
                "sha256": db_snapshot.sha256,
                "snapshot_version": db_snapshot.snapshot_version,
                "included_files": len(db_snapshot.files),
                "items": len(db_snapshot.items),
                "nodes": sum(item.nodes for item in db_snapshot.items),
                "case_items": db_snapshot.case_item_count,
                "violations": list(db_snapshot.violations),
                "blocked_corpora": len(db_snapshot.blocked),
                "excluded_corpora": len(db_snapshot.excluded_corpora),
            }
            if db_snapshot.violations:
                blocking.extend(db_snapshot.violations)
            log(
                f"[preflight] 知识快照 {db_snapshot.sha256[:12]} · {len(db_snapshot.items)} 条 / "
                f"{sum(item.nodes for item in db_snapshot.items)} 节点 · 案例条目 {db_snapshot.case_item_count}"
            )

    # --- 5. 模型与嵌入端点 ---
    chat_host = endpoint_host(settings.tokenhub_base_url)
    embedding_host = endpoint_host(settings.resolved_embedding_base_url)
    embeddings_separated = embedding_host != chat_host
    facts["endpoints"] = {
        "chat_host": chat_host,
        "embedding_host": embedding_host,
        "separated": embeddings_separated,
        "chat_key_configured": settings.tokenhub_api_key is not None,
        "embedding_key_configured": settings.resolved_embedding_api_key is not None,
        "model_id": settings.model_name,
    }
    if settings.tokenhub_api_key is None:
        blocking.append("未配置 TOKENHUB_API_KEY：模型调用无法建立")
    if settings.resolved_embedding_api_key is None:
        blocking.append("未配置嵌入凭据：B 组检索与知识核对都跑不了")
    if not embeddings_separated and is_loopback(chat_host):
        blocking.append(
            f"嵌入端点与对话端点同一个本机网关（{chat_host}）：本机网关通常只提供 chat completions，"
            "嵌入会 404，而产品里表现为「没有资料」。必须显式配置 EMBEDDING_BASE_URL/EMBEDDING_API_KEY"
        )
    log(
        f"[preflight] 对话端点 {chat_host} · 嵌入端点 {embedding_host}"
        f"（{'已分开' if embeddings_separated else '共用'}）· 模型 {settings.model_name}"
    )

    if probe_model:
        from campfire.agent.model import check_model_endpoint

        try:
            report = await check_model_endpoint(settings)
        except Exception as exc:  # noqa: BLE001 —— 探针异常要如实报
            warnings.append(f"模型端点探测异常：{type(exc).__name__}")
        else:
            facts["model_probe"] = {
                "configured": report.configured,
                "reachable": report.reachable,
                "detail": report.detail,
            }
            if not report.reachable:
                warnings.append(f"模型端点探测不可达：{report.detail}")
            log(f"[preflight] 模型探测：reachable={report.reachable}（{report.detail}）")

    if probe_embedding:
        from campfire.modules.library.embedding import build_embedding

        try:
            embedder = build_embedding(settings)
            vector = await embedder.aget_query_embedding("孤独症儿童 感官过载 应对")
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"嵌入真实调用失败（{type(exc).__name__}）：B 组检索无法工作")
        else:
            facts["embedding_probe"] = {"dim": len(vector), "nonzero": any(value != 0 for value in vector)}
            if len(vector) == 0 or not any(value != 0 for value in vector):
                blocking.append("嵌入返回全零向量：检索会静默失准")
            log(f"[preflight] 嵌入探测：维度 {len(vector)}")

    # --- 6. 技能、工具池与 C 组装配 ---
    try:
        from campfire.agent.model import ModelGateway
        from campfire.surfaces.consult import assembly as consult_assembly
        from campfire.surfaces.consult import composition

        gateway = ModelGateway(settings)
        try:
            composition.install(settings, gateway=gateway)
            runner = consult_assembly.get_runner(settings)
            skills = consult_assembly.get_skill_registry(settings)
            pool = composition.build_tool_pool(skills)
            facts["assembly"] = {
                "tool_pool": list(pool.names()),
                "skills": list(skills.names()),
                "runner": type(runner).__name__,
                "installed": True,
            }
            log(f"[preflight] C 组装配：工具 {len(pool.names())} 个 · skill {len(skills.names())} 个")
        finally:
            await gateway.aclose()
    except Exception as exc:  # noqa: BLE001 —— 装配失败是阻断项，不是告警
        blocking.append(f"C 组生产装配失败（{type(exc).__name__}）：{exc}")

    # --- 7. 故障注入计划 ---
    try:
        if fixtures_path is not None:
            from .faults import load_plan

            plan = load_plan(fixtures_path)
            facts["fault_plan"] = plan.summary(tuple(config.systems))
            if facts["fault_plan"]["unknown"]:
                warnings.append(f"fixtures 配置含未注册的 fixture：{facts['fault_plan']['unknown']}")
            log(f"[preflight] 故障注入：请求 {facts['fault_plan']['requested_counts'] or '无'}")
    except Exception as exc:  # noqa: BLE001
        blocking.append(f"fixtures 配置不可用（{type(exc).__name__}）：{exc}")

    report = {
        "checked_at": utc_now(),
        "ready": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "facts": facts,
        "scope_note": "预检不发起生成调用；它证明「装配与条件可行」，不证明模型质量或安全。",
    }
    return report


__all__ = ["run_preflight"]
