"""新批次独立落点与追加式记录；部分写入不得静默丢弃。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..hashing import sha256_value
from ..store import append_jsonl, write_json


def seal(value: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(value, ensure_ascii=False))
    payload.pop("record_sha256", None)
    return {**payload, "record_sha256": sha256_value(payload)}


def check_record(value: dict[str, Any]) -> bool:
    return value.get("record_sha256") == seal(value)["record_sha256"]


def records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError(f"{path.name} 有未完成写入；保留现场，不允许静默续写")
    result = []
    for line, text in enumerate(raw.decode("utf-8").splitlines(), 1):
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"{path.name}:{line} 不是合法 JSON") from exc
        if not isinstance(value, dict) or not check_record(value):
            raise ValueError(f"{path.name}:{line} 记录 hash 不匹配")
        result.append(value)
    return result


def append(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    payload = seal(value)
    append_jsonl(path, payload)
    return payload


def immutable_json(path: Path, value: dict[str, Any]) -> None:
    """冻结件只准首次创建；派生 summary 才使用可替换写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(seal(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        import os

        os.fsync(handle.fileno())


def read_immutable(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not check_record(value):
        raise ValueError(f"{path.name} 冻结 hash 不匹配")
    return value


__all__ = ["append", "check_record", "immutable_json", "read_immutable", "records", "seal", "write_json"]
