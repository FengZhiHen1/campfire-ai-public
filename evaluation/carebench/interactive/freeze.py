"""生成前冻结输入、评分规则、运行身份和完整分母。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_value
from ..manifest import code_facts, environment_facts, utc_now
from .models import SYSTEMS, VERSION, Budget, Scenario, load_scenarios
from .review import (
    ADJUDICATOR_PROMPT,
    ADJUDICATOR_PROMPT_VERSION,
    REVIEW_SCHEMA_VERSION,
    SCORER_PROMPT_VERSIONS,
    SCORER_PROMPTS,
)
from .storage import immutable_json, read_immutable
from .transport import JUDGE_PARAMETERS, REQUEST_WRAPPER_VERSION, SYSTEM_TRANSPORT_VERSION
from .user_policy import POLICY_PROMPT, POLICY_VERSION

PACKAGE = Path(__file__).resolve().parent


def episode_plan(scenarios: tuple[Scenario, ...], budget: Budget) -> list[dict[str, Any]]:
    plan = []
    for repetition in range(1, budget.repetitions + 1):
        for index, scenario in enumerate(scenarios):
            shift = (index + repetition - 1) % len(SYSTEMS)
            for system in (*SYSTEMS[shift:], *SYSTEMS[:shift]):
                plan.append(
                    {
                        "episode_id": f"{scenario.id}__{system}__r{repetition}",
                        "case_id": scenario.id,
                        "system_id": system,
                        "repetition": repetition,
                    }
                )
    return plan


def prompts() -> dict[str, Any]:
    from campfire.surfaces.consult.assembly import CONSULT_INSTRUCTIONS

    from .adapters import GROUP_PROMPTS

    return {
        "systems": {**GROUP_PROMPTS, "C": CONSULT_INSTRUCTIONS},
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "scorer_versions": list(SCORER_PROMPT_VERSIONS),
        "adjudicator_version": ADJUDICATOR_PROMPT_VERSION,
        "policy": POLICY_PROMPT,
        "policy_version": POLICY_VERSION,
        "scorers": list(SCORER_PROMPTS),
        "adjudicator": ADJUDICATOR_PROMPT,
        "parameters": JUDGE_PARAMETERS,
        "request_wrapper_version": REQUEST_WRAPPER_VERSION,
        "system_transport_version": SYSTEM_TRANSPORT_VERSION,
    }


def prepare(
    *,
    root: Path,
    repo: Path,
    cases: Path,
    budget: Budget,
    identity: dict[str, Any],
    snapshot: dict[str, Any],
    metas: dict[str, Any],
    concurrency: int,
) -> dict[str, Any]:
    scenarios = load_scenarios(cases)
    split = scenarios[0].split
    expected = 8 if split == "calibration" else 24
    repetitions = 1 if split == "calibration" else 3
    if len(scenarios) != expected or budget.repetitions != repetitions:
        raise ValueError(f"{split} 必须是 {expected} 案例、每组 {repetitions} 次重复")
    if not 1 <= concurrency <= 6:
        raise ValueError("并发必须在 1–6 之间")
    code = code_facts(repo)
    if code["dirty"] or code["commit"] == "unknown":
        raise ValueError("冻结需要干净且已提交的代码")
    if set(metas) != set(SYSTEMS) or any(meta["model_id"] != identity["model_id"] for meta in metas.values()):
        raise ValueError("三组装配或模型身份不一致")
    root.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, content in {
        "cases.frozen.jsonl": cases.read_bytes(),
        "protocol.frozen.md": (PACKAGE / "PROTOCOL.md").read_bytes(),
    }.items():
        (root / name).write_bytes(content)
        files[name] = sha256_file(root / name)
    immutable_json(root / "prompts.frozen.json", prompts())
    files["prompts.frozen.json"] = sha256_file(root / "prompts.frozen.json")
    manifest = {
        "version": VERSION,
        "run_id": root.name,
        "split": split,
        "created_at": utc_now(),
        "code": code,
        "environment": environment_facts(repo),
        "budget": budget.to_dict(),
        "concurrency": concurrency,
        "systems": metas,
        "identity": identity,
        "knowledge": snapshot,
        "files": files,
        "prompts_sha256": sha256_value(prompts()),
        "plan": episode_plan(scenarios, budget),
        "inference": {
            "system_transport_version": SYSTEM_TRANSPORT_VERSION,
            "system_transport_note": (
                "本地路由不遵从 system-only 探针；统一在首个用户消息前重述已有系统指令。"
                "三组同转换，原始家长文本与实际发送消息分别保留；不等同于未加兼容层的线上端点。"
            ),
            "system_sampling": "provider_defaults",
            "outer_retries": 0,
            "judge_parameters": JUDGE_PARAMETERS,
            "judge_model": identity["model_id"],
            "independent_raters": "independent requests and prompts; same configured model",
            "http_observation": "chat requests and response headers; streaming bodies retained in turn traces",
            "not_observed": "embedding HTTP attempts and provider-internal behavior",
        },
    }
    immutable_json(root / "manifest.json", manifest)
    return read_immutable(root / "manifest.json")


def load_run(root: Path) -> tuple[dict[str, Any], tuple[Scenario, ...], Budget]:
    manifest = read_immutable(root / "manifest.json")
    if manifest["version"] != VERSION:
        raise ValueError("运行版本不受支持")
    for name, digest in manifest["files"].items():
        if Path(name).name != name or sha256_file(root / name) != digest:
            raise ValueError("冻结文件 hash 不一致")
    if sha256_value(prompts()) != manifest["prompts_sha256"]:
        raise ValueError("当前评分/模拟家长提示与冻结件不同")
    scenarios = load_scenarios(root / "cases.frozen.jsonl")
    budget = Budget(**manifest["budget"])
    split = scenarios[0].split
    if (
        manifest["split"] != split
        or len(scenarios) != (8 if split == "calibration" else 24)
        or budget.repetitions != (1 if split == "calibration" else 3)
    ):
        raise ValueError("冻结案例数量、split 或重复预算不符合协议")
    if manifest["plan"] != episode_plan(scenarios, budget):
        raise ValueError("冻结分母或轮换被修改")
    return manifest, scenarios, budget
