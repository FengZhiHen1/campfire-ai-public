"""py-agent-kernel eval——eval-set 批量运行入口（宿主回归用，S5 消费）。

eval-set 格式（宿主维护，Skill metadata eval-set 指向）：
    evals/<name>.yaml：
        - input: "用户输入"
          expect: {contains: ["关键词"], tool_called: "rag_search"}

批量运行作为 Prompt/模型变更后的质量门（Agent内核框架 §九）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EvalCase:
    """单条评测用例。"""

    input: str
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """单条评测结果。"""

    case: EvalCase
    output: str
    passed: bool
    failures: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """批量评测报告。"""

    total: int
    passed: int
    results: list[EvalResult]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def load_eval_set(path: str | Path) -> list[EvalCase]:
    """加载 eval-set YAML 文件。"""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"eval-set 应为用例列表: {path}")
    cases: list[EvalCase] = []
    for item in raw:
        cases.append(EvalCase(input=str(item["input"]), expect=dict(item.get("expect", {}))))
    return cases


def _evaluate(case: EvalCase, output: str, tool_calls: list[str]) -> EvalResult:
    """单条评测判定（contains / tool_called 两类断言）。"""
    failures: list[str] = []
    contains = case.expect.get("contains", [])
    for keyword in contains:
        if keyword not in output:
            failures.append(f"输出缺少关键词: {keyword}")
    expected_tool = case.expect.get("tool_called")
    if expected_tool and expected_tool not in tool_calls:
        failures.append(f"未调用工具: {expected_tool}")
    return EvalResult(case=case, output=output, passed=not failures, failures=failures)


async def run_eval_set(session: Any, cases: list[EvalCase]) -> EvalReport:
    """批量运行 eval-set（复用同一会话，按序执行）。

    Args:
        session: AgentSession 实例。
        cases: 评测用例列表。

    Returns:
        EvalReport（含每条判定与失败原因）。
    """
    results: list[EvalResult] = []
    for case in cases:
        before = len(session.audit.records)
        output = await session.run(case.input)
        tool_calls = [r.tool_name for r in session.audit.records[before:]]
        results.append(_evaluate(case, str(output or ""), tool_calls))
    passed = sum(1 for r in results if r.passed)
    return EvalReport(total=len(results), passed=passed, results=results)


__all__ = ["EvalCase", "EvalResult", "EvalReport", "load_eval_set", "run_eval_set"]
