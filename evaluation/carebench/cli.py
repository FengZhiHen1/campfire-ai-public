"""命令行：`uv run python -m evaluation.carebench <命令>`。

职责：参数解析、命令分发与退出码。

边界：不实现任何评测逻辑（各命令都在自己的模块里）。

命令职责（见 README「接口」一节）：

- `preflight`：开工前核对工作区/案例/知识快照与库/端点/装配（可显式探测模型与嵌入）；
- `identity`：打印当前运行身份（模型/端点/嵌入/知识快照，无凭据、无生成调用），供冻结前锁定；
- `freeze`：把案例集与配置冻结成不可再改的身份；
- `run`：新建批次并跑 A/B/C；
- `resume`：补跑中断批次（只补没有最终结论的轮次）；
- `review-export`：导出盲化评审包 + 空评分表；
- `review-import`：校验并导入人工评分（空值/pending 一律拒收）；
- `ai-prepare` / `ai-score` / `ai-adjudicate`：冻结独立 AI 评分身份、执行与分歧复核；
- `summarize`：按实测数据出计数/时延/token，人工与 AI 分数独立列出；
- `verify`：复算证据包（哈希、分母、公平性、盲化、summary 一致性）。

退出码：0 = 通过；1 = 存在阻断项/违反项（或运行状态不完整）；2 = 用法或输入错误。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from .ai_review import identity_path, prepare_ai_review
from .cases import CaseValidationError, parse_cases
from .config import FORMAL_LABEL, RunConfig, load_config
from .faults import load_plan, merge, plan_from_cases
from .freeze import FreezeError, freeze_cases, load_frozen
from .knowledge import (
    DEFAULT_DB_PREFIX,
    KnowledgeSnapshot,
    KnowledgeSnapshotError,
    load_snapshot_manifest,
    read_database_state,
    require_isolated_database,
)
from .manifest import identity_fingerprint, runtime_identity, utc_now
from .preflight import run_preflight
from .review import ReviewError, export_packet, import_ratings
from .runner import ResumeRejected, launch_run, resume_run
from .store import RunStore
from .summarize import summarize_run
from .verify import verify_run

#: 默认落点（相对仓库根）。`frozen/` 与 `runs/` 都是评测目录内的子目录。
PACKAGE_DIR = Path(__file__).resolve().parent

#: 默认运行目录。
DEFAULT_RUNS_DIR = PACKAGE_DIR / "runs"

#: 默认冻结目录根。
DEFAULT_FROZEN_ROOT = PACKAGE_DIR / "frozen"


def build_parser() -> argparse.ArgumentParser:
    """装配命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.carebench",
        description="CareBench 评测工具：A/B/C 三组真实运行、原始记录、盲化评审与只按实测数据汇总。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--config", type=Path, default=None, help="运行配置覆盖文件（JSON）")

    preflight = sub.add_parser("preflight", help="开工前预检（不发起生成调用）")
    add_common(preflight)
    preflight.add_argument("--cases", type=Path, default=None, help="待冻结/待运行的案例 JSONL")
    preflight.add_argument(
        "--frozen", type=Path, default=None, help="冻结目录：用它声明的案例与配置（与 run 的 hash 完全一致）"
    )
    preflight.add_argument("--knowledge-snapshot", type=Path, default=None, help="知识许可裁定表（缺省用包内清单）")
    preflight.add_argument("--fixtures", type=Path, default=None, help="故障注入计划文件")
    preflight.add_argument("--db-prefix", default=DEFAULT_DB_PREFIX, help="评测库名前缀（隔离守卫）")
    preflight.add_argument("--probe-model", action="store_true", help="真实探测模型端点（GET /models，不烧额度）")
    preflight.add_argument("--probe-embedding", action="store_true", help="真实调用一次查询嵌入")
    preflight.add_argument("--json", action="store_true", help="以 JSON 输出报告")

    freeze = sub.add_parser("freeze", help="冻结案例集与配置")
    add_common(freeze)
    freeze.add_argument("--cases", type=Path, required=True, help="案例 JSONL")
    freeze.add_argument("--label", choices=("calibration", "pilot", "test"), required=True)
    freeze.add_argument("--out", type=Path, default=None, help="冻结目录（缺省 frozen/<label>）")
    freeze.add_argument("--operator", default=None, help="冻结人（缺省取环境变量）")
    freeze.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="运行身份文件（`carebench identity` 的输出）：冻结时锁定模型/端点/嵌入/知识快照；label=test 必须提供",
    )

    identity = sub.add_parser("identity", help="打印当前运行身份（无凭据、不发起生成调用）")
    add_common(identity)
    identity.add_argument("--knowledge-snapshot", type=Path, default=None, help="知识许可裁定表（缺省用包内清单）")
    identity.add_argument("--out", type=Path, default=None, help="写到文件而不是标准输出（供 freeze --identity）")

    run = sub.add_parser("run", help="新建批次并运行 A/B/C")
    add_common(run)
    run.add_argument("--frozen", type=Path, required=True, help="冻结目录（含 cases.frozen.jsonl 与 freeze.json）")
    run.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR, help="批次落点根目录")
    run.add_argument("--run-id", default=None, help="批次标识（缺省自动生成）")
    run.add_argument("--case-ids", default=None, help="只跑这些案例（逗号分隔；用于调试子集）")
    run.add_argument("--fixtures", type=Path, default=None, help="故障注入计划文件")
    run.add_argument("--dry-run", action="store_true", help="只装配并写 manifest，不发起模型调用")
    run.add_argument("--allow-config-drift", action="store_true", help="允许运行配置与冻结时声明的配置不同")

    resume = sub.add_parser("resume", help="续跑中断批次")
    add_common(resume)
    resume.add_argument("--run", type=Path, required=True, help="批次目录")
    resume.add_argument("--case-ids", default=None, help="只补这些案例（逗号分隔）")
    resume.add_argument("--fixtures", type=Path, default=None, help="故障注入计划文件")

    export = sub.add_parser("review-export", help="导出盲化评审包与空评分表")
    export.add_argument("--run", type=Path, required=True, help="批次目录")

    import_cmd = sub.add_parser("review-import", help="校验并导入人工评分")
    import_cmd.add_argument("--run", type=Path, required=True, help="批次目录")
    import_cmd.add_argument("--ratings", type=Path, required=True, help="填好的评分 CSV")
    import_cmd.add_argument("--adjudication", type=Path, default=None, help="分歧裁定 CSV（可选）")

    ai_prepare = sub.add_parser("ai-prepare", help="冻结两套 AI 评分提示与裁定者身份（正式生成前执行）")
    ai_prepare.add_argument("--run", type=Path, required=True, help="先以 run --dry-run 创建的批次目录")
    ai_prepare.add_argument("--model", default=None, help="评分模型 ID（缺省应用配置模型）")
    ai_prepare.add_argument("--pass2-model", default=None, help="第二评分者模型 ID（缺省同模型，独立提示和上下文）")
    ai_prepare.add_argument("--adjudicator-model", default=None, help="裁定者模型 ID（缺省同评分模型）")
    ai_prepare.add_argument("--temperature", type=float, default=0.0)

    for command, help_text in (
        ("ai-score", "执行两套独立 AI 评分（失败追加、不覆盖成功分）"),
        ("ai-adjudicate", "独立复核分歧（保留原分与全部裁定尝试）"),
    ):
        target = sub.add_parser(command, help=help_text)
        target.add_argument("--run", type=Path, required=True)
        target.add_argument("--blind-ids", default=None, help="仅处理这些盲化编号（逗号分隔）")
        target.add_argument("--max-concurrency", type=int, default=4)
        if command == "ai-score":
            target.add_argument("--pass", dest="passes", type=int, choices=(1, 2), nargs="+", default=[1, 2])

    summarize = sub.add_parser("summarize", help="按实测数据汇总（无评审不出分）")
    summarize.add_argument("--run", type=Path, required=True, help="批次目录")

    verify = sub.add_parser("verify", help="复算证据包")
    verify.add_argument("--run", type=Path, required=True, help="批次目录")
    verify.add_argument("--require-complete", action="store_true", help="要求所有 case-group 都有最终结论")

    return parser


