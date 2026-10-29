"""批次执行：按固定协议把 A/B/C 跑满，落原始记录，并支持中断续跑。

职责：编排一次批次——案例顺序、组别轮换、固定第二轮、超时与重试、逐条落盘、
进度与 manifest 更新、失败清单派生。

边界：不实现各组（`systems/*`）、不做统计（`summarize`）、不校验证据包（`verify`）。

四条不可协商的执行规则（每条都能在 outputs.jsonl 里被核对）：

1. **每个 case-group 一个新会话**，三组各自独立（协议 05 第 4 节）。会话 id 与合成账号
   都落进记录，续跑据此复用同一段对话，而不是重开一段。
2. **第二轮只在案例自带 `followup` 时跑**，文本固定取自案例（协议 02 第 1 节）。
3. **组别顺序按案例序号轮换** `ABC/BCA/CAB`（协议 04 第 3 节），顺序取自配置而非命令行。
4. **外层重试至多一次，只对 `error`/`timeout`**，且首错记录保留（协议 04 第 3 节）。

中断语义：每条尝试落盘后立即 fsync；`resume` 只补「没有最终结论」的轮次，绝不重跑
已有最终结论的轮次，也绝不改已落盘的原始输出。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from campfire.core.config import Settings

from . import prompts
from .cases import Case, CaseSet
from .config import RunConfig
from .faults import FaultPlan
from .hashing import batch_fingerprint, sha256_file, sha256_text, sha256_value
from .knowledge import REPO_ROOT, KnowledgeSnapshot, require_isolated_database
from .manifest import build_manifest, utc_now
from .records import (
    GroupProgress,
    effective_records,
    group_progress,
    group_session,
    is_final,
    needs_attempt,
    next_attempt,
    prior_turns,
    progress_summary,
)
from .store import RunStore, create_run_dir, read_jsonl, trailing_partial_line, write_jsonl
from .systems import STATUS_ERROR, STATUS_TIMEOUT, SystemAdapter, TurnInput, TurnOutcome

#: 日志回调类型（CLI 传 print；测试传空实现）。
Logger = Callable[[str], None]


class ResumeRejected(RuntimeError):
    """续跑被拒绝：批次身份不一致（案例/配置/代码变了），不能把两批混成一批。"""


@dataclass
class ExecutionResult:
    """一次执行的结果摘要（CLI 打印与后续 summarize 用）。"""

    run_id: str
    batch_id: str
    status: str
    progress: dict[str, int]
    attempts_written: int


def new_run_id(config: RunConfig, *, now: str | None = None) -> str:
    """生成批次标识：`carebench-<label>-<时间>-<短随机>`（可读且唯一）。"""
    stamp = (now or utc_now()).replace(":", "").replace("-", "").replace("+0000", "Z")
    return f"carebench-{config.label}-{stamp}-{uuid.uuid4().hex[:6]}"


def _resolve_cases(case_set: CaseSet, case_ids: list[str] | None) -> list[Case]:
    """按命令行筛选案例（保持文件顺序）。"""
    if not case_ids:
        return list(case_set.cases)
    wanted = set(case_ids)
    unknown = wanted - set(case_set.ids)
    if unknown:
        raise ValueError(f"案例集里没有这些 id：{sorted(unknown)}")
    return [case for case in case_set.cases if case.id in wanted]


async def execute(
    *,
    store: RunStore,
    config: RunConfig,
    case_set: CaseSet,
    snapshot: KnowledgeSnapshot,
    faults: FaultPlan,
    settings: Settings,
    adapters: dict[str, SystemAdapter] | None = None,
    case_ids: list[str] | None = None,
    resume: bool = False,
    dry_run: bool = False,
    log: Logger = print,
) -> ExecutionResult:
    """执行（或续跑）一次批次。

    Args:
        adapters: 测试缝——传入替身即走完全相同的编排逻辑而不调用外部模型。
        case_ids: 只跑这些案例（调试用；分母仍按 manifest 里的案例集声明）。
        resume: 续跑模式（读取已有记录，只补缺失）。
        dry_run: 只装配并写 manifest，不发起任何模型调用。

    Raises:
        ResumeRejected: 续跑时批次身份与已落盘记录不一致。
        KnowledgeSnapshotError: 数据库不是评测库（隔离守卫）。
        ValueError: 案例筛选非法。
    """
    run_id = store.root.name
    require_isolated_database(settings.database_url)

    created_at = utc_now()
    existing: list[dict[str, Any]] = store.read_outputs()
    dataset_sha = case_set.sha256
    config_sha = config.sha256
    code_commit = _code_commit(REPO_ROOT)
    fingerprint = batch_fingerprint(
        dataset_sha256=dataset_sha,
        config_sha256=config_sha,
        code_commit=code_commit,
    )

    if resume:
        _require_same_batch(existing, fingerprint=fingerprint, store=store)
        frozen = store.read_manifest() if store.manifest_path.exists() else None
        created_at = str((frozen or {}).get("created_at") or created_at)
        if trailing_partial_line(store.outputs_path):
            log("注意：outputs.jsonl 末尾有一行不完整记录（上次中断留下），已忽略该行并继续。")

    _ensure_frozen_copy(store=store, case_set=case_set, config=config)
    cases = _resolve_cases(case_set, case_ids)
    case_index = {case.id: index for index, case in enumerate(case_set.cases)}

    # --- 装配 ---
    bundle_owned = False
    if adapters is None:
        from .systems import build_adapters

        bundle = build_adapters(settings=settings, config=config, faults=faults)
        adapters = bundle.adapters
        bundle_owned = True
    metas = {}
    for system_id in config.systems:
        metas[system_id] = await adapters[system_id].prepare()
        log(f"装配完成：{system_id} = {metas[system_id].assembly}")

    state_progress = group_progress(existing, cases=case_set.cases, system_ids=list(config.systems), config=config)
    manifest = build_manifest(
        run_id=run_id,
        config=config,
        case_set=case_set,
        snapshot=snapshot,
        system_metas=metas,
        faults=faults,
        settings=settings,
        repo_root=REPO_ROOT,
        created_at=created_at,
        status="dry_run" if dry_run else ("running" if not resume else "running"),
        progress=state_progress,
    )
    store.write_manifest(manifest)
    if dry_run:
        _write_state(store, run_id=run_id, batch_id=fingerprint, status="dry_run", progress=state_progress)
        log(
            f"dry-run：计划 {len(cases)} 个案例 × {len(config.systems)} 组 = {len(cases) * len(config.systems)} 个 case-group"
        )
        return ExecutionResult(
            run_id=run_id,
            batch_id=fingerprint,
            status="dry_run",
            progress=progress_summary(state_progress),
            attempts_written=0,
        )

    attempts_written = 0
    records = existing
    try:
        for case in cases:
            index = case_index[case.id]
            order = config.order_for(index)
            for system_id in order:
                adapter = adapters[system_id]
                records, written = await _run_case_group(
                    adapter=adapter,
                    case=case,
                    system_id=system_id,
                    store=store,
                    config=config,
                    faults=faults,
                    records=records,
                    run_id=run_id,
                    batch_id=fingerprint,
                    log=log,
                )
                attempts_written += written
            progress = group_progress(records, cases=case_set.cases, system_ids=list(config.systems), config=config)
            _write_state(store, run_id=run_id, batch_id=fingerprint, status="running", progress=progress)
            store.write_manifest(
                build_manifest(
                    run_id=run_id,
                    config=config,
                    case_set=case_set,
                    snapshot=snapshot,
                    system_metas=metas,
                    faults=faults,
                    settings=settings,
                    repo_root=REPO_ROOT,
                    created_at=created_at,
                    status="running",
                    progress=progress,
                )
            )
            log(f"{case.id} 完成（本轮写入 {attempts_written} 条尝试记录）")
    finally:
        if bundle_owned:
            await bundle.aclose()

    final_progress = group_progress(records, cases=case_set.cases, system_ids=list(config.systems), config=config)
    summary = progress_summary(final_progress)
    status = "completed" if summary["case_groups_complete"] == summary["case_groups_expected"] else "partial"
    store.write_manifest(
        build_manifest(
            run_id=run_id,
            config=config,
            case_set=case_set,
            snapshot=snapshot,
            system_metas=metas,
            faults=faults,
            settings=settings,
            repo_root=REPO_ROOT,
            created_at=created_at,
            status=status,
            progress=final_progress,
        )
    )
    _write_state(store, run_id=run_id, batch_id=fingerprint, status=status, progress=final_progress)
    _write_errors(store, records)
    log(f"批次 {status}：{summary['case_groups_complete']}/{summary['case_groups_expected']} 个 case-group 完成")
    return ExecutionResult(
        run_id=run_id,
        batch_id=fingerprint,
        status=status,
        progress=summary,
        attempts_written=attempts_written,
    )


async def _run_case_group(
    *,
    adapter: SystemAdapter,
    case: Case,
    system_id: str,
    store: RunStore,
    config: RunConfig,
    faults: FaultPlan,
    records: list[dict[str, Any]],
    run_id: str,
    batch_id: str,
    log: Logger,
) -> tuple[list[dict[str, Any]], int]:
    """跑（或补）一个 case-group 的全部轮次，返回（追加后的记录, 本次写入条数）。

    每个轮次按「预锁策略」最多跑 1 + `max_outer_retries` 次：只要有效记录还不是最终结论，
    就再跑一次（这既是首次运行的重试，也是中断续跑补跑的同一条路径——两件事共用一个判据，
    因此不会出现「首跑重试、续跑不重试」这种只在中断后才暴露的不一致）。
    """
    existing = group_session(records, case_id=case.id, system_id=system_id)
    if existing is None:
        session_id = uuid.uuid4().hex
        account_id = uuid.uuid4().hex
    else:
        session_id, account_id = existing

    pending = needs_attempt(records, case=case, system_id=system_id, config=config)
    if not pending:
        return records, 0

    await adapter.open_case(
        case=case,
        session_id=session_id,
        account_id=account_id,
        prior_turns=tuple(prior_turns(records, case_id=case.id, system_id=system_id, before_turn=min(pending))),
    )

    written = 0
    for turn in range(1, case.turns + 1):
        while True:
            effective = effective_records(records)
            settled = effective.get((case.id, system_id, turn))
            if settled is not None and is_final(settled, config):
                break
            attempt = next_attempt(records, case_id=case.id, system_id=system_id, turn=turn)
            request = TurnInput(
                case=case,
                system_id=system_id,
                turn=turn,
                session_id=session_id,
                account_id=account_id,
                attempt=attempt,
            )
            input_text = prompts.render_user_turn(
                shared_context=case.shared_context,
                message=case.message_for_turn(turn),
                is_followup=turn > 1,
            )
            started_at = utc_now()
            outcome = await _run_with_timeout(adapter=adapter, request=request, config=config)
            record = _make_record(
                run_id=run_id,
                batch_id=batch_id,
                request=request,
                outcome=outcome,
                store=store,
                input_text=input_text,
                started_at=started_at,
                faults=faults,
                attempt=attempt,
            )
            store.append_output(record)
            records = [*records, record]
            written += 1
            log(
                f"  {case.id} / {system_id} / turn{turn} / attempt{attempt} → "
                f"{record['completion_status']}（{record['latency_ms']} ms）"
            )
            if record["completion_status"] not in config.retry_on:
                break
            if attempt > config.max_outer_retries:
                break
    return records, written


async def _run_with_timeout(*, adapter: SystemAdapter, request: TurnInput, config: RunConfig) -> TurnOutcome:
    """带墙钟上限地跑一轮。

    超时不重试到「跑通为止」：一次超时就是一次超时（协议 03 第 3 节把超时计入分母）。
    外层重试策略在 `records.needs_attempt` 里统一执行，且次数上限来自配置。
    """
    started = time.monotonic()
    try:
        return await asyncio.wait_for(adapter.run_turn(request), timeout=config.turn_timeout_seconds)
    except TimeoutError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return TurnOutcome(
            status=STATUS_TIMEOUT,
            latency_ms=elapsed_ms,
            error_type="TimeoutError",
            error_detail=f"超过单轮上限 {config.turn_timeout_seconds:.0f} 秒",
            trace={
                "system_id": request.system_id,
                "turn": request.turn,
                "timeout_seconds": config.turn_timeout_seconds,
            },
        )
    except Exception as exc:  # noqa: BLE001 —— 适配器内部异常统一记失败，只留类型名
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return TurnOutcome(
            status=STATUS_ERROR,
            latency_ms=elapsed_ms,
            error_type=type(exc).__name__,
            error_detail=f"适配器抛出异常（{type(exc).__name__}）",
            trace={"system_id": request.system_id, "turn": request.turn, "exception": type(exc).__name__},
        )


def _make_record(
    *,
    run_id: str,
    batch_id: str,
    request: TurnInput,
    outcome: TurnOutcome,
    store: RunStore,
    input_text: str,
    started_at: str,
    faults: FaultPlan,
    attempt: int,
) -> dict[str, Any]:
    """把一次尝试落成 outputs.jsonl 的一条记录。"""
    trace_name = f"{request.case.id}__{request.system_id}__t{request.turn}__a{attempt}"
    trace_file = store.write_trace(trace_name, outcome.trace)
    record: dict[str, Any] = {
        "run_id": run_id,
        "batch_id": batch_id,
        "case_id": request.case.id,
        "system_id": request.system_id,
        "turn": request.turn,
        "attempt": attempt,
        "session_id": request.session_id,
        "account_id": request.account_id,
        "started_at": started_at,
        "ended_at": utc_now(),
        "latency_ms": outcome.latency_ms,
        "completion_status": outcome.status,
        "status_flags": {
            "empty_output": not outcome.raw_output.strip(),
            "refusal_suspected": prompts.refusal_suspected(outcome.raw_output),
            "refusal_is_heuristic": True,
        },
        "raw_output": outcome.raw_output,
        "error": (
            None
            if outcome.status not in {STATUS_ERROR, STATUS_TIMEOUT}
            else {
                "type": outcome.error_type,
                "code": outcome.error_code,
                "detail": outcome.error_detail,
            }
        ),
        "usage": outcome.usage,
        "tool_calls": outcome.tool_calls,
        "citations": outcome.citations,
        "trace_file": trace_file,
        "input_text": input_text,
        "input_sha256": sha256_text(input_text),
        "fixtures": [application.to_dict() for application in faults.plan_for(request.case.id, request.system_id)],
        "system_meta": outcome.meta,
    }
    # 记录自身的内容 hash：证明「原始输出事后没被改过」的唯一机械判据。
    # 不含本字段（自指）——这与冻结案例的字节 hash 是两个层次：一个防案例被改，一个防记录被改。
    record["record_sha256"] = sha256_value({key: value for key, value in record.items() if key != "record_sha256"})
    return record


def _write_state(
    store: RunStore,
    *,
    run_id: str,
    batch_id: str,
    status: str,
    progress: list[GroupProgress],
) -> None:
    """写进度快照（派生文件；verify 会核对它与 outputs.jsonl 一致）。"""
    store.write_state(
        {
            "run_id": run_id,
            "batch_id": batch_id,
            "status": status,
            "updated_at": utc_now(),
            "progress": progress_summary(progress),
            "pending_groups": [
                {"case_id": item.case_id, "system_id": item.system_id, "turns_final": item.turns_final}
                for item in progress
                if not item.complete
            ],
        }
    )


def _write_errors(store: RunStore, records: list[dict[str, Any]]) -> None:
    """派生失败/异常清单（不改原始记录，只挑出需要人眼的那些）。"""
    derived: list[dict[str, Any]] = []
    for record in effective_records(records).values():
        flags = record.get("status_flags") or {}
        if record.get("completion_status") == "completed" and not flags.get("refusal_suspected"):
            continue
        derived.append(
            {
                "case_id": record.get("case_id"),
                "system_id": record.get("system_id"),
                "turn": record.get("turn"),
                "attempt": record.get("attempt"),
                "completion_status": record.get("completion_status"),
                "error": record.get("error"),
                "refusal_suspected": bool(flags.get("refusal_suspected")),
                "empty_output": bool(flags.get("empty_output")),
                "raw_output_chars": len(str(record.get("raw_output") or "")),
                "trace_file": record.get("trace_file"),
            }
        )
    write_jsonl(store.errors_path, derived)


def _code_commit(repo_root: Path) -> str:
    """取当前代码提交（与 manifest 用的是同一个函数，避免两处口径不同）。"""
    from .manifest import code_facts

    return str(code_facts(repo_root)["commit"])


def _require_same_batch(existing: list[dict[str, Any]], *, fingerprint: str, store: RunStore) -> None:
    """续跑前核对批次指纹：不一致就拒绝，绝不合并两批。

    Raises:
        ResumeRejected: 存在不属于本批的记录，或 freeze 声明的案例 hash 与当前不符。
    """
    mismatched = {str(record.get("batch_id")) for record in existing} - {fingerprint}
    if mismatched:
        raise ResumeRejected(
            "已有记录的批次指纹与当前案例/配置/代码不一致"
            f"（记录里为 {sorted(mismatched)}，当前为 {fingerprint}）："
            "不同批次不得混跑，请新建 run 或恢复成原批次的条件"
        )
    if store.freeze_path.exists():
        from .store import read_json

        frozen = read_json(store.freeze_path)
        declared = frozen.get("dataset_sha256")
        actual = sha256_file(store.cases_path) if store.cases_path.exists() else ""
        if declared and declared != actual:
            raise ResumeRejected(
                f"run 目录内的 frozen 案例文件与 freeze.json 不一致（{declared[:12]}… ≠ {actual[:12]}…）："
                "案例文件被改过，续跑会污染批次"
            )


async def launch_run(
    *,
    runs_dir: Path,
    config: RunConfig,
    case_set: CaseSet,
    snapshot: KnowledgeSnapshot,
    faults: FaultPlan,
    settings: Settings,
    run_id: str | None = None,
    case_ids: list[str] | None = None,
    adapters: dict[str, SystemAdapter] | None = None,
    dry_run: bool = False,
    log: Logger = print,
) -> ExecutionResult:
    """新建一个批次目录并执行。

    Raises:
        FileExistsError: run_id 已存在（不允许覆盖已有证据）。
    """
    resolved_id = run_id or new_run_id(config)
    store = create_run_dir(runs_dir, resolved_id)
    return await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=snapshot,
        faults=faults,
        settings=settings,
        adapters=adapters,
        case_ids=case_ids,
        resume=False,
        dry_run=dry_run,
        log=log,
    )


async def resume_run(
    *,
    store: RunStore,
    config: RunConfig,
    case_set: CaseSet,
    snapshot: KnowledgeSnapshot,
    faults: FaultPlan,
    settings: Settings,
    case_ids: list[str] | None = None,
    adapters: dict[str, SystemAdapter] | None = None,
    log: Logger = print,
) -> ExecutionResult:
    """续跑一个已有批次（只补没有最终结论的轮次）。"""
    return await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=snapshot,
        faults=faults,
        settings=settings,
        adapters=adapters,
        case_ids=case_ids,
        resume=True,
        dry_run=False,
        log=log,
    )


def _ensure_frozen_copy(*, store: RunStore, case_set: CaseSet, config: RunConfig) -> None:
    """保证 run 目录自带案例副本与冻结记录（续跑时核对，不一致即拒绝）。

    放在 `execute` 而不是 `launch_run`：无论从哪个入口进来的批次目录，都必须自证
    「跑的是哪一版案例」；否则用一个自造目录跑出来的记录无法复核。
    """
    if store.cases_path.exists():
        actual = sha256_file(store.cases_path)
        if actual != case_set.sha256:
            raise ResumeRejected(
                f"run 目录内的案例文件与本次案例集不一致（{actual[:12]}… ≠ {case_set.sha256[:12]}…）："
                "同一目录不得混入另一份案例"
            )
    else:
        _copy_frozen_cases(store=store, case_set=case_set)
    if not store.freeze_path.exists():
        _write_freeze(store=store, case_set=case_set, config=config)


def _copy_frozen_cases(*, store: RunStore, case_set: CaseSet) -> None:
    """把（已冻结的）案例文件逐字节复制进 run 目录。

    逐字节而不是重新序列化：run 目录里的案例文件必须与冻结文件 hash 相同，
    否则「跑的是哪一版案例」重新变成一个需要相信的说法。
    """
    store.cases_path.write_bytes(case_set.raw_bytes)


def _write_freeze(*, store: RunStore, case_set: CaseSet, config: RunConfig) -> None:
    """写 run 目录内的 freeze.json（案例与配置身份；批次指纹在 manifest 里）。"""
    from .manifest import code_facts
    from .store import write_json

    write_json(
        store.freeze_path,
        {
            "created_at": utc_now(),
            "dataset_path": str(case_set.path),
            "dataset_sha256": case_set.sha256,
            "cases_sha256": sha256_file(store.cases_path),
            "case_count": len(case_set.cases),
            "case_ids": list(case_set.ids),
            "config_sha256": config.sha256,
            "code": code_facts(REPO_ROOT),
        },
    )


def load_run_outputs(store: RunStore) -> list[dict[str, Any]]:
    """读取 run 目录的输出记录（供 summarize / verify / review 复用）。"""
    return read_jsonl(store.outputs_path)


__all__ = [
    "ExecutionResult",
    "Logger",
    "ResumeRejected",
    "execute",
    "launch_run",
    "load_run_outputs",
    "new_run_id",
    "resume_run",
]
