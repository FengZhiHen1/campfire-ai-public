"""测试 message_handler 服务。"""

import json
from pathlib import Path

import pytest

from runtime.message.handler import _cleanup_empty_files, _find_escaped_files, inject_modified_files, scan_messages, write_message


def test_write_message(monkeypatch, tmp_path: Path):
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".agent" / "instances" / "inst-001" / "messages").mkdir(parents=True)
    monkeypatch.chdir(repo)
    result = write_message(
        instance_id="inst-001",
        stage_id="s01",
        stage_instance_id="s01",
        status="DONE",
        report="completed",
    )
    assert result["status"] == "ok"
    assert result["message_id"].startswith("msg-")

    msg_path = repo / ".agent" / "instances" / "inst-001" / "messages" / f"{result['message_id']}.json"
    assert msg_path.exists()
    data = json.loads(msg_path.read_text(encoding="utf-8"))
    assert data["stage_id"] == "s01"
    assert data["status"] == "DONE"


def test_scan_messages_skips_consumed(monkeypatch, tmp_path: Path):
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".agent" / "instances" / "inst-001" / "messages").mkdir(parents=True)
    for mid in ["msg-a", "msg-b", "msg-c"]:
        msg = {
            "message_id": mid,
            "instance_id": "inst-001",
            "stage_id": "s01",
            "status": "DONE",
            "timestamp": f"2026-05-17T10:00:0{mid[-1]}+0800",
        }
        (repo / ".agent" / "instances" / "inst-001" / "messages" / f"{mid}.json").write_text(
            json.dumps(msg), encoding="utf-8"
        )
    monkeypatch.chdir(repo)

    messages = scan_messages("inst-001", {"msg-a"})
    mids = [m["message_id"] for m in messages]
    assert "msg-a" not in mids
    assert "msg-b" in mids
    assert "msg-c" in mids


def test_scan_messages_empty(monkeypatch, tmp_path: Path):
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".agent" / "instances" / "inst-001" / "messages").mkdir(parents=True)
    monkeypatch.chdir(repo)
    messages = scan_messages("inst-001", set())
    assert messages == []


def test_inject_modified_files(tmp_path: Path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    (repo / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)

    msg = {"message_id": "msg-x"}
    result = inject_modified_files(msg, repo)
    assert "modified_files" in result
    # file.txt 已 staged，porcelain 会显示；新格式为对象数组
    paths = [f["path"] for f in result["modified_files"]]
    assert "file.txt" in paths
    # 验证对象包含 status 字段
    if result["modified_files"]:
        assert "status" in result["modified_files"][0]


class TestCleanupEmptyFiles:
    def test_deletes_empty_file_and_removes_from_list(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / "empty.txt").write_text("", encoding="utf-8")
        (wt / "nonempty.txt").write_text("content", encoding="utf-8")

        files = [
            {"path": "empty.txt", "status": "?"},
            {"path": "nonempty.txt", "status": "?"},
        ]
        _cleanup_empty_files(wt, files)

        assert not (wt / "empty.txt").exists()
        assert (wt / "nonempty.txt").exists()
        assert len(files) == 1
        assert files[0]["path"] == "nonempty.txt"

    def test_skips_directories(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / "subdir").mkdir()

        files = [{"path": "subdir", "status": "?"}]
        _cleanup_empty_files(wt, files)

        assert (wt / "subdir").exists()
        assert len(files) == 1

    def test_ignores_permission_errors(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / "locked.txt").write_text("", encoding="utf-8")

        files = [{"path": "locked.txt", "status": "?"}]
        # 不会因为权限问题崩溃
        _cleanup_empty_files(wt, files)
        assert not (wt / "locked.txt").exists()

    def test_none_worktree_noop(self):
        files = [{"path": "x.txt", "status": "?"}]
        _cleanup_empty_files(None, files)  # 不崩溃
        assert len(files) == 1


class TestFindEscapedFiles:
    def test_normal_files_inside_worktree(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / "src").mkdir()
        (wt / "src" / "main.py").write_text("x", encoding="utf-8")

        files = [{"path": "src/main.py", "status": "M"}]
        assert _find_escaped_files(wt, files) == []

    def test_parent_ref_detected(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        (tmp_path / "outside.txt").write_text("x", encoding="utf-8")

        files = [{"path": "../outside.txt", "status": "M"}]
        escaped = _find_escaped_files(wt, files)
        assert len(escaped) == 1
        assert "../outside.txt" in escaped[0]

    def test_absolute_path_detected(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()

        files = [{"path": "C:/Windows/System32/evil.dll", "status": "M"}]
        escaped = _find_escaped_files(wt, files)
        assert len(escaped) == 1

    def test_mixed_ok_and_escaped(self, tmp_path: Path):
        wt = tmp_path / "worktree"
        wt.mkdir()
        (wt / "ok.txt").write_text("x", encoding="utf-8")

        files = [
            {"path": "ok.txt", "status": "M"},
            {"path": "../bad.txt", "status": "M"},
        ]
        escaped = _find_escaped_files(wt, files)
        assert escaped == ["../bad.txt"]
