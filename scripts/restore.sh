#!/usr/bin/env bash
#
# 恢复：把 `scripts/backup.sh` 的产物写回 PostgreSQL、FalkorDB 与 Redis。
#
# 用法：
#   scripts/restore.sh --help
#   scripts/restore.sh --from ./backups/20261001T085613Z --yes
#   scripts/restore.sh --from <目录> --only postgres --yes
#
# ## ⚠️ 这是破坏性操作
#
# 它会**覆盖目标库的现有数据**。因此：
#
# 1. **必须显式给 `--yes`**。没有它，脚本只打印「将要做什么」然后退出——破坏性操作
#    不得默认执行。这是本脚本存在的最重要的一条纪律。
# 2. 恢复 PostgreSQL 前会提示先停应用容器（应用在跑时的并发写入会与恢复打架）。
#    脚本不自动停——停服务是运维决策，且本脚本不该悄悄改变运行状态。
# 3. 恢复前**校验 SHA256SUMS**：备份可能已经损坏（介质问题），拿损坏的备份覆盖
#    仅存的可用数据是最坏的结果。校验不通过即中止。
#
# ## 恢复顺序
#
# Postgres → FalkorDB → Redis。数据库在前，因为图库与队列的数据都引用它（例如
# `pending_write.id` 派生出图库侧的 episode 标识）——先恢复引用方会让一致性判断失去依据。
#
# ## 恢复之后必须做的一件事
#
# 跑 `alembic upgrade head`。备份来自旧版本的 schema，而代码是新版本的；不迁移就启动
# 会得到「表存在但列不全」的一类错误。脚本会在最后提示，但不自动执行——迁移是发布动作，
# 由 docs/运维/发布与回滚.md 的流程管。

set -euo pipefail

FROM_DIR=""
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=""
PROJECT_NAME=""
ONLY=""
ASSUME_YES="0"

usage() {
    cat <<'EOF'
用法：restore.sh --from <备份目录> [选项]

必需：
  --from <目录>             backup.sh 产出的目录（含 postgres.dump / SHA256SUMS）

可选：
  --only <postgres|falkordb|redis>
                            只恢复其中一项（默认全部）
  --compose-file <文件>     compose 文件（默认 docker-compose.yml）
  --env-file <文件>         compose 环境变量文件（生产用 .env.prod）
  --project-name <名>       compose 项目名
  --yes                     确认执行（**不加即为演练**：只打印将做什么）
  -h, --help                显示本说明

⚠️ 会覆盖目标库现有数据。先读脚本顶部的说明。
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --from)         FROM_DIR="${2:-}"; shift 2 ;;
        --only)         ONLY="${2:-}"; shift 2 ;;
        --compose-file) COMPOSE_FILE="${2:-}"; shift 2 ;;
        --env-file)     ENV_FILE="${2:-}"; shift 2 ;;
        --project-name) PROJECT_NAME="${2:-}"; shift 2 ;;
        --yes)          ASSUME_YES="1"; shift ;;
        -h|--help)      usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 1 ;;
    esac
done

if [ -z "$FROM_DIR" ]; then
    echo "错误：必须给 --from <备份目录>" >&2
    usage >&2
    exit 1
fi
if [ ! -d "$FROM_DIR" ]; then
    echo "错误：备份目录不存在：$FROM_DIR" >&2
    exit 1
fi
case "$ONLY" in
    ""|postgres|falkordb|redis) ;;
    *) echo "错误：--only 只能是 postgres / falkordb / redis，收到：$ONLY" >&2; exit 1 ;;
esac

compose() {
    # shellcheck disable=SC2086
    docker compose -f "$COMPOSE_FILE" ${ENV_FILE:+"--env-file" "$ENV_FILE"} ${PROJECT_NAME:+"--project-name" "$PROJECT_NAME"} "$@"
}

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "错误：找不到 compose 文件 $COMPOSE_FILE" >&2
    exit 1
fi

# 把 env 文件里的密码读进**本脚本自己的环境**（与 `backup.sh` 同一处置）。
#
# ⚠️ `--env-file` 只喂给 `docker compose`，**不会**导出到脚本进程。生产编排里
# FalkorDB 与 Redis 都要求密码（`--requirepass`），不把密码传给 `redis-cli` 时的
# 表现极其隐蔽（`backup.sh` 头部记的是同一条实测）：
#
#   `CONFIG GET dir` 打印 `NOAUTH Authentication required.`，而 **退出码仍是 0**。
#
# 于是那行错误文本会被当成「目录」写进 `cat > 'NOAUTH …/dump.rdb'`，脚本继续
# 「完成并已重启」并返回 0 —— 数据根本没有恢复，而验收看到的是一次成功。
# 这里先把密码准备好，再用下面 `read_config_value` 校验**输出**（而不是退出码）。
if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE" 2>/dev/null || true
    set +a
fi

# --- 校验和（在动任何数据之前）------------------------------------------

