"""运维脚本（`scripts/*.sh`）的可执行判据：语法、`--help` 契约、演练不动手、失败要能失败。

为什么需要这组用例：这些脚本是**在压力下使用的破坏性工具**（恢复、回滚），而它们此前
只有注释里的「实测过」。注释不会在下次改动时变红，下面几条会：

1. **演练模式不得碰 docker**：`restore.sh` 不加 `--yes` 时只打印计划。这一条用一个
   假 `docker`（被调用就写日志）来判定——「输出里没出现 docker 命令」不等于「没执行」。
2. **取不到路径时必须失败**：`redis-cli` 未认证时退出码仍是 0、输出是
   `NOAUTH Authentication required.`。此前 `restore.sh` 只判「输出非空」，于是那行
   错误文本被当成目录名，RDB 被写到不存在的路径，脚本仍打印「完成并已重启」并返回 0
   ——**数据没恢复，而验收看到的是成功**。这里用假 docker 把它钉成红灯。
3. **正常路径不能永远失败**：同一条判据在健康输出下必须放行（正向对照）。没有它，
   「永远失败」和「永远通过」在结果上长得一样。

全部用例只跑 shell 与假 `docker`：不连库、不碰容器、不改真实数据。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

#: 假 `docker`：把每次调用写进 `$STUB_LOG`，并按 `$STUB_*` 返回预设输出。
#:
#: 刻意实现「容器已停时 `compose exec` 失败」——`restore.sh` 的回落分支
#: （`compose run` 写卷）只有在 exec 真的失败时才走得到，不模拟它就等于没测那条分支。
STUB_DOCKER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  *"PING"*) printf '%s\\n' "${STUB_PING:-PONG}"; exit 0 ;;
esac
case "$*" in
  *exec*)
    if [ -f "$STUB_STATE/stopped" ]; then echo "service is not running" >&2; exit 1; fi
    ;;
esac
case "$*" in
  *"CONFIG GET dir"*) printf '%s\\n' "${STUB_DIR:-/data}"; exit 0 ;;
  *"CONFIG GET dbfilename"*) printf '%s\\n' "${STUB_FILE:-dump.rdb}"; exit 0 ;;
esac
case "$*" in
  *" stop "*) : > "$STUB_STATE/stopped"; exit 0 ;;
  *" start "*) command rm -f "$STUB_STATE/stopped"; exit 0 ;;
  *" run "*) command cat > /dev/null; exit 0 ;;
esac
exit 0
"""


def _base_env(tmp_path: Path) -> dict[str, str]:
    """基础环境：只带 PATH 与 locale，避免宿主机导出的变量把判据变成「看环境」。"""
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "STUB_LOG": str(tmp_path / "docker-calls.log"),
        "STUB_STATE": str(tmp_path / "docker-state"),
    }


