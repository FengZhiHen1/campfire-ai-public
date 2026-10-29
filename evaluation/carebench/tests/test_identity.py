"""运行身份：模型/端点/嵌入/知识必须绑进批次，换了就不能续跑。

批次指纹只绑案例/配置/代码——换 `MODEL_NAME` 后指纹不变，续跑会把两个模型的输出混进
同一批，而这种混批从数据上几乎看不出来。这组用例就钉住这条护栏。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from campfire.core.config import Settings
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.manifest import identity_drift, identity_fingerprint, runtime_identity
from evaluation.carebench.runner import ResumeRejected, execute
from evaluation.carebench.store import create_run_dir

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot

pytestmark = pytest.mark.asyncio


def _other_snapshot():
    """换一份内容不同的知识快照（文件 hash 不同 → 快照 hash 不同）。"""
    from dataclasses import replace

    base = make_snapshot()
    return replace(base, files=(replace(base.files[0], sha256="1" * 64),))


def _settings(model: str, base_url: str = "http://127.0.0.1:7863/v1") -> Settings:
    """只改模型/端点，其余用测试默认（不连库、不连网络）。"""
    return Settings(
        database_url="postgresql+asyncpg://tester:secret@127.0.0.1:5432/campfire_carebench_test",
        model_name=model,
        tokenhub_base_url=base_url,
    )


def test_identity_carries_no_credentials() -> None:
    """身份段只写端点结构与「是否配了凭据」，不写任何 key/连接串。"""
    identity = runtime_identity(_settings("model-a"), make_snapshot(), RunConfig())
    text = str(identity)
    assert "secret" not in text.lower()
    assert identity["model_id"] == "model-a"
    # `endpoint_host` 的口径是「主机[:端口]」，端口另有独立字段（便于分别核对）
    assert identity["chat"]["host"].startswith("127.0.0.1")
    assert identity["chat"]["port"] == 7863
    assert identity["chat"]["base_path"] == "/v1"
    assert identity["embedding"]["dimension"] == 2560
    assert identity["knowledge"]["snapshot_sha256"] == make_snapshot().sha256
    assert identity["conversation"]["reset_each_case"] is True


def test_identity_drift_names_the_field() -> None:
    """不一致的字段必须被点名（报告里能直接看出换的是模型还是端点）。"""
    before = runtime_identity(_settings("model-a"), make_snapshot(), RunConfig())
    after = runtime_identity(_settings("model-b"), make_snapshot(), RunConfig())
    diffs = identity_drift(before, after)
    assert any("model_id" in item for item in diffs)
    assert identity_fingerprint(before) != identity_fingerprint(after)


async def test_resume_rejects_changed_model(tmp_path: Path, faults_for_tests: FaultPlan) -> None:
    """换模型后续跑同一批次必须被拒（否则一批里混两个模型）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    store = create_run_dir(tmp_path / "runs", "carebench-identity")

    def factory() -> dict[str, Any]:
        return {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}

    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=_settings("model-a"),
        adapters=factory(),
        log=lambda _message: None,
    )
    with pytest.raises(ResumeRejected, match="运行身份"):
        await execute(
            store=store,
            config=RunConfig(label="calibration"),
            case_set=case_set,
            snapshot=make_snapshot(),
            faults=faults_for_tests,
            settings=_settings("model-b"),
            adapters=factory(),
            resume=True,
            log=lambda _message: None,
        )


async def test_resume_rejects_changed_knowledge_snapshot(tmp_path: Path, faults_for_tests: FaultPlan) -> None:
    """换知识快照后续跑同样要拒（B/C 的「同一份知识」是公平性前提）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    store = create_run_dir(tmp_path / "runs", "carebench-identity-snapshot")
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=_settings("model-a"),
        adapters={system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")},
        log=lambda _message: None,
    )
    with pytest.raises(ResumeRejected, match="knowledge"):
        await execute(
            store=store,
            config=RunConfig(label="calibration"),
            case_set=case_set,
            snapshot=_other_snapshot(),
            faults=faults_for_tests,
            settings=_settings("model-a"),
            adapters={system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")},
            resume=True,
            log=lambda _message: None,
        )


def test_shared_session_config_is_rejected() -> None:
    """`conversation_reset_each_case=False` 没有代码路径：直接拒，不静默按 True 跑。"""
    with pytest.raises(ValueError, match="conversation_reset_each_case"):
        RunConfig(conversation_reset_each_case=False)


def _git_repo(tmp_path: Path) -> Path:
    """造一个一次性 git 仓库（用于核对 dirty 判定，不碰当前 worktree）。"""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True, capture_output=True)  # noqa: S603
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, capture_output=True)  # noqa: S603
    return repo


def test_code_facts_counts_untracked_code(tmp_path: Path) -> None:
    """未跟踪的代码文件必须算脏（否则「可复现」绑的是一个不含这些代码的 commit）。"""
    from evaluation.carebench.manifest import code_facts

    repo = _git_repo(tmp_path)
    assert code_facts(repo)["dirty"] is False

    (repo / "new_module.py").write_text("y = 2\n", encoding="utf-8")
    facts = code_facts(repo)
    assert facts["dirty"] is True
    assert facts["dirty_untracked_count"] == 1
    assert "new_module.py" in facts["dirty_files"]

    # 被忽略的产物不算脏：跑一批不该把仓库标脏
    (repo / "new_module.py").unlink()
    import subprocess as _sp

    (repo / ".gitignore").write_text("runs/\n", encoding="utf-8")
    _sp.run(["git", "add", ".gitignore"], cwd=repo, check=True, capture_output=True)  # noqa: S603
    _sp.run(["git", "commit", "-qm", "ignore"], cwd=repo, check=True, capture_output=True)  # noqa: S603
    (repo / "runs").mkdir()
    (repo / "runs" / "outputs.jsonl").write_text("{}\n", encoding="utf-8")
    assert code_facts(repo)["dirty"] is False


def test_formal_label_refuses_dirty_tree(tmp_path: Path) -> None:
    """正式批次（label=test）在脏工作区必须拒绝，校准批次允许（但会如实记 dirty）。"""
    from evaluation.carebench.runner import _require_clean_code_for_formal

    repo = _git_repo(tmp_path)
    _require_clean_code_for_formal(config=RunConfig(), repo_root=repo)  # label=pilot：放行
    _require_clean_code_for_formal(config=RunConfig(label="calibration"), repo_root=repo)

    (repo / "new_module.py").write_text("y = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="干净工作区"):
        _require_clean_code_for_formal(config=RunConfig(label="test"), repo_root=repo)
