"""批次 manifest：一次运行的全部可复现条件（协议 04 第 2 节要求的最小证据包）。

职责：把配置、案例集、知识快照、代码提交、组别装配、运行环境与评审状态汇成一份
`manifest.json`，并给出进度快照（派生）与 errors 清单（派生）。

边界：**不写任何凭据**。密钥、连接串、口令一栏都不出现；数据库只写库名，端点只写主机名，
凭据只写「是否已配置」这个布尔。

为什么把「哪些组别用什么装配」「提示词 hash」「SDK 重试归属」都塞进来：协议 01 第 4 节
把「基准配置必须记录」的清单列成七项，缺任何一项，别人就无法判断 A/B/C 的差异是不是
来自配置差异。这份文件就是那张清单的落地形态。
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cases import CaseSet
from .config import RunConfig
from .faults import FaultPlan
from .hashing import batch_fingerprint, sha256_file, sha256_value
from .knowledge import EMBEDDING_DIM, PACKAGE_ROOT, KnowledgeSnapshot, database_name, endpoint_host, is_loopback
from .records import GroupProgress, progress_summary

#: 协议快照目录（评测目录内的只读副本）。
PROTOCOL_DIR = PACKAGE_ROOT / "protocol"

#: manifest 结构版本。改形状时递增（verify 会核对它）。
MANIFEST_VERSION = "1"


def utc_now() -> str:
    """当前 UTC 时间（ISO 8601，秒精度）。"""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def code_facts(repo_root: Path) -> dict[str, Any]:
    """代码提交事实：commit、分支、是否有未提交改动（**含未跟踪的代码文件**）。

    为什么必须含未跟踪文件：实测踩过——`evaluation/` 整个目录还没 `git add` 时，
    `git status --porcelain --untracked-files=no` 什么都不显示，于是批次被标成
    `dirty=false` 并绑定了一个根本不含这些代码的 commit。那种「可复现」是假的：
    按那个 commit 检出来跑，跑的不是当时跑的东西。

    产物目录（`runs/`、`frozen/`、`.tmp/` 等）由 `.gitignore` 排除，因此这里的
    「未跟踪」只包含真正的代码/文本改动，不会因为跑了一批就把仓库算脏。
    """

    def _run(*args: str) -> str:
        try:
            return subprocess.run(  # noqa: S603 —— 固定命令、无外部输入
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    commit = _run("rev-parse", "HEAD") or "unknown"
    branch = _run("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    status = _run("status", "--porcelain", "--untracked-files=normal")
    tracked_dirty = [line[3:] for line in status.splitlines() if line.strip() and not line.startswith("??")]
    untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    return {
        "commit": commit,
        "branch": branch,
        "dirty": bool(status),
        "dirty_tracked_count": len(tracked_dirty),
        "dirty_untracked_count": len(untracked),
        "dirty_files": sorted({*tracked_dirty, *untracked})[:50],
        "dirty_scope": "tracked + untracked（未跟踪同样算脏：没有提交就没有可复现的提交；产物目录由 .gitignore 排除）",
    }


def environment_facts(repo_root: Path) -> dict[str, Any]:
    """运行环境事实（含 lock 文件 hash：依赖漂移会让分块与嵌入结果变化）。"""
    lock = repo_root / "uv.lock"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "uv_lock_sha256": sha256_file(lock) if lock.exists() else None,
        "operator": os.environ.get("CAREBENCH_OPERATOR") or os.environ.get("USER") or "unknown",
        "timezone": os.environ.get("TZ") or "unknown",
    }


def protocol_snapshot_facts() -> dict[str, Any]:
    """协议快照事实：逐文件 hash + 汇总 hash。

    `inbox` 是只读来源；这里记录仓库内副本的 hash，报告即可以它为准说明
    「这份报告对应哪一版协议」。
    """
    files: list[dict[str, str]] = []
    digest_input: list[tuple[str, str]] = []
    for path in sorted(PROTOCOL_DIR.glob("*.md")):
        digest = sha256_file(path)
        files.append({"name": path.name, "sha256": digest})
        digest_input.append((path.name, digest))
    return {
        "files": files,
        "sha256": sha256_value([{"name": name, "sha256": digest} for name, digest in digest_input]),
    }


def runtime_identity(settings: Any, snapshot: KnowledgeSnapshot, config: RunConfig) -> dict[str, Any]:
    """运行身份：决定「跑的是哪个模型、哪个端点、哪份知识」的全部事实（**无凭据**）。

    为什么必须进 manifest 并在 resume 时逐项核对：批次指纹原本只绑案例/配置/代码，
    换掉 `TOKENHUB_BASE_URL` 或 `MODEL_NAME` 再 resume，工具会照常接受，于是一批里混进
    两个模型——这种混批从数据上几乎看不出来，只能靠身份核对拦住。

    凭据一个字节都不进来：只记「是否已配置」与端点主机/端口/路径，不记 key、不记 query。
    """
    chat_host = endpoint_host(settings.tokenhub_base_url)
    embedding_host = endpoint_host(settings.resolved_embedding_base_url)
    return {
        "model_id": str(settings.model_name),
        "chat": {
            "host": chat_host,
            "port": _port_of(settings.tokenhub_base_url),
            "base_path": _base_path_of(settings.tokenhub_base_url),
            "model_max_retries": int(settings.model_max_retries),
            "request_timeout_seconds": float(settings.model_request_timeout_seconds),
            "api_key_configured": settings.tokenhub_api_key is not None,
        },
        "embedding": {
            "host": embedding_host,
            "port": _port_of(settings.resolved_embedding_base_url),
            "base_path": _base_path_of(settings.resolved_embedding_base_url),
            "model": str(settings.embedding_model_name),
            "dimension": int(EMBEDDING_DIM),
            "api_key_configured": settings.resolved_embedding_api_key is not None,
        },
        "knowledge": {
            "database": database_name(getattr(settings, "database_url", "")),
            "snapshot_sha256": snapshot.sha256,
            "items": len(snapshot.items),
            "nodes": int(sum(item.nodes for item in snapshot.items)),
        },
        "conversation": {
            "reset_each_case": bool(config.conversation_reset_each_case),
            "turn_policy": str(config.turn_policy),
        },
    }


def _port_of(url: str) -> int | None:
    """端点的端口（没有显式端口时按协议给默认值）。"""
    from urllib.parse import urlparse

    parsed = urlparse((url or "").strip())
    if parsed.port is not None:
        return int(parsed.port)
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def _base_path_of(url: str) -> str:
    """端点的路径前缀（去掉末尾斜杠；不含 query）。"""
    from urllib.parse import urlparse

    return urlparse((url or "").strip()).path.rstrip("/")


def identity_fingerprint(identity: dict[str, Any]) -> str:
    """运行身份的指纹（进 batch id 与 resume 核对）。"""
    return sha256_value(identity)


def identity_drift(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """逐项比较两份运行身份，返回不一致的项（空列表 = 一致）。"""
    diffs: list[str] = []
    for section, value in expected.items():
        other = actual.get(section)
        if isinstance(value, dict):
            if not isinstance(other, dict):
                diffs.append(f"{section}：manifest 有记录、当前环境没有")
                continue
            for key, sub_value in value.items():
                if other.get(key) != sub_value:
                    diffs.append(f"{section}.{key}：manifest={sub_value!r} 当前={other.get(key)!r}")
        elif other != value:
            diffs.append(f"{section}：manifest={value!r} 当前={other!r}")
    return diffs


def inference_facts(settings: Any, config: RunConfig, system_metas: dict[str, Any]) -> dict[str, Any]:
    """推理与重试事实。

    两类重试分开写，不合并成一个 `max_retries`：A/B 是一次 HTTP 调用（客户端 `max_retries=0`，
    重试只来自评测工具的外层策略），C 是 SDK 的 runner-managed retry（来自 `Settings`）。
    写成同一个数字会让读者以为三组有同一套重试。
    """
    chat_host = endpoint_host(settings.tokenhub_base_url)
    embedding_host = endpoint_host(settings.resolved_embedding_base_url)
    return {
        "model_id": settings.model_name,
        "chat_endpoint_host": chat_host,
        "embedding_endpoint_host": embedding_host,
        "embedding_separated_from_chat": embedding_host != chat_host,
        "embedding_shared_endpoint_is_loopback": embedding_host == chat_host and is_loopback(chat_host),
        "temperature": config.temperature,
        "top_p": config.top_p,
        "max_output_tokens": config.max_output_tokens,
        "seed": config.seed,
        "parameters_note": "三项为 null 表示不显式传参、使用供应商默认值（协议要求记录该事实，不替供应商编造数值）",
        "credentials": {
            "chat_api_key_configured": settings.tokenhub_api_key is not None,
            "embedding_api_key_configured": settings.resolved_embedding_api_key is not None,
        },
        "retry": {
            "outer": {
                "owner": "carebench runner",
                "max_outer_retries": config.max_outer_retries,
                "retry_on": list(config.retry_on),
                "first_error_retained": True,
            },
            "chat_client": {"owner": "A/B 单次调用", "client_max_retries": 0},
            "sdk_runner": {
                "owner": "C 组 agents-sdk runner-managed retry",
                "model_max_retries": settings.model_max_retries,
                "model_request_timeout_seconds": settings.model_request_timeout_seconds,
                "retry_backoff_seconds": [
                    settings.model_retry_initial_delay_seconds,
                    settings.model_retry_max_delay_seconds,
                ],
            },
            "systems_using_sdk_retry": [sid for sid in system_metas if sid == "C"],
        },
    }


def build_manifest(
    *,
    run_id: str,
    config: RunConfig,
    case_set: CaseSet,
    snapshot: KnowledgeSnapshot,
    system_metas: dict[str, Any],
    faults: FaultPlan,
    settings: Any,
    repo_root: Path,
    created_at: str,
    status: str,
    progress: list[GroupProgress],
    run_identity: dict[str, Any],
    run_identity_sha256: str,
    frozen_identity_sha256: str | None = None,
    identity_locked: bool = False,
    frozen_config_sha256: str | None = None,
    config_drift_allowed: bool = False,
) -> dict[str, Any]:
    """组装 manifest（首次运行与续跑都会重写它：进度与状态会变，身份不变）。

    `run_identity` 是「跑的是哪个模型、哪个端点、哪份知识」的**无凭据**快照；
    它与 `run_identity_sha256` 一起写进 manifest，`resume` 逐项核对（见
    `runner._require_same_identity`）——批次指纹只绑案例/配置/代码，绑不住模型与端点。

    `freeze_binding` 回答另一个问题：**运行身份是不是冻结时就锁定过的那一版**。
    批次开始前锁定的身份（`freeze --identity`）与当前身份必须相等，否则 formal 批次
    就会变成「按计划冻结、按别的模型跑」。配置漂移（`--allow-config-drift`）同样记在
    这里，不被静默吞掉。
    """
    code = code_facts(repo_root)
    fingerprint = batch_fingerprint(
        dataset_sha256=case_set.sha256,
        config_sha256=config.sha256,
        code_commit=str(code["commit"]),
    )
    return {
        "manifest_version": MANIFEST_VERSION,
        "run_identity": run_identity,
        "run_identity_sha256": run_identity_sha256,
        "freeze_binding": {
            "identity_locked": identity_locked,
            "frozen_identity_sha256": frozen_identity_sha256,
            "frozen_config_sha256": frozen_config_sha256,
            "config_drift": bool(frozen_config_sha256) and frozen_config_sha256 != config.sha256,
            "config_drift_allowed": config_drift_allowed,
            "note": (
                "identity_locked=true 表示冻结时已锁定模型/端点/嵌入/知识快照；"
                "config_drift=true 表示实际配置与冻结声明不同，报告不得把它当作同一条件"
            ),
        },
        "run_id": run_id,
        "status": status,
        "created_at": created_at,
        "updated_at": utc_now(),
        "batch_id": fingerprint,
        "label": config.label,
        "dataset": {
            "path": str(case_set.path),
            "sha256": case_set.sha256,
            "case_count": len(case_set.cases),
            "case_ids": list(case_set.ids),
            "split": case_set.split,
            "review_status_counts": case_set.review_status_counts,
            "per_case_sha256": {case.id: case.sha256 for case in case_set.cases},
            "turns_per_case": {case.id: case.turns for case in case_set.cases},
            "formal_ready": all(case.approved for case in case_set.cases),
            "note": (
                "formal_ready=false 表示存在尚未 approved 的案例：结果只能作为原始观察，"
                "不得写成「已审核通过」或专家背书（协议 03 第 5 节、05 第 5 节）"
            ),
        },
        "config": config.to_dict(),
        "config_sha256": config.sha256,
        "code": code,
        "environment": environment_facts(repo_root),
        "protocol_snapshot": protocol_snapshot_facts(),
        "knowledge_snapshot": {
            **snapshot.to_dict(),
            "sha256": snapshot.sha256,
            "ok": snapshot.ok,
            "database": snapshot.database or database_name(settings.database_url),
        },
        "systems": [system_metas[system_id].to_dict() for system_id in config.systems],
        "inference": inference_facts(settings, config, system_metas),
        "runner": {
            "turn_policy": config.turn_policy,
            "rotation": list(config.rotation),
            "conversation_reset_each_case": config.conversation_reset_each_case,
            "turn_timeout_seconds": config.turn_timeout_seconds,
            "systems_per_case": list(config.systems),
            "transport": "in-process（A/B 单次调用；C 为产品 AgentRunner.run()，非 HTTP/SSE）",
        },
        "fault_injection": faults.summary(tuple(config.systems)),
        "review": {
            "state": "pending",
            "rubric_version": config.rubric_version,
            "raters_planned": config.raters_per_case,
            "review_seed": config.review_seed,
            "packet_exported": False,
            "ratings_imported": False,
            "human_scores_available": False,
            "note": "人工评分只能由 review-import 导入的 CSV 产生；pending 不算通过",
        },
        "progress": progress_summary(progress),
        "limitations": _limitations(config, case_set, snapshot),
        "secrets": "本文件不含任何凭据：只记录库名、端点主机名与「凭据是否已配置」",
    }


def _limitations(config: RunConfig, case_set: CaseSet, snapshot: KnowledgeSnapshot) -> list[str]:
    """已知限制（写进证据包，避免报告里漏掉环境前提）。"""
    items = [
        "本工具测的是程序内运行链，不是浏览器端到端体验；HTTP/SSE 契约由产品自身的 e2e 用例覆盖。",
        "A/B 的推理参数未显式传参（temperature/top_p 为 null），因此比较的是「同一模型默认采样」下的差异。",
        "自动层面不判定「明确拒答」：completion_status 的四种取值只描述工程事实，拒答合理性由评审在 ratings.csv 判定。",
        "知识快照仅含许可清单内语料，样例规模小，检索召回不代表真实知识库表现。",
        "提示词 hash 与配置 hash 只证明「同一次批次内部一致」，不证明提示词内容本身是恰当的领域规则。",
    ]
    if not all(case.approved for case in case_set.cases):
        items.append(
            "案例 review_status 未全部 approved：任何专业结论都必须标为待复核（needs_review），不得写成已审核。"
        )
    if not snapshot.ok:
        items.append("知识库隔离核对未通过：见 knowledge_snapshot.violations。")
    if config.max_outer_retries:
        items.append(
            f"外层重试策略：最多 {config.max_outer_retries} 次，仅对 {list(config.retry_on)} 生效，且保留首错记录。"
        )
    return items


__all__ = [
    "MANIFEST_VERSION",
    "PROTOCOL_DIR",
    "build_manifest",
    "code_facts",
    "environment_facts",
    "protocol_snapshot_facts",
    "utc_now",
]