def _split_ids(raw: str | None) -> list[str] | None:
    """把逗号分隔的案例 id 拆开。"""
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def label_is_formal(config: RunConfig) -> bool:
    """该配置是否代表「正式成绩」批次。"""
    return config.label == FORMAL_LABEL


def _settings() -> Any:
    """取应用配置（唯一入口：`core/config`）。"""
    from campfire.core.config import get_settings

    return get_settings()


async def _resolve_snapshot(settings: Any, path: Path | None) -> KnowledgeSnapshot:
    """读知识快照清单并核对评测库内条目。

    Raises:
        KnowledgeSnapshotError: 库不是评测库，或库内条目不在许可清单内。
    """
    from campfire.core.db import session_scope

    require_isolated_database(settings.database_url)
    snapshot, _paths = load_snapshot_manifest(path)
    async with session_scope(settings) as session:
        return await read_database_state(
            session,
            snapshot=snapshot,
            database=(settings.database_url or "").rsplit("/", 1)[-1],
        )


def _cmd_preflight(args: argparse.Namespace) -> int:
    """执行 preflight。

    给了 `--frozen` 时，案例与配置都取自冻结记录：这样预检打印的 `config hash` 与随后
    `run` 用的是同一份（否则默认配置的 label 与冻结标签不同，两个 hash 会并列出现，
    读报告的人会以为是配置漂移）。
    """
    settings = _settings()
    config = load_config(args.config)
    cases_path = args.cases
    if args.frozen is not None:
        frozen = load_frozen(args.frozen)
        config = config if args.config else RunConfig.from_dict(frozen.record["config"])
        cases_path = frozen.case_set.path if cases_path is None else cases_path
    report = asyncio.run(
        run_preflight(
            settings=settings,
            config=config,
            cases_path=cases_path,
            knowledge_snapshot=args.knowledge_snapshot,
            db_prefix=args.db_prefix,
            probe_model=args.probe_model,
            probe_embedding=args.probe_embedding,
            fixtures_path=args.fixtures,
            log=(lambda message: None) if args.json else print,
        )
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print()
        for item in report["blocking"]:
            print(f"× 阻断：{item}")
        for item in report["warnings"]:
            print(f"! 告警：{item}")
        print("预检通过：可以开工" if report["ready"] else "预检未通过：先解决阻断项")
    return 0 if report["ready"] else 1


def _cmd_freeze(args: argparse.Namespace) -> int:
    """执行 freeze。"""
    config = load_config(args.config)
    out = args.out or (DEFAULT_FROZEN_ROOT / args.label)
    identity_payload = _load_identity_file(args.identity) if args.identity else None
    frozen = freeze_cases(
        cases_path=args.cases,
        label=args.label,
        out_dir=out,
        config=config,
        operator=args.operator,
        identity=(identity_payload or {}).get("run_identity"),
        identity_sha256=(identity_payload or {}).get("run_identity_sha256"),
    )
    record = frozen.record
    print(f"已冻结：{out}")
    print(
        f"  案例 {record['case_count']} 个 · split={record['split']} · 双轮 {record['turns_histogram'].get('2', 0)} 个"
    )
    print(f"  dataset_sha256={record['dataset_sha256']}")
    print(f"  config_sha256={record['config_sha256']}")
    locked = frozen.run_identity_sha256
    print(f"  run_identity_sha256={locked or '未锁定（仅非正式批次）'}")
    print(f"  review_status={record['review_status_counts']} · formal_ready={record['formal_ready']}")
    if not record["formal_ready"]:
        print("  注意：存在未 approved 案例，结果只能作为原始观察（不得写成已审核）")
    return 0


def _load_identity_file(path: Path) -> dict[str, Any]:
    """读 `carebench identity` 写出的身份文件，并核对形状。

    Raises:
        ValueError: 文件不是合法 JSON 对象，或缺 `run_identity` / `run_identity_sha256`。
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"身份文件必须是 JSON 对象：{path}")
    if not isinstance(raw.get("run_identity"), dict) or not str(raw.get("run_identity_sha256") or "").strip():
        raise ValueError(f"身份文件缺 run_identity / run_identity_sha256：{path}（请用 `identity` 命令生成）")
    return raw


def _cmd_identity(args: argparse.Namespace) -> int:
    """打印当前运行身份（读库核对知识快照；不发起任何生成调用）。"""
    settings = _settings()
    config = load_config(args.config)
    snapshot = asyncio.run(_resolve_snapshot(settings, args.knowledge_snapshot))
    if not snapshot.ok:
        print("拒绝输出身份：知识快照核对未通过：", file=sys.stderr)
        for item in snapshot.violations:
            print(f"  - {item}", file=sys.stderr)
        return 1
    identity = runtime_identity(settings, snapshot, config)
    payload = {
        "run_identity": identity,
        "run_identity_sha256": identity_fingerprint(identity),
        "checked_at": utc_now(),
        "note": "无凭据：只含端点主机/端口/路径、模型 id、知识快照 hash/条目/节点数与库名",
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"运行身份已写出：{args.out}（sha256={payload['run_identity_sha256']}）")
    else:
        sys.stdout.write(text)
    return 0


def _resolve_faults(frozen_dir: Path, fixtures_path: Path | None) -> tuple[Any, Any]:
    """把案例自带 fixtures 与命令行 fixtures 合并成一份计划。"""
    frozen = load_frozen(frozen_dir)
    plan = merge(plan_from_cases(list(frozen.case_set.cases)), load_plan(fixtures_path))
    return frozen, plan


async def _cmd_run_async(args: argparse.Namespace) -> int:
    """执行 run（异步）。"""
    settings = _settings()
    config = load_config(args.config)
    frozen, plan = _resolve_faults(args.frozen, args.fixtures)
    # 没显式给配置时沿用冻结记录的标签：批次标签属于「这一批是什么」，
    # 由冻结声明而不是 CLI 默认值决定。
    if args.config is None and frozen.record.get("label"):
        config = replace(config, label=str(frozen.record["label"]))

    declared = frozen.record.get("config_sha256")
    if label_is_formal(config) and args.allow_config_drift:
        print(
            "拒绝运行：正式批次（label=test）不得用 --allow-config-drift 掩盖配置漂移。\n"
            "配置属于冻结条件：要改配置就换一个冻结目录重新冻结，正式成绩必须能指回那一份声明。",
            file=sys.stderr,
        )
        return 2
    if label_is_formal(config) and frozen.run_identity is None:
        print(
            "拒绝运行：正式批次的冻结记录没有锁定运行身份（模型/端点/嵌入/知识快照）。\n"
            "请先用 `carebench identity --out <file>` 取得身份，再用 `freeze --identity <file>` 重新冻结。",
            file=sys.stderr,
        )
        return 2
    if declared and declared != config.sha256 and not args.allow_config_drift:
        print(
            "拒绝运行：运行配置与冻结时声明的配置不同"
            f"（冻结 {str(declared)[:12]}… ≠ 当前 {config.sha256[:12]}…）。\n"
            "确属有意变更请加 --allow-config-drift（它会被如实记进 manifest）。",
            file=sys.stderr,
        )
        return 2

    snapshot = await _resolve_snapshot(settings, None)
    if not snapshot.ok:
        print("拒绝运行：知识快照核对未通过：", file=sys.stderr)
        for item in snapshot.violations:
            print(f"  - {item}", file=sys.stderr)
        return 1

    result = await launch_run(
        runs_dir=args.runs_dir,
        config=config,
        case_set=frozen.case_set,
        snapshot=snapshot,
        faults=plan,
        settings=settings,
        run_id=args.run_id,
        case_ids=_split_ids(args.case_ids),
        dry_run=args.dry_run,
        expected_identity=frozen.run_identity,
        frozen_config_sha256=str(declared) if declared else None,
        config_drift_allowed=bool(args.allow_config_drift),
    )
    print()
    print(f"批次 {result.run_id}（{result.status}）· batch_id={result.batch_id}")
    print(f"进度：{result.progress}")
    print(f"本批写入尝试记录：{result.attempts_written} 条")
    print(f"目录：{args.runs_dir / result.run_id}")
    return 0 if result.status in {"completed", "dry_run"} else 1


async def _cmd_resume_async(args: argparse.Namespace) -> int:
    """执行 resume：配置与案例都取自批次自身，避免「续跑换了条件」。

    **整条链路只用一个事件循环**：数据库引擎与连接池绑定在首次使用时的事件循环上
    （`core/db` 的共享引擎），先 `asyncio.run` 解析快照、再 `asyncio.run` 续跑会让第二次
    运行拿到绑在已关闭循环上的连接池——实测报
    `got Future attached to a different loop`，表现为续跑直接崩在第一次查询上。
    """
    settings = _settings()
    store = RunStore(root=args.run)
    manifest = store.read_manifest()
    config = load_config(args.config) if args.config else RunConfig.from_dict(manifest["config"])
    case_set = parse_cases(store.cases_path.read_bytes(), source=str(store.cases_path), path=store.cases_path)
    plan = merge(plan_from_cases(list(case_set.cases)), load_plan(args.fixtures))
    snapshot = await _resolve_snapshot(settings, None)
    try:
        result = await resume_run(
            store=store,
            config=config,
            case_set=case_set,
            snapshot=snapshot,
            faults=plan,
            settings=settings,
            case_ids=_split_ids(args.case_ids),
        )
    except ResumeRejected as exc:
        print(f"拒绝续跑：{exc}", file=sys.stderr)
        return 2
    print(f"续跑完成：{result.status} · {result.progress} · 本次写入 {result.attempts_written} 条")
    return 0 if result.status == "completed" else 1


def _cmd_review_export(args: argparse.Namespace) -> int:
    """执行 review-export。"""
    store = RunStore(root=args.run)
    report = export_packet(store)
    print(f"评审包：{store.review_dir / 'blind-packet.jsonl'}（{report['exported_at_groups']} 个 case-group）")
    print(f"空评分表：{store.review_dir / 'ratings-empty.csv'}")
    print(f"盲化映射（内部，不外发）：{store.review_dir / 'blind-map.json'}")
    if report["excluded"]:
        print(
            f"排除 {len(report['excluded'])} 个案例（轮次未完成）：{[item['case_id'] for item in report['excluded']]}"
        )
    return 0


def _cmd_review_import(args: argparse.Namespace) -> int:
    """执行 review-import。"""
    store = RunStore(root=args.run)
    result = import_ratings(store, ratings_path=args.ratings, adjudication_path=args.adjudication)
    print(f"导入 {result.rows} 行 / {len(result.raters)} 位评分者 / {result.groups} 个 case-group")
    print(f"评分模式：{result.mode}（双评 {result.double_rated_groups}，单评 {result.single_rated_groups}）")
    for warning in result.warnings:
        print(f"! {warning}")
    return 0


def _cmd_ai_prepare(args: argparse.Namespace) -> int:
    """正式身份在系统生成前冻结；校准身份允许用已生成的校准输出试跑。"""
    store = RunStore(root=args.run)
    manifest = store.read_manifest()
    formal = manifest.get("label") == FORMAL_LABEL
    if formal and store.read_outputs() and not identity_path(store).exists():
        raise ValueError("正式评分身份必须在被测系统生成前冻结：请新建批次，先 run --dry-run，再 ai-prepare 和 resume")
    model_id = args.model or _settings().model_name
    identity = prepare_ai_review(
        store,
        model_id=model_id,
        pass2_model_id=args.pass2_model,
        adjudicator_model_id=args.adjudicator_model,
        temperature=args.temperature,
        stage="formal" if formal else "calibration",
    )
    print(f"AI 评分身份：{identity['identity_sha256']}（同模型 ID：{identity['same_model_id']}）")
    return 0


async def _cmd_ai_execute(args: argparse.Namespace) -> int:
    """显式发起评分网络请求前，先复核已有证据的完整性。"""
    from . import ai_runner

    store = RunStore(root=args.run)
    report = verify_run(store)
    if not report.ok:
        for item in report.violations:
            print(f"× {item}", file=sys.stderr)
        return 1
    kwargs: dict[str, Any] = {
        "blind_ids": _split_ids(args.blind_ids),
        "max_concurrency": args.max_concurrency,
    }
    if args.command == "ai-score":
        result = await ai_runner.score_run(store, _settings(), passes=tuple(args.passes), **kwargs)
    else:
        result = await ai_runner.adjudicate_run(store, _settings(), **kwargs)
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 1 if result.invalid or result.error else 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    """执行 summarize。"""
    store = RunStore(root=args.run)
    summary = summarize_run(store)
    denominators = summary["denominators"]
    print(
        f"分母：{denominators['case_groups_expected']} 个 case-group，"
        f"有末轮结论 {denominators['case_groups_with_final_turn']} 个"
    )
    if summary["human_scores"] is None:
        print("未导入人工评分：human_scores 为空")
    else:
        print(f"已按人工评分汇总（模式 {summary['human_scores']['mode']}）")
    print(f"独立 AI 评审：{summary['ai_review_status']}（不写入 human_scores）")
    print(f"报告：{store.root / 'summary.md'}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """执行 verify。"""
    store = RunStore(root=args.run)
    report = verify_run(store, require_complete=args.require_complete)
    for item in report.violations:
        print(f"× {item}")
    for item in report.warnings:
        print(f"! {item}")
    print("证据包校验通过" if report.ok else f"证据包校验未通过（{len(report.violations)} 项）")
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    """命令入口；返回退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "preflight": _cmd_preflight,
        "identity": _cmd_identity,
        "freeze": _cmd_freeze,
        "review-export": _cmd_review_export,
        "review-import": _cmd_review_import,
        "ai-prepare": _cmd_ai_prepare,
        "summarize": _cmd_summarize,
        "verify": _cmd_verify,
    }
    try:
        if args.command == "run":
            return asyncio.run(_cmd_run_async(args))
        if args.command == "resume":
            return asyncio.run(_cmd_resume_async(args))
        if args.command in {"ai-score", "ai-adjudicate"}:
            return asyncio.run(_cmd_ai_execute(args))
        return handlers[args.command](args)
    except (CaseValidationError, FreezeError, ReviewError, KnowledgeSnapshotError, ResumeRejected, ValueError) as exc:
        print(f"× {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


__all__ = ["build_parser", "main"]