def _install_stub(tmp_path: Path) -> Path:
    """把假 `docker` 放进临时 bin 目录，并建好它的状态目录。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(STUB_DOCKER, encoding="utf-8")
    stub.chmod(0o755)
    (tmp_path / "docker-state").mkdir()
    return bin_dir


def _env_with_stub(tmp_path: Path) -> dict[str, str]:
    """基础环境 + 假 docker 在 PATH 首位。"""
    env = _base_env(tmp_path)
    env["PATH"] = f"{_install_stub(tmp_path)}:{env['PATH']}"
    return env


def _run_script(script: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """跑一个仓库脚本（显式给 `bash`，不依赖文件的可执行位）。"""
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def _backup_dir(tmp_path: Path, *, falkordb: bool = True, redis: bool = False) -> Path:
    """造一个最小「备份目录」：`restore.sh` 只按文件是否存在决定要不要恢复。"""
    directory = tmp_path / "backup"
    directory.mkdir()
    (directory / "postgres.dump").write_bytes(b"PGDUMP")
    if falkordb:
        (directory / "falkordb-dump.rdb").write_bytes(b"FALKOR-RDB")
    if redis:
        (directory / "redis-dump.rdb").write_bytes(b"REDIS-RDB")
    return directory


@pytest.mark.parametrize("script", sorted(path.name for path in SCRIPTS.glob("*.sh")))
def test_shell_script_parses(script: str) -> None:
    """每个 shell 脚本都必须能过 `bash -n`（语法错误在真机上就是一次失败的操作）。"""
    proc = subprocess.run(["bash", "-n", str(SCRIPTS / script)], text=True, capture_output=True)

    assert proc.returncode == 0, f"{script} 语法错误：{proc.stderr.strip()}"


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh", "rollback.sh"])
def test_help_prints_usage_and_exits_zero(script: str, tmp_path: Path) -> None:
    """`--help` 是这三个脚本唯一的文档入口，必须可执行、可读、退出码 0。"""
    proc = _run_script(script, "--help", env=_env_with_stub(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert "用法" in proc.stdout


def test_restore_rehearsal_does_not_call_docker(tmp_path: Path) -> None:
    """不加 `--yes` 时只打印计划：**一个 docker 命令都不能发出**（破坏性操作的默认值）。"""
    env = _env_with_stub(tmp_path)
    backup = _backup_dir(tmp_path)

    proc = _run_script("restore.sh", "--from", str(backup), env=env)

    assert proc.returncode == 0, proc.stderr
    assert "演练模式" in proc.stdout
    assert not (tmp_path / "docker-calls.log").exists(), "演练模式不得调用 docker"


@pytest.mark.parametrize(
    ("only", "expected_line", "unexpected_lines"),
    [
        ("postgres", "恢复 PostgreSQL", ["恢复 FalkorDB", "恢复 Redis"]),
        ("falkordb", "恢复 FalkorDB", ["恢复 PostgreSQL", "恢复 Redis"]),
        ("redis", "恢复 Redis", ["恢复 PostgreSQL", "恢复 FalkorDB"]),
    ],
)
def test_restore_rehearsal_honours_only(
    only: str, expected_line: str, unexpected_lines: list[str], tmp_path: Path
) -> None:
    """`--only` 必须真的收窄计划。

    这不是形式检查：计划里多列一项，执行时就会真的多恢复一份数据——而 `--only`
    存在的理由正是「只把坏掉的那一项写回去」。
    """
    env = _env_with_stub(tmp_path)
    backup = _backup_dir(tmp_path, falkordb=True, redis=True)

    proc = _run_script("restore.sh", "--from", str(backup), "--only", only, env=env)

    assert proc.returncode == 0, proc.stderr
    assert expected_line in proc.stdout
    for line in unexpected_lines:
        assert line not in proc.stdout, f"--only {only} 不应计划 {line}"


@pytest.mark.parametrize("service", ["falkordb", "redis"])
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"STUB_PING": "NOAUTH Authentication required."}, "PING"),
        ({"STUB_DIR": "NOAUTH Authentication required."}, "CONFIG GET dir"),
    ],
    ids=["ping-unauthenticated", "config-get-unauthenticated"],
)
def test_restore_fails_loudly_when_redis_cli_is_unauthenticated(
    service: str, overrides: dict[str, str], expected: str, tmp_path: Path
) -> None:
    """未认证时 `redis-cli` 打印 NOAUTH 但退出码为 0 —— `restore.sh` 必须因此失败。

    修复前的形状（写在这里是为了让回归有名字）：只判「输出非空」，于是
    `NOAUTH Authentication required.` 被当成目录名拼进
    `cat > 'NOAUTH Authentication required./dump.rdb'`，脚本随后打印「完成并已重启」
    并返回 0——**数据没有恢复，而退出码说成功**（已用假 docker 复现过这条输出）。

    两道闸各自都要有用例：`PING` 的那道在**停容器之前**拦住，`CONFIG GET` 的那道
    拦住「PING 通了但取路径时认证已失效」这一种（例如密码在两次调用之间变了）。

    还要求 `stop` 没被调用过：认证都过不去，就不该先把服务停下来。
    """
    env = _env_with_stub(tmp_path)
    env.update(overrides)
    backup = _backup_dir(tmp_path, falkordb=True, redis=True)

    proc = _run_script("restore.sh", "--from", str(backup), "--yes", "--only", service, env=env)

    assert proc.returncode != 0, "取不到持久化路径时必须失败，不能打印成功"
    assert expected in proc.stderr
    calls = (tmp_path / "docker-calls.log").read_text(encoding="utf-8")
    assert " stop " not in calls, "认证失败时不得先停容器"
    assert "cat >" not in calls, "认证失败时不得尝试写文件"


@pytest.mark.parametrize("service", ["falkordb", "redis"])
def test_restore_writes_snapshot_when_auth_is_configured(service: str, tmp_path: Path) -> None:
    """正向对照：环境正常时同一段代码必须真的写回 RDB，并且**带上了密码**。

    没有这条用例，「永远失败」也会让上一条保持绿色。
    """
    env = _env_with_stub(tmp_path)
    backup = _backup_dir(tmp_path, falkordb=True, redis=True)
    env_file = tmp_path / "stub.env"
    variable = "FALKORDB_PASSWORD" if service == "falkordb" else "REDIS_PASSWORD"
    env_file.write_text(f"{variable}=stub-secret\n", encoding="utf-8")

    proc = _run_script(
        "restore.sh",
        "--from",
        str(backup),
        "--yes",
        "--only",
        service,
        "--env-file",
        str(env_file),
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    calls = (tmp_path / "docker-calls.log").read_text(encoding="utf-8")
    assert "-a stub-secret" in calls, "必须把 env 文件里的密码传给 redis-cli"
    assert "cat > '/data/dump.rdb'" in calls
    assert " start " in calls, "写完必须把服务重新拉起来"


def test_restore_refuses_missing_backup_directory(tmp_path: Path) -> None:
    """备份目录不存在即拒绝（不给 `docker` 任何被执行的机会）。"""
    env = _env_with_stub(tmp_path)

    proc = _run_script("restore.sh", "--from", str(tmp_path / "nope"), "--yes", env=env)

    assert proc.returncode == 1
    assert "备份目录不存在" in proc.stderr
    assert not (tmp_path / "docker-calls.log").exists()


def test_backup_requires_an_explicit_out_dir(tmp_path: Path) -> None:
    """`--out-dir` 没有默认值：产物写哪里是运维决策，脚本不猜。"""
    env = _env_with_stub(tmp_path)

    proc = _run_script("backup.sh", env=env)

    assert proc.returncode == 1
    assert "--out-dir" in proc.stderr
    assert not (tmp_path / "docker-calls.log").exists(), "参数不全时不得开始备份"


def test_bash_is_available() -> None:
    """前置：上面的用例都依赖 `bash`；缺它时红要归因到环境，而不是脚本缺陷。"""
    assert shutil.which("bash") is not None
