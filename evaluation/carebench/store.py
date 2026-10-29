"""运行目录与落盘原语：一次批次一个目录，原始记录只追加不改写。

职责：给出 run 目录布局、原子 JSON 写、JSONL 追加与读取、轨迹文件命名。

边界：不做任何业务判断（哪些组别完成、分母多少，见 :mod:`evaluation.carebench.runner`
与 :mod:`evaluation.carebench.summarize`）。

落盘纪律（协议 01 第 5 节、04 第 2 节）：

- `outputs.jsonl` 只追加：一次尝试一条记录，写完 `flush + fsync`。中断时最后一条可能是
  半行，读取方跳过它并把它计为 `partial_write`（不猜、不修补）。
- 原始输出与评分数据分离：评分只在 `review/` 下，且评分文件永不回写 `outputs.jsonl`。
- 轨迹（工具调用、检索材料、事件流水）落 `traces/`，输出行只引用文件名——一条检索轨迹
  可能有几十 KB，塞进 outputs.jsonl 会让「逐行读一次」变成读几百 MB。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 输出记录文件（逐 case-group 逐轮逐尝试）。
OUTPUTS_FILE = "outputs.jsonl"

#: 失败/拒答/超时的派生清单（由 outputs.jsonl 派生，供人眼快速定位）。
ERRORS_FILE = "errors.jsonl"

#: 批次清单。
MANIFEST_FILE = "manifest.json"

#: 冻结信息（案例 hash、配置 hash、代码提交、指纹）。
FREEZE_FILE = "freeze.json"

#: 冻结案例副本（与上游字节一致）。
CASES_FILE = "cases.frozen.jsonl"

#: 进度快照（派生；verify 会核对它与 outputs.jsonl 一致）。
STATE_FILE = "state.json"

#: 轨迹子目录。
TRACES_DIR = "traces"

#: 评审子目录。
REVIEW_DIR = "review"


def _json_default(value: Any) -> Any:
    """JSON 序列化的兜底：时间与 UUID 转字符串，其余抛错。

    为什么不让 `json.dumps` 直接失败：C 组的轨迹里带 `datetime`（引用记录的创建时间、
    卡片时间戳）。把它们写成 ISO 字符串是唯一的无损选择；而**其余不可序列化的对象一律抛错**
    ——静默 `str(obj)` 会把一个调试用的 repr 写进证据包，那比失败更糟。
    """
    from datetime import date, datetime
    from uuid import UUID

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    raise TypeError(f"证据载荷里有不可序列化的对象：{type(value).__name__}")


def write_json(path: Path, payload: Any) -> None:
    """原子写 JSON（同目录临时文件 + `os.replace`）。

    原子写的理由不是洁癖：`manifest.json` 与 `freeze.json` 是证据包的身份，写到一半
    被杀掉会得到一个「能解析但内容不完整」的文件，比没有文件更危险。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    """读 JSON。

    Raises:
        FileNotFoundError: 文件不存在。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """追加一条 JSONL 记录并落盘（fsync：断电/被杀也不丢已写记录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读 JSONL；**跳过**末尾半行（中断留下的残行），其余按原顺序返回。

    末尾半行不抛错是刻意的：一次被 `SIGKILL` 打断的运行必然留下它，
    如果读取方直接失败，`resume` 就永远起不来——那等于「中断即报废」。
    """
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            # 只容忍最后一行（其余位置出现坏行说明文件被外部改过，交给 verify 报）。
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def trailing_partial_line(path: Path) -> bool:
    """文件是否以不完整的行结尾（供 verify 报告「上次中断」这一事实）。"""
    if not path.exists():
        return False
    raw = path.read_bytes()
    if not raw:
        return False
    return not raw.endswith(b"\n")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """整份重写 JSONL（只用于派生文件，如 `errors.jsonl`）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


@dataclass(frozen=True)
class RunStore:
    """一次批次的目录视图。

    只包路径与落盘原语；不含任何「哪条记录算数」的判定——那是 runner 与 summarize 的事。
    """

    root: Path

    # --- 路径 ---
    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILE

    @property
    def freeze_path(self) -> Path:
        return self.root / FREEZE_FILE

    @property
    def cases_path(self) -> Path:
        return self.root / CASES_FILE

    @property
    def outputs_path(self) -> Path:
        return self.root / OUTPUTS_FILE

    @property
    def errors_path(self) -> Path:
        return self.root / ERRORS_FILE

    @property
    def state_path(self) -> Path:
        return self.root / STATE_FILE

    @property
    def traces_dir(self) -> Path:
        return self.root / TRACES_DIR

    @property
    def review_dir(self) -> Path:
        return self.root / REVIEW_DIR

    # --- 读写 ---
    def append_output(self, record: dict[str, Any]) -> None:
        append_jsonl(self.outputs_path, record)

    def read_outputs(self) -> list[dict[str, Any]]:
        return read_jsonl(self.outputs_path)

    def write_manifest(self, payload: dict[str, Any]) -> None:
        write_json(self.manifest_path, payload)

    def read_manifest(self) -> dict[str, Any]:
        payload = read_json(self.manifest_path)
        if not isinstance(payload, dict):
            raise ValueError(f"{self.manifest_path} 不是 JSON 对象")
        return payload

    def write_state(self, payload: dict[str, Any]) -> None:
        write_json(self.state_path, payload)

    def read_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        payload = read_json(self.state_path)
        return payload if isinstance(payload, dict) else None

    def write_trace(self, name: str, payload: Any) -> str:
        """写一份轨迹文件，返回相对路径（进 outputs.jsonl 的 `trace_file`）。"""
        safe = _safe_trace_name(name)
        path = self.traces_dir / safe
        write_json(path, payload)
        return f"{TRACES_DIR}/{safe}"

    def read_trace(self, relative: str) -> Any:
        """按相对路径读轨迹文件（拒绝越出 run 目录的路径）。"""
        candidate = (self.root / relative).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError(f"轨迹路径越出 run 目录：{relative}")
        return read_json(candidate)

    def iter_trace_files(self) -> Iterator[Path]:
        if not self.traces_dir.exists():
            return
        yield from sorted(self.traces_dir.glob("*.json"))


def _safe_trace_name(name: str) -> str:
    """把轨迹名限制成文件名（不含分隔符与控制字符）。"""
    cleaned = "".join(char if char.isalnum() or char in "-_." else "_" for char in name)
    return f"{cleaned}.json" if not cleaned.endswith(".json") else cleaned


def create_run_dir(parent: Path, run_id: str) -> RunStore:
    """新建一个批次目录。

    Raises:
        FileExistsError: 该 run_id 已存在（不允许覆盖已有批次：那是抹掉原始证据）。
    """
    root = parent / run_id
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"批次目录已存在且非空：{root}（续跑请用 resume）")
    root.mkdir(parents=True, exist_ok=True)
    store = RunStore(root=root)
    store.traces_dir.mkdir(parents=True, exist_ok=True)
    store.review_dir.mkdir(parents=True, exist_ok=True)
    return store


__all__ = [
    "CASES_FILE",
    "ERRORS_FILE",
    "FREEZE_FILE",
    "MANIFEST_FILE",
    "OUTPUTS_FILE",
    "REVIEW_DIR",
    "STATE_FILE",
    "TRACES_DIR",
    "RunStore",
    "append_jsonl",
    "create_run_dir",
    "read_json",
    "read_jsonl",
    "trailing_partial_line",
    "write_json",
    "write_jsonl",
]
