"""评测工具自身的测试夹具：全部确定性替身，不联网、不连库。

为什么这样可以测「运行器」：适配器是唯一与外部世界接触的边界（模型、检索、产品运行时）。
把它换成脚本化替身之后，编排、落盘、续跑、评审、汇总、校验这几层全部是真的——
而它们正是本轮要交付的东西。真实模型调用另由少量校准运行验证（见 README「验证记录」）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from evaluation.carebench.cases import CaseSet, parse_cases
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.knowledge import KnowledgeSnapshot, SnapshotFile
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.systems.base import SystemMeta, TurnInput, TurnOutcome

#: 测试用的评测库连接串（不会真的连：`require_isolated_database` 只看库名）。
TEST_DATABASE_URL = "postgresql+asyncpg://tester:secret@127.0.0.1:5432/campfire_carebench_test"


def make_cases_file(
    path: Path,
    *,
    count: int = 2,
    followup: bool = False,
    category: str = "日常照护",
    review_status: str = "draft_unreviewed",
    fixtures: Sequence[str] = (),
) -> Path:
    """写一份测试用案例 JSONL（结构对齐协议 02 第 3 节）。"""
    lines: list[str] = []
    for index in range(1, count + 1):
        payload: dict[str, Any] = {
            "id": f"CFB-C-{index:03d}",
            "split": "calibration",
            "category": category,
            "risk_hint": "测试用",
            "user_message": f"第 {index} 个案例的问题",
            "shared_context": f"第 {index} 个案例的背景：只有一位成人，现场嘈杂",
            "followup": "孩子拒绝移动，怎么办？" if followup else None,
            "must_check": ["识别现场限制"],
            "must_not": ["要求监护人离开孩子"],
            "source_kind": "synthetic",
            "review_status": review_status,
        }
        if fixtures:
            payload["fixtures"] = list(fixtures)
        lines.append(json.dumps(payload, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load_cases(path: Path) -> CaseSet:
    """读取刚刚写出的案例文件。"""
    return parse_cases(path.read_bytes(), source=str(path), path=path)


def make_snapshot() -> KnowledgeSnapshot:
    """一个「许可清单齐备」的知识快照替身（不触库）。"""
    return KnowledgeSnapshot(
        snapshot_version="test",
        corpus_root="data/knowledge",
        files=(
            SnapshotFile(
                path="autism-corpus/nhc.md",
                sha256="0" * 64,
                license="测试许可",
                source_kind="institutional",
            ),
        ),
        items=(),
        case_item_count=0,
        database="campfire_carebench_test",
        violations=(),
    )


class FakeAdapter:
    """脚本化适配器：按 (case_id, turn, attempt) 给出预设结局，并记录调用。"""

    @staticmethod
    def default_model_id() -> str:
        """测试替身声明的模型 id：与测试配置的默认模型一致（verify 会核对三组同模型）。

        不让替身随便报一个名字：manifest 里「三组跑同一个模型」是证据的一部分，
        替身报 `fake-model` 会让这类核对在测试里永远失败，进而被顺手删掉。
        """
        from campfire.core.config import Settings

        return str(Settings(database_url=TEST_DATABASE_URL).model_name)

    def __init__(
        self,
        system_id: str,
        *,
        outcome: Callable[[TurnInput], TurnOutcome] | None = None,
        delay_seconds: float = 0.0,
        fail_prepare: bool = False,
        model_id: str | None = None,
    ) -> None:
        self.system_id = system_id
        self._outcome = outcome or (lambda request: TurnOutcome(status="completed", raw_output="脚本回复"))
        self._delay = delay_seconds
        self._fail_prepare = fail_prepare
        self._model_id = model_id or self.default_model_id()
        self.opened: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
        self.calls: list[TurnInput] = []

    async def prepare(self) -> SystemMeta:
        if self._fail_prepare:
            raise RuntimeError("装配失败")
        return SystemMeta(
            system_id=self.system_id,
            label=f"fake_{self.system_id}",
            assembly="测试替身",
            model_id=self._model_id,
            prompt_sha256="0" * 64,
            notes={},
        )

    async def open_case(
        self,
        *,
        case: Any,
        session_id: str,
        account_id: str,
        prior_turns: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.opened.append((case.id, session_id, prior_turns))

    async def run_turn(self, request: TurnInput) -> TurnOutcome:
        import asyncio

        self.calls.append(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._outcome(request)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def settings_for_tests() -> Any:
    """最小可用配置：只给数据库连接串（其余取默认值）。"""
    from campfire.core.config import Settings

    return Settings(database_url=TEST_DATABASE_URL)


@pytest.fixture
def config_for_tests() -> RunConfig:
    """测试用配置：三组、两轮策略默认、超时缩短以便测超时分支。"""
    return RunConfig(turn_timeout_seconds=5.0, label="calibration")


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    """一个空的批次目录。"""
    return create_run_dir(tmp_path / "runs", "carebench-test")


@pytest.fixture
def faults_for_tests() -> FaultPlan:
    """无注入的计划。"""
    return FaultPlan(requested={})
