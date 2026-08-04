"""Session 单元测试——JSONL 树/序列化往返/steering/follow-up/compaction。"""

from __future__ import annotations

from py_agent_kernel.session import (
    InjectionMode,
    PendingMessageQueue,
    SessionTree,
    deserialize_messages,
    serialize_messages,
)
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart


class TestSessionTree:
    def test_append_and_chain(self, tmp_path):
        tree = SessionTree(tmp_path / "s.jsonl")
        e1 = tree.append("message", {"messages": []})
        e2 = tree.append("message", {"messages": []})
        assert e2.parent_id == e1.id
        branch = tree.current_branch()
        assert [e.id for e in branch] == [e1.id, e2.id]

    def test_persistence_roundtrip(self, tmp_path):
        path = tmp_path / "s.jsonl"
        tree = SessionTree(path)
        tree.append("message", {"messages": [{"x": 1}]})
        reloaded = SessionTree(path)
        assert len(reloaded.entries) == 1
        assert reloaded.entries[0].payload == {"messages": [{"x": 1}]}

    def test_fork_structure(self, tmp_path):
        """fork：新分支共享历史前缀（树结构天然支持）。"""
        tree = SessionTree(tmp_path / "s.jsonl")
        e1 = tree.append("message", {"messages": []})
        e2 = tree.append("message", {"messages": []})
        fork_point = tree.fork(e1.id)
        e3 = tree.append("message", {"messages": []}, parent_id=fork_point)
        # e3 从 e1 分叉，e2 是另一分支
        assert e3.parent_id == e1.id
        heads = tree.branch_head_ids()
        assert set(heads) == {e2.id, e3.id}
        # e3 的分支链不含 e2
        chain = tree.chain_to_root(e3.id)
        assert [e.id for e in chain] == [e1.id, e3.id]

    def test_clone(self, tmp_path):
        tree = SessionTree(tmp_path / "a.jsonl")
        tree.append("message", {"messages": []})
        clone = tree.clone_to(tmp_path / "b.jsonl")
        assert len(clone.entries) == 1


class TestMessageSerialization:
    def test_roundtrip(self):
        messages = [
            ModelRequest(parts=[UserPromptPart(content="你好")]),
            ModelResponse(parts=[TextPart(content="您好！")]),
        ]
        payload = serialize_messages(messages)
        restored = deserialize_messages(payload)
        assert len(restored) == 2
        assert isinstance(restored[0], ModelRequest)
        assert restored[0].parts[0].content == "你好"
        assert isinstance(restored[1], ModelResponse)
        assert restored[1].parts[0].content == "您好！"


class TestPendingMessageQueue:
    def test_asap_drain(self):
        q = PendingMessageQueue()
        q.enqueue("立即注入", InjectionMode.ASAP)
        q.enqueue("空闲注入", InjectionMode.WHEN_IDLE)
        asap = q.drain_asap()
        assert asap == ["立即注入"]
        assert len(q) == 1

    def test_when_idle_drain(self):
        q = PendingMessageQueue()
        q.enqueue("空闲注入1", "when_idle")
        q.enqueue("空闲注入2", "when_idle")
        idle = q.drain_when_idle()
        assert idle == ["空闲注入1", "空闲注入2"]
        assert len(q) == 0
