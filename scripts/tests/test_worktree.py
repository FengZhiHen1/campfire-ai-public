"""`scripts/worktree.py` 的针对性测试（纯标准库 + 真实 git，不联网、不连库）。

为什么值得单测：这个脚本删的是**别人未提交的工作**。它的每条拒绝理由都必须能失败
——否则「安全删工作树」只是一句注释。所以每条拒绝都配一个用例，且断言的是
「目录仍在、分支仍在」这个可观察事实，而不是「打印了某句提示」。

用临时仓库（`tmp_path`）而不是本仓库：这些用例要制造脏工作区、未合并分支与
未注册目录，在本仓库里做这些事既不安全也不可重复。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "worktree.py"


def _git(repo: Path, *args: str) -> str:
    """在 repo 里跑一条 git 命令并返回 stdout（失败即抛，避免用例在坏环境上继续）。"""
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr or proc.stdout}"
    return proc.stdout


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """跑本脚本（子进程，避免污染测试进程的环境与 cwd 假设）。"""
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, text=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    """建一个最小 git 仓库，默认分支 `dev`（与仓库习惯一致）。

    `pyproject.toml` 必须存在：`worktree.py` 用「根下有 pyproject.toml」来确认
    common dir 的父目录真的是本仓库根，而不是裸仓库或 `--separate-git-dir` 布局。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.uv]\n", encoding="utf-8")
    (repo / "README.md").write_text("probe\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "worktree-test@example.invalid")
    _git(repo, "config", "user.name", "worktree-test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_create_places_worktree_under_root_with_task_branch(tmp_path: Path) -> None:
    """`create` 在 `<root>/.worktrees/<slug>` 建树，并开 `task/<slug>` 分支。"""
    repo = _init_repo(tmp_path)

    result = _run(repo, "create", "demo")

    assert result.returncode == 0, result.stderr
    worktree = repo / ".worktrees" / "demo"
    assert (worktree / "pyproject.toml").is_file(), "工作树应包含基线分支的内容"
    assert _git(repo, "rev-parse", "--verify", "refs/heads/task/demo").strip()
    listed = _git(repo, "worktree", "list", "--porcelain")
    assert str(worktree) in listed
    # 不嵌套：新工作树自己不能再带一个 .worktrees（那是「在泳道里又建泳道」的形状）。
    assert not (worktree / ".worktrees").exists()


def test_create_from_inside_a_task_worktree_uses_the_original_root(tmp_path: Path) -> None:
    """从泳道内再 `create`，落点仍是原始根的 `.worktrees/`——这是 common-dir 的判据。"""
    repo = _init_repo(tmp_path)
    assert _run(repo, "create", "first").returncode == 0
    first = repo / ".worktrees" / "first"

    result = _run(first, "create", "second")

    assert result.returncode == 0, result.stderr
    assert (repo / ".worktrees" / "second").is_dir()
    assert not (first / ".worktrees").exists(), "在泳道内建树不得产生嵌套 .worktrees"


def test_create_rejects_a_slug_whose_branch_already_exists(tmp_path: Path) -> None:
    """分支已存在即拒绝：不覆盖、不强制重置别人的分支。"""
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "task/taken")

    result = _run(repo, "create", "taken")

    assert result.returncode == 1
    assert "已存在" in result.stderr
    assert not (repo / ".worktrees" / "taken").exists()


def test_create_rejects_an_unknown_base_branch(tmp_path: Path) -> None:
    """基线分支不存在即拒绝（避免在错误的基线上开出空分支）。"""
    repo = _init_repo(tmp_path)

    result = _run(repo, "create", "demo", "--base", "no-such-branch")

    assert result.returncode == 1
    assert "no-such-branch" in result.stderr
    assert not (repo / ".worktrees" / "demo").exists()


def test_list_marks_main_and_task_worktrees(tmp_path: Path) -> None:
    """`list` 同时给出原始根、任务工作树与它们的分支。"""
    repo = _init_repo(tmp_path)
    assert _run(repo, "create", "listed").returncode == 0

    result = _run(repo, "list")

    assert result.returncode == 0, result.stderr
    assert f"原始项目根：{repo}" in result.stdout
    assert "主树" in result.stdout
    assert "task/listed" in result.stdout


def test_remove_refuses_a_dirty_worktree_and_leaves_it_in_place(tmp_path: Path) -> None:
    """有未提交改动时拒绝删除，且真的什么都没删。"""
    repo = _init_repo(tmp_path)
    assert _run(repo, "create", "dirty").returncode == 0
    worktree = repo / ".worktrees" / "dirty"
    (worktree / "scratch.txt").write_text("未提交的工作\n", encoding="utf-8")

    result = _run(repo, "remove", "dirty")

    assert result.returncode == 1
    assert "不干净" in result.stderr
    assert (worktree / "scratch.txt").is_file(), "拒绝删除时不得动工作树里的文件"
    assert _git(repo, "rev-parse", "--verify", "refs/heads/task/dirty").strip()


def test_remove_refuses_unmerged_commits_and_leaves_them_reachable(tmp_path: Path) -> None:
    """分支上有未并入基线的提交时拒绝删除（提交不能被悄悄带走）。"""
    repo = _init_repo(tmp_path)
    assert _run(repo, "create", "unmerged").returncode == 0
    worktree = repo / ".worktrees" / "unmerged"
    (worktree / "feature.txt").write_text("只在这条分支上\n", encoding="utf-8")
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-q", "-m", "只在任务分支上的提交")

    result = _run(repo, "remove", "unmerged")

    assert result.returncode == 1
    assert "未并入" in result.stderr
    assert _git(repo, "rev-parse", "--verify", "refs/heads/task/unmerged").strip()
    assert (worktree / "feature.txt").is_file()


def test_remove_deletes_clean_merged_worktree_and_branch(tmp_path: Path) -> None:
    """干净且已并入基线时才删：工作树目录与任务分支都消失。"""
    repo = _init_repo(tmp_path)
    assert _run(repo, "create", "done").returncode == 0
    worktree = repo / ".worktrees" / "done"
    (worktree / "merged.txt").write_text("已合并\n", encoding="utf-8")
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-q", "-m", "任务分支上的提交")
    # 并入基线（dev），模拟「已整合」这一前提。
    _git(repo, "merge", "-q", "--ff-only", "task/done")

    result = _run(repo, "remove", "done")

    assert result.returncode == 0, result.stderr
    assert not worktree.exists()
    assert "task/done" not in _git(repo, "branch", "--list", "task/done")
    assert str(worktree) not in _git(repo, "worktree", "list", "--porcelain")


def test_remove_refuses_an_unregistered_directory(tmp_path: Path) -> None:
    """目录存在但未注册：拒绝，且不删——不明来源的资源一律不动。"""
    repo = _init_repo(tmp_path)
    ghost = repo / ".worktrees" / "ghost"
    ghost.mkdir(parents=True)
    (ghost / "keep.me").write_text("别乱删\n", encoding="utf-8")

    result = _run(repo, "remove", "ghost")

    assert result.returncode == 1
    assert "不是已注册的工作树" in result.stderr
    assert (ghost / "keep.me").is_file()


def test_remove_refuses_a_slug_whose_directory_branch_disagrees(tmp_path: Path) -> None:
    """目录与分支对不上时拒绝：不按 slug 猜着删。"""
    repo = _init_repo(tmp_path)
    assert _run(repo, "create", "mismatch").returncode == 0
    worktree = repo / ".worktrees" / "mismatch"
    _git(worktree, "checkout", "-q", "-b", "scratch-branch")

    result = _run(repo, "remove", "mismatch")

    assert result.returncode == 1
    assert "scratch-branch" in result.stderr
    assert worktree.is_dir()