echo "备份目录：$FROM_DIR"
if [ -f "$FROM_DIR/SHA256SUMS" ]; then
    echo
    echo "校验产物完整性"
    if command -v sha256sum > /dev/null 2>&1; then
        ( cd "$FROM_DIR" && sha256sum -c SHA256SUMS )
    else
        ( cd "$FROM_DIR" && shasum -a 256 -c SHA256SUMS )
    fi
    echo "校验通过"
else
    # 没有校验和文件的备份**不是可靠备份**，但可能是手工准备的。
    # 这里要求显式确认而不是直接放行。
    echo "警告：备份目录里没有 SHA256SUMS，无法校验完整性。" >&2
    if [ "$ASSUME_YES" != "1" ]; then
        echo "（演练模式：继续会要求 --yes）" >&2
    fi
fi

# --- 演练模式 -----------------------------------------------------------

if [ "$ASSUME_YES" != "1" ]; then
    echo
    echo "=== 演练模式（未加 --yes）==="
    echo "将要执行（**尚未执行任何操作**）："
    [ "$ONLY" = "" ] || [ "$ONLY" = "postgres" ] && echo "  1. 恢复 PostgreSQL：$FROM_DIR/postgres.dump"
    [ "$ONLY" = "" ] || [ "$ONLY" = "falkordb" ] && echo "  2. 恢复 FalkorDB：$FROM_DIR/falkordb-dump.rdb"
    [ "$ONLY" = "" ] || [ "$ONLY" = "redis" ] && echo "  3. 恢复 Redis：$FROM_DIR/redis-dump.rdb"
    echo
    echo "⚠️ 这会**覆盖目标库现有数据**。"
    echo "   确认后重跑并加 --yes。"
    echo
    echo "建议先做的事："
    echo "  - 停掉 api 与 worker 容器（并发写入会与恢复打架）"
    echo "  - 对目标库当前状态再做一次 scripts/backup.sh（回滚点）"
    exit 0
fi

echo
echo "=== 执行恢复（--yes 已给）==="

# --- 带密码的 redis-cli 与「按输出判据」的取值工具 ------------------------

# FalkorDB 是 Redis 分支：生产用 `FALKORDB_PASSWORD`，dev（无密码）走裸调用。
falkor_cli() {
    if [ -n "${FALKORDB_PASSWORD:-}" ]; then
        compose exec -T falkordb redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning "$@"
    elif [ -n "${REDIS_PASSWORD:-}" ]; then
        compose exec -T falkordb redis-cli -a "$REDIS_PASSWORD" --no-auth-warning "$@"
    else
        compose exec -T falkordb redis-cli "$@"
    fi
}

redis_cli() {
    if [ -n "${REDIS_PASSWORD:-}" ]; then
        compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning "$@"
    else
        compose exec -T redis redis-cli "$@"
    fi
}

# 取一个「可以安全拼进容器内路径」的配置值。
#
# 判的是**输出内容**而不是退出码（理由见脚本上方读 env 文件的说明）：认证失败时
# `redis-cli` 退出码为 0，`NOAUTH …` 那段文本会一路被当成目录名使用。
#
# Args: $1 标签（用于报错），$2 原始输出
read_config_value() {
    _label="$1"
    _raw="$2"
    _value="$(printf '%s' "$_raw" | tr -d '\r' | awk 'NF{print; exit}')"
    case "$_value" in
        ""|*[[:space:]]*|NOAUTH*|ERR*|AUTH*|Warning*)
            echo "错误：取不到 $_label（实际输出：${_value:-（空）}）。" >&2
            echo "      常见原因：密码没有传给 redis-cli，或容器未运行。" >&2
            echo "      注意 redis-cli 未认证时退出码为 0，所以这里判的是**输出**。" >&2
            return 1 ;;
    esac
    printf '%s' "$_value"
}

# 探一次 PING：**在停容器之前**确认认证可用，避免把服务停下来却写不回去。
preflight_ping() {
    _label="$1"
    _out="$2"
    if [ "$_out" != "PONG" ]; then
        echo "错误：$_label PING 未返回 PONG（实际：${_out:-（空）}）。" >&2
        echo "      未做任何修改——先修好凭据再恢复，不要在半认证状态下动数据。" >&2
        exit 2
    fi
}

# --- PostgreSQL ---------------------------------------------------------

