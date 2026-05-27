"""Git 薄封装函数。"""

import subprocess
from pathlib import Path
from typing import Optional


def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    """执行 git 命令，统一返回 (returncode, stdout, stderr)。"""
    cmd = ["git", "-C", str(repo)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout, result.stderr


def git_worktree_add(repo: Path, path: Path, base_ref: str, branch: Optional[str] = None) -> tuple[int, str, str]:
    """git -C <repo> worktree add <path> [ -b <branch> ] <base_ref>"""
    cmd = ["worktree", "add"]
    if branch:
        cmd += ["-b", branch]
    cmd += [str(path), base_ref]
    return _git(repo, *cmd)


def git_worktree_remove(repo: Path, path: Path, force: bool = False) -> tuple[int, str, str]:
    """git -C <repo> worktree remove <path> [--force]"""
    cmd = ["worktree", "remove", str(path)]
    if force:
        cmd.append("--force")
    return _git(repo, *cmd)


def git_worktree_list(repo_root: Path) -> tuple[int, str, str]:
    """git worktree list --porcelain"""
    return _git(repo_root, "worktree", "list", "--porcelain")


def git_fetch(repo: Path, source: Path, refspec: str) -> tuple[int, str, str]:
    """git -C <repo> fetch <source> <refspec>"""
    return _git(repo, "fetch", str(source), refspec)


def git_merge(repo: Path, ref: str, no_ff: bool = True) -> tuple[int, str, str]:
    """git -C <repo> merge <ref> [--no-ff]"""
    cmd = ["merge", ref]
    if no_ff:
        cmd.append("--no-ff")
    return _git(repo, *cmd)


def git_checkout(repo: Path, ref: str) -> tuple[int, str, str]:
    """git -C <repo> checkout <ref>"""
    return _git(repo, "checkout", ref)


def git_tag(repo: Path, tag_name: str, ref: str = "HEAD") -> tuple[int, str, str]:
    """git -C <repo> tag <tag_name> <ref>"""
    return _git(repo, "tag", tag_name, ref)


def git_tag_delete(repo: Path, tag_name: str) -> tuple[int, str, str]:
    """git -C <repo> tag -d <tag_name>"""
    return _git(repo, "tag", "-d", tag_name)


def git_tag_exists(repo: Path, tag_name: str) -> bool:
    """检查 tag 是否存在。"""
    rc, stdout, _ = _git(repo, "tag", "-l", tag_name)
    if rc != 0:
        return False
    return stdout.strip() == tag_name


def git_status_porcelain(repo: Path) -> tuple[int, str, str]:
    """git -C <repo> status --porcelain"""
    return _git(repo, "-c", "core.quotePath=false", "status", "--porcelain")


def git_merge_base(repo: Path, ref_a: str, ref_b: str) -> tuple[int, str, str]:
    """git -C <repo> merge-base <ref_a> <ref_b>"""
    return _git(repo, "merge-base", ref_a, ref_b)


def git_worktree_prune(repo: Path) -> tuple[int, str, str]:
    """git -C <repo> worktree prune"""
    return _git(repo, "worktree", "prune")


def git_rev_parse(repo: Path, ref: str) -> tuple[int, str, str]:
    """git -C <repo> rev-parse <ref>"""
    return _git(repo, "rev-parse", ref)


def git_add_all(repo: Path) -> tuple[int, str, str]:
    """git -C <repo> add -A"""
    return _git(repo, "add", "-A")


def git_commit(repo: Path, message: str, allow_empty: bool = False) -> tuple[int, str, str]:
    """git -C <repo> commit -m <message> [--allow-empty]"""
    args = ["commit", "-m", message]
    if allow_empty:
        args.insert(1, "--allow-empty")
    return _git(repo, *args)


def git_commit_file(repo: Path, message_file: Path, allow_empty: bool = False) -> tuple[int, str, str]:
    """git -C <repo> commit -F <message_file> [--allow-empty]"""
    args = ["commit", "-F", str(message_file)]
    if allow_empty:
        args.insert(1, "--allow-empty")
    return _git(repo, *args)


def git_merge_abort(repo: Path) -> tuple[int, str, str]:
    """git -C <repo> merge --abort"""
    return _git(repo, "merge", "--abort")


def git_branch(repo: Path, branch_name: str, ref: str = "HEAD") -> tuple[int, str, str]:
    """git -C <repo> branch <branch_name> <ref>"""
    return _git(repo, "branch", branch_name, ref)
