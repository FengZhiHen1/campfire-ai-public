r"""哈希与规范化 JSON：全包唯一的「同一份内容 → 同一个 hash」实现。

职责：canonical JSON（键排序、紧凑分隔、UTF-8）、内容 hash、文件 hash、批次指纹。

边界：只做编码与摘要，不读业务语义。所有落盘的 manifest / freeze / 输出记录都经
这里算 hash，因此「两个 hash 相等」在全包里只有一种含义。

为什么单独成模块：案例哈希、配置哈希、批次指纹、证据包校验四处的口径必须完全一致。
各处各写一次 `json.dumps(...)` 的话，第一次改 separators 就会让 verify 判所有历史
批次失效——那种「谁都没改业务、校验却全红」的形态在本仓已经出现过（见 AGENTS.md
关于「注释里点名的测试会漂」的记录）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: 规范化 JSON 的分隔符。紧凑形式 + 排序键 = 内容相同则字节相同。
_SEPARATORS = (",", ":")


def canonical_json(value: Any) -> str:
    """把任意可 JSON 化的值写成规范文本（键排序、紧凑、不转义中文）。

    `ensure_ascii=False` 是刻意的：中文标题与来源在 manifest 里要人眼可读，转义成
    `\\uXXXX` 会让证据包里的许可结论变成一串码点，评审者只能靠工具反查。
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=_SEPARATORS)


def sha256_text(text: str) -> str:
    """文本的 SHA-256（UTF-8）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(raw: bytes) -> str:
    """字节的 SHA-256。"""
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    """文件内容的 SHA-256（按块读，避免把大 JSONL 一次读进内存）。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_value(value: Any) -> str:
    """任意可 JSON 化值的 SHA-256（先规范化）。"""
    return sha256_text(canonical_json(value))


def batch_fingerprint(*, dataset_sha256: str, config_sha256: str, code_commit: str) -> str:
    """批次指纹：案例集 + 有效配置 + 代码提交三者的联合 hash。

    三件中任何一件变化都必须得到不同的指纹——这就是「不允许不同代码/案例/配置混批」
    的机械判据（`resume` 与 `verify` 都按它比对，不一致直接拒绝，而不是合并）。
    """
    return sha256_value(
        {
            "dataset_sha256": dataset_sha256,
            "config_sha256": config_sha256,
            "code_commit": code_commit,
        }
    )


__all__ = [
    "batch_fingerprint",
    "canonical_json",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "sha256_value",
]
