"""冻结与命令行的测试：冻结身份不可悄悄改变，配置 hash 稳定，命令齐全。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.carebench.cli import build_parser
from evaluation.carebench.config import ROTATION, RunConfig, load_config
from evaluation.carebench.freeze import FreezeError, freeze_cases, load_frozen
from evaluation.carebench.hashing import batch_fingerprint

from .conftest import make_cases_file


def test_freeze_records_hashes_and_is_idempotent(tmp_path: Path) -> None:
    """冻结记录含案例/配置 hash 与逐案 hash；同一份内容重复冻结不制造分叉。"""
    cases = make_cases_file(tmp_path / "cases.jsonl", count=2)
    out = tmp_path / "frozen"
    config = RunConfig(label="calibration")
    frozen = freeze_cases(cases_path=cases, label="calibration", out_dir=out, config=config)

    record = frozen.record
    assert record["dataset_sha256"] == frozen.case_set.sha256
    assert record["config_sha256"] == config.sha256
    assert record["case_count"] == 2
    assert len(record["per_case_sha256"]) == 2
    assert record["review_status_counts"] == {"draft_unreviewed": 2}
    assert record["formal_ready"] is False  # 未 approved 就是 False，不粉饰
    assert (out / "cases.frozen.jsonl").read_bytes() == cases.read_bytes()

    again = freeze_cases(cases_path=cases, label="calibration", out_dir=out, config=config)
    assert again.record["dataset_sha256"] == record["dataset_sha256"]
    assert "refrozen_at" in again.record


def test_freeze_refuses_to_replace_different_cases(tmp_path: Path) -> None:
    """同一冻结目录换了案例就必须拒绝（看过输出后不得重冻同一批）。"""
    out = tmp_path / "frozen"
    freeze_cases(
        cases_path=make_cases_file(tmp_path / "a.jsonl", count=1),
        label="calibration",
        out_dir=out,
        config=RunConfig(label="calibration"),
    )
    with pytest.raises(FreezeError, match="已冻结过另一版案例"):
        freeze_cases(
            cases_path=make_cases_file(tmp_path / "b.jsonl", count=2),
            label="calibration",
            out_dir=out,
            config=RunConfig(label="calibration"),
        )


def test_load_frozen_detects_tampering(tmp_path: Path) -> None:
    """冻结物被改过，`load_frozen` 必须报错（而不是照常加载）。"""
    out = tmp_path / "frozen"
    freeze_cases(
        cases_path=make_cases_file(tmp_path / "cases.jsonl", count=1),
        label="calibration",
        out_dir=out,
        config=RunConfig(label="calibration"),
    )
    target = out / "cases.frozen.jsonl"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FreezeError, match="冻结物被改过"):
        load_frozen(out)


def test_config_hash_is_stable_and_sensitive() -> None:
    """配置 hash：同内容同 hash；改任意参与运行的字段都会变。"""
    base = RunConfig()
    assert base.sha256 == RunConfig().sha256
    assert base.sha256 != RunConfig(turn_timeout_seconds=301.0).sha256
    assert base.sha256 != RunConfig(label="test").sha256
    # 推理参数参与 hash（否则「同配置」可能藏着不同采样）
    assert base.sha256 != RunConfig(temperature=0.2).sha256


def test_config_round_trip_through_manifest() -> None:
    """`to_dict` → `from_dict` → 同一 hash（续跑靠它恢复配置）。"""
    config = RunConfig(label="test", raters_per_case=2, turn_timeout_seconds=120.0)
    restored = RunConfig.from_dict(config.to_dict())
    assert restored.sha256 == config.sha256


def test_config_rejects_unknown_key_and_bad_rotation(tmp_path: Path) -> None:
    """未知覆盖字段与不覆盖全组别的轮换都必须拒。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="未知字段"):
        load_config(path)

    path.write_text(json.dumps({"rotation": ["AB", "BC", "CA"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="没有覆盖全部组别"):
        load_config(path)


def test_rotation_is_derived_from_index() -> None:
    """轮换顺序由案例序号派生，不看命令行。"""
    config = RunConfig()
    assert config.order_for(0) == tuple(ROTATION[0])
    assert config.order_for(1) == tuple("BCA")
    assert config.order_for(2) == tuple("CAB")
    assert config.order_for(3) == tuple("ABC")


def test_batch_fingerprint_changes_with_any_input() -> None:
    """批次指纹：案例/配置/代码任一变化都必须改变指纹。"""
    base = batch_fingerprint(dataset_sha256="a" * 64, config_sha256="b" * 64, code_commit="c" * 40)
    assert base == batch_fingerprint(dataset_sha256="a" * 64, config_sha256="b" * 64, code_commit="c" * 40)
    assert base != batch_fingerprint(dataset_sha256="a" * 64, config_sha256="b" * 64, code_commit="d" * 40)


def test_cli_exposes_the_eight_commands() -> None:
    """命令行只保留必要功能：八个命令，别的不加。"""
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]  # noqa: SLF001 —— argparse 无公开取法
    choices = set(actions[0].choices)  # type: ignore[index]
    assert choices == {
        "preflight",
        "freeze",
        "run",
        "resume",
        "review-export",
        "review-import",
        "summarize",
        "verify",
    }
