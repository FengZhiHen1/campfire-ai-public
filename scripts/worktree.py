"""任务工作树管理：`create` / `list` / `remove`。

为什么要有这个脚本（而不是每次手敲 `git worktree add`）：

并行任务各自在独立工作树里改代码，手敲命令会在两处反复出错——落点与清理。

1. **落点**：工作树必须落在**原始项目根**的 `.worktrees/<slug>/`，不能落在当前目录
   （在某个泳道里再建泳道会得到 `.worktrees/<a>/.worktrees/<b>` 这种嵌套树，
   它既不在忽略规则覆盖的深度上，也让「哪个是原始根」变得不可判定）。
   本脚本用 `git rev-parse --git-common-dir` 反推原始根：工作树与主树共用一个
   common dir，因此无论从哪个泳道调用，落点都回到同一个 `.worktrees/`。
2. **清理**：删工作树是**破坏性**动作（里面有别人未提交的改动时尤其如此）。本脚本
   只删「已注册 + 干净 + 分支已并入基线」的工作树，且只用 `git worktree remove`
   （不带 `--force`）——不用 `rm -rf`，也不碰任何未注册的目录。

用法：

    uv run python scripts/worktree.py create <slug> [--base dev]
    uv run python scripts/worktree.py list
    uv run python scripts/worktree.py remove <slug> [--base dev]

`create` 只建树、不装依赖：每个工作树要有**自己**的 `.venv`
（`cd .worktrees/<slug> && uv sync --frozen`），不共享主树的虚拟环境。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: slug 的合法形状：小写字母/数字开头，其余为小写字母、数字与连字符。
#:
#: 刻意不允许 `/`：分支名里允许，但 slug 直接拼进目录名，带斜杠就会在
#: `.worktrees/` 下造出嵌套目录，把「一个泳道一个目录」的对应关系弄乱。
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: 任务分支前缀：每任务独立分支，便于 `git log task/x` 与合并判据。
BRANCH_PREFIX = "task/"

#: 工作树落点目录名（原始项目根之下；`/.worktrees/` 已在 `.gitignore` 里忽略）。
WORKTREES_DIRNAME = ".worktrees"


class WorktreeError(RuntimeError):
    """工作树操作被拒绝或失败：消息即给使用者看的原因。"""


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """跑一条 git 命令并返回结果。

    Args:
        *args: 传给 git 的参数（不含 `git` 本身）。
        cwd: 在哪运行；`None` 表示当前目录。
        check: 非零退出码时是否抛 :class:`WorktreeError`。

    Returns:
        完成的进程结果（text 模式）。

    Raises:
        WorktreeError: `check` 为真且 git 返回非零。
    """
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise WorktreeError(f"git {' '.join(args)} 失败：{detail}")
    return proc


def _try_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """跑一条允许失败的 git 命令（用于「存在吗」这类探测）。"""
    return _git(*args, cwd=cwd, check=False)


def repo_root() -> Path:
    """返回**原始项目根**（主工作树所在目录）。

    判据是 `git rev-parse --git-common-dir`：主树与所有工作树共用同一个 common dir
    （主树里是 `<root>/.git`，工作树里指向 `<root>/.git` 的绝对路径）。
    因此从任意泳道调用都得到同一个根——这正是「不嵌套 `.worktrees`」的实现方式。

    Raises:
        WorktreeError: 不在 git 仓库内，或布局不是「主树 + common dir = <root>/.git」
            （例如裸仓库、`git init --separate-git-dir`：这些布局里「原始根」没有
            唯一答案，猜一个只会造出第二个落点）。
    """
    proc = _try_git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if proc.returncode != 0:
        raise WorktreeError("当前目录不在 git 仓库内（git rev-parse --git-common-dir 失败）")
    common_dir = Path(proc.stdout.strip())
    if common_dir.name != ".git":
        raise WorktreeError(
            f"无法识别原始项目根：git common dir 是 {common_dir}，"
            "期望形如 <root>/.git 的布局（裸仓库或 --separate-git-dir 布局不支持）"
        )
    root = common_dir.parent
    if not (root / "pyproject.toml").is_file():
        raise WorktreeError(f"原始项目根 {root} 下没有 pyproject.toml——这不是本仓库的根目录")
    return root


def worktrees_dir(root: Path) -> Path:
    """任务工作树的落点：`<原始根>/.worktrees`。"""
    return root / WORKTREES_DIRNAME


def branch_for(slug: str) -> str:
    """slug → 任务分支名。"""
    return f"{BRANCH_PREFIX}{slug}"


def validate_slug(slug: str) -> None:
    """校验 slug 形状；不合法即抛，不做「帮你改一下」的猜测。

    Raises:
        WorktreeError: slug 为空、含路径分隔符或其它非法字符。
    """
    if not SLUG_PATTERN.match(slug):
        raise WorktreeError(
            f"slug 不合法：{slug!r}——只允许小写字母、数字与连字符，且以字母或数字开头"
            "（不允许 `/`：slug 会直接作为目录名）"
        )


def _ref_exists(root: Path, ref: str) -> bool:
    """该引用是否存在（`refs/heads/<name>` 或完整 ref）。"""
    return _try_git("rev-parse", "--verify", "--quiet", ref, cwd=root).returncode == 0


@dataclass(frozen=True)
class RegisteredWorktree:
    """`git worktree list --porcelain` 的一条记录。"""

    path: Path
    head: str
    branch: str | None
    prunable: bool = False


def registered_worktrees(root: Path) -> list[RegisteredWorktree]:
    """解析 `git worktree list --porcelain`，返回全部已注册工作树（主树在首位）。"""
    out = _git("worktree", "list", "--porcelain", cwd=root).stdout
    worktrees: list[RegisteredWorktree] = []
    path: Path | None = None
    head = ""
    branch: str | None = None
    prunable = False
    for line in [*out.splitlines(), ""]:
        if not line.strip():
            if path is not None:
                worktrees.append(RegisteredWorktree(path=path, head=head, branch=branch, prunable=prunable))
            path, head, branch, prunable = None, "", None, False
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            path = Path(value)
        elif key == "HEAD":
            head = value
        elif key == "branch":
            branch = value.removeprefix("refs/heads/")
        elif key == "prunable":
            prunable = True
    return worktrees


def _find(root: Path, path: Path) -> RegisteredWorktree | None:
    """在注册表里按路径找工作树。"""
    resolved = path.resolve()
    for item in registered_worktrees(root):
        if item.path.resolve() == resolved:
            return item
    return None


def create(slug: str, base: str) -> int:
    """新建任务工作树与分支。

    Args:
        slug: 任务短名（用作目录名与分支名后缀）。
        base: 基线分支（默认 `dev`）。

    Returns:
        进程退出码：0 成功。

    Raises:
        WorktreeError: slug/分支/目录冲突，或基线分支不存在。
    """
    validate_slug(slug)
    root = repo_root()
    path = worktrees_dir(root) / slug
    branch = branch_for(slug)

    if not _ref_exists(root, f"refs/heads/{base}"):
        raise WorktreeError(
            f"基线分支 {base} 不存在（本仓库习惯：日常开发在 dev）——先 git fetch origin {base} 或换 --base"
        )
    if _ref_exists(root, f"refs/heads/{branch}"):
        raise WorktreeError(f"分支 {branch} 已存在——slug 已被占用；换一个 slug，或先处理该分支")
    if _find(root, path) is not None:
        raise WorktreeError(f"{path} 已是注册的工作树——slug 已被占用，换一个 slug")
    if path.exists():
        raise WorktreeError(f"{path} 已存在但不是注册的工作树——本脚本不会清理来源不明的目录，请人工确认")

    path.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--quiet", str(path), "-b", branch, base, cwd=root)
    print(f"已创建工作树 {path}")
    print(f"  分支：{branch}（基线 {base}）")
    print("下一步（每个工作树用**自己的**虚拟环境，不要共享主树 .venv）：")
    print(f"  cd {path} && uv sync --frozen")
    return 0


def list_worktrees() -> int:
    """列出全部工作树，标注原始根与本仓任务工作树。"""
    root = repo_root()
    base_dir = worktrees_dir(root)
    items = registered_worktrees(root)
    if not items:
        print("没有任何已注册的工作树")
        return 0
    print(f"原始项目根：{root}")
    for index, item in enumerate(items):
        role = "主树" if index == 0 else ("任务工作树" if _is_under(item.path, base_dir) else "外部工作树")
        branch = item.branch or "（detached）"
        suffix = "  [prunable：目录已不在，可 git worktree prune]" if item.prunable else ""
        print(f"  {item.path}  {branch}  {item.head[:12]}  [{role}]{suffix}")
    return 0


def _is_under(path: Path, parent: Path) -> bool:
    """path 是否位于 parent 之下（都解析为绝对路径后比较）。"""
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _assert_clean(path: Path) -> None:
    """工作树必须干净（含未跟踪文件）：有东西就不删。

    Raises:
        WorktreeError: 有已修改/未跟踪文件，消息里逐条列出。
    """
    out = _git("status", "--porcelain=v1", "--untracked-files=all", cwd=path).stdout
    lines = [line for line in out.splitlines() if line.strip()]
    if lines:
        preview = "\n  ".join(lines[:20])
        more = f"\n  …（共 {len(lines)} 条）" if len(lines) > 20 else ""
        raise WorktreeError(
            f"{path} 不干净，拒绝删除（不代你丢弃改动——先提交、stash，或自行确认后删）：\n  {preview}{more}"
        )


def _assert_merged(root: Path, branch: str, base: str) -> None:
    """分支的提交必须都已并入基线，否则拒绝删除。

    Raises:
        WorktreeError: 有未并入基线的提交，消息里列出它们。
    """
    if _try_git("merge-base", "--is-ancestor", branch, f"refs/heads/{base}", cwd=root).returncode != 0:
        unmerged = _git("log", "--oneline", f"refs/heads/{base}..{branch}", cwd=root).stdout.strip()
        raise WorktreeError(
            f"分支 {branch} 有未并入 {base} 的提交，拒绝删除：\n  "
            + "\n  ".join(unmerged.splitlines() or ["（无法列出，请手动检查 git log）"])
        )


def remove(slug: str, base: str) -> int:
    """删除任务工作树与分支（只删「已注册 + 干净 + 已并入基线」的）。

    Args:
        slug: 任务短名。
        base: 整合基线（默认 `dev`）：分支提交必须都已进入它。

    Returns:
        进程退出码：0 成功。

    Raises:
        WorktreeError: 目录不是注册工作树、工作树不干净、分支未并入基线、
            或它是主树（一律拒绝，不做 `--force`）。
    """
    validate_slug(slug)
    root = repo_root()
    path = worktrees_dir(root) / slug
    branch = branch_for(slug)

    if not _ref_exists(root, f"refs/heads/{base}"):
        raise WorktreeError(f"整合基线 {base} 不存在——先确认要拿哪条分支判定「已整合」")

    items = registered_worktrees(root)
    registered = _find(root, path)
    if registered is None:
        hint = f"（目录存在但未注册，本脚本不清理来源不明的目录：{path}）" if path.exists() else ""
        raise WorktreeError(f"{path} 不是已注册的工作树{hint}")
    if items and registered.path.resolve() == items[0].path.resolve():
        raise WorktreeError("拒绝删除主工作树")

    _assert_clean(path)
    if registered.branch is None:
        raise WorktreeError(f"{path} 处于 detached 状态（没有分支），拒绝删除")
    if registered.branch != branch:
        raise WorktreeError(
            f"{path} 当前分支是 {registered.branch}，不是预期的 {branch}——"
            "目录与分支的对应关系不符，拒绝按 slug 推断删除"
        )
    _assert_merged(root, branch, base)

    # 只用 git 自己的删除动作（不带 --force）：它会再做一次安全检查，
    # 也把注册表一并更新，不留悬挂条目。
    _git("worktree", "remove", str(path), cwd=root)
    deleted = _try_git("branch", "-d", branch, cwd=root)
    if deleted.returncode != 0:
        print(
            f"工作树已删除，但分支 {branch} 未删除（git branch -d 拒绝）：{(deleted.stderr or deleted.stdout).strip()}",
            file=sys.stderr,
        )
        print("分支保留无副作用；确认后可自行 git branch -D 清理。", file=sys.stderr)
        return 0
    print(f"已删除工作树 {path} 与分支 {branch}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器（子命令见模块 docstring）。"""
    parser = argparse.ArgumentParser(
        prog="worktree.py",
        description="任务工作树管理：在原始项目根的 .worktrees/<slug>/ 下建每任务独立分支的工作树。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_cmd = sub.add_parser("create", help="新建任务工作树与分支 task/<slug>")
    create_cmd.add_argument("slug", help="任务短名（小写字母、数字、连字符；用作目录名与分支名后缀）")
    create_cmd.add_argument("--base", default="dev", help="基线分支（默认 dev）")

    sub.add_parser("list", help="列出全部工作树（标注原始根与本仓任务工作树）")

    remove_cmd = sub.add_parser("remove", help="删除任务工作树与分支（要求干净且已并入基线）")
    remove_cmd.add_argument("slug", help="任务短名")
    remove_cmd.add_argument("--base", default="dev", help="整合基线（默认 dev）：提交必须都已进入它")
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口；返回进程退出码（0 成功，1 被拒绝或失败）。"""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            return create(args.slug, args.base)
        if args.command == "list":
            return list_worktrees()
        return remove(args.slug, args.base)
    except WorktreeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