if [ "$ONLY" = "" ] || [ "$ONLY" = "postgres" ]; then
    if [ ! -f "$FROM_DIR/postgres.dump" ]; then
        echo "错误：缺少 $FROM_DIR/postgres.dump" >&2
        exit 1
    fi
    echo "[1/3] PostgreSQL：pg_restore"

    # `--clean --if-exists`：先删同名对象再建，得到与备份一致的状态（而不是叠加）。
    # `--no-owner --no-privileges`：与备份侧对称——目标机的角色名可能与源不同。
    # 不用 `--create`：库已存在（由 compose 的 POSTGRES_DB 建），重建库会丢掉权限设置。
    #
    # `--single-transaction`：让整次恢复要么全成要么全不成。对 PostgreSQL 有效，
    # 且避免留下「恢复了一半」的库——那比失败更难收拾。
    #
    # `pg_restore` 对 `--clean` 时「对象不存在」的情况会返回非零。加 `--if-exists`
    # 已处理大部分；仍可能有告警级输出，故容忍退出码 0 与 1（1 是「有警告」）。
    set +e
    compose exec -T postgres sh -c \
        'pg_restore -U "${POSTGRES_USER:-campfire}" -d "${POSTGRES_DB:-campfire}" \
         --clean --if-exists --no-owner --no-privileges --single-transaction' \
        < "$FROM_DIR/postgres.dump"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
        echo "错误：pg_restore 失败（退出码 $rc）" >&2
        exit 2
    fi
    echo "      完成（pg_restore 退出码 $rc，1 表示仅告警）"
fi

# --- FalkorDB -----------------------------------------------------------

if [ "$ONLY" = "" ] || [ "$ONLY" = "falkordb" ]; then
    if [ ! -f "$FROM_DIR/falkordb-dump.rdb" ]; then
        echo "警告：缺少 $FROM_DIR/falkordb-dump.rdb，跳过 FalkorDB" >&2
    else
        echo "[2/3] FalkorDB：写入 RDB 并重启"
        preflight_ping FalkorDB "$(falkor_cli PING 2>&1 | tr -d '\r' | tail -n 1)"
        # 路径问 Redis 自己（与 backup.sh 同一理由：FalkorDB 镜像用
        # /var/lib/falkordb/data 而不是 Redis 惯用的 /data）。
        fdir="$(read_config_value "FalkorDB 的 CONFIG GET dir" "$(falkor_cli CONFIG GET dir)")" || exit 2
        ffile="$(read_config_value "FalkorDB 的 CONFIG GET dbfilename" "$(falkor_cli CONFIG GET dbfilename)")" || exit 2
        # RDB 只在进程启动时读入，因此必须先停容器再放文件——运行中放进去不会生效，
        # 而且容器退出时可能用自己的内存状态覆盖它。
        compose stop falkordb > /dev/null
        compose exec -T falkordb sh -c "cat > '$fdir/$ffile'" < "$FROM_DIR/falkordb-dump.rdb" 2>/dev/null \
            || {
                # 容器已停，`compose exec` 不可用；改用 `compose cp` 把文件放进容器文件系统。
                # 但容器停了 `cp` 也不行，因此改为：起一个临时容器挂同一个卷写入。
                echo "      容器已停，改用临时容器写入卷"
                compose run --rm --no-deps --entrypoint sh falkordb -c \
                    "cat > '$fdir/$ffile'" < "$FROM_DIR/falkordb-dump.rdb"
            }
        compose start falkordb > /dev/null
        echo "      完成并已重启"
    fi
fi

# --- Redis --------------------------------------------------------------

if [ "$ONLY" = "" ] || [ "$ONLY" = "redis" ]; then
    if [ ! -f "$FROM_DIR/redis-dump.rdb" ]; then
        echo "警告：缺少 $FROM_DIR/redis-dump.rdb，跳过 Redis" >&2
    else
        echo "[3/3] Redis：写入 RDB 并重启"
        preflight_ping Redis "$(redis_cli PING 2>&1 | tr -d '\r' | tail -n 1)"
        rdir="$(read_config_value "Redis 的 CONFIG GET dir" "$(redis_cli CONFIG GET dir)")" || exit 2
        rfile="$(read_config_value "Redis 的 CONFIG GET dbfilename" "$(redis_cli CONFIG GET dbfilename)")" || exit 2
        compose stop redis > /dev/null
        compose run --rm --no-deps --entrypoint sh redis -c "cat > '$rdir/$rfile'" < "$FROM_DIR/redis-dump.rdb"
        compose start redis > /dev/null
        echo "      完成并已重启"
    fi
fi

# --- 收尾提示 -----------------------------------------------------------

cat <<EOF

恢复完成。

⚠️ 接下来必须做（不要跳过）：

  1. **跑迁移到最新**——备份来自旧版本 schema，代码是新版本的：
       docker compose -f $COMPOSE_FILE${ENV_FILE:+ --env-file $ENV_FILE} run --rm api alembic upgrade head

  2. **启动应用并验证就绪**（用 /readyz，不要用 /livez）：
       docker compose -f $COMPOSE_FILE${ENV_FILE:+ --env-file $ENV_FILE} up -d
       curl -fsS http://<目标>/readyz

  3. **抽查业务数据**——「恢复命令没报错」不等于「数据回来了」。
     至少核对：账号数、支持对象数、资料条目数、以及一条会话能否打开。

  4. 记录本次恢复：时间、来源备份目录、执行人。恢复演练的价值在于可追溯。
EOF
