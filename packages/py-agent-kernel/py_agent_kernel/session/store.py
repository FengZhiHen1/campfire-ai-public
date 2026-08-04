"""py-agent-kernel Session——JSONL 树存储（pi 结构同构）。

语义（Agent内核框架 §六）：
- 每条 entry 含 id/parentId，构成树；branch/fork/clone 结构同构 pi
- 消息负载经 pydantic-ai ModelMessagesTypeAdapter 落盘（字节不与 pi 兼容，
  仅结构同构——§十偏差清单）
- compaction 只影响上下文窗口，完整历史始终保留在 JSONL 中
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionEntry:
    """会话树条目（id/parentId 链）。"""

    id: str
    parent_id: str | None
    type: str  # message / compaction / branch / custom
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parentId": self.parent_id,
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionEntry":
        return cls(
            id=data["id"],
            parent_id=data.get("parentId"),
            type=data["type"],
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", time.time()),
        )


class SessionTree:
    """JSONL 树——追加写 + 全量载入 + 分支导航。

    存储：每会话一个 JSONL 文件（每行一个 entry JSON）。
    树结构经 parentId 链构建；当前分支 = 从叶到根的链。
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: list[SessionEntry] = []
        if path.exists():
            self._load()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append(self, entry_type: str, payload: dict[str, Any], parent_id: str | None = None) -> SessionEntry:
        """追加条目（自动链接到当前叶，除非显式 parent_id）。"""
        if parent_id is None:
            parent_id = self.leaf_id
        entry = SessionEntry(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            type=entry_type,
            payload=payload,
        )
        self._entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return entry

    # ------------------------------------------------------------------
    # 读取与树导航
    # ------------------------------------------------------------------

    @property
    def entries(self) -> list[SessionEntry]:
        return list(self._entries)

    @property
    def leaf_id(self) -> str | None:
        return self._entries[-1].id if self._entries else None

    def get(self, entry_id: str) -> SessionEntry | None:
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def children_of(self, entry_id: str | None) -> list[SessionEntry]:
        return [e for e in self._entries if e.parent_id == entry_id]

    def chain_to_root(self, entry_id: str) -> list[SessionEntry]:
        """从指定条目回溯到根的链（根在前）。"""
        chain: list[SessionEntry] = []
        current: SessionEntry | None = self.get(entry_id)
        while current is not None:
            chain.append(current)
            current = self.get(current.parent_id) if current.parent_id else None
        chain.reverse()
        return chain

    def current_branch(self) -> list[SessionEntry]:
        """当前分支（叶到根的链，根在前）。"""
        if not self._entries:
            return []
        return self.chain_to_root(self._entries[-1].id)

    # ------------------------------------------------------------------
    # branch / fork / clone（结构同构 pi）
    # ------------------------------------------------------------------

    def fork(self, from_entry_id: str) -> str | None:
        """从指定条目分叉——返回分叉点 id（后续 append 以其为 parent）。

        fork 不复制条目；新分支共享历史前缀（树结构天然支持）。
        """
        entry = self.get(from_entry_id)
        return entry.id if entry else None

    def branch_head_ids(self) -> list[str]:
        """全部分支头（无子条目的条目 id 列表）。"""
        parent_ids = {e.parent_id for e in self._entries if e.parent_id}
        return [e.id for e in self._entries if e.id not in parent_ids]

    def clone_to(self, target_path: Path) -> "SessionTree":
        """克隆整棵树到新路径（完整复制 JSONL）。"""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return SessionTree(target_path)

    # ------------------------------------------------------------------
    # 载入
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._entries = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                self._entries.append(SessionEntry.from_dict(json.loads(line)))

    @classmethod
    def load(cls, path: Path) -> "SessionTree":
        return cls(path)


__all__ = ["SessionEntry", "SessionTree"]
