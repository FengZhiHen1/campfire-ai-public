"""自然表达评测独立命令；历史命令与结果保持原有入口。"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from campfire.agent.model import ModelGateway
from campfire.core.config import Settings
from campfire.core.db import session_scope

from ..config import RunConfig
from ..knowledge import load_snapshot_manifest, read_database_state, require_isolated_database
from ..manifest import code_facts, runtime_identity
from .adapters import build_interactive_adapters
from .freeze import PACKAGE, load_run, prepare
from .models import Budget
from .runner import run_episode, seal_interrupted
from .scoring import score_episode
from .storage import records, write_json
from .transport import attach_http_journal, completion

REPO = PACKAGE.parents[2]


def isolated_settings() -> Settings:
    settings = Settings()
    require_isolated_database(settings.database_url, prefix="campfire_carebench_interactive_")
    for value in (settings.database_url, settings.redis_url):
        if urlsplit(value).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("本轮只授权本地隔离服务")
    if (
        urlsplit(settings.redis_url).path != "/14"
        or settings.falkordb_host not in {"127.0.0.1", "localhost", "::1"}
        or not settings.falkordb_database.startswith("carebench_interactive_")
    ):
        raise ValueError("需要独立 Redis DB14 与 carebench_interactive_* 图命名空间")
    return settings


def adapter_config() -> RunConfig:
    return RunConfig(
        label="test",
        max_outer_retries=0,
        turn_timeout_seconds=150,
        turn_policy="interactive_frozen_disclosure",
    )


async def identity(settings: Settings) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot, _ = load_snapshot_manifest()
    async with session_scope(settings) as session:
        snapshot = await read_database_state(
            session,
            snapshot=snapshot,
            database=require_isolated_database(settings.database_url),
        )
    if not snapshot.ok or not snapshot.items or snapshot.node_count < 1:
        raise ValueError("知识快照不完整或为空")
    return runtime_identity(settings, snapshot, adapter_config()), snapshot.to_dict()


@asynccontextmanager
async def runtime(settings: Settings):
    gateway = ModelGateway(settings)
    bundle = build_interactive_adapters(settings=settings, config=adapter_config(), gateway=gateway)
    try:
        metas = {sid: (await adapter.prepare()).to_dict() for sid, adapter in bundle.adapters.items()}
        yield gateway, bundle, metas
    finally:
        await bundle.aclose()
        await gateway.aclose()


def require_code(manifest: dict[str, Any]) -> None:
    actual = code_facts(REPO)
    if actual["dirty"] or actual["commit"] != manifest["code"]["commit"]:
        raise ValueError("运行/评分必须使用冻结的干净代码提交")


async def dispatch(args: argparse.Namespace) -> int:
    if args.command == "prepare":
        settings = isolated_settings()
        current_identity, snapshot = await identity(settings)
        common = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                cwd=REPO,
                text=True,
            ).strip()
        ).parent
        if Path(args.run_id).name != args.run_id or not args.run_id.strip():
            raise ValueError("run-id 必须是目录名")
        root = common / "deliverables/2026-ai-opensource" / args.run_id
        async with runtime(settings) as (_, _, metas):
            manifest = prepare(
                root=root,
                repo=REPO,
                cases=PACKAGE / "cases" / f"{args.split}-v0.2.jsonl",
                budget=Budget(repetitions=1 if args.split == "calibration" else 3),
                identity=current_identity,
                snapshot=snapshot,
                metas=metas,
                concurrency=args.concurrency,
            )
        print(json.dumps({"root": str(root), "planned": len(manifest["plan"])}, ensure_ascii=False))
        return 0
    root = args.root.resolve()
    manifest, scenarios, budget = load_run(root)
    by_case = {case.id: case for case in scenarios}
    if args.command in {"run", "score"}:
        require_code(manifest)
        if args.dry_run:
            print(json.dumps(manifest["plan"], ensure_ascii=False, indent=2))
            return 0
        settings = isolated_settings()
        current_identity, snapshot = await identity(settings)
        if current_identity != manifest["identity"] or snapshot != manifest["knowledge"]:
            raise ValueError("实际模型/端点/知识与冻结件不同")
        # 同批次只允许一个写进程；评分也使用此锁，避免重复请求与超额补采。
        with (root / ".writer.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            async with runtime(settings) as (gateway, bundle, metas):
                if metas != manifest["systems"]:
                    raise ValueError("装配事实与冻结件不同")
                attach_http_journal(gateway, root)
                seal_interrupted(root)
                episodes = records(root / "episodes.jsonl")
                done = {episode["episode_id"] for episode in episodes}
                semaphore = asyncio.Semaphore(manifest["concurrency"])

                async def run_one(item: dict[str, Any]) -> None:
                    async with semaphore:
                        if args.command == "run":
                            result = await run_episode(
                                root=root,
                                scenario=by_case[item["case_id"]],
                                system_id=item["system_id"],
                                repetition=item["repetition"],
                                adapter=bundle.adapters[item["system_id"]],
                                complete=completion(
                                    gateway,
                                    root,
                                    context={"purpose": "policy", "episode_id": item["episode_id"]},
                                ),
                                budget=budget,
                            )
                            print(
                                f"{result['episode_id']} {result['terminal_status']} {len(result['turns'])}", flush=True
                            )
                        else:
                            await score_episode(root, item, by_case[item["case_id"]], budget, gateway)
                            print(f"{item['episode_id']} reviewed", flush=True)

                if args.command == "run":
                    jobs = [item for item in manifest["plan"] if item["episode_id"] not in done]
                else:
                    if done != {item["episode_id"] for item in manifest["plan"]}:
                        raise ValueError("必须先完成全部终局记录，再开始评分")
                    ratings = records(root / "ratings.jsonl")
                    reviewed = {row["episode_id"] for row in ratings}
                    jobs = [item for item in episodes if item["episode_id"] not in reviewed]
                await asyncio.gather(*(run_one(item) for item in jobs))
        return 0
    if args.command == "summarize":
        from .summarize import summarize

        result = summarize(root)
        write_json(root / "summary.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify":
        from .verify import verify

        result = verify(root, require_complete=args.require_complete)
        write_json(root / "verification.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    raise ValueError("未知命令")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--split", choices=("calibration", "test"), required=True)
    prepare_parser.add_argument("--run-id", required=True)
    prepare_parser.add_argument("--concurrency", type=int, default=3)
    for command in ("run", "score", "summarize", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--root", type=Path, required=True)
        if command in {"run", "score"}:
            sub.add_argument("--dry-run", action="store_true")
        if command == "verify":
            sub.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except Exception as exc:  # noqa: BLE001
        # 不输出可能含连接串的原始异常；只给无凭据的类型。
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1
