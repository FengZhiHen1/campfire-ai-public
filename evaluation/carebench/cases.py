"""案例读写与结构校验：CareBench JSONL 的唯一解析处。

职责：按协议 02 第 3 节的字段读取案例、做结构校验（不做内容/专业判断）、给出数据集
字节 hash 与逐案 hash。

边界：**不修改案例内容**。读进来的每一行原文另存一份（`raw`），冻结时逐字节复制；
任何「顺手规范化」都会让冻结哈希与上游不一致，而那正是污染判据失效的形状。

为什么校验只到结构层：协议 02 明写「结构校验成功不等于案例经过领域专家审核」。
本模块因而只回答「这一行能不能被程序当成一个案例」，把 `must_check/must_not` 的
专业正确性留给人工评审（`review_status` 字段与 protocol/README 的措辞要求）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hashing import sha256_bytes, sha256_value

#: `case_id` 的形状。只要求「稳定、可读、无空白」：上游现在用 `CFB-C-001` / `CFB-T-001`，
#: 但把前缀写死会在先导集（`CFB-P-`）上误拒，因此这里不编码前缀含义。
CASE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z0-9]+-\d+$")

#: 协议 02 第 3 节要求的字段。
REQUIRED_FIELDS = (
    "id",
    "split",
    "category",
    "risk_hint",
    "user_message",
    "shared_context",
    "followup",
    "must_check",
    "must_not",
    "source_kind",
    "review_status",
)

#: 允许的 split。与配置的 `label` 不必相等——正式集是 `test`，先导是 `pilot`，
#: 但校准集（`calibration`）也可以被拿来做工具自检。
ALLOWED_SPLITS = frozenset({"calibration", "pilot", "test"})

#: 案例的「已审核」取值。只有这个值才算专业审核通过；其余一律按未审对待。
APPROVED_REVIEW_STATUS = "approved"


class CaseValidationError(ValueError):
    """案例结构不合法（含行号与原因，便于直接定位到样例）。"""


@dataclass(frozen=True)
class Case:
    """一条评测案例（协议 02 第 3 节）。

    `fixtures` 是本工具的可选扩展：某些「系统失效」类案例需要在运行时**真实注入**
    故障（检索为空、工具失败等）。它不改变原始 JSON——冻结文件逐字节保持上游原样，
    注入映射写在单独的 fixture 配置里，运行时按 `case_id` 取名。
    """

    id: str
    split: str
    category: str
    risk_hint: str
    user_message: str
    shared_context: str
    followup: str | None
    must_check: tuple[str, ...]
    must_not: tuple[str, ...]
    source_kind: str
    review_status: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def turns(self) -> int:
        """本案例的轮数：固定 followup 才跑第二轮（协议 02 第 1 节）。"""
        return 2 if self.followup else 1

    @property
    def approved(self) -> bool:
        """是否已由专业/独立评审标记为 approved（决定能否写「已审核」措辞）。"""
        return self.review_status == APPROVED_REVIEW_STATUS

    def message_for_turn(self, turn: int) -> str:
        """第 `turn` 轮的使用者原文。

        Raises:
            ValueError: 轮次超出本案例的轮数——不允许「看结果后即兴追问」。
        """
        if turn == 1:
            return self.user_message
        if turn == 2 and self.followup:
            return self.followup
        raise ValueError(f"{self.id} 没有第 {turn} 轮输入（followup={self.followup!r}）")

    def canonical(self) -> dict[str, Any]:
        """规范字典（逐案 hash 用；不含 `raw` 原文行）。"""
        return {
            "id": self.id,
            "split": self.split,
            "category": self.category,
            "risk_hint": self.risk_hint,
            "user_message": self.user_message,
            "shared_context": self.shared_context,
            "followup": self.followup,
            "must_check": list(self.must_check),
            "must_not": list(self.must_not),
            "source_kind": self.source_kind,
            "review_status": self.review_status,
            "extra": self.extra,
        }

    @property
    def sha256(self) -> str:
        """逐案内容 hash（冻结记录里逐条留痕，便于定位是哪一个案例变了）。"""
        return sha256_value(self.canonical())


@dataclass(frozen=True)
class CaseSet:
    """一份案例集：字节 hash + 解析后的案例（保持文件顺序）。"""

    path: Path
    raw_bytes: bytes
    cases: tuple[Case, ...]

    @property
    def sha256(self) -> str:
        """数据集字节 hash（批次指纹与冻结记录都用它）。"""
        return sha256_bytes(self.raw_bytes)

    @property
    def ids(self) -> tuple[str, ...]:
        """案例 id（保持文件顺序，轮换按这个顺序取模）。"""
        return tuple(case.id for case in self.cases)

    @property
    def split(self) -> str:
        """数据集声明的 split（要求全表一致）。"""
        return self.cases[0].split if self.cases else ""

    @property
    def review_status_counts(self) -> dict[str, int]:
        """`review_status` 直方图（正式运行必须如实报告是否已审）。"""
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.review_status] = counts.get(case.review_status, 0) + 1
        return counts

    def by_id(self, case_id: str) -> Case:
        """按 id 取案例。

        Raises:
            KeyError: 不存在。
        """
        for case in self.cases:
            if case.id == case_id:
                return case
        raise KeyError(case_id)


def load_case_file(path: Path) -> CaseSet:
    """读取并校验一份案例 JSONL。

    Raises:
        FileNotFoundError: 文件不存在。
        CaseValidationError: 结构不合法（缺字段、id 重复、轮数矛盾等）。
    """
    raw = path.read_bytes()
    return parse_cases(raw, source=str(path), path=path)


def parse_cases(raw: bytes, *, source: str, path: Path | None = None) -> CaseSet:
    """从字节解析案例集（冻结文件与上游文件走同一条路，判据因此只有一份）。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaseValidationError(f"{source}：不是 UTF-8 文本（{exc}）") from exc

    cases: list[Case] = []
    seen: set[str] = set()
    splits: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaseValidationError(f"{source}:{line_no} 不是合法 JSON（{exc.msg}）") from exc
        case = _parse_case(payload, source=source, line_no=line_no)
        if case.id in seen:
            raise CaseValidationError(f"{source}:{line_no} 案例 id 重复：{case.id}")
        seen.add(case.id)
        splits.add(case.split)
        cases.append(case)

    if not cases:
        raise CaseValidationError(f"{source}：没有任何案例行")
    if len(splits) > 1:
        raise CaseValidationError(f"{source}：同一文件的 split 不一致：{sorted(splits)}")

    resolved = path if path is not None else Path(source)
    return CaseSet(path=resolved, raw_bytes=raw, cases=tuple(cases))


