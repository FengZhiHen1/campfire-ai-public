"""冻结案例与运行预算；隐藏事实不进入被测系统的初始输入。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..cases import Case

VERSION = "0.2"
SYSTEMS = ("N", "P", "C")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 12000:
        raise ValueError(f"{name} 必须是非空且不超过 12000 字符的文本")
    return value


def _identifier(value: Any, name: str) -> str:
    value = _text(value, name)
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} 不是合法标识")
    return value


def _objects(value: Any, name: str, keys: set[str], *, nonempty: bool = False) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{name} 必须是{'非空' if nonempty else ''}数组")
    result = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != keys:
            raise ValueError(f"{name} 条目字段必须是 {sorted(keys)}")
        identifier = _identifier(item.get("id"), f"{name}.id")
        if identifier in seen:
            raise ValueError(f"{name} 标识重复")
        seen.add(identifier)
        for key, text in item.items():
            if key not in {"known", "initial"}:
                _text(text, f"{name}.{key}")
            elif type(text) is not bool:
                raise ValueError(f"{name}.{key} 必须是布尔值")
        result.append(dict(item))
    return tuple(result)


@dataclass(frozen=True)
class Scenario:
    id: str
    split: str
    category: str
    entry: str
    expression: str
    information: str
    opening: str
    facts: tuple[dict[str, Any], ...]
    feedback: tuple[dict[str, Any], ...]
    success_criteria: tuple[dict[str, Any], ...]
    forbidden: tuple[dict[str, Any], ...]
    max_assistant_turns: int
    source_kind: str
    review_status: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Scenario:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("案例字段缺失或含未知字段")
        payload = dict(value)
        _identifier(payload["id"], "id")
        for key in ("category", "opening"):
            _text(payload[key], key)
        if payload["category"] not in {"日常事务", "日常沟通", "信息不足", "现场安全", "现场资源", "反驳与转介"}:
            raise ValueError("category 不在协议允许范围")
        for key, choices in {
            "split": {"calibration", "test"},
            "entry": {"daily", "emergency"},
            "expression": {"clear", "fragmented"},
            "information": {"sufficient", "partial"},
            "source_kind": {"synthetic"},
            "review_status": {"draft_unreviewed"},
        }.items():
            if not isinstance(payload[key], str) or payload[key] not in choices:
                raise ValueError(f"{key} 不在允许范围")
        limit = 3 if payload["entry"] == "emergency" else 5
        if type(payload["max_assistant_turns"]) is not int or payload["max_assistant_turns"] != limit:
            raise ValueError(f"{payload['entry']} 必须冻结为最多 {limit} 次系统回复")
        payload["facts"] = _objects(
            payload["facts"], "facts", {"id", "description", "answer", "known", "initial"}, nonempty=True
        )
        if not 3 <= len(payload["facts"]) <= 8:
            raise ValueError("事实档案必须含 3–8 条冻结事实")
        payload["feedback"] = _objects(payload["feedback"], "feedback", {"id", "when", "reply"})
        payload["success_criteria"] = _objects(
            payload["success_criteria"], "success_criteria", {"id", "text"}, nonempty=True
        )
        payload["forbidden"] = _objects(payload["forbidden"], "forbidden", {"id", "text"}, nonempty=True)
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))

    def legacy_case(self, user_text: str) -> Case:
        """只适配既有运行器接口；不把隐藏背景装进 shared_context。"""
        return Case(
            id=self.id,
            split=self.split,
            category=self.category,
            risk_hint="unspecified",
            user_message=user_text,
            shared_context="",
            followup=None,
            must_check=tuple(item["text"] for item in self.success_criteria),
            must_not=tuple(item["text"] for item in self.forbidden),
            source_kind=self.source_kind,
            review_status=self.review_status,
        )


def load_scenarios(path: Path) -> tuple[Scenario, ...]:
    result = []
    for line, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            raise ValueError(f"第 {line} 行为空")
        try:
            result.append(Scenario.from_dict(json.loads(raw)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"第 {line} 行案例非法：{exc}") from exc
    if not result:
        raise ValueError("案例集为空")
    if len({case.id for case in result}) != len(result):
        raise ValueError("案例 id 重复")
    if len({case.split for case in result}) != 1:
        raise ValueError("校准集与正式集不得混用")
    return tuple(result)


@dataclass(frozen=True)
class Budget:
    """重试只补结构无效项，不因分数、任务失败或回答质量重采。"""

    repetitions: int = 3
    policy_attempts: int = 2
    rating_attempts: int = 3
    turn_timeout_seconds: int = 150
    daily_wait_seconds: int = 300
    emergency_wait_seconds: int = 150
    max_facts_per_reply: int = 2

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"预算 {key} 必须是正整数")
        if self.policy_attempts > 3 or self.rating_attempts > 5 or self.max_facts_per_reply != 2:
            raise ValueError("重试或披露预算超出协议边界")
        if self.repetitions > 5:
            raise ValueError("重复次数超出协议边界")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