def _parse_case(payload: Any, *, source: str, line_no: int) -> Case:
    """校验单条并转成 :class:`Case`。

    Raises:
        CaseValidationError: 字段缺失、类型不符或取值越界。
    """
    where = f"{source}:{line_no}"
    if not isinstance(payload, dict):
        raise CaseValidationError(f"{where} 这一行不是 JSON 对象")
    missing = [name for name in REQUIRED_FIELDS if name not in payload]
    if missing:
        raise CaseValidationError(f"{where} 缺字段：{missing}")

    case_id = payload["id"]
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise CaseValidationError(f"{where} case_id 形状不合法：{case_id!r}")

    split = payload["split"]
    if split not in ALLOWED_SPLITS:
        raise CaseValidationError(f"{where} split={split!r} 不在 {sorted(ALLOWED_SPLITS)}")

    followup = payload["followup"]
    if followup is not None and not isinstance(followup, str):
        raise CaseValidationError(f"{where} followup 必须是字符串或 null")
    if isinstance(followup, str) and not followup.strip():
        raise CaseValidationError(f"{where} followup 是空串：应写 null 表示单轮")

    for name in ("must_check", "must_not"):
        value = payload[name]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise CaseValidationError(f"{where} {name} 必须是非空字符串数组")

    for name in ("user_message", "shared_context", "category", "risk_hint", "source_kind", "review_status"):
        value = payload[name]
        if not isinstance(value, str) or not value.strip():
            raise CaseValidationError(f"{where} {name} 必须是非空字符串")

    known = set(REQUIRED_FIELDS) | {"fixtures"}
    extra = {key: value for key, value in payload.items() if key not in known}
    if "fixtures" in payload:
        extra["fixtures"] = payload["fixtures"]

    return Case(
        id=case_id,
        split=split,
        category=payload["category"],
        risk_hint=payload["risk_hint"],
        user_message=payload["user_message"],
        shared_context=payload["shared_context"],
        followup=followup,
        must_check=tuple(payload["must_check"]),
        must_not=tuple(payload["must_not"]),
        source_kind=payload["source_kind"],
        review_status=payload["review_status"],
        extra=extra,
    )


__all__ = [
    "ALLOWED_SPLITS",
    "APPROVED_REVIEW_STATUS",
    "CASE_ID_PATTERN",
    "REQUIRED_FIELDS",
    "Case",
    "CaseSet",
    "CaseValidationError",
    "load_case_file",
    "parse_cases",
]
